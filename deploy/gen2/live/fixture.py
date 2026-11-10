"""V7 §5: finite offline HTTP fixtures, never synthetic runner events or ACKs."""
import hashlib
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

SOURCE = b'{"records":[{"id":"q1","title":"2e1 fixture"}],"total":1}\n'
COMMAND = "python3 /inputs/tool_probe.py"


def credential(case):
    return "accepted" if case == "tool-less" else case


def response(case, ordinal, request):
    if request.get("model") != "gpt-5.4" or request.get("stream") is not True:
        raise ValueError("model/stream")
    if case == "rejected" and ordinal == 1:
        return 401, "application/json", b'{"error":{"message":"fixture credential rejected","type":"invalid_api_key"}}\n'
    if case not in {"accepted", "tool-less"} or ordinal not in ((1, 2) if case == "accepted" else (1,)):
        raise ValueError("extra send")
    if ordinal == 1 and case == "accepted":
        if {t.get("name") for t in request.get("tools", [])} != {"exec_command", "write_stdin", "apply_patch"}:
            raise ValueError("advertised tools differ")
        item = dict(type="function_call", id="fc_2e1", call_id="call_2e1", name="exec_command",
                    arguments=json.dumps({"cmd": COMMAND, "max_output_tokens": 2000}))
    else:
        if case == "accepted":
            outputs = [x for x in request.get("input", []) if x.get("type") == "function_call_output"]
            if len(outputs) != 1 or outputs[0].get("call_id") != "call_2e1" or "2e1-tool-ok" not in str(outputs[0].get("output")):
                raise ValueError("tool continuation")
        elif request.get("tools", []) != []:
            raise ValueError("tool-less request required")
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
                if self.command != "POST" or self.path != "/v1/responses" or not re.fullmatch("[0-9a-f]{32}", rid):
                    raise ValueError("model route/id")
                if self.headers.get("Authorization") != "Bearer 2e1-fixture-" + credential(self.server.case):
                    raise ValueError("dummy credential")
                request = json.loads(raw) if raw.lstrip().startswith(b"{") else {}
                status, media, data = response(self.server.case, self.server.count, request)
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
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True


if __name__ == "__main__":
    case = sys.argv[1]
    address = ("172.31.251.3", 18081) if case == "source" else ("172.31.252.3", 8081)
    if case not in {"source", "accepted", "rejected", "tool-less"}:
        raise ValueError("fixture case")
    with HTTPServer(address, Handler) as server, open("/evidence/fixture.json", "x+") as record, open("/evidence/raw.jsonl", "x") as raw:
        server.case, server.record, server.count = case, record, 0
        server.raw, server.requests = raw, []
        server.deadline, server.timeout = time.monotonic() + 1800, 1
        while time.monotonic() < server.deadline and server.count < 64:
            server.handle_request()
