"""Attributed V-8 assessment admission; operator ruling 2026-10-17.

C-9 byte authentication precedes the writer lock. SQL 35 binds relationships;
these records grant no receipt or promotion authority in part 1.
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
        return {"detailed_check_records": [r["check_id"] for r in records]} if records else {}
