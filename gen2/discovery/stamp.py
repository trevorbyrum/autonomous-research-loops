"""Attach each observation to the proposal that caused it, by identity (Astra #125 F2).

Trace: 2e2-min design F4 (challenge searches); INVARIANTS H-5 (the request identity is the hash of the request), RG-4. A
challenge pass must read the observations of ITS proposals, so a lane-and-query match (two proposals may share both) is not
enough. `proposal_ref` = "<proposing invocation id>:<proposal_id>" is written into the observation's `request` as a sibling
of `lane`, `page` and `request`. Trusted code sets it from the committed search_proposals payload the job executes and the
proposing invocation the driver names, never from model text; it is on every observation of the proposal, a failed or
degraded one included. Because the request changed, its identity and everything derived from it are re-derived the way the
client derives them (observe.observation); the parity test in test_discovery_stamp pins the formula.
Oracle: the client's own derivation, applied to an unstamped observation. Limits: the SQL CHECK on `search_observations.request`
reads only `$.request.request_type`, so the extra key is stored; a retained (string) request cannot take a key and is refused.
"""
from __future__ import annotations

import hashlib
from typing import Mapping

from gen2.core import canonical
from gen2.exec.common import Refused


def digest(*parts: object) -> str:
    """The client's id digest (gateway_client/observe.py `_digest`): 32 hex of SHA-256 over the canonical parts."""
    return hashlib.sha256(canonical.canonical_bytes(list(parts))).hexdigest()[:32]


def ref_of(proposing_invocation_id: str, proposal_id: str) -> str:
    return f"{proposing_invocation_id}:{proposal_id}"


def stamp(out: dict, proposal_ref: str, *, invocation_id: str, attempt: int) -> None:
    """Stamp every observation of one search result, in place: request, request_identity, observation_id, event ids."""
    for item in out["observations"]:
        doc = item["observation"]
        if not isinstance(doc["request"], dict):
            raise Refused("a retained (string) request cannot carry a proposal_ref")
        request = {**doc["request"], "proposal_ref": proposal_ref}
        identity = canonical.logical_hash(request)
        doc["request"], doc["request_identity"] = request, identity
        doc["observation_id"] = "obs_" + digest("observation", invocation_id, attempt, identity)
        for event in item["retrieval_events"]:
            event["event_id"] = "rev_" + digest("event", doc["observation_id"], event["provider_record_id"])
