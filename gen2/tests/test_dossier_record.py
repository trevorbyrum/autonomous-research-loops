"""The real fenced writer preserves B2/B5 operands without granting gate proof."""
import inspect
from dataclasses import replace

from gen2 import accounting as a
from gen2.accounting import dossier, stopping as s
from gen2.core import canonical
from gen2.router.accounting import Accounting
from gen2.router.boundary import Refusal
from gen2.router.service import Router
from gen2.store.capture import input_hash
from gen2.tests import router_fixtures as rf
from gen2.tests.test_coverage_dependencies import history, page
from gen2.tests.test_dossier_codec import admitted
ITEMS = s.KnownItems(a.EvidenceReference('sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 10, 'application/json'), frozenset({'w1'}))


def evaluate(inputs):
    revision = inputs.coverage.inventory.current_contract_revision
    context = s.Context(inputs.raw.topic_id, revision, 1)
    rule = s.known_item(context, 'R', inputs.coverage.inventory, ITEMS)
    return s.evaluate_profile(context, s.Profile('P', s.Expression('R'), ()), (rule,), ())


class DossierCase(rf.ContractWorld):
    def setUp(self):
        rf.DurableRouterTestCase.setUp(self)
        self.build_world()
        self.grant = self.started('inv_dossier0001')

    tearDown = rf.DurableRouterTestCase.tearDown

    def record(self, callback=evaluate, *, refuses=False):
        kwargs = dict(invocation_id=self.grant['invocation_id'], history='native', evaluate=callback)
        if refuses:
            try:
                return self.router.record_dossier(rf.TOPIC, **kwargs)
            except Refusal:
                raise
            except Exception as exc:
                self.fail(f"refusal witness raised {type(exc).__name__}: {exc}")
        return admitted(self, self.router.record_dossier, rf.TOPIC, **kwargs)

    def stored(self, revision=1):
        return self.store.select('dossiers', {'topic_id': rf.TOPIC, 'dossier_revision': revision})[0]


class RecordTest(DossierCase):
    def test_attribution_hash_row_agreement_and_exact_effects(self):
        before = self.state(exclude=())
        out = self.record()
        row = self.stored()
        doc = row['document']
        self.assertEqual(row['content_hash'], canonical.content_hash(doc))
        self.assertEqual(out, {'status': 'recorded', 'dossier_revision': 1, 'content_hash': canonical.content_hash(doc)})
        self.assertEqual((doc['schema_version'], doc['evaluator_version'], doc['history']), ('dossier/2', 'stopping-result/1', 'native'))
        self.assertEqual((row['topic_id'], row['contract_revision']), (doc['result']['context']['topic_id'], doc['result']['context']['contract_revision']))
        for field in ('dossier_revision', 'evaluator_version', 'invocation_id'):
            self.assertEqual(row[field], doc[field])
        self.assertEqual(row['invocation_id'], 'inv_dossier0001')
        self.assertRegex(row['created_at'], r'^2026-09-27T10:00:00[.]\d+Z$')
        after = self.state(exclude=())
        self.assertEqual(len(after.pop('dossiers')), len(before.pop('dossiers')) + 1)
        self.assertEqual(len(after.pop('audit_events')), len(before.pop('audit_events')) + 1)
        self.assert_generation_delta(before, after, 1)
        self.assertEqual(after, before)
        self.assertEqual(self.record()['dossier_revision'], 2)
        self.x("INSERT INTO dossiers SELECT topic_id,5,contract_revision,evaluator_version,?,document,invocation_id,created_at FROM dossiers WHERE dossier_revision=1", rf.h('e'))
        self.assertEqual(self.record()['dossier_revision'], 6)

    def test_outer_topic_contract_and_protocol_binding(self):
        for changes, reason in (({'topic_id': 'fleet-a:t0'}, 'cross_topic'), ({'topic_id': rf.OTHER}, 'cross_topic'), ({'contract_revision': 1}, 'stale_inputs'),
                ({'contract_revision': 3}, 'stale_inputs'), ({'protocol_revision': 0}, 'stale_inputs'), ({'protocol_revision': 2}, 'stale_inputs')):
            before = self.state(exclude=())
            with self.assertRaises(Refusal) as caught:
                self.record(lambda inputs: replace(evaluate(inputs), context=replace(evaluate(inputs).context, **changes)), refuses=True)
            self.assertEqual(caught.exception.reason, reason)
            self.assert_audited_state(before, 1)
        self.assertEqual(self.record()['status'], 'recorded')
        self.to_queued(rf.OTHER)
        other = self.started('inv_other00001', tid=rf.OTHER)['invocation_id']
        for topic, iid in ((rf.TOPIC, 'inv_missing000'), (rf.TOPIC, other), (rf.OTHER, self.grant['invocation_id'])):
            before = self.state(exclude=())
            with self.assertRaises(Refusal) as caught:
                self.router.record_dossier(topic, invocation_id=iid, history='native', evaluate=evaluate)
            self.assertEqual(caught.exception.reason, 'unknown_invocation')
            self.assertEqual(self.state(exclude=()), before)

    def test_cancel_during_preparation_refuses_current_authority(self):
        def cancel(inputs):
            self.assertEqual(self.router.request_cancel({'invocation_id': self.grant['invocation_id'], 'reason': 'test', 'requested_by': 'operator'})['status'], 'recorded')
            return evaluate(inputs)
        with self.assertRaises(Refusal) as caught:
            self.record(cancel, refuses=True)
        self.assertEqual(caught.exception.reason, 'cancel_requested')
        self.assertEqual(self.store.select('dossiers'), [])
        self.assertEqual(self.value('SELECT count(*) FROM operation_receipts'), 0)
        self.assertEqual(self.value("SELECT json_extract(detail,'$.recaptures') FROM audit_events WHERE kind='dossier_input_recaptures'"), 0)

    def test_unrelated_write_recaptures_to_revision_one(self):
        self.recapture(False, 1)

    def test_competing_write_recaptures_to_revision_two(self):
        self.recapture(True, 2)

    def recapture(self, compete, expected):
        prepared = []
        def race(inputs):
            prepared.append(inputs.input_hash)
            if len(prepared) == 1:
                if compete:
                    self.record()
                else:
                    with self.store.transaction():
                        self.store.update('queue_entries', {'topic_id': rf.TOPIC}, {'priority': 7})
            return evaluate(inputs)
        out = self.record(race)
        self.assertEqual(out['dossier_revision'], expected)
        self.assertEqual(len(prepared), 2)
        self.assertNotEqual(*prepared)
        doc = self.stored(out['dossier_revision'])['document']
        self.assertEqual(doc['input_hash'], prepared[1])
        self.assertEqual(out['content_hash'], canonical.content_hash(doc))
        self.assertEqual(self.rows("SELECT json_extract(detail,'$.recaptures') FROM audit_events WHERE kind='dossier_input_recaptures' ORDER BY rowid DESC LIMIT 1"), [(1,)])

    def test_capture_omits_only_body_and_keeps_digest_metadata(self):
        self.record()
        raw = self.store.capture_topic(rf.TOPIC)
        for table in raw.tables:
            if table.name in ('dossiers',):
                self.assertEqual(table.columns, ('topic_id', 'dossier_revision', 'contract_revision', 'evaluator_version', 'content_hash', 'invocation_id', 'created_at'))
                self.assertEqual(table.json_columns, ())
                for column in ('content_hash', 'invocation_id', 'dossier_revision'):
                    changed = replace(table, rows=(tuple('changed' if c == column else v for c, v in zip(table.columns, table.rows[0])),))
                    self.assertNotEqual(input_hash(raw, 'native'), input_hash(replace(raw, tables=tuple(changed if t.name == table.name else t for t in raw.tables)), 'native'))
            else:
                self.assertEqual(table.columns, tuple(c[1] for c in self.rows(f'PRAGMA table_info({table.name})')))
                self.assertEqual(table.json_columns, tuple(sorted(self.store._json[table.name])))

    def test_current_invocation_is_checked_inside_writer_fence(self):
        def cancel(inputs):
            self.x("UPDATE invocations SET cancel_requested_at=?,cancel_requested_by='operator' WHERE invocation_id=?", rf.STAMP, self.grant['invocation_id'])
            return evaluate(inputs)
        before = self.state(exclude=())
        with self.assertRaises(Refusal) as caught:
            self.record(cancel, refuses=True)
        self.assertEqual(caught.exception.reason, 'cancel_requested')
        self.assertEqual(self.store.select('dossiers'), [])
        self.assertEqual(self.value('SELECT count(*) FROM operation_receipts'), 0)

    def test_positive_protocol_older_equal_newer(self):
        self.assertEqual(self.approve(self.propose(3, rf.protocol_changed))['status'], 'applied')
        self.grant = self.started('inv_protocol0001', 'checkpoint')
        for protocol, expected in ((1, 'stale_inputs'), (3, 'stale_inputs'), (2, 'recorded')):
            callback = lambda inputs: replace(evaluate(inputs), context=s.Context(rf.TOPIC, 3, protocol))
            if protocol == 2:
                self.assertEqual(self.record(callback)['status'], expected)
            else:
                with self.assertRaises(Refusal) as caught:
                    self.record(callback, refuses=True)
                self.assertEqual(caught.exception.reason, expected)

    def test_literal_route_and_collaborator_signatures(self):
        self.assertEqual(str(inspect.signature(Router.record_dossier)), "(self, topic_id: 'str', *, invocation_id: 'str', history: 'accounting.History', evaluate: 'Callable') -> 'dict'")
        self.assertEqual(str(inspect.signature(Accounting.prepare_dossier)), "(self, inputs: 'DossierInput', invocation_id: str, history: Literal['native', 'legacy_unknown'], evaluate: Callable) -> dict")
        self.assertEqual(str(inspect.signature(Accounting.write_dossier)), '(self, prepared: dict, now: str) -> dict')


class DebtCases(DossierCase):
    # This class adds persisted debt cases, without inheriting the route matrix.
    def test_satisfied_bound_retains_indeterminate_capture(self):
        inv = history(('p1', 'p0'), (page('p1', 'q'),))
        self.persist_coverage(inv, None, ('satisfied', 1, 2))

    def test_conservative_unknown_retains_out_of_scope_and_stale_capture(self):
        inv = history(('p0', 'p1'), (page('p1', 'q'),))
        self.persist_coverage(inv, frozenset({'p1'}), ('unknown', 0, 1))
        impact = a.AmendmentImpact('amendment', 1, (a.RevisionStanding(3, 'protocol_changed'),), (), rf.STAMP)
        self.persist_coverage(replace(inv, amendment_impacts=(impact,)), None, ('unknown', 0, 1), stale=True)

    def persist_coverage(self, inv, scope, expected, stale=False):
        inv = replace(inv, current_contract_revision=2)
        pins = (s.WindowPin('p0', 3 if stale else 2), s.WindowPin('p1', 2))
        def callback(inputs):
            ctx = s.Context(rf.TOPIC, 2, 1)
            rule = s.coverage(ctx, 'R', inv, pins, 1, scope=scope)
            return s.evaluate_profile(ctx, s.Profile('P', s.Expression('R'), ()), (rule,), ())
        out = self.record(callback)
        doc = self.stored(out['dossier_revision'])['document']
        result = admitted(self, dossier.decode, doc['result'])
        operand = result.rules[0].operands
        self.assertEqual((result.state, operand.lower, operand.upper), expected)
        self.assertEqual(operand.scope, scope)
        raw = next(w for w in operand.raw_windows if w.invocation_id == 'p0')
        self.assertEqual(raw, s.WindowOperand('p0', 3 if stale else 2, 'stale' if stale else 'current', 'indeterminate', 'invocation capture missing: p0'))
        self.assertEqual(doc['result']['rules'][0]['operands']['raw_windows'][0 if scope is not None or stale else 1],
            {'invocation_id': 'p0', 'contract_revision': 3 if stale else 2, 'standing': 'stale' if stale else 'current', 'state': 'indeterminate', 'reason': 'invocation capture missing: p0'})
        if stale:
            self.assertEqual(operand.windows[0].state, 'ineligible')

    def test_dropped_original_and_compatible_result_keep_provenance(self):
        def callback(inputs):
            ctx = s.Context(rf.TOPIC, 2, 1)
            rule = s.known_item(s.Context(rf.TOPIC, 1, 1), 'prior', inputs.coverage.inventory, ITEMS)
            old = replace(rule, rule_id='stale', context=replace(rule.context, contract_revision=3))
            inv = replace(inputs.coverage.inventory, amendment_impacts=(a.AmendmentImpact('amendment', 2,
                (a.RevisionStanding(1, 'compatible'), a.RevisionStanding(3, 'protocol_changed')), (), rf.STAMP),))
            return s.evaluate_profile(ctx, s.Profile('P', s.Expression(op='all', operands=(s.Expression('prior'), s.Expression('stale'))), ()), (rule, old), (), inventory=inv)
        self.record(callback)
        doc = self.stored()['document']
        result = admitted(self, dossier.decode, doc['result'])
        self.assertEqual((result.state, tuple(r.rule_id for r in result.rules), tuple(r.rule_id for r in result.dropped)), ('unknown', ('prior',), ('stale',)))
        self.assertEqual(s.expression_state(s.Expression('stale'), {r.rule_id: r.state for r in result.rules}), 'unknown')
        self.assertEqual(result.dropped[0].context, s.Context(rf.TOPIC, 3, 1))
        self.assertEqual(result.rules[0].context, s.Context(rf.TOPIC, 1, 1))
        self.assertEqual(doc['result']['dropped'][0]['operands'], {'declared': {'reference': {'content_hash': 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'size_bytes': 10, 'media_type': 'application/json'}, 'work_ids': ['w1']}, 'retrieved': {'known_ids': [], 'unknown_reason': 'invocation capture missing'}, 'found': [], 'missing': ['w1']})
