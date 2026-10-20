"""Converted fixtures retain admitted evidence, accepted paths and real catalogs."""
import copy
import unittest
from unittest.mock import patch

from gen2.core import canonical
from gen2.tests import store_fixtures as sf
from gen2.tests.detailed_receipt_fixtures import seed_checks, attach_checks, historical_receipt
from gen2.tests.router_fixtures import empty_outcome
from gen2.tests import test_own_extraction_receipts as own
from gen2.tests import test_validated_extraction_receipts as validated
from gen2.tests import test_bound_extraction_support as promotion
from gen2.tests import test_store_own_extraction_receipts as raw_own
from gen2.tests import test_store_validated_extraction_receipts as raw_validated
from gen2.tests import test_store_bound_extraction_support as raw_promotion
from gen2.tests.test_store_fixture_order import reverse_triggers


class ConvertedFixtureTest(unittest.TestCase):
    def opened(self, cls):
        fixture = cls('test_control')
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        fixture.setUp()
        return fixture

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

    def test_own_and_validated_controls(self):
        # Byte-equal controls are intentional; the distinct-output test below
        # independently discriminates canonical, target and validator selectors.
        for cls in (own.OwnReceiptRouterTest, raw_own.OwnReceiptDDLTest,
                validated.ValidatedReceiptRouterTest, raw_validated.ValidatedReceiptDDLTest):
            with self.subTest(owner=cls.__name__):
                fixture = self.opened(cls)
                fixture.test_control()
                self.check_receipt(fixture.case, fixture.doc, fixture.case.source)

    def test_same_promotions_at_every_tier(self):
        for cls in (promotion.BoundPromotionRouterTest, raw_promotion.BoundPromotionDDLTest):
            for method in ('verifier_extraction', 'validated_extraction'):
                for tier in ('bibliographic', 'abstract', 'full_text'):
                    with self.subTest(owner=cls.__name__, method=method, tier=tier):
                        fixture = cls('test_control')
                        self.addCleanup(fixture.doCleanups)
                        fixture.context(method, tier)
                        fixture.store(); fixture.promote()
                        self.check_receipt(fixture.case, fixture.doc, fixture.case.source)

    def test_new_legacy_and_optional_support_requires_records(self):
        for cls in (promotion.BoundPromotionRouterTest, raw_promotion.BoundPromotionDDLTest):
            for method in ('verifier_extraction', 'validated_extraction'):
                for version in ('verification-receipt/1', 'verification-receipt/2'):
                    with self.subTest(owner=cls.__name__, method=method, version=version):
                        fixture = cls('test_control')
                        self.addCleanup(fixture.doCleanups)
                        fixture.context(method)
                        if version.endswith('/1'): historical_receipt(fixture.doc)
                        else:
                            for entry in fixture.doc['detailed_checks'].values(): del entry['record_id']
                        before = fixture.case.state()
                        out = own.OwnCases.submit(fixture)
                        self.assertEqual(out['status'], 'rejected', out)
                        self.assertIn('requires detailed check records', out['detail'])
                        self.assertEqual(fixture.case.state(), before)
                        self.assertEqual(fixture.case.rows('SELECT * FROM verification_receipts'), [])

    def test_performed_failure_and_exemption_retain_evidence(self):
        for cls in (promotion.BoundPromotionRouterTest, raw_promotion.BoundPromotionDDLTest):
            with self.subTest(owner=cls.__name__):
                fixture = cls('test_control'); self.addCleanup(fixture.doCleanups)
                fixture.context('validated_extraction')
                fixture.doc['verdict'] = 'partially_supports'
                fixture.doc['checks'].update(numeric_units='checked_problem', denominators='not_applicable')
                attach_checks(fixture.case, fixture.doc)
                fixture.store()
                self.check_receipt(fixture.case, fixture.doc, fixture.case.source)
                fixture.promote('rejected')

    def test_distinct_outputs_bind_every_kind_and_promote(self):
        for layer in ('router', 'raw'):
            for method in ('canonical_bytes', 'verifier_extraction', 'validated_extraction'):
                with self.subTest(layer=layer, method=method):
                    fixture = promotion.BoundPromotionRouterTest('test_control')
                    self.addCleanup(fixture.doCleanups)
                    fixture.context('validated_extraction')
                    case, doc = fixture.case, fixture.doc
                    refs = [case.artifact(b'Target: a distinct retained fixture rendering.'),
                        case.artifact(b'Validator: independent rendering of the same fixture.'),
                        case.artifact(b'Attributed semantic comparison of both renderings.')]
                    self.assertEqual(len({case.source['content_hash'], *[r['content_hash'] for r in refs]}), 4)
                    def commit(grant, op, **sections):
                        out = case.router.commit_outcome(case.envelope(grant, op,
                            {**empty_outcome(grant['invocation_id'], 'interim_transition'), **sections}, refs=refs))
                        self.assertEqual(out['status'], 'committed', out)
                    def extraction(identity, new_id, ref):
                        row = case.store.select('source_extractions', {'extraction_id': identity})[0]
                        return {**{k: v for k, v in row.items() if k not in
                            ('topic_id', 'extracting_invocation_id', 'recorded_by_operation_id', 'created_at')},
                            'extraction_id': new_id, 'output_ref': ref}
                    target = extraction(fixture.target, 'converted-target', refs[0])
                    independent = extraction(fixture.independent, 'converted-independent', refs[1])
                    commit(case.producer, 'op_convertedtarget', source_extractions=[target])
                    validation = copy.deepcopy(case.store.select('extraction_validations_v2')[0])
                    for key in ('validator_invocation_id', 'recorded_by_operation_id', 'created_at'): del validation[key]
                    validation.update(validation_id='converted-validation', target_extraction_id=target['extraction_id'],
                        validator_extraction_id=independent['extraction_id'], comparison='semantic_agreement', comparison_evidence_ref=refs[2])
                    commit(case.verifier, 'op_convertedvalidator', source_extractions=[independent], extraction_validations_v2=[validation])
                    doc['extraction'].update(method=method)
                    if method == 'verifier_extraction':
                        doc['extraction'].update(extraction_id=independent['extraction_id'], extractor=independent['extractor_identity'],
                            produced_by_invocation_id=case.verifier['invocation_id'], validation_ref=None)
                    elif method == 'validated_extraction': doc['extraction']['validation_ref'] = validation['validation_id']
                    else: doc['extraction'].update(produced_by_invocation_id=case.ACQUIRER, validation_ref=None)
                    expected = case.source if method == 'canonical_bytes' else refs[1 if method == 'verifier_extraction' else 0]
                    if method != 'canonical_bytes': seed_checks(case, doc)
                    fixture.RAW = layer == 'raw'
                    self.assertEqual(own.OwnCases.submit(fixture)['status'], 'committed')
                    fixture.promote()
                    self.check_receipt(case, doc, expected)

    def test_reseed_preserves_requested_catalog(self):
        ddl = reverse_triggers(sf.DDL_TEXT).replace('d.topic_id = NEW.topic_id', '1 = 1')
        ddl += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
        for cls in (own.OwnReceiptRouterTest, raw_own.OwnReceiptDDLTest,
                validated.ValidatedReceiptRouterTest, raw_validated.ValidatedReceiptDDLTest,
                promotion.BoundPromotionRouterTest, raw_promotion.BoundPromotionDDLTest):
            with self.subTest(owner=cls.__name__), patch.object(sf, 'DDL_TEXT', ddl):
                if issubclass(cls, promotion.PromotionCases):
                    fixture = cls('test_control'); self.addCleanup(fixture.doCleanups)
                    fixture.context('validated_extraction')
                else: fixture = self.opened(cls)
                names = dict(fixture.case.rows("SELECT name,sql FROM sqlite_schema WHERE type='trigger'"))
                self.assertNotIn('verification_receipts_detailed_domain', names)
                self.assertIn('1 = 1', names['verification_receipts_detailed_binding'])
