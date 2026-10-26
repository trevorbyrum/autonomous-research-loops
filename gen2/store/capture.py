"""Fixed dossier-input reads; Store owns the read transaction (2d-6a D1).

Raw SQLite scalars remain immutable and JSON remains text. No parsing, byte
hashing, arithmetic, spool I/O or write occurs during capture. No query API.
"""
from dataclasses import dataclass

from gen2.core import canonical

TOPIC_TABLES = """queue_entries contract_revisions facets obligations invocations
leases search_observations retrieval_events screening_assessments claims
semantic_assessments source_lifecycle registry_dispositions branch_windows
obligation_assessments amendment_impacts claim_source_links verification_receipts
source_artifacts source_acquisitions source_extractions detailed_check_records
holds operator_decisions artifact_topics dossiers operation_receipts""".split()

PINS = "SELECT extractor_registry_version FROM source_extractions WHERE topic_id=:topic"
SHARED = {
    "record_work_links": "r.event_id IN (SELECT event_id FROM retrieval_events WHERE topic_id=:topic)",
    "works": "r.work_id IN (SELECT l.work_id FROM record_work_links l JOIN retrieval_events e USING(event_id) WHERE e.topic_id=:topic)",
    "source_lineage": "r.assessment_id IN (SELECT assessment_id FROM semantic_assessments WHERE topic_id=:topic)",
    "quote_checks": "(r.claim_id,r.claim_revision) IN (SELECT claim_id,revision FROM claims WHERE topic_id=:topic)",
    "extraction_validations": "r.target_extraction_id IN (SELECT extraction_id FROM source_extractions WHERE topic_id=:topic)",
    "extraction_validations_v2": "r.target_extraction_id IN (SELECT extraction_id FROM source_extractions WHERE topic_id=:topic)",
    "artifacts": "r.content_hash IN (SELECT content_hash FROM artifact_topics WHERE topic_id=:topic)",
    "extractor_registry_revisions": "r.registry_version IN (" + PINS + ")",
    "extractor_tools": "r.registry_version IN (" + PINS + ")",
    "audit_events": "r.topic_id=:topic OR r.audit_event_id IN (SELECT audit_event_id FROM extractor_registry_revisions WHERE registry_version IN (" + PINS + "))",
}


@dataclass(frozen=True)
class RawTable:
    name: str
    columns: tuple[str, ...]
    json_columns: tuple[str, ...]
    rows: tuple[tuple, ...]


@dataclass(frozen=True)
class Freshness:
    generation: tuple[str | None, int, int]  # pragma: no mutate - type annotation only
    file: tuple | None  # pragma: no mutate - type annotation only


@dataclass(frozen=True)
class TopicCapture:
    topic_id: str
    tables: tuple[RawTable, ...]
    freshness: Freshness | None = None  # pragma: no mutate - annotation; Store binds every admitted capture


def read(conn, json_columns: dict, topic_id: str) -> TopicCapture:
    """Called only by Store.capture_topic within its checked read snapshot."""
    tables = []
    selections = [(name, "r.topic_id=:topic") for name in TOPIC_TABLES]
    for name, predicate in (*selections, *SHARED.items()):
        cursor = conn.execute(f"SELECT r.* FROM {name} r WHERE {predicate} ORDER BY r.rowid", {"topic": topic_id})
        tables.append(RawTable(name, tuple(c[0] for c in cursor.description),
                               tuple(sorted(json_columns[name])), tuple(cursor.fetchall())))
    return TopicCapture(topic_id, tuple(tables))


def input_hash(snapshot: TopicCapture, history: str) -> str:
    """Pure, outside-transaction manifest hash; raw preimage stays in snapshot.

    Per-row digests keep serialization memory bounded. BLOBs are tagged byte
    digests, never decoded or confused with text. Empty groups and order bind.
    """
    if history not in ("native", "legacy_unknown"):
        raise ValueError("history must be native or legacy_unknown")
    tables = [{"name": table.name, "columns": table.columns, "json_columns": table.json_columns,
               "rows": [canonical.logical_hash([
                   {"blob_sha256": canonical.bytes_digest(cell)} if isinstance(cell, bytes) else cell
                   for cell in row]) for row in table.rows]} for table in snapshot.tables]
    return canonical.logical_hash({"snapshot_version": "dossier-input/1", "topic_id": snapshot.topic_id,
                                   "history": history, "tables": tables})
