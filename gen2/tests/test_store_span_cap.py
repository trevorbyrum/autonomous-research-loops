"""Auxiliary raw integer/span admission uses the same cap as receipts."""
import json
import sqlite3
from decimal import Decimal

from gen2.tests import store_fixtures as fx
from gen2.tests.span_cap_cases import LIMIT, NUMERALS, literal


class AuxiliaryCapTest(fx.StoreTestCase):
    def setUp(self):
        super().setUp()
        self.populate_every_table()
        self.x("INSERT INTO claims SELECT claim_id,2,topic_id,text_ref,producer_invocation_id,load_bearing,required_access_tier,'provisional',created_at FROM claims")

    def write_link(self, raw):
        self.x('INSERT INTO claim_source_links SELECT claim_id,2,work_id,source_version,topic_id,contract_revision,obligation_id,?,contribution,evidence_origin_lineage,analytical_method,created_at FROM claim_source_links WHERE claim_revision=1', raw)

    def write_quote(self, start, end):
        self.x("INSERT INTO quote_checks (check_id,claim_id,claim_revision,source_artifact_hash,span_start,span_end,normalization_version,exact_match,nli_signal,quote_quarantined,checked_at) VALUES ('cap-quote','clm_00000001',1,?, ?,?,'n1','matched','not_run',0,?)", fx.h('7'), start, end, fx.T)

    def test_refusals(self):
        for key in ('start', 'end'):
            for n in NUMERALS:
                if n.startswith('-') or n.startswith('0') or 'e-' in n: continue
                if Decimal(n) <= LIMIT: continue
                with self.subTest(key=key, n=n):
                    self.x('SAVEPOINT cap')
                    try:
                        before = self.rows('SELECT * FROM claim_source_links')
                        with self.assertRaisesRegex(sqlite3.IntegrityError, '9007199254740991'): self.write_link(literal(key, n))
                        self.assertEqual(self.rows('SELECT * FROM claim_source_links'), before)
                    finally:
                        self.x('ROLLBACK TO cap')
                        self.x('RELEASE cap')
        for start, end in ((LIMIT + 1, LIMIT + 2), (0, LIMIT + 1)):
            before = self.rows('SELECT * FROM quote_checks')
            with self.assertRaisesRegex(sqlite3.IntegrityError, '9007199254740991'): self.write_quote(start, end)
            self.assertEqual(self.rows('SELECT * FROM quote_checks'), before)

    def test_control(self):
        self.write_link(literal('start', str(LIMIT)))
        self.write_quote(LIMIT - 1, LIMIT)
        self.assertEqual(json.loads(self.rows('SELECT spans FROM claim_source_links WHERE claim_revision=2')[0][0])[0]['start'], LIMIT)
        self.assertEqual(self.rows("SELECT span_start,span_end FROM quote_checks WHERE check_id='cap-quote'"), [(LIMIT - 1, LIMIT)])
