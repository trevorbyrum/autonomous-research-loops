"""Converted Router bindings retain evidence, promotion paths and span identity."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from gen2.tests import store_fixtures as sf
from gen2.tests import test_store_detailed_receipt_fixtures as converted
from gen2.tests.test_store_fixture_order import reverse_triggers
from gen2.tests.ddl_fixtures import TRIGGERS
from gen2.tests import test_pending_extraction_support as pending
from gen2.tests.test_pending_extraction_support import bound_fixture, support_document
from gen2.tests.test_table_availability import span_fixture, content, document, METHODS, PAGE, TABLE
from gen2.tests import test_exact_spans as exact


class SpanFixtureTest(unittest.TestCase):
    check_receipt = converted.ConvertedFixtureTest.check_receipt

    def test_bound_promotions_keep_all_references(self):
        for method in METHODS:
            for tier in ('abstract', 'full_text'):
                with self.subTest(method=method, tier=tier), bound_fixture(content.FULL, tier) as case:
                    doc = support_document(case, method, tier)
                    before = case.state(exclude=())
                    self.assertEqual(case.send(doc)['status'], 'committed')
                    self.check_receipt(case, doc, case.source)
                    self.assertEqual(doc['requested_for'], dict(use='load_bearing', required_access_tier=tier))
                    pending.PendingRouterTest().promote(case, 'committed')
                    self.assertEqual(case.rows("SELECT status FROM claims WHERE claim_id='clm_loadbear1'"), [('accepted_support',)])
                    self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), before['detailed_check_records'])

    def test_distinct_spans_keep_tiers_and_records(self):
        for method in METHODS:
            for tier in ('bibliographic', 'abstract', 'full_text'):
                with self.subTest(method=method, tier=tier), span_fixture(content.FULL) as case:
                    ids = set()
                    for index, spans in enumerate(((PAGE,), (TABLE,), (PAGE, TABLE))):
                        doc = document(case, method, tier, spans=spans)
                        doc['verification_receipt_id'] = 'ver_span0000' + str(index)
                        new_ids = {e['record_id'] for e in doc['detailed_checks'].values()}
                        self.assertTrue(ids.isdisjoint(new_ids)); ids.update(new_ids)
                        self.assertEqual(case.send(doc, op='op_span0000' + str(index))['status'], 'committed')
                        self.check_receipt(case, doc, case.source)
                        self.assertEqual(doc['access_tier'], tier)
                    self.assertEqual(len(ids), 12)

    def test_foreign_span_references_refuse_before_matching_control(self):
        for method in METHODS:
            with self.subTest(method=method), span_fixture(content.FULL) as case:
                page = document(case, method, 'full_text', spans=(PAGE,))
                table = document(case, method, 'full_text', spans=(TABLE,))
                self.assertNotEqual(page['cited_spans'], table['cited_spans'])
                bad = copy.deepcopy(table)
                bad['detailed_checks'] = copy.deepcopy(page['detailed_checks'])
                before = case.state()
                out = case.send(bad)
                self.assertEqual((out['status'], out.get('reason')), ('rejected', 'payload_invalid'), out)
                self.assertIn('receipt detailed check binding', out['detail'])
                self.assertEqual(case.state(), before)
                self.assertEqual(case.send(table)['status'], 'committed')
                self.check_receipt(case, table, case.source)

    def test_exponent_control_binds_decoded_value(self):
        exponent = {**PAGE, 'start': 1e30}
        self.assertNotEqual(exponent, PAGE)
        for method in METHODS:
            with self.subTest(method=method), span_fixture(content.FULL, bindings=((PAGE,), (exponent,))) as case:
                page = document(case, method, 'bibliographic', spans=(PAGE,))
                out = exact.ExactSpanRouterTest().stage(case, method, exact.raw.numeric('start', '1e30'), binding_spans=(exponent,))
                self.assertEqual(out['status'], 'committed', out)
                doc = json.loads(case.value('SELECT receipt FROM verification_receipts'))
                self.assertEqual(doc['cited_spans'], [exponent])
                self.assertTrue({e['record_id'] for e in page['detailed_checks'].values()}.isdisjoint(
                    e['record_id'] for e in doc['detailed_checks'].values()))
                self.check_receipt(case, doc, case.source)

    def test_both_reseeding_owners_preserve_requested_catalog(self):
        ddl = reverse_triggers(sf.DDL_TEXT).replace('d.topic_id = NEW.topic_id', '1 = 1')
        ddl += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(ddl)
            expected = reference.execute(TRIGGERS).fetchall()
        for fixture in (span_fixture, bound_fixture):
            with self.subTest(owner=fixture.__name__), patch.object(sf, 'DDL_TEXT', ddl), fixture(content.FULL) as case:
                self.assertEqual(case.rows(TRIGGERS), expected)
