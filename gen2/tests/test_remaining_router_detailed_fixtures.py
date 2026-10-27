"""Remaining Router positives retain authenticated evidence and their paths."""
import copy
import json
import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from gen2.core import canonical
from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests import test_router_amendments as amendments
from gen2.tests import test_span_cap as cap
from gen2.tests.ddl_fixtures import TRIGGERS, restore_triggers
from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.ddl_fixtures import reverse_triggers


class RemainingRouterFixtureTest(unittest.TestCase):
    def check_receipt(self, case, doc, expected_ref):
        self.assertEqual(doc['receipt_version'], 'verification-receipt/2')
        self.assertEqual(case.store.select('verification_receipts',
            {'verification_receipt_id': doc['verification_receipt_id']})[0]['receipt'], doc)
        self.assertEqual(set(doc['detailed_checks']), {'numeric_units', 'denominators', 'negation', 'qualifications'})
        for kind, entry in doc['detailed_checks'].items():
            row = case.store.select('detailed_check_records', {'check_id': entry['record_id']})[0]
            report = row['assessment']
            self.assertEqual((report['kind'], report['outcome']), (kind, entry['outcome']))
            self.assertEqual((report['claim_id'], report['claim_revision']),
                (doc['claim']['claim_id'], doc['claim']['claim_revision']))
            self.assertEqual((report['work_id'], report['source_version']),
                (doc['source']['work_id'], doc['source']['source_version']))
            self.assertEqual(report['cited_spans'], doc['cited_spans'])
            self.assertEqual(report['examined_artifact_ref'], expected_ref)
            self.assertEqual(report['source_artifact_hash'], case.source['content_hash'])
            self.assertEqual(row['performer_invocation_id'], doc['verifier_invocation_id'])
            self.assertNotEqual(row['performer_invocation_id'], doc['producer_invocation_id'])
            operation = case.store.select('operation_receipts', {'operation_id': row['recorded_by_operation_id']})[0]
            self.assertEqual(operation['invocation_id'], row['performer_invocation_id'])
            self.assertEqual(report['method'], 'attributed-assessment/1')
            self.assertTrue(report['assessment']); self.assertTrue(report['context_examined'])
            if entry['outcome'] == 'not_applicable': self.assertTrue(report['applicability_reason'])
            raw = case.spool.read(row['evidence_ref']['content_hash'], topic_id=doc['topic_id'])
            self.assertEqual(raw, canonical.canonical_bytes(report))
            self.assertEqual(canonical.bytes_digest(raw), row['evidence_ref']['content_hash'])
        self.assertEqual(case.rows('PRAGMA foreign_key_check'), [])

    def opened(self):
        case = amendments.ImpactTest()
        with patch.object(sf, 'DDL_TEXT', db.schema_text()):
            case.setUp()
        self.addCleanup(case.tearDown)
        restore_triggers(case, sf.DDL_TEXT)
        return case

    def observe(self, case, seen):
        original = case.router.commit_outcome
        def commit(env):
            records = case.rows('SELECT * FROM detailed_check_records')
            out = original(env)
            if out['status'] == 'committed':
                payload = canonical.parse_json_strict(case.spool.read(env['payload_digest'], topic_id=env['topic_id']))
                for doc in payload.get('verification_receipts', []):
                    self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), records)
                    case.source = case.store.select('artifacts', {'content_hash': doc['obtained_content_hash']})[0]
                    ref = {k: case.source[k] for k in ('content_hash', 'size_bytes', 'media_type')}
                    self.check_receipt(case, doc, ref)
                    self.assertEqual(canonical.bytes_digest(case.spool.read(ref['content_hash'], topic_id=doc['topic_id'])), ref['content_hash'])
                    seen.append(copy.deepcopy(doc))
            return out
        return patch.object(case.router, 'commit_outcome', side_effect=commit)

    def test_both_amendment_controls_retain_records_and_original_outcomes(self):
        for name in ('test_a_compatible_amendment_lets_admitted_work_complete_under_its_pins',
                'test_a_protocol_change_fences_admitted_work_of_every_kind'):
            with self.subTest(control=name):
                case = self.opened(); seen = []
                with self.observe(case, seen): getattr(case, name)()
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0]['requested_for']['use'], 'load_bearing')
                self.assertEqual(seen[0]['access_tier'], 'full_text')

    def test_cap_literals_retain_current_exact_bindings_for_all_methods(self):
        fixture = cap.tables.span_fixture; seen = []; selected = {}
        @contextmanager
        def observe(*args, **kwargs):
            with fixture(*args, **kwargs) as case:
                with self.observe(case, seen): yield case
        with patch.object(cap.tables, 'span_fixture', observe):
            cap.SpanCapTest().test_receipt_router_matrix()
        self.assertEqual(len(seen), len(cap.tables.METHODS) * sum(cap.admitted(k, n) for k in ('start', 'end') for n in cap.NUMERALS))
        for doc in seen:
            key = (doc['extraction']['method'], canonical.canonical_bytes(doc['cited_spans']))
            ids = {e['record_id'] for e in doc['detailed_checks'].values()}
            self.assertEqual(len(ids), 4)
            if key in selected: self.assertEqual(ids, selected[key])
            else:
                self.assertTrue(all(ids.isdisjoint(v) for (method, _), v in selected.items() if method == key[0]))
                selected[key] = ids
        self.assertEqual({d['extraction']['method'] for d in seen}, set(cap.tables.METHODS))

    def test_foreign_span_refuses_atomically_and_matching_receipt_replays(self):
        for method in ('canonical_producer', 'acquisition_producer'):
            with self.subTest(method=method):
                case = self.opened(); grant = case.research()
                verifier = case.verify(**{method: grant})
                doc = case.store.select('verification_receipts')[0]['receipt']
                bad = copy.deepcopy(doc); bad['verification_receipt_id'] = 'ver_foreignspan'
                bad['cited_spans'][0]['locator']['value'] = 'distinct foreign span'
                payload = {**empty_outcome(verifier['invocation_id'], 'interim_transition'), 'verification_receipts': [bad]}
                before = case.state()
                out = case.router.commit_outcome(case.envelope(verifier, 'op_foreignspan', payload))
                self.assertEqual((out['status'], out.get('reason')), ('rejected', 'payload_invalid'), out)
                self.assertIn('detailed check binding', out['detail'])
                case.assert_audited_state(before, 1)
                bad['cited_spans'] = copy.deepcopy(doc['cited_spans'])
                env = case.envelope(verifier, 'op_matchingspan', payload)
                records = case.rows('SELECT * FROM detailed_check_records')
                case.faults['in_transaction:end'] = RuntimeError('receipt fixture rollback')
                before = case.state(exclude=())
                with self.assertRaisesRegex(RuntimeError, 'receipt fixture rollback'): case.router.commit_outcome(env)
                self.assertEqual(case.state(exclude=()), before)
                out = case.router.commit_outcome(env)
                self.assertEqual(out['status'], 'committed', out)
                before = case.state(exclude=())
                self.assertEqual(case.router.commit_outcome(env), {'status': 'replayed', 'receipt': out['receipt']})
                self.assertEqual(case.state(exclude=()), before)
                self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), records)

    def test_amendment_reseed_restores_exact_requested_catalog(self):
        ddl = reverse_triggers(sf.DDL_TEXT)
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(ddl); expected = list(reference.execute(TRIGGERS))
        for method in ('canonical_producer', 'acquisition_producer'):
            with self.subTest(method=method), patch.object(sf, 'DDL_TEXT', ddl):
                case = self.opened(); grant = case.research()
                case.verify(**{method: grant})
                self.assertEqual(case.rows(TRIGGERS), expected)
