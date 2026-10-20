"""Current Router fixtures, with explicit staged-policy and historical controls."""
import json
import sqlite3
import unittest
from unittest.mock import patch

from gen2.tests import store_fixtures as sf
from gen2.tests import test_router_commit as authority
from gen2.tests import test_store_detailed_receipt_fixtures as converted
from gen2.store import db
from gen2.tests.ddl_fixtures import TRIGGERS
from gen2.tests.detailed_receipt_fixtures import OUTCOME, seed_checks
from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.test_canonical_content_tiers import FULL, attributed_fixture, fixture
from gen2.tests.test_extraction_acquisitions import extraction_document
from gen2.tests.test_pending_extraction_support import load_claim
from gen2.tests.test_store_fixture_order import reverse_triggers


class CanonicalFixtureTest(unittest.TestCase):
    check_receipt = converted.ConvertedFixtureTest.check_receipt

    def promote(self, case):
        out = case.router.commit_outcome(case.envelope(case.producer, 'op_promote001',
            {**empty_outcome(case.producer['invocation_id'], 'interim_transition'),
             'claim_promotions': [dict(claim_id='clm_loadbear1', revision=1)]}))
        self.assertEqual(out['status'], 'committed', out)
        self.assertEqual(case.rows("SELECT status FROM claims WHERE claim_id='clm_loadbear1'"), [('accepted_support',)])

    def test_same_promotions_and_tiers(self):
        # These ordinary outputs are intentionally byte equal. Distinct-output
        # discrimination is separately exercised by ConvertedFixtureTest.
        for method in ('canonical_bytes', 'verifier_extraction', 'validated_extraction'):
            for tier in ('bibliographic', 'abstract', 'full_text'):
                with self.subTest(method=method, tier=tier), attributed_fixture(FULL) as case:
                    load_claim(case, tier)
                    doc = extraction_document(case, method)
                    doc['claim']['claim_id'] = 'clm_loadbear1'
                    doc['requested_for'].update(use='load_bearing', required_access_tier=tier)
                    doc['access_tier'] = tier
                    seed_checks(case, doc)
                    before = case.state(exclude=())
                    case.faults['in_transaction:end'] = RuntimeError('receipt rollback')
                    with self.assertRaisesRegex(RuntimeError, 'receipt rollback'): case.send(doc)
                    self.assertEqual(case.state(exclude=()), before)
                    case.faults.clear()
                    self.assertEqual(case.send(doc)['status'], 'committed')
                    self.check_receipt(case, doc, case.source)
                    self.promote(case)

    def test_new_verifier_has_distinct_records(self):
        for method in ('canonical_bytes', 'verifier_extraction', 'validated_extraction'):
            with self.subTest(method=method), attributed_fixture(FULL) as case:
                first = extraction_document(case, method)
                self.assertEqual(case.send(first)['status'], 'committed')
                first_ids = {e['record_id'] for e in first['detailed_checks'].values()}
                self.assertEqual(case.finish(case.verifier, 'op_finishverify')['status'], 'committed')
                case.verifier = case.started('inv_nextverify', 'verification')
                case.admit()
                doc = extraction_document(case, method)
                doc['verification_receipt_id'] = 'ver_nextverify'
                self.assertNotEqual(doc['verifier_invocation_id'], first['verifier_invocation_id'])
                self.assertTrue(first_ids.isdisjoint(e['record_id'] for e in doc['detailed_checks'].values()))
                self.assertEqual(case.send(doc, op='op_nextverify')['status'], 'committed')
                self.check_receipt(case, doc, case.source)
                self.check_receipt(case, first, case.source)

    def test_empty_record_store_refuses_new_legacy_and_optional_support(self):
        for method in ('canonical_bytes', 'verifier_extraction', 'validated_extraction'):
            for version in ('verification-receipt/1', 'verification-receipt/2'):
                with self.subTest(method=method, version=version), fixture(FULL) as case:
                    load_claim(case, 'full_text')
                    doc = extraction_document(case, method)
                    doc['claim']['claim_id'] = 'clm_loadbear1'
                    doc['requested_for'].update(use='load_bearing', required_access_tier='full_text')
                    doc.update(receipt_version=version, access_tier='full_text')
                    if version.endswith('/2'):
                        doc['detailed_checks'] = {k: dict(outcome=OUTCOME[doc['checks'][k]]) for k in
                            ('numeric_units', 'denominators', 'negation', 'qualifications')}
                    self.assertEqual(case.rows('SELECT * FROM detailed_check_records'), [])
                    before = case.state()
                    out = case.send(doc)
                    self.assertEqual(out['status'], 'rejected', out)
                    self.assertIn('requires detailed check records', out['detail'])
                    self.assertEqual(case.state(), before)
                    self.assertEqual(case.rows('SELECT * FROM verification_receipts'), [])

    def test_authority_positive_has_all_admitted_references(self):
        case = authority.AuthorityTest('test_a_producer_cannot_verify_its_own_work')
        case.setUp()
        self.addCleanup(case.tearDown)
        case.test_a_producer_cannot_verify_its_own_work()
        doc = json.loads(case.value('SELECT receipt FROM verification_receipts'))
        case.source = case.store.select('artifacts', {'content_hash': doc['obtained_content_hash']})[0]
        case.source = {k: case.source[k] for k in ('content_hash', 'size_bytes', 'media_type')}
        self.check_receipt(case, doc, case.source)

    def test_reseeding_owners_preserve_complete_requested_catalog(self):
        ddl = reverse_triggers(sf.DDL_TEXT).replace('d.topic_id = NEW.topic_id', '1 = 1')
        ddl += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(ddl)
            expected = reference.execute(TRIGGERS).fetchall()
        with patch.object(sf, 'DDL_TEXT', ddl), attributed_fixture(FULL) as case:
            self.assertEqual(case.rows(TRIGGERS), expected)
        with patch.object(sf, 'DDL_TEXT', ddl):
            case = authority.AuthorityTest('test_a_producer_cannot_verify_its_own_work')
            with patch.object(sf, 'DDL_TEXT', db.schema_text()): case.setUp()
            self.addCleanup(case.tearDown)
            case.test_a_producer_cannot_verify_its_own_work()
            self.assertEqual(case.rows(TRIGGERS), expected)
