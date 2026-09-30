"""Gateway answers → the engine's search observations (task 2b; no I/O).

The engine's typed door to the Gateway (BOUNDARIES.md Gateway; gen2/boundaries.toml
modules.gateway_client) reads the gateway's answer the way an adapter reads a provider's:
it validates the shape it needs and never turns what it cannot read into zero results
(INVARIANTS H-5, RG-4, RG-U). Each lane of an answer becomes one observation document in
exactly the router's record_observation shape (gen2/router/service.py
router-commands#/$defs/observation), with one retrieval event per identity the lane
retrieved, in the lane's rank order (E-2). What this module checks, per lane, is the
store's own search_observations rules (gen2/store/schema/03-evidence-and-decisions.sql):
a lane entry that breaks them, a count without the identities behind it, or an answer
that does not echo the invocation and attempt it was asked under, is recorded as
`unknown` with error_class `payload_invalid` — never as the counts it claimed.

Identity (H-1, H-5): an observation's `request` names the lane and the gateway's
effective request as echoed; `request_identity` is the engine's RFC 8785 hash of that
document; `observation_id` and each `event_id` derive from the invocation, attempt and
request identity, so recording the same observation again replays instead of
duplicating. The gateway's own request identity rides inside `request`, never assumed
equal to the engine's.

What a lane observation cannot say: its content came from another caller's dispatch
(`served` is coalesced or cache) — carried in `request.served` for accounting to read —
and cost, which the gateway does not report per lane (`cost_units` is null: unknown,
never zero).
"""
from __future__ import annotations

import hashlib

from gen2.core import canonical

COVERAGE = ("searched_ok", "searched_empty", "not_searched", "provider_unavailable", "auth_failed",
            "metadata_only", "exhausted", "unknown")
OBSERVED = ("searched_ok", "searched_empty", "metadata_only")
ERROR_CLASSES = ("payload_invalid", "timeout", "rate_limited", "breaker_open", "budget_refused", "provider_outage",
                 "credentials_rejected", "credentials_not_configured", "secrets_backend_failing", "transport_failure",
                 "telemetry_missing", "partial_pagination")
FACT_STATES = ("healthy", "degraded", "failing", "unknown")
GATEWAY_LANE = "gateway"   # the pseudo-lane of an answer that named no lanes: the gateway itself, not a source


def _digest(*parts: object) -> str:
    return hashlib.sha256(canonical.canonical_bytes(list(parts))).hexdigest()[:32]


def lane_problem(entry: object) -> str | None:
    """Why a gateway lane entry cannot be recorded as it stands, or None (the store's rules)."""
    if not isinstance(entry, dict) or not isinstance(entry.get("source"), str) or not entry["source"]:
        return "a lane entry names no source"
    cov, comp, count, err = entry.get("coverage"), entry.get("completeness"), entry.get("count"), entry.get("error_class")
    if cov not in COVERAGE or comp not in ("complete", "partial", "unobserved"):
        return f"{entry['source']}: coverage {cov!r} / completeness {comp!r} outside the vocabulary"
    if err is not None and err not in ERROR_CLASSES:
        return f"{entry['source']}: error_class {err!r} outside the vocabulary"
    if (cov in OBSERVED) != (comp != "unobserved"):
        return f"{entry['source']}: {cov} with completeness {comp}"
    if comp == "unobserved":
        if count is not None or entry.get("retrieved") is not None:
            return f"{entry['source']}: an unobserved lane carries a count"
        if cov in ("provider_unavailable", "auth_failed", "unknown") and err is None:
            return f"{entry['source']}: {cov} without an error class"
        return None
    retrieved = entry.get("retrieved")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return f"{entry['source']}: an observed lane without a count"
    if not isinstance(retrieved, list) or len(retrieved) != count or not all(isinstance(r, str) and r for r in retrieved):
        return f"{entry['source']}: count {count} is not the identities it names (E-2)"
    if cov == "searched_empty" and (count != 0 or comp != "complete"):
        return f"{entry['source']}: searched_empty is a complete count of 0"
    if cov == "searched_ok" and count < 1:
        return f"{entry['source']}: searched_ok with no record"
    if comp == "partial" and err is None:
        return f"{entry['source']}: a partial set without its reason"
    if comp == "complete" and err is not None:
        return f"{entry['source']}: a complete set with an error class"
    return None


def unobserved(lane: str, coverage: str, error_class: str | None) -> dict:
    """A lane entry for something the engine could not read (its own coverage, never a count)."""
    return {"source": lane, "coverage": coverage, "completeness": "unobserved", "error_class": error_class}


def lane_records(answer: dict, lane: str) -> list[dict]:
    """The answer's records this lane contributed (a merged record names its members)."""
    out = []
    for rec in answer.get("records") or []:
        if not isinstance(rec, dict):
            continue
        members = [m.get("source_id") for m in rec.get("provenance") or [] if isinstance(m, dict)]
        if lane in members or rec.get("source_id") == lane:
            out.append({k: rec[k] for k in ("identity", "kind", "title", "year", "license", "metadata_license", "freshness_lag",
                                            "retrieved_at", "permissions", "source_id", "sources", "provenance") if k in rec})
    return out


def observation(entry: dict, *, request: dict, invocation_id: str, attempt: int, obligation_ids: list,
                policy_version: str, started_at: str, ended_at: str, call_ref: str | None,
                fact_id: str | None = None) -> dict:
    """{"observation", "retrieval_events"} for one validated lane entry. `request` is the
    engine's request document for this lane; its logical hash is the request identity."""
    rid = canonical.logical_hash(request)
    oid = "obs_" + _digest("observation", invocation_id, attempt, rid)
    observed = entry["completeness"] != "unobserved"
    seen: list[str] = []
    for identity in entry.get("retrieved") or []:
        if identity not in seen:   # one candidate, one event: a provider repeating a record does not count it twice
            seen.append(identity)
    coverage, count = entry["coverage"], (len(seen) if observed else None)
    if coverage == "metadata_only" and not count:
        # the gateway's "the identity is known but its full text is not retrievable" with nothing
        # returned: for the store this successful query returned 0 items (it needs >= 1 for metadata_only)
        coverage = "searched_empty"
    doc = {"observation_id": oid, "request": request, "request_identity": rid, "attempt": attempt, "lane": entry["source"],
           "obligation_ids": list(obligation_ids), "started_at": started_at, "ended_at": ended_at, "coverage_state": coverage,
           "result_count": count, "completeness": entry["completeness"], "error_class": entry.get("error_class"),
           "capability_fact_id": fact_id if entry.get("error_class") == "secrets_backend_failing" else None,
           "policy_version": policy_version, "cost_units": None, "gateway_call_ref": call_ref}
    events = [{"event_id": "rev_" + _digest("event", oid, identity), "provider_record_id": identity, "rank": rank,
               "captured_at": ended_at} for rank, identity in enumerate(seen, start=1)]
    return {"observation": doc, "retrieval_events": events}


def capability_fact(fact: object) -> dict | None:
    """A gateway capability fact as the engine's capability_facts row (fact_id deterministic in
    the capability and its since: one failing episode, one id), or None if it is not one."""
    if not isinstance(fact, dict) or not isinstance(fact.get("capability"), str) or fact.get("state") not in FACT_STATES:
        return None
    capability = "gateway." + fact["capability"]
    lanes = fact.get("affected_lanes")
    return {"fact_id": "fact_" + _digest("capability", capability, fact.get("since")), "capability": capability,
            "state": fact["state"], "detail": str(fact.get("detail") or fact["state"])[:500], "since": fact.get("since"),
            "last_success_at": fact.get("last_success_at"),
            "affected_lanes": sorted(x for x in lanes if isinstance(x, str)) if isinstance(lanes, list) else []}
