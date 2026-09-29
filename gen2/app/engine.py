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
operation, status and health, the supervisor's incident list and the
operator's recovery of a stalled job — runs there, one at a time, in arrival
order; the listener's request threads only wait for their answer. The
service (gen2/operator/service.py) decides every answer and writes its bytes
(OperatorService.encode: the answer's text checked for credentials as it is
written; Astra 1e-repair-2 re-review finding 1); this module only moves
them. Nothing it logs or answers repeats the request's own text: a
fault behind the service is logged by its type and the service's labels, the
parser's own refusals are fixed replies, a connection fault is one line
naming its type (Astra 1e review finding 3); and a body answered unread is
discarded only within fixed bounds (_discard; finding 8).

What is not here: TLS (the listener is published on host loopback only),
and a scheduler loop driving the supervisor (Phase 2: until then the
supervisor advances only when the composition root or an operator's
recover_incident drives it). `POST /mcp`
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
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from gen2.app.station import Station, StationRefused, open_station
from gen2.operator.auth import Credentials, CredentialsRefused
from gen2.operator.service import COMMANDS, OperatorService, label
from gen2.router.service import utc_now

ANSWER_TIMEOUT_S = 60.0
DRAIN_MAX = 64 * 1024  # the most of an unread body the listener discards after its answer
DRAIN_IDLE_S = 1.0     # ... waiting at most this long for each next byte
DRAIN_TOTAL_S = 2.0    # ... and this long in all
# The parser's own refusals (http.server calls send_error): each a fixed answer, repeating nothing of the request
PARSER_REFUSALS = {400: "bad_request", 414: "uri_too_long", 431: "headers_too_large", 501: "method_not_supported", 505: "version_not_supported"}


class _Owned:
    """The station as the operator service sees it: only the operations its
    routes call (core.control.OperatorBackend's, the COMMANDS table's) — the
    router's, and the supervisor's recovery of a stalled job (STATION) — each
    run on the owner thread and its answer returned here; and the station's
    capability probe (task 1f), whose runner runs on the caller's thread,
    holding nothing of the router's, and whose observation is recorded on
    the owner thread: so two probes run their runners at once. Nothing else
    of the router or the supervisor — the store least of all — is reachable
    through it."""

    OPERATIONS = frozenset(COMMANDS) | {"status", "healthy"}
    STATION = frozenset({"recover_incident"})  # the supervisor's; every other operation is the router's

    def __init__(self, owner: ThreadPoolExecutor, station: Station) -> None:
        self._owner, self._station = owner, station

    def __getattr__(self, name: str):
        if name not in self.OPERATIONS:
            raise AttributeError(f"{name} is not an operation of the operator surface")
        if name == "probe_capability":
            record = self._station.router.record_capability_probe
            return lambda request: self._station.probe.run(
                request, record=lambda observation: self._owner.submit(record, observation).result(timeout=ANSWER_TIMEOUT_S))
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
            self._server = _Server(listen, _handler(self.service, self.log), self.log)
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


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, listen: tuple[str, int], handler, log: Callable[[str], None]) -> None:
        self._diagnostic = log
        super().__init__(listen, handler)

    def handle_error(self, request, client_address) -> None:
        """A connection that failed outside the service (a client gone
        mid-answer): one line naming the fault's type, never the traceback
        socketserver would print, whose text may carry the request's."""
        self._diagnostic(f"- ? ? -> connection {sys.exc_info()[0].__name__}")


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
                raw = service.encode(reply)
            except Exception as exc:  # a fault behind the service (auth.Unwritable included): answered, logged by type and the service's labels, never with the request
                log("- {} {} -> 500 {}".format(*label(self.command, self.path), type(exc).__name__))
                code, raw = 500, service.encode({"status": "error", "reason": "internal"})
            self._write(code, raw)
            self._discard(length, consumed)

        def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
            """The parser's refusal — a malformed request line or header, a
            method no route serves, a URI or header too long — answered with a
            fixed reply (PARSER_REFUSALS) and logged as one fixed line. The
            inherited answer repeats the request's own text in its reason
            phrase and page (Astra 1e review finding 3); nothing of it is
            repeated here, and the connection closes."""
            self.close_connection = True
            log(f"- ? ? -> {code} refused")
            self._write(code, service.encode({"status": "refused", "reason": PARSER_REFUSALS.get(code, "bad_request")}), close=True)

        def _write(self, code: int, raw: bytes, *, close: bool = False) -> None:
            self.send_response(code)  # the standard reason phrase for the code, never a message
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            if code == 401:
                self.send_header("WWW-Authenticate", 'Bearer realm="gen2-engine"')
            if close:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)
            self.wfile.flush()

        def _discard(self, length: str | None, consumed: int) -> None:
            """After the answer, the rest of a declared body the service never
            read (a refusal before it: 401, 403, 404, 413) is read and thrown
            away, unparsed — only if it is at most DRAIN_MAX bytes, and only
            while each next byte comes within DRAIN_IDLE_S and the whole within
            DRAIN_TOTAL_S. The service has refused before parsing, and nothing
            read here is looked at. Its purpose: a connection closed with
            unread bytes is reset by the kernel, so a client still sending a
            small body would lose the answer it was already sent (Astra 1e
            review finding 8). A larger remainder, or a client too slow, is
            not waited for: the connection is closed, and such a client may
            see its send fail after the answer was sent."""
            remaining = int(length) - consumed if length is not None and length.isascii() and length.isdigit() else 0
            if not 0 < remaining <= DRAIN_MAX:
                return
            deadline = time.monotonic() + DRAIN_TOTAL_S
            try:
                while remaining > 0 and (left := deadline - time.monotonic()) > 0:
                    self.connection.settimeout(min(DRAIN_IDLE_S, left))
                    data = self.rfile.read1(remaining)
                    if not data:
                        return
                    remaining -= len(data)
            except OSError:  # a timeout or a reset: stop discarding
                pass

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - the service logs each request itself; this would add the raw request line
            pass
    return Handler


def main(argv: list[str] | None = None, environ=os.environ) -> int:
    """`python -m gen2.app.engine --root DIR --station-id S --host-id H
    [--bundle FILE] [--create] [--auth-root DIR]`: serve until interrupted.
    --auth-root holds one auth home per provider (<DIR>/<provider>,
    DEPLOYMENT-CONTRACT.md §4), which probe_capability probes. Secrets and the
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
    parser.add_argument("--auth-root", help="the mounted auth homes, one per provider (task 1f)")
    args = parser.parse_args(argv)
    host, _, port = environ.get("GEN2_OPERATOR_LISTEN", "0.0.0.0:8770").rpartition(":")
    try:
        credentials = Credentials.from_environ(environ)
        bundle = None if args.bundle is None else json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        engine = Engine(lambda: open_station(args.root, station_id=args.station_id, host_id=args.host_id, clock=utc_now,
                                             config_bundle=bundle, create=args.create, auth_root=args.auth_root), credentials,
                        listen=(host, int(port)))
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
