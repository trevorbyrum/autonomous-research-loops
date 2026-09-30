"""Constraint tests for the gen-2 store DDL draft: evidence, verification and
accepted support, screening and decision receipts, holds (mostly
gen2/store/schema/03-evidence-and-decisions.sql).

Split from test_store_ddl.py by concern (task 2r): the classes, their
methods and assertions are unchanged.

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

import sqlite3
import unittest

from gen2.tests.store_fixtures import OTHER, TOPIC, StoreTestCase, T, h


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
        self.quote_check("qc-1")

    def second_research_pass(self) -> None:
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.lease("lease_bbbbbbbb", 3)
        self.invocation("inv_qqqqqqqq", lease="lease_bbbbbbbb")

    def test_producer_cannot_verify_itself(self) -> None:
        # Realistic case: the research-pass producer names itself as verifier (the role trigger fires first).
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", verifier="inv_pppppppp", extraction="inv_pppppppp")
        self.assertIn("separate verification invocation", str(ctx.exception))
        # Isolate the producer != verifier CHECK: a claim whose producer is itself a
        # verification-kind invocation passes the role trigger, so only the CHECK can refuse it.
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000001', 2, ?, ?, 'inv_vvvvvvvv', 0, NULL, 'provisional', ?)", TOPIC, h("7"), T)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000002", claim=("clm_00000001", 2), quote=("not_applicable", None), producer="inv_vvvvvvvv", use="sampled")  # not load-bearing: sampled
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.verify("ver_00000001")

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

    def test_requested_by_is_same_topic_and_never_self(self) -> None:
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_vvvvvvvv'", T)
        self.lease("lease_wwwwwwww", 4, scope="verification")
        self.rejects("same topic", *self.raw_invocation(invocation_id="inv_reqdver1", kind="verification", lease_id="lease_wwwwwwww", requested_by_invocation_id="inv_oooooooo"))
        self.rejects("same topic", *self.raw_invocation(invocation_id="inv_reqdver1", kind="verification", lease_id="lease_wwwwwwww", requested_by_invocation_id="inv_reqdver1"))
        self.invocation("inv_reqdver1", kind="verification", lease="lease_wwwwwwww", requested_by="inv_pppppppp")

    def test_receipt_must_name_the_claims_real_producer(self) -> None:
        self.second_research_pass()
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", producer="inv_qqqqqqqq")
        self.assertIn("independent of the claim producer", str(ctx.exception))

    def test_producer_unvalidated_extraction_rejected(self) -> None:
        """D28 rewrite (A6/B6): the prohibited thing is the producer's selected or
        unvalidated extraction — not authenticated canonical bytes the producer
        acquired. Negatives: an unvalidated producer extraction (as a
        'validated' one without its validation, or passed off as the verifier's
        own); canonical bytes without an authenticated acquisition or not a
        staged artifact. Positives: canonical-byte reuse of producer-acquired
        bytes; a validated producer extraction."""
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", method="validated_extraction", extraction="inv_pppppppp", validation=None)
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", method="verifier_extraction", extraction="inv_pppppppp")
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", method="canonical_bytes", extraction="inv_pppppppp", gateway=None)
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", method="canonical_bytes", extraction="inv_pppppppp", obtained=h("0"))
        self.assertIn("authenticated canonical bytes", str(ctx.exception))
        self.verify("ver_00000001", method="canonical_bytes", extraction="inv_pppppppp")  # producer-acquired canonical bytes
        self.verify("ver_00000002", method="validated_extraction", extraction="inv_pppppppp", validation="validation-7")

    def test_supports_cannot_exceed_obtained_tier(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", tier="abstract", required="full_text")
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.verify("ver_00000001", tier="abstract", required="full_text", verdict="cannot_assess_at_required_tier")

    ACCEPT = "UPDATE claims SET status = 'accepted_support' WHERE claim_id = 'clm_00000001' AND revision = 1"
    PROMOTION_REFUSED = "needs a supporting load-bearing-use verification receipt"

    def claim_status(self) -> list[tuple]:
        return self.rows("SELECT status FROM claims WHERE claim_id = 'clm_00000001' AND revision = 1")

    def test_accepted_support_needs_receipt_at_required_tier(self) -> None:
        self.rejects(self.PROMOTION_REFUSED, self.ACCEPT)  # no receipt at all
        self.verify("ver_00000001", use="sampled", tier="abstract", required="abstract")  # supports, but a sample, and only at abstract
        self.rejects(self.PROMOTION_REFUSED, self.ACCEPT)
        self.verify("ver_00000002", tier="full_text", required="full_text")
        self.x(self.ACCEPT)

    def test_sampling_never_qualifies_a_load_bearing_claim(self) -> None:
        """RA5. The review's probe: on the load-bearing, full-text claim, a
        full-text 'supports' receipt with use='sampled', all four substantive
        checks not_checked, a matched quote and an adjudication record. It is a
        truthful sampling receipt and is stored as one, but promotion reads the
        claim's own designation and refuses it. So is a *successful* sampling
        receipt (every check performed and passed): sampling is not
        load-bearing qualification. A load-bearing partial support does not
        qualify either. Only a load-bearing-use 'supports' receipt with every
        check performed promotes; the claim reads back provisional after each
        refusal."""
        unperformed = {name: "not_checked" for name in self.CHECKS_OK}
        adjudicated = {"adjudication_ref": "adj-1", "resolved_at": T, "resolution": "sampled; not re-checked"}
        self.verify("ver_sample01", use="sampled", checks=unperformed, adjudication=adjudicated)
        self.rejects(self.PROMOTION_REFUSED, self.ACCEPT)
        self.verify("ver_sample02", use="sampled")  # successful sampling
        self.rejects(self.PROMOTION_REFUSED, self.ACCEPT)
        self.verify("ver_partial1", verdict="partially_supports")  # load-bearing use, checks performed, not support
        self.rejects(self.PROMOTION_REFUSED, self.ACCEPT)
        self.assertEqual(self.claim_status(), [("provisional",)])
        self.verify("ver_lb000001")  # genuine load-bearing qualification
        self.x(self.ACCEPT)
        self.assertEqual(self.claim_status(), [("accepted_support",)])

    def test_load_bearing_receipt_states_its_claims_designation(self) -> None:
        """RA5: a receipt requested for load-bearing use must be about a
        load-bearing claim at that claim's own required tier — it cannot
        re-describe the subject it certifies. A sampled receipt may audit any
        claim at any tier. (clm_00000002 is not load-bearing but does carry a
        full-text tier, so the load-bearing conjunct alone refuses it.)"""
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000002', 1, ?, ?, 'inv_pppppppp', 0, 'full_text', 'provisional', ?)", TOPIC, h("7"), T)
        self.quote_check("qc-2", claim=("clm_00000002", 1))
        refused = "that claim's own required tier"
        for label, kw in (("a higher required tier than the claim's", dict(tier="reproduced", required="reproduced")),
                          ("a lower required tier than the claim's", dict(tier="abstract", required="abstract")),
                          ("a claim that is not load-bearing", dict(claim=("clm_00000002", 1), quote=("matched", "qc-2")))):
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.verify("ver_00000001", **kw)
                self.assertIn(refused, str(ctx.exception))
        self.assertEqual(self.rows("SELECT count(*) FROM verification_receipts"), [(0,)])
        self.verify("ver_00000001", use="sampled", tier="abstract", required="abstract")
        self.verify("ver_00000002", use="sampled", claim=("clm_00000002", 1), quote=("matched", "qc-2"))
        self.verify("ver_00000003")  # the claim's own designation

    def test_claims_start_provisional(self) -> None:
        self.rejects("claims are captured provisional", "INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000002', 1, ?, ?, 'inv_pppppppp', 0, NULL, 'accepted_support', ?)", TOPIC, h("7"), T)

    def test_nli_alarm_quarantines_the_quote(self) -> None:
        """D32 + the byte-mismatch test the review found missing: an NLI alarm
        and an exact-byte mismatch each quarantine the quote."""
        insert = "INSERT INTO quote_checks (check_id, claim_id, claim_revision, source_artifact_hash, span_start, span_end, normalization_version, exact_match, nli_checker, nli_checker_version, nli_signal, quote_quarantined, checked_at) VALUES (?, 'clm_00000001', 1, ?, 0, 5, 'n1', ?, 'minicheck', '1', ?, ?, ?)"
        self.rejects("CHECK constraint failed", insert, "qc-2", h("7"), "matched", "alarm", 0, T)
        self.x(insert, "qc-2", h("7"), "matched", "alarm", 1, T)
        self.rejects("CHECK constraint failed", insert, "qc-3", h("7"), "mismatch", "pass", 0, T)
        self.x(insert, "qc-3", h("7"), "mismatch", "pass", 1, T)

    def test_support_needs_successful_checks_or_adjudication(self) -> None:
        """A6: 'supports' with an adverse or unperformed check, or a tier-0 alarm,
        is refused unless an explicit adjudication resolves it; a mismatched
        quote can never support."""
        adjudicated = {"adjudication_ref": "adj-1", "resolved_at": T, "resolution": "operator ruled the qualification immaterial"}
        n = 0
        for name in ("numeric_units", "denominators", "negation", "qualifications"):
            for status in ("checked_problem", "not_checked", "unavailable"):
                with self.subTest(check=name, status=status):
                    n += 1
                    checks = dict(self.CHECKS_OK, **{name: status})
                    with self.assertRaises(sqlite3.IntegrityError) as ctx:
                        self.verify(f"ver_{n:08d}", checks=checks)
                    self.assertIn("CHECK constraint failed", str(ctx.exception))
                    if status == "checked_problem":
                        self.verify(f"ver_{n:08d}", checks=checks, adjudication=adjudicated)
        self.quote_check("qc-alarm", nli="alarm")
        with self.assertRaises(sqlite3.IntegrityError):
            self.verify("ver_alarm001", tier0="alarm")
        self.verify("ver_alarm001", tier0="alarm", adjudication=adjudicated)
        self.quote_check("qc-mism", match="mismatch")
        with self.assertRaises(sqlite3.IntegrityError):  # the quarantine binding refuses it; the CHECK is a second layer
            self.verify("ver_mismatch", quote=("mismatch", "qc-mism"), adjudication=adjudicated)

    def test_absent_keys_are_not_passes(self) -> None:
        """SQLite passes a CHECK that evaluates to NULL, so an absent JSON key must
        fail closed: 'supports' with an adverse check and NO adjudication key, or
        with no exact-quote status, is refused like an explicit null."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.verify("ver_00000001", checks=dict(self.CHECKS_OK, numeric_units="checked_problem"), drop=("adjudication",))
        with self.assertRaises(sqlite3.IntegrityError):
            self.verify("ver_00000002", quote=("not_applicable", None), drop=("checks.exact_quote.status",))
        self.verify("ver_00000001", drop=("adjudication",))  # all checks succeeded: the absent adjudication is not needed

    def test_truthful_unsuccessful_verdicts_may_record_unperformed_checks(self) -> None:
        """A6 (the over-restriction): a load-bearing cannot_assess or
        does_not_support receipt may truthfully report not_checked/unavailable;
        a load-bearing partial-support verdict may not."""
        unperformed = {"numeric_units": "not_checked", "denominators": "unavailable", "negation": "not_checked", "qualifications": "unavailable"}
        self.verify("ver_00000001", tier="abstract", verdict="cannot_assess_at_required_tier", checks=unperformed, quote=("not_applicable", None))
        self.verify("ver_00000002", verdict="does_not_support", checks=unperformed)
        with self.assertRaises(sqlite3.IntegrityError):
            self.verify("ver_00000003", verdict="partially_supports", checks=unperformed)
        self.verify("ver_00000004", verdict="partially_supports", checks=dict(self.CHECKS_OK, numeric_units="checked_problem"))

    def test_quote_check_binding(self) -> None:
        """A6/A10: the receipt's quote check is of this claim revision, against the
        receipt's source artifact, with the receipt's match status; support never
        rests on a quarantined quote without adjudication."""
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000001', 2, ?, ?, 'inv_pppppppp', 1, 'full_text', 'provisional', ?)", TOPIC, h("7"), T)
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'text/plain', ?)", h("8"), T)
        self.quote_check("qc-rev2", claim=("clm_00000001", 2))
        self.quote_check("qc-src8", source=h("8"))
        self.quote_check("qc-mism", match="mismatch")
        self.quote_check("qc-alarm", nli="alarm")
        refused = "unquarantined quote check of this claim"
        for label, kw in (("other claim revision", dict(quote=("matched", "qc-rev2"))),
                          ("other source artifact", dict(quote=("matched", "qc-src8"))),
                          ("status disagrees", dict(verdict="does_not_support", quote=("matched", "qc-mism"))),
                          ("quarantined by alarm", dict(quote=("matched", "qc-alarm")))):
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.verify("ver_00000001", **kw)
                self.assertIn(refused, str(ctx.exception))
        self.verify("ver_00000001", quote=("matched", "qc-alarm"), adjudication={"adjudication_ref": "adj-1", "resolved_at": T, "resolution": "entailment confirmed on re-read"})
        self.verify("ver_00000002", verdict="does_not_support", quote=("mismatch", "qc-mism"))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000003", quote=("matched", None))  # a matched quote names its check
        self.assertIn("CHECK constraint failed", str(ctx.exception))

    def test_receipt_row_matches_its_json(self) -> None:
        """A10: every normalized column equals its field in the immutable receipt
        JSON. Each probe keeps the columns valid (so the role, quote and
        capability triggers pass) and changes only the JSON field, so only the
        binding CHECK can refuse it — including the review's probe (JSON
        does_not_support while the column says supports)."""
        spans = [{"start": 0, "end": 9, "locator": {"kind": "page", "value": "3"}}]
        acq = {"route": "gateway:other", "retrieved_at": T, "gateway_call_ref": "gw-call-1", "cache_reuse": False}
        ext = {"method": "verifier_extraction", "extractor": "x-1", "produced_by_invocation_id": "inv_other000", "validation_ref": None}
        probes = {
            "verification_receipt_id": "ver_other000", "topic_id": OTHER,
            "claim": {"claim_id": "clm_other000", "claim_revision": 1}, "claim.revision": {"claim_id": "clm_00000001", "claim_revision": 2},
            "source": {"work_id": "wrk_other000", "source_version": "v1"}, "source.version": {"work_id": "wrk_00000001", "source_version": "v2"},
            "cited_spans": spans, "obtained_content_hash": h("0"), "access_tier": "reproduced",
            "requested_for": {"use": "sampled", "required_access_tier": "full_text"}, "requested_for.tier": {"use": "load_bearing", "required_access_tier": "abstract"},
            "acquisition": acq, "extraction": ext, "extraction.method": dict(ext, method="canonical_bytes", produced_by_invocation_id="inv_vvvvvvvv"),
            "extraction.validation_ref": dict(ext, produced_by_invocation_id="inv_vvvvvvvv", validation_ref="v-1"),
            "producer_invocation_id": "inv_other000", "verifier_invocation_id": "inv_other000", "quote_check_id": "qc-other", "verdict": "does_not_support",
        }
        for label, value in probes.items():
            with self.subTest(field=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.verify("ver_00000001", receipt_overrides={label.split(".")[0]: value})
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.verify("ver_00000001")

    def test_receipt_names_the_verifiers_own_capability(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", capability="cap_pppppppp")
        self.assertIn("verifier capability", str(ctx.exception))
        self.verify("ver_00000001")


class ContractAdmittedSupportTest(StoreTestCase):
    """V-10 (task 1a): accepted support needs contract-admitted production, for
    every claim, from provisional or contested, independently of V-4's
    receipt. The history: a scoping research pass (pre-contract, pinned to the
    confirmed brief; the topic has only a draft contract) captures
    load-bearing, full-text claim clm_00000001 revision 1; the contract is
    then approved, and a contract-admitted research pass and a verification
    invocation are admitted. The expected outcome of every promotion is
    written by hand, and each refusal is read back."""

    SET_STATUS = "UPDATE claims SET status = ? WHERE claim_id = ? AND revision = ?"
    NEEDS_ADMISSION = "accepted support needs contract-admitted production"
    NEEDS_RECEIPT = "needs a supporting load-bearing-use verification receipt"
    SCOPING, ADMITTED = "inv_scoping1", "inv_pppppppp"

    def setUp(self) -> None:
        super().setUp()
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'text/plain', ?)", h("7"), T)
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        self.lease("lease_rrrrrrrr", 1)
        self.invocation(self.SCOPING, lease="lease_rrrrrrrr", pre_contract=True)
        self.claim("clm_00000001", 1, self.SCOPING)
        self.approve_contract(TOPIC, 1)
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_rrrrrrrr'", T)
        self.lease("lease_aaaaaaaa", 2)
        self.invocation(self.ADMITTED, lease="lease_aaaaaaaa")
        self.lease("lease_vvvvvvvv", 3, scope="verification")
        self.invocation("inv_vvvvvvvv", kind="verification", lease="lease_vvvvvvvv")
        self.assertEqual(self.rows("SELECT invocation_id, admission_context FROM invocations WHERE invocation_id IN (?, ?) ORDER BY invocation_id", self.SCOPING, self.ADMITTED),
                         [(self.ADMITTED, "contract/1"), (self.SCOPING, "pre-contract/1")])

    def claim(self, cid: str, rev: int, producer: str, *, load_bearing: bool = True, tid: str = TOPIC) -> None:
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, 'provisional', ?)", cid, rev, tid, h("7"), producer, int(load_bearing), "full_text" if load_bearing else None, T)

    def qualifying_receipt(self, rid: str, cid: str, rev: int, producer: str) -> None:
        """A receipt meeting V-4 in full for a load-bearing full-text claim:
        requested for load-bearing use at full text, obtained at full text,
        every substantive check performed and passed, a matched quote check of
        this claim revision, verdict supports, by the separate verifier."""
        self.quote_check("qc-" + rid, claim=(cid, rev))
        self.verify(rid, claim=(cid, rev), producer=producer, quote=("matched", "qc-" + rid))

    def status(self, cid: str, rev: int = 1) -> str:
        return self.rows("SELECT status FROM claims WHERE claim_id = ? AND revision = ?", cid, rev)[0][0]

    def test_pre_contract_claim_with_a_qualifying_receipt_is_refused(self) -> None:
        """First isolated negative. The scoping claim gets a receipt that meets
        V-4 in full; only admission is missing, so promotion is refused and
        the claim reads back provisional. Control: the same receipt shape
        promotes a claim the contract-admitted pass produced."""
        self.qualifying_receipt("ver_00000001", "clm_00000001", 1, self.SCOPING)
        self.rejects(self.NEEDS_ADMISSION, self.SET_STATUS, "accepted_support", "clm_00000001", 1)
        self.assertEqual(self.status("clm_00000001"), "provisional")
        self.claim("clm_00000002", 1, self.ADMITTED)
        self.qualifying_receipt("ver_00000002", "clm_00000002", 1, self.ADMITTED)
        self.x(self.SET_STATUS, "accepted_support", "clm_00000002", 1)
        self.assertEqual(self.status("clm_00000002"), "accepted_support")

    def test_every_claim_needs_admission_not_only_load_bearing(self) -> None:
        """V-4's receipt rule reads load-bearing claims only; V-10 reads every
        claim. A non-load-bearing scoping claim, which no receipt rule
        touches, is refused; the same claim by the contract-admitted pass
        promotes."""
        self.claim("clm_00000004", 1, self.SCOPING, load_bearing=False)
        self.rejects(self.NEEDS_ADMISSION, self.SET_STATUS, "accepted_support", "clm_00000004", 1)
        self.assertEqual(self.status("clm_00000004"), "provisional")
        self.claim("clm_00000005", 1, self.ADMITTED, load_bearing=False)
        self.x(self.SET_STATUS, "accepted_support", "clm_00000005", 1)

    def test_contract_admitted_claim_without_a_receipt_is_refused(self) -> None:
        """Second isolated negative: V-10 does not replace V-4. The
        contract-admitted pass's load-bearing claim, with no receipt, is
        refused for want of one. A non-load-bearing claim of the same pass
        promotes, so this producer meets V-10 and the receipt is the only
        thing missing. With a qualifying receipt the load-bearing claim
        promotes."""
        self.claim("clm_00000002", 1, self.ADMITTED)
        self.claim("clm_00000003", 1, self.ADMITTED, load_bearing=False)
        self.x(self.SET_STATUS, "accepted_support", "clm_00000003", 1)
        self.rejects(self.NEEDS_RECEIPT, self.SET_STATUS, "accepted_support", "clm_00000002", 1)
        self.assertEqual(self.status("clm_00000002"), "provisional")
        self.qualifying_receipt("ver_00000002", "clm_00000002", 1, self.ADMITTED)
        self.x(self.SET_STATUS, "accepted_support", "clm_00000002", 1)
        self.assertEqual(self.status("clm_00000002"), "accepted_support")

    def test_adopted_pre_contract_claim_with_a_receipt_is_allowed(self) -> None:
        """Adoption (Astra ruling 4 on RA3): the contract-admitted pass writes
        revision 2 of the scoping claim, same text, as its own production;
        with a qualifying receipt of revision 2 it promotes. Adoption is per
        revision: revision 1, with a qualifying receipt of its own, is still
        refused, and so is revision 3, which only relabels the scoping pass as
        a new revision's producer. Every revision is kept."""
        self.claim("clm_00000001", 2, self.ADMITTED)
        self.qualifying_receipt("ver_00000002", "clm_00000001", 2, self.ADMITTED)
        self.x(self.SET_STATUS, "accepted_support", "clm_00000001", 2)
        self.qualifying_receipt("ver_00000001", "clm_00000001", 1, self.SCOPING)
        self.rejects(self.NEEDS_ADMISSION, self.SET_STATUS, "accepted_support", "clm_00000001", 1)
        self.claim("clm_00000001", 3, self.SCOPING)
        self.qualifying_receipt("ver_00000003", "clm_00000001", 3, self.SCOPING)
        self.rejects(self.NEEDS_ADMISSION, self.SET_STATUS, "accepted_support", "clm_00000001", 3)
        self.assertEqual(self.rows("SELECT revision, producer_invocation_id, status FROM claims WHERE claim_id = 'clm_00000001' ORDER BY revision"),
                         [(1, self.SCOPING, "provisional"), (2, self.ADMITTED, "accepted_support"), (3, self.SCOPING, "provisional")])

    def test_contested_to_accepted_support_follows_the_same_rule(self) -> None:
        """From contested as from provisional. The scoping claim, with a
        qualifying receipt, is contested (allowed) and then refused
        contested -> accepted_support, staying contested. The
        contract-admitted pass's claim, with a qualifying receipt, makes the
        same moves and is promoted."""
        self.qualifying_receipt("ver_00000001", "clm_00000001", 1, self.SCOPING)
        self.x(self.SET_STATUS, "contested", "clm_00000001", 1)
        self.rejects(self.NEEDS_ADMISSION, self.SET_STATUS, "accepted_support", "clm_00000001", 1)
        self.assertEqual(self.status("clm_00000001"), "contested")
        self.claim("clm_00000002", 1, self.ADMITTED)
        self.qualifying_receipt("ver_00000002", "clm_00000002", 1, self.ADMITTED)
        self.x(self.SET_STATUS, "contested", "clm_00000002", 1)
        self.x(self.SET_STATUS, "accepted_support", "clm_00000002", 1)
        self.assertEqual(self.status("clm_00000002"), "accepted_support")

    def test_the_producer_is_work_of_the_claims_own_topic(self) -> None:
        """Another topic's contract-admitted work is not this topic's
        contract-admitted production. The claims table does not bind a
        producer's topic when a claim is written, so a claim of this topic
        naming the other topic's admitted pass can exist; its promotion is
        refused (not load-bearing, so V-4 plays no part). The same producer's
        claim in its own topic promotes."""
        self.approved_revision(OTHER)
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.claim("clm_00000006", 1, "inv_oooooooo", load_bearing=False)
        self.rejects(self.NEEDS_ADMISSION, self.SET_STATUS, "accepted_support", "clm_00000006", 1)
        self.assertEqual(self.status("clm_00000006"), "provisional")
        self.claim("clm_00000007", 1, "inv_oooooooo", load_bearing=False, tid=OTHER)
        self.x(self.SET_STATUS, "accepted_support", "clm_00000007", 1)


class ObservationTest(StoreTestCase):
    INSERT = ("INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt, lane, request, obligation_ids, started_at, coverage_state, result_count, error_class, capability_fact_id, policy_version, completeness) "
              "VALUES (?, 'inv_pppppppp', ?, ?, 1, 'crossref', '{}', '[]', ?, ?, ?, ?, ?, 'pol1', ?)")

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")

    def obs(self, oid: str, state: str, count, error=None, fact=None, ident: str = "1", completeness: str | None = None) -> None:
        if completeness is None:
            completeness = "complete" if state in ("searched_ok", "searched_empty", "metadata_only") else "unobserved"
        self.x(self.INSERT, oid, TOPIC, h(ident), T, state, count, error, fact, completeness)

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
        self.rejects("inserted current", "INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, superseded_by_fact_id, recorded_at) VALUES ('cf-9', 'secrets_backend', 'failing', 'd', ?, '[]', 'cf-1', ?)", T, T)
        self.assertEqual(self.rows(current), [("cf-2", "healthy")])

    FACT = ("INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, revision, superseded_by_fact_id, "
            "successor_since, successor_state, successor_revision, recorded_at) VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?)")
    LINK = ("UPDATE capability_facts SET superseded_by_fact_id = ?, successor_since = ?, successor_state = ?, successor_revision = ? "
            "WHERE fact_id = ?")

    def fact(self, fact_id: str, revision, behind=None, *, capability="gateway.secrets.vault", state="failing", since=T, detail="d",
             declared=None) -> tuple:
        """A gateway fact inserted `behind` another states that fact's episode and revision as the router does
        (2b-repair-5 F1): what is recorded of it, unless `declared` (since, state, revision) says otherwise."""
        if declared is None and behind is not None and capability.startswith("gateway."):
            declared = self.db.execute("SELECT since, state, revision FROM capability_facts WHERE fact_id = ?", (behind,)).fetchone()
        return (self.FACT, fact_id, capability, state, detail, since, revision, behind, *(declared or (None, None, None)), T)

    def supersede(self, current: str, successor: tuple, declared=None) -> None:
        """The documented transaction: `current` names its successor with the successor's episode and revision
        (as the router states them, unless `declared` says otherwise), then the successor is inserted current.
        Rolled back when refused."""
        fid, state, since, revision = successor[1], successor[3], successor[5], successor[6]
        self.x("BEGIN")
        try:
            self.x(self.LINK, fid, *(declared or (since, state, revision)), current)
            self.x(*successor)
            self.x("COMMIT")
        except sqlite3.IntegrityError:
            self.x("ROLLBACK")
            raise

    def test_a_late_snapshot_is_an_earlier_revision_of_the_current_facts_own_episode(self) -> None:
        """2b-repair-4 F1 (Astra's 2b-repair-3 review, its table): a fact is inserted behind its
        capability's current fact only as a late gateway snapshot: a `gateway.*` fact of the same
        capability, episode (`since`) and state as the current fact, its revision strictly below the
        current fact's. 2b-repair-5 F1: its place (behind the current fact, in its episode) is the insert's
        rule; the rest is the one supersession relation every gateway edge is held to. Each refused insert
        differs from the accepted one in that one respect, and names the rule refusing it; one revision of an
        episode is one snapshot."""
        current = "SELECT fact_id, revision FROM capability_facts WHERE capability = ? AND superseded_by_fact_id IS NULL"
        self.x(*self.fact("cf-3", 3))
        self.x(*self.fact("cf-n3", 3, capability="secrets_backend"))   # not a gateway fact, with revisions
        self.x(*self.fact("cf-o1", None, capability="unrelated.operator"))
        for label, fact, rule in (("an earlier episode", self.fact("cf-2", 2, "cf-3", since="2026-09-24T12:00:00Z"), "inserted current"),
                                  ("a later episode", self.fact("cf-2", 2, "cf-3", since="2026-09-26T12:00:00Z"), "inserted current"),
                                  ("another state since the same instant", self.fact("cf-2", 2, "cf-3", state="degraded"), "gateway_supersession_edge"),
                                  ("a higher revision", self.fact("cf-4", 4, "cf-3"), "gateway_supersession_edge"),
                                  ("the same revision", self.fact("cf-3b", 3, "cf-3", detail="other"), "gateway_supersession_edge"),
                                  ("no revision", self.fact("cf-2", None, "cf-3"), "gateway_fact_snapshot"),
                                  ("not a gateway fact", self.fact("cf-n2", 2, "cf-n3", capability="secrets_backend"), "inserted current"),
                                  ("neither a gateway fact nor revised", self.fact("cf-o0", None, "cf-o1", capability="unrelated.operator"), "inserted current"),
                                  ("another capability's current fact", self.fact("cf-2", 2, "cf-n3"), "FOREIGN KEY constraint failed"),
                                  ("a fact never recorded", self.fact("cf-2", 2, "cf-absent"), "inserted current")):
            with self.subTest(label):
                self.rejects(rule, *fact)
        self.assertEqual(self.rows(current, "gateway.secrets.vault"), [("cf-3", 3)])
        self.x(*self.fact("cf-2", 2, "cf-3"))   # the accepted case
        self.assertEqual(self.rows(current, "gateway.secrets.vault"), [("cf-3", 3)], "the newer fact stays current")
        self.rejects("UNIQUE constraint failed", *self.fact("cf-2b", 2, "cf-3", detail="other"))
        self.assertEqual(self.rows("SELECT fact_id, superseded_by_fact_id FROM capability_facts ORDER BY fact_id"),
                         [("cf-2", "cf-3"), ("cf-3", None), ("cf-n3", None), ("cf-o1", None)])

    def test_supersession_goes_on_past_a_late_snapshot(self) -> None:
        """2b-repair-4 F1: a later snapshot or episode supersedes the current fact as before, with a
        late snapshot behind it; the graph protections hold around it: a late snapshot is inserted
        behind the current fact only (never a superseded one, never an earlier episode behind a
        later), is never another fact's successor, and its revision is pinned like its contents."""
        later = "2026-09-26T12:00:00Z"
        self.x(*self.fact("cf-3", 3))
        self.x(*self.fact("cf-2", 2, "cf-3"))
        self.supersede("cf-3", self.fact("cf-5", 5))   # a later revision of the episode supersedes the current fact
        self.rejects("inserted current", *self.fact("cf-1", 1, "cf-3"))   # behind a fact no longer current
        self.x(*self.fact("cf-4", 4, "cf-5"))   # late again, behind the new current fact
        self.supersede("cf-5", self.fact("cf-l6", 6, since=later))   # a new episode supersedes it
        self.rejects("inserted current", *self.fact("cf-1", 1, "cf-l6"))   # an earlier episode, behind the later one
        self.assertEqual(self.rows("SELECT fact_id, revision, superseded_by_fact_id FROM capability_facts ORDER BY since, revision"),
                         [("cf-2", 2, "cf-3"), ("cf-3", 3, "cf-5"), ("cf-4", 4, "cf-5"), ("cf-5", 5, "cf-l6"), ("cf-l6", 6, None)])
        self.rejects("must be current", "UPDATE capability_facts SET superseded_by_fact_id = 'cf-4' WHERE fact_id = 'cf-l6'")
        self.x("BEGIN")   # the successor another fact names is inserted current, never behind one
        self.x(self.LINK, "cf-l7", later, "failing", 7, "cf-l6")
        self.x(*self.fact("cf-l8", 8, since=later))
        self.rejects("inserted current", *self.fact("cf-l7", 7, "cf-l8", since=later))
        self.x("ROLLBACK")
        self.rejects("CHECK constraint failed", *self.fact("cf-l0", 0, "cf-l6", since=later))
        self.rejects("supersede, never edit", "UPDATE capability_facts SET revision = 9 WHERE fact_id = 'cf-l6'")
        self.assertEqual(self.rows("SELECT fact_id FROM capability_facts WHERE superseded_by_fact_id IS NULL"), [("cf-l6",)])

    def test_every_gateway_supersession_edge_is_the_one_relation(self) -> None:
        """2b-repair-5 F1 (Astra's 2b-repair-4 review, its ordinary-successor table): the ordinary
        supersession transaction — the current fact linked to a successor not yet inserted, then that
        successor inserted — is held to the late snapshot's relation, at the edge. An older revision of
        the episode, the same revision, no revision, another state since the same instant and an older
        episode are refused, whether the current fact states the successor it links truly (the relation's
        CHECK), states a valid one and another is inserted (the deferred foreign key, at COMMIT), or states
        none (the reproduction as written). A higher revision, and a later episode with its revision
        started again, are accepted."""
        earlier, later = "2026-09-24T12:00:00Z", "2026-09-26T12:00:00Z"
        current = "SELECT fact_id FROM capability_facts WHERE capability = 'gateway.secrets.vault' AND superseded_by_fact_id IS NULL"
        self.x(*self.fact("cf-3", 3))
        for label, successor, declared, rule in (
                ("an older revision of the episode", self.fact("cf-n", 2), None, "gateway_supersession_edge"),
                ("the same revision", self.fact("cf-n", 3, detail="other"), None, "gateway_supersession_edge"),
                ("no revision", self.fact("cf-n", None), None, "gateway_supersession_edge"),
                ("another state since the same instant", self.fact("cf-n", 4, state="healthy"), None, "gateway_supersession_edge"),
                ("an older episode", self.fact("cf-n", 4, since=earlier), None, "gateway_supersession_edge"),
                ("an older revision, a higher one stated", self.fact("cf-n", 2), (T, "failing", 4), "FOREIGN KEY constraint failed"),
                ("no revision, one stated", self.fact("cf-n", None), (T, "failing", 4), "gateway_fact_snapshot"),
                ("another state, the same one stated", self.fact("cf-n", 4, state="healthy"), (T, "failing", 4), "FOREIGN KEY constraint failed"),
                ("an older episode, a later one stated", self.fact("cf-n", 4, since=earlier), (later, "failing", 4), "FOREIGN KEY constraint failed")):
            with self.subTest(label):
                with self.assertRaises(sqlite3.IntegrityError) as refused:
                    self.supersede("cf-3", successor, declared)
                self.assertIn(rule, str(refused.exception))
                self.assertEqual(self.rows(current), [("cf-3",)])
        self.rejects("gateway_supersession_edge", "UPDATE capability_facts SET superseded_by_fact_id = 'cf-n' WHERE fact_id = 'cf-3'")
        self.supersede("cf-3", self.fact("cf-4", 4))   # a higher revision of the episode
        self.supersede("cf-4", self.fact("cf-l1", 1, since=later))   # a later episode, its revision started again
        self.assertEqual(self.rows("SELECT fact_id, revision, superseded_by_fact_id FROM capability_facts ORDER BY since, revision"),
                         [("cf-3", 3, "cf-4"), ("cf-4", 4, "cf-l1"), ("cf-l1", 1, None)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_an_episode_is_later_by_its_instant_not_its_text(self) -> None:
        """2b-repair-5 F1: which episode is later is decided by instants, a fraction's digits counted as
        time whatever the text sorts as: "...:00Z" sorts after "...:00.5Z" and is half a second before it."""
        self.x(*self.fact("cf-a", 3, since="2026-09-25T12:00:00.5Z"))
        with self.assertRaises(sqlite3.IntegrityError) as refused:
            self.supersede("cf-a", self.fact("cf-b", 1, since="2026-09-25T12:00:00Z"))
        self.assertIn("gateway_supersession_edge", str(refused.exception))
        self.supersede("cf-a", self.fact("cf-c", 1, since="2026-09-25T12:00:00.500000001Z"))   # a nanosecond later
        self.supersede("cf-c", self.fact("cf-d", 1, since="2026-09-25T12:00:01Z"))
        self.assertEqual(self.rows("SELECT fact_id FROM capability_facts WHERE superseded_by_fact_id IS NULL"), [("cf-d",)])

    def test_a_gateway_fact_is_a_snapshot_in_an_orderable_form(self) -> None:
        """2b-repair-5 F1: a gateway fact carries its revision, and its `since` in the one form whose instants
        the store orders (common.schema.json's timestamp: seconds, an optional 1-9 digit fraction, Z);
        whether it names a real calendar instant stays the router's (A11). Other facts are not held to it."""
        for label, since in (("an offset", "2026-09-25T12:00:00+00:00"), ("no zone", "2026-09-25T12:00:00"),
                             ("a space", "2026-09-25 12:00:00Z"), ("an empty fraction", "2026-09-25T12:00:00.Z"),
                             ("a ten-digit fraction", "2026-09-25T12:00:00.0123456789Z"),
                             ("a fraction that is not digits", "2026-09-25T12:00:00.5x5Z")):
            with self.subTest(label):
                self.rejects("gateway_fact_snapshot", *self.fact("cf-x", 1, since=since))
        self.rejects("gateway_fact_snapshot", *self.fact("cf-x", None))
        for i, since in enumerate(("2026-09-25T12:00:00Z", "2026-09-25T12:00:00.5Z", "2026-09-25T12:00:00.123456789Z")):
            self.x(*self.fact(f"cf-{i}", 1, capability=f"gateway.form{i}", since=since))
        self.x(*self.fact("cf-o", None, capability="provider-auth:x", since="2026-09-25 12:00"))
        self.assertEqual(self.rows("SELECT count(*) FROM capability_facts"), [(4,)])

    def test_only_a_superseded_gateway_fact_states_its_successor(self) -> None:
        """2b-repair-5 F1: a successor's episode and revision are stated by the gateway fact it supersedes,
        and by nothing else: not by a current fact, nor by another capability's fact."""
        self.rejects("gateway_supersession_edge", *self.fact("cf-1", 1, declared=(T, "failing", 2)))
        self.rejects("gateway_supersession_edge", *self.fact("cf-o", None, capability="provider-auth:x", declared=(T, "failing", 2)))
        self.x(*self.fact("cf-1", 1))
        self.x(*self.fact("cf-o", None, capability="provider-auth:x"))
        self.rejects("gateway_supersession_edge", "UPDATE capability_facts SET successor_revision = 2 WHERE fact_id = 'cf-1'")
        self.x("BEGIN")
        self.rejects("gateway_supersession_edge", self.LINK, "cf-o2", T, "failing", 2, "cf-o")
        self.x("UPDATE capability_facts SET superseded_by_fact_id = 'cf-o2' WHERE fact_id = 'cf-o'")
        self.x(*self.fact("cf-o2", None, capability="provider-auth:x", state="healthy"))
        self.x("COMMIT")
        self.assertEqual(self.rows("SELECT fact_id, successor_since, successor_state, successor_revision FROM capability_facts ORDER BY fact_id"),
                         [("cf-1", None, None, None), ("cf-o", None, None, None), ("cf-o2", None, None, None)])

    def test_observation_invocation_is_of_its_topic(self) -> None:
        """A10: search_observations binds its invocation's topic."""
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.rejects("invocation of its own topic", self.INSERT.replace("'inv_pppppppp'", "'inv_oooooooo'"), "o1", TOPIC, h("1"), T, "searched_ok", 3, None, None, "complete")
        self.x(self.INSERT.replace("'inv_pppppppp'", "'inv_oooooooo'"), "o1", OTHER, h("1"), T, "searched_ok", 3, None, None, "complete")

    def test_partial_results_are_kept_and_marked_incomplete(self) -> None:
        """A11 / RG-4: a partial result set keeps its observed records (count as a
        lower bound, retrieval events captured) and says why it is partial; it is
        never searched_empty, a degraded search never claims an observed result
        set, and a complete successful search carries no error."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_ok", 5, completeness="partial")  # partial must say why
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_empty", 0, "partial_pagination", completeness="partial")  # an empty page is not an empty search
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "provider_unavailable", None, "provider_outage", completeness="complete")
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_ok", 5, completeness="unobserved")
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_ok", 5, "timeout", completeness="complete")  # a complete result set has no error
        self.obs("o1", "searched_ok", 5, "partial_pagination", completeness="partial")
        self.x("INSERT INTO retrieval_events (event_id, observation_id, topic_id, provider_record_id, captured_at) VALUES ('e1', 'o1', ?, 'rec-1', ?)", TOPIC, T)
        self.assertEqual(self.rows("SELECT completeness, result_count, error_class FROM search_observations"), [("partial", 5, "partial_pagination")])

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
        # The A10 binding (the receipt's committed action must be this assessment)
        # now refuses a shadow receipt first; the qualified-authority trigger is
        # its second layer (tools/gen2_mutations.py SECOND_LAYER).
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev)  # shadow
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", "dec_00000001", T)
        self.decision_receipt("dec_00000002", "inv_pppppppp", self.jev, authority="qualified", qualification="qual_screen01", action="commit_reversible_action", commit_op="op_00000001")
        self.x(self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", "dec_00000002", T)

    def test_provider_assessment_is_exactly_its_receipts_committed_action(self) -> None:
        """A10: class, topic, invocation, action, commit and subject of the
        qualified receipt all bind to the assessment; each probe is a qualified
        receipt differing in one of them."""
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000002', 'doi', '10.1/y', ?)", T)
        self.receipt("op_00000002", "inv_pppppppp", kind="interim_transition", before=1)
        pre = self.spec("dspec_prefil01", cls="relevance_prefilter")
        q = dict(authority="qualified", qualification="qual_screen01")
        self.decision_receipt("dec_otherwrk", "inv_pppppppp", self.jev, action="commit_reversible_action", commit_op="op_00000001", subject=("work", "wrk_00000002"), **q)
        self.decision_receipt("dec_othercls", "inv_pppppppp", pre, action="commit_reversible_action", commit_op="op_00000001", cls="relevance_prefilter",
                              **{**q, "qualification": "qual_prefil01"})
        self.decision_receipt("dec_othercom", "inv_pppppppp", self.jev, action="commit_reversible_action", commit_op="op_00000002", **q)
        self.decision_receipt("dec_proposal", "inv_pppppppp", self.jev, action="attach_proposal", proposal="prop-1", **q)
        self.decision_receipt("dec_othersub", "inv_pppppppp", self.jev, action="commit_reversible_action", commit_op="op_00000001", subject=("claim", "wrk_00000001"), **q)
        for did in ("dec_otherwrk", "dec_othercls", "dec_othercom", "dec_proposal", "dec_othersub"):
            with self.subTest(receipt=did):
                self.rejects("screening assessment bindings", self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", did, T)
        # another invocation's receipt (a discovery pass of the same topic)
        self.lease("lease_dddddddd", 2, scope="discovery")
        self.invocation("inv_disc0001", kind="discovery", lease="lease_dddddddd")
        self.decision_receipt("dec_otherinv", "inv_disc0001", self.jev, action="commit_reversible_action", commit_op="op_00000001", **q)
        self.rejects("screening assessment bindings", self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", "dec_otherinv", T)
        self.decision_receipt("dec_00000002", "inv_pppppppp", self.jev, action="commit_reversible_action", commit_op="op_00000001", **q)
        self.x(self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", "dec_00000002", T)

    def test_assessment_operation_invocation_and_reversal_are_of_its_topic(self) -> None:
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.receipt("op_other001", "inv_oooooooo", lease="lease_zzzzzzzz", tid=OTHER, kind="interim_transition")
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000002', 'doi', '10.1/y', ?)", T)
        refused = "screening assessment bindings"
        self.rejects(refused, self.SCREEN.replace("'op_00000001'", "'op_other001'"), "sa1", TOPIC, "include", None, "primary", None, T)
        self.rejects(refused, self.SCREEN.replace("'inv_pppppppp'", "'inv_oooooooo'"), "sa1", TOPIC, "include", None, "primary", None, T)
        self.x(self.SCREEN, "sa1", TOPIC, "exclude", "EC-1", "primary", None, T)
        reverse = ("INSERT INTO screening_assessments (assessment_id, topic_id, work_id, contract_revision, eligibility_protocol_version, framing_version, stage, decision, reason_code, criterion_results, actor_kind, invocation_id, supersedes_assessment_id, recorded_by_operation_id, created_at) "
                   "VALUES (?, ?, ?, 1, 1, 1, 'abstract', 'include', NULL, '{}', 'primary', 'inv_pppppppp', 'sa1', 'op_00000001', ?)")
        self.rejects(refused, reverse, "sa2", TOPIC, "wrk_00000002", T)  # a reversal of another work's exclusion
        # a reversal of another topic's exclusion of the same work
        self.x("INSERT INTO screening_assessments (assessment_id, topic_id, work_id, contract_revision, eligibility_protocol_version, framing_version, stage, decision, reason_code, criterion_results, actor_kind, invocation_id, recorded_by_operation_id, created_at) "
               "VALUES ('sa-other', ?, 'wrk_00000001', 1, 1, 1, 'abstract', 'exclude', 'EC-1', '{}', 'primary', 'inv_oooooooo', 'op_other001', ?)", OTHER, T)
        self.rejects(refused, reverse.replace("'sa1'", "'sa-other'"), "sa2", TOPIC, "wrk_00000001", T)
        self.x(reverse, "sa2", TOPIC, "wrk_00000001", T)

    def test_fallback_label_cannot_carry_probability(self) -> None:
        fb = self.spec("dspec_screen02", provider="llm_fallback")
        label = {"primitive": "label", "selected_option_id": "include", "evidence_refs": ["r1"]}
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", fb, provider="llm_fallback", answer=dict(label, probability=0.9))
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", fb, provider="llm_fallback", answer=dict(label, primitive="choice", confidence=0.9))
        self.decision_receipt("dec_00000001", "inv_pppppppp", fb, provider="llm_fallback", answer=label)

    def test_missing_confidence_or_primitive_is_rejected_not_defaulted(self) -> None:
        """D41 (MODIFY per review): the Noul positive now runs under a Noul spec."""
        noul = self.spec("dspec_noul0001", primitive="noul", options=("yes", "no"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, answer={"primitive": "choice", "selected_option_id": "include", "distribution": {"include": 0.8, "exclude": 0.2}})
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, answer={"selected_option_id": "include", "confidence": 0.7})
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", noul, answer={"primitive": "noul", "probability": 0.8, "confidence": 0.9})
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", noul, answer={"primitive": "noul"})
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev)
        self.decision_receipt("dec_00000002", "inv_pppppppp", noul, answer={"primitive": "noul", "probability": 0.8})

    def test_unqualified_authority_is_capped(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="qualified", action="attach_proposal", proposal="prop-1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="advisory", action="commit_reversible_action", commit_op="op_00000001")
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="shadow", action="attach_proposal", proposal="prop-1")
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="advisory", action="attach_proposal", proposal="prop-1")

    def test_receipt_provider_must_match_spec(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, provider="llm_fallback", answer={"primitive": "label", "selected_option_id": "x", "evidence_refs": ["r"]})
        self.assertIn("must match its spec", str(ctx.exception))


class DecisionReceiptConsistencyTest(StoreTestCase):
    """A7 (and A10 for the receipt JSON): action/outcome shapes, raw response
    retention, spec binding by primitive/policy/options/protocol, spec shape."""

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")
        self.x("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, created_at) "
               "VALUES ('hold_00000001', ?, 'wrk_00000001', 'judgment', 'low confidence', 'needs_decision', 'primary', 'primary', ?, 'primary decides', ?)", TOPIC, T, T)
        self.jev = self.spec()

    def test_action_fixes_the_outcome_shape(self) -> None:
        q = dict(authority="qualified", qualification="qual_00000001")
        bad = {
            "shadow with a committed operation (the review's probe)": dict(commit_op="op_00000001"),
            "shadow with a hold": dict(hold="hold_00000001"),
            "shadow with a proposal": dict(proposal="prop-1"),
            "proposal without its ref": dict(action="attach_proposal", authority="advisory"),
            "proposal that also commits": dict(action="attach_proposal", proposal="prop-1", commit_op="op_00000001", **q),
            "commit that also proposes": dict(action="commit_reversible_action", commit_op="op_00000001", proposal="prop-1", **q),
            "commit that also holds": dict(action="commit_reversible_action", commit_op="op_00000001", hold="hold_00000001", **q),
            "escalation that commits": dict(action="escalate", commit_op="op_00000001", authority="advisory"),
            "escalation that proposes": dict(action="escalate", proposal="prop-1", authority="advisory"),
            "abstain-hold without its hold": dict(action="abstain_hold", authority="advisory"),
        }
        for label, kw in bad.items():
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, **kw)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.decision_receipt("dec_shadow01", "inv_pppppppp", self.jev)
        self.decision_receipt("dec_propos01", "inv_pppppppp", self.jev, action="attach_proposal", proposal="prop-1", authority="advisory")
        self.decision_receipt("dec_commit01", "inv_pppppppp", self.jev, action="commit_reversible_action", commit_op="op_00000001", **q)
        self.decision_receipt("dec_escal001", "inv_pppppppp", self.jev, action="escalate", hold="hold_00000001", authority="advisory")
        self.decision_receipt("dec_abstn001", "inv_pppppppp", self.jev, action="abstain_hold", hold="hold_00000001", authority="advisory", status="abstained", answer=None)

    def test_abstention_retains_the_raw_response(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, status="abstained", answer=None, raw=None, action="escalate", authority="advisory")
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, raw=None)  # an answer without its raw bytes
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, status="abstained", answer=None, action="escalate", authority="advisory", raw="0", stage_raw=False)
        self.assertIn("FOREIGN KEY constraint failed", str(ctx.exception))  # the digest must be a retained artifact
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, status="abstained", answer=None, action="escalate", authority="advisory")
        self.decision_receipt("dec_00000002", "inv_pppppppp", self.jev, status="timeout", answer=None, raw=None, action="escalate", authority="advisory")

    def test_receipt_matches_its_spec(self) -> None:
        refused = "must match its spec"
        noul = {"primitive": "noul", "probability": 0.6}
        cases = {
            "a Noul answer under a Choice spec (the review's D41 probe)": dict(answer=noul),
            "another action-policy id": dict(policy=("P2", 1)),
            "another action-policy version": dict(policy=("P1", 2)),
            "a selected option the spec does not offer": dict(answer={"primitive": "choice", "selected_option_id": "maybe", "distribution": {"include": 0.5, "exclude": 0.5}, "confidence": 0.5}),
            "a distribution over an option the spec does not offer": dict(answer={"primitive": "choice", "selected_option_id": "include", "distribution": {"include": 0.5, "maybe": 0.5}, "confidence": 0.5}),
        }
        for label, kw in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, **kw)
                self.assertIn(refused, str(ctx.exception))
        other = self.spec("dspec_otherpr1", protocol_topic=OTHER)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.decision_receipt("dec_00000001", "inv_pppppppp", other)  # a spec bound to another topic's protocol
        self.assertIn(refused, str(ctx.exception))
        # RA6: the spec id the receipt names must be the id of the spec its hash
        # selects — an unknown id, and the id of another stored spec, each with
        # the correct hash
        self.spec("dspec_screen02")
        for spec_id in ("dspec_wrong001", "dspec_screen02"):
            with self.subTest(spec_id=spec_id):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, receipt_overrides={"spec": {"spec_id": spec_id, "spec_hash": self.jev}})
                self.assertIn(refused, str(ctx.exception))
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev)

    def test_spec_shape_by_class_and_provider(self) -> None:
        cases = {
            "screening without an eligibility protocol (the review's probe)": dict(spec_id="dspec_bad00001", no_protocol=True),
            "method_selection without its contract protocol": dict(spec_id="dspec_bad00002", cls="method_selection", no_protocol=True),
            "a fallback that answers Choice": dict(spec_id="dspec_bad00003", provider="llm_fallback", primitive="choice"),
            "a Noul with three options": dict(spec_id="dspec_bad00004", primitive="noul", options=("yes", "no", "maybe")),
            "a single option": dict(spec_id="dspec_bad00005", options=("include",)),
            "options as a list (ids not unique by construction)": dict(spec_id="dspec_bad00006", document_overrides={"options": [{"option_id": "a"}, {"option_id": "a"}]}),
            "no options key at all (absent, not null)": dict(spec_id="dspec_bad00007", drop=("options",)),
            "screening whose protocol key is absent": dict(spec_id="dspec_bad00008", no_protocol=True, drop=("protocol",)),
        }
        for label, kw in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.spec(**kw)
                self.assertTrue("CHECK constraint failed" in str(ctx.exception) or "at least two options" in str(ctx.exception), str(ctx.exception))
        other_protocol = {"topic_id": OTHER, "contract": {"revision": 1, "content_hash": h("a")}, "eligibility_protocol_version": 1}
        for label, overrides in (("primitive", {"primitive": "score"}), ("policy id", {"action_policy": {"policy_id": "P2", "version": 1}}),
                                 ("policy version", {"action_policy": {"policy_id": "P1", "version": 2}}), ("protocol topic", {"protocol": other_protocol})):
            with self.subTest(json_field=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.spec("dspec_bad00009", document_overrides=overrides)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.spec("dspec_noul0001", primitive="noul", options=("yes", "no"))
        self.spec("dspec_meth0001", cls="method_selection", options=("design-a", "design-b", "design-c"))
        self.spec("dspec_fall0001", provider="llm_fallback", cls="intake_triage")

    def test_receipt_row_matches_its_json(self) -> None:
        """A10: each probe keeps the columns valid and changes only the JSON field."""
        doc_probes = {
            "decision_receipt_id": "dec_other000", "invocation_id": "inv_other000", "topic_id": OTHER, "spec": {"spec_id": "dspec_screen01", "spec_hash": h("0")},
            "decided_at": "2026-09-26T00:00:00Z",
            "decision_class": "method_selection", "provider": "llm_fallback", "subject": {"kind": "work", "ref": "wrk_other000"},
            "subject.kind": {"kind": "claim", "ref": "wrk_00000001"},
            "input_manifest": {"snapshot_digest": h("6"), "input_record_ids": [], "input_status": "stale"},
            "policy": {"policy_id": "P9", "version": 1}, "policy.version": {"policy_id": "P1", "version": 9},
            "authorization": {"authority_level": "advisory", "qualification_ref": None}, "authorization.qualification_ref": {"authority_level": "shadow", "qualification_ref": "q-x"},
            "action": "escalate", "outcome": {"commit_operation_id": "op_00000001", "proposal_ref": None, "hold_id": None},
            "outcome.proposal_ref": {"commit_operation_id": None, "proposal_ref": "p-x", "hold_id": None}, "outcome.hold_id": {"commit_operation_id": None, "proposal_ref": None, "hold_id": "hold_00000001"},
            "blind_sample": {"selected": True, "initial_disposition_ref": None},
        }
        base_response = {"status": "answered", "raw_response_digest": h("5"), "raw_response_artifact": {"content_hash": h("5"), "size_bytes": 10, "media_type": "application/json"},
                         "answer": {"primitive": "choice", "selected_option_id": "include", "distribution": {"include": 0.8, "exclude": 0.2}, "confidence": 0.7}}
        for key, value in (("status", "abstained"), ("raw_response_digest", h("4")), ("raw_response_artifact", {"content_hash": h("4"), "size_bytes": 10, "media_type": "application/json"}),
                           ("answer", {"primitive": "choice", "selected_option_id": "exclude", "distribution": {"include": 0.2, "exclude": 0.8}, "confidence": 0.7})):
            doc_probes[f"provider_response.{key}"] = dict(base_response, **{key: value})
        for label, value in doc_probes.items():
            with self.subTest(field=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, receipt_overrides={label.split(".")[0]: value})
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev)


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
        ins = "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'user', ?)"
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
        ins = "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES ('opd_x', ?, ?, ?, ?, ?, ?, ?, 'user', ?)"
        ch = self.content_hash_of(TOPIC, 1)
        self.x(self.INSERT, "hold_00000001", TOPIC, "scope", "operator", "operator", T, "c", None, T)
        # (rows chosen so the subject-existence trigger, which fires first, passes)
        bad = (
            (TOPIC, "hold_clearance", "approved", "topic", TOPIC, 0, None),                 # kind admits only a hold subject
            (TOPIC, "retirement", "approved", "hold", "hold_00000001", None, None),         # and the reverse
            (TOPIC, "publication_approval", "approved", "publication_source", "src-1", None, ch),  # a versioned subject needs its revision (task 2a: a kind with no stored subject)
            (TOPIC, "contract_approval", "approved", "contract_revision", OTHER, 1, ch),     # contract subject is referenced by its own topic
            (TOPIC, "retirement", "approved", "topic", TOPIC, None, None),                  # topic subject needs the state revision decided against
            (None, "publication_approval", "approved", "publication_source", "src-1", 1, ch),  # only hold decisions may be topic-less
            (TOPIC, "retirement", "recorded", "topic", TOPIC, 0, None),                     # 'recorded' is only for blind/advised records
            (TOPIC, "publication_approval", "approved", "publication_source", "src-1", 1, None),  # a publication source needs its hash
        )
        for row in bad:
            with self.subTest(row=row):
                self.rejects("CHECK constraint failed", ins, *row, T)
        self.x(ins, TOPIC, "contract_approval", "approved", "contract_revision", TOPIC, 1, ch, T)


if __name__ == "__main__":
    unittest.main()
