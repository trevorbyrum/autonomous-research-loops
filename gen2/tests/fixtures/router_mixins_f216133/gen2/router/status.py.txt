"""The operator's status read and the health probe (task 1e). A mixin of
service.Router: reads only. Neither writes a row, an audit event included.

Trace: BOUNDARIES.md Operator (interface guarantees: typed holds with owners
and deadlines; status that answers why every waiting item waits; dated
capability facts), Router (the sole writer: status is served from its store,
never from a copy elsewhere, P-3); INVARIANTS RG-9 and H-4 (status explains
waiting), H-2 (capability facts), H-3 (holds), L-4 (outcome_unknown and its
reconciliation), L-6 and RG-3 (re-queues and their budget holds), G-1, G-4,
G-5, C-12 (pins, briefs, reservations); DEPLOYMENT-CONTRACT.md §1.2 (the
engine is healthy when the router can commit); the 1d carry (status for
re-queues, reservations and holds).

`status` is the committed record in one snapshot (one transaction that writes
nothing), per topic: its queue row, the brief versions still standing, the
contract drafts awaiting approval, the open holds, its live invocations, the
last work of each of its lanes, its open reservations, its pending signals
and open reviews; and, engine-wide, the active and pinned config bundles, the
current capability facts and the open holds of no topic (task 1f: a
capability's, capabilities.py). Beside the rows it gives what the router
itself would decide now, from the same helpers its operations decide with,
so status and the next operation cannot disagree: an invocation's
launch-admission check (L-7), how its pins stand after any amendment
(amendment_pending exactly when a commit would be refused as that, G-1), and
whether its lease and deadline are over at the router's time. Composing that
into "why each item waits" is the operator surface's (gen2/operator/status.py).
"""
from __future__ import annotations

from typing import Mapping

from gen2.router import boundary
from gen2.router.amendments import COMPATIBLE
from gen2.router.boundary import Refusal, instant

LIVE = ("admitted", "launching", "running", "result_ready", "outcome_unknown")
STATUS_COMMANDS = {"operator_status": {"type": "object", "additionalProperties": False,
                                       "properties": {"topic_id": {"$ref": "common.schema.json#/$defs/topic_id"}}}}
HOLD = ("hold_id", "subject_ref", "hold_class", "cause", "recoverability", "required_authority", "owner", "deadline_at", "clears_when",
        "capability_fact_id", "created_at")


def _pick(row: dict, keys) -> dict:
    return {k: row[k] for k in keys}


class Status:
    def healthy(self) -> bool:
        """The router can take its store's write lock now (DEPLOYMENT-CONTRACT.md
        §1.2: healthy means the router can commit). Nothing is written."""
        try:
            with self._store.transaction():
                self._now()
            return True
        except Exception:  # an unhealthy answer, never a crash of the health route
            return False

    def status(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._schemas, req, "router-commands#/$defs/operator_status", "request_invalid")
            with self._store.transaction():  # one snapshot; nothing is written
                now = self._now()
                topics = self._store.select("queue_entries", {"topic_id": req["topic_id"]} if "topic_id" in req else None)
                if "topic_id" in req and not topics:
                    raise Refusal("unknown_topic", req["topic_id"])
                live = [i for i in self._store.select("invocations") if i["state"] in LIVE]
                active = self._active_bundle()
                pinned = {}
                for inv in live:
                    pinned.setdefault(inv["config_bundle_hash"], []).append(inv["invocation_id"])
                return {
                    "status": "ok", "at": now,
                    "topics": [self._topic_facts(t, now) for t in sorted(topics, key=lambda t: t["topic_id"])],
                    "config_bundles": {
                        "active": None if active is None else _pick(active, ("bundle_hash", "version", "activated_at")),
                        "pinned": [{**_pick(self._one("config_bundles", {"bundle_hash": h}), ("bundle_hash", "version", "status")), "invocations": sorted(ids)}
                                   for h, ids in sorted(pinned.items())]},
                    "capability_facts": [_pick(f, ("fact_id", "capability", "state", "detail", "since", "last_success_at", "affected_lanes"))
                                         for f in sorted(self._store.select("capability_facts"), key=lambda f: f["capability"])
                                         if f["superseded_by_fact_id"] is None],
                    "holds": [{**_pick(h, HOLD), "deadline_passed": instant(now) >= instant(h["deadline_at"])}  # open holds of no topic (task 1f: a capability's)
                              for h in sorted(self._store.select("holds"), key=lambda h: h["created_at"]) if h["topic_id"] is None and h["cleared_at"] is None]}
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _topic_facts(self, topic: dict, now: str) -> dict:
        tid = topic["topic_id"]
        where = {"topic_id": tid}
        invocations = self._store.select("invocations", where)
        retries = self._store.select("retries", where)
        holds = [h for h in self._store.select("holds", where) if h["cleared_at"] is None]
        reservations = [r for r in self._store.select("reservations", where) if r["closed_at"] is None]
        return {
            **_pick(topic, ("topic_id", "status", "state_revision", "paused_at", "active_contract_revision")),
            "briefs": [{**_pick(b, ("brief_id", "version", "status", "review_deadline", "overdue_since")), "owner": b["owner_operator_id"],
                        "deadline_passed": instant(now) >= instant(b["review_deadline"])}
                       for b in sorted(self._store.select("intake_briefs", where), key=lambda b: (b["brief_id"], b["version"]))
                       if b["status"] in ("awaiting_confirmation", "confirmed")],
            "drafts": self._drafts(tid),
            "holds": [{**_pick(h, HOLD), "deadline_passed": instant(now) >= instant(h["deadline_at"])} for h in sorted(holds, key=lambda h: h["created_at"])],
            "invocations": [self._invocation_facts(i, now, holds, retries) for i in sorted(invocations, key=lambda i: i["admitted_at"]) if i["state"] in LIVE],
            "lanes": self._lane_facts(tid, invocations, retries, holds),
            "reservations": [{**_pick(r, ("reservation_id", "purpose", "contract_revision", "units", "min_band", "opened_at")),
                              "drawn": len(self._store.select("reservation_draws", {"reservation_id": r["reservation_id"]}))} for r in reservations],
            "signals": [{**_pick(t, ("trigger_identity", "reason_code", "signal_source", "observed_at"))}
                        for t in self._store.select("review_triggers", where) if t["episode_id"] is None and t["handled_at"] is None],
            "reviews": [_pick(e, ("episode_id", "kind", "opened_at")) for e in self._store.select("review_episodes", where) if e["closed_at"] is None]}

    def _drafts(self, tid: str) -> list[dict]:
        """The contract drafts an approval could still approve (service.Router
        _approve_contract): with none approved, every draft; otherwise those
        revising the approved revision. An older draft never can be: it waits
        for nothing, and is not listed."""
        revisions = self._store.select("contract_revisions", {"topic_id": tid})
        approved = next((c["revision"] for c in revisions if c["status"] == "approved"), None)
        return [_pick(c, ("revision", "parent_revision", "created_at")) for c in sorted(revisions, key=lambda c: c["revision"])
                if c["status"] == "draft" and (approved is None or c["parent_revision"] == approved)]

    def _invocation_facts(self, inv: dict, now: str, holds: list[dict], retries: list[dict]) -> dict:
        lease = self._lease_of(inv)
        standing = self._pin_status(inv)
        episode_hold = next((h for h in holds if h["subject_ref"] == f"invocation:{inv['invocation_id']}#unknown:{inv['unknown_episode']}"), None)
        launch = self._launch_refusal(inv, now) if inv["state"] in ("admitted", "launching") else None
        retry = next((r for r in retries if r["retry_invocation_id"] == inv["invocation_id"]), None)
        draw = self._one("reservation_draws", {"invocation_id": inv["invocation_id"]})
        return {
            **_pick(inv, ("invocation_id", "kind", "state", "parent_invocation_id", "deadline_at", "config_bundle_hash", "result_payload_digest")),
            "deadline_passed": instant(now) >= instant(inv["deadline_at"]),
            "lease": {**_pick(lease, ("lease_id", "scope", "generation", "station_id", "expires_at", "released_at")),
                      "expired": instant(now) >= instant(lease["expires_at"])},
            "admission": self._admission_json(inv),
            "pins": {"standing": standing, "incompatible": standing not in COMPATIBLE, "current": self._current_pins(inv) if standing != "current" else None},
            "cancel_requested": None if inv["cancel_requested_at"] is None else {"at": inv["cancel_requested_at"], "by": inv["cancel_requested_by"]},
            "launch_admission": None if launch is None else {"reason": launch.reason, "detail": launch.detail[:500]},
            "unknown": None if inv["state"] != "outcome_unknown" else {
                "episode": inv["unknown_episode"], "since": inv["outcome_unknown_since"], "reconciliation": "pending",
                "hold": None if episode_hold is None else _pick(episode_hold, ("hold_id", "owner", "deadline_at", "clears_when"))},
            "reconciliations": [_pick(r, ("unknown_episode", "resolution", "method", "resolved_at"))
                                for r in self._store.select("invocation_reconciliations", {"invocation_id": inv["invocation_id"]})],
            "retry": None if retry is None else {"of": retry["invocation_id"], "attempt": retry["attempt"], "requested_by": retry["requested_by"]},
            "reservation": None if draw is None else draw["reservation_id"]}

    def _current_pins(self, inv: dict) -> dict | None:
        """What superseded the invocation's pin: the topic's approved contract
        revision (or confirmed brief version), with the decision approving it."""
        if inv["admission_context"] == "contract/1":
            current = self._one("contract_revisions", {"topic_id": inv["topic_id"], "status": "approved"})
            return None if current is None else {"contract_revision": current["revision"], "approved_by_decision_id": current["approved_by_decision_id"]}
        current = self._one("intake_briefs", {"topic_id": inv["topic_id"], "status": "confirmed"})
        return None if current is None else {"brief_id": current["brief_id"], "version": current["version"],
                                             "confirmed_by_decision_id": current["confirmed_by_decision_id"]}

    def _lane_facts(self, tid: str, invocations: list[dict], retries: list[dict], holds: list[dict]) -> list[dict]:
        """Each lane's last work (scheduling.py: a lane whose last work ended
        failed or cancelled is claimed again only as its re-queued retry), and
        where its re-queue stands: none yet, recorded and not yet claimed, or
        held by an exhausted budget's operator hold (L-6, RG-3)."""
        lanes = []
        for scope in sorted({lease["scope"] for lease in self._store.select("leases", {"topic_id": tid})}):
            last = self._lane_last(tid, scope)
            inv = next(i for i in invocations if i["invocation_id"] == last)
            lane = {"scope": scope, "last_invocation_id": last, "state": inv["state"], "requeue": None, "requeue_hold": None}
            if inv["state"] in ("failed", "cancelled"):
                retry = next((r for r in retries if r["invocation_id"] == last), None)
                hold = next((h for h in holds if h["subject_ref"] == f"invocation:{last}#requeue"), None)
                lane.update(failure_class=inv["failure_class"], cancel_requested_by=inv["cancel_requested_by"],
                            requeue=None if retry is None else {"attempt": retry["attempt"], "requested_by": retry["requested_by"], "claimed_by": retry["retry_invocation_id"]},
                            requeue_hold=None if hold is None else _pick(hold, ("hold_id", "owner", "deadline_at", "clears_when")))
            lanes.append(lane)
        return lanes
