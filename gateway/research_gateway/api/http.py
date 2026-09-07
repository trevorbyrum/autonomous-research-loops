"""HTTP front door (PLAN.md §9): stdlib server, bearer token per client.

  GET  /v1/health              no auth; polled by monitors
  GET  /v1/status              broker, cache, workers, job counts
  GET  /v1/jobs/{id}           a queued job's state and (redacted) result
  POST /v1/{find|resolve|enrich|fetch|data}
       body: JSON payload (query/identity/target/params, kind, domain, commercial, ...)
       ?async=1 → {job_id} immediately; otherwise waits up to `timeout` (≤ 120 s)
       fetch with params.download=true streams the bytes back; nothing is stored (D-17)
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from ..app import Gateway, Settings, load_settings
from ..core.queue import REQUEST_TYPES
from ..mcp import homelab_adapter

MAX_TIMEOUT = 120.0
MAX_BODY = 1 << 20


class Handler(BaseHTTPRequestHandler):
    server_version = "research-gateway/0.1"
    gateway: Gateway  # set on the server object

    # ------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):  # one line per request, to stderr, never the body
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body, content_type: str = "application/json") -> None:
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _client(self) -> str | None:
        name = self.server.gateway.authenticate(self.headers.get("Authorization"))
        if name is None:
            self._send(401, {"error": "missing or invalid bearer token"})
        return name

    def _body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._send(413, {"error": "body too large"})
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            self._send(400, {"error": "body must be JSON"})
            return None
        if not isinstance(body, dict):
            self._send(400, {"error": "body must be a JSON object"})
            return None
        return body

    # ------------------------------------------------------------ routes
    def do_GET(self) -> None:
        path = urlsplit(self.path).path.rstrip("/")
        gw = self.server.gateway
        if path == "/v1/health":
            h = gw.health()
            return self._send(200 if h["ok"] else 503, h)
        if self._client() is None:
            return
        if path == "/v1/status":
            return self._send(200, gw.status())
        if path.startswith("/v1/jobs/"):
            if gw.conn is None:
                return self._send(404, {"error": "no queue: this gateway runs inline"})
            try:
                job = gw.job(int(path.rsplit("/", 1)[1]))
            except ValueError:
                return self._send(400, {"error": "job id must be an integer"})
            return self._send(200, job) if job else self._send(404, {"error": "no such job"})
        self._send(404, {"error": "no such route"})

    def do_POST(self) -> None:
        parts = urlsplit(self.path)
        rt = parts.path.rstrip("/").rsplit("/", 1)[-1]
        if parts.path.rstrip("/") == "/mcp":
            return self._mcp()
        if not parts.path.startswith("/v1/") or rt not in REQUEST_TYPES:
            return self._send(404, {"error": f"POST /v1/<{'|'.join(REQUEST_TYPES)}> or POST /mcp"})
        client = self._client()
        if client is None:
            return
        body = self._body()
        if body is None:
            return
        payload = {**body, "request_type": rt}
        gw = self.server.gateway
        query = parse_qs(parts.query)
        try:
            if query.get("async", ["0"])[0] in ("1", "true") and gw.conn is not None and not gw.is_inline_only(payload):
                job_id, created = gw.submit(payload, client, priority=str(body.get("priority") or "interactive"))
                return self._send(202, {"job_id": job_id, "created": created, "status": "queued"})
            timeout = min(float(body.get("timeout") or gw.settings.sync_timeout), MAX_TIMEOUT)
            out = gw.handle(payload, client, timeout=timeout, priority=str(body.get("priority") or "interactive"))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:  # the front door never dies on a request; the error is the answer
            return self._send(500, {"error": f"{type(e).__name__}: {e}"[:500]})
        if out.get("content") is not None:
            return self._send(200, out["content"], out.get("content_type") or "application/octet-stream")
        status = 202 if out.get("status") in ("queued", "running") else 200
        self._send(status, {k: v for k, v in out.items() if k != "content"})


    def _mcp(self) -> None:
        """Stateless MCP over HTTP for the homelab gateway: one JSON-RPC message per POST."""
        client = self._client()
        if client is None:
            return
        body = self._body()
        if body is None:
            return
        try:
            reply = homelab_adapter.rpc(self.server.gateway, client, body)
        except Exception as e:  # a broken tool call is an in-band JSON-RPC error, never a dead server
            reply = {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"[:500]}}
        if reply is None:
            return self._send(202, b"", "application/json")
        self._send(200, reply)


def serve(gateway: Gateway, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.gateway = gateway
    return server


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()
    if not settings.tokens:
        print("refusing to start without client tokens (RESEARCH_GATEWAY_TOKENS or the secrets backend)", file=sys.stderr)
        return 2
    gw = Gateway(settings)
    gw.start()
    server = serve(gw, settings.host, settings.port)
    print(f"research-gateway {gw.health()['version']} listening on {settings.host}:{server.server_port} "
          f"({'queued' if gw.conn is not None else 'inline'} mode, {len(settings.tokens)} client token(s))", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        gw.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
