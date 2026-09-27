"""commit_outcome: replay and identity, fencing, authority, boundary checks,
atomicity (task 1b, Gate C list).

Trace: design review §5 steps 1-5; INVARIANTS C-2, C-3, C-4, C-5, C-8, C-9,
C-12, C-13, RG-1a, RG-1b, RG-5; BOUNDARIES.md Router (authority from
capability; no caller-supplied role label).

Each rule has an isolated negative — one field of an otherwise committable
envelope changed — and the positive control of the same envelope unchanged.
Oracles: hand-written expected reasons; the store read back with raw SQL
(`state()` compares every table but the audit log, which a rejection
appends to by design: exactly one `commit_rejected` row is asserted); and
every response validated by the independent `jsonschema` package against
commit-outcome.schema.json#/$defs/response.

Structural limits: the store is in memory and faults are raised exceptions
(test_router_crash.py kills a real process); the capability is a bearer
string, so these tests show that the router derives authority from it, not
that the process presenting it is who it claims (no transport yet, 1e).
"""
from __future__ import annotations

import copy

import jsonschema

from gen2.core import canonical
from gen2.router.service import MalformedRequest
from gen2.tests.router_fixtures import OTHER, TOPIC, RouterTestCase, empty_outcome, h, jcs
from gen2.tests.test_router_schemas import oracle

ORACLE = oracle()


class CommitCase(RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.grant = self.started("inv_research01")

    def assertResponse(self, response: dict) -> None:
        self.assertTrue(ORACLE(response, "commit-outcome.schema.json#/$defs/response"), response)

    def assertRejected(self, response: dict, reason: str, before: dict, audits_before: int) -> None:
        self.assertResponse(response)
        self.assertEqual(response["status"], "rejected", response)
        self.assertEqual(response["reason"], reason, response)
        self.assertNotIn("receipt", response)
        self.assertEqual(self.state(), before)  # nothing changed ...
        self.assertEqual(self.value("SELECT count(*) FROM audit_events"), audits_before + 1)  # ... but the refusal is logged
        self.assertEqual(self.value("SELECT kind FROM audit_events ORDER BY rowid DESC LIMIT 1"), "commit_rejected")

    def snapshot(self) -> tuple[dict, int]:
        return self.state(), self.value("SELECT count(*) FROM audit_events")

    def final_envelope(self, op: str = "op_final000001", outcome: dict | None = None, grant: dict | None = None, **overrides) -> dict:
        grant = grant or self.grant
        outcome = outcome or empty_outcome(grant["invocation_id"])
        env = self.envelope(grant, op, outcome)
        self.ready(grant, env["payload_digest"])
        env["expected_state_revision"] = self.state_revision(grant["topic_id"])
        env.update(overrides)
        return env


class ReplayAndIdentityTest(CommitCase):
    def test_replaying_a_committed_operation_returns_the_identical_receipt(self) -> None:
        env = self.final_envelope()
        first = self.router.commit_outcome(env)
        self.assertResponse(first)
        self.assertEqual(first["status"], "committed")
        after_commit = self.state()
        replay = self.router.commit_outcome(copy.deepcopy(env))
        self.assertResponse(replay)
        self.assertEqual(replay["status"], "replayed")
        self.assertEqual(jcs(replay["receipt"]), jcs(first["receipt"]))
        self.assertEqual(self.state(), after_commit)  # the state revision and every row unchanged
        # submitted_at is outside the fingerprint (C-13): a resubmission later is the same request
        later = self.router.commit_outcome({**env, "submitted_at": "2026-09-27T11:59:59.5Z"})
        self.assertEqual(later["status"], "replayed")
        self.assertEqual(jcs(later["receipt"]), jcs(first["receipt"]))

    def test_the_same_operation_id_with_different_content_is_refused(self) -> None:
        env = self.final_envelope()
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")
        before, audits = self.snapshot()
        for field, value in (("payload_size_bytes", env["payload_size_bytes"] + 1), ("expected_state_revision", env["expected_state_revision"] + 1),
                             ("result_refs", [self.artifact(b"another packet")]), ("operation_kind", "interim_transition")):
            with self.subTest(field):
                response = self.router.commit_outcome({**env, field: value})
                self.assertRejected(response, "operation_id_conflict", before, audits)
                audits += 1

    def test_a_lost_reply_is_recovered_by_operation_id(self) -> None:
        env = self.final_envelope()
        self.faults["after_commit"] = ConnectionError("reply lost after commit")
        with self.assertRaises(ConnectionError):
            self.router.commit_outcome(env)
        committed = self.value("SELECT receipt FROM operation_receipts WHERE operation_id = ?", env["operation_id"])
        self.assertIsNotNone(committed)  # the commit happened; only the reply was lost
        recovered = self.router.commit_outcome(env)
        self.assertEqual(recovered["status"], "replayed")
        self.assertEqual(jcs(recovered["receipt"]), canonical.canonical_bytes(canonical.parse_json_strict(committed)))
        self.assertEqual(self.router.receipt(env["operation_id"]), recovered["receipt"])
        self.assertEqual(self.value("SELECT count(*) FROM operation_receipts WHERE invocation_id = 'inv_research01'"), 1)

    def test_a_retained_receipt_authorizes_nothing_after_its_lease_ends(self) -> None:
        """RG-1b(d): after the final outcome released the lease, the receipt
        is readable, and a new operation under that lease is refused."""
        env = self.final_envelope()
        receipt = self.router.commit_outcome(env)["receipt"]
        self.assertEqual(self.router.receipt(env["operation_id"]), receipt)
        before, audits = self.snapshot()
        late = self.envelope(self.grant, "op_interim0001", empty_outcome("inv_research01", "interim_transition"))
        self.assertRejected(self.router.commit_outcome(late), "lease_released", before, audits)


class FencingTest(CommitCase):
    def test_positive_control(self) -> None:
        self.assertEqual(self.router.commit_outcome(self.final_envelope())["status"], "committed")

    def test_a_stale_generation_is_refused(self) -> None:
        env = self.final_envelope()
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome({**env, "lease": {**env["lease"], "generation": env["lease"]["generation"] - 1}}),
                            "lease_generation_stale", before, audits)
        self.assertRejected(self.router.commit_outcome({**env, "operation_id": "op_final000002", "lease": {**env["lease"], "generation": env["lease"]["generation"] + 1}}),
                            "lease_generation_stale", before, audits + 1)

    def test_the_gen1_probe_shapes_are_refused(self) -> None:
        """DR §3: an unminted run with generation -1, and a lease that was never minted."""
        env = self.final_envelope()
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome({**env, "lease": {**env["lease"], "generation": -1}}), "envelope_invalid", before, audits)
        self.assertRejected(self.router.commit_outcome({**env, "lease": {"lease_id": "lease_neverminted", "generation": 7}}), "lease_not_current", before, audits + 1)

    def test_an_expired_lease_is_fenced_by_its_successor(self) -> None:
        """The first holder's lease expires; a new claim releases it and takes
        a higher generation; the old holder's commit is refused."""
        env = self.final_envelope()
        self.clock.set("2026-12-31T00:00:01Z")
        successor = self.claim("inv_research02", deadline_at="2027-01-30T00:00:00Z", lease_expires_at="2027-01-31T00:00:00Z")
        self.assertEqual(successor["status"], "refused")  # the topic is active under the first pass: not claimable for research
        self.x("UPDATE queue_entries SET status = 'queued', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)  # the router's requeue (1d scheduling) stand-in
        successor = self.claim("inv_research02", deadline_at="2027-01-30T00:00:00Z", lease_expires_at="2027-01-31T00:00:00Z")
        self.assertEqual(successor["status"], "granted", successor)
        self.assertGreater(successor["lease"]["generation"], env["lease"]["generation"])
        self.assertEqual(self.rows("SELECT release_reason FROM leases WHERE lease_id = ?", env["lease"]["lease_id"]), [("expired",)])
        before, audits = self.snapshot()
        env["expected_state_revision"] = self.state_revision()
        self.assertRejected(self.router.commit_outcome(env), "lease_released", before, audits)

    def test_an_expired_but_unreleased_lease_is_not_current(self) -> None:
        env = self.final_envelope()
        self.clock.set("2026-12-31T00:00:00Z")  # the next reading is 1 ms past expiry
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "lease_not_current", before, audits)

    def test_a_wrong_expected_revision_is_refused(self) -> None:
        env = self.final_envelope()
        before, audits = self.snapshot()
        for wrong in (env["expected_state_revision"] - 1, env["expected_state_revision"] + 1):
            with self.subTest(wrong):
                self.assertRejected(self.router.commit_outcome({**env, "expected_state_revision": wrong}), "state_revision_stale", before, audits)
                audits += 1

    def test_a_cross_topic_write_is_refused(self) -> None:
        """RG-5: the envelope, the outcome document, or a claim naming another topic."""
        self.to_scoping(OTHER)
        env = self.final_envelope()
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome({**env, "topic_id": OTHER}), "cross_topic", before, audits)
        foreign = empty_outcome("inv_research01", topic=OTHER)
        other = self.envelope(self.grant, "op_final000002", foreign)
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(other), "cross_topic", before, audits)

    def test_another_topics_claim_cannot_be_revised_or_promoted(self) -> None:
        self.to_queued(OTHER)
        theirs = self.started("inv_other001", tid=OTHER)
        text = self.artifact(b"their claim")
        outcome = empty_outcome("inv_other001", topic=OTHER)
        outcome["claims"] = [{"claim_id": "clm_theirs01", "revision": 1, "text_ref": text, "load_bearing": False, "required_access_tier": None}]
        self.assertEqual(self.finish(theirs, "op_theirs0001", outcome, refs=[text])["status"], "committed")
        for section, entry in (("claims", {"claim_id": "clm_theirs01", "revision": 2, "text_ref": text, "load_bearing": False, "required_access_tier": None}),
                               ("claim_promotions", {"claim_id": "clm_theirs01", "revision": 1})):
            with self.subTest(section):
                ours = empty_outcome("inv_research01", "interim_transition")
                ours[section] = [entry]
                env = self.envelope(self.grant, f"op_ours{section[:6]}01", ours, refs=[text])
                before, audits = self.snapshot()
                self.assertRejected(self.router.commit_outcome(env), "cross_topic", before, audits)

    def test_a_stale_admission_or_config_is_refused(self) -> None:
        env = self.final_envelope()
        before, audits = self.snapshot()
        stale = {"context": "contract/1", "contract": {"revision": 1, "content_hash": h("0")}}
        self.assertRejected(self.router.commit_outcome({**env, "admission": stale}), "contract_revision_stale", before, audits)
        self.assertRejected(self.router.commit_outcome({**env, "config_bundle_hash": h("d")}), "config_bundle_mismatch", before, audits + 1)

    def test_a_paused_topic_commits_nothing(self) -> None:
        env = self.final_envelope()
        self.x("UPDATE queue_entries SET paused_at = '2026-09-27T10:10:00Z' WHERE topic_id = ?", TOPIC)
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "topic_paused", before, audits)

    def test_work_pinned_to_a_superseded_contract_is_not_committed(self) -> None:
        """The G-1 hook: after an amendment approves revision 2, a result pinned
        to revision 1 is refused (amendment_pending) until 1d's impact rules
        say which results remain compatible."""
        env = self.final_envelope()
        chash = self.contract_draft(TOPIC, 2)
        self.assertEqual(self.decide("opd_amend0001", "amendment_approval", {"kind": "contract_revision", "revision": 2, "hash": chash})["status"], "applied")
        env["expected_state_revision"] = self.state_revision()
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "amendment_pending", before, audits)

    def test_one_final_outcome_per_invocation(self) -> None:
        """A delegate's lease is its parent's, so its first final outcome does
        not release it: the second final is refused by the final-outcome
        check itself (a non-delegate's is refused earlier, by its released
        lease — ReplayAndIdentityTest)."""
        delegate = self.started("inv_deleg001", "delegate", parent=self.grant)
        env = self.final_envelope(grant=delegate)
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")
        second = {**env, "operation_id": "op_final000002", "expected_state_revision": self.state_revision()}
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(second), "final_outcome_exists", before, audits)

    def test_the_invocation_must_be_in_the_state_the_operation_needs(self) -> None:
        env = self.envelope(self.grant, "op_final000001", empty_outcome("inv_research01"))
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "invocation_state_invalid", before, audits)  # still running: nothing staged
        self.ready(self.grant, env["payload_digest"])
        other = self.envelope(self.grant, "op_final000002", {**empty_outcome("inv_research01"), "next_queue_state": "queued"})
        before, audits = self.snapshot()
        # a final outcome commits exactly the result the supervisor staged, not another document
        self.assertRejected(self.router.commit_outcome(other), "invocation_state_invalid", before, audits)
        interim = self.envelope(self.grant, "op_interim0001", empty_outcome("inv_research01", "interim_transition"))
        self.assertRejected(self.router.commit_outcome(interim), "invocation_state_invalid", before, audits + 1)  # no longer running
        env["expected_state_revision"] = self.state_revision()
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")


class AuthorityTest(CommitCase):
    def test_a_role_label_is_refused_not_ignored(self) -> None:
        env = self.final_envelope()
        before, audits = self.snapshot()
        for label in ({"role": "router"}, {"actor": "operator"}, {"authority": "qualified"}):
            with self.subTest(label):
                self.assertRejected(self.router.commit_outcome({**env, **label}), "envelope_invalid", before, audits)
                audits += 1
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")

    def test_a_role_label_in_the_outcome_document_is_refused(self) -> None:
        outcome = {**empty_outcome("inv_research01", "interim_transition"), "role": "verifier"}
        env = self.envelope(self.grant, "op_interim0001", outcome)
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "payload_invalid", before, audits)

    def test_a_capability_acts_only_for_its_own_invocation(self) -> None:
        other = self.started("inv_verify01", "verification")
        env = self.final_envelope()
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome({**env, "capability_id": other["capability_id"]}), "capability_invocation_mismatch", before, audits)
        self.assertRejected(self.router.commit_outcome({**env, "capability_id": "cap_forgedforged"}), "capability_invalid", before, audits + 1)
        del env["capability_id"]
        self.assertRejected(self.router.commit_outcome(env), "envelope_invalid", before, audits + 2)

    def test_a_producer_cannot_verify_its_own_work(self) -> None:
        """RG-5: a research pass (the producer) cannot commit a verification
        receipt; a verifier cannot commit one naming another verifier, or one
        claiming to be the producer; its own receipt commits."""
        text = self.artifact(b"a load-bearing claim")
        outcome = empty_outcome("inv_research01", "interim_transition")
        outcome["claims"] = [{"claim_id": "clm_00000001", "revision": 1, "text_ref": text, "load_bearing": True, "required_access_tier": "full_text"}]
        self.assertEqual(self.router.commit_outcome(self.envelope(self.grant, "op_capture0001", outcome, refs=[text]))["status"], "committed")
        verifier = self.started("inv_verify01", "verification")
        receipt = self.verification_receipt(verifier)
        cases = (
            ("the producer commits it", self.grant, receipt, "kind_not_permitted"),
            ("the verifier names another verifier", verifier, {**receipt, "verifier_invocation_id": "inv_research01"}, "capability_invocation_mismatch"),
            ("the verifier names another capability", verifier, {**receipt, "verifier_capability_id": self.grant["capability_id"]}, "capability_invocation_mismatch"),
            ("the verifier claims to be the producer", verifier, {**receipt, "producer_invocation_id": "inv_verify01"}, "kind_not_permitted"),
        )
        for name, grant, doc, reason in cases:
            with self.subTest(name):
                committing = empty_outcome(grant["invocation_id"], "interim_transition")
                committing["verification_receipts"] = [doc]
                env = self.envelope(grant, "op_verify0001", committing)
                before, audits = self.snapshot()
                self.assertRejected(self.router.commit_outcome(env), reason, before, audits)
        own = empty_outcome("inv_verify01", "interim_transition")
        own["verification_receipts"] = [receipt]
        self.assertEqual(self.router.commit_outcome(self.envelope(verifier, "op_verify0001", own))["status"], "committed")
        self.assertEqual(self.rows("SELECT verifier_invocation_id, producer_invocation_id FROM verification_receipts"), [("inv_verify01", "inv_research01")])

    def verification_receipt(self, verifier: dict) -> dict:
        return {"receipt_version": "verification-receipt/1", "verification_receipt_id": "ver_000000000001", "topic_id": TOPIC,
                "claim": {"claim_id": "clm_00000001", "claim_revision": 1}, "source": {"work_id": "wrk_00000001", "source_version": "v1"},
                "cited_spans": [{"start": 0, "end": 5, "locator": {"kind": "page", "value": "3"}}], "obtained_content_hash": h("7"),
                "access_tier": "full_text", "requested_for": {"use": "load_bearing", "required_access_tier": "full_text"},
                "acquisition": {"route": "gateway:crossref", "retrieved_at": "2026-09-27T10:00:00Z", "gateway_call_ref": "call-1", "cache_reuse": False},
                "extraction": {"method": "verifier_extraction", "extractor": "x-1", "produced_by_invocation_id": verifier["invocation_id"], "validation_ref": None},
                "producer_invocation_id": "inv_research01", "verifier_invocation_id": verifier["invocation_id"],
                "verifier_capability_id": verifier["capability_id"], "quote_check_id": None,
                "checks": {"exact_quote": {"status": "not_applicable", "normalization_version": "n1", "source_artifact_hash": h("7")},
                           "numeric_units": "checked_ok", "denominators": "checked_ok", "negation": "not_applicable", "qualifications": "checked_ok"},
                "adjudication": None, "verdict": "supports", "verified_at": "2026-09-27T10:05:00Z"}

    def setUp(self) -> None:
        super().setUp()
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', '2026-09-27T09:00:00Z')")

    def test_discovery_and_delegate_work_hold_no_evidence_write_capability(self) -> None:
        discovery = self.started("inv_disco001", "discovery")
        delegate = self.started("inv_deleg001", "delegate", parent=self.grant)
        text = self.artifact(b"a delegate's claim")
        for grant in (discovery, delegate):
            with self.subTest(grant["kind"]):
                outcome = empty_outcome(grant["invocation_id"], "interim_transition")
                outcome["claims"] = [{"claim_id": "clm_delegate01", "revision": 1, "text_ref": text, "load_bearing": False, "required_access_tier": None}]
                op = "op_evidence" + grant["kind"][:5]
                env = self.envelope(grant, op, outcome, refs=[text])
                before, audits = self.snapshot()
                self.assertRejected(self.router.commit_outcome(env), "kind_not_permitted", before, audits)
                # the same commit without the evidence section is accepted: the refusal is the section, not the kind
                self.assertEqual(self.router.commit_outcome(self.envelope(grant, op, empty_outcome(grant["invocation_id"], "interim_transition")))["status"],
                                 "committed")


class BoundaryValidationTest(CommitCase):
    def test_a_payload_digest_that_does_not_match_the_bytes_is_refused(self) -> None:
        env = self.final_envelope()
        good = self.spool.blobs[env["payload_digest"]]
        before, audits = self.snapshot()
        self.spool.blobs[env["payload_digest"]] = good.replace(b"final_outcome", b"final_outcomf")  # bytes changed, label kept
        self.assertRejected(self.router.commit_outcome(env), "payload_digest_mismatch", before, audits)
        self.spool.blobs[env["payload_digest"]] = good
        self.assertRejected(self.router.commit_outcome({**env, "payload_size_bytes": len(good) - 1}), "payload_digest_mismatch", before, audits + 1)
        del self.spool.blobs[env["payload_digest"]]
        self.assertRejected(self.router.commit_outcome(env), "payload_missing", before, audits + 2)
        self.spool.blobs[env["payload_digest"]] = good
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")

    def test_a_result_ref_whose_label_is_not_its_bytes_is_refused(self) -> None:
        ref = self.artifact(b"packet bytes")
        env = self.final_envelope(result_refs=[ref])
        self.spool.blobs[ref["content_hash"]] = b"packet bytez"
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "payload_digest_mismatch", before, audits)
        self.spool.blobs[ref["content_hash"]] = b"packet bytes"
        self.assertRejected(self.router.commit_outcome({**env, "result_refs": [{**ref, "size_bytes": 13}]}), "payload_digest_mismatch", before, audits + 1)
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")

    def test_a_schema_invalid_document_is_refused(self) -> None:
        outcome = empty_outcome("inv_research01", "interim_transition")
        del outcome["exports"]
        env = self.envelope(self.grant, "op_interim0001", outcome)
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "payload_invalid", before, audits)
        duplicate = b'{"outcome_version": "outcome/1", "outcome_version": "outcome/1"}'  # a duplicate key (C-13)
        self.assertRejected(self.router.commit_outcome({**env, "payload_digest": self.spool.put(duplicate), "payload_size_bytes": len(duplicate)}),
                            "payload_invalid", before, audits + 1)

    def test_an_impossible_timestamp_is_refused(self) -> None:
        outcome = empty_outcome("inv_research01", "interim_transition")
        outcome["review_triggers"] = [{"reason_code": "persistent_contradiction", "cause_ref": "c", "source_revision": 1, "observed_at": "2026-02-29T00:00:00Z"}]
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(self.envelope(self.grant, "op_interim0001", outcome)), "payload_invalid", before, audits)
        outcome["review_triggers"][0]["observed_at"] = "2028-02-29T00:00:00Z"  # a real leap day
        self.assertEqual(self.router.commit_outcome(self.envelope(self.grant, "op_interim0001", outcome))["status"], "committed")
        env = self.final_envelope()
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome({**env, "submitted_at": "2026-02-31T10:30:00Z"}), "envelope_invalid", before, audits)
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")

    def test_an_oversized_or_non_canonical_envelope_is_refused(self) -> None:
        env = self.final_envelope()
        before, audits = self.snapshot()
        refs = [{"content_hash": "sha256:" + f"{i:064x}", "size_bytes": 1, "media_type": "text/" + "x" * 300} for i in range(256)]  # schema-valid, > 64 KiB
        self.assertRejected(self.router.commit_outcome({**env, "result_refs": refs}), "envelope_invalid", before, audits)
        self.assertRejected(self.router.commit_outcome({**env, "expected_state_revision": float("nan")}), "envelope_invalid", before, audits + 1)
        self.assertRejected(self.router.commit_outcome({**env, "expected_state_revision": 2**53}), "envelope_invalid", before, audits + 2)

    def test_an_envelope_without_an_operation_id_is_not_answered(self) -> None:
        env = self.final_envelope()
        for bad in (None, "op_short", "inv_abcdefgh", 7):
            with self.subTest(bad), self.assertRaises(MalformedRequest):
                self.router.commit_outcome({**env, "operation_id": bad})
        with self.assertRaises(MalformedRequest):
            self.router.commit_outcome(["not", "an", "envelope"])

    def test_an_unknown_topic_reports_no_state_revision(self) -> None:
        env = self.final_envelope()
        response = self.router.commit_outcome({**env, "topic_id": "fleet-a:nowhere"})
        self.assertResponse(response)
        self.assertEqual((response["reason"], response["current_state_revision"]), ("cross_topic", None))  # never 0 (RG-U)
        known = self.router.commit_outcome({**env, "expected_state_revision": 0})
        self.assertEqual((known["reason"], known["current_state_revision"]), ("state_revision_stale", self.state_revision()))


class AtomicityTest(CommitCase):
    """A fault injected at each point inside the transaction leaves no partial
    state; before the transaction nothing was written; after commit the whole
    commit stands. (Raised exceptions here; a killed process in
    test_router_crash.py.)"""

    def busy_outcome(self) -> tuple[dict, list]:
        text = self.artifact(b"claim text")
        outcome = empty_outcome("inv_research01")
        outcome["next_queue_state"] = "queued"
        outcome["claims"] = [{"claim_id": "clm_00000001", "revision": 1, "text_ref": text, "load_bearing": False, "required_access_tier": None}]
        outcome["claim_promotions"] = [{"claim_id": "clm_00000001", "revision": 1}]
        outcome["review_triggers"] = [{"reason_code": "persistent_contradiction", "cause_ref": "c", "source_revision": 1, "observed_at": "2026-09-27T10:00:00Z"}]
        outcome["holds"] = [{"hold_id": "hold_000000000001", "subject_ref": "obligation:O-1", "hold_class": "judgment", "cause": "sources disagree",
                             "recoverability": "needs_decision", "required_authority": "primary", "owner": "primary", "deadline_at": "2026-10-01T00:00:00Z",
                             "clears_when": "adjudicated", "capability_fact_id": None}]
        return outcome, [text]

    def test_a_fault_at_each_point_leaves_nothing_or_everything(self) -> None:
        outcome, refs = self.busy_outcome()
        env = self.final_envelope(outcome=outcome, result_refs=refs)
        points = ("before_validation", "after_validation", "in_transaction:start", "in_transaction:fenced",
                  "in_transaction:receipt", "in_transaction:evidence", "in_transaction:end")
        before, audits = self.snapshot()
        for point in points:
            with self.subTest(point):
                self.faults[point] = RuntimeError(f"injected at {point}")
                with self.assertRaises(RuntimeError):
                    self.router.commit_outcome(env)
                self.assertEqual(self.state(), before)
                self.assertEqual(self.value("SELECT count(*) FROM audit_events"), audits)  # a crash is not a rejection: nothing logged
        self.faults["after_commit"] = RuntimeError("after commit")
        with self.assertRaises(RuntimeError):
            self.router.commit_outcome(env)
        self.assertEqual(self.value("SELECT count(*) FROM operation_receipts"), 1)
        self.assertEqual(self.rows("SELECT status FROM claims"), [("accepted_support",)])
        self.assertEqual(self.value("SELECT count(*) FROM holds"), 1)
        self.assertEqual(self.status(), "queued")
        self.assertEqual(self.router.commit_outcome(env)["status"], "replayed")

    def test_a_store_refusal_inside_the_transaction_rolls_everything_back(self) -> None:
        """The DDL is the second layer: a promotion it refuses (a load-bearing
        claim with no receipt, V-4) undoes the claim written before it in the
        same transaction, and the commit is a refusal."""
        outcome, refs = self.busy_outcome()
        outcome["claims"][0].update(load_bearing=True, required_access_tier="full_text")
        env = self.final_envelope(outcome=outcome, result_refs=refs)
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "payload_invalid", before, audits)
        self.assertIn("V-4", self.value("SELECT json_extract(detail, '$.detail') FROM audit_events ORDER BY rowid DESC LIMIT 1"))

    def test_staged_bytes_are_read_only_outside_transactions(self) -> None:
        """C-3/C-8: validation reads the spool with no transaction open."""
        outcome, refs = self.busy_outcome()
        self.spool.reads.clear()
        self.assertEqual(self.router.commit_outcome(self.final_envelope(outcome=outcome, result_refs=refs))["status"], "committed")
        self.assertTrue(self.spool.reads)
        self.assertEqual([digest for digest, in_txn in self.spool.reads if in_txn], [])

    def test_the_commit_binds_the_bytes_it_validated(self) -> None:
        """C-3: bytes swapped in the spool after validation change nothing: the
        transaction writes what was validated, and the receipt names it."""
        outcome, refs = self.busy_outcome()
        env = self.final_envelope(outcome=outcome, result_refs=refs)
        original = self.spool.blobs[env["payload_digest"]]

        class Swap(Exception):
            pass

        def swap(point: str) -> None:
            if point == "after_validation":
                self.spool.blobs[env["payload_digest"]] = original.replace(b"clm_00000001", b"clm_99999999")
        router = self.make_router(fault=swap)
        receipt = router.commit_outcome(env)["receipt"]
        self.assertEqual(self.rows("SELECT claim_id FROM claims"), [("clm_00000001",)])
        self.assertEqual(receipt["validation"]["validated_hashes"][0], canonical.bytes_digest(original))
