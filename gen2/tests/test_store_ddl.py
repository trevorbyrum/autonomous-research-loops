"""Constraint tests for the gen-2 store DDL draft (gen2/store/schema.sql).

Trace: task 0a deliverable 3 ("Uniqueness/fencing constraints expressed in
DDL where SQLite allows"); invariant IDs refer to docs/gen2/INVARIANTS.md.

What these tests show: the named constraint or trigger rejects the stated
row. Where a test also shows the same write minus the violation being
accepted, that control rules out an unrelated failure (such as a missing
foreign key); the few tests without such a control say so. Every
connection applies gen2/store/connection.sql (store_fixtures.connect). What
they cannot show: that the router uses these tables correctly, that crash recovery or
replay behave (RG-1a/RG-1b need Phase 1 fault-injection tests against the
router), or anything about concurrency. They test the draft schema only.
"""
from __future__ import annotations

import json
import sqlite3
import unittest

from gen2.tests.store_fixtures import OTHER, TOPIC, StoreTestCase, T, facet, h, obligation


class LeaseFencingTest(StoreTestCase):
    def test_one_live_lease_per_topic_and_scope_until_released(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.lease("lease_vvvvvvvv", 2, scope="verification")  # another scope is independent
        self.rejects("UNIQUE constraint failed: leases.topic_id, leases.scope",
                     "INSERT INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES ('lease_bbbbbbbb', ?, 'research', 3, 'st2', ?, ?)", TOPIC, T, T)
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.lease("lease_bbbbbbbb", 3)

    def test_generation_strictly_increases_per_topic(self) -> None:
        self.lease("lease_aaaaaaaa", 5)
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)  # generations are per topic
        self.rejects("lease generation must exceed", "INSERT INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES ('lease_bbbbbbbb', ?, 'research', 5, 'st1', ?, ?)", TOPIC, T, T)
        self.rejects("lease generation must exceed", "INSERT INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES ('lease_bbbbbbbb', ?, 'research', 4, 'st1', ?, ?)", TOPIC, T, T)
        self.lease("lease_bbbbbbbb", 6)

    def test_release_is_write_once(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.x("UPDATE leases SET expires_at = '2026-09-25T13:00:00Z' WHERE lease_id = 'lease_aaaaaaaa'")  # renewal allowed while live
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.rejects("a released lease is final", "UPDATE leases SET released_at = NULL, release_reason = NULL WHERE lease_id = 'lease_aaaaaaaa'")
        self.rejects("a released lease is final", "UPDATE leases SET release_reason = 'again' WHERE lease_id = 'lease_aaaaaaaa'")


class InvocationLifecycleTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)

    def test_invocations_start_admitted(self) -> None:
        self.rejects("invocations are created admitted", *self.raw_invocation(invocation_id="inv_pppppppp", state="committed", launch_intent_at=T, job_handle="job-1",
                                                                              result_payload_digest=h("d"), result_staged_at=T))
        self.invocation("inv_pppppppp")

    def test_full_chain_allowed_but_skips_rejected(self) -> None:
        self.invocation("inv_pppppppp")
        self.rejects("invocation state transition not allowed", "UPDATE invocations SET state = 'committed', launch_intent_at = ?, result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_pppppppp'", T, h("d"), T)
        self.to_running("inv_pppppppp")
        self.x("UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_pppppppp'", h("d"), T)
        self.x("UPDATE invocations SET state = 'committed' WHERE invocation_id = 'inv_pppppppp'")

    def test_terminal_states_are_final(self) -> None:
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.x("UPDATE invocations SET state = 'failed' WHERE invocation_id = 'inv_pppppppp'")
        self.rejects("invocation state transition not allowed", "UPDATE invocations SET state = 'running' WHERE invocation_id = 'inv_pppppppp'")

    def test_outcome_unknown_is_reconciled_not_skipped(self) -> None:
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.rejects("CHECK constraint failed", "UPDATE invocations SET state = 'outcome_unknown' WHERE invocation_id = 'inv_pppppppp'")
        self.x("UPDATE invocations SET state = 'outcome_unknown', outcome_unknown_since = ? WHERE invocation_id = 'inv_pppppppp'", T)
        self.x("UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_pppppppp'", h("d"), T)

    def test_running_requires_process_identity_not_a_pid(self) -> None:
        self.invocation("inv_pppppppp")
        self.x("UPDATE invocations SET state = 'launching', launch_intent_at = ? WHERE invocation_id = 'inv_pppppppp'", T)
        self.rejects("CHECK constraint failed", "UPDATE invocations SET state = 'running', job_handle = 'job-1', host_id = 'dev' WHERE invocation_id = 'inv_pppppppp'")
        self.x("UPDATE invocations SET state = 'running', job_handle = 'job-1', host_id = 'dev', boot_id = 'b1', start_fingerprint = 'st=1' WHERE invocation_id = 'inv_pppppppp'")
        columns = {row[1] for row in self.x("PRAGMA table_info(invocations)")}
        self.assertNotIn("pid", columns)

    def test_launching_requires_launch_intent(self) -> None:
        self.invocation("inv_pppppppp")
        self.rejects("CHECK constraint failed", "UPDATE invocations SET state = 'launching' WHERE invocation_id = 'inv_pppppppp'")
        self.x("UPDATE invocations SET state = 'launching', launch_intent_at = ? WHERE invocation_id = 'inv_pppppppp'", T)

    def test_process_identity_is_write_once(self) -> None:
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.rejects("write-once", "UPDATE invocations SET boot_id = 'b2' WHERE invocation_id = 'inv_pppppppp'")
        self.rejects("write-once", "UPDATE invocations SET kind = 'verification' WHERE invocation_id = 'inv_pppppppp'")

    def test_delegate_names_its_parent(self) -> None:
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.rejects("a delegate runs under", *self.raw_invocation(invocation_id="inv_dddddddd", kind="delegate", lease_id=None))
        self.invocation("inv_dddddddd", kind="delegate", lease=None, parent="inv_pppppppp")

    def test_delegate_inherits_a_running_parent_of_its_topic(self) -> None:
        """R2.1/R2.2: a delegate runs under a launching/running non-delegate parent
        of its topic, with the parent's admission pins and no lease of its own."""
        rev = self.approved_revision(TOPIC)
        self.invocation("inv_pppppppp")
        refused = "a delegate runs under"
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_d0000001", kind="delegate", lease_id=None, parent_invocation_id="inv_pppppppp", contract_revision=rev))  # parent not started
        self.to_running("inv_pppppppp")
        self.rejects("CHECK constraint failed", *self.raw_invocation(invocation_id="inv_d0000001", kind="delegate", lease_id="lease_aaaaaaaa", parent_invocation_id="inv_pppppppp", contract_revision=rev))  # own lease
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.to_running("inv_oooooooo")
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_d0000001", kind="delegate", lease_id=None, parent_invocation_id="inv_oooooooo", contract_revision=rev))  # other topic's parent
        # different pins: revision 2 is approved by amendment after the parent was admitted under revision 1
        self.contract(TOPIC, 2)
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.approve_contract(TOPIC, 2, kind="amendment_approval")
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_d0000001", kind="delegate", lease_id=None, parent_invocation_id="inv_pppppppp", contract_revision=2))
        self.invocation("inv_d0000001", kind="delegate", lease=None, parent="inv_pppppppp")
        self.to_running("inv_d0000001")
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_d0000002", kind="delegate", lease_id=None, parent_invocation_id="inv_d0000001", contract_revision=rev))  # no delegate chains

    def test_capability_is_unique_per_invocation(self) -> None:
        self.invocation("inv_pppppppp")
        self.lease("lease_dddddddd", 2, scope="discovery")
        self.rejects("UNIQUE constraint failed: invocations.capability_id", *self.raw_invocation(invocation_id="inv_vvvvvvvv", kind="discovery", lease_id="lease_dddddddd", capability_id="cap_pppppppp"))


class CommitFencingTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")

    def test_operation_id_reuse_rejected_and_receipts_immutable(self) -> None:
        self.receipt("op_00000001", "inv_pppppppp")
        stored = self.snapshot("operation_receipts")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp", before=1, kind="interim_transition", rid="rcpt_distinct1")
        self.assertIn("UNIQUE constraint failed: operation_receipts.operation_id", str(ctx.exception))
        self.rejects("operation receipts are immutable", "UPDATE operation_receipts SET payload_digest = ? WHERE operation_id = 'op_00000001'", h("0"))
        self.rejects("never deleted", "DELETE FROM operation_receipts WHERE operation_id = 'op_00000001'")
        # REPLACE on the primary key and on the alternate receipt_id key (A1);
        # every key is attacked in test_store_history.py.
        replace = ("INSERT OR REPLACE INTO operation_receipts SELECT ?, ?, operation_kind, invocation_id, topic_id, ?, ?, lease_id, lease_generation, admission_context, contract_revision, brief_hash, config_bundle_hash, state_revision_before + ?, state_revision_after + ?, validator_version, policy_version, "
                   "json_set(receipt, '$.operation_id', ?, '$.receipt_id', ?, '$.payload_digest', ?), committed_at FROM operation_receipts WHERE operation_id = 'op_00000001'")
        self.rejects("replay protection depends on them", replace, "op_00000001", "rcpt_00000001", h("9"), h("0"), 0, 0, "op_00000001", "rcpt_00000001", h("0"))
        self.rejects("replay protection depends on them", replace, "op_00000002", "rcpt_00000001", h("9"), h("0"), 5, 5, "op_00000002", "rcpt_00000001", h("0"))
        self.assertEqual(self.snapshot("operation_receipts"), stored)

    def test_one_final_outcome_per_invocation(self) -> None:
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition", before=0)
        self.receipt("op_00000002", "inv_pppppppp", kind="interim_transition", before=1)
        self.receipt("op_00000003", "inv_pppppppp", kind="final_outcome", before=2)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000004", "inv_pppppppp", kind="final_outcome", before=3)
        self.assertIn("UNIQUE constraint failed: operation_receipts.invocation_id", str(ctx.exception))

    def test_one_commit_per_state_revision(self) -> None:
        self.lease("lease_dddddddd", 2, scope="discovery")
        self.invocation("inv_qqqqqqqq", kind="discovery", lease="lease_dddddddd")
        self.receipt("op_00000001", "inv_pppppppp", before=4)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000002", "inv_qqqqqqqq", lease="lease_dddddddd", gen=2, before=4)
        self.assertIn("UNIQUE constraint failed: operation_receipts.topic_id, operation_receipts.state_revision_after", str(ctx.exception))

    def test_stale_generation_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp", gen=0)
        self.assertIn("stale generation", str(ctx.exception))
        self.receipt("op_00000001", "inv_pppppppp", gen=1)

    def test_released_lease_cannot_commit(self) -> None:
        self.x("UPDATE leases SET released_at = ?, release_reason = 'expired' WHERE lease_id = 'lease_aaaaaaaa'", T)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp")
        self.assertIn("released lease", str(ctx.exception))

    def test_cross_topic_commit_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp", tid=OTHER)
        self.assertIn("cross-topic", str(ctx.exception))

    def test_commit_under_another_invocations_lease_rejected(self) -> None:
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp", lease="lease_vvvvvvvv", gen=2)
        self.assertIn("foreign lease", str(ctx.exception))

    def test_delegate_commits_under_parent_lease(self) -> None:
        self.to_running("inv_pppppppp")
        self.invocation("inv_dddddddd", kind="delegate", lease=None, parent="inv_pppppppp")
        self.receipt("op_00000001", "inv_dddddddd")

    def test_state_revision_advances_by_exactly_one(self) -> None:
        self.x("UPDATE queue_entries SET state_revision = 1 WHERE topic_id = ?", TOPIC)
        self.rejects("advances by exactly one", "UPDATE queue_entries SET state_revision = 3 WHERE topic_id = ?", TOPIC)
        self.rejects("advances by exactly one", "UPDATE queue_entries SET state_revision = 0 WHERE topic_id = ?", TOPIC)


class OrdinalAndTriggerTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_cccccccc", 2, scope="checkpoint")
        self.invocation("inv_kkkkkkkk", kind="checkpoint", lease="lease_cccccccc")

    def test_only_research_pass_final_outcomes_get_ordinals(self) -> None:
        self.receipt("op_00000001", "inv_kkkkkkkk", lease="lease_cccccccc", gen=2, before=0)
        self.rejects("ordinals go only to", "INSERT INTO research_ordinals VALUES (?, 1, 'inv_kkkkkkkk', 'op_00000001')", TOPIC)
        self.receipt("op_00000002", "inv_pppppppp", kind="interim_transition", before=1)
        self.rejects("ordinals go only to", "INSERT INTO research_ordinals VALUES (?, 1, 'inv_pppppppp', 'op_00000002')", TOPIC)
        self.receipt("op_00000003", "inv_pppppppp", before=2)
        self.x("INSERT INTO research_ordinals VALUES (?, 1, 'inv_pppppppp', 'op_00000003')", TOPIC)

    def test_ordinals_dense_and_once_per_invocation(self) -> None:
        self.receipt("op_00000001", "inv_pppppppp", before=0)
        self.rejects("densely", "INSERT INTO research_ordinals VALUES (?, 2, 'inv_pppppppp', 'op_00000001')", TOPIC)
        self.x("INSERT INTO research_ordinals VALUES (?, 1, 'inv_pppppppp', 'op_00000001')", TOPIC)
        self.rejects("UNIQUE constraint failed", "INSERT INTO research_ordinals VALUES (?, 2, 'inv_pppppppp', 'op_00000001')", TOPIC)

    def test_trigger_identity_unique_and_handled_is_final(self) -> None:
        insert = "INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at) VALUES (?, ?, 'persistent_contradiction', 'deterministic', 'CL-3', ?)"
        self.x(insert, h("1"), TOPIC, T)
        self.rejects("UNIQUE constraint failed: review_triggers.trigger_identity", insert, h("1"), TOPIC, T)
        self.receipt("op_00000009", "inv_pppppppp", kind="interim_transition", before=0)
        self.receipt("op_00000010", "inv_pppppppp", kind="interim_transition", before=1)
        self.x("INSERT INTO review_episodes (episode_id, topic_id, kind, opened_at, opened_by_operation_id) VALUES ('ep-1', ?, 'method_fit', ?, 'op_00000009')", TOPIC, T)
        self.x("UPDATE review_triggers SET episode_id = 'ep-1', handled_at = ? WHERE trigger_identity = ?", T, h("1"))
        self.x("UPDATE review_episodes SET closed_at = ?, closed_by_operation_id = 'op_00000010' WHERE episode_id = 'ep-1'", T)
        self.rejects("a handled trigger stays handled", "UPDATE review_triggers SET handled_at = NULL WHERE trigger_identity = ?", h("1"))
        self.rejects("never deleted", "DELETE FROM review_triggers WHERE trigger_identity = ?", h("1"))
        # A1 / RG-1b(e): replaying the trigger unhandled after its episode closed,
        # through REPLACE, cannot reopen it; read back the stored row.
        self.rejects("never deleted", insert.replace("INSERT", "INSERT OR REPLACE"), h("1"), TOPIC, T)
        self.assertEqual(self.rows("SELECT episode_id, handled_at FROM review_triggers WHERE trigger_identity = ?", h("1")), [("ep-1", T)])


class VerificationTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        self.invocation("inv_vvvvvvvv", kind="verification", lease="lease_vvvvvvvv")
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'text/plain', ?)", h("7"), T)
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000001', 1, ?, ?, 'inv_pppppppp', 1, 'full_text', 'provisional', ?)", TOPIC, h("7"), T)

    VER = ("INSERT INTO verification_receipts (verification_receipt_id, topic_id, claim_id, claim_revision, work_id, source_version, cited_spans, obtained_content_hash, access_tier, use, required_access_tier, acquisition, extraction_method, extraction_invocation_id, extraction_validation_ref, producer_invocation_id, verifier_invocation_id, verdict, receipt, verified_at) "
           "VALUES (?, ?, 'clm_00000001', 1, 'wrk_00000001', 'v1', '[{\"start\":0,\"end\":5}]', ?, ?, 'load_bearing', ?, '{}', ?, ?, ?, ?, ?, ?, '{}', ?)")

    def verify(self, rid: str, *, tier: str = "full_text", required: str = "full_text", method: str = "verifier_extraction", extraction: str = "inv_vvvvvvvv",
               validation: str | None = None, producer: str = "inv_pppppppp", verifier: str = "inv_vvvvvvvv", verdict: str = "supports") -> None:
        self.x(self.VER, rid, TOPIC, h("2"), tier, required, method, extraction, validation, producer, verifier, verdict, T)

    def test_requested_by_is_same_topic_and_never_self(self) -> None:
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_vvvvvvvv'", T)
        self.lease("lease_wwwwwwww", 4, scope="verification")
        self.rejects("same topic", *self.raw_invocation(invocation_id="inv_reqdver1", kind="verification", lease_id="lease_wwwwwwww", requested_by_invocation_id="inv_oooooooo"))
        self.rejects("same topic", *self.raw_invocation(invocation_id="inv_reqdver1", kind="verification", lease_id="lease_wwwwwwww", requested_by_invocation_id="inv_reqdver1"))
        self.invocation("inv_reqdver1", kind="verification", lease="lease_wwwwwwww", requested_by="inv_pppppppp")

    def test_producer_cannot_verify_itself(self) -> None:
        # Realistic case: the research-pass producer names itself as verifier (the role trigger fires first).
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", verifier="inv_pppppppp", extraction="inv_pppppppp", validation="val-1")
        self.assertIn("separate verification invocation", str(ctx.exception))
        # Isolate the producer != verifier CHECK: a claim whose producer is itself a
        # verification-kind invocation passes the role trigger, so only the CHECK can refuse it.
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000001', 2, ?, ?, 'inv_vvvvvvvv', 0, NULL, 'provisional', ?)", TOPIC, h("7"), T)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.x(self.VER.replace("'clm_00000001', 1,", "'clm_00000001', 2,"), "ver_00000002", TOPIC, h("2"), "full_text", "full_text", "validated_extraction", "inv_vvvvvvvv", "val-9", "inv_vvvvvvvv", "inv_vvvvvvvv", "supports", T)
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.verify("ver_00000001")

    def second_research_pass(self) -> None:
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.lease("lease_bbbbbbbb", 3)
        self.invocation("inv_qqqqqqqq", lease="lease_bbbbbbbb")

    def test_verifier_must_be_separate_verification_invocation(self) -> None:
        """D26 rewrite (ruling R2.2): keep the kind rule; replace blanket parent
        rejection with the control/causal distinction. A verifier can never have
        a controlling parent (so the producer cannot launch or control it); a
        verifier *requested by* the producing pass is legitimate."""
        self.second_research_pass()  # a second research_pass, not a verifier
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", verifier="inv_qqqqqqqq", extraction="inv_qqqqqqqq")
        self.assertIn("separate verification invocation", str(ctx.exception))
        # control parentage: refused when the verification invocation is admitted
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_vvvvvvvv'", T)
        self.lease("lease_wwwwwwww", 4, scope="verification")
        self.rejects("CHECK constraint failed", *self.raw_invocation(invocation_id="inv_childver", kind="verification", lease_id="lease_wwwwwwww", parent_invocation_id="inv_pppppppp"))
        # causal request by the producer: admitted, and its receipt is accepted
        self.invocation("inv_reqdver1", kind="verification", lease="lease_wwwwwwww", requested_by="inv_pppppppp")
        self.verify("ver_00000002", verifier="inv_reqdver1", extraction="inv_reqdver1")

    def test_receipt_must_name_the_claims_real_producer(self) -> None:
        self.second_research_pass()
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", producer="inv_qqqqqqqq")
        self.assertIn("independent of the claim producer", str(ctx.exception))

    def test_producer_unvalidated_extraction_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", method="canonical_bytes", extraction="inv_pppppppp")
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.verify("ver_00000001", method="validated_extraction", extraction="inv_pppppppp", validation="validation-7")

    def test_supports_cannot_exceed_obtained_tier(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", tier="abstract", required="full_text")
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.verify("ver_00000001", tier="abstract", required="full_text", verdict="cannot_assess_at_required_tier")

    def test_accepted_support_needs_receipt_at_required_tier(self) -> None:
        accept = "UPDATE claims SET status = 'accepted_support' WHERE claim_id = 'clm_00000001' AND revision = 1"
        self.rejects("needs a supporting verification receipt", accept)
        self.verify("ver_00000001", tier="abstract", required="abstract")  # supports, but only at abstract
        self.rejects("needs a supporting verification receipt", accept)
        self.verify("ver_00000002", tier="full_text", required="full_text")
        self.x(accept)

    def test_claims_start_provisional(self) -> None:
        self.rejects("claims are captured provisional", "INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000002', 1, ?, ?, 'inv_pppppppp', 0, NULL, 'accepted_support', ?)", TOPIC, h("7"), T)

    def test_nli_alarm_quarantines_the_quote(self) -> None:
        insert = "INSERT INTO quote_checks (check_id, claim_id, claim_revision, source_artifact_hash, span_start, span_end, normalization_version, exact_match, nli_checker, nli_checker_version, nli_signal, quote_quarantined, checked_at) VALUES (?, 'clm_00000001', 1, ?, 0, 5, 'n1', 'matched', 'minicheck', '1', 'alarm', ?, ?)"
        self.rejects("CHECK constraint failed", insert, "qc-1", h("7"), 0, T)
        self.x(insert, "qc-1", h("7"), 1, T)


class ObservationTest(StoreTestCase):
    INSERT = ("INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt, lane, request, obligation_ids, started_at, coverage_state, result_count, error_class, capability_fact_id, policy_version) "
              "VALUES (?, 'inv_pppppppp', ?, ?, 1, 'crossref', '{}', '[]', ?, ?, ?, ?, ?, 'pol1')")

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")

    def obs(self, oid: str, state: str, count, error=None, fact=None, ident: str = "1") -> None:
        self.x(self.INSERT, oid, TOPIC, h(ident), T, state, count, error, fact)

    def test_degraded_search_cannot_report_zero(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "provider_unavailable", 0, "provider_outage")
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "provider_unavailable", None, None)  # degraded needs an error class
        self.obs("o1", "provider_unavailable", None, "payload_invalid")
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o2", "unknown", 0, "telemetry_missing", ident="2")
        self.obs("o2", "unknown", None, "telemetry_missing", ident="2")

    def test_searched_empty_is_exactly_zero_and_searched_ok_has_results(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_empty", None)
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_ok", 0)
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_ok", None)
        self.obs("o1", "searched_empty", 0)
        self.obs("o2", "searched_ok", 3, ident="2")

    def test_secrets_failure_is_a_dated_capability_fact(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "auth_failed", None, "secrets_backend_failing")
        self.x("INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, recorded_at) VALUES ('cf-1', 'secrets_backend', 'failing', 'vault 403', '2026-09-21T19:47:00Z', '[\"semantic_scholar\"]', ?)", T)
        self.obs("o1", "auth_failed", None, "secrets_backend_failing", "cf-1")

    def test_one_current_capability_fact_supersede_to_transition(self) -> None:
        ins = "INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, recorded_at) VALUES (?, ?, ?, 'd', ?, '[]', ?)"
        current = "SELECT fact_id, state FROM capability_facts WHERE capability = 'secrets_backend' AND superseded_by_fact_id IS NULL"
        self.x(ins, "cf-1", "secrets_backend", "failing", T, T)
        self.rejects("UNIQUE constraint failed", ins, "cf-2", "secrets_backend", "healthy", T, T)  # a second current fact
        # A9: the documented supersession transaction, failure -> healthy, same capability
        self.x("BEGIN")
        self.x("UPDATE capability_facts SET superseded_by_fact_id = 'cf-2' WHERE fact_id = 'cf-1'")
        self.x(ins, "cf-2", "secrets_backend", "healthy", T, T)
        self.x("COMMIT")
        self.assertEqual(self.rows(current), [("cf-2", "healthy")])
        self.assertEqual(self.rows("SELECT state, superseded_by_fact_id FROM capability_facts WHERE fact_id = 'cf-1'"), [("failing", "cf-2")])  # retained
        self.rejects("supersede, never edit", "UPDATE capability_facts SET state = 'healthy' WHERE fact_id = 'cf-1'")
        self.rejects("supersede, never edit", "UPDATE capability_facts SET recorded_at = '2026-09-26T00:00:00Z' WHERE fact_id = 'cf-2'")
        # linking a successor that is never inserted fails at COMMIT; rollback leaves cf-2 current
        self.x("BEGIN")
        self.x("UPDATE capability_facts SET superseded_by_fact_id = 'cf-3' WHERE fact_id = 'cf-2'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("COMMIT")
        self.x("ROLLBACK")
        self.assertEqual(self.rows(current), [("cf-2", "healthy")])
        # cross-capability successor, in either order
        self.x("BEGIN")
        self.x("UPDATE capability_facts SET superseded_by_fact_id = 'cf-x' WHERE fact_id = 'cf-2'")
        self.rejects("same capability", ins, "cf-x", "gateway_budget", "failing", T, T)
        self.x("ROLLBACK")
        self.x(ins, "cf-y", "gateway_budget", "failing", T, T)
        self.rejects("same capability", "UPDATE capability_facts SET superseded_by_fact_id = 'cf-y' WHERE fact_id = 'cf-2'")
        # self and cyclic supersession; inserting an already-superseded fact
        self.rejects("CHECK constraint failed", "UPDATE capability_facts SET superseded_by_fact_id = 'cf-2' WHERE fact_id = 'cf-2'")
        self.rejects("must be current", "UPDATE capability_facts SET superseded_by_fact_id = 'cf-1' WHERE fact_id = 'cf-2'")
        self.rejects("inserted current", "INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, superseded_by_fact_id, recorded_at) VALUES ('cf-9', 'secrets_backend', 'failing', 'd', ?, '[]', 'cf-2', ?)", T, T)
        self.assertEqual(self.rows(current), [("cf-2", "healthy")])

    def test_retrieval_events_only_from_successful_searches(self) -> None:
        self.obs("o1", "provider_unavailable", None, "timeout")
        self.obs("o2", "searched_ok", 2, ident="2")
        ins = "INSERT INTO retrieval_events (event_id, observation_id, topic_id, provider_record_id, captured_at) VALUES (?, ?, ?, 'rec-1', ?)"
        self.rejects("successful searches", ins, "e1", "o1", TOPIC, T)
        self.rejects("successful searches", ins, "e1", "o2", OTHER, T)
        self.x(ins, "e1", "o2", TOPIC, T)


class ScreeningAndDecisionTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        self.jev = self.spec()

    SCREEN = ("INSERT INTO screening_assessments (assessment_id, topic_id, work_id, contract_revision, eligibility_protocol_version, framing_version, stage, decision, reason_code, criterion_results, actor_kind, invocation_id, decision_receipt_id, recorded_by_operation_id, created_at) "
              "VALUES (?, ?, 'wrk_00000001', 1, 1, 1, 'abstract', ?, ?, '{}', ?, 'inv_pppppppp', ?, 'op_00000001', ?)")

    def test_exclusion_requires_reason_code(self) -> None:
        self.rejects("CHECK constraint failed", self.SCREEN, "sa1", TOPIC, "exclude", None, "primary", None, T)
        self.x(self.SCREEN, "sa1", TOPIC, "exclude", "EC-outcome-not-met", "primary", None, T)
        self.rejects("never deleted", "DELETE FROM screening_assessments WHERE assessment_id = 'sa1'")

    def test_shadow_decision_provider_cannot_write_authoritative_screening(self) -> None:
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev)  # shadow
        self.rejects("never write authoritative screening", self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", "dec_00000001", T)
        self.decision_receipt("dec_00000002", "inv_pppppppp", self.jev, authority="qualified", qualification="qual-screen-1", action="commit_reversible_action", commit_op="op_00000001")
        self.x(self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", "dec_00000002", T)

    def test_fallback_label_cannot_carry_probability(self) -> None:
        fb = self.spec("dspec_screen02", provider="llm_fallback")
        label = {"primitive": "label", "selected_option_id": "include", "evidence_refs": ["r1"]}
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", fb, provider="llm_fallback", answer=dict(label, probability=0.9))
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", fb, provider="llm_fallback", answer=dict(label, primitive="choice", confidence=0.9))
        self.decision_receipt("dec_00000001", "inv_pppppppp", fb, provider="llm_fallback", answer=label)

    def test_missing_confidence_or_primitive_is_rejected_not_defaulted(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, answer={"primitive": "choice", "selected_option_id": "include", "distribution": {"include": 0.8, "exclude": 0.2}})
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, answer={"selected_option_id": "include", "confidence": 0.7})
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, answer={"primitive": "noul", "probability": 0.8, "confidence": 0.9})
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev)
        self.decision_receipt("dec_00000002", "inv_pppppppp", self.jev, answer={"primitive": "noul", "probability": 0.8})

    def test_unqualified_authority_is_capped(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="qualified", action="attach_proposal")
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="advisory", action="commit_reversible_action", commit_op="op_00000001")
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="shadow", action="attach_proposal")
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="advisory", action="attach_proposal")

    def test_receipt_provider_must_match_spec(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, provider="llm_fallback", answer={"primitive": "label", "selected_option_id": "x", "evidence_refs": ["r"]})
        self.assertIn("must match its spec", str(ctx.exception))


class HoldTest(StoreTestCase):
    INSERT = ("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, capability_fact_id, created_at) "
              "VALUES (?, ?, 'clm_00000001', ?, 'verifier disagreement', 'needs_decision', ?, ?, ?, ?, ?, ?)")

    def test_hold_needs_owner_deadline_and_clearing_condition(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(self.INSERT, "hold_00000001", TOPIC, "judgment", "primary", None, T, "adjudicated", None, T)
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(self.INSERT, "hold_00000001", TOPIC, "judgment", "primary", "primary", None, "adjudicated", None, T)
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(self.INSERT, "hold_00000001", TOPIC, "judgment", "primary", "primary", T, "", None, T)
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(self.INSERT, "hold_00000001", TOPIC, "capability", "router", "router", T, "vault healthy", None, T)
        self.x(self.INSERT, "hold_00000001", TOPIC, "judgment", "primary", "primary", T, "adjudicated", None, T)

    def test_operator_hold_cleared_only_by_operator_decision(self) -> None:
        """D45 rewrite (A2): only an approved hold_clearance about THIS hold clears
        it. Each near-miss differs from the valid decision in one dimension:
        disposition, subject (another hold of the same topic), or kind (a
        publication approval whose free-text subject ref names this hold). A
        decision's topic is fixed by its hold subject when it is recorded
        (test_decision_subject_must_exist_with_its_topic)."""
        self.x(self.INSERT, "hold_00000001", TOPIC, "scope", "operator", "operator", T, "operator rules on reframe", None, T)
        self.x(self.INSERT, "hold_00000002", TOPIC, "scope", "operator", "operator", T, "another hold", None, T)
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")
        clear = "UPDATE holds SET cleared_at = ?, cleared_by_decision_id = ? WHERE hold_id = 'hold_00000001'"
        self.rejects("CHECK constraint failed", "UPDATE holds SET cleared_at = ?, cleared_by_operation_id = 'op_00000001' WHERE hold_id = 'hold_00000001'", T)
        self.decision("opd_rejected", "hold_clearance", disposition="rejected", ref="hold_00000001")
        self.decision("opd_otherhld", "hold_clearance", ref="hold_00000002")
        self.decision("opd_wrongknd", "publication_approval", ref="hold_00000001", rev=1, hsh=h("5"))
        for did in ("opd_rejected", "opd_otherhld", "opd_wrongknd"):
            with self.subTest(decision=did):
                self.rejects("hold_clearance decision about this hold", clear, T, did)
        self.assertEqual(self.rows("SELECT cleared_at FROM holds WHERE hold_id = 'hold_00000001'"), [(None,)])
        self.decision("opd_00000001", "hold_clearance", ref="hold_00000001")
        self.rejects("hold_clearance decision about this hold", clear, T, "opd_rejected")  # a valid clearance exists, but is not the one named
        self.x(clear, T, "opd_00000001")
        self.rejects("a cleared hold is final", "UPDATE holds SET cleared_at = NULL, cleared_by_decision_id = NULL WHERE hold_id = 'hold_00000001'")

    def test_holds_are_created_open(self) -> None:
        self.rejects("created open", "INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, created_at, cleared_at, cleared_by_operation_id) "
                     "VALUES ('hold_00000001', ?, 'x', 'judgment', 'c', 'needs_decision', 'primary', 'primary', ?, 'adjudicated', ?, ?, 'op_00000001')", TOPIC, T, T, T)

    def test_decision_subject_must_exist_with_its_topic(self) -> None:
        self.x(self.INSERT, "hold_00000001", TOPIC, "scope", "operator", "operator", T, "c", None, T)
        ins = "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'trevor', ?)"
        self.rejects("existing subject", ins, "opd_x", TOPIC, "hold_clearance", "approved", "hold", "hold_nothere", None, None, T)
        self.rejects("existing subject", ins, "opd_x", OTHER, "hold_clearance", "approved", "hold", "hold_00000001", None, None, T)  # another topic's decision about this hold
        self.rejects("existing subject", ins, "opd_x", TOPIC, "blind_initial_disposition", "recorded", "decision_receipt", "dec_nothere", None, None, T)
        self.x(ins, "opd_x", TOPIC, "hold_clearance", "approved", "hold", "hold_00000001", None, None, T)
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.spec())
        self.x(ins, "opd_y", TOPIC, "blind_initial_disposition", "recorded", "decision_receipt", "dec_00000001", None, None, T)

    def test_decision_subject_shape(self) -> None:
        """A2: each decision kind admits one subject kind with its identifying fields."""
        ins = "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES ('opd_x', ?, ?, ?, ?, ?, ?, ?, 'trevor', ?)"
        ch = self.content_hash_of(TOPIC, 1)
        self.x(self.INSERT, "hold_00000001", TOPIC, "scope", "operator", "operator", T, "c", None, T)
        # (rows chosen so the subject-existence trigger, which fires first, passes)
        bad = (
            (TOPIC, "hold_clearance", "approved", "topic", TOPIC, 0, None),                 # kind admits only a hold subject
            (TOPIC, "retirement", "approved", "hold", "hold_00000001", None, None),         # and the reverse
            (TOPIC, "scope_approval", "approved", "scoping_report", "scope-1", None, ch),   # a versioned subject needs its revision
            (TOPIC, "contract_approval", "approved", "contract_revision", OTHER, 1, ch),     # contract subject is referenced by its own topic
            (TOPIC, "retirement", "approved", "topic", TOPIC, None, None),                  # topic subject needs the state revision decided against
            (None, "scope_approval", "approved", "scoping_report", "scope-1", 1, ch),       # only hold decisions may be topic-less
            (TOPIC, "retirement", "recorded", "topic", TOPIC, 0, None),                     # 'recorded' is only for blind/advised records
            (TOPIC, "publication_approval", "approved", "publication_source", "src-1", 1, None),  # a publication source needs its hash
        )
        for row in bad:
            with self.subTest(row=row):
                self.rejects("CHECK constraint failed", ins, *row, T)
        self.x(ins, TOPIC, "contract_approval", "approved", "contract_revision", TOPIC, 1, ch, T)


class PublicationTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")

    def test_only_approved_work_is_published(self) -> None:
        """D46 rewrite (A2): the approval must be an approved publication_approval
        of this topic about exactly the published source revision and hash. Each
        near-miss matches the published source in every dimension but one; the
        wrong-kind probe is the review's (an approved rating decision) with its
        subject revision/hash made to coincide with the source's."""
        src = h("5")
        rated = self.content_hash_of(TOPIC, 1)
        probes = (
            ("opd_rejected", dict(disposition="rejected", rev=3, hsh=src), 3, src),
            ("opd_wronghsh", dict(rev=3, hsh=h("4")), 3, src),
            ("opd_stalerev", dict(rev=2, hsh=src), 3, src),
            ("opd_othertop", dict(tid=OTHER, rev=3, hsh=src), 3, src),
        )
        for did, kwargs, rev, hsh in probes:
            self.decision(did, "publication_approval", **kwargs)
        self.decision("opd_rating01", "rating_approval", rev=1, hsh=rated)
        for did, rev, hsh in [(d, r, x) for d, _, r, x in probes] + [("opd_rating01", 1, rated)]:
            with self.subTest(decision=did):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000001", "man_00000001", 1, None, did, h("1"), source_rev=rev, source_hash=hsh)
                self.assertIn("unapproved work is never published", str(ctx.exception))
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=src)
        with self.assertRaises(sqlite3.IntegrityError):  # a valid approval exists, but is not the one named
            self.outbox("obx_00000001", "man_00000001", 1, None, "opd_rejected", h("1"), source_rev=3, source_hash=src)
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), source_rev=3, source_hash=src)

    def test_manifest_json_matches_its_columns(self) -> None:
        src = h("5")
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=src)
        for override in ({"source": {"revision": 3, "content_hash": h("4")}}, {"source": {"revision": 2, "content_hash": src}}, {"approval": {"operator_decision_id": "opd_other", "approved_revision": 3}},
                         {"approval": {"operator_decision_id": "opd_00000002", "approved_revision": 2}}, {"artifact_kind": "evidence_correction"},
                         {"expected_sinks": ["neo4j"]}, {"supersedes": {"manifest_id": "man_x", "generation": 1}}):
            with self.subTest(override=override):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), source_rev=3, source_hash=src, manifest_overrides=override)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), source_rev=3, source_hash=src)

    def test_generations_strictly_increase(self) -> None:
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.outbox("obx_00000001", "man_00000001", 2, 1, "opd_00000002", h("1"))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.outbox("obx_00000002", "man_00000002", 1, None, "opd_00000002", h("2"))
        self.assertIn("strictly increase", str(ctx.exception))
        self.outbox("obx_00000002", "man_00000002", 3, 2, "opd_00000002", h("2"))

    def test_delivery_receipt_only_for_expected_sinks(self) -> None:
        """D48 rewrite: membership, not vocabulary. The manifest expects only
        Neo4j; a receipt for Qdrant (a valid physical sink) is refused by the
        expected-sink trigger, and a Neo4j receipt is accepted."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), sinks=("neo4j",))
        ins = "INSERT INTO sink_delivery_receipts (delivery_receipt_id, outbox_event_id, sink, attempt, status, tombstones_acknowledged, error_class, attempted_at, acked_at) VALUES (?, 'obx_00000001', ?, 1, ?, ?, ?, ?, ?)"
        self.rejects("sink the manifest does not expect", ins, "d1", "qdrant", "delivered", 1, None, T, T)
        self.rejects("CHECK constraint failed", ins, "d1", "neo4j", "failed", 0, None, T, None)  # a failure needs its error class
        self.x(ins, "d1", "neo4j", "failed", 0, "timeout", T, None)
        self.x("INSERT INTO sink_delivery_receipts (delivery_receipt_id, outbox_event_id, sink, attempt, status, tombstones_acknowledged, error_class, attempted_at, acked_at) VALUES ('d2', 'obx_00000001', 'neo4j', 2, 'delivered', 1, NULL, ?, ?)", T, T)

    def test_sink_generation_never_regresses(self) -> None:
        self.x("INSERT INTO sink_generations VALUES (?, 'qdrant', 2, ?)", TOPIC, T)
        self.x("UPDATE sink_generations SET delivered_generation = 2, delivered_at = ? WHERE topic_id = ? AND sink = 'qdrant'", T, TOPIC)  # idempotent retry
        self.rejects("never overwrites a newer delivered generation", "UPDATE sink_generations SET delivered_generation = 1 WHERE topic_id = ? AND sink = 'qdrant'", TOPIC)
        # A1: the regression paths that bypass an UPDATE guard
        self.rejects("high-water mark is never deleted", "DELETE FROM sink_generations WHERE topic_id = ? AND sink = 'qdrant'", TOPIC)
        self.rejects("high-water mark is never deleted", "INSERT OR REPLACE INTO sink_generations VALUES (?, 'qdrant', 1, ?)", TOPIC, T)
        self.assertEqual(self.rows("SELECT delivered_generation FROM sink_generations WHERE topic_id = ? AND sink = 'qdrant'", TOPIC), [(2,)])
        self.x("UPDATE sink_generations SET delivered_generation = 3 WHERE topic_id = ? AND sink = 'qdrant'", TOPIC)


class ContractGovernanceTest(StoreTestCase):
    def test_contract_content_immutable_never_deleted(self) -> None:
        """D50 rewrite (A1/A2): every pin, REPLACE, creation as draft, and the
        approval subject. Approval near-misses differ in one dimension: kind (an
        approved rating decision about this very revision), disposition, or
        subject (another revision; a contract's revision, hash and topic are
        mutually determined because content hashes are unique and the decision's
        subject must exist when recorded)."""
        stored = self.snapshot("contract_revisions")
        for pin, value in (("protocol_revision", 2), ("framing_version", 2), ("content_hash", h("9")), ("parent_revision", 1),
                           ("document", '{"topic_id":"fleet-a:t1"}'), ("created_at", "2026-09-26T00:00:00Z"), ("revision", 7)):
            with self.subTest(pin=pin):
                self.rejects("contract revisions are immutable", f"UPDATE contract_revisions SET {pin} = ? WHERE topic_id = ? AND revision = 1", value, TOPIC)
        self.rejects("never deleted", "DELETE FROM contract_revisions WHERE topic_id = ? AND revision = 1", TOPIC)
        self.rejects("never deleted", "INSERT OR REPLACE INTO contract_revisions SELECT topic_id, revision, parent_revision, 2, framing_version, content_hash, json_set(document, '$.protocol_revision', 2), status, approved_by_decision_id, created_at FROM contract_revisions WHERE topic_id = ? AND revision = 1", TOPIC)
        self.assertEqual(self.snapshot("contract_revisions"), stored)
        approve = "UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = ? WHERE topic_id = ? AND revision = 1"
        self.contract(TOPIC, 2)
        self.decision("opd_ratingxx", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.decision("opd_rejected", "contract_approval", disposition="rejected", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.decision("opd_otherrev", "contract_approval", rev=2, hsh=self.content_hash_of(TOPIC, 2))
        self.decision("opd_othertop", "contract_approval", tid=OTHER, rev=1, hsh=self.content_hash_of(OTHER, 1))
        for did in ("opd_ratingxx", "opd_rejected", "opd_otherrev", "opd_othertop"):
            with self.subTest(decision=did):
                self.rejects("exact topic, revision and content hash", approve, did, TOPIC)
        self.rejects("existing subject", "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES ('opd_wronghsh', ?, 'contract_approval', 'approved', 'contract_revision', ?, 1, ?, 'trevor', ?)", TOPIC, TOPIC, h("0"), T)
        self.decision("opd_00000001", "contract_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.rejects("exact topic, revision and content hash", approve, "opd_rejected", TOPIC)  # a valid approval exists, but is not the one named
        self.x(approve, "opd_00000001", TOPIC)
        self.rejects("draft -> approved -> superseded", "UPDATE contract_revisions SET status = 'draft' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.rejects("written as a draft", "INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, approved_by_decision_id, created_at) "
                     "SELECT topic_id, 3, 2, protocol_revision, framing_version, ?, json_set(json_set(document, '$.revision', 3), '$.content_hash', ?), 'approved', 'opd_00000001', created_at FROM contract_revisions WHERE topic_id = ? AND revision = 1", h("8"), h("8"), TOPIC)

    def test_hash_lock_binds_document_to_row(self) -> None:
        doc = json.dumps({"topic_id": TOPIC, "revision": 2, "content_hash": h("0"), "protocol_revision": 1, "facet_map": {"framing_version": 1}})
        self.rejects("CHECK constraint failed", "INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, created_at) VALUES (?, 2, 1, 1, 1, ?, ?, 'draft', ?)", TOPIC, h("9"), doc, T)

    def test_one_approved_revision_per_topic(self) -> None:
        self.approve_contract(TOPIC, 1, "opd_00000001")
        self.contract(TOPIC, 2)
        self.decision("opd_00000002", "amendment_approval", rev=2, hsh=self.content_hash_of(TOPIC, 2))
        self.rejects("UNIQUE constraint failed", "UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000002' WHERE topic_id = ? AND revision = 2", TOPIC)
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000002' WHERE topic_id = ? AND revision = 2", TOPIC)

    def test_operator_rating_band_and_score_consistent(self) -> None:
        """Each probe's document entry carries the same values as its row, so the
        rejection is the band/score CHECK, not the document binding."""
        self.decision("opd_00000001", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        bad = (obligation("O-bad1", band="critical", score=5, decision="opd_00000001"),
               obligation("O-bad2", band="critical", score=8),
               obligation("O-bad3", score=8))  # a score without a band
        good = (obligation("O-1", band="critical", score=8, decision="opd_00000001"),
                obligation("O-2", band="important", decision="opd_00000001"),
                obligation("O-3"))
        self.contract(TOPIC, 2)
        self.contract(TOPIC, 3, facets=(facet("F-1"),), obligations=bad + good)
        self.insert_facet(TOPIC, 3, facet("F-1"))
        for entry in bad:
            with self.subTest(obligation=entry["obligation_id"]):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, 3, entry)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        for entry in good:
            self.insert_obligation(TOPIC, 3, entry)
        self.rejects("obligations are immutable", "UPDATE obligations SET operator_importance_band = 'limited' WHERE obligation_id = 'O-2'")

    def test_operator_rating_bound_to_a_rating_decision(self) -> None:
        """A2: the rating's decision must be an approved rating_approval of this
        topic about an earlier revision (the draft that was rated). Each probe's
        document entry names its own decision, so only the decision binding can
        refuse it; a valid decision exists throughout (naming)."""
        self.decision("opd_00000001", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        probes = ("opd_rejected", "opd_samerev", "opd_othertop", "opd_approval")
        entries = {did: obligation("O-" + did, band="critical", decision=did) for did in probes + ("opd_00000001",)}
        self.contract(TOPIC, 2, facets=(facet("F-1"),), obligations=tuple(entries.values()))
        self.insert_facet(TOPIC, 2, facet("F-1"))
        self.decision("opd_rejected", "rating_approval", disposition="rejected", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.decision("opd_samerev", "rating_approval", rev=2, hsh=self.content_hash_of(TOPIC, 2))  # about the revision that carries it
        self.decision("opd_othertop", "rating_approval", tid=OTHER, rev=1, hsh=self.content_hash_of(OTHER, 1))
        self.decision("opd_approval", "contract_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        for did in probes:
            with self.subTest(decision=did):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, 2, entries[did])
                self.assertIn("approved rating decision about an earlier revision", str(ctx.exception))
        self.insert_obligation(TOPIC, 2, entries["opd_00000001"])

    def test_proposed_importance_cites_an_importance_receipt(self) -> None:
        """A2: a Jev-score proposal cites an importance_score decision receipt of
        the same topic; a receipt of another class or topic is refused."""
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        imp = self.spec("dspec_import01", cls="importance_score")
        self.decision_receipt("dec_screen01", "inv_pppppppp", self.spec())
        self.decision_receipt("dec_import01", "inv_pppppppp", imp, cls="importance_score")
        self.decision_receipt("dec_otherimp", "inv_oooooooo", imp, cls="importance_score", tid=OTHER)
        entries = {rid: obligation("O-" + rid, psource="jev_score", pscore=8, preceipt=rid) for rid in ("dec_screen01", "dec_otherimp", "dec_import01")}
        self.contract(TOPIC, 2, facets=(facet("F-1"),), obligations=tuple(entries.values()))
        self.insert_facet(TOPIC, 2, facet("F-1"))
        for rid in ("dec_screen01", "dec_otherimp"):
            with self.subTest(receipt=rid):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, 2, entries[rid])
                self.assertIn("importance_score receipt", str(ctx.exception))
        self.insert_obligation(TOPIC, 2, entries["dec_import01"])

    def dossier(self, rev: int, contract_rev: int, ch: str) -> None:
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, ?, ?, 1, 'eval-1', ?, ?, ?)", TOPIC, rev, contract_rev, ch, h("7"), T)

    def test_completion_needs_approval_of_current_dossier(self) -> None:
        """D54 rewrite (A2): the transition names an approved completion approval
        of the current dossier (revision + hash) evaluated under the active,
        approved contract. Each near-miss differs from a valid decision in one
        dimension: currency (stale dossier), disposition, kind (a rating
        decision whose subject revision/hash deliberately coincide with the
        current dossier's), naming (a valid approval exists but the transition
        names another), protocol (dossier under an approved but non-active
        contract; under the active contract while it is unapproved)."""
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        self.approve_contract(TOPIC, 1)
        self.set_status(TOPIC, "active")
        self.x("UPDATE queue_entries SET active_contract_revision = 1 WHERE topic_id = ?", TOPIC)
        complete = "UPDATE queue_entries SET status = 'completed_with_qualified_conclusions', status_decision_id = ?, state_revision = state_revision + 1 WHERE topic_id = ?"
        refused = "completion requires operator approval"
        self.dossier(1, 1, h("3"))
        self.decision("opd_stale001", "completion_approval", rev=1, hsh=h("3"))
        self.dossier(2, 1, h("4"))  # material change after that approval
        self.rejects(refused, complete, "opd_stale001", TOPIC)
        self.decision("opd_rejected", "completion_approval", disposition="rejected", rev=2, hsh=h("4"))
        self.rejects(refused, complete, "opd_rejected", TOPIC)
        self.rejects("existing subject", "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES ('opd_wronghsh', ?, 'completion_approval', 'approved', 'dossier', ?, 2, ?, 'trevor', ?)", TOPIC, TOPIC, h("3"), T)
        for rev in (2, 3, 4, 5):
            self.contract(TOPIC, rev)
        self.dossier(5, 1, self.content_hash_of(TOPIC, 5))  # current dossier carrying contract 5's hash
        self.decision("opd_wrongknd", "rating_approval", rev=5, hsh=self.content_hash_of(TOPIC, 5))
        self.rejects(refused, complete, "opd_wrongknd", TOPIC)
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, 5, 1, 1, 'eval-1', ?, ?, ?)", OTHER, h("9"), h("7"), T)
        self.decision("opd_othertop", "completion_approval", tid=OTHER, rev=5, hsh=h("9"))
        self.rejects(refused, complete, "opd_othertop", TOPIC)  # another topic's approval of its own dossier 5
        self.decision("opd_valid005", "completion_approval", rev=5, hsh=self.content_hash_of(TOPIC, 5))
        self.rejects(refused, complete, "opd_wrongknd", TOPIC)  # a valid approval exists, but is not the one named
        self.x("UPDATE queue_entries SET active_contract_revision = 2 WHERE topic_id = ?", TOPIC)
        self.rejects(refused, complete, "opd_valid005", TOPIC)  # dossier's contract (approved) is not the active one
        self.dossier(6, 2, h("6"))
        self.decision("opd_unapprov", "completion_approval", rev=6, hsh=h("6"))
        self.rejects(refused, complete, "opd_unapprov", TOPIC)  # dossier under the active contract, which is not approved
        self.x("UPDATE queue_entries SET active_contract_revision = 1 WHERE topic_id = ?", TOPIC)
        self.dossier(7, 1, h("8"))
        self.decision("opd_00000001", "completion_approval", rev=7, hsh=h("8"))
        self.x(complete, "opd_00000001", TOPIC)
        self.assertEqual(self.rows("SELECT status, status_decision_id FROM queue_entries WHERE topic_id = ?", TOPIC), [("completed_with_qualified_conclusions", "opd_00000001")])

    def test_retirement_needs_operator_decision(self) -> None:
        """D55 rewrite (A2): the transition names an approved retirement decision
        about this topic at the state revision being left. Near-misses, one
        dimension each: no decision, stale revision, disposition, topic (same
        revision number), kind (a completion approval whose subject revision
        equals the current state revision), naming (a valid decision exists but
        another is named); and a used decision cannot be reused after
        reactivation."""
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        retire = "UPDATE queue_entries SET status = 'retired', status_decision_id = ?, state_revision = state_revision + 1 WHERE topic_id = ?"
        refused = "retirement requires"
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(retire, None, TOPIC)  # no decision named at all
        self.decision("opd_stale000", "retirement", rev=self.state_revision())
        self.set_status(TOPIC, "scoping")  # a commit after the decision makes it stale
        now = self.state_revision()
        self.rejects(refused, retire, "opd_stale000", TOPIC)
        self.decision("opd_rejected", "retirement", disposition="rejected", rev=now)
        self.decision("opd_othertop", "retirement", tid=OTHER, rev=now)
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, ?, 1, 1, 'eval-1', ?, ?, ?)", TOPIC, now, h("3"), h("7"), T)
        self.decision("opd_wrongknd", "completion_approval", rev=now, hsh=h("3"))
        for did in ("opd_rejected", "opd_othertop", "opd_wrongknd"):
            with self.subTest(decision=did):
                self.rejects(refused, retire, did, TOPIC)
        self.decision("opd_00000001", "retirement", rev=now)
        self.rejects(refused, retire, "opd_stale000", TOPIC)  # a valid decision exists, but is not the one named
        self.x(retire, "opd_00000001", TOPIC)
        self.set_status(TOPIC, "active")
        self.rejects(refused, retire, "opd_00000001", TOPIC)  # reuse after reactivation: made against an earlier state

    def test_terminal_statuses_cannot_be_inserted(self) -> None:
        """A2: creation is constrained to the initial intake status."""
        ins = "INSERT INTO queue_entries (topic_id, fleet_id, priority, status, status_decision_id, state_revision, created_at, updated_at) VALUES ('fleet-a:t3', 'fleet-a', 1, ?, ?, ?, ?, ?)"
        self.decision("opd_00000001", "retirement", rev=self.state_revision())
        for status, did in (("retired", "opd_00000001"), ("completed_with_qualified_conclusions", "opd_00000001"), ("active", None)):
            with self.subTest(status=status):
                self.rejects("created awaiting brief confirmation", ins, status, did, 0, T, T)
        self.rejects("created awaiting brief confirmation", ins, "awaiting_brief_confirmation", None, 5, T, T)
        self.x(ins, "awaiting_brief_confirmation", None, 0, T, T)

    def test_status_change_is_a_commit(self) -> None:
        self.rejects("advances state_revision by one", "UPDATE queue_entries SET status = 'scoping' WHERE topic_id = ?", TOPIC)
        self.set_status(TOPIC, "scoping")
        self.assertEqual(self.state_revision(), 1)
        # the authorizing decision is recorded only with a decision-gated status, and cleared on leaving it
        self.decision("opd_00000001", "retirement", rev=self.state_revision())
        self.rejects("CHECK constraint failed", "UPDATE queue_entries SET status = 'active', status_decision_id = 'opd_00000001', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        self.set_status(TOPIC, "retired", "opd_00000001")
        self.rejects("CHECK constraint failed", "UPDATE queue_entries SET status = 'active', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        self.set_status(TOPIC, "active")


class AdmissionAndLeaseTest(StoreTestCase):
    """A4 (typed admission context; pre-contract work can finalize without a
    Contract v2 FK, scientific commits still need the approved protocol) and
    ruling R2.1 (per-scope leases, one owning invocation, kind/scope match)."""

    def discovery(self, iid: str = "inv_scope001", lease: str = "lease_dddddddd", gen: int = 1, **kw) -> None:
        self.lease(lease, gen, scope="discovery")
        self.invocation(iid, kind="discovery", lease=lease, pre_contract=True, **kw)

    def test_pre_contract_discovery_can_finalize(self) -> None:
        """The review's probe: a scoping discovery on a topic with no contract
        commits its final receipt (it hit an FK failure before)."""
        self.discovery()
        self.receipt("op_00000001", "inv_scope001", lease="lease_dddddddd", kind="final_outcome")
        self.assertEqual(self.rows("SELECT admission_context, contract_revision, brief_hash FROM operation_receipts"), [("pre-contract/1", None, h("b"))])

    def test_pre_contract_admission_needs_the_confirmed_brief(self) -> None:
        brief, version, bhash, _ = self.confirm_brief(TOPIC)  # a valid confirmation exists throughout (naming)
        self.lease("lease_dddddddd", 1, scope="discovery")
        self.decision("opd_rejected", "brief_confirmation", disposition="rejected", ref=brief, rev=version, hsh=bhash)
        self.decision("opd_otherbrf", "brief_confirmation", ref="brief-2", rev=version, hsh=bhash)
        self.decision("opd_otherver", "brief_confirmation", ref=brief, rev=2, hsh=bhash)
        self.decision("opd_otherhsh", "brief_confirmation", ref=brief, rev=version, hsh=h("9"))
        self.decision("opd_othertop", "brief_confirmation", tid=OTHER, ref=brief, rev=version, hsh=bhash)
        self.decision("opd_wrongknd", "scope_approval", ref=brief, rev=version, hsh=bhash)
        pins = dict(kind="discovery", lease_id="lease_dddddddd", admission_context="pre-contract/1", contract_revision=None,
                    brief_ref=brief, brief_version=version, brief_hash=bhash)
        for did in ("opd_rejected", "opd_otherbrf", "opd_otherver", "opd_otherhsh", "opd_othertop", "opd_wrongknd"):
            with self.subTest(decision=did):
                self.rejects("pre-contract work needs a confirmed brief", *self.raw_invocation(invocation_id="inv_scope001", brief_confirmation_decision_id=did, **pins))
        self.x(*self.raw_invocation(invocation_id="inv_scope001", brief_confirmation_decision_id=self.confirm_brief(TOPIC)[3], **pins))

    def test_pre_contract_admission_closes_once_a_contract_is_approved(self) -> None:
        self.approve_contract(TOPIC, 1)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.discovery()
        self.assertIn("no approved contract", str(ctx.exception))
        self.invocation("inv_disc0001", kind="discovery", lease="lease_dddddddd")  # contract-admitted discovery on the same lease is fine

    def test_pre_contract_admission_only_for_scoping_kinds(self) -> None:
        brief, version, bhash, did = self.confirm_brief(TOPIC)
        for kind, scope in (("verification", "verification"), ("checkpoint", "checkpoint")):
            with self.subTest(kind=kind):
                lid = f"lease_{kind[:8]:0<8}"
                self.lease(lid, 1 if kind == "verification" else 2, scope=scope)
                self.rejects("CHECK constraint failed", *self.raw_invocation(invocation_id=f"inv_{kind[:8]:0<8}", kind=kind, lease_id=lid, admission_context="pre-contract/1", contract_revision=None,
                                                                             brief_ref=brief, brief_version=version, brief_hash=bhash, brief_confirmation_decision_id=did))
        self.lease("lease_rrrrrrrr", 3)
        self.invocation("inv_draft001", lease="lease_rrrrrrrr", pre_contract=True)  # the primary drafting the contract (S3)

    def test_contract_admission_needs_an_approved_revision(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.rejects("contract work needs an approved contract revision", *self.raw_invocation(invocation_id="inv_pppppppp", contract_revision=1))
        self.approve_contract(TOPIC, 1)
        self.invocation("inv_pppppppp")

    def test_receipt_carries_the_invocations_admission_and_config(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")  # pinned to approved revision 1
        self.contract(TOPIC, 2)
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.approve_contract(TOPIC, 2, kind="amendment_approval")
        pinned = "admission pins or config bundle differ"
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp", admission=("contract/1", 2, None))  # the now-current revision is not the invocation's
        self.assertIn(pinned, str(ctx.exception))
        for admission in (("pre-contract/1", None, h("b")), ("pre-contract/1", 1, None)):  # the second differs in context alone
            with self.subTest(admission=admission):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.receipt("op_00000001", "inv_pppppppp", admission=admission)
                self.assertIn(pinned, str(ctx.exception))
        self.rejects(pinned, "INSERT INTO operation_receipts (operation_id, receipt_id, operation_kind, invocation_id, topic_id, request_fingerprint, payload_digest, lease_id, lease_generation, admission_context, contract_revision, config_bundle_hash, state_revision_before, state_revision_after, validator_version, policy_version, receipt, committed_at) "
                     "VALUES ('op_00000001', 'rcpt_00000001', 'final_outcome', 'inv_pppppppp', ?, ?, ?, 'lease_aaaaaaaa', 1, 'contract/1', 1, ?, 0, 1, 'v1', 'p1', ?, ?)",
                     TOPIC, h("f"), h("d"), h("0"), json.dumps({"operation_id": "op_00000001", "receipt_id": "rcpt_00000001", "payload_digest": h("d"), "admission": {"context": "contract/1", "contract": {"revision": 1}, "brief": None}}), T)
        self.receipt("op_00000001", "inv_pppppppp")

    def test_receipt_json_admission_matches_its_columns(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        body = {"operation_id": "op_00000001", "receipt_id": "rcpt_00000001", "payload_digest": h("d"), "admission": {"context": "contract/1", "contract": {"revision": 1}, "brief": None}}
        ins = ("INSERT INTO operation_receipts (operation_id, receipt_id, operation_kind, invocation_id, topic_id, request_fingerprint, payload_digest, lease_id, lease_generation, admission_context, contract_revision, config_bundle_hash, state_revision_before, state_revision_after, validator_version, policy_version, receipt, committed_at) "
               "VALUES ('op_00000001', 'rcpt_00000001', 'final_outcome', 'inv_pppppppp', ?, ?, ?, 'lease_aaaaaaaa', 1, 'contract/1', 1, ?, 0, 1, 'v1', 'p1', ?, ?)")
        for key, value in (("context", "pre-contract/1"), ("contract", {"revision": 2}), ("brief", {"content_hash": h("b")})):
            with self.subTest(field=key):
                self.rejects("CHECK constraint failed", ins, TOPIC, h("f"), h("d"), h("c"), json.dumps({**body, "admission": {**body["admission"], key: value}}), T)
        self.x(ins, TOPIC, h("f"), h("d"), h("c"), json.dumps(body), T)

    def test_pre_contract_receipt_carries_the_brief_pinned_at_admission(self) -> None:
        self.discovery()
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_scope001", lease="lease_dddddddd", admission=("pre-contract/1", None, h("9")))
        self.assertIn("admission pins or config bundle differ", str(ctx.exception))
        self.receipt("op_00000001", "inv_scope001", lease="lease_dddddddd")

    def test_admission_pins_are_exclusive(self) -> None:
        """A contract-admitted row carries no brief pins; a pre-contract row no
        contract revision (probes chosen so the admission trigger passes)."""
        brief, version, bhash, did = self.confirm_brief(TOPIC)
        self.lease("lease_dddddddd", 1, scope="discovery")
        self.rejects("CHECK constraint failed", *self.raw_invocation(invocation_id="inv_scope001", kind="discovery", lease_id="lease_dddddddd", admission_context="pre-contract/1", contract_revision=1,
                                                                     brief_ref=brief, brief_version=version, brief_hash=bhash, brief_confirmation_decision_id=did))
        self.approve_contract(TOPIC, 1)
        self.rejects("CHECK constraint failed", *self.raw_invocation(invocation_id="inv_disc0001", kind="discovery", lease_id="lease_dddddddd", contract_revision=1,
                                                                     brief_ref=brief, brief_version=version, brief_hash=bhash, brief_confirmation_decision_id=did))
        self.x(*self.raw_invocation(invocation_id="inv_disc0001", kind="discovery", lease_id="lease_dddddddd", contract_revision=1))

    def test_pre_contract_research_pass_earns_no_ordinal(self) -> None:
        """C-12 / C-7: a scientific counter needs the approved protocol."""
        self.lease("lease_rrrrrrrr", 1)
        self.invocation("inv_draft001", lease="lease_rrrrrrrr", pre_contract=True)
        self.receipt("op_00000001", "inv_draft001", lease="lease_rrrrrrrr", kind="final_outcome")
        self.rejects("ordinals go only to", "INSERT INTO research_ordinals VALUES (?, 1, 'inv_draft001', 'op_00000001')", TOPIC)

    def test_invocation_owns_a_live_lease_of_its_kind_and_topic(self) -> None:
        self.approve_contract(TOPIC, 1)
        self.lease("lease_aaaaaaaa", 1)
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        refused = "owns a live lease of its topic"
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_pppppppp", lease_id="lease_vvvvvvvv"))  # wrong scope
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_pppppppp", lease_id="lease_zzzzzzzz"))  # other topic's lease
        self.invocation("inv_pppppppp")
        self.rejects("UNIQUE constraint failed: invocations.lease_id", *self.raw_invocation(invocation_id="inv_qqqqqqqq"))  # a second owner
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.lease("lease_bbbbbbbb", 3)
        self.x("UPDATE leases SET released_at = ?, release_reason = 'expired' WHERE lease_id = 'lease_bbbbbbbb'", T)
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_qqqqqqqq", lease_id="lease_bbbbbbbb"))  # released
        self.lease("lease_cccccccc", 4)
        self.invocation("inv_qqqqqqqq", lease="lease_cccccccc")

    def test_newer_verification_generation_does_not_fence_research(self) -> None:
        """R2.1: a verification lease granted after the research lease has a larger
        generation; the research pass still commits at its own generation."""
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        self.invocation("inv_vvvvvvvv", kind="verification", lease="lease_vvvvvvvv")
        self.receipt("op_00000002", "inv_vvvvvvvv", lease="lease_vvvvvvvv", gen=2, before=0, kind="final_outcome")
        self.receipt("op_00000001", "inv_pppppppp", lease="lease_aaaaaaaa", gen=1, before=1, kind="final_outcome")
        self.assertEqual(self.rows("SELECT operation_id FROM operation_receipts ORDER BY state_revision_after"), [("op_00000002",), ("op_00000001",)])


class FacetImportanceTest(StoreTestCase):
    """A3: facet importance is its own record, bound to the hash-locked
    document and the operator's rating decision — never inferred from
    obligations — and G-3's uncovered-critical-facet rule gates approval."""

    def setUp(self) -> None:
        super().setUp()
        self.decision("opd_rate0001", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))

    def approve(self, rev: int) -> None:
        self.decision(f"opd_appr{rev:04d}", "contract_approval", rev=rev, hsh=self.content_hash_of(TOPIC, rev))
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?", f"opd_appr{rev:04d}", TOPIC, rev)

    def uncovered(self, rev: int) -> list[tuple]:
        return self.rows("SELECT facet_id FROM uncovered_critical_facets WHERE topic_id = ? AND contract_revision = ? ORDER BY facet_id", TOPIC, rev)

    def test_critical_facet_with_zero_obligations_is_representable_and_blocks_approval(self) -> None:
        # F-omitted is rated critical by the operator and no obligation tags it
        self.contract_with_rows(TOPIC, 2, facets=(facet("F-omitted", band="critical", score=8, decision="opd_rate0001"),
                                                  facet("F-2", band="important", decision="opd_rate0001")),
                                obligations=(obligation("O-1", ("F-2",), band="important", decision="opd_rate0001"),))
        self.assertEqual(self.rows("SELECT operator_importance_band FROM facets WHERE facet_id = 'F-omitted'"), [("critical",)])
        self.assertEqual(self.uncovered(2), [("F-omitted",)])
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.approve(2)
        self.assertIn("no uncovered critical facet", str(ctx.exception))
        # a revision whose obligation tags the critical facet is approvable
        self.contract_with_rows(TOPIC, 3, facets=(facet("F-omitted", band="critical", score=8, decision="opd_rate0001"),),
                                obligations=(obligation("O-2", ("F-omitted",)),))
        self.assertEqual(self.uncovered(3), [])
        self.approve(3)

    def test_approval_needs_complete_rows_and_every_facet_rated(self) -> None:
        both = (facet("F-1", band="limited", decision="opd_rate0001"), facet("F-2", band="limited", decision="opd_rate0001"))
        # a document facet without its row
        self.contract(TOPIC, 2, facets=both, obligations=(obligation("O-1", ("F-1",)),))
        self.insert_facet(TOPIC, 2, both[0])
        self.insert_obligation(TOPIC, 2, obligation("O-1", ("F-1",)))
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(2)
        # a document obligation without its row
        self.contract(TOPIC, 3, facets=both, obligations=(obligation("O-1", ("F-1",)), obligation("O-2", ("F-2",))))
        for entry in both:
            self.insert_facet(TOPIC, 3, entry)
        self.insert_obligation(TOPIC, 3, obligation("O-1", ("F-1",)))
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(3)
        # an unrated facet (its importance could not be known critical)
        self.contract_with_rows(TOPIC, 4, facets=(both[0], facet("F-2")), obligations=(obligation("O-1", ("F-1",)),))
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(4)
        self.contract_with_rows(TOPIC, 5, facets=both, obligations=(obligation("O-1", ("F-1",)),))
        self.approve(5)

    def test_facet_row_must_equal_its_document_entry(self) -> None:
        doc_entry = facet("F-1", band="critical", score=8, decision="opd_rate0001")
        self.contract(TOPIC, 2, facets=(doc_entry,))
        for field, row in (("band", facet("F-1", band="important", decision="opd_rate0001")),
                           ("score", facet("F-1", band="critical", score=9, decision="opd_rate0001")),
                           ("unrated", facet("F-1")),
                           ("absent", facet("F-9", band="critical", score=8, decision="opd_rate0001"))):
            with self.subTest(field=field):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_facet(TOPIC, 2, row)
                self.assertIn("equal its document entry", str(ctx.exception))
        self.insert_facet(TOPIC, 2, doc_entry)

    def test_facet_rating_bound_to_a_rating_decision(self) -> None:
        probes = ("opd_rejected", "opd_samerev", "opd_othertop", "opd_approval")
        entries = {did: facet("F-" + did, band="critical", decision=did) for did in probes + ("opd_rate0001",)}
        out_of_band = facet("F-x", band="critical", score=5, decision="opd_rate0001")
        self.contract(TOPIC, 2, facets=tuple(entries.values()) + (out_of_band,))
        self.decision("opd_rejected", "rating_approval", disposition="rejected", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.decision("opd_samerev", "rating_approval", rev=2, hsh=self.content_hash_of(TOPIC, 2))
        self.decision("opd_othertop", "rating_approval", tid=OTHER, rev=1, hsh=self.content_hash_of(OTHER, 1))
        self.decision("opd_approval", "contract_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        for did in probes:
            with self.subTest(decision=did):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_facet(TOPIC, 2, entries[did])
                self.assertIn("approved rating decision", str(ctx.exception))
        self.insert_facet(TOPIC, 2, entries["opd_rate0001"])  # a valid decision exists throughout (naming)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_facet(TOPIC, 2, out_of_band)
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.rejects("facets are immutable", "UPDATE facets SET operator_importance_band = 'limited'")

    def test_facet_proposal_cites_an_importance_receipt(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        imp = self.spec("dspec_import01", cls="importance_score")
        self.decision_receipt("dec_screen01", "inv_pppppppp", self.spec())
        self.decision_receipt("dec_import01", "inv_pppppppp", imp, cls="importance_score")
        self.decision_receipt("dec_otherimp", "inv_oooooooo", imp, cls="importance_score", tid=OTHER)
        entries = {rid: facet("F-" + rid, psource="jev_score", pscore=8, preceipt=rid) for rid in ("dec_screen01", "dec_otherimp", "dec_import01")}
        self.contract(TOPIC, 2, facets=tuple(entries.values()))
        for rid in ("dec_screen01", "dec_otherimp"):
            with self.subTest(receipt=rid):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert_facet(TOPIC, 2, entries[rid])
        self.insert_facet(TOPIC, 2, entries["dec_import01"])

    def test_obligation_row_equals_its_entry_and_tags_only_its_facets(self) -> None:
        entry = obligation("O-1", ("F-1",), band="important", decision="opd_rate0001")
        self.contract(TOPIC, 2, facets=(facet("F-1"),), obligations=(entry, obligation("O-2", ("F-9",))))
        self.insert_facet(TOPIC, 2, facet("F-1"))
        for name, row in (("facet tags", obligation("O-1", ("F-1", "F-2"), band="important", decision="opd_rate0001")),
                          ("band", obligation("O-1", ("F-1",), band="critical", decision="opd_rate0001"))):
            with self.subTest(field=name):
                self.assertRaises(sqlite3.IntegrityError, self.insert_obligation, TOPIC, 2, row)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_obligation(TOPIC, 2, obligation("O-2", ("F-9",)))  # matches its entry, but F-9 is no facet of the revision
        self.assertIn("tag only facets of its revision", str(ctx.exception))
        self.insert_obligation(TOPIC, 2, entry)


if __name__ == "__main__":
    unittest.main()
