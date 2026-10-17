"""Raw table positives consume real assessments without changing SQL policy."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from gen2.core import canonical
from gen2.tests import store_fixtures as sf
from gen2.tests import test_store_table_availability as raw
from gen2.tests import test_store_detailed_receipt_fixtures as converted
from gen2.tests.ddl_fixtures import TRIGGERS
from gen2.tests.test_store_fixture_order import reverse_triggers

OWNERS = (raw.TableDDLTest, raw.ExtractionTableDDLTest, raw.ValidatedTableDDLTest)


class RawTableFixtureTest(unittest.TestCase):
    check_receipt = converted.ConvertedFixtureTest.check_receipt

    def opened(self, owner):
        case = owner('test_table_control')
        case.setUp()
        self.addCleanup(case.tearDown)
        return case

    def test_all_spans_and_tiers_keep_authenticated_records(self):
        for owner in OWNERS:
            for tier in ('bibliographic', 'abstract', 'full_text'):
                with self.subTest(owner=owner.__name__, tier=tier):
                    case = self.opened(owner); case.acquired(raw.content.FULL)
                    before = case.rows('SELECT * FROM detailed_check_records')
                    ids = set()
                    for index, spans in enumerate(((raw.PAGE,), (raw.TABLE,), (raw.PAGE, raw.TABLE))):
                        case.table_receipt(tier, rid='ver_rawtable' + str(index), spans=spans)
                        doc = json.loads(case.rows('SELECT receipt FROM verification_receipts WHERE verification_receipt_id=?',
                            'ver_rawtable' + str(index))[0][0])
                        self.assertEqual((doc['access_tier'], doc['cited_spans']), (tier, list(spans)))
                        self.check_receipt(case.assessments, doc, case.assessments.source)
                        current = {e['record_id'] for e in doc['detailed_checks'].values()}
                        self.assertTrue(ids.isdisjoint(current)); ids.update(current)
                    self.assertEqual(len(ids), 12)
                    self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), before)
                    data = case.assessments.spool.read(case.assessments.source['content_hash'], topic_id=sf.TOPIC)
                    self.assertEqual(data, raw.content.response(raw.content.FULL))
                    self.assertEqual(canonical.bytes_digest(data), case.assessments.source['content_hash'])
                    self.assertNotEqual(case.assessments.source['content_hash'], sf.h('7'))

    def test_foreign_span_records_refuse_then_matching_support_promotes(self):
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__):
                case = self.opened(owner); case.acquired(raw.content.FULL)
                rows = []
                for spans in ((raw.PAGE,), (raw.TABLE,)):
                    case.x('SAVEPOINT capture_row')
                    case.table_receipt('full_text', spans=spans, use='load_bearing')
                    cur = case.db.execute('SELECT * FROM verification_receipts')
                    rows.append(dict(zip([d[0] for d in cur.description], cur.fetchone())))
                    case.x('ROLLBACK TO capture_row'); case.x('RELEASE capture_row')
                page, table = [json.loads(r['receipt']) for r in rows]
                self.assertNotEqual(page['cited_spans'], table['cited_spans'])
                bad = copy.deepcopy(table); bad['detailed_checks'] = page['detailed_checks']
                row = dict(rows[1], receipt=canonical.canonical_bytes(bad).decode())
                sql = f"INSERT INTO verification_receipts ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})"
                before = case.assessments.state(exclude=())
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt detailed check binding'):
                    case.x(sql, *row.values())
                self.assertEqual(case.assessments.state(exclude=()), before)
                case.x(sql, *rows[1].values())
                self.check_receipt(case.assessments, table, case.assessments.source)
                case.x("UPDATE claims SET status='accepted_support' WHERE claim_id='clm_00000001' AND revision=1")
                self.assertEqual(case.rows("SELECT status FROM claims WHERE claim_id='clm_00000001'"), [('accepted_support',)])

    def test_unperformed_outcomes_have_no_invented_references(self):
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__):
                case = self.opened(owner); case.acquired(dict(identity='rec-1'))
                case.table_receipt(required='full_text', verdict='cannot_assess_at_required_tier',
                    checks=dict(case.CHECKS_OK, numeric_units='not_checked', denominators='unavailable'))
                doc = json.loads(case.rows('SELECT receipt FROM verification_receipts')[0][0])
                self.assertEqual(doc['receipt_version'], 'verification-receipt/2')
                for kind in ('numeric_units', 'denominators'):
                    self.assertEqual(doc['detailed_checks'][kind], dict(outcome=doc['checks'][kind]))
                for kind in ('negation', 'qualifications'):
                    self.assertEqual(len(case.rows('SELECT 1 FROM detailed_check_records WHERE check_id=?',
                        doc['detailed_checks'][kind]['record_id'])), 1)
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'supporting load-bearing-use verification receipt'):
                    case.x("UPDATE claims SET status='accepted_support' WHERE claim_id='clm_00000001'")

    def test_reseed_restores_exact_requested_catalog_for_every_owner(self):
        ddl = reverse_triggers(sf.DDL_TEXT).replace('d.topic_id = NEW.topic_id', '1 = 1')
        ddl += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(ddl)
            expected = reference.execute(TRIGGERS).fetchall()
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__), patch.object(sf, 'DDL_TEXT', ddl):
                case = self.opened(owner)
                self.assertEqual(case.rows(TRIGGERS), expected)
                case.test_table_control()
