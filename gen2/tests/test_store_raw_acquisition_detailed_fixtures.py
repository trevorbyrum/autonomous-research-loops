"""Canonical/acquisition controls consume real assessments without hidden writes."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from gen2.core import canonical
from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests import test_store_canonical_receipts as source
from gen2.tests import test_store_extraction_acquisitions as extraction
from gen2.tests import test_store_detailed_receipt_fixtures as converted
from gen2.tests.ddl_fixtures import TRIGGERS
from gen2.tests.test_store_fixture_order import reverse_triggers

OWNERS = ((source.CanonicalDDLTest, 'canonical_bytes'),
    (extraction.ExtractionDDLTest, 'verifier_extraction'),
    (extraction.ExtractionDDLTest, 'validated_extraction'))


class RawAcquisitionFixtureTest(unittest.TestCase):
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
        self.assertEqual(case.rows('SELECT response_bytes FROM source_acquisitions'), [(raw,)])
        return doc

    def test_original_selector_controls_retain_exact_source_and_verifier_records(self):
        for owner, name, expected in ((source.CanonicalDDLTest, 'test_predicates', 8),
                (extraction.ExtractionDDLTest, 'test_selectors', 14)):
            with self.subTest(owner=owner.__name__):
                case = self.opened(owner); verify = case.verify; seen = []
                def observe(*args, **kwargs):
                    records = case.rows('SELECT * FROM detailed_check_records')
                    verify(*args, **kwargs)
                    self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), records)
                    seen.append(self.retained(case))
                with patch.object(case, 'verify', side_effect=observe): getattr(case, name)()
                self.assertEqual(len(seen), expected)
                self.assertEqual({d['source']['work_id'] for d in seen}, {'wrk_00000001', 'wrk_other001'})
                self.assertEqual({d['verifier_invocation_id'] for d in seen}, {'inv_vvvvvvvv', 'inv_newver01'})
                sets = [{e['record_id'] for e in d['detailed_checks'].values()} for d in seen]
                self.assertTrue(sets[0].isdisjoint(sets[2]))  # foreign work and verifier

    def test_performed_outcomes_conflict_and_rollback_leave_assessments_unchanged(self):
        for owner, method in OWNERS:
            with self.subTest(method=method):
                case = self.opened(owner); case.raw()
                submit = case.canonical_receipt if method == 'canonical_bytes' else lambda **kw: case.extraction_receipt(method, **kw)
                before = case.assessments.state(exclude=())
                for outcome, status in (('succeeded', 'checked_ok'), ('failed', 'checked_problem'), ('not_applicable', 'not_applicable')):
                    case.x('SAVEPOINT receipt')
                    try:
                        submit(verdict='partially_supports', checks=dict(case.CHECKS_OK, numeric_units=status))
                        doc = self.retained(case)
                        self.assertEqual(doc['extraction']['method'], method)
                        self.assertEqual(doc['detailed_checks']['numeric_units']['outcome'], outcome)
                        self.assertEqual(doc['access_tier'], 'bibliographic')
                        self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), before['detailed_check_records'])
                        with self.assertRaisesRegex(sqlite3.IntegrityError, 'UNIQUE constraint'): submit()
                    finally:
                        case.x('ROLLBACK TO receipt'); case.x('RELEASE receipt')
                    self.assertEqual(case.assessments.state(exclude=()), before)

    def test_foreign_span_refuses_atomically_then_matching_receipt_is_accepted(self):
        for owner, method in OWNERS:
            with self.subTest(method=method):
                case = self.opened(owner); case.raw()
                submit = case.canonical_receipt if method == 'canonical_bytes' else lambda: case.extraction_receipt(method)
                case.x('SAVEPOINT row'); submit(); doc = self.retained(case)
                cursor = case.x('SELECT * FROM verification_receipts')
                row = dict(zip([d[0] for d in cursor.description], cursor.fetchone()))
                case.x('ROLLBACK TO row'); case.x('RELEASE row')
                bad = copy.deepcopy(doc); bad['cited_spans'][0]['locator']['value'] = 'foreign page'
                row.update(receipt=canonical.canonical_bytes(bad).decode(), cited_spans=canonical.canonical_bytes(bad['cited_spans']).decode())
                before = case.assessments.state(exclude=())
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt detailed check binding'):
                    case.x(f"INSERT INTO verification_receipts ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())
                self.assertEqual(case.assessments.state(exclude=()), before)
                submit(); self.retained(case)

    def test_full_admission_restores_requested_views_and_trigger_order(self):
        requested = reverse_triggers(sf.DDL_TEXT).replace('d.topic_id = NEW.topic_id', '1 = 1')
        requested = requested.replace('ELSE 1 END AS recorded_tier_rank', 'ELSE (0 + 1) END AS recorded_tier_rank')
        requested += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
        views = "SELECT name,sql FROM sqlite_schema WHERE type='view' ORDER BY rowid"
        def catalog(ddl):
            with sqlite3.connect(':memory:') as reference:
                reference.executescript(ddl)
                return list(reference.execute(TRIGGERS)), list(reference.execute(views))
        full, expected = catalog(db.schema_text()), catalog(requested)
        seed = source.seed_checks; seen = []
        def observe(bridge, doc):
            self.assertEqual((bridge.rows(TRIGGERS), bridge.rows(views)), full)
            seen.append(doc['source'])
            return seed(bridge, doc)
        for owner, method in OWNERS:
            with self.subTest(method=method), patch.object(sf, 'DDL_TEXT', requested), patch.object(source, 'seed_checks', observe):
                case = self.opened(owner); case.raw()
                self.assertEqual((case.rows(TRIGGERS), case.rows(views)), expected)
                if method == 'canonical_bytes': case.canonical_receipt()
                else: case.extraction_receipt(method)
                self.retained(case)
                self.assertEqual((case.rows(TRIGGERS), case.rows(views)), expected)
        self.assertEqual(len(seen), len(OWNERS))
