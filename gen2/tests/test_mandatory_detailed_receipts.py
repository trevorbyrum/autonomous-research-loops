"""Current receipt admission: attributed records, never self-declared authority."""
import copy
import unittest

from gen2.tests import test_detailed_check_receipts as references
from gen2.tests.ddl_fixtures import TRIGGERS
from gen2.tests.detailed_receipt_fixtures import OUTCOME, attach_checks, seed_checks, historical_receipt, historical_admission
from gen2.tests.test_pending_extraction_support import load_claim


class MandatoryCases:

    def opened(self):
        case = references.ReferenceRouterTest('test_control')
        case.setUp()
        self.addCleanup(case.tearDown)
        load_claim(case, 'abstract')
        case.doc['claim']['claim_id'] = 'clm_loadbear1'
        case.doc['requested_for']['use'] = 'load_bearing'
        seed_checks(case, case.doc)
        return case

    def refused(self, case, detail=None):
        before = case.state(exclude=())
        out = case.submit()
        self.assertEqual(out['status'], 'rejected', out)
        self.assertEqual(out.get('reason'), 'payload_invalid', out)
        if detail: self.assertIn(detail, out['detail'])
        case.assert_audited_state(before, 1)

    def test_control(self):
        case = self.opened()
        self.assertEqual(case.submit()['status'], 'committed')
        self.assertEqual(case.store.select('verification_receipts')[0]['receipt'], case.doc)
        self.assertEqual(case.rows('PRAGMA foreign_key_check'), [])

    def test_missing(self):
        case = self.opened()
        original = copy.deepcopy(case.doc)
        for verdict in ('supports', 'partially_supports'):
            for kind in references.KINDS:
                with self.subTest(verdict=verdict, kind=kind):
                    case.doc = copy.deepcopy(original)
                    case.doc['verdict'] = verdict
                    del case.doc['detailed_checks'][kind]['record_id']
                    self.refused(case, 'requires detailed check records')

    def test_legacy(self):
        case = self.opened()
        case.doc['receipt_version'] = 'verification-receipt/1'
        del case.doc['detailed_checks']
        for verdict in ('supports', 'partially_supports'):
            case.doc['verdict'] = verdict
            self.refused(case, 'requires detailed check records')

    def test_bindings(self):
        case = self.opened()
        original = copy.deepcopy(case.doc)
        for kind in references.KINDS:
            with self.subTest(kind=kind):
                # All other references match; only this reference names the
                # independently admitted record for the other claim revision.
                case.doc = copy.deepcopy(original)
                case.doc['detailed_checks'][kind]['record_id'] = kind
                self.refused(case, 'receipt detailed check binding')
                case.doc = copy.deepcopy(original)
                case.doc['detailed_checks'][kind]['record_id'] = 'absent'
                self.refused(case, 'receipt detailed check binding')

    def test_outcomes(self):
        case = self.opened()
        original = copy.deepcopy(case.doc)
        for kind in references.KINDS:
            for summary, outcome in OUTCOME.items():
                with self.subTest(kind=kind, outcome=outcome):
                    case.doc = copy.deepcopy(original)
                    case.doc['checks'][kind] = summary
                    case.doc['verification_receipt_id'] = 'ver_' + kind + '_' + outcome
                    if outcome == 'failed':
                        case.doc['adjudication'] = dict(adjudication_ref='adj-performed',
                            resolved_at=case.doc['verified_at'], resolution='Explicit fixture resolution after re-reading.')
                    attach_checks(case, case.doc)
                    if outcome in ('not_checked', 'unavailable'):
                        for verdict in ('supports', 'partially_supports'):
                            case.doc['verdict'] = verdict
                            self.refused(case)
                        case.doc['verdict'] = 'does_not_support'
                    self.assertEqual(case.submit()['status'], 'committed', case.doc)
                    self.assertEqual(case.store.select('verification_receipts',
                        {'verification_receipt_id': case.doc['verification_receipt_id']})[0]['receipt'], case.doc)

    def test_failed_without_record(self):
        case = self.opened()
        for kind in references.KINDS:
            case.doc['checks'][kind] = 'checked_problem'
        attach_checks(case, case.doc)
        case.doc['adjudication'] = dict(adjudication_ref='adj-unperformed',
            resolved_at=case.doc['verified_at'], resolution='An adjudication cannot perform absent checks.')
        self.missing_entries(case)

    def test_exemption_without_record(self):
        case = self.opened()
        for kind in references.KINDS:
            case.doc['checks'][kind] = 'not_applicable'
        attach_checks(case, case.doc)
        self.missing_entries(case)

    def test_historical_isolation_restores_current_policy_and_catalog(self):
        case = self.opened()
        case.x("CREATE TRIGGER legacy_sentinel BEFORE INSERT ON verification_receipts "
            "WHEN NEW.verification_receipt_id='ver_sentinel' BEGIN SELECT RAISE(ABORT,'legacy sentinel'); END")
        catalog = case.rows(TRIGGERS)
        historical_receipt(case.doc)
        with historical_admission(case):
            self.assertNotIn('verification_receipts_require_detailed_checks', dict(case.rows(TRIGGERS)))
            self.assertEqual(case.submit()['status'], 'committed')
            case.doc['verification_receipt_id'] = 'ver_sentinel'
            self.refused(case, 'legacy sentinel')
        self.assertEqual(case.rows(TRIGGERS), catalog)
        retained = case.store.select('verification_receipts')[0]['receipt']
        self.assertEqual(retained['receipt_version'], 'verification-receipt/1')
        with self.assertRaisesRegex(RuntimeError, 'historical rollback'):
            with historical_admission(case):
                raise RuntimeError('historical rollback')
        self.assertEqual(case.rows(TRIGGERS), catalog)
        case.doc['verification_receipt_id'] = 'ver_current001'
        self.refused(case, 'requires detailed check records')

    def missing_entries(self, case):
        for kind in references.KINDS:
            entry = case.doc['detailed_checks'][kind]
            identity = entry.pop('record_id')
            self.refused(case, 'requires detailed check records')
            entry['record_id'] = identity


class MandatoryRouterTest(MandatoryCases, unittest.TestCase):
    def test_replay_conflict_rollback(self):
        case = self.opened()
        before = case.state(exclude=())
        case.faults['in_transaction:end'] = RuntimeError('mandatory rollback')
        with self.assertRaisesRegex(RuntimeError, 'mandatory rollback'):
            case.submit()
        self.assertEqual(case.state(exclude=()), before)
        case.faults.clear()
        self.assertEqual(case.submit()['status'], 'committed')
        before = case.state(exclude=())
        self.assertEqual(case.router.commit_outcome(case.env)['status'], 'replayed')
        self.assertEqual(case.state(exclude=()), before)
        del case.doc['detailed_checks']['negation']['record_id']
        self.assertEqual(case.submit()['reason'], 'operation_id_conflict')
