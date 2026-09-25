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

from gen2.tests.store_fixtures import OTHER, TOPIC, StoreTestCase, T, h


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
        self.rejects("invocations are created admitted",
                     "INSERT INTO invocations (invocation_id, kind, topic_id, lease_id, capability_id, config_bundle_hash, state, admitted_at, deadline_at, launch_intent_at, result_payload_digest, result_staged_at, state_changed_at) VALUES ('inv_pppppppp', 'research_pass', ?, 'lease_aaaaaaaa', 'cap_pppppppp', ?, 'committed', ?, ?, ?, ?, ?, ?)",
                     TOPIC, h("c"), T, T, T, h("d"), T, T)
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
        self.rejects("CHECK constraint failed", "INSERT INTO invocations (invocation_id, kind, topic_id, lease_id, capability_id, config_bundle_hash, state, admitted_at, deadline_at, state_changed_at) VALUES ('inv_dddddddd', 'delegate', ?, NULL, 'cap_dddddddd', ?, 'admitted', ?, ?, ?)", TOPIC, h("c"), T, T, T)
        self.invocation("inv_dddddddd", kind="delegate", lease=None, parent="inv_pppppppp")

    def test_capability_is_unique_per_invocation(self) -> None:
        self.invocation("inv_pppppppp")
        self.rejects("UNIQUE constraint failed: invocations.capability_id",
                     "INSERT INTO invocations (invocation_id, kind, topic_id, lease_id, capability_id, config_bundle_hash, state, admitted_at, deadline_at, state_changed_at) VALUES ('inv_vvvvvvvv', 'research_pass', ?, 'lease_aaaaaaaa', 'cap_pppppppp', ?, 'admitted', ?, ?, ?)", TOPIC, h("c"), T, T, T)


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
        replace = ("INSERT OR REPLACE INTO operation_receipts SELECT ?, ?, operation_kind, invocation_id, topic_id, ?, ?, lease_id, lease_generation, contract_revision, config_bundle_hash, state_revision_before + ?, state_revision_after + ?, validator_version, policy_version, "
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
        self.invocation("inv_qqqqqqqq")
        self.receipt("op_00000001", "inv_pppppppp", before=4)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000002", "inv_qqqqqqqq", before=4)
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
        self.rejects("ordinals go only to research_pass", "INSERT INTO research_ordinals VALUES (?, 1, 'inv_kkkkkkkk', 'op_00000001')", TOPIC)
        self.receipt("op_00000002", "inv_pppppppp", kind="interim_transition", before=1)
        self.rejects("ordinals go only to research_pass", "INSERT INTO research_ordinals VALUES (?, 1, 'inv_pppppppp', 'op_00000002')", TOPIC)
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

    def test_verifier_must_be_separate_verification_invocation(self) -> None:
        self.invocation("inv_qqqqqqqq")  # a second research_pass, not a verifier
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", verifier="inv_qqqqqqqq", extraction="inv_qqqqqqqq")
        self.assertIn("separate verification invocation", str(ctx.exception))
        # A verification invocation launched by the producer is not independent.
        self.x("INSERT INTO invocations (invocation_id, kind, topic_id, parent_invocation_id, lease_id, capability_id, config_bundle_hash, state, admitted_at, deadline_at, state_changed_at) VALUES ('inv_childver', 'verification', ?, 'inv_pppppppp', 'lease_vvvvvvvv', 'cap_childver', ?, 'admitted', ?, ?, ?)", TOPIC, h("c"), T, T, T)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000002", verifier="inv_childver", extraction="inv_childver")
        self.assertIn("independent of the claim producer", str(ctx.exception))

    def test_receipt_must_name_the_claims_real_producer(self) -> None:
        self.invocation("inv_qqqqqqqq")
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
        self.x(self.INSERT, "hold_00000001", TOPIC, "scope", "operator", "operator", T, "operator rules on reframe", None, T)
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")
        self.rejects("CHECK constraint failed", "UPDATE holds SET cleared_at = ?, cleared_by_operation_id = 'op_00000001' WHERE hold_id = 'hold_00000001'", T)
        self.decision("opd_00000001", "hold_clearance")
        self.x("UPDATE holds SET cleared_at = ?, cleared_by_decision_id = 'opd_00000001' WHERE hold_id = 'hold_00000001'", T)
        self.rejects("a cleared hold is final", "UPDATE holds SET cleared_at = NULL, cleared_by_decision_id = NULL WHERE hold_id = 'hold_00000001'")


class PublicationTest(StoreTestCase):
    OUTBOX = ("INSERT INTO outbox_events (outbox_event_id, topic_id, manifest_id, manifest_hash, artifact_kind, generation, supersedes_generation, source_revision, approval_decision_id, expected_sinks, manifest, committed_by_operation_id, created_at) "
              "VALUES (?, ?, ?, ?, 'completion_publication', ?, ?, 3, ?, '[\"neo4j\", \"qdrant\"]', ?, 'op_00000001', ?)")

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")

    def outbox(self, eid: str, mid: str, gen: int, sup, decision: str, mh: str) -> None:
        self.x(self.OUTBOX, eid, TOPIC, mid, h(mh), gen, sup, decision, json.dumps({"manifest_id": mid, "generation": gen, "topic_id": TOPIC}), T)

    def test_only_approved_work_is_published(self) -> None:
        self.decision("opd_00000001", "publication_approval", disposition="rejected")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000001", "1")
        self.assertIn("unapproved work is never published", str(ctx.exception))
        self.decision("opd_00000002", "publication_approval")
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", "1")

    def test_generations_strictly_increase(self) -> None:
        self.decision("opd_00000002", "publication_approval")
        self.outbox("obx_00000001", "man_00000001", 2, 1, "opd_00000002", "1")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.outbox("obx_00000002", "man_00000002", 1, None, "opd_00000002", "2")
        self.assertIn("strictly increase", str(ctx.exception))
        self.outbox("obx_00000002", "man_00000002", 3, 2, "opd_00000002", "2")

    def test_delivery_receipt_only_for_expected_sinks(self) -> None:
        self.decision("opd_00000002", "publication_approval")
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", "1")
        self.x("CREATE TEMP TABLE probe AS SELECT 1")  # connection still healthy
        ins = "INSERT INTO sink_delivery_receipts (delivery_receipt_id, outbox_event_id, sink, attempt, status, tombstones_acknowledged, error_class, attempted_at, acked_at) VALUES (?, 'obx_00000001', ?, 1, ?, ?, ?, ?, ?)"
        # The expected-sink trigger fires before the sink CHECK, so its message is the one seen.
        self.rejects("sink the manifest does not expect", ins, "d1", "graphrag", "delivered", 1, None, T, T)
        self.rejects("CHECK constraint failed", ins, "d1", "qdrant", "failed", 0, None, T, None)
        self.x(ins, "d1", "qdrant", "failed", 0, "timeout", T, None)
        self.x(ins, "d2", "neo4j", "delivered", 1, None, T, T)

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
        stored = self.snapshot("contract_revisions")
        for pin, value in (("protocol_revision", 2), ("framing_version", 2), ("content_hash", h("9")), ("parent_revision", 1),
                           ("document", '{"topic_id":"fleet-a:t1"}'), ("created_at", "2026-09-26T00:00:00Z"), ("revision", 7)):
            with self.subTest(pin=pin):
                self.rejects("contract revisions are immutable", f"UPDATE contract_revisions SET {pin} = ? WHERE topic_id = ? AND revision = 1", value, TOPIC)
        self.rejects("never deleted", "DELETE FROM contract_revisions WHERE topic_id = ? AND revision = 1", TOPIC)
        self.rejects("never deleted", "INSERT OR REPLACE INTO contract_revisions SELECT topic_id, revision, parent_revision, 2, framing_version, content_hash, json_set(document, '$.protocol_revision', 2), status, approved_by_decision_id, created_at FROM contract_revisions WHERE topic_id = ? AND revision = 1", TOPIC)
        self.assertEqual(self.snapshot("contract_revisions"), stored)
        self.decision("opd_00000001", "contract_approval")
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000001' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.rejects("draft -> approved -> superseded", "UPDATE contract_revisions SET status = 'draft' WHERE topic_id = ? AND revision = 1", TOPIC)

    def test_hash_lock_binds_document_to_row(self) -> None:
        doc = json.dumps({"topic_id": TOPIC, "revision": 2, "content_hash": h("0"), "protocol_revision": 1, "facet_map": {"framing_version": 1}})
        self.rejects("CHECK constraint failed", "INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, created_at) VALUES (?, 2, 1, 1, 1, ?, ?, 'draft', ?)", TOPIC, h("9"), doc, T)

    def test_one_approved_revision_per_topic(self) -> None:
        self.decision("opd_00000001", "contract_approval")
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000001' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.contract(TOPIC, 2)
        self.rejects("UNIQUE constraint failed", "UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000001' WHERE topic_id = ? AND revision = 2", TOPIC)
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000001' WHERE topic_id = ? AND revision = 2", TOPIC)

    def test_operator_rating_band_and_score_consistent(self) -> None:
        self.decision("opd_00000001", "rating_approval")
        ins = ("INSERT INTO obligations (topic_id, contract_revision, obligation_id, template_id, template_version, claim_type, facet_ids, stopping_profile_id, exploratory, operator_importance_band, operator_importance_score, operator_rating_decision_id) "
               "VALUES (?, 1, ?, 'T1', 1, 'effect', '[\"F-1\"]', 'SP-1', 0, ?, ?, ?)")
        self.rejects("CHECK constraint failed", ins, TOPIC, "O-1", "critical", 5, "opd_00000001")
        self.rejects("CHECK constraint failed", ins, TOPIC, "O-1", "critical", 8, None)
        self.rejects("CHECK constraint failed", ins, TOPIC, "O-1", None, 8, None)  # a score without a band
        self.x(ins, TOPIC, "O-1", "critical", 8, "opd_00000001")
        self.x(ins, TOPIC, "O-2", "important", None, "opd_00000001")
        self.x(ins, TOPIC, "O-3", None, None, None)
        self.rejects("obligations are immutable", "UPDATE obligations SET operator_importance_band = 'limited' WHERE obligation_id = 'O-2'")

    def test_completion_needs_approval_of_current_dossier(self) -> None:
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        dossier = "INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, ?, 1, 1, 'eval-1', ?, ?, ?)"
        self.x(dossier, TOPIC, 1, h("3"), h("7"), T)
        self.decision("opd_00000001", "completion_approval", dossier=1)
        self.x(dossier, TOPIC, 2, h("4"), h("7"), T)  # material change after the approval
        complete = "UPDATE queue_entries SET status = 'completed_with_qualified_conclusions' WHERE topic_id = ?"
        self.rejects("current dossier revision", complete, TOPIC)
        self.decision("opd_00000002", "completion_approval", dossier=2)
        self.x(complete, TOPIC)

    def test_retirement_needs_operator_decision(self) -> None:
        self.rejects("retirement requires", "UPDATE queue_entries SET status = 'retired' WHERE topic_id = ?", TOPIC)
        self.decision("opd_00000001", "retirement")
        self.x("UPDATE queue_entries SET status = 'retired' WHERE topic_id = ?", TOPIC)


if __name__ == "__main__":
    unittest.main()
