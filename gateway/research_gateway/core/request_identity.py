"""The complete effective request, and its identity (task 2b; INVARIANTS H-5; design review §9).

A request's identity is the hash of what the gateway EXECUTES for it: every field the
router and executor read, with the executor's own defaults applied — kind, filters,
limit, cursor/page, domain as resolved, the commercial posture. Two requests that
differ in anything the gateway acts on never share an identity (the defect this fixes:
two searches differing in kind and cursor produced one activity key); two spellings of
the same request (an explicit default, an unknown domain that resolves to `other`)
share one. Tracing (iteration, topic, batch entry, invocation, attempt), scheduling
(priority, timeout) and the topic binding (topic_id: who asks, not what) are never part
of it.

The identity is "sha256:" + SHA-256 over the effective request serialized as JSON with
sorted keys and no whitespace (the gateway's own scheme, `gw-request/1`). The engine
keeps its own RFC 8785 hash of the request document it records; the two are carried
side by side, never assumed equal.
"""
from __future__ import annotations

import hashlib
import json

from ..registry.load import DOMAINS

SCHEME = "gw-request/1"
DEFAULT_LIMIT = 20   # the executor's default page size (router._call_find, catalog)


def _domain(value) -> str:
    return value if value in DOMAINS else "other"


def effective_request(payload: dict) -> dict:
    """The request as the gateway executes it. `payload` is a validated front-door payload
    (app.validate_payload) with `request_type` set."""
    rt = payload.get("request_type")
    out: dict = {"request_type": rt, "domain": _domain(payload.get("domain")),
                 "commercial": bool(payload.get("commercial")), "accept_per_item": bool(payload.get("accept_per_item"))}
    if rt == "find":
        out.update(query=payload.get("query") or "", kind=payload.get("kind"), limit=payload.get("limit") or DEFAULT_LIMIT,
                   year_from=payload.get("year_from"), published_after=payload.get("published_after"),
                   cursors=dict(payload.get("cursors") or {}), lanes=sorted(payload["lanes"]) if payload.get("lanes") else None)
    elif rt in ("resolve", "enrich"):
        out.update(identity=payload.get("identity"), what=payload.get("what") if rt == "enrich" else None)
    elif rt == "fetch":
        out.update(target=payload.get("target"), params=dict(payload.get("params") or {}))
    elif rt == "data":
        out.update(source=payload.get("source"), params=dict(payload.get("params") or {}))
    elif rt == "catalog":
        out.update(source=payload.get("source"), query=payload.get("query"), within=payload.get("within"),
                   cursor=payload.get("cursor"), limit=payload.get("limit") or DEFAULT_LIMIT)
    return out


def identity_of(effective: dict) -> str:
    text = json.dumps(effective, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_identity(payload: dict) -> str:
    return identity_of(effective_request(payload))
