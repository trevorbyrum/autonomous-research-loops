"""The `discovery/search` recorder: the station's trusted step between the child's exit and the result's commit.

Trace: 2e2-min design O13.4; Astra T11 decision 3 and F2 (replayable recording, stable per-effect identities);
DEPLOYMENT-CONTRACT §4.1 and BOUNDARIES (two ACKs: the gateway's call-capture ACK proves gateway capture only; the router's
persistence ACK alone lets records go on to work registration, and its absence changes no stored coverage); INVARIANTS RG-4,
C-10. Oracle: the router's own replies (`recorded` or `replayed`); anything else raises, and the supervisor retries within its
write attempts. Limits: ids come from the client's observations (deterministic from invocation, attempt and request), so a repeat
after a crash adds nothing; it reads `discovery-result.json` as the child left it and trusts nothing in it the router does
not re-validate.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Callable, Mapping

from gen2.core import canonical
from gen2.discovery import child, exchanges
from gen2.exec.common import Refused
from gen2.gateway_client import observe

OK = ("recorded", "replayed")
SCHEMES = ("doi", "arxiv", "pmid", "isbn", "url")
DEDUP = "identity-only/1"
MAX_RESULT = 64 << 20


def work_identity(provider_record_id: str) -> tuple[str, str]:
    """(identity_scheme, identity_value) of a provider record id: `doi:10.1/a` is a doi; anything else is a gateway record."""
    scheme, _, value = provider_record_id.partition(":")
    return (scheme, value) if scheme in SCHEMES and value else ("gateway_record", provider_record_id)


def _result(scratch: Path | str) -> dict:
    path = Path(scratch) / child.RESULT
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise Refused(f"{child.RESULT} unreadable: {error.strerror}") from None
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode) or os.fstat(handle.fileno()).st_size > MAX_RESULT:
            raise Refused(f"{child.RESULT} is not a bounded regular file")
        return canonical.parse_json_strict(handle.read())


def _require(method: str, reply: Mapping) -> Mapping:
    if reply.get("status") not in OK:
        raise Refused(f"{method} was not acknowledged by the router: {reply.get('reason', reply.get('status'))}")
    return reply


def recorder(stage: exchanges.Stage) -> Callable:
    """The recorder for the station: `Supervisor(..., recorders={"discovery/search": discovery.recorder.recorder(spool.stage)})`."""
    def record(control, order: Mapping, grant: Mapping, scratch: Path | str) -> None:
        result = _result(scratch)
        if result["invocation_id"] != order["invocation_id"]:
            raise Refused("the result is another invocation's")
        events: dict[str, set[str]] = {}
        for search in result["searches"]:                      # 1. the router's persistence ACK, in the client's own order
            for method, request in observe.router_requests(search["out"], capability_id=grant["capability_id"], invocation_id=order["invocation_id"]):
                _require(method, getattr(control, method)(request))
                for event in request.get("retrieval_events", []):
                    events.setdefault(event["provider_record_id"], set()).add(event["event_id"])
        built = exchanges.build(result)                         # 2. retain what the gateway returned, before anything depends on it
        exchanges.write_index(scratch, order["invocation_id"], result["attempt"], exchanges.stage_all(stage, order["topic_id"], built))
        identities = sorted((work_identity(pid), sorted(ids)) for pid, ids in events.items())
        for start in range(0, len(identities), 1000):           # 3. only after the ACK do retrieved records become works
            batch = [{"identity_scheme": s, "identity_value": v, "event_ids": ids} for (s, v), ids in identities[start:start + 1000]]
            _require("register_works", control.register_works({"capability_id": grant["capability_id"], "invocation_id": order["invocation_id"],
                                                               "dedup_method_version": DEDUP, "works": batch}))
    return record
