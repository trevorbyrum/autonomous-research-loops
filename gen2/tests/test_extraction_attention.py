"""SQL 34 basis membership controls attention, without clearing prior holds."""
import json
import unittest

from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.test_bound_extraction_support import PromotionCases
from gen2.tests.test_pending_extraction_support import METHODS
from gen2.tests.test_validated_extraction_receipts import ValidatedCases
from gen2.tests.independent_tier_fixtures import independent_basis
from gen2.tests.detailed_receipt_fixtures import attach_checks


class ExtractionAttentionTest(unittest.TestCase):
    RAW = False
    context = PromotionCases.context
    clone = PromotionCases.clone
    store = PromotionCases.store

    def effects(self, out, expected):
        c = self.case
        self.assertEqual(out['status'], 'committed', out)
        self.assertEqual(out['receipt']['effects']['holds_created'], expected)
        audit = json.loads(c.value('SELECT detail FROM audit_events WHERE audit_event_id=?',
            out['receipt']['effects']['audit_event_id']))
        self.assertEqual(audit['verification_holds'], expected)
        stored = json.loads(c.value('SELECT receipt FROM operation_receipts WHERE operation_id=?', c.env['operation_id']))
        self.assertEqual(stored, out['receipt'])

    def test_bound_control(self):
        for method in METHODS:
            for tier in ('bibliographic', 'abstract', 'full_text'):
                with self.subTest(method=method, tier=tier):
                    self.context(method, tier)
                    self.effects(self.case.send(self.doc), [])
                    self.assertEqual(self.case.rows('SELECT * FROM holds'), [])
                    self.assertTrue(self.case.store.bound_extraction_receipt(self.doc['verification_receipt_id']))
                    self.assertFalse(self.case.store.bound_extraction_receipt('absent'))

    def test_canonical_control(self):
        self.context('canonical_bytes')
        self.effects(self.case.send(self.doc), [])
        self.assertEqual(self.case.rows('SELECT * FROM holds'), [])

    def test_missing_content(self):
        for method in METHODS:
            with self.subTest(method=method):
                self.context(method)
                self.doc.update(access_tier='abstract', verdict='cannot_assess_at_required_tier')
                self.doc['checks'].update(numeric_units='not_checked', denominators='unavailable',
                    negation='not_checked', qualifications='unavailable')
                attach_checks(self.case, self.doc)
                out = self.case.send(self.doc)
                self.assertTrue(self.case.store.bound_extraction_receipt(self.doc['verification_receipt_id']))
                ids = [r[0] for r in self.case.rows('SELECT hold_id FROM holds')]
                self.assertEqual(len(ids), 1)
                self.effects(out, ids)
                self.assertEqual(self.case.rows('SELECT cause, recoverability, owner, deadline_at, clears_when FROM holds'),
                    [('verification missing content: cannot_assess_at_required_tier', 'needs_remediation',
                      'primary:station-1', self.case.value("SELECT deadline_at FROM invocations WHERE invocation_id='inv_capture001'"),
                      'independent verification with the required content')])

    def test_disagreement_preserved(self):
        for method in METHODS:
            for verdict in ('does_not_support', 'partially_supports'):
                with self.subTest(method=method, verdict=verdict):
                    self.context(method)
                    self.doc['verdict'] = verdict
                    out = self.case.send(self.doc)
                    held = self.case.rows('SELECT * FROM holds')
                    self.assertEqual(len(held), 1)
                    self.effects(out, [held[0][0]])
                    self.assertEqual(self.case.rows('SELECT cause, recoverability FROM holds'),
                        [('verification disagreement: ' + verdict, 'needs_decision')])
                    self.doc.update(verdict='supports', verification_receipt_id='ver_later001')
                    self.effects(self.case.send(self.doc, op='op_later001'), [])
                    self.assertEqual(self.case.rows('SELECT * FROM holds'), held)

    def historical_hold(self):
        self.store(legacy=True)
        c = self.case
        self.assertFalse(c.store.bound_extraction_receipt(self.doc['verification_receipt_id']))
        payload = dict(verification_receipts=[self.doc])
        op = c.value('SELECT recorded_by_operation_id FROM source_extractions LIMIT 1')
        with c.store.transaction():
            written = c.router._verification.write_holds(payload, op, self.doc['verified_at'])
        ids = [r[0] for r in c.rows('SELECT hold_id FROM holds')]
        self.assertEqual(len(ids), 1)
        self.assertEqual(written, dict(verification_holds=ids))
        self.assertEqual(c.router._verification.hold_ids(payload), ids)
        self.assertEqual(c.rows('SELECT cause, recoverability, cleared_at FROM holds'),
            [('verification missing content: extraction evidence not durably bound', 'needs_remediation', None)])

    def test_fenced(self):
        for method in METHODS:
            kinds = ('missing', 'invented', 'free_text', 'unpinned', 'foreign', 'tier')
            if method == 'validated_extraction':
                kinds += ('legacy', 'failed', 'integrity', 'independent_tier')
            for kind in kinds:
                with self.subTest(method=method, kind=kind):
                    self.context(method)
                    if kind in ('missing', 'invented', 'free_text'):
                        key = 'extraction_id' if method == 'verifier_extraction' else 'validation_ref'
                        if kind == 'missing' and method == 'verifier_extraction':
                            self.doc['extraction'].pop(key)
                        else:
                            self.doc['extraction'][key] = kind
                    elif kind in ('legacy', 'failed', 'integrity'):
                        helper = type('Helper', (), dict(case=self.case, doc=self.doc, target=self.target,
                            independent=self.independent, clone=self.clone, refuse=lambda _: None))()
                        getattr(ValidatedCases, 'test_' + kind)(helper)
                    elif kind == 'foreign':
                        self.doc['extraction']['extractor'] = 'different-tool'
                    elif kind == 'independent_tier':
                        independent_basis(self.case, self.doc, 'abstract')
                    else:
                        basis = self.target if method == 'validated_extraction' else self.doc['extraction']['extraction_id']
                        self.case.x('DROP TRIGGER source_extractions_immutable_u')
                        column, value = ('extractor_registry_version', None) if kind == 'unpinned' else ('supported_tier', 'abstract')
                        self.case.x('UPDATE source_extractions SET ' + column + '=? WHERE extraction_id=?', value, basis)
                    self.historical_hold()
                    held = self.case.rows('SELECT * FROM holds')
                    # A later valid basis adds no hold and clears no earlier one.
                    self.doc.update(verification_receipt_id='ver_canonical1')
                    self.doc['extraction'] = dict(method='canonical_bytes', extractor='canonical/1',
                        produced_by_invocation_id=self.case.ACQUIRER, validation_ref=None)
                    attach_checks(self.case, self.doc)
                    self.effects(self.case.send(self.doc), [])
                    self.assertEqual(self.case.rows('SELECT * FROM holds'), held)

    def test_same_outcome_control(self):
        for method in METHODS:
            with self.subTest(method=method):
                self.context(method)
                c = self.case
                basis = c.store.select('source_extractions', {'extraction_id': self.independent})[0]
                record = {k: v for k, v in basis.items() if k not in
                    ('topic_id', 'extracting_invocation_id', 'recorded_by_operation_id', 'created_at')}
                record['extraction_id'] = 'same-outcome-extraction'
                payload = {**empty_outcome(c.verifier['invocation_id'], 'interim_transition'),
                    'source_extractions': [record], 'verification_receipts': [self.doc]}
                if method == 'verifier_extraction':
                    self.doc['extraction']['extraction_id'] = record['extraction_id']
                else:
                    validation = c.store.select('extraction_validations_v2')[0]
                    validation = {k: v for k, v in validation.items() if k not in
                        ('validator_invocation_id', 'recorded_by_operation_id', 'created_at')}
                    validation.update(validation_id='same-outcome-validation', validator_extraction_id=record['extraction_id'])
                    payload['extraction_validations_v2'] = [validation]
                    self.doc['extraction']['validation_ref'] = validation['validation_id']
                c.env = c.envelope(c.verifier, 'op_same00001', payload, refs=[record['output_ref']])
                self.assertFalse(c.store.bound_extraction_receipt(self.doc['verification_receipt_id']))
                self.effects(c.router.commit_outcome(c.env), [])
                self.assertTrue(c.store.bound_extraction_receipt(self.doc['verification_receipt_id']))
                self.assertEqual(c.rows('SELECT * FROM holds'), [])

    def test_fenced_with_bound_distractor(self):
        self.context('verifier_extraction')
        self.doc['verification_receipt_id'] = 'ver_bound0001'
        self.effects(self.case.send(self.doc), [])
        self.doc['verification_receipt_id'] = 'ver_unbound01'
        self.doc['extraction'].pop('extraction_id')
        self.historical_hold()

    def test_historical_hold_rollback(self):
        self.context('verifier_extraction')
        self.doc['extraction'].pop('extraction_id')
        self.store(legacy=True)
        before = self.case.state(exclude=())
        op = self.case.value('SELECT recorded_by_operation_id FROM source_extractions LIMIT 1')
        with self.assertRaisesRegex(RuntimeError, 'after historical hold'):
            with self.case.store.transaction():
                self.case.router._verification.write_holds(dict(verification_receipts=[self.doc]), op, self.doc['verified_at'])
                self.assertEqual(len(self.case.rows('SELECT * FROM holds')), 1)
                raise RuntimeError('after historical hold')
        self.assertEqual(self.case.state(exclude=()), before)

    def test_replay_conflict_rollback(self):
        for method in METHODS:
            for missing in (False, True):
                with self.subTest(method=method, missing=missing):
                    self.context(method)
                    if missing:
                        self.doc.update(access_tier='abstract', verdict='cannot_assess_at_required_tier')
                    before = self.case.state(exclude=())
                    self.case.faults['in_transaction:end'] = RuntimeError('after extraction attention')
                    with self.assertRaisesRegex(RuntimeError, 'after extraction attention'):
                        self.case.send(self.doc)
                    self.assertEqual(self.case.state(exclude=()), before)
                    self.case.faults.clear()
                    out = self.case.send(self.doc)
                    ids = [r[0] for r in self.case.rows('SELECT hold_id FROM holds')]
                    self.assertEqual(len(ids), int(missing))
                    self.effects(out, ids)
                    before = self.case.state(exclude=())
                    self.assertEqual(self.case.router.commit_outcome(self.case.env), dict(status='replayed', receipt=out['receipt']))
                    self.assertEqual(self.case.state(exclude=()), before)
                    self.doc['verification_receipt_id'] = 'ver_conflict1'
                    self.assertEqual(self.case.send(self.doc)['reason'], 'operation_id_conflict')
                    self.assertEqual(self.case.state(), {k: v for k, v in before.items() if k != 'audit_events'})

    def test_invalid_new_basis_rolls_back(self):
        for method in METHODS:
            with self.subTest(method=method):
                self.context(method)
                self.doc['extraction'].update(extraction_id='invented', validation_ref='invented')
                before = self.case.state()
                out = self.case.send(self.doc)
                self.assertEqual(out['status'], 'rejected', out)
                self.assertEqual(self.case.state(), before)
                self.assertEqual(self.case.rows('SELECT * FROM holds'), [])
