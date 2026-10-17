"""Attributed quote consumers preserve captures, attention and exact catalogs."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from gen2.tests import store_fixtures as sf
from gen2.tests import canonical_quotes_fixtures as canonical
from gen2.tests import test_capture_support as capture
from gen2.tests import test_quote_attention as quote
from gen2.tests import test_verification_attention as verdict
from gen2.tests import test_store_detailed_receipt_fixtures as converted
from gen2.tests.ddl_fixtures import TRIGGERS
from gen2.tests.test_store_fixture_order import reverse_triggers


class QuoteFixtureTest(unittest.TestCase):
    check_receipt = converted.ConvertedFixtureTest.check_receipt

    def opened(self, owner):
        case = owner()
        case.setUp()
        self.addCleanup(case.tearDown)
        return case

    def retained(self, case):
        docs = [json.loads(row[0]) for row in case.rows('SELECT receipt FROM verification_receipts')]
        self.assertTrue(docs)
        for doc in docs:
            self.check_receipt(case, doc, case.source)
            self.assertEqual(doc['access_tier'], 'full_text')
        return docs

    def test_accepted_quote_capture_adjudication_and_verdict_paths(self):
        for owner, method in ((capture.CaptureTest, 'test_control'), (capture.RouterGuardTest, 'test_control'),
                (quote.AttentionTest, 'test_recapture'), (quote.AttentionTest, 'test_nli_adjudication_control'),
                (verdict.AttentionTest, 'test_support_control'), (verdict.AttentionTest, 'test_competing_receipt_preserves_hold')):
            with self.subTest(owner=owner.__module__ + '.' + owner.__name__, method=method):
                case = self.opened(owner)
                getattr(case, method)()
                self.retained(case)
        case = self.opened(canonical.CanonicalQuotesCase)
        case.accepted(verification_receipts=[case.receipt_document()])
        self.retained(case)

    def test_distinct_revisions_and_ordered_spans_keep_promotions(self):
        case = self.opened(capture.CaptureTest)
        _, single = case.operands()
        case.test_multi_control()
        mixed = self.retained(case)[0]
        self.assertEqual(mixed['claim'], dict(claim_id='clm_quote00001', claim_revision=2))
        self.assertEqual(mixed['cited_spans'], [dict(start=2, end=17, locator=dict(kind='section', value='Results')),
            dict(start=0, end=1, locator=dict(kind='section', value='Results'))])
        case.new_capture(3, b'effect observed again')
        record, third = case.operands(3)
        record['check_id'] = third['quote_check_id'] = 'qck_nextcapture'
        third['verification_receipt_id'] = 'ver_nextcapture'
        groups = [{e['record_id'] for e in doc['detailed_checks'].values()} for doc in (single, mixed, third)]
        self.assertEqual([len(g) for g in groups], [4, 4, 4])
        self.assertEqual(len(set.union(*groups)), 12)
        before = case.rows('SELECT * FROM detailed_check_records')
        case.accepted(record, verification_receipts=[third]); case.promote(3)
        self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), before)
        self.assertEqual(case.rows('SELECT revision,status FROM claims WHERE revision>1 ORDER BY revision'),
            [(2, 'accepted_support'), (3, 'accepted_support')])
        self.retained(case)

    def test_foreign_capture_records_refuse_atomically_then_matching_promotes(self):
        case = self.opened(capture.CaptureTest)
        record, doc = case.operands()
        bad = copy.deepcopy(doc)
        bad['detailed_checks'] = case.receipt_document()['detailed_checks']
        self.assertNotEqual(doc['claim']['claim_revision'], case.receipt_document()['claim']['claim_revision'])
        before = case.state()
        out = case.send([record], verification_receipts=[bad])
        self.assertEqual((out['status'], out.get('reason')), ('rejected', 'payload_invalid'), out)
        self.assertIn('receipt detailed check binding', out['detail'])
        self.assertEqual(case.state(), before)
        case.accepted(record, verification_receipts=[doc]); case.promote()
        self.retained(case)

    def test_unperformed_attention_retains_truthful_outcomes_without_references(self):
        case = self.opened(verdict.AttentionTest)
        before = case.rows('SELECT * FROM detailed_check_records')
        case.test_missing_content()
        doc = json.loads(case.value('SELECT receipt FROM verification_receipts'))
        self.assertEqual(doc['receipt_version'], 'verification-receipt/2')
        self.assertEqual(doc['detailed_checks'], {k: dict(outcome=v) for k, v in
            dict(numeric_units='not_checked', denominators='unavailable', negation='not_checked', qualifications='unavailable').items()})
        self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), before)

    def test_reseeding_preserves_requested_catalog_and_subject_local_drops(self):
        ddl = reverse_triggers(sf.DDL_TEXT).replace('d.topic_id = NEW.topic_id', '1 = 1')
        ddl += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(ddl)
            expected = reference.execute(TRIGGERS).fetchall()
        for owner in (canonical.CanonicalQuotesCase, capture.CaptureTest, capture.RouterGuardTest):
            with self.subTest(owner=owner.__name__), patch.object(sf, 'DDL_TEXT', ddl):
                case = self.opened(owner)
                omitted = {'verification_receipts_capture_binding', 'claims_accepted_support_needs_capture',
                    'verification_receipts_admitted_extraction'} if owner is capture.RouterGuardTest else set()
                self.assertEqual(case.rows(TRIGGERS), [r for r in expected if r[0] not in omitted])
                if isinstance(case, capture.CaptureCase):
                    requested = case.rows(TRIGGERS)
                    case.new_capture(3, b'new capture bytes')
                    self.assertEqual(case.rows(TRIGGERS), requested)
                case.accepted(verification_receipts=[case.receipt_document()])
                self.retained(case)
