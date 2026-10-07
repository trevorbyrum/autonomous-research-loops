"""The router's side of the supervisor's lifecycle ends (task 1c): cancellation,
outcome_unknown reconciliation, the evidence both rest on, and the status
read the supervisor polls. A collaborator of service.Router (task 2q-b6:
"Router composition", BOUNDARIES.md), with the router's one shape: validate
outside any transaction (reading staged bytes only there), then one short
transaction (the core's: `_guarded`) that fences and writes.

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

import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Mapping, Protocol

from gen2.core import instants
from gen2.router import boundary
from gen2.router.boundary import Refusal

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


def _after(now: str, seconds: float) -> str:
    """The instant `seconds` after `now`, in exact nanoseconds: a duration's
    fraction of a second is kept and carries into the seconds (a hold window
    of 0.5 s is half a second, Astra 1d review finding 4). A duration is the
    decimal it is written as (config-bundle/1 seconds); a fraction finer than
    a nanosecond rounds up, so a positive window is never zero."""
    total = instants.utc_instant_ns(now) + math.ceil(Decimal(repr(seconds)) * 10**9)
    whole, rest = divmod(total, 10**9)
    return datetime.fromtimestamp(whole, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{rest:09d}Z"


def unknown_hold_subject(invocation_id: str, episode: int) -> str:
    """The subject of an episode's router hold (DDL holds_reconciliation_clears_its_episode)."""
    return f"invocation:{invocation_id}#unknown:{episode}"


def is_episode_hold(hold: dict) -> bool:
    """A router hold with an episode's subject: it clears only through that
    episode's reconciliation record (DDL holds_episode_cleared_only_by_reconciliation,
    whose GLOB 'invocation:*#unknown:*' this matches; Astra 1c review A7)."""
    subject = hold["subject_ref"]
    return hold["required_authority"] == "router" and subject.startswith("invocation:") and "#unknown:" in subject[len("invocation:"):]


class Rows(Protocol):
    """The router's store as the lifecycle uses it (store/api.py Store): writes only inside the core's transaction; reads there too, but `invocation_status` and `reconcile`'s first reads take none."""
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...
    def update(self, table: str, key: Mapping[str, object], changes: Mapping[str, object]) -> None: ...


class Schemas(Protocol):
    """The router's schema set as boundary.require_schema uses it (schemas.py SchemaSet)."""
    def errors(self, instance: object, target: str) -> list[str]: ...


class Spool(Protocol):
    """The router's spool as boundary.staged uses it: reads only (supervisor/spool.py Spool)."""
    def read(self, content_hash: str, *, topic_id: str) -> bytes | None: ...
    def media_type(self, content_hash: str, *, topic_id: str) -> str | None: ...


class LifecycleCore(Protocol):
    """What the lifecycle takes of the router core, and nothing else; service.Router
    implements it without inheriting it. Every member is the core's own (service.py).
    The lifecycle's own members the rest of the Router reads (`_evidence`, `_bind_evidence`,
    `_record_artifact`, `_require_delegates_ended`, `_release_capacity`, `_open_unknown_hold`,
    `_cancel_in_transaction`) are the core's delegating members, so no other mixin or
    collaborator reaches the lifecycle but through the core."""
    _store: Rows
    _spool: Spool
    _schemas: Schemas
    _new_id: Callable[[str], str]
    _fault: Callable[[str], None]
    def _now(self) -> str: ...
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...
    def _guarded(self, reason: str, body: Callable[[str], object]) -> object: ...  # the one transaction an operation runs in
    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str: ...
    def _capability(self, capability_id: str, invocation_id: str) -> dict: ...
    def _lease_of(self, inv: dict) -> dict: ...
    def _launch_refusal(self, inv: dict, now: str) -> Refusal | None: ...
    def _authorize_artifact(self, content_hash: str, inv: dict, now: str) -> None: ...
    def _set_topic(self, topic: dict, now: str, status: str | None = None, **columns) -> int: ...
    def _transition_row(self, invocation_id: str, from_state: str | None, to_state: str, at: str, cause: str, facts: dict | None = None) -> None: ...
    def _router_policy(self, bundle_hash: str) -> dict: ...


class Lifecycle:
    def __init__(self, core: LifecycleCore) -> None:
        self._core = core

    # -- evidence ------------------------------------------------------------
    def _evidence(self, inv: dict, content_hash: str) -> dict:
        """The execution record staged for the invocation's topic under this
        hash, re-hashed and validated (outside any transaction)."""
        raw = boundary.staged(self._core._spool, content_hash, topic_id=inv["topic_id"], media_type="application/json")
        doc = boundary.normalize(raw, "evidence_refused")
        boundary.require_schema(self._core._schemas, doc, "execution-record.schema.json", "evidence_refused")
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
        stored = self._core._one("artifacts", {"content_hash": evidence["content_hash"]})
        if stored is None:
            self._core._store.insert("artifacts", {"content_hash": evidence["content_hash"], "size_bytes": evidence["size_bytes"], "media_type": "application/json",
                                             "topic_id": inv["topic_id"], "staged_by_invocation_id": inv["invocation_id"], "staged_at": now})
        elif (stored["size_bytes"], stored["media_type"]) != (evidence["size_bytes"], "application/json"):
            raise Refusal("evidence_refused", f"{evidence['content_hash']} is recorded as {stored['size_bytes']} bytes of {stored['media_type']}")
        self._core._authorize_artifact(evidence["content_hash"], inv, now)  # staged in the invocation's topic (_evidence reads it there)

    # -- capacity and holds --------------------------------------------------
    def _require_delegates_ended(self, inv: dict) -> None:
        """A non-delegate's lease is its delegates' too (L-8): it is released
        only once every delegate admitted under it has ended (committed,
        failed or cancelled) — the parent's own descendant check cannot see a
        delegate, which runs in its own supervisor-owned session (L-7; Astra
        1c review A3)."""
        live = sorted(d["invocation_id"] for d in self._core._store.select("invocations", {"parent_invocation_id": inv["invocation_id"]})
                      if d["state"] not in ("committed", "failed", "cancelled"))
        if live:
            raise Refusal("delegates_live", f"{inv['invocation_id']}'s delegates {', '.join(live)} have not ended; its lease is theirs too (L-7, L-8)")

    def _release_capacity(self, inv: dict, now: str, reason: str) -> None:
        """A failed or cancelled non-delegate releases its lease (a delegate
        runs under its parent's); a research lease returns an active topic to
        the queue. Called only once the end's descendant handling is
        confirmed (L-7), and refused while a delegate still runs under it."""
        if inv["kind"] == "delegate":
            return
        self._require_delegates_ended(inv)
        lease = self._core._one("leases", {"lease_id": inv["lease_id"]})
        if lease["released_at"] is None:
            self._core._store.update("leases", {"lease_id": lease["lease_id"]}, {"released_at": now, "release_reason": reason})
            topic = self._core._one("queue_entries", {"topic_id": inv["topic_id"]})
            if lease["scope"] == "research" and topic["status"] == "active":
                self._core._set_topic(topic, now, "queued")

    def _open_unknown_hold(self, inv: dict, episode: int, cause: str, now: str) -> None:
        """The episode's typed hold: class unknown, the router's to clear
        (through the episode's reconciliation record), owned by the station
        that holds the job, with a deadline: the hold window of the bundle the
        invocation is pinned to (G-10, RG-9; shipped default one hour) (H-3,
        RG-3)."""
        station = self._core._lease_of(inv)["station_id"]
        window = self._core._router_policy(inv["config_bundle_hash"])["hold_window_s"]
        self._core._store.insert("holds", {
            "hold_id": self._core._new_id("hold_"), "topic_id": inv["topic_id"], "subject_ref": unknown_hold_subject(inv["invocation_id"], episode),
            "hold_class": "unknown", "cause": f"outcome_unknown ({cause})", "recoverability": "unknown", "required_authority": "router",
            "owner": f"supervisor:{station}", "deadline_at": _after(now, window),
            "clears_when": f"the reconciliation record of episode {episode}: a job-handle lookup or the termination of the execution group",
            "capability_fact_id": None, "created_at": now, "created_by_operation_id": None})

    # -- cancellation --------------------------------------------------------
    def request_cancel(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._core._schemas, req, "router-commands#/$defs/cancel", "request_invalid")
            return self._core._guarded("transition_not_allowed", lambda now: self._cancel_in_transaction(req, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _cancel_in_transaction(self, req: dict, now: str) -> dict:
        inv = self._core._one("invocations", {"invocation_id": req["invocation_id"]})
        if inv is None:
            raise Refusal("unknown_invocation", req["invocation_id"])
        if req["requested_by"] == "supervisor":
            self._core._capability(req["capability_id"], req["invocation_id"])
        if inv["cancel_requested_at"] is not None:  # the key is the invocation; its request is write-once
            if inv["cancel_requested_by"] != req["requested_by"]:
                raise Refusal("cancel_conflict", f"cancellation was requested by {inv['cancel_requested_by']} at {inv['cancel_requested_at']}")
            return {"status": "replayed", "invocation_id": inv["invocation_id"], "state": inv["state"]}
        if inv["state"] not in ("admitted", "launching", "running", "outcome_unknown"):
            raise Refusal("not_cancellable", f"{inv['invocation_id']} is {inv['state']}: a staged result or a recorded end wins the race")
        changes = {"cancel_requested_at": now, "cancel_requested_by": req["requested_by"]}
        if inv["state"] == "admitted":  # no launch intent, so nothing was spawned (L-2): no descendant can exist
            changes.update(state="cancelled", state_changed_at=now, descendants_confirmed_at=now)
        self._core._store.update("invocations", {"invocation_id": inv["invocation_id"]}, changes)
        if inv["state"] == "admitted":
            self._core._transition_row(inv["invocation_id"], "admitted", "cancelled", now, "cancelled_before_launch")
            self._release_capacity(inv, now, "cancelled")
        self._core._audit("cancel_requested", now, {"by": req["requested_by"], "reason": req["reason"], "state": inv["state"]},
                    topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
        return {"status": "cancelled" if inv["state"] == "admitted" else "recorded", "invocation_id": inv["invocation_id"],
                "state": "cancelled" if inv["state"] == "admitted" else inv["state"]}

    # -- reconciliation ------------------------------------------------------
    def reconcile(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._core._schemas, req, "router-commands#/$defs/reconcile", "request_invalid")
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
            self._core._fault("reconcile_checked")
            inv = self._core._capability(req["capability_id"], req["invocation_id"])
            evidence = self._evidence(inv, req["evidence_ref"])
            if req["resolution"] == "found_result":
                boundary.staged(self._core._spool, req["result_payload_digest"], topic_id=inv["topic_id"], media_type="application/json")
            return self._core._guarded("transition_not_allowed", lambda now: self._reconcile_in_transaction(req, identity, evidence, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    @staticmethod
    def _reconciliation_facts(req: dict) -> dict:
        """The complete normalized factual request of a reconciliation: every
        fact it asserts, absent ones as none (Astra 1c review A8)."""
        return {k: req.get(k) for k in ("resolution", "method", "evidence_ref", "result_payload_digest", "failure_class", *IDENTITY)}

    def _recorded_reconciliation(self, req: dict) -> dict | None:
        row = self._core._one("invocation_reconciliations", {"invocation_id": req["invocation_id"], "unknown_episode": req["unknown_episode"]})
        if row is None:
            return None
        inv = self._core._capability(req["capability_id"], req["invocation_id"])
        if row["request"] != self._reconciliation_facts(req):  # the identical request replays; any other fact is a conflict, not a replay
            changed = sorted(k for k, v in self._reconciliation_facts(req).items() if row["request"].get(k) != v)
            raise Refusal("reconciliation_conflict", f"episode {req['unknown_episode']} of {inv['invocation_id']} was reconciled otherwise ({', '.join(changed)})")
        return {"status": "replayed", "invocation_id": inv["invocation_id"], "unknown_episode": req["unknown_episode"], "resolution": row["resolution"]}

    def _reconcile_in_transaction(self, req: dict, identity: dict, evidence: dict, now: str) -> dict:
        replay = self._recorded_reconciliation(req)
        if replay is not None:
            return replay
        inv = self._core._capability(req["capability_id"], req["invocation_id"])
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
        reconciliation_id = self._core._new_id("rec_")
        self._core._store.insert("invocation_reconciliations", {
            "reconciliation_id": reconciliation_id, "invocation_id": inv["invocation_id"], "unknown_episode": inv["unknown_episode"],
            "unknown_since": inv["outcome_unknown_since"], "resolution": resolution, "method": req["method"], "evidence_ref": evidence["content_hash"],
            "result_payload_digest": req.get("result_payload_digest"), "descendants_confirmed_at": now if terminal else None, "resolved_at": now,
            "request": self._reconciliation_facts(req)})
        self._core._store.update("invocations", {"invocation_id": inv["invocation_id"]}, changes)
        self._core._transition_row(inv["invocation_id"], "outcome_unknown", target, now, "reconciled")
        subject = unknown_hold_subject(inv["invocation_id"], inv["unknown_episode"])
        for hold in self._core._store.select("holds", {"topic_id": inv["topic_id"], "subject_ref": subject}):
            if hold["cleared_at"] is None:
                self._core._store.update("holds", {"hold_id": hold["hold_id"]}, {"cleared_at": now, "cleared_by_reconciliation_id": reconciliation_id})
        if terminal:
            self._release_capacity(inv, now, target)
        self._core._audit("reconciled", now, {"episode": inv["unknown_episode"], "resolution": resolution, "to": target},
                    topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
        return {"status": "recorded", "invocation_id": inv["invocation_id"], "unknown_episode": inv["unknown_episode"], "resolution": resolution, "state": target}

    # -- status --------------------------------------------------------------
    def invocation_status(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._core._schemas, req, "router-commands#/$defs/status", "request_invalid")
            inv = self._core._capability(req["capability_id"], req["invocation_id"])
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}
        lease = self._core._lease_of(inv)
        topic = self._core._one("queue_entries", {"topic_id": inv["topic_id"]})
        finals = [r["operation_id"] for r in self._core._store.select("operation_receipts", {"invocation_id": inv["invocation_id"]})
                  if r["operation_kind"] == "final_outcome"]
        refusal = self._core._launch_refusal(inv, self._core._now())  # the current launch-admission check (L-7), for every actual start
        return {"status": "ok", "invocation_id": inv["invocation_id"], "kind": inv["kind"], "topic_id": inv["topic_id"], "state": inv["state"],
                "deadline_at": inv["deadline_at"], "job_handle": inv["job_handle"], "identity": {k: inv[k] for k in IDENTITY},
                "result_payload_digest": inv["result_payload_digest"], "failure_class": inv["failure_class"],
                "cancel_requested": None if inv["cancel_requested_at"] is None else {"at": inv["cancel_requested_at"], "by": inv["cancel_requested_by"]},
                "unknown_episode": inv["unknown_episode"], "outcome_unknown_since": inv["outcome_unknown_since"],
                "lease": {"lease_id": lease["lease_id"], "generation": lease["generation"], "expires_at": lease["expires_at"], "released_at": lease["released_at"]},
                "topic_paused": topic["paused_at"] is not None, "state_revision": topic["state_revision"], "final_operation_id": finals[0] if finals else None,
                "launch_admission": None if refusal is None else {"reason": refusal.reason, "detail": refusal.detail[:500]}}
