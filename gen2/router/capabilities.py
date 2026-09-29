"""Capability probes as the router records them (task 1f). A mixin of
service.Router, with the router's one shape: validate outside any
transaction, then one short transaction that fences and writes.

Trace: DEPLOYMENT-CONTRACT.md §4 (testing requirement (d): a revoked or
expired credential produces a dated capability fact and a typed capability
hold, not a silent zero-result pass), §1.2 (a dependency's failure is a
capability fact, never an unhealthy container); BOUNDARIES.md Station
supervisor (it runs and classifies capability probes) and Router (the sole
writer; holds typed, owned, deadlined); INVARIANTS H-2, H-3, RG-3, G-13.

The station supervisor probes a capability and classifies what it saw
(gen2/supervisor/probe.py); this records it. One observation, one
transaction:
  * it is kept whole as an audit event under its probe id: the same
    observation again replays the answer it got; another under that id is a
    conflict;
  * the capability's dated fact moves on a transition only (H-2): usable is
    healthy, unusable_credential failing, runner_error unknown (the runner
    could not say). Nothing recorded is not healthy: a capability known only
    by probing is unknown until probed, so its first observation is a
    transition. A fact's `since` is the observation's own instant, and a
    failing or unknown one carries `last_success_at`, the last usable
    observation recorded;
  * an observation older than one already recorded for the capability (two
    probes that ran together, recorded out of order) is kept and moves
    nothing: the fact follows the newest observation (found by reading the
    recorded probes, fine at an operator's or a scheduler's probe cadence;
    frequent probing would want an index);
  * an observation that is not usable opens the capability's hold when none
    is open (RG-3): class capability, owned by the operator, deadlined by the
    router's hold window, cleared only by an operator hold_clearance (G-13).
    A usable observation records the recovery fact and clears no hold: the
    operator clears it with that fact in status. A hold cleared while the
    capability still fails is opened again by the next such observation.
"""
from __future__ import annotations

from typing import Mapping

from gen2.router import boundary
from gen2.router.boundary import Refusal
from gen2.router.lifecycle import _after
from gen2.router.registries import ROUTER_DEFAULTS

OUTCOME_STATE = {"usable": "healthy", "unusable_credential": "failing", "runner_error": "unknown"}
AUDIT_KIND = "capability_probe"
_ID = {"$ref": "common.schema.json#/$defs/short_text"}
CAPABILITY_COMMANDS = {
    "capability_probe": {
        "type": "object", "additionalProperties": False,
        "required": ["probe_id", "capability", "outcome", "detail", "started_at", "observed_at", "runner", "affected_lanes", "requested_by"],
        "properties": {
            "probe_id": {"type": "string", "pattern": "^probe_[a-f0-9]{32}$"},
            "capability": {"type": "string", "pattern": "^provider-auth:[a-z][a-z0-9-]{0,39}$"},
            "outcome": {"enum": sorted(OUTCOME_STATE)}, "detail": _ID,
            "started_at": {"$ref": "common.schema.json#/$defs/timestamp"}, "observed_at": {"$ref": "common.schema.json#/$defs/timestamp"},
            "runner": {"type": "object", "additionalProperties": False, "required": ["name", "version"], "properties": {"name": _ID, "version": _ID}},
            "affected_lanes": {"type": "array", "maxItems": 20, "uniqueItems": True, "items": _ID},
            "requested_by": _ID}},
}


def hold_subject(capability: str) -> str:
    return f"capability:{capability}"


class Capabilities:
    def record_capability_probe(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._schemas, req, "router-commands#/$defs/capability_probe", "request_invalid")
            if boundary.instant(req["observed_at"]) < boundary.instant(req["started_at"]):
                raise Refusal("request_invalid", "a probe is observed at or after it started")
            return self._guarded("request_invalid", lambda now: self._probe_in_transaction(req, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _probe_in_transaction(self, req: dict, now: str) -> dict:
        audit_id = "aud_" + req["probe_id"]
        recorded = self._one("audit_events", {"audit_event_id": audit_id})
        if recorded is not None:
            if recorded["kind"] != AUDIT_KIND or recorded["detail"]["observation"] != req:
                raise Refusal("probe_conflict", f"{req['probe_id']} was recorded with another observation")
            return {**recorded["detail"]["reply"], "status": "replayed"}
        capability, state = req["capability"], OUTCOME_STATE[req["outcome"]]
        seen = [e["detail"]["observation"] for e in self._store.select("audit_events", {"kind": AUDIT_KIND})
                if e["detail"]["observation"]["capability"] == capability]
        newest = max((boundary.instant(o["observed_at"]) for o in seen), default=None)
        applied = newest is None or boundary.instant(req["observed_at"]) >= newest
        current = next((f for f in self._store.select("capability_facts", {"capability": capability}) if f["superseded_by_fact_id"] is None), None)
        transition = applied and (current is None or current["state"] != state)
        if transition:
            usable = [o["observed_at"] for o in seen if o["outcome"] == "usable"]
            fact_id = self._new_id("fact_")
            if current is not None:
                self._store.update("capability_facts", {"fact_id": current["fact_id"]}, {"superseded_by_fact_id": fact_id})
            self._store.insert("capability_facts", {
                "fact_id": fact_id, "capability": capability, "state": state, "detail": f"{req['outcome']}: {req['detail']}"[:500],
                "since": req["observed_at"], "last_success_at": None if state == "healthy" else max(usable, key=boundary.instant, default=None),
                "affected_lanes": req["affected_lanes"], "recorded_at": now})
            current = self._one("capability_facts", {"fact_id": fact_id})
        hold = None
        if applied and state != "healthy":
            hold = next((h for h in self._store.select("holds", {"subject_ref": hold_subject(capability)}) if h["cleared_at"] is None), None)
            if hold is None:
                active = self._active_bundle()
                policy = self._router_policy(active["bundle_hash"]) if active is not None else ROUTER_DEFAULTS
                hold = {"hold_id": self._new_id("hold_"), "topic_id": None, "subject_ref": hold_subject(capability), "hold_class": "capability",
                        "cause": f"{capability} {req['outcome']}: {req['detail']}"[:500],
                        "recoverability": "needs_remediation" if req["outcome"] == "unusable_credential" else "unknown",
                        "required_authority": "operator", "owner": "operator", "deadline_at": _after(now, policy["hold_window_s"]),
                        "clears_when": f"an operator hold_clearance, once a probe records {capability} usable (for a credential: refreshed "
                                       "in its auth volume; for the runner: repaired by an image release)",
                        "capability_fact_id": current["fact_id"], "created_at": now, "created_by_operation_id": None}
                self._store.insert("holds", hold)
                hold = {"hold_id": hold["hold_id"], "opened": True}
            else:
                hold = {"hold_id": hold["hold_id"], "opened": False}
        reply = {"status": "recorded", "probe_id": req["probe_id"], "capability": capability, "outcome": req["outcome"],
                 "started_at": req["started_at"], "observed_at": req["observed_at"], "applied": applied,
                 "fact": {"fact_id": current["fact_id"], "state": current["state"], "since": current["since"],  # an older observation implies a newer one's fact
                          "last_success_at": current["last_success_at"], "transition": transition},
                 "hold": hold}
        self._store.insert("audit_events", {"audit_event_id": audit_id, "at": now, "kind": AUDIT_KIND, "topic_id": None, "invocation_id": None,
                                            "operation_id": None, "detail": {"observation": req, "reply": reply}})
        return reply
