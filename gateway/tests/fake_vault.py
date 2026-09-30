"""A loopback HashiCorp Vault KV v2 server for the DEPLOYMENT-CONTRACT §3.4 fixtures.

It answers GET /v1/<mount>/data/<prefix>/<name> the way Vault's KV v2 engine does:
200 {"data": {"data": {...}, "metadata": {...}}} for a stored secret; 404
{"errors": []} for a path with nothing stored under an existing mount; 404
{"errors": ["no handler for route ..."]} when the mount itself does not exist (the
misconfigured-mount case). `mode` makes every read fail another way — a status
(403, 500, 503), a redirect, an unparseable body, a stall past the client's
timeout —, `ok_status` sends a stored secret's valid body under another status, and `fail_from` (an epoch second, compared against `clock()`) switches
every read to 403 from a fixed time (the outage replay). Every request is kept in
`requests` as (path, token) so a test can prove what was, and was not, asked.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeVault:
    def __init__(self, *, mount: str = "secret", prefix: str = "services", secrets: dict | None = None,
                 clock=time.time):
        self.mount, self.prefix, self.clock = mount, prefix, clock
        self.secrets = dict(secrets or {})
        self.mode: str = "ok"            # ok | status:<code> | redirect:<code>:<url> | unparseable | stall:<seconds> | shapeless
        self.ok_status = 200             # the status a stored secret's (otherwise identical) answer carries
        self.fail_from: float | None = None
        self.requests: list[tuple[str, str | None]] = []
        vault = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status: int, body: bytes, headers: dict | None = None) -> None:
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                vault.requests.append((self.path, self.headers.get("X-Vault-Token")))
                vault.answer(self)

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass   # a client that timed out and hung up mid-answer is the fixture, not an error

        self._server = Server(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def answer(self, h) -> None:
        mode = self.mode
        if self.fail_from is not None and self.clock() >= self.fail_from:
            mode = "status:403"
        if mode.startswith("status:"):
            code = int(mode.split(":")[1])
            return h._send(code, json.dumps({"errors": ["permission denied" if code == 403 else "internal error"]}).encode())
        if mode.startswith("redirect:"):
            _, code, target = mode.split(":", 2)
            return h._send(int(code), b"", {"Location": target + h.path})
        if mode == "unparseable":
            return h._send(200, b"<html>not a vault answer</html>", {"Content-Type": "text/html"})
        if mode == "shapeless":
            return h._send(200, json.dumps({"warnings": None}).encode(), {"Content-Type": "application/json"})
        if mode.startswith("stall:"):
            time.sleep(float(mode.split(":")[1]))
        parts = h.path.split("?")[0].strip("/").split("/")
        # v1 / <mount> / data / <prefix> / <name>
        if len(parts) < 3 or parts[0] != "v1" or parts[1] != self.mount or parts[2] != "data":
            route = "/".join(parts[1:])
            return h._send(404, json.dumps({"errors": [f'no handler for route "{route}". route entry not found.']}).encode(),
                           {"Content-Type": "application/json"})
        name = "/".join(parts[3:])
        if not name.startswith(self.prefix + "/") or name[len(self.prefix) + 1:] not in self.secrets:
            return h._send(404, json.dumps({"errors": []}).encode(), {"Content-Type": "application/json"})
        data = self.secrets[name[len(self.prefix) + 1:]]
        body = {"request_id": "r", "data": {"data": data, "metadata": {"version": 1, "deletion_time": ""}}}
        h._send(self.ok_status, json.dumps(body).encode(), {"Content-Type": "application/json"})
