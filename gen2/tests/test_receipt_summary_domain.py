"""Router admission validates summaries before they can select record policy."""
import copy
import unittest

from gen2.tests.detailed_receipt_fixtures import seed_checks, historical_receipt
from gen2.tests.test_canonical_receipt_admission import ReceiptCase
from gen2.tests.test_detailed_check_receipts import KINDS, ReferenceCases
from gen2.tests.test_extraction_acquisitions import extraction_document
from gen2.tests.test_pending_extraction_support import load_claim


METHODS = ('canonical_bytes', 'verifier_extraction', 'validated_extraction')
BAD = ('succeeded', 'failed', 'invented', 1, True, {}, [], None, 'checked_ok\x00suffix')


class SummaryCases:

    def opened(self, method='canonical_bytes'):
        case = ReceiptCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        case.admit()
        load_claim(case, 'abstract')
        case.doc = (case.document() if method == 'canonical_bytes'
            else extraction_document(case, method, detailed=False))
        case.doc['claim']['claim_id'] = 'clm_loadbear1'
        case.doc['requested_for']['use'] = 'load_bearing'
        case.doc['access_tier'] = case.doc['requested_for']['required_access_tier'] = 'abstract'
        self.assertEqual(case.value('PRAGMA foreign_keys'), 1)
        self.assertEqual(case.value('SELECT count(*) FROM detailed_check_records'), 0)
        return case

    def refused(self, case):
        before = case.state(exclude=())
        out = ReferenceCases.submit(case)
        self.assertEqual(out['status'], 'rejected', out)
        case.assert_audited_state(before, 1)
        self.assertEqual(case.store.select('verification_receipts'), [])
        self.assertEqual(out['reason'], 'payload_invalid', out)
        return out

    def test_b1(self):
        # Astra's exact bypass: /1, all four successor words, no records,
        # ordinary current admission with the declared catalog.
        case = self.opened()
        case.doc['verdict'] = 'partially_supports'
        for kind in KINDS:
            case.doc['checks'][kind] = 'succeeded'
        self.refused(case)

    def test_summary_domain(self):
        for method in METHODS:
            case = self.opened(method)
            original = copy.deepcopy(case.doc)
            for version in ('verification-receipt/1', 'verification-receipt/2'):
                for verdict in ('supports', 'partially_supports'):
                    for bad in BAD:
                        for kind in KINDS:
                            with self.subTest(method=method, version=version,
                                    verdict=verdict, bad=bad, kind=kind):
                                case.doc = copy.deepcopy(original)
                                case.doc.update(receipt_version=version, verdict=verdict)
                                if verdict == 'supports':
                                    case.doc['adjudication'] = dict(adjudication_ref='adj-domain',
                                        resolved_at=case.doc['verified_at'], resolution='Explicit fixture resolution.')
                                if version.endswith('/2'):
                                    case.doc['detailed_checks'] = {k: dict(outcome='succeeded') for k in KINDS}
                                case.doc['checks'][kind] = bad
                                self.refused(case)
            self.doCleanups()

    def test_control(self):
        # Separate accepted control: real authenticated records, all three bases.
        for method in METHODS:
            with self.subTest(method=method):
                case = self.opened(method)
                seed_checks(case, case.doc)
                for verdict in ('supports', 'partially_supports'):
                    case.doc.update(verdict=verdict, verification_receipt_id='ver_' + verdict)
                    case.doc['adjudication'] = (dict(adjudication_ref='adj-control',
                        resolved_at=case.doc['verified_at'], resolution='Explicit fixture resolution.')
                        if verdict == 'supports' else None)
                    self.assertEqual(ReferenceCases.submit(case)['status'], 'committed')
                    self.assertEqual(case.store.select('verification_receipts',
                        {'verification_receipt_id': case.doc['verification_receipt_id']})[0]['receipt'], case.doc)
                self.assertEqual(case.rows('PRAGMA foreign_key_check'), [])

    def test_successor_outcome_vocabulary(self):
        case = self.opened()
        seed_checks(case, case.doc)
        for kind in KINDS:
            for legacy in ('checked_ok', 'checked_problem'):
                with self.subTest(kind=kind, legacy=legacy):
                    original = case.doc['detailed_checks'][kind]['outcome']
                    case.doc['detailed_checks'][kind]['outcome'] = legacy
                    self.refused(case)
                    case.doc['detailed_checks'][kind]['outcome'] = original

    def test_compatibility(self):
        for verdict, use, summary in (('supports', 'sampled', 'checked_ok'),
                ('does_not_support', 'load_bearing', 'not_checked'),
                ('cannot_assess_at_required_tier', 'load_bearing', 'unavailable')):
            with self.subTest(verdict=verdict):
                case = self.opened()
                case.doc['verdict'] = verdict
                case.doc['requested_for']['use'] = use
                for kind in KINDS:
                    case.doc['checks'][kind] = summary
                self.assertEqual(ReferenceCases.submit(case)['status'], 'committed')
                self.assertEqual(case.store.select('verification_receipts')[0]['receipt'], case.doc)

    def test_unperformed_remains_refused(self):
        for summary in ('not_checked', 'unavailable'):
            case = self.opened()
            case.doc['verdict'] = 'partially_supports'
            for kind in KINDS:
                case.doc['checks'][kind] = summary
            self.refused(case)


class SummaryRouterTest(SummaryCases, unittest.TestCase):
    pass
