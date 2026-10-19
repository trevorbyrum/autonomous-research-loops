"""Raw content positives bind authenticated assessments before subject writes."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from gen2.core import canonical
from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests import test_store_content_tiers as content
from gen2.tests import test_store_extraction_content_tiers as extraction
from gen2.tests import test_store_detailed_receipt_fixtures as converted
from gen2.tests.ddl_fixtures import TRIGGERS
from gen2.tests.test_store_fixture_order import reverse_triggers

OWNERS = (content.ContentDDLTest, extraction.ExtractionContentDDLTest, extraction.ValidatedContentDDLTest)


class RawContentFixtureTest(unittest.TestCase):
    check_receipt = converted.ConvertedFixtureTest.check_receipt

    def opened(self, owner):
        case = owner()
        case.setUp()
        self.addCleanup(case.tearDown)
        return case

    def retained(self, case):
        doc = json.loads(case.rows('SELECT receipt FROM verification_receipts')[0][0])
        self.check_receipt(case.assessments, doc, case.assessments.source)
        raw = case.assessments.spool.read(doc['obtained_content_hash'], topic_id=sf.TOPIC)
        self.assertEqual(canonical.bytes_digest(raw), doc['obtained_content_hash'])
        return doc

    def test_every_tier_and_performed_outcome_retains_evidence_without_new_records(self):
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__):
                case = self.opened(owner)
                case.acquired(content.FULL)
                records = case.rows('SELECT * FROM detailed_check_records')
                before = case.assessments.state(exclude=())
                for tier in ('bibliographic', 'abstract', 'full_text'):
                    for outcome, status in (('succeeded', 'checked_ok'), ('failed', 'checked_problem'), ('not_applicable', 'not_applicable')):
                        with self.subTest(tier=tier, outcome=outcome):
                            case.x('SAVEPOINT retention')
                            try:
                                case.content_receipt(tier, verdict='partially_supports', checks=dict(case.CHECKS_OK, numeric_units=status))
                                doc = self.retained(case)
                                self.assertEqual(doc['access_tier'], tier)
                                self.assertEqual(doc['detailed_checks']['numeric_units']['outcome'], outcome)
                                self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), records)
                                with self.assertRaisesRegex(sqlite3.IntegrityError, 'UNIQUE constraint'):
                                    case.content_receipt(tier)
                            finally:
                                case.x('ROLLBACK TO retention'); case.x('RELEASE retention')
                            self.assertEqual(case.assessments.state(exclude=()), before)

    def test_foreign_span_refuses_atomically_then_matching_full_text_promotes(self):
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__):
                case = self.opened(owner)
                case.acquired(content.FULL)
                case.x('SAVEPOINT row')
                case.content_receipt('full_text', use='load_bearing')
                doc = self.retained(case)
                cursor = case.x('SELECT * FROM verification_receipts')
                row = dict(zip([d[0] for d in cursor.description], cursor.fetchone()))
                case.x('ROLLBACK TO row'); case.x('RELEASE row')
                bad = copy.deepcopy(doc)
                bad['cited_spans'][0]['locator']['value'] = 'foreign page'
                row.update(receipt=canonical.canonical_bytes(bad).decode(),
                    cited_spans=canonical.canonical_bytes(bad['cited_spans']).decode())
                before = case.assessments.state(exclude=())
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt detailed check binding'):
                    case.x(f"INSERT INTO verification_receipts ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())
                self.assertEqual(case.assessments.state(exclude=()), before)
                case.content_receipt('full_text', use='load_bearing')
                self.retained(case)
                case.x("UPDATE claims SET status='accepted_support' WHERE claim_id='clm_00000001' AND revision=1")
                self.assertEqual(case.rows('SELECT status FROM claims'), [('accepted_support',)])
                self.assertEqual(case.rows('SELECT response_bytes FROM source_acquisitions')[0][0],
                    case.assessments.spool.read(doc['obtained_content_hash'], topic_id=sf.TOPIC))

    def test_admission_uses_full_ddl_then_restores_exact_requested_catalog(self):
        requested = reverse_triggers(sf.DDL_TEXT).replace('d.topic_id = NEW.topic_id', '1 = 1')
        requested = requested.replace('ELSE 1 END AS recorded_tier_rank', 'ELSE (0 + 1) END AS recorded_tier_rank')
        requested += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
        views = "SELECT name,sql FROM sqlite_schema WHERE type='view' ORDER BY rowid"
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(requested); expected = list(reference.execute(TRIGGERS))
            expected_views = list(reference.execute(views))
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(db.schema_text()); full = list(reference.execute(TRIGGERS))
            full_views = list(reference.execute(views))
        seed = content.seed_checks
        seen = []
        def observe(bridge, doc):
            self.assertEqual(bridge.rows(TRIGGERS), full)
            self.assertEqual(bridge.rows(views), full_views)
            seen.append(doc['source'])
            return seed(bridge, doc)
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__), patch.object(sf, 'DDL_TEXT', requested), patch.object(content, 'seed_checks', observe):
                case = self.opened(owner)
                self.assertEqual(case.rows(TRIGGERS), expected)
                self.assertEqual(case.rows(views), expected_views)
                case.test_full_text_control()
                self.retained(case)
                self.assertEqual(case.rows(TRIGGERS), expected)
        self.assertEqual(len(seen), len(OWNERS))
