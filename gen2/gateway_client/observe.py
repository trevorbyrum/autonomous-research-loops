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

Identity (H-1, H-5; task 2b-repair A2): an observation's `request` is what the engine
ATTEMPTED — the lane, the page, and the exact request it sent for that page (its query,
kind, filters, cursors) — so it exists whether or not anything answered, and two
different requests never share it. It holds nothing the answer said: not the gateway's
echo of its effective request (a failure has none), not how the answer was delivered
(dispatched, coalesced, from a cache, polled), not its durable-capture acknowledgement.
`request_identity` is the engine's RFC 8785 hash of that document; `observation_id` and
each `event_id` derive from the invocation, attempt and request identity, so recording
the same observation again replays, and the same attempt answered another way is a
conflict at the router — never a second observation of one attempt.

What the answer did say, and the store keeps: the lane's coverage, completeness, count,
error class and fact; `gateway_call_ref`, the caller's own durable request row at the
gateway (null when it was not captured). An answer the gateway did not capture durably
(2b-repair A1; RG-4's telemetry loss) keeps what it read only as a LOWER BOUND: a complete
set becomes partial (`telemetry_missing`), a complete empty set becomes `unknown` — missing
telemetry is never complete negative evidence. What an observation still cannot say: cost,
which the gateway does not report per lane (`cost_units` is null: unknown, never zero).
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


def metadata_only_named(entry: dict, sent: dict) -> dict:
    """`metadata_only` is "the record was found; its full text is not retrievable"
    (STATION-CONTRACT §2): it names the record, and it is never an empty search (2b-repair
    A1). The gateway's enrich of a HELD identity that found no full text names no record in
    its lane — the record is the one the request held, so that is the identity recorded; any
    other metadata_only that names nothing is unreadable (`unknown`, payload_invalid)."""
    if entry.get("coverage") != "metadata_only" or entry.get("retrieved"):
        return entry
    held = sent.get("identity") if sent.get("request_type") == "enrich" else None
    if not (isinstance(held, str) and held):
        return unobserved(entry["source"], "unknown", "payload_invalid")
    return {**entry, "count": 1, "retrieved": [held]}


def uncaptured(entry: dict) -> dict:
    """A lane of an answer the gateway did not capture durably (2b-repair A1; RG-4): what it
    read stays, as a lower bound — a complete set is partial (`telemetry_missing`), a complete
    empty set is `unknown` — and a set already partial or unobserved keeps its own reason."""
    if entry.get("completeness") != "complete":
        return entry
    if entry["coverage"] == "searched_empty":
        return unobserved(entry["source"], "unknown", "telemetry_missing")
    return {**entry, "completeness": "partial", "error_class": "telemetry_missing"}


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
    engine's attempted-request document for this lane and page; its hash is the request identity."""
    rid = canonical.logical_hash(request)
    oid = "obs_" + _digest("observation", invocation_id, attempt, rid)
    observed = entry["completeness"] != "unobserved"
    seen: list[str] = []
    for identity in entry.get("retrieved") or []:
        if identity not in seen:   # one candidate, one event: a provider repeating a record does not count it twice
            seen.append(identity)
    doc = {"observation_id": oid, "request": request, "request_identity": rid, "attempt": attempt, "lane": entry["source"],
           "obligation_ids": list(obligation_ids), "started_at": started_at, "ended_at": ended_at, "coverage_state": entry["coverage"],
           "result_count": len(seen) if observed else None, "completeness": entry["completeness"], "error_class": entry.get("error_class"),
           "capability_fact_id": fact_id if entry.get("error_class") == "secrets_backend_failing" else None,
           "policy_version": policy_version, "cost_units": None, "gateway_call_ref": call_ref}
    events = [{"event_id": "rev_" + _digest("event", oid, identity), "provider_record_id": identity, "rank": rank,
               "captured_at": ended_at} for rank, identity in enumerate(seen, start=1)]
    return {"observation": doc, "retrieval_events": events}


def capability_fact(fact: object) -> dict | None:
    """A gateway capability fact as the engine's capability_facts row (its id the snapshot's,
    canonical.gateway_fact_id: an episode, the snapshot's revision and what the gateway said of
    it then), or None if it is not one — a fact without the instant its state began is not a
    dated fact, and one without its revision has no place among its episode's snapshots."""
    if not isinstance(fact, dict) or not isinstance(fact.get("capability"), str) or fact.get("state") not in FACT_STATES \
            or not isinstance(fact.get("since"), str) or not fact["since"] \
            or type(fact.get("revision")) is not int or not 1 <= fact["revision"] <= canonical.INT_BOUND:
        return None
    lanes = fact.get("affected_lanes")
    last = fact.get("last_success_at")
    row = {"capability": "gateway." + fact["capability"], "state": fact["state"], "revision": fact["revision"],
           "detail": str(fact.get("detail") or fact["state"])[:500],
           "since": fact["since"], "last_success_at": last if isinstance(last, str) and last else None,
           "affected_lanes": sorted({x for x in lanes if isinstance(x, str) and x}) if isinstance(lanes, list) else []}
    return {"fact_id": canonical.gateway_fact_id(row), **row}


def router_requests(out: dict, *, capability_id: str, invocation_id: str) -> list[tuple[str, dict]]:
    """What the router records for one search, in order (2b-repair A6): the capability facts
    the gateway reported first (record_gateway_facts — an observation names its fact, which
    must exist), then each observation with its retrieval events (record_observation). Pages
    answered under two snapshots of one capability's episode (2b-repair-2 R2) are two
    commands, in the order the pages reported them: a command holds one fact per capability."""
    who = {"capability_id": capability_id, "invocation_id": invocation_id}
    batches: list[list[dict]] = []
    for fact in out["capability_facts"]:
        if not batches or any(f["capability"] == fact["capability"] for f in batches[-1]):
            batches.append([])
        batches[-1].append(fact)
    return [("record_gateway_facts", {**who, "facts": batch}) for batch in batches] + [
        ("record_observation", {**who, "observation": o["observation"], "retrieval_events": o["retrieval_events"]})
        for o in out["observations"]]
