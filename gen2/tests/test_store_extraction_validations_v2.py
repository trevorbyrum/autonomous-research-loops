"""Direct SQL 29/31 binding, registry and retained-comparison witnesses."""
import json
import sqlite3

from gen2.tests import store_fixtures as sf


class ValidationV2IntegrityTest(sf.RecordIntegrityCase):
    def test_controls(self):
        for identity, changes, expected in (('failed', dict(outcome='failed', comparison='disagreement'), 0),
                ('semantic', dict(comparison='semantic_agreement'), 1), ('ordinary', {}, 1)):
            self.insert_record('extraction_validations_v2', validation_id=identity, **changes)
            self.assertEqual(self.rows('SELECT method_succeeded FROM extraction_validation_results_v2 WHERE validation_id=?', identity), [(expected,)])
            self.assertEqual(self.rows('SELECT validator_invocation_id,policy_version FROM extraction_validations_v2 WHERE validation_id=?', identity), [('inv_vvvvvvvv', 2)])
        with self.corrupt('source_extractions', "extraction_id='ext-independent'", extractor_identity='tool-a', extractor_version='2'):
            self.insert_record('extraction_validations_v2', validation_id='replay', method='same_family_replay')
            self.assertEqual(self.rows("SELECT method_succeeded FROM extraction_validation_results_v2 WHERE validation_id='replay'"), [(0,)])

    def test_registered(self):
        for guard in ('comparison_registry', 'current_registry', 'artifact', 'binding'):
            self.x('DROP TRIGGER extraction_validations_v2_' + guard)  # isolate historical membership
        for identity in ('ext-target', 'ext-independent'):
            with self.subTest(identity=identity), self.corrupt('source_extractions', f"extraction_id='{identity}'", extractor_registry_version=None):
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation /2 needs both pinned registered tools'):
                    self.insert_record('extraction_validations_v2')
        for field in ('target_extraction_id', 'validator_extraction_id'):
            with self.subTest(field=field), self.assertRaisesRegex(sqlite3.IntegrityError, 'validation /2 needs both pinned registered tools'):
                self.insert_record('extraction_validations_v2', **{field:'absent'})

    def test_comparison_registry(self):
        self.registry(2, [('tool-b','family-b')])
        with self.corrupt('source_extractions', "extraction_id='ext-independent'", extractor_registry_version=2):
            for method in ('independent_extraction', 'same_family_replay'):
                with self.subTest(method=method), self.assertRaisesRegex(sqlite3.IntegrityError, 'validation /2 needs both tools in the comparison registry'):
                    self.insert_record('extraction_validations_v2', method=method)

    def test_method(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation method or byte comparison disagrees with extraction records'):
            self.insert_record('extraction_validations_v2', method='same_family_replay')
        with self.corrupt('source_extractions', "extraction_id='ext-independent'", output_ref=json.dumps(self.other_ref)):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation method or byte comparison disagrees with extraction records'):
                self.insert_record('extraction_validations_v2')
            self.insert_record('extraction_validations_v2', comparison='semantic_agreement')
            self.assertEqual(self.rows("SELECT method_succeeded FROM extraction_validation_results_v2 WHERE validation_id='raw-candidate'"), [(1,)])

    def test_registry_controls(self):
        self.registry(2, [('tool-a','family-a'),('tool-b','family-b'),('tool-c','family-a')])
        self.registry(3, [('tool-a','family-c'),('tool-b','family-b'),('tool-c','family-c')])
        for target_pin, identity, independent in ((2,'tool-c',True), (1,'tool-a',True), (1,'tool-b',False)):
            with self.subTest(target_pin=target_pin,identity=identity), self.corrupt('source_extractions', "extraction_id='ext-target'", extractor_registry_version=target_pin):
                with self.corrupt('source_extractions', "extraction_id='ext-independent'", extractor_registry_version=3, extractor_identity=identity):
                    if independent:
                        with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation method or byte comparison disagrees with extraction records'):
                            self.insert_record('extraction_validations_v2')
                        self.insert_record('extraction_validations_v2', method='same_family_replay')
                        self.assertEqual(self.rows("SELECT method_succeeded FROM extraction_validation_results_v2 WHERE validation_id='raw-candidate'"), [(0,)])
                    else:
                        self.insert_record('extraction_validations_v2')
                        self.assertEqual(self.rows("SELECT method_succeeded FROM extraction_validation_results_v2 WHERE validation_id='raw-candidate'"), [(1,)])
        self.registry(7, [('tool-a','family-a'),('tool-b','family-a'),('tool-c','family-c')])
        for identity, method, expected in (('tool-b','same_family_replay',0), ('tool-c','independent_extraction',1)):
            with self.subTest(identity=identity), self.corrupt('source_extractions', "extraction_id='ext-independent'", extractor_registry_version=7, extractor_identity=identity):
                if identity=='tool-b':
                    with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation method or byte comparison disagrees with extraction records'):
                        self.insert_record('extraction_validations_v2')
                self.insert_record('extraction_validations_v2', method=method)
                self.assertEqual(self.rows("SELECT method_succeeded FROM extraction_validation_results_v2 WHERE validation_id='raw-candidate'"), [(expected,)])
                self.assertEqual(self.rows("SELECT extractor_registry_version FROM source_extractions WHERE extraction_id='ext-target'"), [(1,)])

    def test_current_registry(self):
        before = self.snapshot('extraction_validations_v2')
        self.registry(7, [('tool-a','family-a'),('tool-b','family-a'),('tool-c','family-c')])
        self.insert_record('source_extractions', extraction_id='unrelated', extractor_identity='tool-c', extractor_registry_version=7)
        for change in ({}, {'outcome':'failed','comparison':'disagreement'}, {'method':'same_family_replay'}):
            with self.subTest(change=change), self.assertRaisesRegex(sqlite3.IntegrityError, 'validation /2 needs the current extractor registry revision'):
                self.insert_record('extraction_validations_v2', **change)
        with self.corrupt('source_extractions', "extraction_id='ext-target'", extractor_registry_version=7):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation /2 needs the current extractor registry revision'):
                self.insert_record('extraction_validations_v2')
        self.assertEqual(self.snapshot('extraction_validations_v2'), before)
        self.assertEqual(self.rows("SELECT method_succeeded FROM extraction_validation_results_v2 WHERE validation_id='val-fixture'"), [(1,)])

    def test_consistency(self):
        for changes, fragment in (({'method':'same_extractor_replay'}, 'method IN'), ({'method':'invented'}, 'method IN'),
                ({'policy_version':1}, 'policy_version = 2'), ({'outcome':'invented','comparison':'disagreement'}, 'outcome IN'),
                ({'comparison':'invented','outcome':'failed'}, 'comparison IN'),
                ({'outcome':'succeeded','comparison':'disagreement'}, "outcome = 'succeeded'")):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, fragment):
                self.insert_record('extraction_validations_v2', **changes)

        with self.corrupt('source_extractions', "extraction_id='ext-independent'", extractor_identity='tool-a'):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "method <> 'same_family_replay'"):
                self.insert_record('extraction_validations_v2', method='same_family_replay', comparison='semantic_agreement')

    def test_evidence(self):
        ref = json.loads(self.record_row('extraction_validations_v2')['comparison_evidence_ref'])
        for changes in ({'content_hash':sf.h('0')}, {'content_hash':sf.h('6')}, {'size_bytes':999}, {'media_type':'text/plain'}):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, 'validation needs topic-authorized comparison evidence'):
                self.insert_record('extraction_validations_v2', comparison_evidence_ref=json.dumps({**ref, **changes}))
        with self.corrupt('artifact_topics', '1=1', topic_id=sf.OTHER):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation needs topic-authorized comparison evidence'):
                self.insert_record('extraction_validations_v2')

    def test_immutable(self):
        before = self.snapshot('extraction_validations_v2')
        for sql, message in (("UPDATE extraction_validations_v2 SET created_at=created_at", 'validations are immutable'),
                ("DELETE FROM extraction_validations_v2", 'validations are retained'),
                ("INSERT OR REPLACE INTO extraction_validations_v2 SELECT * FROM extraction_validations_v2", 'validations are retained'),
                ("INSERT INTO extraction_validations_v2 SELECT * FROM extraction_validations_v2 WHERE true ON CONFLICT DO UPDATE SET created_at=excluded.created_at", 'validations are immutable')):
            self.rejects(message, sql)
            self.assertEqual(self.snapshot('extraction_validations_v2'), before)

    def test_bindings(self):
        for guard in ('registered', 'comparison_registry', 'current_registry', 'artifact'):
            self.x('DROP TRIGGER extraction_validations_v2_' + guard)  # isolate lineage
        for field in ('target_extraction_id', 'validator_extraction_id'):
            with self.subTest(field=field), self.assertRaisesRegex(sqlite3.IntegrityError, 'validation needs independent validator and exact acquisition lineage'):
                self.insert_record('extraction_validations_v2', **{field: 'absent'})
        for table, where, field, value in (
                *(('source_extractions', "extraction_id='ext-independent'", f, 'foreign') for f in ('topic_id','work_id','source_version','event_id','verifier_invocation_id','extracting_invocation_id')),
                ('source_extractions', "extraction_id='ext-target'", 'extracting_invocation_id', 'inv_vvvvvvvv'),
                ('source_extractions', "extraction_id IN ('ext-target','ext-independent')", 'verifier_invocation_id', 'inv_pppppppp'),
                ('source_artifacts', '1=1', 'invocation_id', 'inv_vvvvvvvv'),
                *(('invocations', "invocation_id='inv_vvvvvvvv'", f, v) for f, v in (('topic_id',sf.OTHER),('kind','checkpoint'),('admission_context','scoping/1'),('parent_invocation_id','inv_pppppppp'))),
                *(('operation_receipts', "operation_id='op_extractval'", f, v) for f, v in (('invocation_id','inv_pppppppp'),('topic_id',sf.OTHER),('contract_revision',999)))):
            with self.subTest(table=table, field=field), self.corrupt(table, where, **{field:value}):
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'validation needs independent validator and exact acquisition lineage'):
                    self.insert_record('extraction_validations_v2')
