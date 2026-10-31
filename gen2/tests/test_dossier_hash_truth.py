"""Document truth and decision-subject binding are separate equalities (G-8/13)."""
from gen2.tests import router_fixtures as rf
from gen2.tests.test_dossier_record import FixtureEvaluator, admitted


class HashTruthTest(FixtureEvaluator, rf.ContractWorld):
    def test_untrue_and_wrong_subject_hash_refuse_truthful_control_completes(self):
        self.started('inv_dossier0001')
        out = admitted(self, self.router.record_dossier, rf.TOPIC, invocation_id='inv_dossier0001', history='native')
        for revision, digest, reason in ((1, rf.h('f'), 'decision_refused'), (2, rf.h('e'), 'subject_hash_untrue')):
            if revision == 2:
                self.x('INSERT INTO dossiers SELECT topic_id,2,contract_revision,evaluator_version,?,document,invocation_id,created_at FROM dossiers WHERE dossier_revision=1', rf.h('e'))
            before = self.state(exclude=())
            rejected = self.decide('opd_dossier001', 'completion_approval', {'kind': 'dossier', 'revision': revision, 'hash': digest})
            self.assertEqual((rejected['status'], rejected['reason']), ('rejected', reason))
            self.assertEqual(self.state(exclude=()), before)
        # The newest raw-integrity row is deliberately untrue; bind the first
        # truthful document again at a new revision through the real writer.
        last = admitted(self, self.router.record_dossier, rf.TOPIC, invocation_id='inv_dossier0001', history='native')
        self.assertEqual(last['dossier_revision'], 3)
        accepted = self.decide('opd_dossier001', 'completion_approval', {'kind': 'dossier', 'revision': 3, 'hash': last['content_hash']})
        self.assertEqual(accepted['status'], 'applied')
        self.assertEqual(accepted['effects']['queue_transition'], {'from': 'active', 'to': 'completed_with_qualified_conclusions'})
        self.assertEqual(self.decide('opd_dossier001', 'completion_approval', {'kind': 'dossier', 'revision': 3, 'hash': last['content_hash']})['status'], 'replayed')
