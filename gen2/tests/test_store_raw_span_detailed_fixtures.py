"""Raw literal controls retain exact values alongside admitted /2 positives."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from gen2.core import canonical
from gen2.tests import store_fixtures as sf
from gen2.tests import test_store_span_domain as spans
from gen2.tests import test_store_exact_spans as exact
from gen2.tests import test_store_content_tiers as content
from gen2.tests import test_store_detailed_receipt_fixtures as converted
from gen2.tests.ddl_fixtures import TRIGGERS
from gen2.tests.span_cap_cases import LIMIT
from gen2.tests.test_store_fixture_order import reverse_triggers

OWNERS = (spans.SpanDDLTest, spans.ExtractionSpanDDLTest, spans.ValidatedSpanDDLTest,
    exact.ExactSpanDDLTest, exact.ExtractionExactSpanDDLTest, exact.ValidatedExactSpanDDLTest)


class RawSpanFixtureTest(unittest.TestCase):
    check_receipt = converted.ConvertedFixtureTest.check_receipt

    def opened(self, owner, *, full=False):
        case = owner()
        acquired = case.acquired
        with patch.object(case, 'acquired', side_effect=lambda record, *a, **kw:
                acquired(content.FULL if full else record, *a, **kw)):
            case.setUp()
        self.addCleanup(case.tearDown)
        return case

    def retained(self, case):
        doc = json.loads(case.rows('SELECT receipt FROM verification_receipts')[0][0])
        self.check_receipt(case.assessments, doc, case.assessments.source)
        return doc

    def test_distinct_spans_bind_all_kinds_without_new_assessments(self):
        controls = ([spans.PAGE], [spans.span(start=LIMIT, end=LIMIT)],
            [spans.PAGE, spans.locator(kind='line')], [spans.locator(kind='line'), spans.PAGE])
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__):
                case = self.opened(owner); before = case.assessments.state(exclude=())
                records = case.rows('SELECT * FROM detailed_check_records')
                ids = set()
                for control in controls:
                    case.x('SAVEPOINT retained')
                    try:
                        case.insert(control)
                        self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), records)
                        doc = self.retained(case)
                        self.assertEqual(doc['cited_spans'], control)
                        self.assertEqual(doc['access_tier'], 'bibliographic')
                        current = {e['record_id'] for e in doc['detailed_checks'].values()}
                        self.assertTrue(ids.isdisjoint(current)); ids.update(current)
                    finally:
                        case.x('ROLLBACK TO retained'); case.x('RELEASE retained')
                self.assertEqual(len(ids), 16)
                self.assertEqual(case.assessments.state(exclude=()), before)

    def test_literal_spelling_survives_legacy_probe_and_exact_v2_binding(self):
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__):
                case = self.opened(owner); original = case.x; seen = []
                def observe(sql, *params):
                    result = original(sql, *params)
                    if sql.startswith('INSERT INTO verification_receipts ('):
                        row = dict(zip(sql.split('(', 1)[1].split(')', 1)[0].split(', '), params))
                        seen.append((json.loads(row['receipt']), row['cited_spans']))
                    return result
                for numeral, expected in (('9.007199254740991e15', LIMIT), ('0e-999999999999999999999', 0)):
                    case.x('SAVEPOINT spelling')
                    try:
                        seen.clear()
                        with patch.object(case, 'x', side_effect=observe): case.insert(exact.numeric('start', numeral))
                        self.assertEqual([d['receipt_version'] for d, _ in seen],
                            ['verification-receipt/1', 'verification-receipt/2'])
                        self.assertIn(numeral, seen[0][1]); self.assertNotIn('detailed_checks', seen[0][0])
                        doc = self.retained(case)
                        self.assertEqual(doc['cited_spans'], [dict(spans.PAGE, start=expected)])
                        self.assertEqual(seen[1][1], canonical.canonical_bytes(doc['cited_spans']).decode())
                    finally:
                        case.x('ROLLBACK TO spelling'); case.x('RELEASE spelling')

    def test_foreign_span_records_refuse_atomically_then_matching_promotes(self):
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__):
                case = self.opened(owner, full=True)
                case.x('SAVEPOINT matching_row')
                case.table_receipt('full_text', spans=(spans.PAGE,), use='load_bearing')
                doc = self.retained(case)
                cur = case.db.execute('SELECT * FROM verification_receipts')
                row = dict(zip([d[0] for d in cur.description], cur.fetchone()))
                case.x('ROLLBACK TO matching_row'); case.x('RELEASE matching_row')
                bad = copy.deepcopy(doc); bad['verification_receipt_id'] = 'ver_foreignspan'
                bad['cited_spans'] = [spans.span(start=LIMIT, end=LIMIT)]
                row.update(verification_receipt_id=bad['verification_receipt_id'],
                    cited_spans=canonical.canonical_bytes(bad['cited_spans']).decode(),
                    receipt=canonical.canonical_bytes(bad).decode())
                before = case.assessments.state(exclude=())
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt detailed check binding'):
                    case.x(f"INSERT INTO verification_receipts ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())
                self.assertEqual(case.assessments.state(exclude=()), before)
                case.table_receipt('full_text', spans=bad['cited_spans'], use='load_bearing')
                matching = self.retained(case)
                self.assertNotEqual(matching['detailed_checks'], bad['detailed_checks'])
                case.x("UPDATE claims SET status='accepted_support' WHERE claim_id='clm_00000001' AND revision=1")
                self.assertEqual(case.rows("SELECT status FROM claims WHERE claim_id='clm_00000001'"), [('accepted_support',)])

    def test_requested_catalog_and_local_omissions_survive_all_six_owners(self):
        ddl = reverse_triggers(sf.DDL_TEXT).replace('d.topic_id = NEW.topic_id', '1 = 1')
        ddl += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
        omitted = {'member_domain_verification_receipts_receipt_i', 'member_domain_verification_receipts_cited_spans_i'}
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(ddl)
            expected = [r for r in reference.execute(TRIGGERS) if r[0] not in omitted]
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__), patch.object(sf, 'DDL_TEXT', ddl):
                case = self.opened(owner)
                self.assertEqual(case.rows(TRIGGERS), expected)
                case.test_domain_control(); self.retained(case)
