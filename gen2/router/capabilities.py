"""Capability probes as the router records them (task 1f). A collaborator
of service.Router (task 2q-b2: "Router composition", BOUNDARIES.md), with the
router's one shape: validate outside any transaction, then one short
transaction (the core's: `_guarded`) that fences and writes.

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
    could not say), declared_expired degraded (the runner reads the
    credential, whose access token declares it expired: the credential's own
    claim, which a refresh credential may renew; the provider was not asked,
    task 1f-repair; such an observation names that declared instant, at or
    before it was observed). Nothing recorded is not healthy: a capability
    known only by probing is unknown until probed, so its first observation
    is a transition. A fact's `since` is the observation's own instant, and
    one not healthy carries `last_success_at`, the last usable observation
    recorded;
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

Gateway-reported facts (task 2b-repair A6; DEPLOYMENT-CONTRACT §3.4 fixture 5):
the Gateway answers a request with the dated capability facts that explain its
lanes (its secrets backend failing, since when, which lanes); an observation
naming such a fact (secrets_backend_failing) needs it recorded first, and
record_gateway_facts is the typed path, under the capability of the running
invocation that received it. Each fact is a `gateway.*` capability — never
another namespace — and one SNAPSHOT of an episode (2b-repair-2 R2): the
episode is the capability, its state and `since`, the instant that state
began; the snapshot is the gateway's `revision` of its fact (the count of the
fact's changes, so it orders the episode's snapshots however they reach the
router, 2b-repair-3 R2) and what the gateway said then (detail, last success,
affected lanes). Its id is its content's (canonical.gateway_fact_id), whoever
reports it: the same snapshot again replays, and moves nothing. A new one
supersedes the capability's current fact (H-2: a transition is a new row, and
every snapshot is kept) when it is a later episode, or a later revision of the
current episode (an outage that widens to another lane, fails another way, or
returns to what it said before, keeps its `since`); an earlier revision of the
current episode — a report recorded after a newer one — is kept behind the
current fact, which supersedes it, so each observation names the snapshot it
was answered with and the current fact is the newest. One older than the
current episode is refused (fact_superseded); another state since the current
episode's instant is refused (fact_conflict): a new state begins a new
episode; so is a revision of the episode recorded with other contents. It
opens no hold: what a failing gateway capability holds is 2c/2e's to decide.
"""
from __future__ import annotations

from typing import Callable, Mapping, Protocol

from gen2.core import canonical
from gen2.router import boundary
from gen2.router.boundary import Refusal, instant
from gen2.router.lifecycle import _after
from gen2.router.registries import ROUTER_DEFAULTS

OUTCOME_STATE = {"usable": "healthy", "declared_expired": "degraded", "unusable_credential": "failing", "runner_error": "unknown"}
AUDIT_KIND = "capability_probe"
_ID = {"$ref": "common.schema.json#/$defs/short_text"}
_DECLARED = {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/timestamp"}]}
CAPABILITY_COMMANDS = {
    "capability_probe": {
        "type": "object", "additionalProperties": False,
        "required": ["probe_id", "capability", "outcome", "detail", "declared_expiry", "started_at", "observed_at", "runner", "affected_lanes",
                     "requested_by"],
        "properties": {
            "probe_id": {"type": "string", "pattern": "^probe_[a-f0-9]{32}$"},
            "capability": {"type": "string", "pattern": "^provider-auth:[a-z][a-z0-9-]{0,39}$"},
            "outcome": {"enum": sorted(OUTCOME_STATE)}, "detail": _ID,
            "declared_expiry": {"oneOf": [{"type": "null"}, {  # what the credential declares of its own expiry, when it was read
                "type": "object", "additionalProperties": False, "required": ["access_token", "id_token", "refresh_credential"],
                "properties": {"access_token": _DECLARED, "id_token": _DECLARED, "refresh_credential": {"type": "boolean"}}}]},
            "started_at": {"$ref": "common.schema.json#/$defs/timestamp"}, "observed_at": {"$ref": "common.schema.json#/$defs/timestamp"},
            "runner": {"type": "object", "additionalProperties": False, "required": ["name", "version"], "properties": {"name": _ID, "version": _ID}},
            "affected_lanes": {"type": "array", "maxItems": 20, "uniqueItems": True, "items": _ID},
            "requested_by": _ID}},
    "gateway_facts": {
        "type": "object", "additionalProperties": False, "required": ["capability_id", "invocation_id", "facts"],
        "properties": {
            "capability_id": {"$ref": "common.schema.json#/$defs/capability_id"},
            "invocation_id": {"$ref": "common.schema.json#/$defs/invocation_id"},
            "facts": {"type": "array", "minItems": 1, "maxItems": 20, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["fact_id", "capability", "state", "revision", "detail", "since", "last_success_at", "affected_lanes"],
                "properties": {
                    "fact_id": {"type": "string", "pattern": "^fact_[a-f0-9]{32}$"},
                    "capability": {"type": "string", "pattern": "^gateway\\.[a-z0-9][a-z0-9_.-]{0,62}$"},
                    "state": {"enum": ["healthy", "degraded", "failing", "unknown"]}, "revision": {"$ref": "common.schema.json#/$defs/revision"},
                    "detail": _ID,
                    "since": {"$ref": "common.schema.json#/$defs/timestamp"}, "last_success_at": _DECLARED,
                    "affected_lanes": {"type": "array", "maxItems": 50, "uniqueItems": True, "items": _ID}}}}}},
}
GATEWAY_FACT_AUDIT = "gateway_fact"


def hold_subject(capability: str) -> str:
    return f"capability:{capability}"


def _successor(fact: Mapping) -> dict:
    """What a gateway fact's predecessor states of it: the edge the store holds to the relation (2b-repair-5 F1)."""
    return {"successor_since": fact["since"], "successor_state": fact["state"], "successor_revision": fact["revision"]}


class Rows(Protocol):
    """The router's store as the capability record uses it (store/api.py Store): inside the core's transaction."""
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...
    def update(self, table: str, key: Mapping[str, object], changes: Mapping[str, object]) -> None: ...


class Schemas(Protocol):
    """The router's schema set as boundary.require_schema uses it (schemas.py SchemaSet)."""
    def errors(self, instance: object, target: str) -> list[str]: ...


class CapabilityCore(Protocol):
    """What the capability record takes of the router core, and nothing else;
    service.Router implements it without inheriting it. A member with no comment
    is the core's own (service.py); a comment names the mixin of the Router that
    defines it until that mixin is made a collaborator too."""
    _store: Rows
    _schemas: Schemas
    _new_id: Callable[[str], str]
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...
    def _guarded(self, reason: str, body: Callable[[str], object]) -> object: ...  # the one transaction an operation runs in
    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str: ...
    def _capability(self, capability_id: str, invocation_id: str) -> dict: ...
    def _require_current_lease(self, inv: dict, now: str, lease_ref: Mapping | None = None) -> dict: ...
    def _active_bundle(self) -> dict | None: ...  # registries.py
    def _router_policy(self, bundle_hash: str) -> dict: ...  # registries.py


class Capabilities:
    def __init__(self, core: CapabilityCore) -> None:
        self._core = core

    def record_capability_probe(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._core._schemas, req, "router-commands#/$defs/capability_probe", "request_invalid")
            if boundary.instant(req["observed_at"]) < boundary.instant(req["started_at"]):
                raise Refusal("request_invalid", "a probe is observed at or after it started")
            if req["outcome"] == "declared_expired" and not (
                    req["declared_expiry"] and req["declared_expiry"]["access_token"]
                    and boundary.instant(req["declared_expiry"]["access_token"]) <= boundary.instant(req["observed_at"])):
                raise Refusal("request_invalid", "declared_expired names the access token's declared expiry, at or before the observation")
            return self._core._guarded("request_invalid", lambda now: self._probe_in_transaction(req, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _probe_in_transaction(self, req: dict, now: str) -> dict:
        audit_id = "aud_" + req["probe_id"]
        recorded = self._core._one("audit_events", {"audit_event_id": audit_id})
        if recorded is not None:
            if recorded["kind"] != AUDIT_KIND or recorded["detail"]["observation"] != req:
                raise Refusal("probe_conflict", f"{req['probe_id']} was recorded with another observation")
            return {**recorded["detail"]["reply"], "status": "replayed"}
        capability, state = req["capability"], OUTCOME_STATE[req["outcome"]]
        seen = [e["detail"]["observation"] for e in self._core._store.select("audit_events", {"kind": AUDIT_KIND})
                if e["detail"]["observation"]["capability"] == capability]
        newest = max((boundary.instant(o["observed_at"]) for o in seen), default=None)
        applied = newest is None or boundary.instant(req["observed_at"]) >= newest
        current = next((f for f in self._core._store.select("capability_facts", {"capability": capability}) if f["superseded_by_fact_id"] is None), None)
        transition = applied and (current is None or current["state"] != state)
        if transition:
            usable = [o["observed_at"] for o in seen if o["outcome"] == "usable"]
            fact_id = self._core._new_id("fact_")
            if current is not None:
                self._core._store.update("capability_facts", {"fact_id": current["fact_id"]}, {"superseded_by_fact_id": fact_id})
            self._core._store.insert("capability_facts", {
                "fact_id": fact_id, "capability": capability, "state": state, "detail": f"{req['outcome']}: {req['detail']}"[:500],
                "since": req["observed_at"], "last_success_at": None if state == "healthy" else max(usable, key=boundary.instant, default=None),
                "affected_lanes": req["affected_lanes"], "recorded_at": now})
            current = self._core._one("capability_facts", {"fact_id": fact_id})
        hold = None
        if applied and state != "healthy":
            hold = next((h for h in self._core._store.select("holds", {"subject_ref": hold_subject(capability)}) if h["cleared_at"] is None), None)
            if hold is None:
                active = self._core._active_bundle()
                policy = self._core._router_policy(active["bundle_hash"]) if active is not None else ROUTER_DEFAULTS
                hold = {"hold_id": self._core._new_id("hold_"), "topic_id": None, "subject_ref": hold_subject(capability), "hold_class": "capability",
                        "cause": f"{capability} {req['outcome']}: {req['detail']}"[:500],
                        "recoverability": "needs_remediation" if req["outcome"] in ("unusable_credential", "declared_expired") else "unknown",
                        "required_authority": "operator", "owner": "operator", "deadline_at": _after(now, policy["hold_window_s"]),
                        "clears_when": f"an operator hold_clearance, once a probe records {capability} usable (for a credential: refreshed "
                                       "in its auth volume; for the runner: repaired by an image release)",
                        "capability_fact_id": current["fact_id"], "created_at": now, "created_by_operation_id": None}
                self._core._store.insert("holds", hold)
                hold = {"hold_id": hold["hold_id"], "opened": True}
            else:
                hold = {"hold_id": hold["hold_id"], "opened": False}
        reply = {"status": "recorded", "probe_id": req["probe_id"], "capability": capability, "outcome": req["outcome"],
                 "declared_expiry": req["declared_expiry"], "started_at": req["started_at"], "observed_at": req["observed_at"], "applied": applied,
                 "fact": {"fact_id": current["fact_id"], "state": current["state"], "since": current["since"],  # an older observation implies a newer one's fact
                          "last_success_at": current["last_success_at"], "transition": transition},
                 "hold": hold}
        self._core._store.insert("audit_events", {"audit_event_id": audit_id, "at": now, "kind": AUDIT_KIND, "topic_id": None, "invocation_id": None,
                                            "operation_id": None, "detail": {"observation": req, "reply": reply}})
        return reply

    def record_gateway_facts(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._core._schemas, req, "router-commands#/$defs/gateway_facts", "request_invalid")
            if len({f["capability"] for f in req["facts"]}) != len(req["facts"]):
                raise Refusal("request_invalid", "one fact per capability: an answer reports each capability's current fact once")
            for fact in req["facts"]:
                if fact["fact_id"] != canonical.gateway_fact_id(fact):
                    raise Refusal("request_invalid", f"{fact['fact_id']} is not the id of its content ({fact['capability']} since {fact['since']})")
            return self._core._guarded("request_invalid", lambda now: self._gateway_facts_in_transaction(req, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _gateway_facts_in_transaction(self, req: dict, now: str) -> dict:
        inv = self._core._capability(req["capability_id"], req["invocation_id"])
        replies, new = [], []
        for fact in req["facts"]:
            if self._core._one("capability_facts", {"fact_id": fact["fact_id"]}) is None:   # the id is its content's: recorded is identical
                new.append(fact)
            else:
                replies.append({"fact_id": fact["fact_id"], "status": "replayed"})
        if not new:   # a lost reply is answered from the facts, whatever the invocation's state now
            return {"status": "replayed", "facts": replies}
        if inv["state"] != "running" or inv["cancel_requested_at"] is not None:
            raise Refusal("invocation_state_invalid", f"gateway facts are recorded while running, not {inv['state']}, and never after a cancellation request")
        self._core._require_current_lease(inv, now)
        if self._core._one("queue_entries", {"topic_id": inv["topic_id"]})["paused_at"] is not None:
            raise Refusal("topic_paused", f"{inv['topic_id']} is paused")
        for fact in new:
            recorded = self._core._store.select("capability_facts", {"capability": fact["capability"]})
            current = next((f for f in recorded if f["superseded_by_fact_id"] is None), None)
            if current is not None and instant(current["since"]) > instant(fact["since"]):
                raise Refusal("fact_superseded", f"{fact['capability']}'s current fact {current['fact_id']} began at {current['since']}, "
                                                 f"after {fact['since']}: an older episode is never recorded behind a newer one")
            if current is not None and instant(current["since"]) == instant(fact["since"]) and current["state"] != fact["state"]:
                raise Refusal("fact_conflict", f"{fact['capability']} was {current['state']} since {current['since']}, not {fact['state']}: "
                                               "a new state is a new episode, with the instant it began")
            twin = next((f for f in recorded if instant(f["since"]) == instant(fact["since"]) and f["revision"] == fact["revision"]), None)
            if twin is not None:
                raise Refusal("fact_conflict", f"{fact['capability']}'s revision {fact['revision']} since {fact['since']} is {twin['fact_id']}: "
                                               "one revision of an episode is one snapshot")
            behind = current is not None and instant(current["since"]) == instant(fact["since"]) and current["revision"] > fact["revision"]
            if current is not None and not behind:
                self._core._store.update("capability_facts", {"fact_id": current["fact_id"]}, {"superseded_by_fact_id": fact["fact_id"], **_successor(fact)})
            self._core._store.insert("capability_facts", {**fact, "observed_by_invocation_id": inv["invocation_id"], "recorded_at": now,
                                                    **({"superseded_by_fact_id": current["fact_id"], **_successor(current)} if behind else {})})
            replies.append({"fact_id": fact["fact_id"], "status": "recorded"})
        self._core._audit(GATEWAY_FACT_AUDIT, now, {"facts": [f["fact_id"] for f in new]}, topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
        return {"status": "recorded", "facts": replies}
