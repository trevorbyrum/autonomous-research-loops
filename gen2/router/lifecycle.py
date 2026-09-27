"""The router's side of the supervisor's lifecycle ends (task 1c): cancellation,
outcome_unknown reconciliation, the evidence both rest on, and the status
read the supervisor polls. A mixin of service.Router, so each operation keeps
the router's one shape: validate outside any transaction (reading staged
bytes only there), then one short transaction that fences and writes.

Trace: BOUNDARIES.md Station supervisor (never treat outcome_unknown as
vanished/failed/retryable/done without reconciliation; never trust agent
self-reported completion) and Router (sole writer); design review §5 ("Crash
fencing": resolve a crash between spawn and identity record by job lookup or
by terminating and reconciling the owned execution group; "Pause and
cancellation require a final launch-admission check and confirmed descendant
handling before releasing capacity"), §6 ("ambiguous outcomes create a
visible diagnostic/reconciliation state with an owner and deadline");
INVARIANTS L-1, L-4, L-5, L-7, L-9, C-9, C-10, H-3, RG-2, RG-3.

Evidence: a failure, a cancellation of launched work and every
reconciliation name the supervisor's execution record
(execution-record.schema.json), staged in the spool for the invocation's
topic. The router re-hashes it, validates it, and binds it before writing:
it is this invocation's and this job's record; its descendants were handled
(not "unconfirmed") wherever capacity is released or a terminal state is
reached (L-7); a failure's class is one of its findings; a reconciliation's
method is its method, and it supports the resolution (a live verified
process for found_running, the staged result with a clean exit for
found_result, a terminated group for terminated_group). The router checks
that the record says so; whether the record is true is the supervisor's
(its observations are the station's own, L-5), and is what the supervisor's
tests exercise with real processes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping

from gen2.core import instants
from gen2.router import boundary
from gen2.router.boundary import Refusal

# How long an outcome_unknown episode may stay unreconciled before its hold is
# overdue (the owner escalates). Execution policy (G-10): the mounted policy
# bundle owns it once 1d loads bundles.
UNKNOWN_HOLD_WINDOW = timedelta(hours=1)
RESOLUTION_TARGET = {"found_running": "running", "found_result": "result_ready", "confirmed_failed": "failed"}

_CAP = {"$ref": "common.schema.json#/$defs/capability_id"}
_INV = {"$ref": "common.schema.json#/$defs/invocation_id"}
_ID = {"$ref": "common.schema.json#/$defs/short_text"}
_SHA = {"$ref": "common.schema.json#/$defs/sha256"}
LIFECYCLE_COMMANDS = {
    "cancel": {
        "type": "object", "additionalProperties": False, "required": ["invocation_id", "requested_by", "reason"],
        "properties": {"invocation_id": _INV, "requested_by": {"enum": ["operator", "router", "supervisor"]}, "reason": _ID, "capability_id": _CAP},
        # the supervisor asks under the invocation's capability; operator and router requests come from the trusted surface (1e authenticates it)
        "if": {"properties": {"requested_by": {"const": "supervisor"}}}, "then": {"required": ["capability_id"]}, "else": {"not": {"required": ["capability_id"]}}},
    "reconcile": {
        "type": "object", "additionalProperties": False,
        "required": ["capability_id", "invocation_id", "unknown_episode", "resolution", "method", "evidence_ref"],
        "properties": {
            "capability_id": _CAP, "invocation_id": _INV, "unknown_episode": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
            "resolution": {"enum": ["found_running", "found_result", "confirmed_failed", "terminated_group"]},
            "method": {"enum": ["job_handle_lookup", "execution_group_termination"]}, "evidence_ref": _SHA,
            "result_payload_digest": _SHA, "failure_class": {"$ref": "execution-record.schema.json#/properties/findings/items"},
            "host_id": _ID, "container_id": {"oneOf": [{"type": "null"}, _ID]}, "boot_id": _ID, "start_fingerprint": _ID}},
    "status": {"type": "object", "additionalProperties": False, "required": ["capability_id", "invocation_id"],
               "properties": {"capability_id": _CAP, "invocation_id": _INV}},
}
IDENTITY = ("host_id", "container_id", "boot_id", "start_fingerprint")


def _after(now: str, delta: timedelta) -> str:
    seconds, rest = divmod(instants.utc_instant_ns(now), 10**9)
    moment = datetime.fromtimestamp(seconds, timezone.utc) + delta
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + f".{rest // 1000:06d}Z"


def unknown_hold_subject(invocation_id: str, episode: int) -> str:
    """The subject of an episode's router hold (DDL holds_reconciliation_clears_its_episode)."""
    return f"invocation:{invocation_id}#unknown:{episode}"


class Lifecycle:
    # -- evidence ------------------------------------------------------------
    def _evidence(self, inv: dict, content_hash: str) -> dict:
        """The execution record staged for the invocation's topic under this
        hash, re-hashed and validated (outside any transaction)."""
        raw = boundary.staged(self._spool, content_hash, topic_id=inv["topic_id"], media_type="application/json")
        doc = boundary.normalize(raw, "evidence_refused")
        boundary.require_schema(self._schemas, doc, "execution-record.schema.json", "evidence_refused")
        if (doc["invocation_id"], doc["topic_id"]) != (inv["invocation_id"], inv["topic_id"]):
            raise Refusal("evidence_refused", f"the execution record is {doc['invocation_id']}'s of {doc['topic_id']}")
        return {"content_hash": content_hash, "size_bytes": len(raw), "doc": doc}

    def _bind_evidence(self, inv: dict, evidence: dict | None, *, failure_class: str | None = None, terminal: bool = True) -> None:
        """What every end's evidence must say, against the row read under the
        lock: this job's record, descendants handled before capacity is
        released (L-7), a failure's class among its findings (L-5, L-9)."""
        if evidence is None:
            raise Refusal("evidence_refused", "an end of launched work names the supervisor's execution record")
        doc = evidence["doc"]
        if inv["job_handle"] is None or doc["job_handle"] != inv["job_handle"]:
            raise Refusal("evidence_refused", f"the execution record is of job {doc['job_handle']}, not {inv['job_handle']}")
        if terminal and doc["descendants"]["handling"] == "unconfirmed":
            raise Refusal("evidence_refused", "descendant handling is not confirmed; capacity is not released (L-7)")
        if failure_class is not None and failure_class not in doc["findings"]:
            raise Refusal("evidence_refused", f"{failure_class} is not among the execution record's findings {doc['findings']}")

    def _record_artifact(self, inv: dict, evidence: dict, now: str) -> None:
        stored = self._one("artifacts", {"content_hash": evidence["content_hash"]})
        if stored is None:
            self._store.insert("artifacts", {"content_hash": evidence["content_hash"], "size_bytes": evidence["size_bytes"], "media_type": "application/json",
                                             "topic_id": inv["topic_id"], "staged_by_invocation_id": inv["invocation_id"], "staged_at": now})
        elif (stored["size_bytes"], stored["media_type"]) != (evidence["size_bytes"], "application/json"):
            raise Refusal("evidence_refused", f"{evidence['content_hash']} is recorded as {stored['size_bytes']} bytes of {stored['media_type']}")

    # -- capacity and holds --------------------------------------------------
    def _release_capacity(self, inv: dict, now: str, reason: str) -> None:
        """A failed or cancelled non-delegate releases its lease (a delegate
        runs under its parent's); a research lease returns an active topic to
        the queue. Called only once the end's descendant handling is
        confirmed (L-7)."""
        if inv["kind"] == "delegate":
            return
        lease = self._one("leases", {"lease_id": inv["lease_id"]})
        if lease["released_at"] is None:
            self._store.update("leases", {"lease_id": lease["lease_id"]}, {"released_at": now, "release_reason": reason})
            topic = self._one("queue_entries", {"topic_id": inv["topic_id"]})
            if lease["scope"] == "research" and topic["status"] == "active":
                self._set_topic(topic, now, "queued")

    def _open_unknown_hold(self, inv: dict, episode: int, cause: str, now: str) -> None:
        """The episode's typed hold: class unknown, the router's to clear
        (through the episode's reconciliation record), owned by the station
        that holds the job, with a deadline (H-3, RG-3)."""
        station = self._lease_of(inv)["station_id"]
        self._store.insert("holds", {
            "hold_id": self._new_id("hold_"), "topic_id": inv["topic_id"], "subject_ref": unknown_hold_subject(inv["invocation_id"], episode),
            "hold_class": "unknown", "cause": f"outcome_unknown ({cause})", "recoverability": "unknown", "required_authority": "router",
            "owner": f"supervisor:{station}", "deadline_at": _after(now, UNKNOWN_HOLD_WINDOW),
            "clears_when": f"the reconciliation record of episode {episode}: a job-handle lookup or the termination of the execution group",
            "capability_fact_id": None, "created_at": now, "created_by_operation_id": None})

    # -- cancellation --------------------------------------------------------
    def request_cancel(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._schemas, req, "router-commands#/$defs/cancel", "request_invalid")
            return self._guarded("transition_not_allowed", lambda now: self._cancel_in_transaction(req, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _cancel_in_transaction(self, req: dict, now: str) -> dict:
        inv = self._one("invocations", {"invocation_id": req["invocation_id"]})
        if inv is None:
            raise Refusal("unknown_invocation", req["invocation_id"])
        if req["requested_by"] == "supervisor":
            self._capability(req["capability_id"], req["invocation_id"])
        if inv["cancel_requested_at"] is not None:  # the key is the invocation; its request is write-once
            if inv["cancel_requested_by"] != req["requested_by"]:
                raise Refusal("cancel_conflict", f"cancellation was requested by {inv['cancel_requested_by']} at {inv['cancel_requested_at']}")
            return {"status": "replayed", "invocation_id": inv["invocation_id"], "state": inv["state"]}
        if inv["state"] not in ("admitted", "launching", "running", "outcome_unknown"):
            raise Refusal("not_cancellable", f"{inv['invocation_id']} is {inv['state']}: a staged result or a recorded end wins the race")
        changes = {"cancel_requested_at": now, "cancel_requested_by": req["requested_by"]}
        if inv["state"] == "admitted":  # no launch intent, so nothing was spawned (L-2): no descendant can exist
            changes.update(state="cancelled", state_changed_at=now, descendants_confirmed_at=now)
        self._store.update("invocations", {"invocation_id": inv["invocation_id"]}, changes)
        if inv["state"] == "admitted":
            self._transition_row(inv["invocation_id"], "admitted", "cancelled", now, "cancelled_before_launch")
            self._release_capacity(inv, now, "cancelled")
        self._audit("cancel_requested", now, {"by": req["requested_by"], "reason": req["reason"], "state": inv["state"]},
                    topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
        return {"status": "cancelled" if inv["state"] == "admitted" else "recorded", "invocation_id": inv["invocation_id"],
                "state": "cancelled" if inv["state"] == "admitted" else inv["state"]}

    # -- reconciliation ------------------------------------------------------
    def reconcile(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._schemas, req, "router-commands#/$defs/reconcile", "request_invalid")
            identity = {k: req.get(k) for k in IDENTITY if k in req}
            wants_identity = req["resolution"] == "found_running"
            # a failure class is a confirmed failure's, never a found process's or result's; a terminated group carries one
            # exactly when it ends failed — under a cancellation request it ends cancelled, with none (checked in the
            # transaction, against the row: Astra 1c review A2)
            if (req["resolution"] == "found_result") != ("result_payload_digest" in req) or bool(identity) != wants_identity \
                    or (wants_identity and set(identity) - {"container_id"} != {"host_id", "boot_id", "start_fingerprint"}) \
                    or ("failure_class" in req and req["resolution"] in ("found_running", "found_result")) \
                    or ("failure_class" not in req and req["resolution"] == "confirmed_failed"):
                raise Refusal("request_invalid", f"{req['resolution']} carries exactly the facts it resolves to (identity, result digest or failure class)")
            replay = self._recorded_reconciliation(req)  # before any byte: a recorded episode answers from its row (as A5-R)
            if replay is not None:
                return replay
            inv = self._capability(req["capability_id"], req["invocation_id"])
            evidence = self._evidence(inv, req["evidence_ref"])
            if req["resolution"] == "found_result":
                boundary.staged(self._spool, req["result_payload_digest"], topic_id=inv["topic_id"], media_type="application/json")
            return self._guarded("transition_not_allowed", lambda now: self._reconcile_in_transaction(req, identity, evidence, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _recorded_reconciliation(self, req: dict) -> dict | None:
        row = self._one("invocation_reconciliations", {"invocation_id": req["invocation_id"], "unknown_episode": req["unknown_episode"]})
        if row is None:
            return None
        inv = self._capability(req["capability_id"], req["invocation_id"])
        same = (row["resolution"], row["method"], row["evidence_ref"], row["result_payload_digest"]) == (
            req["resolution"], req["method"], req["evidence_ref"], req.get("result_payload_digest"))
        if not same:
            raise Refusal("reconciliation_conflict", f"episode {req['unknown_episode']} of {inv['invocation_id']} was reconciled otherwise")
        return {"status": "replayed", "invocation_id": inv["invocation_id"], "unknown_episode": req["unknown_episode"], "resolution": row["resolution"]}

    def _reconcile_in_transaction(self, req: dict, identity: dict, evidence: dict, now: str) -> dict:
        replay = self._recorded_reconciliation(req)
        if replay is not None:
            return replay
        inv = self._capability(req["capability_id"], req["invocation_id"])
        if inv["state"] != "outcome_unknown" or inv["unknown_episode"] != req["unknown_episode"]:
            raise Refusal("transition_not_allowed", f"{inv['invocation_id']} is {inv['state']} in episode {inv['unknown_episode']}, not in episode {req['unknown_episode']}")
        resolution, doc = req["resolution"], evidence["doc"]
        if doc["method"] != req["method"]:
            raise Refusal("evidence_refused", f"the execution record's method is {doc['method']}, not {req['method']}")
        target = RESOLUTION_TARGET.get(resolution) or ("cancelled" if inv["cancel_requested_at"] is not None else "failed")
        if resolution == "terminated_group" and ("failure_class" in req) != (target == "failed"):
            if target == "cancelled":  # no failure class is invented for a cancellation (Q5 ruling)
                raise Refusal("cancel_requested", f"cancellation was requested at {inv['cancel_requested_at']}: the group's end is a cancellation, with no failure class")
            raise Refusal("request_invalid", "no cancellation was requested: a terminated group ends failed, with its failure class")
        terminal = target in ("failed", "cancelled")
        self._bind_evidence(inv, evidence, failure_class=req.get("failure_class") if target == "failed" else None, terminal=terminal)
        changes = {"state": target, "state_changed_at": now}
        if resolution == "found_running":  # a live process, verified by its identity (never a PID alone, L-3)
            if doc["process"] is None or doc["exit"] is not None or {k: doc["process"][k] for k in IDENTITY} != {k: identity.get(k) for k in IDENTITY}:
                raise Refusal("evidence_refused", "found_running needs the record of a live process with exactly this identity")
            changes.update({k: identity.get(k) for k in IDENTITY})
        elif resolution == "found_result":
            output = doc["output"]
            if output["status"] != "present" or output["content_hash"] != req["result_payload_digest"] or doc["findings"] or doc["exit"] != {"code": 0, "signal": None}:
                raise Refusal("evidence_refused", "found_result needs a clean exit whose collected output is exactly this result")
            if inv["cancel_requested_at"] is not None:
                raise Refusal("cancel_requested", f"cancellation was requested at {inv['cancel_requested_at']}; the result stays retained")
            changes.update(result_payload_digest=req["result_payload_digest"], result_staged_at=now)
        # terminated_group: the record's method is execution_group_termination (checked above), which the schema
        # admits only with its termination recorded (execution-record.schema.json allOf)
        if terminal:
            changes["end_evidence_ref"] = evidence["content_hash"]
            if target == "failed":
                changes["failure_class"] = req["failure_class"]
            else:
                changes["descendants_confirmed_at"] = now
        self._record_artifact(inv, evidence, now)
        reconciliation_id = self._new_id("rec_")
        self._store.insert("invocation_reconciliations", {
            "reconciliation_id": reconciliation_id, "invocation_id": inv["invocation_id"], "unknown_episode": inv["unknown_episode"],
            "unknown_since": inv["outcome_unknown_since"], "resolution": resolution, "method": req["method"], "evidence_ref": evidence["content_hash"],
            "result_payload_digest": req.get("result_payload_digest"), "descendants_confirmed_at": now if terminal else None, "resolved_at": now})
        self._store.update("invocations", {"invocation_id": inv["invocation_id"]}, changes)
        self._transition_row(inv["invocation_id"], "outcome_unknown", target, now, "reconciled")
        subject = unknown_hold_subject(inv["invocation_id"], inv["unknown_episode"])
        for hold in self._store.select("holds", {"topic_id": inv["topic_id"], "subject_ref": subject}):
            if hold["cleared_at"] is None:
                self._store.update("holds", {"hold_id": hold["hold_id"]}, {"cleared_at": now, "cleared_by_reconciliation_id": reconciliation_id})
        if terminal:
            self._release_capacity(inv, now, target)
        self._audit("reconciled", now, {"episode": inv["unknown_episode"], "resolution": resolution, "to": target},
                    topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
        return {"status": "recorded", "invocation_id": inv["invocation_id"], "unknown_episode": inv["unknown_episode"], "resolution": resolution, "state": target}

    # -- status --------------------------------------------------------------
    def invocation_status(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._schemas, req, "router-commands#/$defs/status", "request_invalid")
            inv = self._capability(req["capability_id"], req["invocation_id"])
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}
        lease = self._lease_of(inv)
        topic = self._one("queue_entries", {"topic_id": inv["topic_id"]})
        finals = [r["operation_id"] for r in self._store.select("operation_receipts", {"invocation_id": inv["invocation_id"]})
                  if r["operation_kind"] == "final_outcome"]
        refusal = self._launch_refusal(inv, self._now())  # the current launch-admission check (L-7), for every actual start
        return {"status": "ok", "invocation_id": inv["invocation_id"], "kind": inv["kind"], "topic_id": inv["topic_id"], "state": inv["state"],
                "deadline_at": inv["deadline_at"], "job_handle": inv["job_handle"], "identity": {k: inv[k] for k in IDENTITY},
                "result_payload_digest": inv["result_payload_digest"], "failure_class": inv["failure_class"],
                "cancel_requested": None if inv["cancel_requested_at"] is None else {"at": inv["cancel_requested_at"], "by": inv["cancel_requested_by"]},
                "unknown_episode": inv["unknown_episode"], "outcome_unknown_since": inv["outcome_unknown_since"],
                "lease": {"lease_id": lease["lease_id"], "generation": lease["generation"], "expires_at": lease["expires_at"], "released_at": lease["released_at"]},
                "topic_paused": topic["paused_at"] is not None, "state_revision": topic["state_revision"], "final_operation_id": finals[0] if finals else None,
                "launch_admission": None if refusal is None else {"reason": refusal.reason, "detail": refusal.detail[:500]}}
