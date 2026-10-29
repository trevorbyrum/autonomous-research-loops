"""Direct SQL 35 claim/source, attribution and artifact integrity witnesses."""
import json
import sqlite3

from gen2.tests import store_fixtures as sf

KINDS = ('numeric_units', 'denominators', 'negation', 'qualifications')


class DetailedIntegrityTest(sf.RecordIntegrityCase):
    def test_control(self):
        self.insert_record('detailed_check_records')
        self.assertEqual(self.rows("SELECT performer_invocation_id,recorded_by_operation_id FROM detailed_check_records WHERE check_id='raw-candidate'"), [('inv_vvvvvvvv', 'op_extractval')])
        self.assertEqual(self.rows('PRAGMA foreign_key_check'), [])

    def test_bindings(self):
        report = json.loads(self.record_row('detailed_check_records')['assessment'])
        for kind in KINDS:
            for changes in ({'claim_id':'absent'}, {'claim_revision':2}, {'work_id':'absent'},
                    {'source_version':'foreign'}, {'source_artifact_hash':sf.h('0')}):
                with self.subTest(kind=kind,changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, 'detailed check needs exact claim/source and independent committing verifier'):
                    self.insert_record('detailed_check_records', assessment=json.dumps({**report,'kind':kind,**changes}))

    def test_attribution(self):
        report = json.loads(self.record_row('detailed_check_records')['assessment'])
        for table, where, field, value in (
                *(('invocations', "invocation_id='inv_vvvvvvvv'", f, v) for f, v in (('topic_id',sf.OTHER),('kind','checkpoint'),('admission_context','scoping/1'),('parent_invocation_id','inv_pppppppp'))),
                ('source_artifacts','1=1','invocation_id','inv_vvvvvvvv'), ('claims','1=1','producer_invocation_id','inv_vvvvvvvv'),
                *(('operation_receipts', "operation_id='op_extractval'", f, v) for f, v in (('invocation_id','inv_pppppppp'),('topic_id',sf.OTHER),('contract_revision',999)))):
            with self.subTest(table=table,field=field), self.corrupt(table, where, **{field:value}):
                for kind in KINDS:
                    with self.assertRaisesRegex(sqlite3.IntegrityError, 'detailed check needs exact claim/source and independent committing verifier'):
                        self.insert_record('detailed_check_records', assessment=json.dumps({**report,'kind':kind}))

    def test_artifacts(self):
        report = json.loads(self.record_row('detailed_check_records')['assessment'])
        ref = report['examined_artifact_ref']
        for kind in KINDS:
            try:
                self.insert_record('detailed_check_records', check_id='ok-'+kind, assessment=json.dumps({**report,'kind':kind}), evidence_ref=json.dumps(ref))
            except sqlite3.IntegrityError as refusal:
                self.fail(f'{kind}: valid evidence_ref refused: {refusal}')
            self.assertEqual(self.rows('SELECT evidence_ref FROM detailed_check_records WHERE check_id=?', 'ok-'+kind), [(json.dumps(ref),)])
            for field in ('examined_artifact_ref','evidence_ref'):
                for change in ({'size_bytes':999}, {'media_type':'text/plain'}, {'content_hash':sf.h('0')}):
                    changes = {'assessment':json.dumps({**report,'kind':kind,field:{**ref,**change}})} if field=='examined_artifact_ref' else {'evidence_ref':json.dumps({**ref,**change})}
                    with self.subTest(kind=kind,field=field,change=change), self.assertRaisesRegex(sqlite3.IntegrityError, 'detailed check needs topic-authorized artifact metadata'):
                        self.insert_record('detailed_check_records', **changes)
        with self.corrupt('artifact_topics', '1=1', topic_id=sf.OTHER):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'detailed check needs topic-authorized artifact metadata'):
                self.insert_record('detailed_check_records')

    def test_immutable(self):
        before = self.snapshot('detailed_check_records')
        for sql, message in (("UPDATE detailed_check_records SET created_at=created_at", 'detailed checks are immutable'),
                ("DELETE FROM detailed_check_records", 'detailed checks are retained'),
                ("INSERT OR REPLACE INTO detailed_check_records SELECT * FROM detailed_check_records", 'detailed checks are retained'),
                ("INSERT INTO detailed_check_records SELECT * FROM detailed_check_records WHERE true ON CONFLICT DO UPDATE SET created_at=excluded.created_at", 'detailed checks are immutable')):
            self.rejects(message, sql)
            self.assertEqual(self.snapshot('detailed_check_records'), before)
