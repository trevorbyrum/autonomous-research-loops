"""The material-operand digest: what a reviewed dossier was derived from (G-8).

A hash of the detached capture without bookkeeping that every commit writes.
Everything else the capture delivers is included, so a new scientific relation
is material unless it is named here with a reason.
"""
from dataclasses import replace

from gen2.core import canonical
from gen2.store.capture import RawTable, TopicCapture, input_hash

# Written by every commit or by the dossier route, or scheduling and staging state.
EXCLUDED = frozenset({"dossiers", "audit_events", "operation_receipts", "queue_entries", "leases", "artifacts", "artifact_topics"})
INVOCATION_COLUMNS = ("invocation_id", "kind", "state", "parent_invocation_id", "admission_context", "contract_revision")


def _narrow(table: RawTable, keep: tuple[str, ...]) -> RawTable:
    at = [table.columns.index(c) for c in keep]
    return RawTable(table.name, keep, tuple(c for c in table.json_columns if c in keep), tuple(tuple(row[i] for i in at) for row in table.rows))


def project(raw: TopicCapture) -> TopicCapture:
    tables = []
    for table in raw.tables:
        if table.name in EXCLUDED:
            continue
        if table.name == "completion_records":  # the review is bound to the dossier separately
            kind = table.columns.index("kind")
            table = replace(table, rows=tuple(r for r in table.rows if r[kind] != "sufficiency_review"))
        if table.name == "invocations":  # checkpoint lifecycle is bookkeeping
            kind = table.columns.index("kind")
            table = _narrow(replace(table, rows=tuple(r for r in table.rows if r[kind] != "checkpoint")), INVOCATION_COLUMNS)
        tables.append(table)
    return replace(raw, tables=tuple(tables))


def digest(raw: TopicCapture, history: str) -> str:
    return canonical.logical_hash({"material_version": "material-operands/1", "projection": input_hash(project(raw), history)})
