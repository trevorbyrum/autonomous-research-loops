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
  * QualificationRegistry: which (provider, class, spec) may act at
    qualified authority (task 1d loads fake records; Phase 3 real ones);
  * ExtensionRegistry: which reviewed extension connectors the image carries
    (EXPORT-API.md §7; Phase 3 registers them).
Their defaults (router.service) admit nothing: no registry means no
qualification and no extension, never "any non-null string" (INVARIANTS §13).
"""
from __future__ import annotations

from typing import Mapping, Protocol


class ControlUnavailable(Exception):
    """The router could not be reached. Nothing is known to have happened;
    every operation is idempotent under its key, so the same request is sent
    again (C-10). Raised by a transport (task 1e), never by the router."""


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


class QualificationRegistry(Protocol):
    def is_qualified(self, *, provider: str, decision_class: str, spec_hash: str, qualification_ref: str) -> bool:
        """True only for a live qualification of exactly this provider, class
        and DecisionSpec (INVARIANTS D-4, D-5)."""


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
        key with other facts is a conflict. A failure or cancellation
        releases the invocation's lease only once its evidence confirms the
        execution group's descendants were handled (L-7); entering
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
        as evidence, and the resolution that evidence supports (L-4). Key:
        (invocation, episode); the identical record replays, another is a
        conflict. Clears the episode's hold; a terminal resolution releases
        the lease."""

    def invocation_status(self, request: Mapping) -> dict:
        """Read one invocation's lifecycle state under its capability: state,
        cancellation request, unknown episode, deadline, lease currency,
        pause, recorded facts and the topic's state revision. A fresh copy of
        committed rows; reading it authorizes nothing."""

    def record_observation(self, request: Mapping) -> dict:
        """Record one search observation and the retrieval events captured
        with it, under the capability of a running invocation whose lease is
        current. Key: observation_id."""

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
