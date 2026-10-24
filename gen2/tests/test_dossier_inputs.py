"""Lossless internal inputs; pure stopping evaluators retain uncertainty and G-1."""
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch
from gen2.accounting import stopping as s
from gen2.router.accounting import records
from gen2.router.boundary import Refusal
from gen2.store.capture import input_hash
from gen2.tests.router_fixtures import TOPIC, RouterTestCase, find_request
from gen2.tests import test_accounting as at
from gen2.tests.test_router_amendments import ContractWorld, reframed
from gen2.tests.test_verification_attention import AttentionCase
from gen2.tests.test_branch_windows import World


class RefusalTest(RouterTestCase):
    def test_requires_approved_contract(self):
        before = self.state(exclude=())
        for history in ('native', 'legacy_unknown'):
            with self.assertRaises(Refusal) as refused:
                self.router._dossier_inputs(TOPIC, history=history)
            self.assertEqual(refused.exception.reason, 'no_approved_contract')
            with self.assertRaises(Refusal) as unknown:
                self.router._dossier_inputs('topic_unknown01', history=history)
            self.assertEqual(unknown.exception.reason, 'unknown_topic')
            self.assertIsNone(self.router.evidence_inventory(TOPIC, history=history).current_contract_revision)
        with self.assertRaises(ValueError):
            self.router._dossier_inputs(TOPIC, history='invented')
        self.assertEqual(self.state(exclude=()), before)


class AdapterTest(ContractWorld):
    page = at.WindowTest.page
    scope = frozenset({'inv_dossier0001', 'inv_dossier0002'})

    def window(self, inv, observe):
        grant = self.started(inv)
        if observe:
            self.page(grant, 'obs_dossier001', find_request('complete search'))
        self.assertEqual(self.finish(grant, 'op_' + inv[4:])['status'], 'committed')

    def inputs(self):
        return self.router._dossier_inputs(TOPIC, history='native')

    def bound(self, inputs, minimum):
        snap = inputs.coverage
        return s.coverage(s.Context(TOPIC, 2, 1), 'R', snap.inventory, snap.window_pins, minimum, scope=self.scope)

    def test_control_route(self):
        value = self.inputs()
        self.assertEqual((value.raw.topic_id, value.coverage.inventory.current_contract_revision), (TOPIC, 2))
        self.assertEqual(value.input_hash, input_hash(value.raw, 'native'))
        with self.assertRaises(FrozenInstanceError):
            value.input_hash = 'changed'

    def test_unattributed_contract_refuses(self):
        raw = self.store.capture_topic(TOPIC)
        raw = replace(raw, tables=tuple(replace(t, rows=tuple(tuple(None if c == 'approved_by_decision_id' else v
            for c, v in zip(t.columns, row)) for row in t.rows)) if t.name == 'contract_revisions' else t for t in raw.tables))
        with patch.object(self.store, 'capture_topic', return_value=raw):
            with self.assertRaises(Refusal) as refused:
                self.inputs()
        self.assertEqual(refused.exception.reason, 'no_approved_contract')

    def test_satisfied_and_unknown_bounds_retain_indeterminate(self):
        self.window('inv_dossier0001', True)
        self.window('inv_dossier0002', False)
        before = self.state(exclude=())
        self.router._clock = lambda: self.fail('input read used clock')
        value = self.inputs()
        for minimum, state in ((1, 'satisfied'), (2, 'unknown')):
            result = self.bound(value, minimum)
            self.assertEqual((result.state, result.operands.lower, result.operands.upper), (state, 1, 2))
            window = next(w for w in result.operands.windows if w.invocation_id == 'inv_dossier0002')
            self.assertEqual((window.state, window.contract_revision, window.standing), ('indeterminate', 2, 'current'))
        self.assertEqual(len(tuple(records(value.raw, 'search_observations'))), 1)
        self.assertEqual({r['invocation_id'] for r in records(value.raw, 'invocations')} & self.scope, self.scope)
        self.assertEqual(self.state(exclude=()), before)

    def test_stale_g1_has_no_current_credit_but_retains_records(self):
        self.window('inv_dossier0001', True)
        first = self.inputs()
        result = self.bound(first, 1)
        self.assertEqual(result.state, 'satisfied')
        self.assertEqual(self.approve(self.propose(3, reframed), 'reframe_approval')['status'], 'applied')
        current = self.inputs()
        inventory = current.coverage.inventory
        old = next(r for r in records(current.raw, 'contract_revisions') if r['revision'] == 2)
        self.assertEqual(old['status'], 'superseded')
        self.assertEqual(tuple(records(first.raw, 'search_observations')), tuple(records(current.raw, 'search_observations')))
        self.assertEqual(current.coverage.window_pins, first.coverage.window_pins)
        profile = s.evaluate_profile(s.Context(TOPIC, 3, 1), s.Profile('P', s.Expression('R'), ()), (result,), (), inventory=inventory)
        self.assertEqual((profile.state, profile.rules), ('unknown', ()))
        self.assertEqual(s.label_standing(inventory, 2), 'stale')


class HistoryTest(AttentionCase):
    def test_adverse_then_support_and_attention_retained(self):
        self.retained('does_not_support')

    def test_partial_then_support_and_attention_retained(self):
        self.retained('partially_supports')

    def retained(self, adverse):
        self.attention(adverse)
        self.commit({**self.document('supports'), 'verification_receipt_id': 'ver_support001'})
        before = self.state(exclude=())
        native = self.router._dossier_inputs(TOPIC, history='native')
        legacy = self.router._dossier_inputs(TOPIC, history='legacy_unknown')
        self.assertEqual([r['verdict'] for r in records(native.raw, 'verification_receipts')], [adverse, 'supports'])
        holds = next(t.rows for t in native.raw.tables if t.name == 'holds')
        self.assertEqual(holds, tuple(self.rows('SELECT * FROM holds ORDER BY rowid')))
        self.assertEqual(len(holds), 1)
        self.assertEqual(native.raw, legacy.raw)
        self.assertEqual(legacy.coverage.inventory.history, 'legacy_unknown')
        self.assertNotEqual(native.input_hash, legacy.input_hash)
        self.assertEqual(native.input_hash, input_hash(native.raw, 'native'))
        self.assertEqual(self.state(exclude=()), before)


class BranchTest(World):
    def test_branch_provenance_retained(self):
        self.assertEqual(self.send([self.record()])['status'], 'committed')
        value = self.router._dossier_inputs(TOPIC, history='native')
        self.assertEqual([(l.registry_id, l.invocation_id) for l in value.coverage.branch_links], [('B-1', 'inv_window0001')])
        self.assertEqual([(r['registry_id'], r['window_invocation_id']) for r in records(value.raw, 'branch_windows')], [('B-1', 'inv_window0001')])
