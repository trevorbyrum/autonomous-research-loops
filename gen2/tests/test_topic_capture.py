"""Literal capture oracles on governed fixture records; no live services."""
import hashlib
import json
import sqlite3
import tempfile
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

from gen2.core import canonical
from gen2.router.service import Router
from gen2.store import api, capture, db
from gen2.tests.router_fixtures import TOPIC, OTHER, Spool
from gen2.tests.test_extraction_records import RecordCase
from gen2.tests import test_semantic_assessments as semantic, test_governed_quotes as quotes
from gen2.tests.router_fixtures import contract


def group(snapshot, name):
    return next(table for table in snapshot.tables if table.name == name)


class CaptureTest(RecordCase):
    def snap(self, topic=TOPIC):
        return self.store.capture_topic(topic)

    def test_control(self):
        snap = self.snap()
        self.assertEqual(group(snap, 'works').rows, tuple(self.rows('SELECT * FROM works WHERE work_id=?', self.work)))
        self.assertEqual(group(snap, 'source_acquisitions').rows[0][-3:-1], (self.exchange.request_bytes, self.raw))
        self.assertEqual(group(snap, 'verification_receipts').rows, ())
        self.assertEqual(group(snap, 'contract_revisions').columns[0], 'topic_id')

    def test_hash_control(self):
        snap = self.snap()
        self.assertEqual(snap.topic_id, TOPIC)
        self.assertTrue(capture.input_hash(snap, 'native').startswith('sha256:'))

    def test_groups_and_order(self):
        snap = self.snap()
        self.assertEqual({t.name for t in snap.tables}, set('''queue_entries contract_revisions facets obligations invocations
            leases search_observations retrieval_events screening_assessments claims semantic_assessments source_lifecycle
            registry_dispositions branch_windows obligation_assessments amendment_impacts claim_source_links
            verification_receipts source_artifacts source_acquisitions source_extractions detailed_check_records holds
            operator_decisions artifact_topics dossiers operation_receipts record_work_links works source_lineage quote_checks
            extraction_validations extraction_validations_v2 artifacts extractor_registry_revisions extractor_tools audit_events'''.split()))
        self.assertEqual(group(snap, 'invocations').rows, tuple(self.rows('SELECT * FROM invocations WHERE topic_id=? ORDER BY rowid', TOPIC)))
        self.assertEqual(group(snap, 'source_extractions').rows, ())
        self.assertEqual(group(snap, 'extractor_registry_revisions').rows, ())

    def test_isolation_and_authorization(self):
        ref = self.foreign_ref(b'foreign authorization')
        before = self.snap()
        self.assertNotIn(ref['content_hash'], [r[0] for r in group(before, 'artifacts').rows])
        # The first recording topic is not the authorization relation.
        self.x('INSERT INTO artifact_topics VALUES (?, ?, ?, ?)', ref['content_hash'], TOPIC, self.producer['invocation_id'], '2026-09-27T10:00:00Z')
        after = self.snap()
        self.assertIn(ref['content_hash'], [r[0] for r in group(after, 'artifacts').rows])
        self.assertNotIn('inv_other001', [r[0] for r in group(after, 'invocations').rows])
        self.assertEqual(group(self.snap(OTHER), 'works').rows, ())
        self.assertEqual(group(self.snap(OTHER), 'record_work_links').rows, ())

    def test_historical_registry(self):
        self.basis()
        self.assertEqual(self.send(self.verifier, 'op_capture_validation', extraction_validations=[self.validation()])['status'], 'committed')
        self.assertEqual(self.router.register_extractor_registry({'registry_version': 2, 'operator_id': 'fixture',
            'reason': 'new mapping', 'tools': [{'extractor_identity': 'tool-z', 'family': 'family-z'}]})['status'], 'registered')
        snap = self.snap()
        self.assertEqual([r[0] for r in group(snap, 'extractor_registry_revisions').rows], [1])
        self.assertEqual([r[:3] for r in group(snap, 'extractor_tools').rows], [(1, 'tool-a', 'family-a'), (1, 'tool-b', 'family-b')])
        self.assertEqual([r[0] for r in group(snap, 'extraction_validations').rows], ['validation-1'])
        foreign = self.store.capture_topic(OTHER)
        self.assertEqual(group(foreign, 'extraction_validations').rows, ())
        self.assertEqual(group(foreign, 'extractor_tools').rows, ())

    def test_historical_contract(self):
        doc = contract(3, 2)
        self.assertEqual(self.router.propose_amendment({'document': doc})['status'], 'recorded')
        self.assertEqual(self.decide('opd_capture_amend', 'amendment_approval', {'kind': 'contract_revision',
            'revision': 3, 'hash': doc['content_hash']})['status'], 'applied')
        table = group(self.snap(), 'contract_revisions')
        self.assertEqual([(r[1], r[table.columns.index('status')]) for r in table.rows], [(1, 'draft'), (2, 'superseded'), (3, 'approved')])

    def test_other_shared_relations(self):
        for cls, table, expected in ((semantic.SemanticTest, 'source_lineage', 'asm_semantic00'),
                                     (quotes.QuotesCase, 'quote_checks', 'qck_quote00001')):
            case = cls()
            case.setUp()
            try:
                if table == 'source_lineage':
                    self.assertEqual(case.send([case.record()])['status'], 'committed')
                else:
                    case.accepted()
                own, foreign = case.store.capture_topic(TOPIC), case.store.capture_topic(OTHER)
                self.assertEqual([r[0] for r in group(own, table).rows], [expected])
                self.assertEqual(group(foreign, table).rows, ())
            finally:
                case.tearDown()
                case.doCleanups()

    def test_no_dml_or_computation(self):
        before, statements = self.state(exclude=()), []
        self.db.set_trace_callback(statements.append)
        with patch.object(canonical, 'parse_json_strict', side_effect=AssertionError('parsed during capture')), \
                patch.object(canonical, 'logical_hash', side_effect=AssertionError('hashed during capture')):
            snap = self.snap()
        self.db.set_trace_callback(None)
        self.assertEqual(self.state(exclude=()), before)
        self.assertFalse(any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')) for s in statements))
        digest = canonical.logical_hash
        def outside(value):
            self.assertFalse(self.db.in_transaction)
            return digest(value)
        with patch.object(canonical, 'logical_hash', outside):
            self.assertTrue(capture.input_hash(snap, 'native').startswith('sha256:'))

    def test_requires_owned_transaction(self):
        with self.store.transaction(), patch.object(db, 'capture_reader'), patch.object(capture, 'read', return_value=None):
            with self.assertRaises(api.StoreWriteError):
                self.store.capture_topic(TOPIC)
        self.db.execute('BEGIN')
        try:
            with patch.object(db, 'capture_reader'), patch.object(capture, 'read', return_value=None):
                with self.assertRaises(api.StoreWriteError):
                    self.store.capture_topic(TOPIC)
        finally:
            self.db.execute('ROLLBACK')

    def test_immutable(self):
        snap = self.snap()
        with self.assertRaises(FrozenInstanceError):
            snap.topic_id = OTHER
        with self.assertRaises(FrozenInstanceError):
            snap.tables[0].rows = ()
        with self.assertRaises(TypeError):
            snap.tables[0].rows[0][0] = OTHER
        for table in snap.tables:
            self.assertIsInstance(table.rows, tuple)
            self.assertIsInstance(table.json_columns, tuple)
            self.assertTrue(all(type(c) in (str, bytes, int, float, type(None)) for r in table.rows for c in r))

    def test_retained_wal(self):
        expected = self.snap()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.db'
            with sqlite3.connect(path) as dest:
                self.db.backup(dest)
            retained = Router.open(path, Spool())
            try:
                for _ in range(2):
                    actual = retained._store.capture_topic(TOPIC)
                    self.assertEqual((actual.topic_id, actual.tables), (expected.topic_id, expected.tables))
                    self.assertEqual(capture.input_hash(actual, 'native'), capture.input_hash(expected, 'native'))
            finally:
                retained.close()

    def test_hash_binding(self):
        table = capture.RawTable('literal', ('id', 'json', 'raw'), ('json',), (('one', '{"n":1}', b'\x00\xff'), ('two', None, b'x')))
        snap = capture.TopicCapture(TOPIC, (table, capture.RawTable('empty', ('id',), (), ())))
        def sha(value):
            return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        expected = sha({'snapshot_version': 'dossier-input/1', 'topic_id': TOPIC, 'history': 'native', 'tables': [
            {'name': 'literal', 'columns': ['id', 'json', 'raw'], 'json_columns': ['json'], 'rows': [
                sha(['one', '{"n":1}', {'blob_sha256': 'sha256:' + hashlib.sha256(b'\x00\xff').hexdigest()}]),
                sha(['two', None, {'blob_sha256': 'sha256:' + hashlib.sha256(b'x').hexdigest()}])]},
            {'name': 'empty', 'columns': ['id'], 'json_columns': [], 'rows': []}]})
        self.assertEqual(capture.input_hash(snap, 'native'), expected)
        for changed in (replace(snap, topic_id=OTHER), replace(snap, tables=(table,)),
                replace(snap, tables=(replace(table, rows=table.rows[::-1]), snap.tables[1])),
                replace(snap, tables=(replace(table, json_columns=()), snap.tables[1])),
                replace(snap, tables=(replace(table, rows=(('one', '{"n":1}', b'changed'), table.rows[1])), snap.tables[1]))):
            self.assertNotEqual(capture.input_hash(changed, 'native'), expected)
        self.assertNotEqual(capture.input_hash(snap, 'legacy_unknown'), expected)
        with self.assertRaises(ValueError):
            capture.input_hash(snap, 'invented')


class SuccessorTest(RecordCase):
    def test_successor_control(self):
        self.basis()
        self.assertEqual(self.send(self.verifier, 'op_capture_v2', extraction_validations_v2=[self.validation(policy_version=2)])['status'], 'committed')
        snap = self.store.capture_topic(TOPIC)
        self.assertEqual([r[0] for r in group(snap, 'extraction_validations_v2').rows], ['validation-1'])
