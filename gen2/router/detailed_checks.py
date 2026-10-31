"""Attributed V-8 assessment admission; operator ruling 2026-10-17.

C-9 byte authentication precedes the writer lock. SQL 35 binds relationships;
receipt references bind exactly; load-bearing support must consume records.
"""
from typing import Callable, Protocol

from gen2.core import canonical
from gen2.router import boundary, support
from gen2.router.boundary import Refusal
from gen2.router.protocols import Rows, Spool


class DetailedChecksCore(Protocol):
    _store: Rows[object]
    _spool: Spool


class DetailedChecks:
    def __init__(self, core: DetailedChecksCore) -> None:
        self._core = core

    def require_support(self, claim: dict, capture_valid: Callable[[dict], bool]) -> None:
        support.require_support(self._core._store, claim, capture_valid)

    def _content_rank(self, acquired: dict) -> int:
        return support.content_rank(self._core._store, acquired)

    def authenticate(self, payload: dict, inv: dict, bind: Callable[[dict, str], None]) -> None:
        records = payload.get("detailed_check_records", [])
        for record in records:
            report = record["assessment"]
            if report["outcome"] in ("succeeded", "failed", "not_applicable") and not all(
                    support.nonblank(report[field]) for field in ("assessment", "context_examined")):
                raise Refusal("payload_invalid", "performed detailed check needs nonblank assessment and context")
            if report["outcome"] in ("not_applicable",) and not support.nonblank(report["applicability_reason"]):
                raise Refusal("payload_invalid", "detailed check exemption needs nonblank applicability reason")
            boundary.check_span_offsets(report["cited_spans"] + report["context_spans"])
            for ref in (report["examined_artifact_ref"], record["evidence_ref"]):
                if ref is None:
                    continue
                bind(ref, "detailed check artifact")
                raw = boundary.staged(self._core._spool, ref["content_hash"], ref["size_bytes"],
                    topic_id=inv["topic_id"], media_type=ref["media_type"])
                if ref is record["evidence_ref"]:
                    evidence = boundary.normalize(raw, "payload_invalid", member_domain=True)
                    if canonical.canonical_bytes(evidence) != canonical.canonical_bytes(report):
                        raise Refusal("payload_invalid", "detailed check evidence must retain the exact assessment report")

    def write(self, payload: dict, inv: dict, operation_id: str, now: str) -> dict:
        records = payload.get("detailed_check_records", [])
        for record in records:
            report = record["assessment"]
            claims = self._core._store.select("claims", {"claim_id": report["claim_id"], "revision": report["claim_revision"]})
            sources = self._core._store.select("source_artifacts", {"topic_id": inv["topic_id"],
                "work_id": report["work_id"], "source_version": report["source_version"]})
            if not claims or not sources or claims[0]["topic_id"] != inv["topic_id"]:
                raise Refusal("payload_invalid", "detailed check needs exact claim/source topic")
            if (claims[0]["producer_invocation_id"] == inv["invocation_id"]
                    or sources[0]["invocation_id"] == inv["invocation_id"]
                    or sources[0]["content_hash"] != report["source_artifact_hash"]):
                raise Refusal("payload_invalid", "detailed check needs independent verifier and exact source hash")
            self._core._store.insert("detailed_check_records", {**record, "topic_id": inv["topic_id"],
                "performer_invocation_id": inv["invocation_id"], "recorded_by_operation_id": operation_id, "created_at": now})
        for doc in payload["verification_receipts"]:
            support.require_receipt(self._core._store, doc)
        return {"detailed_check_records": [r["check_id"] for r in records]} if records else {}
