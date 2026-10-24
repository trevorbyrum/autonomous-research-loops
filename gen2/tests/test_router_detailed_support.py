"""Promotion reads actual records with all SQL support consumers isolated."""
import copy
import json
import unittest
from unittest.mock import patch

from gen2.core import canonical
from gen2.tests import test_store_detailed_support as raw
from gen2.tests import test_detailed_check_receipts as refs
from gen2.tests.detailed_receipt_fixtures import attach_checks, historical_receipt
from gen2.tests.detailed_support_fixtures import history
from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.test_receipt_summary_domain import METHODS


class RouterDetailedSupportTest(unittest.TestCase):
    RAW = True  # Receipt preparation is raw; the subject is public Router promotion.

    def opened(self, method='canonical_bytes', reverse=False, *, distinct=False):
        case = raw.DetailedSupportDDLTest.opened(self, method, reverse, seed=True, distinct=distinct)
        for name in ('claims_accepted_support_detailed_receipt', 'claims_accepted_support_detailed_extraction',
                'claims_accepted_support_needs_capture'):
            case.x('DROP TRIGGER IF EXISTS ' + name)
        # An intentionally permissive SQL42 relation cannot grant Router authority.
        case.x('DROP VIEW detailed_support_receipts')
        case.x('CREATE VIEW detailed_support_receipts AS SELECT verification_receipt_id FROM verification_receipts')
        return case

    def store(self, case):
        with history(case, unchecked=True):
            self.assertEqual(refs.ReferenceCases.submit(case)['status'], 'committed')

    def promote(self, case, accepted=False):
        before = case.state()
        case.promotion_env = case.envelope(case.producer, 'op_promote_details', {
            **empty_outcome(case.producer['invocation_id'], 'interim_transition'),
            'claim_promotions': [dict(claim_id='clm_loadbear1', revision=1)]})
        out = case.router.commit_outcome(case.promotion_env)
        self.assertEqual(out['status'], 'committed' if accepted else 'rejected', out)
        if not accepted:
            self.assertEqual(out['reason'], 'payload_invalid', out)
            self.assertIn('performed detailed checks', out['detail'])
            case.assert_audited_state(before, 1)
        self.assertEqual(case.rows('PRAGMA foreign_key_check'), [])
        return out

    def replace_doc(self, case, doc):
        with history(case, unchecked=True):
            case.x('UPDATE verification_receipts SET receipt=? WHERE verification_receipt_id=?',
                canonical.canonical_bytes(doc).decode(), case.doc['verification_receipt_id'])

    def test_control(self):
        for reverse in (False, True):
            for method in METHODS:
                with self.subTest(reverse=reverse, method=method):
                    case = self.opened(method, reverse)
                    self.store(case)
                    self.promote(case, True)
                    self.assertEqual(case.value("SELECT status FROM claims WHERE claim_id='clm_loadbear1'"), 'accepted_support')
                    self.doCleanups()

    def test_historical_shapes(self):
        for reverse in (False, True):
            for method in METHODS:
                case = self.opened(method, reverse)
                self.store(case)
                for shape in ('legacy', 'old_domain', 'empty', 'null', 'partial', 'extra'):
                    with self.subTest(reverse=reverse, method=method, shape=shape):
                        doc = copy.deepcopy(case.doc)
                        if shape == 'legacy':
                            doc['receipt_version'] = 'verification-receipt/1'
                        elif shape == 'old_domain':
                            historical_receipt(doc)
                            doc['checks'].update({k: 'invented' for k in refs.KINDS})
                            doc['adjudication'] = dict(adjudication_ref='adj-history', resolved_at=doc['verified_at'],
                                resolution='Retained old-domain assessment, never detailed authority.')
                        elif shape == 'empty':
                            historical_receipt(doc)
                            doc['receipt_version'] = 'verification-receipt/2'
                            doc['detailed_checks'] = {}
                            doc['checks'].update({k: 'invented' for k in refs.KINDS})
                        elif shape == 'null': doc['detailed_checks'] = None
                        elif shape == 'partial':
                            doc['detailed_checks'].pop('qualifications')
                            doc['checks']['qualifications'] = 'invented'
                        else:
                            doc['checks']['foreign'] = 'checked_ok'
                            doc['detailed_checks']['foreign'] = dict(outcome='succeeded',
                                record_id=doc['detailed_checks']['qualifications']['record_id'])
                        self.replace_doc(case, doc)
                        self.promote(case)
                self.doCleanups()

    def test_bindings(self):
        for reverse in (False, True):
            for method in METHODS:
                case = self.opened(method, reverse, distinct=method == 'validated_extraction')
                self.store(case)
                for kind in refs.KINDS:
                    rid = case.doc['detailed_checks'][kind]['record_id']
                    original = case.store.select('detailed_check_records', {'check_id': rid})[0]
                    fields = dict(kind='foreign', outcome='failed', claim_id='clm_foreign01', claim_revision=2,
                        cited_spans=[*case.doc['cited_spans'], case.doc['cited_spans'][0]], work_id='wrk_foreign01',
                        source_version='v2', source_artifact_hash='sha256:' + '0' * 64,
                        **{'examined_artifact_ref.content_hash': 'sha256:' + '1' * 64})
                    for field, value in fields.items():
                        with self.subTest(reverse=reverse, method=method, kind=kind, field=field):
                            with history(case):
                                case.x('UPDATE detailed_check_records SET assessment=json_set(assessment,?,json(?)) WHERE check_id=?',
                                    '$.' + field, json.dumps(value), rid)
                            self.promote(case)
                            with history(case):
                                case.x('UPDATE detailed_check_records SET assessment=? WHERE check_id=?', json.dumps(original['assessment']), rid)
                    for column, value in (('topic_id', 'topic_other01'),
                            ('performer_invocation_id', case.producer['invocation_id'])):
                        with self.subTest(reverse=reverse, method=method, kind=kind, column=column):
                            # Use an existing foreign topic to preserve the FK contract.
                            if column == 'topic_id':
                                value = case.value("SELECT topic_id FROM queue_entries WHERE topic_id<>? LIMIT 1", case.doc['topic_id'])
                            with history(case):
                                case.x('UPDATE detailed_check_records SET ' + column + '=? WHERE check_id=?', value, rid)
                            self.promote(case)
                            with history(case):
                                case.x('UPDATE detailed_check_records SET ' + column + '=? WHERE check_id=?', original[column], rid)
                self.doCleanups()

    def test_missing_and_outcomes(self):
        for method in METHODS:
            case = self.opened(method)
            self.store(case)
            for kind in refs.KINDS:
                for outcome in ('missing', 'absent', 'not_checked', 'unavailable', 'projection', 'outcome'):
                    with self.subTest(method=method, kind=kind, outcome=outcome):
                        doc = copy.deepcopy(case.doc)
                        entry = doc['detailed_checks'][kind]
                        if outcome == 'missing': entry.pop('record_id')
                        elif outcome == 'absent': entry['record_id'] = 'absent'
                        elif outcome == 'projection': doc['checks'][kind] = 'invented'
                        elif outcome == 'outcome': entry['outcome'] = 'failed'
                        else:
                            entry['outcome'] = outcome
                            doc['checks'][kind] = outcome
                        rid = case.doc['detailed_checks'][kind]['record_id']
                        record = case.store.select('detailed_check_records', {'check_id': rid})[0]
                        if outcome in ('not_checked', 'unavailable'):
                            with history(case, unchecked=True):
                                case.x("UPDATE detailed_check_records SET assessment=json_set(assessment,'$.outcome',?) WHERE check_id=?", outcome, rid)
                        doc['adjudication'] = dict(adjudication_ref='adj-unperformed', resolved_at=doc['verified_at'],
                            resolution='Cannot waive absent performance.')
                        self.replace_doc(case, doc)
                        self.promote(case)
                        with history(case):
                            case.x('UPDATE detailed_check_records SET assessment=? WHERE check_id=?', json.dumps(record['assessment']), rid)
            self.doCleanups()

    def test_performed_controls(self):
        for method in METHODS:
            for summary in ('checked_ok', 'checked_problem', 'not_applicable'):
                with self.subTest(method=method, summary=summary):
                    case = self.opened(method)
                    case.doc['checks'].update({k: summary for k in refs.KINDS})
                    attach_checks(case, case.doc)
                    case.doc['adjudication'] = dict(adjudication_ref='adj-performed', resolved_at=case.doc['verified_at'],
                        resolution='Attributed performed assessment retained.')
                    self.store(case)
                    self.promote(case, True)
                    self.doCleanups()

    def test_claim_owned_gates(self):
        for field, value in (('use', 'sampled'), ('verdict', 'partially_supports'),
                ('required_access_tier', 'bibliographic'), ('access_tier', 'bibliographic')):
            case = self.opened()
            self.store(case)
            with history(case, unchecked=True):
                case.x('UPDATE verification_receipts SET ' + field + '=?', value)
            self.promote(case)
            self.doCleanups()

    def test_no_receipt_pooling(self):
        for method in METHODS:
            case = self.opened(method)
            for i, missing in enumerate(('negation', 'qualifications')):
                doc = copy.deepcopy(case.doc)
                doc['verification_receipt_id'] += str(i)
                doc['detailed_checks'][missing].pop('record_id')
                original, case.doc = case.doc, doc
                self.store(case)
                case.doc = original
            self.promote(case)
            self.doCleanups()

    def test_stored_operands(self):
        case = self.opened()
        self.store(case)
        row = case.store.select('verification_receipts')[0]
        foreign_topic = case.value('SELECT topic_id FROM queue_entries WHERE topic_id<>? LIMIT 1', case.doc['topic_id'])
        for column, value in (('topic_id', foreign_topic), ('verifier_invocation_id', case.producer['invocation_id']),
                ('cited_spans', json.dumps([*case.doc['cited_spans'], case.doc['cited_spans'][0]]))):
            with self.subTest(column=column):
                with history(case, unchecked=True):
                    case.x('UPDATE verification_receipts SET ' + column + '=?', value)
                # Isolate detailed-column consumption from the newer basis gate.
                with patch.object(case.router._detailed_checks, '_has_basis', return_value=True):
                    self.promote(case)
                with history(case, unchecked=True):
                    value = canonical.canonical_bytes(row[column]).decode() if column == 'cited_spans' else row[column]
                    case.x('UPDATE verification_receipts SET ' + column + '=?', value)

    def test_non_load_bearing_control(self):
        case = self.opened()
        with history(case):
            case.x("UPDATE claims SET load_bearing=0,required_access_tier=NULL WHERE claim_id='clm_loadbear1'")
        self.promote(case, True)

    def test_replay_conflict_rollback(self):
        case = self.opened('validated_extraction')
        self.store(case)
        before = case.state(exclude=())
        case.faults['in_transaction:end'] = RuntimeError('after detailed promotion')
        with self.assertRaisesRegex(RuntimeError, 'after detailed promotion'):
            self.promote(case, True)
        self.assertEqual(case.state(exclude=()), before)
        case.faults.clear()
        out = self.promote(case, True)
        before = case.state(exclude=())
        self.assertEqual(case.router.commit_outcome(case.promotion_env), dict(status='replayed', receipt=out['receipt']))
        self.assertEqual(case.state(exclude=()), before)
        other = case.envelope(case.producer, 'op_promote_details', empty_outcome(case.producer['invocation_id'], 'interim_transition'))
        self.assertEqual(case.router.commit_outcome(other)['reason'], 'operation_id_conflict')
