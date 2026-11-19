"""V7 §5: finite offline HTTP fixtures, never synthetic runner events or ACKs."""
import hashlib
import json
import re
import ssl
import sys
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

SOURCE = b'{"records":[{"id":"q1","title":"2e1 fixture"}],"total":1}\n'
COMMAND = "python3 /inputs/tool_probe.py"
TOOLS_SHA = "b7bde2c6481df2ab8cb4b3fec1abff18b48630540c05840137d643568560aadb"


def tool_schema(request, enabled=False):
    inputs = request.get("input", [])
    if "tools" in request or not isinstance(inputs, list) or any(not isinstance(x, dict) for x in inputs):
        raise ValueError("tool envelope")
    schemas = [x for x in inputs if x.get("type") == "additional_tools"]
    if not enabled:
        if schemas:
            raise ValueError("tool-less request required")
    elif len(schemas) != 1 or schemas[0].get("role") != "developer" or hashlib.sha256(
            json.dumps(schemas[0].get("tools"), sort_keys=True, separators=(",", ":")).encode()).hexdigest() != TOOLS_SHA:
        raise ValueError("advertised tools differ")


def credential(case):
    return "accepted" if case in {"tool-less", "hold", "hold-first"} else case


def response(case, ordinal, request, *, subscription=False):
    case = {"hold": "accepted", "hold-first": "tool-less"}.get(case, case)
    if request.get("model") != "gpt-6.1-terra" or request.get("stream") is not True or (subscription and case == "accepted"):
        raise ValueError("model/stream/subscription policy")
    if subscription or case in {"accepted", "tool-less"}:
        tool_schema(request, case == "accepted")
    if case == "limited" and ordinal == 1:
        return 429, "application/json", b'{"error":{"type":"usage_limit_reached","resets_at":253402300799}}\n'
    if case == "rejected" and ordinal == 1:
        return 401, "application/json", b'{"error":{"message":"fixture credential rejected","type":"invalid_api_key"}}\n'
    if case not in {"accepted", "tool-less"} or ordinal not in ((1, 2) if case == "accepted" else (1,)):
        raise ValueError("extra send")
    if ordinal == 1 and case == "accepted":
        item = dict(type="custom_tool_call", id="fc_2e1", call_id="call_2e1", name="exec",
                    input='// @exec: {"yield_time_ms": 30000, "max_output_tokens": 10000}\n'
                    f'text(await tools.exec_command({json.dumps(dict(cmd=COMMAND, yield_time_ms=30000, max_output_tokens=8000))}));')
    else:
        if case == "accepted":
            outputs = [x for x in request.get("input", []) if x.get("type", "").endswith("_call_output")]
            if len(outputs) != 1 or outputs[0].get("type") != "custom_tool_call_output" or outputs[0].get("call_id") != "call_2e1":
                raise ValueError("tool continuation")
            content = outputs[0].get("output")
            if not isinstance(content, list) or len(content) != 2 or any(not isinstance(x, dict) for x in content):
                raise ValueError("tool output envelope")
            header, result = content
            if any(x.get("type") != "input_text" for x in (header, result)) or not re.fullmatch(r"Script completed\nWall time \d+\.\d seconds\nOutput:\n", header.get("text", "")):
                raise ValueError("incomplete code cell")
            result = json.loads(result["text"])
            if not isinstance(result, dict) or not isinstance(result.get("output"), str) or type(result.get("exit_code")) is not int or result["exit_code"] != 0 or "session_id" in result or "2e1-tool-ok" not in result.get("output", ""):
                raise ValueError("probe execution")
        item = dict(type="message", id="msg_2e1", role="assistant", status="completed",
                    content=[{"type": "output_text", "text": "2e1 complete", "annotations": []}])
    events = [{"type": "response.output_item.done", "output_index": 0, "item": item},
              {"type": "response.completed", "response": {"id": f"resp_2e1_{ordinal}", "status": "completed",
               "output": [item], "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}}]
    data = "".join("event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events)
    return 200, "text/event-stream", data.encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass  # ordinary HTTP diagnostics must not leak Authorization or request bodies

    def handle_one_request(self):
        self.connection.settimeout(2)
        super().handle_one_request()

    def do_GET(self):
        self.exchange()

    def do_POST(self):
        self.exchange()

    def exchange(self):
        self.server.count += 1
        raw, request, status, media, data = b"", {}, 400, "application/json", b'{}\n'
        rid = self.headers.get("X-Request-ID", "")
        try:
            if time.monotonic() >= self.server.deadline or self.server.count > 64:
                raise ValueError("fixture window/count")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 1 << 20 or self.headers.get("Transfer-Encoding"):
                raise ValueError("framing")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("short request")
            if self.server.case == "source":
                if self.command != "GET" or self.path != "/fixture" or raw or self.headers.get("Authorization"):
                    raise ValueError("source route")
                status, media, data = 200, "application/json", SOURCE
            else:
                subscription = isinstance(self.connection, ssl.SSLSocket) and self.path == "/backend-api/codex/responses"
                if self.command != "POST" or (self.path != "/v1/responses" and not subscription) or not re.fullmatch("[0-9a-f]{32}", rid):
                    raise ValueError("model route/id")
                expected = {"Authorization": "Bearer e30.eyJleHAiOjI1MzQwMjMwMDc5OX0.c2ln", "ChatGPT-Account-ID": "fixture-session", "originator": "codex_cli_rs", "version": "0.169.0", "Host": "chatgpt.com", "Content-Type": "application/json", "Accept": "text/event-stream"} if subscription else {"Authorization": "Bearer 2e1-fixture-" + credential(self.server.case)}
                if any(self.headers.get_all(k) != [v] for k, v in expected.items()):
                    raise ValueError("dummy credential/headers")
                if subscription and {k.lower() for k in self.headers} - ({k.lower() for k in expected} | {"content-length", "x-request-id"}):
                    raise ValueError("unexpected subscription header")
                request = json.loads(raw) if raw.lstrip().startswith(b"{") else {}
                status, media, data = response(self.server.case, self.server.count, request, subscription=subscription)
        finally:
            record = dict(ordinal=self.server.count, id=rid, method=self.command, route=self.path[:128],
                          model=request.get("model"), status=status, case=self.server.case,
                          request_sha256=hashlib.sha256(raw).hexdigest(), request_bytes=len(raw), request=request)
            line = json.dumps(record) + "\n"
            if self.server.raw.tell() + len(line.encode()) > 1 << 20:
                raise ValueError("fixture record bound")
            self.server.raw.write(line)
            self.server.raw.flush()
            self.server.requests.append(dict(id=rid, route=self.path[:128], model=request.get("model"),
                                            credential=credential(self.server.case) if self.headers.get("Authorization") == "Bearer 2e1-fixture-" + credential(self.server.case) else "unknown"))
            self.server.record.seek(0)
            json.dump({"v": 1, "requests": self.server.requests}, self.server.record)
            self.server.record.truncate()
            self.server.record.flush()
        ticks = self.server.hold_seconds if status == 200 and (self.server.case, self.server.count) in {("hold", 2), ("hold-first", 1)} else 0
        keepalive = b'event: response.in_progress\ndata: {"type":"response.in_progress"}\n\n'
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(data) + ticks * len(keepalive)))
        self.send_header("Connection", "close")
        self.end_headers()
        for _ in range(ticks):
            self.wfile.write(keepalive)
            self.wfile.flush()
            time.sleep(1)
        self.wfile.write(data)
        self.close_connection = True


def operands(argv):
    case = argv[1]
    hold_seconds = int(argv[2]) if case in {"hold", "hold-first"} else 0
    if case in {"hold", "hold-first"} and not 1 <= hold_seconds <= 300:
        raise ValueError("finite hold required")
    lifetime = int(argv[3 if hold_seconds else 2]) if len(argv) > (3 if hold_seconds else 2) else 1800
    if not (hold_seconds + 60 if hold_seconds else 1) <= lifetime <= 1800:
        raise ValueError("fixture lifetime")
    return case, hold_seconds, lifetime


if __name__ == "__main__":
    case, hold_seconds, lifetime = operands(sys.argv)
    tls = Path("/certs").is_dir()
    address = ("172.31.251.3", 18081) if case == "source" else ("172.31.252.3", 443 if tls else 8081)
    if case not in {"source", "accepted", "rejected", "tool-less", "hold", "hold-first", "limited"}:
        raise ValueError("fixture case")
    with HTTPServer(address, Handler) as server, open("/evidence/fixture.json", "x+") as record, open("/evidence/raw.jsonl", "x") as raw:
        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain("/certs/cert.pem", "/certs/key.pem")
            server.socket = context.wrap_socket(server.socket, server_side=True)
        server.case, server.record, server.count = case, record, 0
        server.hold_seconds = hold_seconds
        server.raw, server.requests = raw, []
        server.deadline, server.timeout = time.monotonic() + lifetime, 1
        while time.monotonic() < server.deadline and server.count < 64:
            server.handle_request()
