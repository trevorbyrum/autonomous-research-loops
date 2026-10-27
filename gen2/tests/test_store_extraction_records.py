"""Direct SQL 22 integrity witnesses, independent of Router test inheritance."""
import json
import sqlite3

from gen2.tests import store_fixtures as sf


class ExtractionIntegrityTest(sf.RecordIntegrityCase):
    def test_control(self):
        self.insert_record('source_extractions')
        self.assertEqual(self.rows("SELECT extractor_identity,extractor_registry_version FROM source_extractions WHERE extraction_id='raw-candidate'"), [('tool-a', 1)])
        self.assertEqual(self.rows('PRAGMA foreign_key_check'), [])

    def test_acquisition(self):
        for field, value in (('event_id','absent'), ('source_version','absent'), ('work_id','absent'), ('verifier_invocation_id','inv_pppppppp')):
            with self.subTest(field=field), self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                self.insert_record('source_extractions', **{field: value})

    def test_commit(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'extraction needs its extracting invocation commit'):
            self.insert_record('source_extractions', recorded_by_operation_id='op_extractval')

    def test_output(self):
        ref = json.loads(self.record_row('source_extractions')['output_ref'])
        for change in ({'content_hash': sf.h('0')}, {'size_bytes': 999}, {'media_type': 'text/plain'}):
            with self.subTest(change=change), self.assertRaisesRegex(sqlite3.IntegrityError, 'extraction needs topic-authorized output metadata'):
                self.insert_record('source_extractions', output_ref=json.dumps({**ref, **change}))
        with self.corrupt('artifact_topics', '1=1', topic_id=sf.OTHER):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'extraction needs topic-authorized output metadata'):
                self.insert_record('source_extractions')

    def test_registry(self):
        for change in (*({'extractor_identity': s} for s in ('unknown', 'alias-a', 'Tool-a', ' tool-a', 'tool-a ', 'tool-a\0alias')),
                {'extractor_registry_version': None}, {'extractor_registry_version': 2}):
            with self.subTest(change=change), self.assertRaisesRegex(sqlite3.IntegrityError, 'extraction needs an exact registered tool and registry revision'):
                self.insert_record('source_extractions', **change)

    def test_conflict(self):
        for tool in ('tool-a', 'tool-b'):
            with self.subTest(tool=tool), self.assertRaisesRegex(sqlite3.IntegrityError, 'UNIQUE constraint failed: source_extractions.extraction_id'):
                self.insert_record('source_extractions', extraction_id='ext-target', extractor_identity=tool)

    def test_immutable(self):
        before = self.snapshot('source_extractions')
        for sql, message in (("UPDATE source_extractions SET created_at=created_at", 'extractions are immutable'),
                ("DELETE FROM source_extractions", 'extractions are retained'),
                ("INSERT OR REPLACE INTO source_extractions SELECT * FROM source_extractions", 'extractions are retained'),
                ("UPDATE OR REPLACE source_extractions SET created_at=created_at", 'extractions are immutable'),
                ("INSERT INTO source_extractions SELECT * FROM source_extractions WHERE true ON CONFLICT DO UPDATE SET created_at=excluded.created_at", 'extractions are immutable')):
            self.rejects(message, sql)
            self.assertEqual(self.snapshot('source_extractions'), before)


class ValidationIntegrityTest(sf.RecordIntegrityCase):
    def test_controls(self):
        for identity, changes, expected in (('failed', dict(outcome='failed', comparison='disagreement'), 0),
                ('semantic', dict(comparison='semantic_agreement'), 1), ('ordinary', {}, 1)):
            self.insert_record('extraction_validations', validation_id=identity, **changes)
            self.assertEqual(self.rows('SELECT method_succeeded FROM extraction_validation_results WHERE validation_id=?', identity), [(expected,)])
            self.assertEqual(self.rows('SELECT validator_invocation_id,policy_version FROM extraction_validations WHERE validation_id=?', identity), [('inv_vvvvvvvv', 1)])
        with self.corrupt('source_extractions', "extraction_id='ext-independent'", extractor_identity='tool-a'):
            self.insert_record('extraction_validations', validation_id='replay', method='same_extractor_replay')
            self.assertEqual(self.rows("SELECT method_succeeded FROM extraction_validation_results WHERE validation_id='replay'"), [(0,)])

    def test_bindings(self):
        self.x('DROP TRIGGER extraction_validations_artifact')  # missing target cannot be masked by its artifact guard
        for field in ('target_extraction_id', 'validator_extraction_id'):
            with self.subTest(field=field), self.assertRaisesRegex(sqlite3.IntegrityError, 'validation needs independent validator and exact acquisition lineage'):
                self.insert_record('extraction_validations', **{field: 'absent'})
        for table, where, field, value in (
                *(('source_extractions', "extraction_id='ext-independent'", f, 'foreign') for f in ('topic_id','work_id','source_version','event_id','verifier_invocation_id','extracting_invocation_id')),
                ('source_extractions', "extraction_id='ext-target'", 'extracting_invocation_id', 'inv_vvvvvvvv'),
                ('source_extractions', "extraction_id IN ('ext-target','ext-independent')", 'verifier_invocation_id', 'inv_pppppppp'),
                ('source_artifacts', '1=1', 'invocation_id', 'inv_vvvvvvvv'),
                *(('invocations', "invocation_id='inv_vvvvvvvv'", f, v) for f, v in (('topic_id',sf.OTHER),('kind','checkpoint'),('admission_context','scoping/1'),('parent_invocation_id','inv_pppppppp'))),
                *(('operation_receipts', "operation_id='op_extractval'", f, v) for f, v in (('invocation_id','inv_pppppppp'),('topic_id',sf.OTHER),('contract_revision',999)))):
            with self.subTest(table=table, field=field), self.corrupt(table, where, **{field:value}):
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation needs independent validator and exact acquisition lineage'):
                    self.insert_record('extraction_validations')

    def test_method(self):
        for changes, method in (({'extractor_identity':'tool-a'}, 'independent_extraction'),
                ({'extractor_identity':'tool-a','extractor_version':'2'}, 'same_extractor_replay')):
            with self.subTest(changes=changes), self.corrupt('source_extractions', "extraction_id='ext-independent'", **changes):
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation method or byte comparison disagrees with extraction records'):
                    self.insert_record('extraction_validations', method=method)
        with self.corrupt('source_extractions', "extraction_id='ext-independent'", output_ref=json.dumps(self.other_ref)):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation method or byte comparison disagrees with extraction records'):
                self.insert_record('extraction_validations')
            self.insert_record('extraction_validations', comparison='semantic_agreement')
            self.assertEqual(self.rows("SELECT method_succeeded FROM extraction_validation_results WHERE validation_id='raw-candidate'"), [(1,)])

    def test_consistency(self):
        for changes, fragment in (({'outcome':'succeeded','comparison':'disagreement'}, "outcome = 'succeeded'"),
                ({'method':'invented'}, 'method IN'), ({'policy_version':2}, 'policy_version = 1')):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, fragment):
                self.insert_record('extraction_validations', **changes)

    def test_evidence(self):
        ref = json.loads(self.record_row('extraction_validations')['comparison_evidence_ref'])
        for changes in ({'content_hash':sf.h('0')}, {'size_bytes':999}, {'media_type':'text/plain'}):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, 'validation needs topic-authorized comparison evidence'):
                self.insert_record('extraction_validations', comparison_evidence_ref=json.dumps({**ref, **changes}))
        with self.corrupt('artifact_topics', '1=1', topic_id=sf.OTHER):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation needs topic-authorized comparison evidence'):
                self.insert_record('extraction_validations')

    def test_immutable(self):
        before = self.snapshot('extraction_validations')
        for sql, message in (("UPDATE extraction_validations SET created_at=created_at", 'validations are immutable'),
                ("DELETE FROM extraction_validations", 'validations are retained'),
                ("INSERT OR REPLACE INTO extraction_validations SELECT * FROM extraction_validations", 'validations are retained'),
                ("UPDATE OR REPLACE extraction_validations SET created_at=created_at", 'validations are immutable'),
                ("INSERT INTO extraction_validations SELECT * FROM extraction_validations WHERE true ON CONFLICT DO UPDATE SET created_at=excluded.created_at", 'validations are immutable')):
            self.rejects(message, sql)
            self.assertEqual(self.snapshot('extraction_validations'), before)
