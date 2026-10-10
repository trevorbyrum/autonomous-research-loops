"""Explicit reconciliation operands (S7/S8), supplied by fixtures in this slice.

These records and checks prove no approval, provenance or durable admission.
2d owns admission/assembly; 2e2 produces judgments. No export path lives here.
"""
from dataclasses import dataclass
from typing import Literal

from gen2 import accounting as a


@dataclass(frozen=True)
class SchemePin:
    scheme_id: str
    version: int


@dataclass(frozen=True)
class UnknownConfidence:
    basis: Literal["unknown"]
    reason: str


@dataclass(frozen=True)
class RecordedConfidence:
    basis: Literal["recorded_assessment"]
    scheme: SchemePin
    label: str
    assessed_by_invocation_id: str


@dataclass(frozen=True)
class ObligationRecord:
    """Attribution belongs to this record, including an explicit open record."""
    record_id: str
    topic_id: str
    obligation_id: str
    subject: str
    contract_revision: int
    contract_content_hash: str
    eligibility_protocol_version: int
    framing_version: int
    evidence_refs: tuple[a.EvidenceReference, ...]
    actor_kind: Literal["primary"]
    invocation_id: str
    recorded_by_operation_id: str
    created_at: str
    reason: str
    supersedes_id: str | None


@dataclass(frozen=True)
class ObligationAssessment(ObligationRecord):
    disposition: Literal["supported", "contradicted", "unresolved", "deferred"]
    confidence: UnknownConfidence | RecordedConfidence


@dataclass(frozen=True)
class OpenObligation(ObligationRecord):
    """A separately recorded not-yet-assessed state, never an unresolved verdict."""
    state: Literal["open"]
    confidence: UnknownConfidence


@dataclass(frozen=True)
class ReconciliationOperands:
    """Complete supplied histories, without selecting or inventing judgments.

    Registry, semantic and lifecycle identities are scoped to topic_id; lineage
    inherits its assessment's attribution. Deferrals are obligation records in
    obligations, including replaced and competing assessments. No empty-history
    defaults hide a missing operand. G-1 standing stays separately recorded.
    """
    topic_id: str
    obligations: tuple[ObligationAssessment | OpenObligation, ...]
    semantic_assessments: tuple[a.SemanticAssessment, ...]
    source_lineage: tuple[a.SourceLineage, ...]
    source_lifecycle: tuple[a.SourceDisposition, ...]
    registry_dispositions: tuple[a.RegistryDisposition, ...]
    current_contract_revision: int | None
    amendment_impacts: tuple[a.AmendmentImpact, ...]


def check_confidence(record: ObligationAssessment | OpenObligation,
                     approved_contract: dict) -> UnknownConfidence | RecordedConfidence:
    """Check one explicit operand against its supplied approved revision.

    The caller supplies a schema-validated approved contract document from the
    existing approval path. Equality of pins and scheme membership establish
    consistency only; this pure helper cannot establish approval or provenance.
    Historical records require their own contract, even after a scheme change.
    """
    pins = (record.topic_id, record.contract_revision, record.contract_content_hash,
            record.eligibility_protocol_version, record.framing_version)
    declared = (approved_contract["topic_id"], approved_contract["revision"],
                approved_contract["content_hash"], approved_contract["eligibility_protocol"]["protocol_version"],
                approved_contract["facet_map"]["framing_version"])
    if pins != declared:
        raise ValueError("confidence contract pins differ")
    confidence = record.confidence
    if isinstance(record, OpenObligation) and not isinstance(confidence, UnknownConfidence):
        raise ValueError("open obligation has no confidence assessment")
    if isinstance(confidence, UnknownConfidence):
        if confidence.basis != "unknown" or not confidence.reason.strip():
            raise ValueError("unknown confidence requires its reason")
        return confidence
    if not isinstance(confidence, RecordedConfidence) or confidence.basis != "recorded_assessment":
        raise ValueError("explicit confidence basis required")
    scheme = approved_contract.get("confidence_scheme")
    if scheme is None:
        raise ValueError("contract declares no confidence scheme")
    if (confidence.scheme.scheme_id != scheme["scheme_id"] or
            type(confidence.scheme.version) is not int or confidence.scheme.version != scheme["version"] or
            confidence.label not in scheme["labels"]):
        raise ValueError("confidence differs from contract scheme")
    return confidence
