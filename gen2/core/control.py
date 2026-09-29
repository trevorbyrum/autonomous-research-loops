"""The ControlBackend protocol: the one write interface to authoritative state.

Trace: design review §5 ("The ControlBackend contract should support
operations such as claim, record_observation, commit_outcome,
apply_operator_decision, and ack_delivery, with uniqueness, fencing, and
atomicity specified. It must not expose unrestricted snapshots for callers to
mutate."); gen2/boundaries.toml modules.core (the protocol other modules code
against) and modules.app (the composition root hands it to supervisor,
exporter and operator, so none of them imports the router); BOUNDARIES.md
Router; INVARIANTS C-1..C-13; task 1b.

Every operation takes and returns plain JSON values (dicts, lists, strings,
numbers). A returned value is a fresh copy built from committed rows:
mutating it changes nothing, and nothing here hands out the store. Each
operation's uniqueness, fencing and atomicity are stated on it below; the
implementation is gen2/router/service.py (the only one; design review §5:
another backend must pass the same behavioural tests first).

The supervisor (task 1c) reaches the router only through this protocol,
wired by the composition root; it never imports the router or the store.
When the router cannot be reached, a backend raises ControlUnavailable and
nothing is known to have happened: the caller keeps what it holds and sends
the same request again under the same key, within its declared budget
(C-10, L-6).

The collaborators the router reads through (supplied by the composition
root) are protocols here too, so the router needs no import of the modules
that implement them:
  * StagedBytes: the protected spool's read side (gen2/supervisor/spool.py);
  * ExtensionRegistry: which reviewed extension connectors the image carries
    (EXPORT-API.md §7; Phase 3 registers them). Its default (router.service)
    admits nothing, never "any non-null string" (INVARIANTS §13).
Qualification is not a collaborator: its records are the router's own
(gen2/router/registries.py, task 1d), and none recorded means none qualified.
"""
from __future__ import annotations

from typing import Mapping, Protocol


class ControlUnavailable(Exception):
    """The router could not be reached. Nothing is known to have happened;
    every operation is idempotent under its key, so the same request is sent
    again (C-10). Raised by a transport, never by the router: today by a test
    double standing between the supervisor and the router (the supervisor
    runs in the engine's own process); the exporter's transport (Phase 3)
    raises it when the engine's listener cannot be reached."""


class StagedBytes(Protocol):
    """The spool is topic-scoped (C-9): an artifact is staged for one topic
    and read only under it."""

    def read(self, content_hash: str, *, topic_id: str) -> bytes | None:
        """The bytes staged for this topic under this content hash, or None
        if nothing is. The router recomputes the digest itself; a wrong
        answer here is refused, never trusted (C-9, hash truth)."""

    def media_type(self, content_hash: str, *, topic_id: str) -> str | None:
        """The media type the spool recorded when these bytes were staged for
        this topic, or None if nothing is staged."""


class ExtensionRegistry(Protocol):
    def is_admitted(self, *, module: str, review_ref: str) -> bool:
        """True only for an extension connector the image carries under this
        accepted review (EXPORT-API.md §5, §7)."""


class ControlBackend(Protocol):
    """Every authoritative state change goes through one of these (C-1).
    Each is one short transaction with no subprocess or network call inside
    it (C-4, C-8), and each is idempotent under its own key, so a caller that
    lost a reply resubmits the same request. Leases, deadlines and expiry are
    judged against the clock read inside that transaction, once the write
    lock is held, so time spent waiting for the lock counts; a lease or
    deadline at instant E is over at E."""

    def claim(self, request: Mapping) -> dict:
        """Admit one invocation. Key: invocation_id (the supervisor's stable
        job identity, L-8): the same request again returns the same grant, a
        different request under that id is refused. A non-delegate gets a new
        lease of its kind's scope, generation above every earlier one of the
        topic, and at most one live lease per (topic, scope); a delegate runs
        under its parent's lease and pins. The capability returned is the
        invocation's authority for everything below."""

    def record_transition(self, request: Mapping) -> dict:
        """Record a lifecycle fact the supervisor observed (launch intent,
        process identity, staged result, failure with its structural class
        and execution record, cancellation with its confirmed descendant
        handling, entry into outcome_unknown) under the invocation's
        capability, along L-1 only. Key: (invocation, target state), and for
        outcome_unknown (invocation, episode): repeating a recorded fact is a
        replay whatever state the invocation has reached since, and the same
        key with other facts (an outcome_unknown entry's cause included) is
        a conflict. A failure or cancellation releases the invocation's lease
        only once its evidence confirms the execution group's descendants
        were handled (L-7), and a parent's only once no delegate of it is
        live (L-8); entering
        outcome_unknown opens the episode's router hold, owned by the
        station, with a deadline (L-4, RG-3)."""

    def request_cancel(self, request: Mapping) -> dict:
        """Record that an invocation is to be cancelled, and by whom
        (operator, router or supervisor). Key: invocation. Work never
        launched is cancelled at once (nothing was spawned: L-2); launched
        work keeps its lease until the supervisor records `cancelled` with
        its evidence; once requested, no result, observation or commit of
        that invocation is accepted. A result already staged (result_ready)
        or an end already recorded is refused as not cancellable: the
        cancellation lost the race."""

    def reconcile(self, request: Mapping) -> dict:
        """Leave the current outcome_unknown episode through its durable
        reconciliation record: the method, the supervisor's execution record
        as evidence, and the resolution that evidence supports (L-4). A
        confirmed failure names its failure class; a terminated group names
        one exactly when it ends failed — under a cancellation request it
        ends cancelled, with none. Key: (invocation, episode); the identical
        complete request replays, any changed fact (identity, class, evidence)
        is a conflict. Clears the episode's hold (the only way it clears); a
        terminal resolution releases the lease, once no delegate of it is
        live."""

    def invocation_status(self, request: Mapping) -> dict:
        """Read one invocation's lifecycle state under its capability: state,
        cancellation request, unknown episode, deadline, lease currency,
        pause, recorded facts, the topic's state revision, and
        launch_admission: the launch-admission check as it stands now (None,
        or the refusal), which the supervisor reads before every actual
        start. A fresh copy of committed rows; reading it authorizes
        nothing."""

    def record_observation(self, request: Mapping) -> dict:
        """Record one search observation and the retrieval events captured
        with it, under the capability of a running invocation whose lease is
        current. Key: observation_id."""

    def register_works(self, request: Mapping) -> dict:
        """Link retrieved records of the invocation's topic to the works they
        are, by identity (task 2a; E-3), under the capability, while running
        and its lease current. Key: each record's link, recorded once."""

    def commit_outcome(self, envelope: Mapping) -> dict:
        """The commit protocol (design review §5 steps 1-5; C-2..C-5): replay
        or reject by operation_id, validate outside the transaction, fence and
        write in one transaction, return the receipt only after commit.
        Returns a commit-outcome.schema.json#/$defs/response."""

    def receipt(self, operation_id: str) -> dict | None:
        """The committed receipt for an operation, if any (lost-reply
        recovery, C-5). Reading a receipt authorizes nothing (RG-1b(d))."""

    def apply_operator_decision(self, request: Mapping) -> dict:
        """Record one operator decision and apply the transition it authorizes
        in the same transaction (G-13). Key: decision_id."""

    def ack_delivery(self, receipt: Mapping) -> dict:
        """Record one export-delivery-receipt/2, whole, for a committed
        manifest and advance the connector's watermark from a delivered one.
        Key: export_receipt_id; only the identical document replays."""

    def record_capability_probe(self, observation: Mapping) -> dict:
        """Record one capability probe's observation, the station supervisor's
        classification of a provider's auth home (task 1f;
        gen2/router/capabilities.py): kept whole; the capability's dated fact
        moved on a transition only, following the newest observation; a hold
        of the capability, the operator's, opened when it is not usable and
        none is open (H-2, RG-3). Key: probe_id; only the identical
        observation replays."""


class OperatorBackend(ControlBackend, Protocol):
    """What the operator surface (gen2/operator/service.py, task 1e) is handed
    by the composition root: the router's operations for the trusted surface,
    beside the protocol above, and two of the station's (recover_incident,
    probe_capability).
    The surface authenticates the principal and fills the fields that name
    it; the router validates, fences and writes as for every operation. None
    of these hands out the store."""

    def recover_incident(self, request: Mapping) -> dict:
        """The station's, not the router's (gen2/supervisor/supervisor.py
        Supervisor.recover_incident; task 1e-repair): an operator's request
        that the station recover one job stalled on an open incident, within
        the job's recovery budget. The station ends the job's execution group
        afresh where its retained end's descendants were never confirmed
        ended, then resumes the job, which reaches the router only through the
        invocation's own capability-bearing operations (an outcome_unknown
        episode through reconcile, the only way its hold clears). Key: the
        incident; the request once it is closed replays."""

    def probe_capability(self, request: Mapping) -> dict:
        """The station's, not the router's (gen2/supervisor/probe.py; task 1f):
        an operator's request that the station probe one provider's auth home
        with its pinned runner now — {provider}; the surface supplies
        requested_by. The observation reaches the router as
        record_capability_probe, whose answer this returns."""

    def activate_config_bundle(self, document: Mapping) -> dict:
        """Validate and activate a mounted config-bundle/1 (task 1d)."""

    def version_brief(self, request: Mapping) -> dict:
        """Write the next version of an intake brief (task 1d)."""

    def mark_brief_overdue(self, request: Mapping) -> dict:
        """Mark a version awaiting confirmation overdue, once its deadline has
        passed on the router's clock (task 1d, G-4)."""

    def close_brief(self, request: Mapping) -> dict:
        """Cancel a version awaiting confirmation, or archive a confirmed one,
        naming the operator who closed it (task 1e, G-4)."""

    def propose_amendment(self, request: Mapping) -> dict:
        """Write the next contract revision as a draft of the approved one (task 1d)."""

    def requeue(self, request: Mapping) -> dict:
        """Re-queue ended failed or cancelled work (task 1d, L-6)."""

    def status(self, request: Mapping) -> dict:
        """The committed record the operator's status is composed from, in one
        snapshot, with the router's own judgments of it now (task 1e). Writes
        nothing."""

    def healthy(self) -> bool:
        """The router can commit now (DEPLOYMENT-CONTRACT.md §1.2). Writes nothing."""

