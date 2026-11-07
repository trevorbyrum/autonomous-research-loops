"""A canned gateway behind the real GatewayClient's transport hook, for the offline whole-workflow run (2e2-min T18, O18.2).

Not collected as tests. It answers the client's own requests (grant, find) with adapter-shaped lane answers: the
`semanticscholar` lane carries canonical records WITH an abstract, the `crossref` lane the same works bibliographically
(no abstract), as the real adapters do (T12-G). Echoes the invocation and attempt from the request headers, numbers the
captured calls, and can be told how a counterevidence search goes: `empty` (read, found nothing), `found` (a contrary
record), `degraded` (no answer at all, so the client's unknown observation). Limits: it is a finite script, not a
model of the gateway; it checks only that the client sent what it needs to answer, and it speaks plain HTTP shapes, never
raw sockets. Named lanes are the two the real gateway has; arXiv is not a gateway lane.
"""
from __future__ import annotations

import hashlib
import json

from gen2.core import canonical

HEADERS = {"content-type": "application/json", "x-research-gateway": "result"}
WORKS = {
    "doi:10.1/offline-a": ("Sleep timing and attention in adolescents", "Adolescents who slept under seven hours scored lower on a sustained attention task in this cohort of 412."),
    "doi:10.1/offline-b": ("School start times and alertness", "Later school start times were followed by higher self-reported alertness in a pooled sample of 3,000 students."),
    "doi:10.1/offline-c": ("A null result on sleep restriction and attention", "Two nights of restricted sleep produced no measurable change in attention in 60 adolescents."),
}
QUERY_WORKS = {"main": ("doi:10.1/offline-a", "doi:10.1/offline-b"), "found": ("doi:10.1/offline-c",), "empty": ()}


def record(identity: str, lane: str, abstract: bool) -> dict:
    title, text = WORKS[identity]
    return {"identity": identity, "kind": "article", "source_id": lane, "title": title, "authors": [], "year": 2024, "venue": None,
            "identifiers": {"doi": identity.split(":", 1)[1]}, "links": [], "license": None, "attribution": lane,
            "retrieved_at": "2026-11-07T00:00:00Z", "redistributable": False, **({"abstract": text} if abstract else {})}


class OfflineGateway:
    def __init__(self, *, counter: str = "empty", abstracts: bool = True) -> None:
        if counter not in ("empty", "found", "degraded"):
            raise ValueError(counter)
        self.counter, self.abstracts, self.calls, self._calls = counter, abstracts, [], 0

    def which(self, sent: dict) -> str:
        return "main" if "counterevidence" not in sent.get("query", "") else ("empty" if self.counter == "degraded" else self.counter)

    def __call__(self, method, url, headers, body, timeout):
        path = url.split("/v1/", 1)[1]
        sent = canonical.parse_json_strict(body) if body else {}
        self.calls.append((path, sent))
        if path == "grants":
            return 201, HEADERS, json.dumps({"token": "gwg1.offline"}).encode(), None
        if path != "find":
            return 404, HEADERS, b"{}", None
        if self.counter == "degraded" and "counterevidence" in sent.get("query", ""):
            return None, {}, b"", "timeout"
        self._calls += 1
        lane = sent["lanes"][0]
        # the real gateway's call refs are unique across invocations: so are these (a per-invocation base), or the retained exchanges of two jobs would share a name
        base = int(hashlib.sha256(headers["X-Research-Invocation"].encode()).hexdigest()[:6], 16) * 100
        identities = QUERY_WORKS[self.which(sent)]
        records = [record(i, lane, self.abstracts and lane == "semanticscholar") for i in identities]
        entry = {"source": lane, "coverage": "searched_ok" if records else "searched_empty", "completeness": "complete",
                 "count": len(records), "retrieved": list(identities), "exhausted": True}
        answer = {"observation": {"invocation_id": headers["X-Research-Invocation"], "attempt": int(headers["X-Research-Attempt"]),
                                  "captured": True, "call_ref": base + self._calls},
                  "lanes": [entry], "records": records}
        return 200, HEADERS, json.dumps(answer).encode(), None
