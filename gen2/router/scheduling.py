"""Re-queues, reservations and the coalesced signal queue (task 1d). A collaborator
of service.Router (task 2q-b7: "Router composition", BOUNDARIES.md), with the
router's one shape: validate outside any transaction, then one short transaction
(the core's: `_guarded`) that fences and writes. None of it
is a scheduler: each is an operation the trusted surface (1e) or a policy
caller asks for, which the router admits or refuses against recorded state
and the pinned bundle's policy.

Trace: design review §6 ("Every retry path consumes a declared attempt/time
budget ... Known transient faults retry within budget; suspected semantic
faults are diagnosed or revised, not blindly retried"), §10 gate 3 (exhausted
retries end in a bounded, visible state), §5 ("Already admitted work may
finish within its existing deadline and reservation"); flow S5 (one fixed
cadence review plus one coalesced signal queue, per-topic budget/cooldown,
causes recorded, never dropped), S6 (the protected exploration budget),
§6.4 (auto-promotion bound to the exact approved revision and the remaining
auto-budget reservation); BOUNDARIES.md Router (scheduling and leases;
checkpoint cadence and the coalesced signal queue); INVARIANTS L-6, RG-3,
G-5, G-10, G-12, H-3; the 1c deferrals (Astra 1c review, rulings on
questions 2 and 4).

Re-queue. Work that ended failed or cancelled leaves its lane — the topic's
leases of its scope, taken one at a time — waiting: the lane's next claim is
admitted only as that work's re-queued retry (service.Router claim,
`requeue_required`). A policy re-queue is admitted for a failure class the
ended work's pinned bundle lists as retryable, or a cancellation the
supervisor or the router made, within that bundle's attempt budget; past it,
nothing is re-queued and the budget's hold opens (operator authority, owned,
deadlined), once. An operator re-queue needs no budget; it is the diagnosis
L-6 asks for. Neither is admitted while that work's hold is open: it is
cleared by an operator decision first (hold_clearance).

Reservations. A reservation holds admissions for protected exploration or
auto-promotion, bound to the approved revision it was opened under and sized
by the active bundle (G-10). A claim draws on one (DDL reservation_draws):
within it, revision-bound, and for auto-promotion inside a facet whose
operator rating meets the bundle's threshold (G-5). An amendment closes it
(amendments.py); an exhausted one is closed when the next is opened. The
promotion mechanism itself is Phase 3.

Signal queue. Triggers are recorded by commits and never dropped. A review
episode takes every pending trigger of its topic. A signal-driven episode is
admitted within the active bundle's budget per window and after its
cooldown; the fixed cadence floor, and any pending mandatory signal
(retraction, decision-record change), are never held back by either (G-12).
Task 2a: the mandatory signals enter through raise_signal (code policy or
the operator; the surveillance that raises them is 2d's); a checkpoint's
commit closes its episode and marks the episode's triggers handled
(service.Router, review_closures).

Topics (task 2a). create_topic enters a topic into the queue at intake
(flow S1); what advances it is the brief's confirmation (G-4).
"""
from __future__ import annotations

from typing import Callable, Mapping, Protocol

from gen2.router import boundary
from gen2.router.boundary import Refusal, instant
from gen2.router.lifecycle import _after

MANDATORY = ("retraction", "decision_record_change")
BAND = {"critical": 3, "important": 2, "limited": 1}

_ID = {"$ref": "common.schema.json#/$defs/short_text"}
_RSV = {"type": "string", "pattern": "^rsv_[A-Za-z0-9_-]{8,64}$"}
SCHEDULING_COMMANDS = {
    "requeue": {
        "type": "object", "additionalProperties": False, "required": ["invocation_id", "requested_by", "reason"],
        "properties": {"invocation_id": {"$ref": "common.schema.json#/$defs/invocation_id"}, "requested_by": {"enum": ["operator", "policy"]}, "reason": _ID}},
    "reservation": {
        "type": "object", "additionalProperties": False, "required": ["reservation_id", "topic_id", "purpose"],
        "properties": {"reservation_id": _RSV, "topic_id": {"$ref": "common.schema.json#/$defs/topic_id"},
                       "purpose": {"enum": ["protected_exploration", "auto_promotion"]}}},
    "draw": {
        "type": "object", "additionalProperties": False, "required": ["reservation_id"],
        "properties": {"reservation_id": _RSV, "facet_id": {"$ref": "common.schema.json#/$defs/local_id"}}},
    "review": {
        "type": "object", "additionalProperties": False, "required": ["episode_id", "topic_id", "kind"],
        "properties": {"episode_id": {"type": "string", "pattern": "^rev_[A-Za-z0-9_-]{8,64}$"}, "topic_id": {"$ref": "common.schema.json#/$defs/topic_id"},
                       "kind": {"enum": ["fixed_cadence", "obligations_scope", "method_fit", "facet_audit", "calibration", "state_integrity_audit"]}}},
    "topic": {  # task 2a
        "type": "object", "additionalProperties": False, "required": ["topic_id", "priority"],
        "properties": {"topic_id": {"$ref": "common.schema.json#/$defs/topic_id"}, "priority": {"type": "integer", "minimum": 0, "maximum": 9007199254740991}}},
    "signal": {  # task 2a: signal_source names the trusted caller (code policy or the operator surface), as requeue's requested_by does
        "type": "object", "additionalProperties": False, "required": ["topic_id", "reason_code", "signal_source", "cause_ref", "source_revision", "observed_at"],
        "properties": {"topic_id": {"$ref": "common.schema.json#/$defs/topic_id"}, "reason_code": {"enum": list(MANDATORY)},
                       "signal_source": {"enum": ["deterministic", "operator"]}, "cause_ref": _ID,
                       "source_revision": {"$ref": "common.schema.json#/$defs/state_revision"}, "observed_at": {"$ref": "common.schema.json#/$defs/timestamp"}}},
}


class Rows(Protocol):
    """The router's store as scheduling uses it (store/api.py Store): inside the core's transaction."""
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...
    def update(self, table: str, key: Mapping[str, object], changes: Mapping[str, object]) -> None: ...


class Schemas(Protocol):
    """The router's schema set as boundary.require_schema uses it (schemas.py SchemaSet)."""
    def errors(self, instance: object, target: str) -> list[str]: ...


class SchedulingCore(Protocol):
    """What scheduling takes of the router core, and nothing else; service.Router
    implements it without inheriting it. A member with no comment is the core's own
    (service.py); comments naming collaborators identify core delegates that forward
    cross-collaborator access. Scheduling's own members the rest of the Router
    reads (`_lane_last`, `_admit_lane`, `_draw`) are the core's delegating members, so
    no other collaborator reaches scheduling but through the core."""
    _store: Rows
    _schemas: Schemas
    _new_id: Callable[[str], str]
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...
    def _guarded(self, reason: str, body: Callable[[str], object]) -> object: ...  # the one transaction an operation runs in
    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str: ...
    def _router_policy(self, bundle_hash: str) -> dict: ...
    def _active_bundle(self) -> dict | None: ...
    def _open_topic(self, topic_id: str) -> dict: ...


class Scheduling:
    def __init__(self, core: SchedulingCore) -> None:
        self._core = core

    def requeue(self, request: Mapping) -> dict:
        return self._scheduling_command(request, "requeue", self._requeue_in_transaction)

    def open_reservation(self, request: Mapping) -> dict:
        return self._scheduling_command(request, "reservation", self._reserve_in_transaction)

    def open_review(self, request: Mapping) -> dict:
        return self._scheduling_command(request, "review", self._review_in_transaction)

    def create_topic(self, request: Mapping) -> dict:
        return self._scheduling_command(request, "topic", self._topic_in_transaction)

    def raise_signal(self, request: Mapping) -> dict:
        return self._scheduling_command(request, "signal", self._signal_in_transaction)

    def _scheduling_command(self, request: Mapping, shape: str, body) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._core._schemas, req, f"router-commands#/$defs/{shape}", "request_invalid")
            return self._core._guarded("request_invalid", lambda now: body(req, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    # -- topics (task 2a) ----------------------------------------------------------
    def _topic_in_transaction(self, req: dict, now: str) -> dict:
        """A topic enters the queue at intake: awaiting its brief's
        confirmation, at state revision 0 (DDL queue_entries_created_at_intake;
        G-13: nothing is created decided), its fleet its id's prefix. Key: the
        topic id; only the identical request replays, whatever the topic has
        done since."""
        tid = req["topic_id"]
        stored = self._core._one("queue_entries", {"topic_id": tid})
        if stored is not None:
            if stored["priority"] != req["priority"]:
                raise Refusal("topic_conflict", f"{tid} was created with priority {stored['priority']}")
            return {"status": "replayed", "topic_id": tid}
        self._core._store.insert("queue_entries", {"topic_id": tid, "fleet_id": tid.split(":", 1)[0], "priority": req["priority"],
                                             "status": "awaiting_brief_confirmation", "created_at": now, "updated_at": now})
        self._core._audit("topic_created", now, {"priority": req["priority"]}, topic_id=tid)
        return {"status": "created", "topic_id": tid}

    # -- re-queue ------------------------------------------------------------------
    def _requeue_in_transaction(self, req: dict, now: str) -> dict:
        inv = self._core._one("invocations", {"invocation_id": req["invocation_id"]})
        if inv is None:
            raise Refusal("unknown_invocation", req["invocation_id"])
        recorded = self._core._one("retries", {"invocation_id": inv["invocation_id"]})
        if recorded is not None:  # the key is the ended work: one re-queue each
            if (recorded["requested_by"], recorded["reason"]) != (req["requested_by"], req["reason"]):
                raise Refusal("requeue_conflict", f"{inv['invocation_id']} was re-queued by {recorded['requested_by']} ({recorded['reason']})")
            return {"status": "replayed", "invocation_id": inv["invocation_id"], "attempt": recorded["attempt"]}
        # a delegate holds no lease, so it is never a lane's last work: its work is its parent's to re-queue
        if inv["state"] not in ("failed", "cancelled") or self._lane_last(inv["topic_id"], boundary.SCOPE_OF_KIND.get(inv["kind"])) != inv["invocation_id"]:
            raise Refusal("not_requeueable", f"{inv['invocation_id']} is a {inv['kind']} in state {inv['state']}: only the last work of a lane, ended failed or cancelled, is re-queued")
        subject = f"invocation:{inv['invocation_id']}#requeue"
        if any(h["cleared_at"] is None for h in self._core._store.select("holds", {"topic_id": inv["topic_id"], "subject_ref": subject})):
            raise Refusal("incident_open", f"the hold on {inv['invocation_id']}'s retries is open; an operator decision clears it first (RG-3)")
        prior = self._core._one("retries", {"retry_invocation_id": inv["invocation_id"]})
        attempt = (prior["attempt"] if prior is not None else 1) + 1
        if req["requested_by"] == "policy":
            policy = self._core._router_policy(inv["config_bundle_hash"]).get("retry")
            retryable = inv["cancel_requested_by"] in ("supervisor", "router") if inv["state"] == "cancelled" else \
                policy is not None and inv["failure_class"] in policy["failure_classes"]
            if not retryable:
                raise Refusal("not_policy_retryable", f"{inv['invocation_id']} ended {inv['state']} ({inv['failure_class'] or inv['cancel_requested_by']}): the operator's to diagnose (L-6)")
            if policy is None or attempt - 1 > policy["attempts"]:
                hold_id = self._core._new_id("hold_")
                self._core._store.insert("holds", {
                    "hold_id": hold_id, "topic_id": inv["topic_id"], "subject_ref": subject, "hold_class": "transient",
                    "cause": f"retry budget exhausted at attempt {attempt - 1} of {inv['invocation_id']}", "recoverability": "needs_decision",
                    "required_authority": "operator", "owner": "operator",
                    "deadline_at": _after(now, self._core._router_policy(inv["config_bundle_hash"])["hold_window_s"]),
                    "clears_when": "an operator hold_clearance; then the operator re-queues the work or leaves it ended",
                    "capability_fact_id": None, "created_at": now, "created_by_operation_id": None})
                self._core._audit("retry_budget_exhausted", now, {"hold_id": hold_id, "attempt": attempt - 1}, topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
                return {"status": "exhausted", "invocation_id": inv["invocation_id"], "hold_id": hold_id}
        self._core._store.insert("retries", {"invocation_id": inv["invocation_id"], "topic_id": inv["topic_id"], "attempt": attempt, "requested_by": req["requested_by"],
                                       "reason": req["reason"], "requested_at": now})
        self._core._audit("requeued", now, {"attempt": attempt, "by": req["requested_by"]}, topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
        return {"status": "requeued", "invocation_id": inv["invocation_id"], "attempt": attempt}

    def _lane_last(self, topic_id: str, scope: str) -> str | None:
        """The invocation holding the topic's newest lease of this scope."""
        last = max(self._core._store.select("leases", {"topic_id": topic_id, "scope": scope}), key=lambda lease: lease["generation"], default=None)
        return None if last is None else self._core._one("invocations", {"lease_id": last["lease_id"]})["invocation_id"]

    def _admit_lane(self, req: dict, topic_id: str, scope: str) -> dict | None:
        """At a claim: work of the lane that ended failed or cancelled is
        claimed again only as its re-queued retry, which the claim names
        (retry_of); returns that re-queue."""
        last = self._lane_last(topic_id, scope)
        ended = None if last is None else self._core._one("invocations", {"invocation_id": last})
        if ended is not None and ended["state"] in ("failed", "cancelled"):
            retry = self._core._one("retries", {"invocation_id": last})
            if req.get("retry_of") != last or retry is None:  # a claimed re-queue's retry is the lane's last since, so it never reaches here
                raise Refusal("requeue_required", f"{last}, the last {scope} work of {topic_id}, ended {ended['state']}: the lane is claimed again only as its re-queued retry (L-6)")
            return retry
        if req.get("retry_of") is not None:
            raise Refusal("request_invalid", f"{req['retry_of']} is not ended work waiting in this lane")
        return None

    # -- reservations ------------------------------------------------------------
    def _reserve_in_transaction(self, req: dict, now: str) -> dict:
        stored = self._core._one("reservations", {"reservation_id": req["reservation_id"]})
        if stored is not None:
            if (stored["topic_id"], stored["purpose"]) != (req["topic_id"], req["purpose"]):
                raise Refusal("reservation_conflict", f"{req['reservation_id']} is another reservation")
            return {"status": "replayed", "reservation_id": req["reservation_id"], "units": stored["units"]}
        self._core._open_topic(req["topic_id"])
        approved = self._core._one("contract_revisions", {"topic_id": req["topic_id"], "status": "approved"})
        if approved is None:
            raise Refusal("no_approved_contract", "a reservation is bound to an approved contract revision (G-5)")
        bundle = self._core._active_bundle()
        sized = None if bundle is None else (self._core._router_policy(bundle["bundle_hash"]).get("reservations") or {}).get(req["purpose"])
        if sized is None:
            raise Refusal("not_configured", f"the active bundle sizes no {req['purpose']} reservation (G-10)")
        current = next((r for r in self._core._store.select("reservations", {"topic_id": req["topic_id"], "purpose": req["purpose"]}) if r["closed_at"] is None), None)
        if current is not None:
            if len(self._core._store.select("reservation_draws", {"reservation_id": current["reservation_id"]})) < current["units"]:
                raise Refusal("reservation_open", f"{current['reservation_id']} is open with units left")
            self._core._store.update("reservations", {"reservation_id": current["reservation_id"]}, {"closed_at": now, "close_reason": "exhausted"})
        self._core._store.insert("reservations", {"reservation_id": req["reservation_id"], "topic_id": req["topic_id"], "purpose": req["purpose"],
                                            "contract_revision": approved["revision"], "units": sized["units"], "min_band": sized.get("min_band"),
                                            "bundle_hash": bundle["bundle_hash"], "opened_at": now})
        self._core._audit("reservation_opened", now, {"reservation_id": req["reservation_id"], "purpose": req["purpose"], "units": sized["units"]}, topic_id=req["topic_id"])
        return {"status": "opened", "reservation_id": req["reservation_id"], "contract_revision": approved["revision"], "units": sized["units"]}

    def _draw(self, draw: dict, inv_id: str, topic_id: str, now: str) -> None:
        """At a claim under a reservation: the checks G-5 names, then the draw.
        Revision-bound needs no check of its own here: an open reservation is
        bound to the approved revision the claim is admitted under (an
        approval closes the others), which the DDL checks again."""
        r = self._core._one("reservations", {"reservation_id": draw["reservation_id"]})
        if r is None or r["topic_id"] != topic_id or r["closed_at"] is not None:
            raise Refusal("reservation_closed", f"{draw['reservation_id']} is not an open reservation of {topic_id}")
        if len(self._core._store.select("reservation_draws", {"reservation_id": r["reservation_id"]})) >= r["units"]:
            raise Refusal("reservation_exhausted", f"{r['reservation_id']} holds {r['units']} admissions, all drawn")
        if r["purpose"] == "auto_promotion":
            facet = self._core._one("facets", {"topic_id": topic_id, "contract_revision": r["contract_revision"], "facet_id": draw.get("facet_id") or ""})
            if facet is None or BAND.get(facet["operator_importance_band"], 0) < BAND[r["min_band"]]:
                raise Refusal("reservation_invalid", f"auto-promotion is inside an existing facet rated {r['min_band']} or above by the operator (G-5)")
        self._core._store.insert("reservation_draws", {"invocation_id": inv_id, "reservation_id": r["reservation_id"], "facet_id": draw.get("facet_id"), "drawn_at": now})

    # -- the signal queue ----------------------------------------------------------
    def _review_in_transaction(self, req: dict, now: str) -> dict:
        stored = self._core._one("review_episodes", {"episode_id": req["episode_id"]})
        if stored is not None:
            if (stored["topic_id"], stored["kind"]) != (req["topic_id"], req["kind"]):
                raise Refusal("review_conflict", f"{req['episode_id']} is another review")
            return {"status": "replayed", "episode_id": req["episode_id"]}
        self._core._open_topic(req["topic_id"])
        pending = [t for t in self._core._store.select("review_triggers", {"topic_id": req["topic_id"]}) if t["episode_id"] is None and t["handled_at"] is None]
        if req["kind"] != "fixed_cadence" and not any(t["reason_code"] in MANDATORY for t in pending):
            if not pending:
                raise Refusal("no_pending_signal", "a signal-driven review takes pending signals; the cadence floor is fixed_cadence")
            bundle = self._core._active_bundle()
            queue = None if bundle is None else self._core._router_policy(bundle["bundle_hash"]).get("signal_queue")
            if queue is None:
                raise Refusal("not_configured", "the active bundle sets no signal-queue budget; the signals stay queued (G-10)")
            opened = sorted(instant(e["opened_at"]) for e in self._core._store.select("review_episodes", {"topic_id": req["topic_id"]}) if e["kind"] != "fixed_cadence")
            recent = [t for t in opened if t > instant(now) - int(queue["window_s"] * 10**9)]
            if len(recent) >= queue["budget"]:
                raise Refusal("signal_budget_spent", f"{len(recent)} signal reviews within {queue['window_s']} s; the signals stay queued")
            if opened and instant(now) < opened[-1] + int(queue["cooldown_s"] * 10**9):
                raise Refusal("signal_cooldown", f"the last signal review opened within {queue['cooldown_s']} s; the signals stay queued")
        generation = max((lease["generation"] for lease in self._core._store.select("leases", {"topic_id": req["topic_id"]})), default=0)  # work admitted later holds a later one
        self._core._store.insert("review_episodes", {"episode_id": req["episode_id"], "topic_id": req["topic_id"], "kind": req["kind"], "opened_at": now,
                                               "opened_after_generation": generation})
        for trigger in pending:
            self._core._store.update("review_triggers", {"trigger_identity": trigger["trigger_identity"]}, {"episode_id": req["episode_id"]})
        self._core._audit("review_opened", now, {"episode_id": req["episode_id"], "kind": req["kind"], "triggers": len(pending)}, topic_id=req["topic_id"])
        return {"status": "opened", "episode_id": req["episode_id"], "triggers": [t["trigger_identity"] for t in pending]}

    def _signal_in_transaction(self, req: dict, now: str) -> dict:
        """A code-policy signal (task 2a; G-12): a retraction or a
        decision-record change, raised by code policy or the operator (never
        by a model's observation: the store's CHECK), recorded pending in the
        topic's coalesced queue, where it exempts a signal-driven review from
        budget and cooldown (above). Key: its trigger identity — (topic,
        reason, cause, source revision), source_revision being the revision of
        the source the signal is about — so the same signal reported again
        collides with the first whatever became of it, and a handled one
        opens nothing (RG-1b(e))."""
        identity = boundary.trigger_identity(req["topic_id"], req)
        stored = self._core._one("review_triggers", {"trigger_identity": identity})
        if stored is not None:
            return {"status": "replayed", "trigger_identity": identity, "episode_id": stored["episode_id"], "handled_at": stored["handled_at"]}
        self._core._open_topic(req["topic_id"])
        if instant(req["observed_at"]) > instant(now):
            raise Refusal("request_invalid", f"a signal is observed by now ({now}), not at {req['observed_at']}")
        self._core._store.insert("review_triggers", {"trigger_identity": identity, **{k: req[k] for k in ("topic_id", "reason_code", "signal_source", "cause_ref", "observed_at")}})
        self._core._audit("signal_raised", now, {"trigger_identity": identity, "reason_code": req["reason_code"], "source": req["signal_source"]}, topic_id=req["topic_id"])
        return {"status": "recorded", "trigger_identity": identity, "episode_id": None, "handled_at": None}
