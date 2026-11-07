"""Shared builder core: refusals, deterministic ids, the empty-section outcome scaffold.

Trace: 2e2-min design O14.6; INVARIANTS C-2, C-9 (the model authors no id, hash or pin), C-10 (a replay
builds the same bytes, so it collides instead of duplicating). Oracle: the closed outcome/1 schema's required
keys, compared in tests; the router re-validates every committed document. Limits: it knows no purpose; the
purpose builders map judgment to sections, and the router fills producer, contract pins and attribution.
"""
from __future__ import annotations

import hashlib
from typing import Iterable, Mapping, Protocol, Sequence

from gen2.core import canonical

REQUIRED_SECTIONS = ("claims", "claim_promotions", "claim_source_links", "verification_receipts", "decision_receipts",
                     "screening_assessments", "review_triggers", "review_closures", "scoping_reports",
                     "source_proposals", "holds", "exports")
OPTIONAL_SECTIONS = ("search_proposals", "source_artifacts", "obligation_assessments", "completion_records",
                     "quote_checks", "detailed_check_records")


class Exchanges(Protocol):
    def response(self, gateway_call_ref: str) -> tuple[Mapping, bytes] | None:
        """(artifact_ref, bytes) staged for this topic's retained gateway response, or None."""


class RecordsReader(Protocol):
    def topic_records(self, request: Mapping) -> dict:
        """{topic_id, families} -> {status: ok, topic_id, records: {family: [row, ...]}} or {status: refused, ...}."""


def latest_revision(rows: Iterable[Mapping], key: str = "claim_id") -> dict[str, Mapping]:
    """The highest-revision row for each `key` value."""
    latest: dict[str, Mapping] = {}
    for row in rows:
        if row[key] not in latest or row["revision"] > latest[row[key]]["revision"]:
            latest[row[key]] = row
    return latest


class Refused(ValueError):
    """The executor stops before producing a result; nothing is committed, so nothing is half-written."""


def derived_id(prefix: str, invocation_id: str, kind: str, index: int) -> str:
    """`<prefix>_<24 hex>` from (invocation, kind, index). The same invocation builds the same id."""
    digest = hashlib.sha256(f"{invocation_id}\0{kind}\0{index}".encode()).hexdigest()
    return f"{prefix}_{digest[:24]}"


def scaffold(invocation_id: str, topic_id: str, *, next_queue_state: str | None = None, **sections: object) -> dict:
    """An outcome/1 document: every required section present and empty unless given."""
    unknown = set(sections) - set(REQUIRED_SECTIONS) - set(OPTIONAL_SECTIONS)
    if unknown:
        raise Refused(f"not an outcome section: {sorted(unknown)}")
    document = {"outcome_version": "outcome/1", "invocation_id": invocation_id, "topic_id": topic_id,
                "operation_kind": "final_outcome", "next_queue_state": next_queue_state}
    document.update({name: [] for name in REQUIRED_SECTIONS})
    document.update(sections)
    return document


def outcome_bytes(document: Mapping) -> bytes:
    """The exact bytes staged and hashed: canonical, so equal documents give equal digests."""
    return canonical.canonical_bytes(document)
