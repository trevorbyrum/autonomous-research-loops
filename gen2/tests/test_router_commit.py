"""commit_outcome: replay and identity, fencing, authority, boundary checks,
atomicity (task 1b, Gate C list).

Trace: design review §5 steps 1-5; INVARIANTS C-2, C-3, C-4, C-5, C-8, C-9,
C-12, C-13, RG-1a, RG-1b, RG-5; BOUNDARIES.md Router (authority from
capability; no caller-supplied role label).

Each rule has an isolated negative — one field of an otherwise committable
envelope changed — and the positive control of the same envelope unchanged.
Oracles: hand-written expected reasons, each generic one pinned to its rule
by the refusal's detail; the store read back with raw SQL (`state()`
compares every table but the audit log, which a rejection appends to by
design: exactly one `commit_rejected` row is asserted). Responses are also
checked against commit-outcome.schema.json#/$defs/response here with the
router's own validator; the independent jsonschema check of what the router
emits is test_router_schemas.RouterDocumentsSatisfyTheOracleTest.

Structural limits: the store is in memory and faults are raised exceptions
(test_router_crash.py kills a real process); the capability is a bearer
string, so these tests show that the router derives authority from it, not
that the process presenting it is who it claims (no transport yet, 1e).
"""
from __future__ import annotations

import copy
import json

from gen2.core import canonical
from gen2.router.schemas import SchemaSet
from gen2.router.service import MalformedRequest
from gen2.tests.router_fixtures import OTHER, TOPIC, RouterTestCase, empty_outcome, h, jcs
from gen2.tests.test_router_schemas import verdicts  # the jsonschema oracle, as a subprocess (a function: nothing here is collected twice)

SCHEMAS = SchemaSet()


class CommitCase(RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.grant = self.started("inv_research01")

    def assertResponse(self, response: dict) -> None:
        self.assertEqual(SCHEMAS.errors(response, "commit-outcome.schema.json#/$defs/response"), [], response)

    def assertRejected(self, response: dict, reason: str, before: dict, audits_before: int, detail: str | None = None) -> None:
        """`detail` pins a generic reason to the rule that must have fired."""
        self.assertResponse(response)
        self.assertEqual(response["status"], "rejected", response)
        self.assertEqual(response.get("reason"), reason, response)
        if detail is not None:
            self.assertIn(detail, response.get("detail", ""))
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
        self.assertRejected(self.router.commit_outcome({**env, "lease": {**env["lease"], "generation": -1}}), "envelope_invalid", before, audits, "/lease/generation")
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
        """G-1 (task 1d): after an amendment approves revision 2, whose
        protocol changed, a result pinned to revision 1 is fenced
        (amendment_pending). test_router_amendments.py has the compatible
        case, which commits under its pins."""
        env = self.final_envelope()
        chash = self.contract_draft(TOPIC, 2)
        self.assertEqual(self.decide("opd_amend0001", "amendment_approval", {"kind": "contract_revision", "revision": 2, "hash": chash})["status"], "applied")
        env["expected_state_revision"] = self.state_revision()
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "amendment_pending", before, audits)

    def test_work_pinned_to_a_superseded_brief_is_not_committed(self) -> None:
        """The same before any contract: a pre-contract pass pinned to brief
        v1 does not commit once v2, whose content changed, is the confirmed
        version (a lineage-only v2 is test_router_amendments.py's)."""
        scoping_topic = OTHER
        self.to_scoping(scoping_topic)
        grant = self.started("inv_scoping01", tid=scoping_topic)
        env = self.final_envelope(grant=grant, outcome=empty_outcome("inv_scoping01", topic=scoping_topic))
        v2 = self.brief(scoping_topic, version=2, feeds="rebuild, or buy")
        self.assertEqual(self.decide("opd_brief0002", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 2, "hash": v2}, scoping_topic)["status"],
                         "applied")
        self.assertEqual(self.rows("SELECT version, status FROM intake_briefs WHERE topic_id = ? ORDER BY version", scoping_topic), [(1, "superseded"), (2, "confirmed")])
        env["expected_state_revision"] = self.state_revision(scoping_topic)
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "amendment_pending", before, audits, "brief brief-1 v1 was superseded (content_changed)")

    def test_a_held_topic_is_left_held(self) -> None:
        """A research pass finishing after its topic was held releases its
        lease into the hold and moves the topic nowhere."""
        env = self.final_envelope(outcome={**empty_outcome("inv_research01"), "next_queue_state": "queued"})
        self.x("UPDATE queue_entries SET status = 'held', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        env["expected_state_revision"] = self.state_revision()
        receipt = self.router.commit_outcome(env)["receipt"]
        self.assertEqual((receipt["effects"]["queue_transition"], receipt["effects"]["lease_release"]["rest_state"]), (None, "held"))
        self.assertEqual(self.status(), "held")

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
                self.assertRejected(self.router.commit_outcome({**env, **label}), "envelope_invalid", before, audits, "/" + next(iter(label)))
                audits += 1
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")

    def test_a_role_label_in_the_outcome_document_is_refused(self) -> None:
        outcome = {**empty_outcome("inv_research01", "interim_transition"), "role": "verifier"}
        env = self.envelope(self.grant, "op_interim0001", outcome)
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "payload_invalid", before, audits, "/role")

    def test_an_outcome_document_is_its_own_invocations(self) -> None:
        """Replaying another invocation's document under this capability is refused."""
        env = self.envelope(self.grant, "op_interim0001", empty_outcome("inv_research99", "interim_transition"))
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "capability_invocation_mismatch", before, audits, "inv_research99")

    def test_only_a_research_pass_proposes_the_next_queue_state(self) -> None:
        checkpoint = self.started("inv_checkpt01", "checkpoint")
        outcome = {**empty_outcome("inv_checkpt01"), "next_queue_state": "queued"}
        env = self.final_envelope(outcome=outcome, grant=checkpoint)
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "kind_not_permitted", before, audits, "next queue state")

    def test_a_capability_acts_only_for_its_own_invocation(self) -> None:
        other = self.started("inv_verify01", "verification")
        env = self.final_envelope()
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome({**env, "capability_id": other["capability_id"]}), "capability_invocation_mismatch", before, audits)
        self.assertRejected(self.router.commit_outcome({**env, "capability_id": "cap_forgedforged"}), "capability_invalid", before, audits + 1)
        del env["capability_id"]
        self.assertRejected(self.router.commit_outcome(env), "envelope_invalid", before, audits + 2, "missing required 'capability_id'")

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

    def test_canonical_bytes_are_staged_or_recorded(self) -> None:
        """V-3: reused canonical bytes are authenticated acquired bytes — the
        receipt's obtained hash must be staged with the commit or recorded."""
        text = self.artifact(b"a load-bearing claim")
        outcome = empty_outcome("inv_research01", "interim_transition")
        outcome["claims"] = [{"claim_id": "clm_00000001", "revision": 1, "text_ref": text, "load_bearing": True, "required_access_tier": "full_text"}]
        self.assertEqual(self.router.commit_outcome(self.envelope(self.grant, "op_capture0001", outcome, refs=[text]))["status"], "committed")
        verifier = self.started("inv_verify01", "verification")
        acquired = self.artifact(b"the source's canonical bytes", "application/pdf")
        receipt = self.verification_receipt(verifier)
        receipt.update(obtained_content_hash=acquired["content_hash"],
                       extraction={"method": "canonical_bytes", "extractor": "x-1", "produced_by_invocation_id": "inv_research01", "validation_ref": None})
        own = {**empty_outcome("inv_verify01", "interim_transition"), "verification_receipts": [receipt]}
        env = self.envelope(verifier, "op_verify0001", own)
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "payload_missing", before, audits, "canonical bytes are not staged")
        self.assertEqual(self.router.commit_outcome(self.envelope(verifier, "op_verify0001", own, refs=[acquired]))["status"], "committed")

    def test_canonical_bytes_recorded_only_for_another_topic_are_not_this_topics(self) -> None:
        """Astra 1c review A6: the same receipt path, the obtained bytes
        recorded only by another topic's commit. Content identity is not
        topic authorization: refused as not staged here, nothing written;
        staged with this commit (in this topic's spool) they are accepted."""
        text = self.artifact(b"a load-bearing claim")
        outcome = empty_outcome("inv_research01", "interim_transition")
        outcome["claims"] = [{"claim_id": "clm_00000001", "revision": 1, "text_ref": text, "load_bearing": True, "required_access_tier": "full_text"}]
        self.assertEqual(self.router.commit_outcome(self.envelope(self.grant, "op_capture0001", outcome, refs=[text]))["status"], "committed")
        self.to_queued(OTHER)
        theirs = self.started("inv_other001", "checkpoint", tid=OTHER)
        raw = b"the source's canonical bytes"
        acquired = {"content_hash": self.spool.put(raw, media_type="application/pdf", topic=OTHER), "size_bytes": len(raw), "media_type": "application/pdf"}
        self.assertEqual(self.router.commit_outcome(self.envelope(theirs, "op_theirs0001", empty_outcome("inv_other001", "interim_transition", topic=OTHER),
                                                                  refs=[acquired]))["status"], "committed")
        verifier = self.started("inv_verify01", "verification")
        receipt = self.verification_receipt(verifier)
        receipt.update(obtained_content_hash=acquired["content_hash"],
                       extraction={"method": "canonical_bytes", "extractor": "x-1", "produced_by_invocation_id": "inv_research01", "validation_ref": None})
        own = {**empty_outcome("inv_verify01", "interim_transition"), "verification_receipts": [receipt]}
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(self.envelope(verifier, "op_verify0001", own)), "payload_missing", before, audits, "canonical bytes are not staged")
        self.spool.put(raw, media_type="application/pdf", topic=TOPIC)
        self.assertEqual(self.router.commit_outcome(self.envelope(verifier, "op_verify0001", own, refs=[acquired]))["status"], "committed")
        self.assertEqual(self.rows("SELECT topic_id FROM artifact_topics WHERE content_hash = ? ORDER BY topic_id", acquired["content_hash"]), [(TOPIC,), (OTHER,)])

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
        """Astra 1b review C2: three separate defects of one committable
        envelope. The wrong-hash bytes are themselves a schema-valid outcome
        document (the research pass proposing `queued` instead of null, which
        it may) of exactly the declared size, so the digest is all that is
        wrong; then the right bytes under a wrong size; then no bytes. The
        right bytes commit."""
        env = self.final_envelope()
        good = self.spool.blobs[env["payload_digest"]]
        other = good.replace(b'"next_queue_state":null', b'"next_queue_state":"queued"')
        self.assertEqual(verdicts((json.loads(other), "outcome-document.schema.json")), [{"oracle": True, "router": True}])
        before, audits = self.snapshot()
        self.spool.blobs[env["payload_digest"]] = other  # bytes changed, label kept, size declared truly
        self.assertRejected(self.router.commit_outcome({**env, "payload_size_bytes": len(other)}), "payload_digest_mismatch", before, audits, "hash to")
        self.spool.blobs[env["payload_digest"]] = good
        self.assertRejected(self.router.commit_outcome({**env, "payload_size_bytes": len(good) - 1}), "payload_digest_mismatch", before, audits + 1, "declared")
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
        self.assertRejected(self.router.commit_outcome(env), "payload_invalid", before, audits, "missing required 'exports'")
        complete = empty_outcome("inv_research01", "interim_transition")
        duplicate = jcs(complete).replace(b"{", b'{"claims":[],', 1)  # the complete document with one key given twice (C-13), Astra 1b review C2
        self.assertEqual(json.loads(duplicate), complete)  # read leniently, it is the document that commits below: the duplicate is its only defect
        self.assertRejected(self.router.commit_outcome({**env, "payload_digest": self.spool.put(duplicate), "payload_size_bytes": len(duplicate)}),
                            "payload_invalid", before, audits + 1, "duplicate object key")
        self.assertEqual(self.router.commit_outcome(self.envelope(self.grant, "op_interim0001", complete))["status"], "committed")

    def test_an_impossible_timestamp_is_refused(self) -> None:
        outcome = empty_outcome("inv_research01", "interim_transition")
        outcome["review_triggers"] = [{"reason_code": "persistent_contradiction", "cause_ref": "c", "source_revision": 1, "observed_at": "2026-02-29T00:00:00Z"}]
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(self.envelope(self.grant, "op_interim0001", outcome)), "payload_invalid", before, audits, "observed_at")
        outcome["review_triggers"][0]["observed_at"] = "2028-02-29T00:00:00Z"  # a real leap day
        self.assertEqual(self.router.commit_outcome(self.envelope(self.grant, "op_interim0001", outcome))["status"], "committed")
        env = self.final_envelope()
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome({**env, "submitted_at": "2026-02-31T10:30:00Z"}), "envelope_invalid", before, audits, "submitted_at")
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")

    def test_an_oversized_or_non_canonical_envelope_is_refused(self) -> None:
        env = self.final_envelope()
        before, audits = self.snapshot()
        refs = [{"content_hash": "sha256:" + f"{i:064x}", "size_bytes": 1, "media_type": "text/" + "x" * 300} for i in range(256)]  # schema-valid, > 64 KiB
        self.assertRejected(self.router.commit_outcome({**env, "result_refs": refs}), "envelope_invalid", before, audits, "exceeds")
        self.assertRejected(self.router.commit_outcome({**env, "expected_state_revision": float("nan")}), "envelope_invalid", before, audits + 1, "C-13")
        self.assertRejected(self.router.commit_outcome({**env, "expected_state_revision": 2**53}), "envelope_invalid", before, audits + 2, "C-13")

    def test_the_document_is_for_the_envelopes_operation_kind(self) -> None:
        env = self.envelope(self.grant, "op_interim0001", empty_outcome("inv_research01", "final_outcome"), operation_kind="interim_transition")
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(env), "payload_invalid", before, audits, "another operation kind")

    def test_an_artifact_is_one_record_whoever_references_it(self) -> None:
        """A10: a reference to recorded bytes must agree with the recorded
        size and media type."""
        ref = self.artifact(b"packet")
        first = self.envelope(self.grant, "op_interim0001", empty_outcome("inv_research01", "interim_transition"), refs=[ref])
        self.assertEqual(self.router.commit_outcome(first)["status"], "committed")
        second = self.envelope(self.grant, "op_interim0002", empty_outcome("inv_research01", "interim_transition"), refs=[{**ref, "media_type": "text/html"}])
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(second), "payload_invalid", before, audits, "is recorded as")

    def test_an_artifact_recorded_meanwhile_is_held_to_what_was_validated(self) -> None:
        """Astra 1b review A4: two topics stage the same bytes. This commit
        validates them as text/html while no artifact row exists; before its
        transaction, another topic's commit records them. Inside the
        transaction the recorded metadata is compared again (a row read; no
        bytes are read or hashed there): recorded as text/plain, this commit
        is refused and the other stands; recorded as text/html, the same
        interleaving commits both. Different topics, so no state-revision
        fence hides the race."""
        self.to_queued(OTHER)
        theirs = self.started("inv_other001", "checkpoint", tid=OTHER)
        for n, (their_media, ours_expected) in enumerate((("text/plain", "rejected"), ("text/html", "committed")), start=1):
            with self.subTest(their_media):
                ours_ref = self.artifact(f"identical bytes {n}".encode(), "text/html")
                their_ref = {**ours_ref, "media_type": their_media}
                self.spool.put(f"identical bytes {n}".encode(), media_type=their_media, topic=OTHER)  # the other topic's own spool entry (C-9)
                ours = {**empty_outcome("inv_research01", "interim_transition"),
                        "claims": [{"claim_id": f"clm_ours000{n}", "revision": 1, "text_ref": ours_ref, "load_bearing": False, "required_access_tier": None}]}
                their_outcome = {**empty_outcome("inv_other001", "interim_transition", topic=OTHER),
                                 "claims": [{"claim_id": f"clm_their00{n}", "revision": 1, "text_ref": their_ref, "load_bearing": False, "required_access_tier": None}]}
                their_env = self.envelope(theirs, f"op_theirs000{n}", their_outcome, refs=[their_ref])
                ours_env = self.envelope(self.grant, f"op_ours00000{n}", ours, refs=[ours_ref])
                other_router, interleaved = self.make_router(), []
                router = self.make_router(fault=lambda point: interleaved.append(other_router.commit_outcome(their_env)["status"]) if point == "after_validation" else None)
                out = router.commit_outcome(ours_env)
                self.assertEqual(interleaved, ["committed"])
                self.assertEqual(out["status"], ours_expected, out)
                self.assertEqual(self.rows("SELECT media_type FROM artifacts WHERE content_hash = ?", ours_ref["content_hash"]), [(their_media,)])
                self.assertEqual(self.value("SELECT count(*) FROM claims WHERE claim_id = ?", f"clm_ours000{n}"), 1 if ours_expected == "committed" else 0)
                self.assertEqual(self.rows("SELECT topic_id FROM artifact_topics WHERE content_hash = ? ORDER BY topic_id", ours_ref["content_hash"]),
                                 [(TOPIC,), (OTHER,)] if ours_expected == "committed" else [(OTHER,)])  # A6: each topic's own authorization
                if ours_expected == "rejected":
                    self.assertEqual((out["reason"], self.value("SELECT count(*) FROM operation_receipts WHERE operation_id = ?", ours_env["operation_id"])),
                                     ("payload_invalid", 0))
                    self.assertIn("recorded meanwhile as 17 bytes of text/plain", out.get("detail", ""))

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
        self.assertEqual((response.get("reason"), response.get("current_state_revision")), ("cross_topic", None))  # never 0 (RG-U)
        known = self.router.commit_outcome({**env, "expected_state_revision": 0})
        self.assertEqual((known.get("reason"), known.get("current_state_revision")), ("state_revision_stale", self.state_revision()))


class TopicAuthorizationTest(CommitCase):
    """Astra 1c review A6 and the Q6 ruling (C-9, RG-5): an artifact reference
    resolves to bytes staged with the commit or recorded for the committing
    invocation's own topic. The artifacts row is one physical record shared
    by every topic that staged the same bytes; which topics may reference it
    is recorded separately (artifact_topics), by each topic's own work.
    Oracles: expected outcomes written by hand; raw SQL read-back."""

    def setUp(self) -> None:
        super().setUp()
        self.to_queued(OTHER)
        self.theirs = self.started("inv_other001", "checkpoint", tid=OTHER)

    def claiming(self, grant: dict, op: str, claim_id: str, ref: dict, *, refs=()) -> dict:
        outcome = {**empty_outcome(grant["invocation_id"], "interim_transition", topic=grant["topic_id"]),
                   "claims": [{"claim_id": claim_id, "revision": 1, "text_ref": ref, "load_bearing": False, "required_access_tier": None}]}
        return self.envelope(grant, op, outcome, refs=refs)

    def recorded_for_other(self, text: bytes) -> dict:
        ref = {"content_hash": self.spool.put(text, media_type="text/plain", topic=OTHER), "size_bytes": len(text), "media_type": "text/plain"}
        self.assertEqual(self.router.commit_outcome(self.claiming(self.theirs, "op_theirs0001", "clm_theirs001", ref, refs=[ref]))["status"], "committed")
        return ref

    def test_bytes_recorded_only_for_another_topic_are_not_referenced_by_hash(self) -> None:
        ref = self.recorded_for_other(b"their claim text")
        before, audits = self.snapshot()
        self.assertRejected(self.router.commit_outcome(self.claiming(self.grant, "op_ours0000001", "clm_ours0001", ref)), "payload_missing", before, audits,
                            "recorded only for another topic")
        self.assertEqual(self.rows("SELECT topic_id FROM artifact_topics WHERE content_hash = ?", ref["content_hash"]), [(OTHER,)])

    def test_bytes_recorded_for_this_topic_are_referenced_by_hash(self) -> None:
        text = b"our claim text"
        ref = {"content_hash": self.spool.put(text, media_type="text/plain", topic=TOPIC), "size_bytes": len(text), "media_type": "text/plain"}
        self.assertEqual(self.router.commit_outcome(self.claiming(self.grant, "op_ours0000001", "clm_ours0001", ref, refs=[ref]))["status"], "committed")
        self.assertEqual(self.rows("SELECT topic_id, recorded_by_invocation_id FROM artifact_topics WHERE content_hash = ?", ref["content_hash"]),
                         [(TOPIC, "inv_research01")])
        self.assertEqual(self.router.commit_outcome(self.claiming(self.grant, "op_ours0000002", "clm_ours0002", ref))["status"], "committed")  # by hash alone

    def test_the_same_bytes_staged_by_this_topic_are_its_own(self) -> None:
        ref = self.recorded_for_other(b"shared text")
        self.spool.put(b"shared text", media_type="text/plain", topic=TOPIC)  # this topic's own spool entry of the same bytes
        self.assertEqual(self.router.commit_outcome(self.claiming(self.grant, "op_ours0000001", "clm_ours0001", ref, refs=[ref]))["status"], "committed")
        self.assertEqual(self.rows("SELECT topic_id, staged_by_invocation_id FROM artifacts WHERE content_hash = ?", ref["content_hash"]),
                         [(OTHER, "inv_other001")])  # one physical record: the first stager's
        self.assertEqual(self.rows("SELECT topic_id, recorded_by_invocation_id FROM artifact_topics WHERE content_hash = ? ORDER BY topic_id", ref["content_hash"]),
                         [(TOPIC, "inv_research01"), (OTHER, "inv_other001")])

    def test_bytes_another_topic_records_meanwhile_do_not_become_this_topics(self) -> None:
        """Concurrent insertion: another topic records the bytes just before
        this commit validates its reference by hash. Refused (they are that
        topic's); the other commit stands. Control: the same interleaving,
        this commit staging the bytes itself, commits both."""
        text = b"racing text"
        ref = {"content_hash": self.spool.put(text, media_type="text/plain", topic=OTHER), "size_bytes": len(text), "media_type": "text/plain"}
        theirs = self.claiming(self.theirs, "op_theirs0001", "clm_theirs001", ref, refs=[ref])
        other_router, interleaved = self.make_router(), []
        router = self.make_router(fault=lambda point: interleaved.append(other_router.commit_outcome(theirs)["status"]) if point == "before_validation" else None)
        out = router.commit_outcome(self.claiming(self.grant, "op_ours0000001", "clm_ours0001", ref))
        self.assertEqual((interleaved, out["status"], out.get("reason")), (["committed"], "rejected", "payload_missing"))
        self.assertEqual(self.value("SELECT count(*) FROM claims WHERE claim_id = 'clm_ours0001'"), 0)
        self.spool.put(text, media_type="text/plain", topic=TOPIC)
        out = self.router.commit_outcome(self.claiming(self.grant, "op_ours0000002", "clm_ours0002", ref, refs=[ref]))
        self.assertEqual(out["status"], "committed")
        self.assertEqual(self.rows("SELECT topic_id FROM artifact_topics WHERE content_hash = ? ORDER BY topic_id", ref["content_hash"]), [(TOPIC,), (OTHER,)])


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
        self.assertRejected(self.router.commit_outcome(env), "payload_invalid", before, audits, "V-4")
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
