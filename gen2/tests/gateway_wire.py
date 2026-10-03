"""What the gateway client's loopback tests put on the wire and read back (not collected as tests; no name from the client module is bound here).

The client module is the thing the mutation runner replaces, and it reloads only the test modules a mutant names, so nothing in this file imports it: a test module imports
`GatewayClient` itself, and everything here is the server's side of the exchange or an expectation written by hand.
"""
from __future__ import annotations

import json
import socket
import threading
from typing import Callable

from gen2.tests.loopback import Loopback

INV = "inv_discover1"
STAMP = "2026-09-27T10:00:00Z"
TOKEN = "synthetic-token"
CAPTURED = {"invocation_id": INV, "attempt": 1, "captured": True, "call_ref": 1}
FIND = {"request_type": "find", "query": "synthetic", "lanes": ["crossref"]}
EMPTY_LANE = {"source": "crossref", "coverage": "searched_empty", "completeness": "complete", "count": 0, "retrieved": [], "exhausted": True}
HEAD = ("HTTP/1.1 {}\r\nContent-Type: application/json\r\nX-Research-Gateway: result\r\n"
        "Content-Length: {}\r\nConnection: close\r\n\r\n")
EMPTY_AND_EXHAUSTED = ("searched_empty", "complete", 0, "exhausted", None)   # what a search answered by gateway_answer() observes (see `observed`)


def unobserved(error: str) -> tuple:
    """What a search that got no usable answer observes: unknown, unobserved, no count, a failed page, and why."""
    return "unknown", "unobserved", None, "failed", error


def job(status: str, lanes=None) -> bytes:
    return json.dumps({"status": status, "observation": CAPTURED, "result": {"lanes": lanes if lanes is not None else [], "records": []}},
                      separators=(",", ":")).encode()


def reply(body: bytes, status: str = "200 OK") -> bytes:
    return HEAD.format(status, len(body)).encode() + body


def gateway_answer() -> bytes:
    """What a gateway answers a find with when the lane was read and found nothing: `searched_empty`, complete, 0, exhausted."""
    return reply(json.dumps({"observation": CAPTURED, "lanes": [EMPTY_LANE], "records": []}, separators=(",", ":")).encode())


def queued_answer() -> bytes:
    return reply(json.dumps({"status": "queued", "job_id": 1, "observation": CAPTURED}, separators=(",", ":")).encode())


def lookup(*addresses: str, port: int = 0):
    """A resolver (getaddrinfo's signature) that finds these addresses for any name, and records each call it is given."""
    def find(host, called_port, *rest):
        find.calls.append((host, called_port))
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port or called_port)) for address in addresses]
    find.calls = []
    return find


def admitted(port: int, host: str = "127.0.0.1") -> list:
    """What an endpoint's owner admits for a loopback listener: getaddrinfo's one result, as the transport is handed it (written out here, not asked of the client's own `_Endpoint`)."""
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, port))]


def observed(out: dict) -> tuple:
    """(coverage, completeness, count, page outcome, error class) of the one observation of a one-lane search."""
    [only] = out["observations"]
    o = only["observation"]
    return o["coverage_state"], o["completeness"], o["result_count"], o["page_outcome"], o["error_class"]


class Recorder:
    """What a loopback listener was sent: every connection it accepted (a script runs once for each, after its request was read), the request line and headers, and the body."""

    def __init__(self, test, script: Callable | None = None, **kw) -> None:
        self.hits: list[tuple[bytes, bytes]] = []
        self._answer = script
        self._lock = threading.Lock()
        self.server: Loopback = test.serve(self._record, **kw)
        self.port = self.server.port

    def _record(self, server, conn, head, body) -> None:
        with self._lock:
            self.hits.append((head, body))
            index = len(self.hits)
        if self._answer is not None:
            self._answer(server, conn, head, body, index)

    @property
    def count(self) -> int:
        return len(self.hits)

    @property
    def request_lines(self) -> list[str]:
        return [head.split(b"\r\n")[0].decode() for head, _ in self.hits]

    def carrying(self, token: str = TOKEN) -> int:
        """How many of the requests carried this bearer token."""
        return sum(f"Authorization: Bearer {token}".encode() in head for head, _ in self.hits)


def paged_answer(page: int) -> bytes:
    """A lane that read one record and, on its first page, hands back a continuation (the cursor `c2`); its second page is the end."""
    lane = {"source": "crossref", "role": "base", "coverage": "searched_ok", "completeness": "complete", "count": 1, "retrieved": ["doi:10.1/a"],
            **({"next": "c2"} if page == 1 else {"exhausted": True})}
    return reply(json.dumps({"observation": CAPTURED, "lanes": [lane], "records": [{"identity": "doi:10.1/a", "source_id": "crossref"}]}, separators=(",", ":")).encode())


def gateway_script(*, poll: bool = False):
    """A Recorder script for a gateway that answers a find with an empty, exhausted lane; with `poll`, queues it and answers the first poll."""
    def script(server, conn, head, body, index):
        if head.startswith(b"POST /v1/grants"):
            server.send(conn, [(0, reply(json.dumps({"token": "gwg1.synthetic"}).encode(), "201 Created"))])
        elif poll and head.startswith(b"POST"):
            server.send(conn, [(0, queued_answer())])
        elif poll:
            server.send(conn, [(0, reply(job("done", [EMPTY_LANE])))])
        else:
            server.send(conn, [(0, gateway_answer())])
    return script
