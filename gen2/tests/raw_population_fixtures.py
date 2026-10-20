"""Authenticate raw population assessments without replacing subject constraints."""
import copy
import sqlite3

from gen2.core import canonical
from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests.ddl_fixtures import TRIGGERS, restore_triggers
from gen2.tests.detailed_receipt_fixtures import seed_checks, attach_checks, assessment_binding
from gen2.tests.raw_detailed_receipt_fixtures import RawAssessmentFixture

SOURCE_BYTES = b'{"records":[{"identity":"rec-1","kind":"full_text","text":"Fixture text"}]}'.ljust(512)
SOURCE_HASH = canonical.bytes_digest(SOURCE_BYTES)
SPANS = [dict(start=0, end=5, locator=dict(kind='page', value='3'))]


def snapshot(conn):
    return {name: list(conn.execute('SELECT rowid,* FROM ' + name)) for name, in
        conn.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def prepare(case, claim=('clm_00000001', 1), *, spans=SPANS, verifier='inv_vvvvvvvv'):
    """Router admission on a full-DDL mirror; retain its exact rows in the owner.

    CHECK/connection mutants must still govern the original subject connection.
    Only copying previously admitted fixture state bypasses guards; submission
    never calls this function. All connections here are disposable in-memory.
    """
    case.assertFalse(case.db.in_transaction, 'prepare assessments before subject savepoints')
    before = snapshot(case.db)
    requested = case.rows(TRIGGERS)
    contract = case.rows('PRAGMA foreign_keys')[0][0], case.rows('PRAGMA ignore_check_constraints')[0][0]
    mirror = sf.StoreTestCase()
    mirror.db = sqlite3.connect(':memory:', isolation_level=None)
    try:
        mirror.db.executescript((sf.STORE_DIR / "connection.sql").read_text() + db.schema_text())
        full = mirror.rows(TRIGGERS)
        for name, _ in full:
            mirror.x('DROP TRIGGER '+name)
        mirror.x('PRAGMA foreign_keys=OFF')
        mirror.x('PRAGMA ignore_check_constraints=ON')
        for table, rows in before.items():
            for row in rows:
                columns = [r[1] for r in mirror.rows(f'PRAGMA table_info({table})')]
                mirror.x(f"INSERT INTO {table} (rowid,{','.join(columns)}) VALUES ({','.join('?' for _ in row)})", *row)
        mirror.x("UPDATE queue_entries SET state_revision=coalesce((SELECT MAX(state_revision_after) FROM operation_receipts r WHERE r.topic_id=queue_entries.topic_id),state_revision)")
        mirror.x('PRAGMA ignore_check_constraints=OFF')
        mirror.x('PRAGMA foreign_keys=ON')
        for _, sql in full:
            mirror.x(sql)
        bridge = RawAssessmentFixture(mirror, SOURCE_BYTES, verifier=verifier)
        bridge.ids.n = getattr(case, '_assessment_ids', 0)
        doc = dict(topic_id=sf.TOPIC, claim=dict(claim_id=claim[0], claim_revision=claim[1]),
            source=dict(work_id='wrk_00000001', source_version='v1'), cited_spans=copy.deepcopy(spans),
            obtained_content_hash=SOURCE_HASH, extraction=dict(method='canonical_bytes'),
            verifier_invocation_id=verifier, checks=case.CHECKS_OK)
        binding = assessment_binding(bridge, doc)
        records = bridge.store.select("detailed_check_records", {"performer_invocation_id": verifier})
        if len([r for r in records if all(r["assessment"][k] == v for k, v in binding.items())]) != 12:
            seed_checks(bridge, doc)
        after = snapshot(mirror.db)
        # Copy exact admitted rows, keeping every requested table/view definition.
        for name, _ in requested:
            case.x('DROP TRIGGER '+name)
        case.x('PRAGMA foreign_keys=OFF')
        case.x('PRAGMA ignore_check_constraints=ON')
        try:
            for table, rows in after.items():
                old = {r[0]: r for r in before[table]}
                columns = [r[1] for r in case.rows(f'PRAGMA table_info({table})')]
                for row in rows:
                    if row[0] not in old:
                        case.x(f"INSERT INTO {table} (rowid,{','.join(columns)}) VALUES ({','.join('?' for _ in row)})", *row)
                    elif old[row[0]] != row:
                        case.x(f"UPDATE {table} SET {','.join(c+'=?' for c in columns)} WHERE rowid=?", *row[1:], row[0])
        finally:
            case.x('PRAGMA ignore_check_constraints=' + str(contract[1]))
            case.x('PRAGMA foreign_keys=' + str(contract[0]))
            catalog = db.schema_text() + '\n' + '\n'.join('DROP TRIGGER "'+n+'";' for n, _ in full)
            restore_triggers(case, catalog + '\n' + '\n'.join(sql+';' for _, sql in requested))
        case._assessment_ids = bridge.ids.n
        if hasattr(case, 'population_assessments'):
            bridge.spool.blobs.update(case.population_assessments.spool.blobs)
            bridge.spool.media.update(case.population_assessments.spool.media)
        bridge.db = case.db
        bridge.store._conn = case.db  # readback/attachment only; no Router commit on the subject
        bridge.spool.conn = case.db
        case.population_assessments = bridge
    finally:
        mirror.db.close()


def attach(case, doc):
    attach_checks(case.population_assessments, doc)
