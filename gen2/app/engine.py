"""The engine's operator listener (task 1e): the station, the operator command
service over its router, and the HTTP transport that carries the service.

Trace: gen2/boundaries.toml modules.app (the composition root: hands the
router's protocol to the operator; no domain logic) — amended by task 1e to
grant the listener (`http.server`) and the CLI's client (`http.client`, in
cli.py), the transport the brief places here; DEPLOYMENT-CONTRACT.md §1.1
(the engine's listener: GEN2_OPERATOR_LISTEN inside its container, published
on host loopback only; bearer tokens), §1.2 (GET /v1/health), §2 (restart,
not rebuild: the same volumes and the same mounted secrets), §3.1 (env
secrets); INVARIANTS C-1 (one writer), RG-9 (restart and replacement
preserve pins, auth-volume access and permissions).

One thread owns the router. The store's SQLite connection belongs to the
thread that opened it, and the router is one writer, so the station is
opened on a single worker thread and every call into it — each request's
operation, status and health, the supervisor's incident list — runs there,
one at a time, in arrival order; the listener's request threads only wait
for their answer. The service (gen2/operator/service.py) decides every
answer; this module only moves bytes and never logs a header.

What is not here: TLS (the listener is published on host loopback only),
and a scheduler loop driving the supervisor (Phase 2). `POST /mcp`
(DEPLOYMENT-CONTRACT.md §1.1) is a route of the same service, not a
transport of its own.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from gen2.app.station import Station, StationRefused, open_station
from gen2.operator.auth import Credentials, CredentialsRefused
from gen2.operator.service import COMMANDS, OperatorService
from gen2.router.service import utc_now

ANSWER_TIMEOUT_S = 60.0
DRAIN_MAX = 64 * 1024


class _Owned:
    """The station as the operator service sees it: only the operations its
    routes call (core.control.OperatorBackend's, the COMMANDS table's) — the
    router's, and the supervisor's recovery of a stalled job (STATION) — each
    run on the owner thread and its answer returned here. Nothing else of the
    router or the supervisor — the store least of all — is reachable through
    it."""

    OPERATIONS = frozenset(COMMANDS) | {"status", "healthy"}
    STATION = frozenset({"recover_incident"})  # the supervisor's; every other operation is the router's

    def __init__(self, owner: ThreadPoolExecutor, station: Station) -> None:
        self._owner, self._station = owner, station

    def __getattr__(self, name: str):
        if name not in self.OPERATIONS:
            raise AttributeError(f"{name} is not an operation of the operator surface")
        method = getattr(self._station.supervisor if name in self.STATION else self._station.router, name)
        return lambda *args: self._owner.submit(method, *args).result(timeout=ANSWER_TIMEOUT_S)


class Engine:
    def __init__(self, opener: Callable[[], Station], credentials: Credentials, *, listen: tuple[str, int] = ("127.0.0.1", 0),
                 log: Callable[[str], None] | None = None) -> None:
        self._owner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gen2-router")
        try:
            self.station = self._owner.submit(opener).result()
        except BaseException:
            self._owner.shutdown()
            raise
        self.log = log or (lambda line: print(line, file=sys.stderr, flush=True))
        supervisor = self.station.supervisor
        self.service = OperatorService(_Owned(self._owner, self.station), credentials,
                                       incidents=lambda: self._owner.submit(supervisor.incidents).result(timeout=ANSWER_TIMEOUT_S), log=self.log)
        try:
            self._server = http.server.ThreadingHTTPServer(listen, _handler(self.service, self.log))
        except BaseException:
            self._owner.submit(self.station.close).result()
            self._owner.shutdown()
            raise
        self._thread = threading.Thread(target=self._server.serve_forever, name="gen2-listener", daemon=True)
        self._thread.start()

    @property
    def address(self) -> tuple[str, int]:
        return self._server.server_address[:2]

    def call(self, fn: Callable[[Station], object]) -> object:
        """Run fn(station) on the owner thread (the composition root's own
        wiring; tests use it to act as the in-process supervisor would)."""
        return self._owner.submit(fn, self.station).result(timeout=ANSWER_TIMEOUT_S)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        try:
            self._owner.submit(self.station.close).result()
        finally:
            self._owner.shutdown()


def _handler(service: OperatorService, log: Callable[[str], None]):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "gen2-engine"
        sys_version = ""
        timeout = 30  # a client that stops sending is dropped, never waited on

        def do_GET(self) -> None:
            self._serve()

        def do_POST(self) -> None:
            self._serve()

        def _serve(self) -> None:
            consumed = 0

            def read(size: int) -> bytes:
                nonlocal consumed
                data = self.rfile.read(size)
                consumed += len(data)
                return data
            length = self.headers.get("Content-Length")
            try:
                code, reply = service.handle(self.command, self.path, self.headers.get("Authorization"), length, read)
            except Exception as exc:  # a fault behind the service: answered, logged by type only, never with the request
                log(f"- {self.command} {self.path.partition('?')[0]} -> 500 {type(exc).__name__}")
                code, reply = 500, {"status": "error", "reason": "internal"}
            raw = json.dumps(reply, sort_keys=True).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            if code == 401:
                self.send_header("WWW-Authenticate", 'Bearer realm="gen2-engine"')
            self.end_headers()
            self.wfile.write(raw)
            self.wfile.flush()
            self._discard(length, consumed)

        def _discard(self, length: str | None, consumed: int) -> None:
            """After the answer, the rest of a small declared body the service
            never read (a refusal before it: 401, 403, 404) is read and thrown
            away, unparsed, so the connection closes cleanly: closing with
            unread bytes makes the kernel reset it, and a client still sending
            loses the answer. A larger remainder is not waited for."""
            remaining = int(length) - consumed if length is not None and length.isascii() and length.isdigit() else 0
            if 0 < remaining <= DRAIN_MAX:
                try:
                    self.connection.settimeout(1.0)
                    self.rfile.read(remaining)
                except OSError:
                    pass

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - the service logs each request itself; this would add the raw request line
            pass
    return Handler


def main(argv: list[str] | None = None, environ=os.environ) -> int:
    """`python -m gen2.app.engine --root DIR --station-id S --host-id H
    [--bundle FILE] [--create]`: serve until interrupted. Secrets and the
    listen address come from the deployment contract's environment names
    (GEN2_SECRETS, GEN2_OPERATOR_TOKENS, GEN2_SECRET_EXPORTER_TOKEN,
    GEN2_OPERATOR_LISTEN); the state directory holds the store, the spool and
    the jobs (gen2/app/station.py). Prints `listening on HOST:PORT` once
    serving. Exit 1 if the credentials or the config bundle are refused."""
    parser = argparse.ArgumentParser(prog="python -m gen2.app.engine")
    parser.add_argument("--root", required=True)
    parser.add_argument("--station-id", required=True)
    parser.add_argument("--host-id", required=True)
    parser.add_argument("--bundle", help="the mounted config-bundle/1 file; without it, the active bundle is restored")
    parser.add_argument("--create", action="store_true", help="create the store (first start only)")
    args = parser.parse_args(argv)
    host, _, port = environ.get("GEN2_OPERATOR_LISTEN", "0.0.0.0:8770").rpartition(":")
    try:
        credentials = Credentials.from_environ(environ)
        bundle = None if args.bundle is None else json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        engine = Engine(lambda: open_station(args.root, station_id=args.station_id, host_id=args.host_id, clock=utc_now,
                                             config_bundle=bundle, create=args.create), credentials, listen=(host, int(port)))
    except (CredentialsRefused, StationRefused, ValueError, OSError) as refused:  # never a token in any of these messages
        print(f"gen2 engine refused to start: {refused}", file=sys.stderr, flush=True)
        return 1
    engine.log("principals: " + ", ".join(f"{p.role}:{p.name}" for p in credentials.principals))
    print(f"listening on {engine.address[0]}:{engine.address[1]}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
