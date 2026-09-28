"""The router: the single logical writer to authoritative engine state (task 1b).

Trace: BOUNDARIES.md Router ("the single logical writer ... code, no model
calls in its decision path"; owns leases and every state commit via
commit_outcome; produces commit receipts and leases with generations; must
never accept caller-supplied role labels or write through any path other
than its own transactions); design review §5 (the ControlBackend contract and
the five-step commit_outcome protocol); INVARIANTS C-1..C-13, L-1, L-2, L-8,
RG-1a, RG-1b, RG-4, RG-5, E-2, G-13, V-10, P-1, P-2, P-5, P-7, H-2, H-3;
gen2/core/control.py (the protocol implemented here); gen2/store/README.md
("What stays router logic").

Shape of every operation: normalize and validate the request (schemas,
timestamps, hash truth, the A10 comparisons) with no transaction open —
reading staged bytes happens only here (C-3, C-8) — then one short
transaction that reads the clock once the write lock is held, fences
against current state and writes, then the reply.
The DDL's guards stay the second layer: a write they refuse rolls the whole
transaction back and is reported as a refusal, never retried.

Authority: an invocation acts only through the capability the router minted
for it at claim; its kind, topic, pins and lease are read from its row,
never from the request. The capability is an unguessable bearer identifier,
held by the supervisor in the engine's own process: no transport carries it
(task 1e). Operator decisions, the trusted-surface commands and delivery
receipts reach the router through the operator surface
(gen2/operator/service.py), which authenticates the principal and supplies
the fields that name it (a decision's operator_id, a brief closure's
closed_by); the router records what that surface hands it.

Task 1c's lifecycle operations (cancellation, reconciliation, status) are in
lifecycle.py; task 1d's config bundles, question registry and qualification
records in registries.py, brief and contract versions and amendment impact
(G-1) in amendments.py, re-queues, reservations and the signal queue in
scheduling.py; task 1e's status read and health probe in status.py.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from gen2.core import canonical, instants
from gen2.router import boundary
from gen2.router.amendments import AMENDMENT_COMMANDS, Amendments, contract_compatibility
from gen2.router.boundary import Refusal, instant
from gen2.router.lifecycle import LIFECYCLE_COMMANDS, Lifecycle, is_episode_hold
from gen2.router.registries import REGISTRY_COMMANDS, Registries
from gen2.router.scheduling import SCHEDULING_COMMANDS, Scheduling
from gen2.router.schemas import SchemaSet
from gen2.router.status import STATUS_COMMANDS, Status
from gen2.store import api

VALIDATOR_VERSION = "router-boundary/1"
ENVELOPE_MAX_BYTES = 64 * 1024
LIFECYCLE_FACTS = {  # target state -> the facts that record it (L-2, L-3, C-9; task 1c: L-4, L-5, L-7, L-9)
    "launching": ("job_handle",),
    "running": ("host_id", "container_id", "boot_id", "start_fingerprint"),
    "result_ready": ("result_payload_digest",),
    "failed": ("failure_class", "end_evidence_ref"),
    "cancelled": ("end_evidence_ref",),
    "outcome_unknown": ("unknown_episode",),
}
LIFECYCLE_CAUSE = {"launching": "launch_intent", "running": "identity_recorded", "result_ready": "result_staged", "failed": "failed",
                   "cancelled": "cancelled", "outcome_unknown": "outcome_unknown"}

_ID = {"$ref": "common.schema.json#/$defs/short_text"}
_OPT = {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/short_text"}]}
_TS = {"$ref": "common.schema.json#/$defs/timestamp"}
_CAP = {"$ref": "common.schema.json#/$defs/capability_id"}
_INV = {"$ref": "common.schema.json#/$defs/invocation_id"}
COMMANDS = {  # the router's own request shapes (commands, not stored documents), on the shared vocabulary
    "$defs": {
        "claim": {
            "type": "object", "additionalProperties": False,
            "required": ["invocation_id", "kind", "topic_id", "config_bundle_hash", "deadline_at"],
            "properties": {
                "invocation_id": _INV, "kind": {"$ref": "common.schema.json#/$defs/invocation_kind"},
                "topic_id": {"$ref": "common.schema.json#/$defs/topic_id"}, "station_id": _ID,
                "config_bundle_hash": {"$ref": "common.schema.json#/$defs/sha256"}, "deadline_at": _TS, "lease_expires_at": _TS,
                "parent_capability_id": _CAP, "requested_by_invocation_id": _INV, "retry_of": _INV,
                "reservation": {"$ref": "router-commands#/$defs/draw"}},
            "if": {"properties": {"kind": {"const": "delegate"}}},
            "then": {"required": ["parent_capability_id"], "not": {"anyOf": [{"required": k} for k in (["lease_expires_at"], ["station_id"], ["retry_of"], ["reservation"])]}},
            "else": {"required": ["lease_expires_at", "station_id"], "not": {"required": ["parent_capability_id"]}}},
        "transition": {
            "type": "object", "additionalProperties": False, "required": ["capability_id", "invocation_id", "to_state"],
            "properties": {
                "capability_id": _CAP, "invocation_id": _INV, "to_state": {"enum": sorted(LIFECYCLE_FACTS)},
                "job_handle": _ID, "host_id": _ID, "container_id": _OPT, "boot_id": _ID, "start_fingerprint": _ID,
                "result_payload_digest": {"$ref": "common.schema.json#/$defs/sha256"},
                "failure_class": {"$ref": "execution-record.schema.json#/properties/findings/items"},
                "end_evidence_ref": {"$ref": "common.schema.json#/$defs/sha256"},
                "unknown_episode": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
                "unknown_cause": {"enum": ["spawn_uncertain", "contact_lost", "termination_unconfirmed"]}}},
        "observation": {
            "type": "object", "additionalProperties": False, "required": ["capability_id", "invocation_id", "observation", "retrieval_events"],
            "properties": {
                "capability_id": _CAP, "invocation_id": _INV,
                "observation": {
                    "type": "object", "additionalProperties": False,
                    "required": ["observation_id", "request", "request_identity", "attempt", "lane", "obligation_ids", "started_at", "ended_at",
                                 "coverage_state", "result_count", "completeness", "error_class", "capability_fact_id", "policy_version",
                                 "cost_units", "gateway_call_ref"],
                    "properties": {
                        "observation_id": {"type": "string", "pattern": "^obs_[A-Za-z0-9_-]{8,64}$"},
                        "request": {"type": "object"}, "request_identity": {"$ref": "common.schema.json#/$defs/sha256"},
                        "attempt": {"type": "integer", "minimum": 1, "maximum": 9007199254740991}, "lane": _ID,
                        "obligation_ids": {"type": "array", "maxItems": 100, "uniqueItems": True, "items": {"$ref": "common.schema.json#/$defs/local_id"}},
                        "started_at": _TS, "ended_at": {"oneOf": [{"type": "null"}, _TS]},
                        "coverage_state": {"$ref": "common.schema.json#/$defs/coverage_state"},
                        "result_count": {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0, "maximum": 9007199254740991}]},
                        "completeness": {"enum": ["complete", "partial", "unobserved"]},
                        "error_class": {"enum": [None, "payload_invalid", "timeout", "rate_limited", "breaker_open", "budget_refused", "provider_outage",
                                                 "credentials_rejected", "credentials_not_configured", "secrets_backend_failing", "transport_failure",
                                                 "telemetry_missing", "partial_pagination"]},
                        "capability_fact_id": _OPT, "policy_version": _ID,
                        "cost_units": {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0, "maximum": 9007199254740991}]},
                        "gateway_call_ref": _OPT}},
                "retrieval_events": {
                    "type": "array", "maxItems": 10000,
                    "items": {"type": "object", "additionalProperties": False, "required": ["event_id", "provider_record_id", "rank", "captured_at"],
                              "properties": {"event_id": {"type": "string", "pattern": "^rev_[A-Za-z0-9_-]{8,64}$"}, "provider_record_id": _ID,
                                             "rank": {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 1, "maximum": 9007199254740991}]},
                                             "captured_at": _TS}}}}},
        "operator_decision": {
            "type": "object", "additionalProperties": False,
            "required": ["decision_id", "topic_id", "kind", "disposition", "subject", "operator_id", "decided_at", "notes", "payload"],
            "properties": {
                "decision_id": {"$ref": "common.schema.json#/$defs/operator_decision_id"},
                "topic_id": {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/topic_id"}]},
                "kind": {"enum": ["brief_confirmation", "scope_approval", "rating_approval", "contract_approval", "amendment_approval", "reframe_approval",
                                  "completion_approval", "retirement", "hold_clearance", "publication_approval", "blind_initial_disposition", "advised_feedback"]},
                "disposition": {"enum": ["approved", "rejected", "deferred", "recorded"]},
                "subject": {"type": "object", "additionalProperties": False, "required": ["kind", "ref", "revision", "hash"],
                            "properties": {"kind": {"enum": ["intake_brief", "scoping_report", "contract_revision", "dossier", "topic", "hold",
                                                             "publication_source", "decision_receipt"]},
                                           "ref": _ID, "revision": {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/state_revision"}]},
                                           "hash": {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/sha256"}]}}},
                "operator_id": _ID, "decided_at": _TS,
                "notes": {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/long_text"}]},
                "payload": {"type": ["object", "null"]}}},
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def random_id(prefix: str) -> str:
    return prefix + secrets.token_hex(16)


class NoExtensions:
    """No extension loading (Phase 3): no extension connector is admitted."""

    def is_admitted(self, **_) -> bool:
        return False


class MalformedRequest(ValueError):
    """A commit envelope without a well-formed operation_id: there is no
    operation to answer for, so this is raised rather than returned."""


def _short(text: str) -> str:
    return (text or "refused")[:500]


class Router(Lifecycle, Registries, Amendments, Scheduling, Status):
    """The ControlBackend (gen2/core/control.py) over one store. Construct
    with a Store (Router.open for a durable one); the router owns it and hands
    it to no one. Qualification is read from the store's own records
    (registries.py): there is no registry to inject, and none recorded means
    none qualified (INVARIANTS §13)."""

    def __init__(self, store: api.Store, spool, *, clock: Callable[[], str] = utc_now, new_id: Callable[[str], str] = random_id,
                 extensions=None, fault: Callable[[str], None] | None = None, schemas: SchemaSet | None = None) -> None:
        self._store = store
        self._spool = spool
        self._clock = clock
        self._new_id = new_id
        self._extensions = extensions or NoExtensions()
        self._fault = fault or (lambda point: None)
        self._schemas = schemas or SchemaSet(extra={"router-commands": {"$defs": {
            **COMMANDS["$defs"], **LIFECYCLE_COMMANDS, **REGISTRY_COMMANDS, **AMENDMENT_COMMANDS, **SCHEDULING_COMMANDS,
            **STATUS_COMMANDS}}})

    @classmethod
    def open(cls, path: str | Path, spool, *, create: bool = False, **kwargs) -> "Router":
        return cls(api.open_store(path, create=create), spool, **kwargs)

    def close(self) -> None:
        self._store.close()

    # -- small helpers -----------------------------------------------------
    def _now(self) -> str:
        now = self._clock()
        if not instants.is_utc_instant(now):
            raise RuntimeError(f"the router clock returned {now!r}, not an RFC 3339 UTC instant")
        return now

    def _one(self, table: str, where: Mapping[str, object]) -> dict | None:
        rows = self._store.select(table, where)
        return rows[0] if rows else None

    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str:
        audit_id = self._new_id("aud_")
        self._store.insert("audit_events", {"audit_event_id": audit_id, "at": at, "kind": kind, "topic_id": topic_id,
                                            "invocation_id": invocation_id, "operation_id": operation_id, "detail": detail})
        return audit_id

    def _transition_row(self, invocation_id: str, from_state: str | None, to_state: str, at: str, cause: str, facts: dict | None = None) -> None:
        seq = self._store.next_in_sequence("invocation_transitions", "seq", {"invocation_id": invocation_id})
        self._store.insert("invocation_transitions", {"invocation_id": invocation_id, "seq": seq, "from_state": from_state,
                                                      "to_state": to_state, "at": at, "cause": cause, "facts": facts})

    def _lease_of(self, inv: dict) -> dict:
        """A non-delegate's own lease; a delegate's parent's (L-8)."""
        lease_id = inv["lease_id"] or self._one("invocations", {"invocation_id": inv["parent_invocation_id"]})["lease_id"]
        return self._one("leases", {"lease_id": lease_id})

    def _require_current_lease(self, inv: dict, now: str, lease_ref: Mapping | None = None) -> dict:
        lease = self._lease_of(inv)
        if lease_ref is not None and lease_ref["lease_id"] != lease["lease_id"]:
            raise Refusal("lease_not_current", f"{lease_ref['lease_id']} is not the lease {inv['invocation_id']} runs under")
        if lease["released_at"] is not None:
            raise Refusal("lease_released", f"{lease['lease_id']} was released at {lease['released_at']} ({lease['release_reason']})")
        if lease_ref is not None and lease_ref["generation"] != lease["generation"]:
            raise Refusal("lease_generation_stale", f"generation {lease_ref['generation']} is not {lease['lease_id']}'s generation {lease['generation']}")
        if instant(now) >= instant(lease["expires_at"]):
            raise Refusal("lease_not_current", f"{lease['lease_id']} expired at {lease['expires_at']}")
        return lease

    def _launch_refusal(self, inv: dict, now: str) -> Refusal | None:
        """L-7: the launch-admission check against current state — the lease
        the invocation runs under is current (not released, replaced or
        expired), its topic is not paused, its deadline has not passed and no
        cancellation was requested. Checked when launch intent is recorded,
        and reported by invocation_status before every actual start (task
        1c-repair A1: a recorded launch intent is evidence of the earlier
        intent, not renewed authority to start)."""
        try:
            self._require_current_lease(inv, now)
        except Refusal as refusal:
            return refusal
        topic = self._one("queue_entries", {"topic_id": inv["topic_id"]})
        if topic["paused_at"] is not None:
            return Refusal("topic_paused", f"paused at {topic['paused_at']}")
        if instant(now) >= instant(inv["deadline_at"]):
            return Refusal("deadline_passed", f"deadline {inv['deadline_at']}")
        if inv["cancel_requested_at"] is not None:
            return Refusal("cancel_requested", f"cancellation was requested at {inv['cancel_requested_at']}")
        return None

    def _authorize_artifact(self, content_hash: str, inv: dict, now: str) -> None:
        """Record that the invocation's topic may reference these bytes: they
        were staged in its spool and are recorded by its own work (C-9). The
        artifact row is shared by every topic that staged the same bytes;
        the authorization is per topic (Astra 1c review A6)."""
        if self._one("artifact_topics", {"content_hash": content_hash, "topic_id": inv["topic_id"]}) is None:
            self._store.insert("artifact_topics", {"content_hash": content_hash, "topic_id": inv["topic_id"],
                                                   "recorded_by_invocation_id": inv["invocation_id"], "recorded_at": now})

    def _recorded_for(self, content_hash: str, topic_id: str) -> dict | None:
        """The artifact row of bytes already recorded for this topic, or None.
        Bytes recorded only for other topics are not this topic's: content
        identity is not topic authorization (C-9, RG-5; Q6 ruling)."""
        if self._one("artifact_topics", {"content_hash": content_hash, "topic_id": topic_id}) is None:
            return None
        return self._one("artifacts", {"content_hash": content_hash})

    def _capability(self, capability_id: str, invocation_id: str) -> dict:
        inv = self._one("invocations", {"capability_id": capability_id})
        if inv is None:
            raise Refusal("capability_invalid", "no invocation holds this capability")
        if inv["invocation_id"] != invocation_id:
            raise Refusal("capability_invocation_mismatch", f"the capability is {inv['invocation_id']}'s, not {invocation_id}'s")
        return inv

    def _admission_json(self, inv: dict) -> dict:
        if inv["admission_context"] == "contract/1":
            contract = self._one("contract_revisions", {"topic_id": inv["topic_id"], "revision": inv["contract_revision"]})
            return {"context": "contract/1", "contract": {"revision": inv["contract_revision"], "content_hash": contract["content_hash"]}}
        return {"context": "pre-contract/1", "brief": {"brief_id": inv["brief_ref"], "version": inv["brief_version"], "content_hash": inv["brief_hash"]},
                "brief_confirmation_decision_id": inv["brief_confirmation_decision_id"]}

    def _set_topic(self, topic: dict, now: str, status: str | None = None, **columns) -> int:
        """Advance the topic's state revision by one (compare-and-set on the
        revision read), with a status change in the same statement."""
        before = topic["state_revision"]
        changes = {"state_revision": before + 1, "updated_at": now, **columns}
        if status is not None:
            changes["status"] = status
        self._store.update("queue_entries", {"topic_id": topic["topic_id"]}, changes, expect={"state_revision": before})
        return before + 1

    def _guarded(self, reason: str, body: Callable[[str], object]) -> object:
        """Run one transaction; a write the store refuses is a refusal (nothing
        was written), never retried. The body gets the clock read once the
        write lock is held (BEGIN IMMEDIATE has returned), so time spent
        waiting for the lock counts against every lease, deadline and expiry
        it checks (L-7; Astra 1b review A1)."""
        try:
            with self._store.transaction():
                return body(self._now())
        except (api.ConstraintViolation, api.StoreWriteError) as exc:
            raise Refusal(reason, f"the store refused the write: {exc}") from None

    # -- claim ---------------------------------------------------------------
    def claim(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._schemas, req, "router-commands#/$defs/claim", "request_invalid")
            return self._guarded("request_invalid", lambda now: self._claim_in_transaction(req, now))
        except Refusal as refusal:
            return {"status": "refused", "invocation_id": request.get("invocation_id") if isinstance(request, Mapping) else None,
                    "reason": refusal.reason, "detail": _short(refusal.detail)}

    def _claim_in_transaction(self, req: dict, now: str) -> dict:
        existing = self._one("invocations", {"invocation_id": req["invocation_id"]})
        if existing is not None:
            return self._claim_replay(req, existing)  # a lost reply gets its grant back, whatever the time now
        for field in ("deadline_at", "lease_expires_at"):
            if field in req and instant(req[field]) <= instant(now):
                raise Refusal("request_invalid", f"{field} {req[field]} is not after {now}")
        topic = self._one("queue_entries", {"topic_id": req["topic_id"]})
        if topic is None:
            raise Refusal("unknown_topic", req["topic_id"])
        if topic["paused_at"] is not None:
            raise Refusal("topic_paused", f"paused at {topic['paused_at']}")
        if req["kind"] == "delegate":
            return self._admit_delegate(req, topic, now)
        active = self._active_bundle()  # new work pins the active bundle; admitted work keeps its own (RG-9, C-12)
        if active is None or active["bundle_hash"] != req["config_bundle_hash"]:
            raise Refusal("config_bundle_not_active", f"new work is admitted under the active config bundle ({None if active is None else active['bundle_hash']})")
        pins = self._derive_admission(topic["topic_id"], req["kind"])
        scope = boundary.SCOPE_OF_KIND[req["kind"]]
        claimable = {"scoping"} if pins["admission_context"] == "pre-contract/1" else (
            {"queued", "resting"} if scope == "research" else {"queued", "active", "resting"})
        if topic["status"] not in claimable:
            raise Refusal("topic_not_claimable", f"a {scope} lease under {pins['admission_context']} needs the topic {sorted(claimable)}, not {topic['status']}")
        retry = self._admit_lane(req, topic["topic_id"], scope)
        for live in (row for row in self._store.select("leases", {"topic_id": topic["topic_id"], "scope": scope}) if row["released_at"] is None):
            if instant(now) < instant(live["expires_at"]):
                raise Refusal("lease_held", f"{live['lease_id']} (generation {live['generation']}) is live until {live['expires_at']}")
            self._store.update("leases", {"lease_id": live["lease_id"]}, {"released_at": now, "release_reason": "expired"})
        generation = self._store.next_in_sequence("leases", "generation", {"topic_id": topic["topic_id"]})
        lease_id = self._new_id("lease_")
        self._store.insert("leases", {"lease_id": lease_id, "topic_id": topic["topic_id"], "scope": scope, "generation": generation,
                                      "station_id": req["station_id"], "granted_at": now, "expires_at": req["lease_expires_at"]})
        self._insert_invocation(req, topic["topic_id"], lease_id, pins, now)
        if retry is not None:
            self._store.update("retries", {"invocation_id": retry["invocation_id"]}, {"retry_invocation_id": req["invocation_id"]})
        if "reservation" in req:
            self._draw(req["reservation"], req["invocation_id"], topic["topic_id"], now)
        if scope == "research" and pins["admission_context"] == "contract/1":
            self._set_topic(topic, now, "active")
        self._audit("claim", now, {"lease_id": lease_id, "generation": generation, "scope": scope},
                    topic_id=topic["topic_id"], invocation_id=req["invocation_id"])
        return self._grant("granted", req["invocation_id"])

    def _derive_admission(self, topic_id: str, kind: str) -> dict:
        """The admission context comes from state, never from the request
        (C-12): the approved contract revision, or — only while the topic has
        never had one — its confirmed brief, for scoping/drafting kinds."""
        contracts = self._store.select("contract_revisions", {"topic_id": topic_id})
        approved = [c for c in contracts if c["status"] == "approved"]
        none = {"brief_ref": None, "brief_version": None, "brief_hash": None, "brief_confirmation_decision_id": None}
        if approved:
            return {"admission_context": "contract/1", "contract_revision": approved[0]["revision"], **none}
        if kind not in ("discovery", "research_pass") or any(c["status"] != "draft" for c in contracts):
            raise Refusal("not_admissible", f"no approved contract admits {kind} work")
        brief = self._one("intake_briefs", {"topic_id": topic_id, "status": "confirmed"})
        if brief is None:
            raise Refusal("not_admissible", "neither an approved contract nor a confirmed brief")
        return {"admission_context": "pre-contract/1", "contract_revision": None, "brief_ref": brief["brief_id"],
                "brief_version": brief["version"], "brief_hash": brief["content_hash"], "brief_confirmation_decision_id": brief["confirmed_by_decision_id"]}

    def _insert_invocation(self, req: dict, topic_id: str, lease_id: str | None, pins: dict, now: str, parent: str | None = None) -> None:
        self._store.insert("invocations", {
            "invocation_id": req["invocation_id"], "kind": req["kind"], "topic_id": topic_id, "parent_invocation_id": parent,
            "requested_by_invocation_id": req.get("requested_by_invocation_id"), "lease_id": lease_id, "capability_id": self._new_id("cap_"),
            "config_bundle_hash": req["config_bundle_hash"], **pins, "state": "admitted", "admitted_at": now,
            "deadline_at": req["deadline_at"], "state_changed_at": now})
        self._transition_row(req["invocation_id"], None, "admitted", now, "claim")

    def _admit_delegate(self, req: dict, topic: dict, now: str) -> dict:
        """L-8: a delegate runs under its launching/running non-delegate
        parent's lease and pins, holding no lease of its own; the parent is
        named by its capability, not by an id."""
        parent = self._one("invocations", {"capability_id": req["parent_capability_id"]})
        if parent is None:
            raise Refusal("capability_invalid", "no invocation holds the parent capability")
        if parent["topic_id"] != topic["topic_id"]:
            raise Refusal("cross_topic", f"the parent is of topic {parent['topic_id']}")
        if parent["kind"] == "delegate" or parent["state"] not in ("launching", "running"):
            raise Refusal("parent_not_running", f"{parent['invocation_id']} is a {parent['kind']} in state {parent['state']}")
        if parent["config_bundle_hash"] != req["config_bundle_hash"]:
            raise Refusal("config_bundle_mismatch", "a delegate inherits its parent's config bundle (C-12)")
        pins = {k: parent[k] for k in ("admission_context", "contract_revision", "brief_ref", "brief_version", "brief_hash", "brief_confirmation_decision_id")}
        self._insert_invocation(req, topic["topic_id"], None, pins, now, parent=parent["invocation_id"])
        self._audit("claim", now, {"delegate_of": parent["invocation_id"]}, topic_id=topic["topic_id"], invocation_id=req["invocation_id"])
        return self._grant("granted", req["invocation_id"])

    def _claim_replay(self, req: dict, inv: dict) -> dict:
        same = (inv["kind"] == req["kind"] and inv["topic_id"] == req["topic_id"] and inv["config_bundle_hash"] == req["config_bundle_hash"]
                and inv["deadline_at"] == req["deadline_at"] and inv["requested_by_invocation_id"] == req.get("requested_by_invocation_id"))
        if same and inv["kind"] == "delegate":
            same = self._one("invocations", {"invocation_id": inv["parent_invocation_id"]})["capability_id"] == req["parent_capability_id"]
        elif same:
            lease = self._one("leases", {"lease_id": inv["lease_id"]})
            retry, draw = self._one("retries", {"retry_invocation_id": inv["invocation_id"]}), self._one("reservation_draws", {"invocation_id": inv["invocation_id"]})
            same = (lease["station_id"] == req["station_id"] and lease["expires_at"] == req["lease_expires_at"]
                    and (retry and retry["invocation_id"]) == req.get("retry_of")
                    and (draw and {k: v for k, v in draw.items() if k in ("reservation_id", "facet_id") and v is not None}) == req.get("reservation"))
        if not same:
            raise Refusal("invocation_id_conflict", f"{inv['invocation_id']} was admitted for a different request")
        return self._grant("replayed", inv["invocation_id"])

    def _grant(self, status: str, invocation_id: str) -> dict:
        inv = self._one("invocations", {"invocation_id": invocation_id})
        lease = self._lease_of(inv)
        topic = self._one("queue_entries", {"topic_id": inv["topic_id"]})
        return {"status": status, "invocation_id": invocation_id, "capability_id": inv["capability_id"], "kind": inv["kind"],
                "topic_id": inv["topic_id"], "lease": {"lease_id": lease["lease_id"], "generation": lease["generation"], "expires_at": lease["expires_at"]},
                "admission": self._admission_json(inv), "config_bundle_hash": inv["config_bundle_hash"], "deadline_at": inv["deadline_at"],
                "state_revision": topic["state_revision"]}

    # -- lifecycle facts -----------------------------------------------------
    def record_transition(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._schemas, req, "router-commands#/$defs/transition", "request_invalid")
            target = req["to_state"]
            facts = {k: v for k, v in req.items() if k not in ("capability_id", "invocation_id", "to_state", "unknown_cause")}
            wanted = set(LIFECYCLE_FACTS[target])
            if set(facts) - wanted or wanted - {"container_id"} - set(facts) or ("unknown_cause" in req) != (target == "outcome_unknown"):
                raise Refusal("request_invalid", f"{target} is recorded with exactly {sorted(wanted)} (container_id optional; unknown_cause with outcome_unknown)")
            facts = {k: facts.get(k) for k in LIFECYCLE_FACTS[target]}  # an omitted container_id is recorded, and compared, as none
            # A recorded fact answers from its recorded facts before any byte
            # is asked for: once committed, a result's staged copy may be gone
            # (C-9), and a changed fact is a conflict whether or not its bytes
            # are staged (Astra 1b-repair review A5-R).
            replay = self._recorded_transition(req, facts)
            if replay is not None:
                return replay
            self._fault("transition_checked")
            inv = self._capability(req["capability_id"], req["invocation_id"])  # its topic and job handle are write-once
            evidence = None
            if target == "result_ready":  # C-9: the new result the supervisor retained is really staged, as JSON, for this topic
                boundary.staged(self._spool, facts["result_payload_digest"], topic_id=inv["topic_id"], media_type="application/json")
            elif facts.get("end_evidence_ref") is not None:
                evidence = self._evidence(inv, facts["end_evidence_ref"])
            return self._guarded("transition_not_allowed", lambda now: self._transition_in_transaction(req, facts, evidence, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": _short(refusal.detail)}

    def _recorded_transition(self, req: dict, facts: dict) -> dict | None:
        """The answer to a lifecycle fact already recorded, or None. The key is
        (invocation, target state): a fact this operation recorded replays
        whatever state the invocation has reached since, before any check of
        current authority (a lost launch reply after the lease ended is still
        that launch), and its facts are write-once (DDL), so the row holds them
        (Astra 1b review A5). An entry into outcome_unknown is keyed by its
        episode: an episode the invocation has entered replays, the next one
        is new, and one beyond it is a conflict (RA4). An exit out of
        outcome_unknown is recorded by reconcile, under its own cause, so it
        is never taken for this fact. The transition row is read first, so
        outside a transaction too the invocation row read after it already
        holds the facts written with it."""
        target = req["to_state"]
        if target == "outcome_unknown":
            inv = self._capability(req["capability_id"], req["invocation_id"])
            if facts["unknown_episode"] <= inv["unknown_episode"]:  # an entry recorded: replayed only with the cause it was recorded with (A8)
                entries = [row["facts"] for row in self._store.select("invocation_transitions", {"invocation_id": inv["invocation_id"], "to_state": target,
                                                                                                 "cause": LIFECYCLE_CAUSE[target]})]
                recorded = next((f for f in entries if f is not None and f.get("unknown_episode") == facts["unknown_episode"]), None)
                if recorded is None or recorded.get("unknown_cause") != req["unknown_cause"]:
                    raise Refusal("transition_conflict", f"episode {facts['unknown_episode']} of {inv['invocation_id']} was entered "
                                                         f"{'with cause ' + str(recorded.get('unknown_cause')) if recorded else 'with no recorded cause'}")
                return {"status": "replayed", "invocation_id": inv["invocation_id"], "state": target, "unknown_episode": facts["unknown_episode"]}
            if facts["unknown_episode"] > inv["unknown_episode"] + 1:
                raise Refusal("transition_conflict", f"{inv['invocation_id']} has entered episode {inv['unknown_episode']}; the next is {inv['unknown_episode'] + 1}")
            return None
        recorded = self._one("invocation_transitions", {"invocation_id": req["invocation_id"], "to_state": target, "cause": LIFECYCLE_CAUSE[target]})
        if recorded is None:
            return None
        inv = self._capability(req["capability_id"], req["invocation_id"])
        if any(inv[k] != v for k, v in facts.items()):
            raise Refusal("transition_conflict", f"{inv['invocation_id']} recorded {target} with other facts")
        return {"status": "replayed", "invocation_id": inv["invocation_id"], "state": target}

    def _transition_in_transaction(self, req: dict, facts: dict, evidence: dict | None, now: str) -> dict:
        replay = self._recorded_transition(req, facts)  # again under the lock: the same fact may have been recorded meanwhile
        if replay is not None:
            return replay
        inv = self._capability(req["capability_id"], req["invocation_id"])
        target = req["to_state"]
        if inv["state"] == target:
            raise Refusal("transition_not_allowed", f"{inv['invocation_id']} is already {target} (reached another way)")
        changes = {"state": target, "state_changed_at": now, **facts}
        if target == "launching":
            refusal = self._launch_refusal(inv, now)
            if refusal is not None:
                raise refusal
            changes["launch_intent_at"] = now
        if target == "result_ready":
            if inv["cancel_requested_at"] is not None:  # the cancellation won: the result stays retained, uncommitted (C-10)
                raise Refusal("cancel_requested", f"cancellation was requested at {inv['cancel_requested_at']}")
            changes["result_staged_at"] = now
        if target in ("failed", "cancelled"):
            self._bind_evidence(inv, evidence, failure_class=facts.get("failure_class"))
            self._record_artifact(inv, evidence, now)
        if target == "cancelled":
            if inv["cancel_requested_at"] is None:
                raise Refusal("transition_not_allowed", f"no cancellation of {inv['invocation_id']} was requested")
            changes["descendants_confirmed_at"] = now  # the evidence confirms them handled (L-7)
        if target == "outcome_unknown":
            changes["outcome_unknown_since"] = now
        self._store.update("invocations", {"invocation_id": inv["invocation_id"]}, changes)
        self._transition_row(inv["invocation_id"], inv["state"], target, now, LIFECYCLE_CAUSE[target],
                             {**facts, **({"unknown_cause": req["unknown_cause"]} if target == "outcome_unknown" else {})})
        if target in ("failed", "cancelled"):
            self._release_capacity(inv, now, target)
        if target == "outcome_unknown":
            self._open_unknown_hold(inv, facts["unknown_episode"], req["unknown_cause"], now)
        self._audit("transition", now, {"from": inv["state"], "to": target, **({"cause": req["unknown_cause"]} if target == "outcome_unknown" else {})},
                    topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
        return {"status": "recorded", "invocation_id": inv["invocation_id"], "state": target}

    # -- observations ----------------------------------------------------------
    def record_observation(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._schemas, req, "router-commands#/$defs/observation", "request_invalid")
            boundary.check_observation(req["observation"], req["retrieval_events"])
            return self._guarded("payload_invalid", lambda now: self._observation_in_transaction(req, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": _short(refusal.detail)}

    def _observation_in_transaction(self, req: dict, now: str) -> dict:
        obs, events = req["observation"], req["retrieval_events"]
        existing = self._one("search_observations", {"observation_id": obs["observation_id"]})
        if existing is not None:
            stored_events = self._store.select("retrieval_events", {"observation_id": obs["observation_id"]})
            same = (existing["invocation_id"] == req["invocation_id"] and all(existing[k] == v for k, v in obs.items())
                    and sorted((e["event_id"], e["provider_record_id"], e["rank"], e["captured_at"]) for e in stored_events)
                    == sorted((e["event_id"], e["provider_record_id"], e["rank"], e["captured_at"]) for e in events))
            if not same:
                raise Refusal("observation_id_conflict", f"{obs['observation_id']} was recorded with different content")
            return {"status": "replayed", "observation_id": obs["observation_id"], "retrieval_events": len(stored_events)}
        inv = self._capability(req["capability_id"], req["invocation_id"])
        if inv["state"] != "running":
            raise Refusal("invocation_state_invalid", f"observations are recorded while running, not {inv['state']}")
        if inv["cancel_requested_at"] is not None:
            raise Refusal("invocation_state_invalid", f"cancellation was requested at {inv['cancel_requested_at']}")
        self._require_current_lease(inv, now)
        topic = self._one("queue_entries", {"topic_id": inv["topic_id"]})
        if topic["paused_at"] is not None:
            raise Refusal("topic_paused", f"paused at {topic['paused_at']}")
        self._store.insert("search_observations", {**obs, "invocation_id": inv["invocation_id"], "topic_id": inv["topic_id"]})
        for event in events:
            self._store.insert("retrieval_events", {**event, "observation_id": obs["observation_id"], "topic_id": inv["topic_id"]})
        self._audit("observation", now, {"observation_id": obs["observation_id"], "retrieval_events": len(events)},
                    topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
        return {"status": "recorded", "observation_id": obs["observation_id"], "retrieval_events": len(events)}

    # -- commit_outcome ----------------------------------------------------------
    def commit_outcome(self, envelope: Mapping) -> dict:
        op_id = envelope.get("operation_id") if isinstance(envelope, Mapping) else None
        if not isinstance(op_id, str) or self._schemas.errors(op_id, "common.schema.json#/$defs/operation_id"):
            raise MalformedRequest("a commit envelope names a well-formed operation_id; there is nothing to answer for without one")
        env: dict | None = None
        try:
            env = boundary.normalize(envelope, "envelope_invalid")
            boundary.require_schema(self._schemas, env, "commit-outcome.schema.json", "envelope_invalid")
            if len(canonical.canonical_bytes(env)) > ENVELOPE_MAX_BYTES:
                raise Refusal("envelope_invalid", f"the envelope exceeds {ENVELOPE_MAX_BYTES} bytes")
            fingerprint = canonical.request_fingerprint(env)
            replay = self._replay(op_id, fingerprint)  # receipts are immutable: a committed one is final, so this read needs no transaction
            if replay is not None:
                return replay
            self._fault("before_validation")
            checked = self._validate_commit(env)
            self._fault("after_validation")
            status, receipt = self._guarded("payload_invalid", lambda now: self._commit_in_transaction(env, fingerprint, checked, now))
            if status == "committed":
                self._fault("after_commit")
            return {"status": status, "receipt": receipt}
        except Refusal as refusal:
            return self._reject(op_id, env, refusal)

    def receipt(self, operation_id: str) -> dict | None:
        row = self._one("operation_receipts", {"operation_id": operation_id})
        return None if row is None else row["receipt"]

    def _replay(self, op_id: str, fingerprint: str) -> dict | None:
        row = self._one("operation_receipts", {"operation_id": op_id})
        if row is None:
            return None
        if row["request_fingerprint"] != fingerprint:
            raise Refusal("operation_id_conflict", f"{op_id} was committed for a different request")
        return {"status": "replayed", "receipt": row["receipt"]}

    def _reject(self, op_id: str, env: dict | None, refusal: Refusal) -> dict:
        """Nothing changed; the refusal itself is logged (DDL audit_events:
        a rejection writes no receipt, RG-1b)."""
        topic_id = env.get("topic_id") if isinstance(env, dict) else None
        topic = self._one("queue_entries", {"topic_id": topic_id}) if isinstance(topic_id, str) else None
        response = {"status": "rejected", "operation_id": op_id, "reason": refusal.reason,
                    "current_state_revision": None if topic is None else topic["state_revision"]}
        if refusal.detail:
            response["detail"] = _short(refusal.detail)
        with self._store.transaction():
            now = self._now()
            self._audit("commit_rejected", now, {"reason": refusal.reason, "detail": _short(refusal.detail)},
                        topic_id=topic_id if topic is not None else None, operation_id=op_id,
                        invocation_id=env.get("invocation_id") if isinstance(env, dict) and isinstance(env.get("invocation_id"), str) else None)
        return response

    def _validate_commit(self, env: dict) -> dict:
        """Step 2, outside any transaction: every staged byte the commit
        relies on is read and re-hashed here, every document validated, and
        the result bound to the exact hashes validated (C-3). Identity, pins
        and contract documents read here are write-once."""
        inv = self._capability(env["capability_id"], env["invocation_id"])
        if env["topic_id"] != inv["topic_id"]:
            raise Refusal("cross_topic", f"{inv['invocation_id']} is of topic {inv['topic_id']}")
        raw = boundary.staged(self._spool, env["payload_digest"], env["payload_size_bytes"], topic_id=inv["topic_id"])
        payload = boundary.normalize(raw, "payload_invalid")
        boundary.require_schema(self._schemas, payload, "outcome-document.schema.json", "payload_invalid")
        if payload["invocation_id"] != inv["invocation_id"]:
            raise Refusal("capability_invocation_mismatch", f"the outcome document is {payload['invocation_id']}'s")
        if payload["topic_id"] != inv["topic_id"]:
            raise Refusal("cross_topic", f"the outcome document is about topic {payload['topic_id']}")
        if payload["operation_kind"] != env["operation_kind"]:
            raise Refusal("payload_invalid", "the outcome document is for another operation kind")
        if payload["next_queue_state"] is not None and inv["kind"] != "research_pass":
            raise Refusal("kind_not_permitted", "only a research pass proposes its topic's next queue state")
        boundary.check_sections(payload, inv["kind"], inv["admission_context"])
        artifacts = {env["payload_digest"]: {"size_bytes": len(raw), "media_type": "application/json"}}
        staged = {env["payload_digest"]: raw}
        for ref in env["result_refs"]:
            staged[ref["content_hash"]] = boundary.staged(self._spool, ref["content_hash"], ref["size_bytes"], topic_id=inv["topic_id"])
            if artifacts.setdefault(ref["content_hash"], ref) is not ref and artifacts[ref["content_hash"]]["media_type"] != ref["media_type"]:
                raise Refusal("payload_invalid", f"{ref['content_hash']} is referenced with two media types")
        for content_hash, ref in artifacts.items():
            stored = self._one("artifacts", {"content_hash": content_hash})
            if stored is not None and (stored["size_bytes"], stored["media_type"]) != (ref["size_bytes"], ref["media_type"]):
                raise Refusal("payload_invalid", f"{content_hash} is recorded as {stored['size_bytes']} bytes of {stored['media_type']} (A10)")
            spooled = self._spool.media_type(content_hash, topic_id=inv["topic_id"])
            if spooled != ref["media_type"]:  # the spool's own record of what it staged for this topic (task 1c)
                raise Refusal("payload_invalid", f"{content_hash} is staged as {spooled}, not the {ref['media_type']} declared")

        def recorded_here(content_hash: str) -> dict | None:  # a topic's authorization is write-once (DDL artifact_topics): what validation finds stands
            return self._recorded_for(content_hash, inv["topic_id"])

        def available(content_hash: str) -> bool:
            return content_hash in staged or recorded_here(content_hash) is not None

        def bind(ref: dict, what: str) -> None:
            """The one rule for an artifact reference a document embeds (A10;
            Astra 1b review A4): its bytes are staged with this commit or
            already recorded for this topic (A6), and its size and media type
            are theirs — the staged declaration (its size checked against the
            bytes) or the recorded row."""
            known = artifacts.get(ref["content_hash"]) or recorded_here(ref["content_hash"])
            if known is None:
                elsewhere = self._one("artifacts", {"content_hash": ref["content_hash"]}) is not None
                raise Refusal("payload_missing", f"{what} {ref['content_hash']} is neither staged with this commit nor recorded for {inv['topic_id']}"
                                                 + ("; it is recorded only for another topic, and content identity is not topic authorization (C-9)" if elsewhere else ""))
            if (known["size_bytes"], known["media_type"]) != (ref["size_bytes"], ref["media_type"]):
                raise Refusal("payload_invalid", f"{what}: its reference disagrees with the artifact's size or media type "
                                                 f"({known['size_bytes']} bytes of {known['media_type']})")

        for claim in payload["claims"]:
            bind(claim["text_ref"], f"{claim['claim_id']}: its text")
        for doc in payload["verification_receipts"]:
            boundary.check_verification_receipt(doc, inv["invocation_id"], env["capability_id"], inv["topic_id"])
            if doc["extraction"]["method"] == "canonical_bytes" and not available(doc["obtained_content_hash"]):
                raise Refusal("payload_missing", f"{doc['verification_receipt_id']}: its canonical bytes are not staged (V-3)")
        receipts = {}
        specs = {}
        hold_ids = {hold["hold_id"] for hold in payload["holds"]}
        bundle = self._bundle(inv["config_bundle_hash"])  # immutable: the question registry the invocation was admitted under (D-1)
        questions = {(q["question_id"], q["version"], q["content_hash"]) for q in bundle["questions"]}
        for doc in payload["decision_receipts"]:
            spec = self._one("decision_specs", {"spec_hash": doc["spec"]["spec_hash"]})
            specs[doc["decision_receipt_id"]] = None if spec is None else spec["document"]
            boundary.check_decision_receipt(doc, specs[doc["decision_receipt_id"]], invocation_id=inv["invocation_id"], topic_id=inv["topic_id"],
                                            operation_id=env["operation_id"], qualifications=self, questions=questions)
            response = doc["provider_response"]
            if response["raw_response_artifact"] is not None:  # D-1: response bytes are retained, and the reference is to them
                if response["raw_response_digest"] != response["raw_response_artifact"]["content_hash"]:
                    raise Refusal("payload_invalid", f"{doc['decision_receipt_id']}: its raw response digest is not its raw response artifact's hash")
                bind(response["raw_response_artifact"], f"{doc['decision_receipt_id']}: its raw response")
            hold = doc["outcome"]["hold_id"]
            if hold is not None and hold not in hold_ids and self._one("holds", {"hold_id": hold}) is None:
                raise Refusal("payload_invalid", f"{doc['decision_receipt_id']}: its hold {hold} is neither created here nor recorded")
            receipts[doc["decision_receipt_id"]] = doc
        protocol = None
        if payload["screening_assessments"]:
            contract = self._one("contract_revisions", {"topic_id": inv["topic_id"], "revision": inv["contract_revision"]})
            protocol = contract["document"]["eligibility_protocol"]
            admitted = {"topic_id": inv["topic_id"], "contract": {"revision": inv["contract_revision"], "content_hash": contract["content_hash"]}}
            for assessment in payload["screening_assessments"]:
                rid = assessment["decision_receipt_id"]
                boundary.check_screening(assessment, protocol, receipts.get(rid), specs.get(rid), admitted)
        manifests = []
        for manifest in payload["exports"]:
            bundle_hash = manifest["bundle"]["content_hash"]
            if bundle_hash not in staged:
                raise Refusal("payload_missing", f"{manifest['manifest_id']}: its bundle {bundle_hash} is not staged with this commit")
            manifests.append((manifest, boundary.check_manifest(manifest, inv["topic_id"], self._extensions, staged[bundle_hash], self._schemas)))
        for hold in payload["holds"]:
            fact = hold["capability_fact_id"]
            if fact is not None and self._one("capability_facts", {"fact_id": fact}) is None:
                raise Refusal("payload_invalid", f"{hold['hold_id']}: capability fact {fact} is not recorded")
        validated = list(dict.fromkeys([env["payload_digest"], *(ref["content_hash"] for ref in env["result_refs"])]))
        return {"invocation": inv, "payload": payload, "artifacts": artifacts, "manifests": manifests, "protocol": protocol,
                "validation": {"validator_version": VALIDATOR_VERSION, "policy_version": f"config-bundle/{bundle['version']}", "validated_hashes": validated}}

    def _commit_in_transaction(self, env: dict, fingerprint: str, checked: dict, now: str) -> tuple[str, dict]:
        """Steps 3-4: replay or reject, fence against current state, then
        record everything the validated outcome authorizes, atomically."""
        replay = self._replay(env["operation_id"], fingerprint)
        if replay is not None:
            return "replayed", replay["receipt"]
        self._fault("in_transaction:start")
        inv = self._one("invocations", {"invocation_id": env["invocation_id"]})
        topic = self._one("queue_entries", {"topic_id": inv["topic_id"]})
        payload, final = checked["payload"], env["operation_kind"] == "final_outcome"
        lease = self._require_current_lease(inv, now, env["lease"])
        if topic["state_revision"] != env["expected_state_revision"]:
            raise Refusal("state_revision_stale", f"the topic is at state revision {topic['state_revision']}")
        admission = self._admission_json(inv)
        if not canonical.canonical_bytes(env["admission"]) == canonical.canonical_bytes(admission):
            raise Refusal("contract_revision_stale", "the envelope's admission is not the invocation's pinned admission (C-12)")
        if env["config_bundle_hash"] != inv["config_bundle_hash"]:
            raise Refusal("config_bundle_mismatch", "the envelope's config bundle is not the invocation's pinned one")
        if topic["paused_at"] is not None:
            raise Refusal("topic_paused", f"paused at {topic['paused_at']}")
        self._require_current_pins(inv)
        if inv["cancel_requested_at"] is not None:  # a cancellation, once requested, admits no further effect (L-7; task 1c)
            raise Refusal("invocation_state_invalid", f"cancellation of {inv['invocation_id']} was requested at {inv['cancel_requested_at']}")
        if final:
            finals = [r for r in self._store.select("operation_receipts", {"invocation_id": inv["invocation_id"]}) if r["operation_kind"] == "final_outcome"]
            if finals:
                raise Refusal("final_outcome_exists", f"{inv['invocation_id']} finalized with {finals[0]['operation_id']}")
            if inv["state"] != "result_ready" or inv["result_payload_digest"] != env["payload_digest"]:
                raise Refusal("invocation_state_invalid", f"a final outcome commits the result staged by a result_ready invocation ({inv['state']})")
            if inv["kind"] != "delegate":  # the lease a final outcome releases is its delegates' too (L-7, L-8; task 1c-repair A3)
                try:
                    self._require_delegates_ended(inv)
                except Refusal as refusal:
                    raise Refusal("invocation_state_invalid", refusal.detail) from None
        elif inv["state"] != "running":
            raise Refusal("invocation_state_invalid", f"an interim transition is committed while running, not {inv['state']}")
        for content_hash, ref in checked["artifacts"].items():  # recorded since validation, by another commit? then as validated (A10; Astra 1b review A4)
            stored = self._one("artifacts", {"content_hash": content_hash})
            if stored is not None and (stored["size_bytes"], stored["media_type"]) != (ref["size_bytes"], ref["media_type"]):
                raise Refusal("payload_invalid", f"{content_hash} was recorded meanwhile as {stored['size_bytes']} bytes of {stored['media_type']} (A10)")
        for doc in payload["decision_receipts"]:  # revoked since validation? then no longer qualified (D-4, D-11)
            authorization = doc["authorization"]
            if authorization["authority_level"] == "qualified" and not self.is_qualified(
                    provider=doc["provider"], decision_class=doc["decision_class"], spec_hash=doc["spec"]["spec_hash"],
                    qualification_ref=authorization["qualification_ref"]):
                raise Refusal("payload_invalid", f"{doc['decision_receipt_id']}: its qualification was revoked meanwhile (D-4, D-11)")
        self._fault("in_transaction:fenced")

        # effects, decided before the receipt so the receipt records them all
        ordinal = None
        if final and inv["kind"] == "research_pass" and inv["admission_context"] == "contract/1":
            ordinal = self._store.next_in_sequence("research_ordinals", "ordinal", {"topic_id": inv["topic_id"]})
        queue_transition, rest_state, lease_release = None, "idle", None
        if final and inv["kind"] == "research_pass" and topic["status"] == "active":
            target = payload["next_queue_state"] or "resting"
            queue_transition, rest_state = {"from": "active", "to": target}, ("rest_until" if target == "resting" else "idle")
        elif topic["status"] == "held":
            rest_state = "held"
        if final and inv["kind"] != "delegate":
            lease_release = {"lease_id": lease["lease_id"], "generation": lease["generation"], "rest_state": rest_state}
        known = {row["trigger_identity"] for row in self._store.select("review_triggers", {"topic_id": inv["topic_id"]})}
        triggers = [(boundary.trigger_identity(inv["topic_id"], t), t) for t in payload["review_triggers"]]
        new_triggers = list({identity: t for identity, t in triggers if identity not in known}.items())
        outbox = [(self._new_id("obx_"), manifest, manifest_hash) for manifest, manifest_hash in checked["manifests"]]
        receipt_id, audit_id = self._new_id("rcpt_"), self._new_id("aud_")
        after = topic["state_revision"] + 1
        receipt = boundary.normalize({
            "receipt_version": "commit-receipt/1", "receipt_id": receipt_id, "operation_id": env["operation_id"],
            "operation_kind": env["operation_kind"], "invocation_id": inv["invocation_id"], "topic_id": inv["topic_id"],
            "request_fingerprint": fingerprint, "payload_digest": env["payload_digest"],
            "hash_contract": {"canonicalization": canonical.CANONICALIZATION, "fingerprint": canonical.FINGERPRINT_CONTRACT},
            "admission": admission, "committed_at": now, "state_revision_before": topic["state_revision"], "state_revision_after": after,
            "validation": checked["validation"],
            "effects": {"evidence_revision": None, "research_ordinal": ordinal, "queue_transition": queue_transition, "lease_release": lease_release,
                        "holds_created": [h["hold_id"] for h in payload["holds"]], "retry_intent": None,
                        "trigger_identities": [identity for identity, _ in new_triggers], "outbox_event_ids": [o[0] for o in outbox],
                        "decision_receipt_ids": [d["decision_receipt_id"] for d in payload["decision_receipts"]], "audit_event_id": audit_id}},
            "payload_invalid")
        boundary.require_schema(self._schemas, receipt, "commit-outcome.schema.json#/$defs/receipt", "payload_invalid")

        self._set_topic(topic, now, queue_transition["to"] if queue_transition else None)
        for content_hash, ref in checked["artifacts"].items():
            if self._one("artifacts", {"content_hash": content_hash}) is None:
                self._store.insert("artifacts", {"content_hash": content_hash, "size_bytes": ref["size_bytes"], "media_type": ref["media_type"],
                                                 "topic_id": inv["topic_id"], "staged_by_invocation_id": inv["invocation_id"], "staged_at": now})
            self._authorize_artifact(content_hash, inv, now)  # staged in this topic's spool with this commit: this topic's, whoever recorded the bytes first
        lease_id = lease["lease_id"]
        self._store.insert("operation_receipts", {
            "operation_id": env["operation_id"], "receipt_id": receipt_id, "operation_kind": env["operation_kind"], "invocation_id": inv["invocation_id"],
            "topic_id": inv["topic_id"], "request_fingerprint": fingerprint, "payload_digest": env["payload_digest"], "lease_id": lease_id,
            "lease_generation": lease["generation"], "admission_context": inv["admission_context"], "contract_revision": inv["contract_revision"],
            "brief_hash": inv["brief_hash"], "config_bundle_hash": inv["config_bundle_hash"], "state_revision_before": topic["state_revision"],
            "state_revision_after": after, "validator_version": VALIDATOR_VERSION, "policy_version": checked["validation"]["policy_version"], "receipt": receipt, "committed_at": now})
        self._fault("in_transaction:receipt")
        if ordinal is not None:
            self._store.insert("research_ordinals", {"topic_id": inv["topic_id"], "ordinal": ordinal, "invocation_id": inv["invocation_id"],
                                                     "operation_id": env["operation_id"]})
        if lease_release is not None:
            self._store.update("leases", {"lease_id": lease_id}, {"released_at": now, "release_reason": "final_outcome"})
        if final:
            self._store.update("invocations", {"invocation_id": inv["invocation_id"]}, {"state": "committed", "state_changed_at": now})
            self._transition_row(inv["invocation_id"], "result_ready", "committed", now, "commit_outcome")
        written = self._write_evidence(env, inv, checked, now, new_triggers, outbox)
        self._fault("in_transaction:evidence")
        self._store.insert("audit_events", {"audit_event_id": audit_id, "at": now, "kind": "commit_outcome", "topic_id": inv["topic_id"],
                                            "invocation_id": inv["invocation_id"], "operation_id": env["operation_id"],
                                            "detail": {**written, "receipt_id": receipt_id,
                                                       "triggers_already_recorded": sorted({i for i, _ in triggers} - {i for i, _ in new_triggers})}})
        self._fault("in_transaction:end")
        return "committed", receipt

    def _write_evidence(self, env: dict, inv: dict, checked: dict, now: str, new_triggers: list, outbox: list) -> dict:
        """The evidence and governance rows of one commit. Producer, verifier,
        recorder and signal source are the committing invocation and
        operation — never a document field (V-10, RG-5, G-12)."""
        payload, op_id, topic_id = checked["payload"], env["operation_id"], inv["topic_id"]
        claims = []
        for claim in payload["claims"]:
            prior = self._store.select("claims", {"claim_id": claim["claim_id"]})
            if any(row["topic_id"] != topic_id for row in prior):
                raise Refusal("cross_topic", f"{claim['claim_id']} is another topic's claim")
            if claim["revision"] != max((row["revision"] for row in prior), default=0) + 1:
                raise Refusal("payload_invalid", f"{claim['claim_id']}: the next revision is {len(prior) + 1}")
            self._store.insert("claims", {"claim_id": claim["claim_id"], "revision": claim["revision"], "topic_id": topic_id,
                                          "text_ref": claim["text_ref"]["content_hash"], "producer_invocation_id": inv["invocation_id"],
                                          "load_bearing": claim["load_bearing"], "required_access_tier": claim["required_access_tier"],
                                          "status": "provisional", "created_at": now})
            claims.append([claim["claim_id"], claim["revision"]])
        for hold in payload["holds"]:
            self._store.insert("holds", {**hold, "topic_id": topic_id, "created_at": now, "created_by_operation_id": op_id})
        for doc in payload["verification_receipts"]:
            self._store.insert("verification_receipts", {
                "verification_receipt_id": doc["verification_receipt_id"], "topic_id": doc["topic_id"], "claim_id": doc["claim"]["claim_id"],
                "claim_revision": doc["claim"]["claim_revision"], "work_id": doc["source"]["work_id"], "source_version": doc["source"]["source_version"],
                "cited_spans": doc["cited_spans"], "obtained_content_hash": doc["obtained_content_hash"], "access_tier": doc["access_tier"],
                "use": doc["requested_for"]["use"], "required_access_tier": doc["requested_for"]["required_access_tier"], "acquisition": doc["acquisition"],
                "extraction_method": doc["extraction"]["method"], "extraction_invocation_id": doc["extraction"]["produced_by_invocation_id"],
                "extraction_validation_ref": doc["extraction"]["validation_ref"], "producer_invocation_id": doc["producer_invocation_id"],
                "verifier_invocation_id": doc["verifier_invocation_id"], "quote_check_id": doc["quote_check_id"], "verdict": doc["verdict"],
                "receipt": doc, "verified_at": doc["verified_at"]})
        for doc in payload["decision_receipts"]:
            response, outcome = doc["provider_response"], doc["outcome"]
            self._store.insert("decision_receipts", {
                "decision_receipt_id": doc["decision_receipt_id"], "invocation_id": doc["invocation_id"], "topic_id": doc["topic_id"],
                "spec_hash": doc["spec"]["spec_hash"], "decision_class": doc["decision_class"], "provider": doc["provider"],
                "input_status": doc["input_manifest"]["input_status"], "response_status": response["status"],
                "raw_response_digest": response["raw_response_digest"], "answer": response["answer"], "subject_kind": doc["subject"]["kind"],
                "subject_ref": doc["subject"]["ref"], "policy_id": doc["policy"]["policy_id"], "policy_version": doc["policy"]["version"],
                "authority_level": doc["authorization"]["authority_level"], "qualification_ref": doc["authorization"]["qualification_ref"],
                "action": doc["action"], "commit_operation_id": outcome["commit_operation_id"], "hold_id": outcome["hold_id"],
                "proposal_ref": outcome["proposal_ref"], "blind_sample": doc["blind_sample"]["selected"], "receipt": doc, "decided_at": doc["decided_at"]})
        for assessment in payload["screening_assessments"]:
            contract = self._one("contract_revisions", {"topic_id": topic_id, "revision": inv["contract_revision"]})
            self._store.insert("screening_assessments", {
                **{k: assessment[k] for k in ("assessment_id", "work_id", "stage", "decision", "reason_code", "criterion_results", "actor_kind",
                                              "decision_receipt_id", "supersedes_assessment_id")},
                "topic_id": topic_id, "contract_revision": inv["contract_revision"], "framing_version": contract["framing_version"],
                "eligibility_protocol_version": checked["protocol"]["protocol_version"], "invocation_id": inv["invocation_id"],
                "operator_decision_id": None, "recorded_by_operation_id": op_id, "created_at": now})
        promotions = []
        for promotion in payload["claim_promotions"]:
            row = self._one("claims", {"claim_id": promotion["claim_id"], "revision": promotion["revision"]})
            if row is None:
                raise Refusal("payload_invalid", f"{promotion['claim_id']} revision {promotion['revision']} is not recorded")
            if row["topic_id"] != topic_id:
                raise Refusal("cross_topic", f"{promotion['claim_id']} is another topic's claim")
            if row["status"] not in ("provisional", "contested"):
                raise Refusal("payload_invalid", f"{promotion['claim_id']} revision {promotion['revision']} is {row['status']}")
            producer = self._one("invocations", {"invocation_id": row["producer_invocation_id"]})
            if producer["admission_context"] == "contract/1" and self._pin_status(producer) not in ("current", "compatible"):
                raise Refusal("amendment_pending", f"{promotion['claim_id']} revision {promotion['revision']} was produced under a revision an amendment made "
                                                   "incompatible; contract-admitted work adopts it as a new revision (V-10, G-1)")
            self._store.update("claims", {"claim_id": promotion["claim_id"], "revision": promotion["revision"]}, {"status": "accepted_support"})
            promotions.append([promotion["claim_id"], promotion["revision"]])
        for identity, trigger in new_triggers:
            self._store.insert("review_triggers", {"trigger_identity": identity, "topic_id": topic_id, "reason_code": trigger["reason_code"],
                                                   "signal_source": "primary_observation", "cause_ref": trigger["cause_ref"],
                                                   "observed_at": trigger["observed_at"], "recorded_by_operation_id": op_id})
        for outbox_id, manifest, manifest_hash in outbox:
            supersedes = manifest["supersedes"] or {}
            self._store.insert("outbox_events", {
                "outbox_event_id": outbox_id, "topic_id": topic_id, "manifest_id": manifest["manifest_id"], "manifest_hash": manifest_hash,
                "artifact_kind": manifest["artifact_kind"], "generation": manifest["generation"], "options_revision": manifest["options_revision"],
                "supersedes_generation": supersedes.get("generation"), "supersedes_options_revision": supersedes.get("options_revision"),
                "source_revision": manifest["source"]["revision"], "source_content_hash": manifest["source"]["content_hash"],
                "approval_decision_id": manifest["approval"]["operator_decision_id"], "bundle_content_hash": manifest["bundle"]["content_hash"],
                "expected_connectors": manifest["expected_connectors"], "manifest": manifest, "committed_by_operation_id": op_id, "created_at": now})
        return {"claims": claims, "claim_promotions": promotions,
                "verification_receipts": [d["verification_receipt_id"] for d in payload["verification_receipts"]],
                "screening_assessments": [a["assessment_id"] for a in payload["screening_assessments"]],
                "artifacts": sorted(checked["artifacts"])}

    # -- operator decisions ------------------------------------------------------
    def apply_operator_decision(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._schemas, req, "router-commands#/$defs/operator_decision", "request_invalid")
            return self._guarded("decision_refused", lambda now: self._decision_in_transaction(req, now))
        except Refusal as refusal:
            return {"status": "rejected", "decision_id": request.get("decision_id") if isinstance(request, Mapping) else None,
                    "reason": refusal.reason, "detail": _short(refusal.detail)}

    def _decision_in_transaction(self, req: dict, now: str) -> dict:
        subject = req["subject"]
        row = {"decision_id": req["decision_id"], "topic_id": req["topic_id"], "kind": req["kind"], "disposition": req["disposition"],
               "subject_kind": subject["kind"], "subject_ref": subject["ref"], "subject_revision": subject["revision"], "subject_hash": subject["hash"],
               "operator_id": req["operator_id"], "decided_at": req["decided_at"], "notes": req["notes"], "payload": req["payload"]}
        existing = self._one("operator_decisions", {"decision_id": req["decision_id"]})
        if existing is not None:
            if canonical.canonical_bytes(existing) != canonical.canonical_bytes(row):
                raise Refusal("decision_id_conflict", f"{req['decision_id']} was recorded with different content")
            return {"status": "replayed", "decision_id": req["decision_id"], "effects": None}
        self._require_subject_hash_truth(row)
        self._store.insert("operator_decisions", row)
        effects = self._apply_decision(row, now) if row["disposition"] == "approved" else {}
        self._audit("operator_decision", now, {"kind": row["kind"], "disposition": row["disposition"], "effects": effects}, topic_id=row["topic_id"])
        topic = self._one("queue_entries", {"topic_id": row["topic_id"]}) if row["topic_id"] else None
        return {"status": "applied", "decision_id": req["decision_id"], "effects": effects,
                "state_revision": None if topic is None else topic["state_revision"]}

    def _require_subject_hash_truth(self, row: dict) -> None:
        """RA6: a decision about a stored document binds to a hash that really
        is that document's content hash (recomputed from the stored bytes),
        so a row whose hash label was never true cannot be approved."""
        if row["subject_kind"] == "contract_revision":
            stored = self._one("contract_revisions", {"topic_id": row["topic_id"], "revision": row["subject_revision"]})
        elif row["subject_kind"] == "intake_brief":
            stored = self._one("intake_briefs", {"topic_id": row["topic_id"], "brief_id": row["subject_ref"], "version": row["subject_revision"]})
        else:
            return
        if stored is not None and canonical.content_hash(stored["document"]) != stored["content_hash"]:
            raise Refusal("subject_hash_untrue", f"the stored {row['subject_kind']} does not hash to its recorded content hash")

    def _apply_decision(self, d: dict, now: str) -> dict:
        """The transition an approved decision authorizes, in the decision's
        own transaction. The DDL checks the binding (G-13); a decision whose
        transition the current state does not allow is refused whole."""
        kind, topic = d["kind"], self._one("queue_entries", {"topic_id": d["topic_id"]}) if d["topic_id"] else None
        if kind == "brief_confirmation":
            key = {"topic_id": d["topic_id"], "brief_id": d["subject_ref"]}
            older = self._store.select("intake_briefs", {**key, "status": "confirmed"})
            for row in older:
                self._store.update("intake_briefs", {**key, "version": row["version"]}, {"status": "superseded"})
            self._store.update("intake_briefs", {**key, "version": d["subject_revision"]}, {"status": "confirmed", "confirmed_by_decision_id": d["decision_id"]})
            effects = {**self._move(topic, now, {"awaiting_brief_confirmation": "scoping"}), "brief_confirmed": [d["subject_ref"], d["subject_revision"]]}
            current = self._one("intake_briefs", {**key, "version": d["subject_revision"]})
            for row in older:  # G-1: work pinned to the version this one supersedes (amendments.py)
                effects.update(self._record_impact(d, "brief", row, current, now))
            return effects
        if kind == "scope_approval":
            return self._move(topic, now, {"awaiting_scope_approval": "awaiting_contract_approval"}, required=True)
        if kind in ("contract_approval", "amendment_approval", "reframe_approval"):
            return self._approve_contract(d, topic, now)
        if kind == "completion_approval":
            return self._move(topic, now, {"active": "completed_with_qualified_conclusions", "awaiting_judgment": "completed_with_qualified_conclusions"},
                              required=True, status_decision_id=d["decision_id"])
        if kind == "retirement":
            moves = {} if topic["status"] == "retired" else {topic["status"]: "retired"}
            return self._move(topic, now, moves, required=True, status_decision_id=d["decision_id"])
        if kind == "hold_clearance":
            hold = self._one("holds", {"hold_id": d["subject_ref"]})
            if hold is not None and is_episode_hold(hold):
                raise Refusal("decision_refused", f"{hold['hold_id']} holds an outcome_unknown episode: it clears only through that episode's reconciliation record (L-4)")
            self._store.update("holds", {"hold_id": d["subject_ref"]}, {"cleared_at": now, "cleared_by_decision_id": d["decision_id"]})
            return {"hold_cleared": d["subject_ref"]}
        return {}  # rating, publication, blind and advised decisions are records their consumers read

    def _approve_contract(self, d: dict, topic: dict, now: str) -> dict:
        """Approve exactly this revision, superseding the approved one (one
        approved revision per topic). An amendment revises the approved
        revision (its parent), and a framing change is approved as a reframe
        and only a reframe (G-6, G-7). An approved amendment requeues a
        completed topic (store README, queue status). Then G-1: the impact on
        what was pinned to the superseded revision (amendments.py)."""
        key = {"topic_id": d["topic_id"]}
        revision = self._one("contract_revisions", {**key, "revision": d["subject_revision"]})
        previous = self._one("contract_revisions", {**key, "status": "approved"})
        if previous is not None and revision["parent_revision"] != previous["revision"]:
            raise Refusal("decision_refused", f"revision {revision['revision']} does not revise the approved revision {previous['revision']}")
        reframe = previous is not None and contract_compatibility(previous["document"], revision["document"]) == "reframed"
        if reframe != (d["kind"] == "reframe_approval"):
            raise Refusal("decision_refused", "a framing change is approved as a reframe, and a reframe approval approves a framing change (G-6, G-7)")
        if previous is not None:
            self._store.update("contract_revisions", {**key, "revision": previous["revision"]}, {"status": "superseded"})
        self._store.update("contract_revisions", {**key, "revision": d["subject_revision"]}, {"status": "approved", "approved_by_decision_id": d["decision_id"]})
        effects = self._move(topic, now, {"awaiting_contract_approval": "queued", "completed_with_qualified_conclusions": "queued"},
                             active_contract_revision=d["subject_revision"], status_decision_id=None)
        effects.update(contract_approved=d["subject_revision"], contract_superseded=[] if previous is None else [previous["revision"]])
        if previous is not None:
            effects.update(self._record_impact(d, "contract", self._one("contract_revisions", {**key, "revision": previous["revision"]}),
                                               self._one("contract_revisions", {**key, "revision": d["subject_revision"]}), now))
        return effects

    def _move(self, topic: dict, now: str, moves: dict, *, required: bool = False, **queue_columns) -> dict:
        """Apply the queue move for the topic's current status, with any
        queue_entries columns the decision sets, as one revision step. With no
        move for the current status, a `required` one refuses the decision
        whole; otherwise only the columns (if any) are written."""
        target = moves.get(topic["status"])
        if target is None and required:
            raise Refusal("decision_refused", f"the topic is {topic['status']}; this decision moves it only from {sorted(moves)}")
        if target is None and not queue_columns:
            return {"queue_transition": None}
        self._set_topic(topic, now, target, **queue_columns)
        return {"queue_transition": None if target is None else {"from": topic["status"], "to": target}}

    # -- export delivery ---------------------------------------------------------
    def ack_delivery(self, receipt: Mapping) -> dict:
        try:
            doc = boundary.normalize(receipt, "request_invalid")
            boundary.require_schema(self._schemas, doc, "export-delivery-receipt.schema.json", "request_invalid")
            return self._guarded("delivery_refused", lambda now: self._ack_in_transaction(doc, now))
        except Refusal as refusal:
            return {"status": "rejected", "export_receipt_id": receipt.get("export_receipt_id") if isinstance(receipt, Mapping) else None,
                    "reason": refusal.reason, "detail": _short(refusal.detail)}

    def _ack_in_transaction(self, doc: dict, now: str) -> dict:
        """One attempt of one connector: recorded once, whole, for a committed
        manifest's own connector, pair and topic; a failure or unknown outcome
        raises its dated capability fact (H-2, P-7); a delivery advances the
        connector's watermark, which never regresses (P-2). The receipt
        document is stored as it came (JCS) beside the columns projected
        from it (EXPORT-API.md §9 item 3), so the written count keeps its
        observed, partial or unknown state and the hold and invocation it
        names are kept (Astra 1b review A2). Which invocation a delivery runs
        under is the exporter's (Phase 3): the router keeps that reference
        and does not yet check what it names."""
        rid, connector, written = doc["export_receipt_id"], doc["connector"], doc["written"]
        existing = self._one("export_delivery_receipts", {"export_receipt_id": rid})
        if existing is not None:  # the key replays exactly the document it recorded, every field of it
            if canonical.canonical_bytes(existing["receipt"]) != canonical.canonical_bytes(doc):
                raise Refusal("export_receipt_id_conflict", f"{rid} was recorded with different content")
            return {"status": "replayed", "export_receipt_id": rid}
        event = self._one("outbox_events", {"manifest_id": doc["manifest_id"]})
        if event is None:
            raise Refusal("unknown_manifest", f"{doc['manifest_id']} is not a committed manifest")
        if doc["topic_id"] != event["topic_id"] or (doc["generation"], doc["options_revision"]) != (event["generation"], event["options_revision"]):
            raise Refusal("delivery_refused", f"{rid} does not describe {doc['manifest_id']}'s topic and ordering pair")
        hold = doc.get("hold_id")
        if hold is not None and self._one("holds", {"hold_id": hold, "topic_id": event["topic_id"]}) is None:
            raise Refusal("delivery_refused", f"{rid}: {hold} is not a recorded hold of {event['topic_id']} (H-3)")
        attempts = self._store.select("export_delivery_receipts", {"manifest_id": doc["manifest_id"], "connector_id": connector["connector_id"]})
        if doc["attempt"] != len(attempts) + 1:
            raise Refusal("delivery_refused", f"the next attempt for {connector['connector_id']} is {len(attempts) + 1}")
        capability = f"export-connector:{connector['connector_id']}"
        if doc["status"] in ("failed", "outcome_unknown"):
            self._record_fact(capability, doc["capability_fact_id"], "failing" if doc["status"] == "failed" else "unknown",
                              doc.get("error_class") or doc.get("unknown_cause"), doc["attempted_at"], now)
        self._store.insert("export_delivery_receipts", {
            "export_receipt_id": rid, "manifest_id": doc["manifest_id"], "connector_id": connector["connector_id"],
            "connector_type": connector["connector_type"], "attempt": doc["attempt"], "status": doc["status"],
            "tombstones_acknowledged": doc["tombstones_acknowledged"], "reconciliation_required": doc["reconciliation_required"],
            "error_class": doc.get("error_class"), "unknown_cause": doc.get("unknown_cause"), "capability_fact_id": doc.get("capability_fact_id"),
            "written_status": written["status"], "written_value": written.get("value"), "hold_id": hold,
            "attempted_at": doc["attempted_at"], "acked_at": doc["acked_at"], "receipt": doc})
        if doc["status"] == "delivered":
            self._advance_watermark(event, connector["connector_id"], doc["acked_at"])
            self._record_fact(capability, None, "healthy", "delivered", doc["acked_at"], now)
        self._audit("delivery_receipt", now, {"export_receipt_id": rid, "status": doc["status"]}, topic_id=event["topic_id"])
        return {"status": "recorded", "export_receipt_id": rid}

    def _advance_watermark(self, event: dict, connector_id: str, delivered_at: str) -> None:
        key = {"topic_id": event["topic_id"], "connector_id": connector_id}
        pair = (event["generation"], event["options_revision"])
        mark = self._one("connector_watermarks", key)
        if mark is None:
            self._store.insert("connector_watermarks", {**key, "generation": pair[0], "options_revision": pair[1], "delivered_at": delivered_at})
        elif pair > (mark["generation"], mark["options_revision"]):
            self._store.update("connector_watermarks", key, {"generation": pair[0], "options_revision": pair[1], "delivered_at": delivered_at})
        elif pair < (mark["generation"], mark["options_revision"]):
            raise Refusal("watermark_regression", f"{connector_id} already holds ({mark['generation']}, {mark['options_revision']}); "
                                                  "a delivery of an older pair contradicts the ordering contract (P-2)")

    def _record_fact(self, capability: str, fact_id: str | None, state: str, detail: str, since: str, now: str) -> None:
        """A dated capability fact, recorded only on a transition (H-2). A
        failure names its fact: the connector's current fact when it is
        already in that state, or a new id when this attempt changes the
        state. A delivery after a failing or unknown fact records the
        recovery as a new healthy fact."""
        current = next((f for f in self._store.select("capability_facts", {"capability": capability}) if f["superseded_by_fact_id"] is None), None)
        if fact_id is None:  # a recovery is recorded only as a transition out of failing/unknown
            if current is None or current["state"] == state:
                return
            fact_id = self._new_id("fact_")
        elif current is not None and current["fact_id"] == fact_id:
            if current["state"] != state:
                raise Refusal("delivery_refused", f"{fact_id} is {current['state']}, not {state}")
            return
        elif current is not None and current["state"] == state:
            raise Refusal("delivery_refused", f"{capability} is already {state} as {current['fact_id']}; a fact is raised on a transition only (H-2)")
        elif self._one("capability_facts", {"fact_id": fact_id}) is not None:
            raise Refusal("delivery_refused", f"{fact_id} is not {capability}'s current fact")
        if current is not None:
            self._store.update("capability_facts", {"fact_id": current["fact_id"]}, {"superseded_by_fact_id": fact_id})
        self._store.insert("capability_facts", {"fact_id": fact_id, "capability": capability, "state": state, "detail": detail, "since": since,
                                                "affected_lanes": [], "recorded_at": now})

