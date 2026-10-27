"""Capture consumption and final refencing through the Router."""
import copy
import json
import unittest

from gen2.tests.detailed_support_fixtures import history
from gen2.tests.detailed_receipt_fixtures import attach_checks, historical_receipt
from gen2.tests.extraction_receipt_fixtures import attach
from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.test_capture_support import CaptureCase


class RouterCaptureSupportTest(unittest.TestCase):

    def opened(self):
        case = CaptureCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        return case

    def status(self, case, revision=2):
        return case.value('SELECT status FROM claims WHERE revision=?', revision)

    def retained(self, case, doc):
        # Explicit historical/corrupt operands; all checks/bases were admitted.
        with history(case, unchecked=True):
            case.x('UPDATE verification_receipts SET receipt=? WHERE verification_receipt_id=?',
                json.dumps(doc), doc['verification_receipt_id'])

    def test_control(self):
        case = self.opened()
        record, doc = case.operands()
        case.accepted(record, verification_receipts=[doc])
        case.promote()
        self.assertEqual(case.rows('PRAGMA foreign_key_check'), [])
        self.doCleanups()

    def test_no_pooling(self):
        for method in ('verifier_extraction', 'validated_extraction'):
            case = self.opened()
            record, canonical = case.operands()
            extraction = copy.deepcopy(canonical)
            extraction['verification_receipt_id'] = 'ver_extraction01'
            extraction['extraction'].update(method=method,
                produced_by_invocation_id=case.grant['invocation_id'] if method == 'verifier_extraction' else 'inv_capture001')
            attach(case, extraction); attach_checks(case, extraction)
            case.accepted(record, verification_receipts=[canonical, extraction])
            historical = copy.deepcopy(canonical)
            historical_receipt(historical)
            self.retained(case, historical)
            case.promote(accepted=False)
            # A later, individually complete canonical candidate may win.
            canonical['verification_receipt_id'] = 'ver_latercomplete'
            self.assertEqual(case.send([], verification_receipts=[canonical])['status'], 'committed')
            case.promote()
            self.doCleanups()

    def test_capture_binding_and_columns(self):
        case = self.opened()
        record, doc = case.operands()
        case.accepted(record, verification_receipts=[doc])
        with history(case, unchecked=True):
            case.x("UPDATE verification_receipts SET quote_check_id=NULL")
        case.promote(accepted=False)
        with history(case):
            case.x('UPDATE verification_receipts SET quote_check_id=?', doc['quote_check_id'])
            case.x("UPDATE verification_receipts SET receipt=json_set(receipt,'$.checks.exact_quote.normalization_version','foreign/1')")
        case.promote(accepted=False)
        self.retained(case, doc)
        case.promote()
        self.doCleanups()

    def late(self, case, *, complete=False, kind='interim_transition', records=None):
        record, doc = case.operands()
        doc['verification_receipt_id'] = 'ver_latebound01'
        payload = {**empty_outcome(case.grant['invocation_id'], kind),
            'quote_checks': records if records is not None else [record],
            'verification_receipts': [doc] if complete else []}
        case.env = case.envelope(case.grant, case.ids('op_'), payload)
        if kind == 'final_outcome':
            case.ready(case.grant, case.env['payload_digest'])
        out = case.router.commit_outcome(case.env)
        self.assertEqual(out['status'], 'committed', out)
        return out

    def accepted_without_capture(self, case):
        _, doc = case.operands()
        doc['quote_check_id'] = None
        doc['checks']['exact_quote']['status'] = 'not_applicable'
        self.assertEqual(case.send([], verification_receipts=[doc])['status'], 'committed')
        case.promote()

    def test_final_control(self):
        for kind in ('interim_transition', 'final_outcome'):
            case = self.opened()
            self.accepted_without_capture(case)
            self.late(case, complete=True, kind=kind)
            self.assertEqual(self.status(case), 'accepted_support')
            self.assertEqual(case.rows('PRAGMA foreign_key_check'), [])
            self.doCleanups()

    def test_final_missing_and_history(self):
        for kind in ('interim_transition', 'final_outcome'):
            case = self.opened()
            self.accepted_without_capture(case)
            self.late(case, kind=kind)
            self.assertEqual(self.status(case), 'quarantined')
            self.doCleanups()
        case = self.opened()
        record, doc = case.operands()
        case.accepted(record, verification_receipts=[doc])
        case.promote()
        historical_receipt(doc)
        self.retained(case, doc)
        self.assertIsNotNone(case.router.receipt(case.env['operation_id']))
        self.late(case, records=[{**record, 'check_id': 'qck_latehistory'}])
        self.assertEqual(self.status(case), 'quarantined')

    def test_scope_and_status(self):
        case = self.opened()
        self.accepted_without_capture(case)
        # Another operation's deficient acceptance is untouched by this one.
        with history(case):
            case.x("UPDATE claims SET status='accepted_support' WHERE revision=1")
        case.accepted(case.record(quoted_text='effect NOT observed'))
        self.assertEqual(self.status(case, 1), 'quarantined')
        with history(case):
            case.x("UPDATE claims SET status='accepted_support' WHERE revision=1")
            case.x("UPDATE claims SET status='contested' WHERE revision=2")
        self.late(case, records=[case.record(claim_revision=2, check_id='qck_scoped0002', quoted_text='effect NOT observed')])
        self.assertEqual(self.status(case), 'contested')
        self.assertEqual(self.status(case, 1), 'accepted_support')
        self.doCleanups()

    def test_final_records_and_basis(self):
        case = self.opened()
        record, doc = case.operands()
        case.accepted(record, verification_receipts=[doc])
        case.promote()
        for i, kind in enumerate(('numeric_units', 'denominators', 'negation', 'qualifications', 'basis')):
            bad = copy.deepcopy(doc)
            if kind == 'basis':
                with history(case):
                    case.x("UPDATE source_acquisitions SET lane='foreign'")
            else:
                bad['detailed_checks'][kind] = dict(outcome='not_checked')
                bad['checks'][kind] = 'not_checked'
                bad['adjudication'] = dict(adjudication_ref='adj-unperformed', resolved_at=doc['verified_at'],
                    resolution='Cannot waive unperformed checks.')
                self.retained(case, bad)
            self.late(case, records=[{**record, 'check_id': 'qck_final000' + str(i)}])
            self.assertEqual(self.status(case), 'quarantined', kind)
            self.retained(case, doc)
            with history(case):
                case.x("UPDATE source_acquisitions SET lane='crossref'")
                case.x("UPDATE claims SET status='accepted_support' WHERE revision=2")
        self.doCleanups()

    def test_replay_conflict_rollback(self):
        case = self.opened()
        self.accepted_without_capture(case)
        before = case.state(exclude=())
        case.faults['in_transaction:end'] = RuntimeError('after capture refence')
        with self.assertRaisesRegex(RuntimeError, 'after capture refence'):
            self.late(case)
        self.assertEqual(case.state(exclude=()), before)
        case.faults.clear()
        out = self.late(case)
        before = case.state(exclude=())
        self.assertEqual(case.router.commit_outcome(case.env), dict(status='replayed', receipt=out['receipt']))
        self.assertEqual(case.state(exclude=()), before)
        other = case.envelope(case.grant, case.env['operation_id'], empty_outcome(case.grant['invocation_id'], 'interim_transition'))
        self.assertEqual(case.router.commit_outcome(other)['reason'], 'operation_id_conflict')
