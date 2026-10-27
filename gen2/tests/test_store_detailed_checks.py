"""Raw SQL 35 integrity bindings and conflict immutability."""
import json
import sqlite3


from gen2.tests import store_fixtures as fx

from gen2.tests.test_detailed_checks import CheckCase, KINDS, RecordMatrix


class DDLCheckTest(RecordMatrix, CheckCase):
    RAW = True
    test_domain = test_missing_evidence = test_spans = None

    def setUp(self):
        # Install raw target objects over admitted fixture operands.
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(fx.DDL_TEXT)
            objects = reference.execute("SELECT sql FROM sqlite_schema WHERE tbl_name='detailed_check_records' AND sql IS NOT NULL ORDER BY rowid").fetchall()
        CheckCase.setUp(self)
        self.x('DROP TABLE detailed_check_records')
        for sql, in objects:
            self.x(sql)

    def send(self, record, grant=None, op='op_detailcheck1'):
        self.x('SAVEPOINT detailed_record')
        try:
            ref = record['evidence_ref']
            if ref and isinstance(ref, dict) and not self.rows('SELECT 1 FROM artifacts WHERE content_hash=?', ref['content_hash']):
                raw = self.spool.read(ref['content_hash'], topic_id=self.verifier['topic_id'])
                self.x('INSERT INTO artifacts (content_hash,size_bytes,media_type,staged_at) VALUES (?,?,?,?)', ref['content_hash'], len(raw), 'application/json', '2026-10-17T00:00:00Z')
                self.x('INSERT INTO artifact_topics VALUES (?,?,?,?)', ref['content_hash'], self.verifier['topic_id'], self.producer['invocation_id'], '2026-10-17T00:00:00Z')
            row = dict(check_id=record['check_id'], topic_id=self.verifier['topic_id'],
                performer_invocation_id=(grant or self.verifier)['invocation_id'], assessment=record['assessment'], evidence_ref=ref,
                recorded_by_operation_id='op_setupcheck1', created_at='2026-10-17T00:00:00Z')
            self.x(f"INSERT INTO detailed_check_records ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                *[json.dumps(v) if isinstance(v, dict) else v for v in row.values()])
            return {'status': 'committed'}
        except sqlite3.IntegrityError:
            self.x('ROLLBACK TO detailed_record')
            return {'status': 'rejected'}
        finally:
            self.x('RELEASE detailed_record')


    def test_immutable(self):
        self.test_control()
        for statement in ('UPDATE detailed_check_records SET created_at=created_at', 'DELETE FROM detailed_check_records',
                'INSERT OR REPLACE INTO detailed_check_records SELECT * FROM detailed_check_records',
                'INSERT INTO detailed_check_records SELECT * FROM detailed_check_records WHERE true ON CONFLICT DO UPDATE SET created_at=excluded.created_at'):
            before = self.state(exclude=())
            with self.assertRaises(sqlite3.IntegrityError):
                self.x(statement)
            self.assertEqual(self.state(exclude=()), before)

    def test_attribution(self):
        self.x('PRAGMA foreign_keys=OFF')
        for table, field, value in (('invocations', 'kind', 'checkpoint'), ('invocations', 'topic_id', 'foreign'),
                ('invocations', 'admission_context', 'scoping/1'), ('invocations', 'parent_invocation_id', self.producer['invocation_id']),
                ('source_artifacts', 'invocation_id', self.verifier['invocation_id']),
                ('operation_receipts', 'invocation_id', self.producer['invocation_id']), ('operation_receipts', 'topic_id', 'foreign'),
                ('operation_receipts', 'contract_revision', 999)):
            self.x('SAVEPOINT corrupt_operand')
            for name, in self.rows("SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name=?", table):
                self.x('DROP TRIGGER ' + name)
            key = " WHERE invocation_id='inv_verify0001'" if table == 'invocations' else " WHERE operation_id='op_setupcheck1'" if table == 'operation_receipts' else ''
            self.x('PRAGMA ignore_check_constraints=ON')
            self.x(f'UPDATE {table} SET {field}=?' + key, value)
            self.x('PRAGMA ignore_check_constraints=OFF')
            for kind in KINDS:
                self.refuse(self.record(kind=kind))
            self.x('ROLLBACK TO corrupt_operand')
            self.x('RELEASE corrupt_operand')
