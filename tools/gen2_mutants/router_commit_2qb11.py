"""Mutants of task 2q-b11: Router._commit_in_transaction split into nine private helpers by extract-method. The rules the split added are the helper boundaries: that each is called, what each returns,
the order of the writes, and that a write the store refuses still reaches `_guarded`. Each is broken alone at the call; the tests that kill them are the existing commit, evidence and fencing tests and
gen2/tests/test_router_commit_wiring.py, and the tests that do not reach the changed line are their controls (by hand: nothing here was traced).

  2QB11-fence-state-not-called                  the current-state fence is not called (the lease and the admission are still taken), so a stale state revision commits;
  2QB11-fence-kind-not-called                   the outcome-kind fence is not called, so a second final outcome is not refused as one;
  2QB11-fence-kind-given-the-opposite-kind      the outcome-kind fence is told a final outcome is interim, so a final commit is refused;
  2QB11-fence-changes-not-called                the since-validation fence is not called, so bytes recorded meanwhile with another size are not refused there;
  2QB11-effects-ordinal-dropped                 `_decide_effects` returns no ordinal to the receipt and the write, so a research pass earns none;
  2QB11-effects-lease-release-dropped           the lease release `_decide_effects` returns is dropped, so the final outcome leaves its lease live;
  2QB11-effects-queue-transition-dropped        the queue transition it returns is dropped, so a research pass that proposes its topic's next state leaves it where it was;
  2QB11-triggers-already-recorded-dropped       the identities `_decide_triggers_and_outbox` returns in `triggers` are the new ones only, so the audit event lists no trigger as already recorded;
  2QB11-topic-write-not-called                  `_write_topic_and_artifacts` is not called;
  2QB11-receipt-write-not-called                `_write_operation_receipt` is not called;
  2QB11-final-effects-write-not-called          `_write_final_effects` is not called;
  2QB11-final-effects-before-the-receipt        the final effects are written before the operation receipt, whose operation the ordinal row names;
  2QB11-topic-write-refusal-swallowed           the call of `_write_topic_and_artifacts` drops the refusal of a write the store makes, so the commit goes on;
  2QB11-receipt-write-refusal-swallowed         the same for `_write_operation_receipt`;
  2QB11-final-effects-refusal-swallowed         the same for `_write_final_effects`.
"""
from __future__ import annotations

from .base import RC, RE, SVC, Mutation

WF, WIRING = "test_router_workflow.", "test_router_commit_wiring."
FENCE, ATOMIC, TRIGGER = RC + "FencingTest.", RC + "AtomicityTest.", RE + "TriggerAndOrdinalTest."
STATE, KIND, CHANGES = FENCE + "test_a_wrong_expected_revision_is_refused", FENCE + "test_one_final_outcome_per_invocation", RC + "BoundaryValidationTest.test_an_artifact_recorded_meanwhile_is_held_to_what_was_validated"
POSITIVE, RELEASED = FENCE + "test_positive_control", RC + "ReplayAndIdentityTest.test_a_retained_receipt_authorizes_nothing_after_its_lease_ends"
ORDINAL, QUEUE, ALREADY = TRIGGER + "test_only_contract_research_passes_earn_ordinals", ATOMIC + "test_a_fault_at_each_point_leaves_nothing_or_everything", TRIGGER + "test_a_replayed_trigger_opens_nothing_new"
TOPIC_TEST, RECEIPT_TEST, EFFECTS_TEST = (WIRING + f"{cls}.test_{what}_written_whichever_write_is_refused" for cls, what in (
    ("TopicAndArtifactsTest", "the_topic_move_and_the_artifacts_are"), ("OperationReceiptTest", "the_operation_receipt_is"), ("FinalEffectsTest", "the_final_effects_are")))
STATE_CALL = "        lease, admission = self._fence_against_current_state(inv, now, env, topic)\n"
KIND_CALL = "        self._fence_outcome_kind(final, inv, env)\n"
CHANGES_CALL = "        self._fence_changes_since_validation(checked, payload)\n"
EFFECTS_CALL = "        ordinal, queue_transition, lease_release = self._decide_effects(final, inv, topic, payload, lease)\n"
TRIGGERS_CALL = "        new_triggers, outbox, triggers = self._decide_triggers_and_outbox(inv, payload, checked)\n"
TOPIC_CALL = "        self._write_topic_and_artifacts(topic, now, queue_transition, checked, inv)\n"
RECEIPT_CALL = "        self._write_operation_receipt(env, receipt_id, inv, fingerprint, lease_id, lease, topic, after, checked, receipt, now)\n"
FINAL_CALL = "        self._write_final_effects(ordinal, inv, env, lease_release, lease_id, now, final)\n"
FAULT_RECEIPT = '        self._fault("in_transaction:receipt")\n'


def swallowed(call: str) -> str:
    return "        try:\n    " + call + "        except api.StoreWriteError:\n            pass\n"


def mutant(name: str, description: str, killer: str, old: str, new: str, *also: tuple[str, str]) -> Mutation:
    return Mutation(f"2QB11-{name}", "2q-b11", description, (killer,), target=SVC, old=old, new=new, also=also)


MUTATIONS: list[Mutation] = [
    mutant("fence-state-not-called", "`_commit_in_transaction` does not call the current-state fence", STATE, STATE_CALL,
           '        lease, admission = self._require_current_lease(inv, now, env["lease"]), self._admission_json(inv)\n'),
    mutant("fence-kind-not-called", "`_commit_in_transaction` does not call the outcome-kind fence", KIND, KIND_CALL, ""),
    mutant("fence-kind-given-the-opposite-kind", "the outcome-kind fence is told a final outcome is interim", POSITIVE, KIND_CALL, KIND_CALL.replace("(final,", "(not final,")),
    mutant("fence-changes-not-called", "`_commit_in_transaction` does not call the since-validation fence", CHANGES, CHANGES_CALL, ""),
    mutant("effects-ordinal-dropped", "the ordinal `_decide_effects` returns is dropped", ORDINAL, EFFECTS_CALL,
           "        _, queue_transition, lease_release = self._decide_effects(final, inv, topic, payload, lease)\n        ordinal = None\n"),
    mutant("effects-lease-release-dropped", "the lease release `_decide_effects` returns is dropped", RELEASED, EFFECTS_CALL,
           "        ordinal, queue_transition, _ = self._decide_effects(final, inv, topic, payload, lease)\n        lease_release = None\n"),
    mutant("effects-queue-transition-dropped", "the queue transition `_decide_effects` returns is dropped", QUEUE, EFFECTS_CALL,
           "        ordinal, _, lease_release = self._decide_effects(final, inv, topic, payload, lease)\n        queue_transition = None\n"),
    mutant("triggers-already-recorded-dropped", "`triggers` is the new triggers only, so none is reported as already recorded", ALREADY, TRIGGERS_CALL,
           "        new_triggers, outbox, _ = self._decide_triggers_and_outbox(inv, payload, checked)\n        triggers = new_triggers\n"),
    mutant("topic-write-not-called", "`_commit_in_transaction` does not call `_write_topic_and_artifacts`", TOPIC_TEST, TOPIC_CALL, ""),
    mutant("receipt-write-not-called", "`_commit_in_transaction` does not call `_write_operation_receipt`", RECEIPT_TEST, RECEIPT_CALL, ""),
    mutant("final-effects-write-not-called", "`_commit_in_transaction` does not call `_write_final_effects`", EFFECTS_TEST, FINAL_CALL, ""),
    mutant("final-effects-before-the-receipt", "`_write_final_effects` runs before `_write_operation_receipt`", EFFECTS_TEST, RECEIPT_CALL + FAULT_RECEIPT + FINAL_CALL, FINAL_CALL + FAULT_RECEIPT + RECEIPT_CALL),
    mutant("topic-write-refusal-swallowed", "the call of `_write_topic_and_artifacts` drops the refusal of a write", TOPIC_TEST, TOPIC_CALL, swallowed(TOPIC_CALL)),
    mutant("receipt-write-refusal-swallowed", "the call of `_write_operation_receipt` drops the refusal of a write", RECEIPT_TEST, RECEIPT_CALL, swallowed(RECEIPT_CALL)),
    mutant("final-effects-refusal-swallowed", "the call of `_write_final_effects` drops the refusal of a write", EFFECTS_TEST, FINAL_CALL, swallowed(FINAL_CALL)),
]
