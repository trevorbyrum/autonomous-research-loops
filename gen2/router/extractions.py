"""Durable attributed extraction records; DOSSIER 2d-4b3e1, V-3, C-9.

Authentication runs outside the core writer lock; writes use its fenced commit.
SQL 22/29 check recorded relationships, never semantic correctness or execution.
"""
from typing import Callable, Mapping, Protocol

from gen2.router import boundary, support
from gen2.router.boundary import Refusal


class Rows(Protocol):
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...


class ExtractionCore(Protocol):
    _store: Rows
    _spool: object
    def _require_extractor_tool(self, record: dict) -> None: ...


class ExtractionRecords:
    def __init__(self, core: ExtractionCore) -> None:
        self._core = core

    def authenticate(self, payload: dict, inv: dict, bind: Callable[[dict, str], None]) -> None:
        extractions = payload.get("source_extractions", [])
        validations = payload.get("extraction_validations", []) + payload.get("extraction_validations_v2", [])
        for record in extractions:
            self._core._require_extractor_tool(record)
        for records, field in ((extractions, "output_ref"), (validations, "comparison_evidence_ref")):
            for record in records:
                ref = record[field]
                bind(ref, field)
                boundary.staged(self._core._spool, ref["content_hash"], ref["size_bytes"],
                    topic_id=inv["topic_id"], media_type=ref["media_type"])

    def write(self, payload: dict, inv: dict, operation_id: str, now: str) -> dict:
        written = {}
        for table, identity, attribution in (("source_extractions", "extraction_id", "extracting_invocation_id"),
                ("extraction_validations", "validation_id", "validator_invocation_id"),
                ("extraction_validations_v2", "validation_id", "validator_invocation_id")):
            records = payload.get(table, [])
            for record in records:
                if table == "extraction_validations_v2":
                    self._require_current_registry(record)
                row = {**record, attribution: inv["invocation_id"], "recorded_by_operation_id": operation_id, "created_at": now}
                if table == "source_extractions":
                    row["topic_id"] = inv["topic_id"]
                    acquired = self._core._store.select("source_acquisitions", {key: row[key] for key in
                        ("topic_id", "work_id", "source_version", "event_id", "verifier_invocation_id")})
                    if not acquired or boundary.TIER[row["supported_tier"]] > support.content_rank(self._core._store, next(iter(acquired))):
                        raise Refusal("payload_invalid", "extraction tier exceeds recorded content")
                self._core._store.insert(table, row)
            if records:
                written[table] = [r[identity] for r in records]
        return written

    def _require_current_registry(self, record: dict) -> None:
        # Inside the writer fence, after same-outcome extractions. Retained
        # operation replay returns before this new-admission check.
        validators = self._core._store.select("source_extractions", {"extraction_id": record["validator_extraction_id"]})
        pin = next((r["extractor_registry_version"] for r in validators), None)
        current = max((r["registry_version"] for r in self._core._store.select("extractor_registry_revisions")), default=0)
        if pin != current:
            raise Refusal("payload_invalid", "validation /2 needs the current extractor registry revision")
