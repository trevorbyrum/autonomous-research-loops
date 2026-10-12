"""Durable attributed extraction records; DOSSIER 2d-4b3e1, V-3, C-9.

Authentication runs outside the core writer lock; writes use its fenced commit.
SQL 22 checks recorded relationships, never semantic correctness or execution.
"""
from typing import Callable, Mapping, Protocol

from gen2.router import boundary
from gen2.router.boundary import Refusal


class Rows(Protocol):
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...


class ExtractionCore(Protocol):
    _store: Rows
    _spool: object


class ExtractionRecords:
    def __init__(self, core: ExtractionCore) -> None:
        self._core = core

    def authenticate(self, payload: dict, inv: dict, bind: Callable[[dict, str], None]) -> None:
        extractions = payload.get("source_extractions", [])
        validations = payload.get("extraction_validations", [])
        if (extractions or validations) and inv["admission_context"] != "contract/1":
            raise Refusal("kind_not_permitted", "extraction records require contract-admitted work")
        if validations and (inv["kind"] != "verification" or inv["parent_invocation_id"] is not None):
            raise Refusal("kind_not_permitted", "validation requires independent verification")
        for records, field in ((extractions, "output_ref"), (validations, "comparison_evidence_ref")):
            for record in records:
                ref = record[field]
                bind(ref, field)
                boundary.staged(self._core._spool, ref["content_hash"], ref["size_bytes"],
                    topic_id=inv["topic_id"], media_type=ref["media_type"])

    def write(self, payload: dict, inv: dict, operation_id: str, now: str) -> dict:
        written = {}
        for table, identity, attribution in (("source_extractions", "extraction_id", "extracting_invocation_id"),
                ("extraction_validations", "validation_id", "validator_invocation_id")):
            records = payload.get(table, [])
            for record in records:
                row = {**record, attribution: inv["invocation_id"], "recorded_by_operation_id": operation_id, "created_at": now}
                if table == "source_extractions":
                    row["topic_id"] = inv["topic_id"]
                self._core._store.insert(table, row)
            if records:
                written[table] = [r[identity] for r in records]
        return written
