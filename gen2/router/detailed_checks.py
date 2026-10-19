"""Attributed V-8 assessment admission; operator ruling 2026-10-17.

C-9 byte authentication precedes the writer lock. SQL 35 binds relationships;
optional receipt references bind exactly; promotion policy remains unchanged.
"""
from typing import Callable

from gen2.core import canonical
from gen2.router import boundary
from gen2.router.boundary import Refusal
from gen2.router.extractions import ExtractionCore


class DetailedChecks:
    def __init__(self, core: ExtractionCore) -> None:
        self._core = core

    def authenticate(self, payload: dict, inv: dict, bind: Callable[[dict, str], None]) -> None:
        records = payload.get("detailed_check_records", [])
        if records and (inv["admission_context"] != "contract/1" or inv["kind"] != "verification"
                or inv["parent_invocation_id"] is not None):
            raise Refusal("kind_not_permitted", "detailed checks require independent contract verification")
        for record in records:
            report = record["assessment"]
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
            self.require_receipt(doc)
        return {"detailed_check_records": [r["check_id"] for r in records]} if records else {}

    def require_receipt(self, doc: dict) -> None:
        """Part 2: explicit summary projection; any supplied reference must bind."""
        projection = {"succeeded": "checked_ok", "failed": "checked_problem",
            "not_applicable": "not_applicable", "not_checked": "not_checked", "unavailable": "unavailable"}
        for kind, entry in doc.get("detailed_checks", {}).items():
            if projection[entry["outcome"]] != doc["checks"][kind]:
                raise Refusal("payload_invalid", "detailed receipt summary projection mismatch")
            if "record_id" not in entry:
                continue
            rows = self._core._store.select("detailed_check_records", {"check_id": entry["record_id"]})
            sources = self._core._store.select("source_artifacts", {"topic_id": doc["topic_id"], **doc["source"]})
            if not rows or not sources:
                raise Refusal("payload_invalid", "receipt detailed check binding")
            row, report = rows[0], rows[0]["assessment"]
            artifact_hash = doc["obtained_content_hash"]
            if doc["extraction"]["method"] != "canonical_bytes":
                extraction_id = doc["extraction"].get("extraction_id")
                if doc["extraction"]["method"] == "validated_extraction":
                    validations = self._core._store.select("extraction_validations_v2", {"validation_id": doc["extraction"]["validation_ref"]})
                    extraction_id = validations[0]["target_extraction_id"] if validations else None
                extractions = self._core._store.select("source_extractions", {"extraction_id": extraction_id})
                artifact_hash = extractions[0]["output_ref"]["content_hash"] if extractions else None
            expected = {**doc["claim"], **doc["source"], "kind": kind, "outcome": entry["outcome"],
                "cited_spans": doc["cited_spans"], "source_artifact_hash": sources[0]["content_hash"]}
            if (row["topic_id"] != doc["topic_id"] or row["performer_invocation_id"] != doc["verifier_invocation_id"]
                    or any(report[k] != v for k, v in expected.items())
                    or report["examined_artifact_ref"]["content_hash"] != artifact_hash):
                raise Refusal("payload_invalid", "receipt detailed check binding")
