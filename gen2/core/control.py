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

The collaborators the router reads through (supplied by the composition
root) are protocols here too, so the router needs no import of the modules
that implement them:
  * StagedBytes: the protected spool's read side (task 1c builds the spool);
  * QualificationRegistry: which (provider, class, spec) may act at
    qualified authority (task 1d loads fake records; Phase 3 real ones);
  * ExtensionRegistry: which reviewed extension connectors the image carries
    (EXPORT-API.md §7; Phase 3 registers them).
Their defaults (router.service) admit nothing: no registry means no
qualification and no extension, never "any non-null string" (INVARIANTS §13).
"""
from __future__ import annotations

from typing import Mapping, Protocol


class StagedBytes(Protocol):
    def read(self, content_hash: str) -> bytes | None:
        """The bytes staged under this content hash, or None if nothing is.
        The router recomputes the digest itself; a wrong answer here is
        refused, never trusted (C-9, hash truth)."""


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
        process identity, staged result, failure, cancellation) under the
        invocation's capability, along L-1 only. Key: (invocation, target
        state): repeating a recorded fact is a replay whatever state the
        invocation has reached since, and the same key with other facts is
        a conflict."""

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
