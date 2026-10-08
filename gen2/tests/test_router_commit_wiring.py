"""The Router's commit transaction and the three helpers split out of `_commit_in_transaction` that write (task 2q-b11, Astra's 2q-b3b ruling 4): what the exact replay cannot settle. Independent of the replay.

Rollback (the three tests named ..._whichever_write_is_refused): a commit that goes through one of the helpers (`_write_topic_and_artifacts`, `_write_operation_receipt`, `_write_final_effects`)
is run with the store refusing its first write, then its second, and so on up to its last (test_router_evidence_wiring.Rollback): every refusal is `payload_invalid` ("the store refused the
write"), every table but the audit log is as it was, the audit log gains one `commit_rejected` event, and the run allowed every write records the helper's rows. Each test also states the
tables the whole commit writes, in order, and reads its helper's place in them off the statements of the helper, so a refused write is placed in the helper that makes it. So the helpers run
in the transaction `_commit_in_transaction` holds, as the blocks they came from did.

Oracles: expected values and write orders by hand; the store read back with raw SQL. Limits: the refusing store is a double that refuses by position, not by the DDL's own guards; the helpers that
only read (the three fences, the effects, the triggers and outbox, the receipt) have no writes to refuse: their refusals are test_router_commit's and test_router_workflow's, through
`assertRejected`; the post-lock clock read is `_guarded`'s, which this change does not touch.
"""
from __future__ import annotations

from gen2.tests import test_router_evidence_wiring as wiring
from gen2.tests.router_fixtures import TOPIC, empty_outcome


class CommitRollback(wiring.Rollback):
    def interim(self) -> dict:  # a research pass of a queued topic, running: a claim captured under it is an interim transition
        self.to_queued()
        return self.started("inv_research01")

    def final(self) -> tuple[dict, dict]:  # an approved contract's research pass whose result is staged: the commit is repeatable, as a refused commit changes nothing
        self.approved()
        grant = self.started("inv_research01")
        env = self.envelope(grant, "op_final000001", empty_outcome("inv_research01"))
        self.ready(grant, env["payload_digest"])
        env["expected_state_revision"] = self.state_revision()
        return grant, env


class TopicAndArtifactsTest(CommitRollback):
    def test_the_topic_move_and_the_artifacts_are_written_whichever_write_is_refused(self) -> None:  # _write_topic_and_artifacts
        grant = self.interim()
        revision = self.state_revision()
        tables = self.whichever_write_is_refused(lambda: self.capture(grant, "op_capture0001"), "artifacts")
        self.assertEqual(tables[:5], ["queue_entries", "artifacts", "artifact_topics", "artifacts", "artifact_topics"])  # the topic, then the payload's and the claim text's rows, each authorized for the topic
        self.assertEqual(self.state_revision(), revision + 1)
        self.assertEqual(self.rows("SELECT count(*), min(topic_id), max(topic_id), min(staged_by_invocation_id), max(staged_by_invocation_id) FROM artifacts"), [(2, TOPIC, TOPIC, "inv_research01", "inv_research01")])
        self.assertEqual(self.rows("SELECT count(*), min(topic_id), max(topic_id), min(recorded_by_invocation_id), max(recorded_by_invocation_id) FROM artifact_topics"), [(2, TOPIC, TOPIC, "inv_research01", "inv_research01")])


class OperationReceiptTest(CommitRollback):
    def test_the_operation_receipt_is_written_whichever_write_is_refused(self) -> None:  # _write_operation_receipt
        grant = self.interim()
        revision = self.state_revision()
        tables = self.whichever_write_is_refused(lambda: self.capture(grant, "op_capture0001"), "operation_receipts")
        self.assertEqual(tables[5], "operation_receipts")  # after the topic and the four artifact writes, before the claim the evidence writer records
        self.assertEqual(tables[6:], ["claims", "audit_events"])
        self.assertEqual(self.rows("SELECT operation_id, operation_kind, invocation_id, topic_id, lease_id, lease_generation, state_revision_before, state_revision_after FROM operation_receipts"),
                         [("op_capture0001", "interim_transition", "inv_research01", TOPIC, grant["lease"]["lease_id"], grant["lease"]["generation"], revision, revision + 1)])
        self.assertEqual(self.value("SELECT json_extract(receipt, '$.receipt_id') = receipt_id AND json_extract(receipt, '$.state_revision_after') = state_revision_after FROM operation_receipts"), 1)


class FinalEffectsTest(CommitRollback):
    def test_the_final_effects_are_written_whichever_write_is_refused(self) -> None:  # _write_final_effects
        grant, env = self.final()
        tables = self.whichever_write_is_refused(lambda: self.router.commit_outcome(env), "invocations")
        self.assertEqual(tables, ["queue_entries", "artifacts", "artifact_topics", "operation_receipts",   # _write_topic_and_artifacts, _write_operation_receipt
                                  "research_ordinals", "leases", "invocations", "invocation_transitions",  # _write_final_effects: the ordinal, the lease released, the invocation committed and its transition
                                  "audit_events"])                                                          # no evidence rows: the outcome is empty
        self.assertEqual(self.rows("SELECT topic_id, ordinal, invocation_id, operation_id FROM research_ordinals"), [(TOPIC, 1, "inv_research01", "op_final000001")])
        self.assertEqual(self.rows("SELECT released_at IS NOT NULL, release_reason FROM leases WHERE lease_id = ?", grant["lease"]["lease_id"]), [(1, "final_outcome")])
        self.assertEqual(self.rows("SELECT state FROM invocations WHERE invocation_id = 'inv_research01'"), [("committed",)])
        self.assertEqual(self.rows("SELECT from_state, to_state, cause FROM invocation_transitions WHERE invocation_id = 'inv_research01' ORDER BY seq DESC LIMIT 1"), [("result_ready", "committed", "commit_outcome")])
        committed_at = self.value("SELECT committed_at FROM operation_receipts WHERE operation_id = 'op_final000001'")  # one instant, read once the write lock is held, for every row of the commit
        self.assertEqual(self.rows("SELECT state_changed_at FROM invocations WHERE invocation_id = 'inv_research01' UNION ALL SELECT released_at FROM leases WHERE lease_id = ? UNION ALL "
                                   "SELECT at FROM invocation_transitions WHERE invocation_id = 'inv_research01' AND to_state = 'committed'", grant["lease"]["lease_id"]), [(committed_at,)] * 3)
