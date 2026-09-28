"""Brief and contract versions, and G-1 amendment impact (task 1d).

Trace: INVARIANTS G-1, G-4, G-6, G-7, C-10, C-12, V-10, §13 (Phase 1: the
fake-executor lifecycle of briefs, confirmation/amendment fencing, owner
reassignment and deadline extension); the 1b review's bootstrap ruling
(minimal router-owned brief and amendment version commands) and its ruling
on proposal 3 (amendment_pending was interim fail-closed); the 1a review
(G-1 impact before Phase 1 acceptance); gen2/router/amendments.py.

The contract world: revision 1 is the draft the operator rated (a fixture,
contract construction being Phase 2), revision 2 carries those ratings and
is approved through the router; amendments are proposed and approved
through the router. Documents follow the schema-valid example contract.

Oracles: hand-written expectations and dispositions; raw SQL read-back of
the whole store (every table but the audit log) around each refusal; the
compatibility of each edit is stated by the test that makes it.

Structural limits: work is exercised at the router, with fixture
invocations standing in for executors (the supervisor's side of a
cancellation is test_supervisor_*'s); the compatibility rule is structural,
so these tests show which edits it classes as which, not that the classes
are semantically right (a harmless edit to protocol text is still
incompatible, by design).
"""
from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
from pathlib import Path

from gen2.core import canonical
from gen2.store import api
from gen2.tests import router_fixtures as rf, store_fixtures
from gen2.tests.router_fixtures import OTHER, TOPIC, RouterTestCase, empty_outcome, h, jcs
from gen2.tests import test_router_commit  # its verification-receipt builder (the module, so its tests are not collected twice)

EXAMPLE = json.loads((rf.EXAMPLES / "contract-v2" / "valid-two-obligations.json").read_text())["instance"]
KINDS = ("research_pass", "discovery", "verification", "checkpoint")


def contract_doc(revision: int, parent: int | None, *, rated: bool = True, edit=None) -> dict:
    """The example contract as TOPIC's revision `revision`; `edit` changes it."""
    doc = copy.deepcopy(EXAMPLE)
    doc.update(topic_id=TOPIC, revision=revision, parent_revision=parent, created_at="2026-09-27T09:30:00Z")
    for entry in doc["facet_map"]["facets"] + doc["obligations"]:
        entry["importance"]["proposed"] = None
        if not rated:
            entry["importance"]["operator_rating"] = None
    if edit is not None:
        edit(doc)
    doc["content_hash"] = canonical.content_hash(doc)
    return doc


def compatible(doc: dict) -> None:
    """A decision-record edit: no framing, protocol or obligation changes."""
    doc["decision_record"]["feeds"]["description"] = "Intake station design for the six-station fleet."


def protocol_changed(doc: dict) -> None:
    doc["protocol_revision"] = 2
    doc["eligibility_protocol"]["protocol_version"] = 2
    doc["eligibility_protocol"]["criteria"][1]["description"] = "Reports an omission, coverage or cost outcome for elicited requirements."


def reframed(doc: dict) -> None:
    doc["facet_map"]["framing_version"] = 2


def columns(entry: dict) -> tuple:
    """A facet's or obligation's importance columns, from its entry (written out here, not the router's projection)."""
    proposed, rating = entry["importance"]["proposed"] or {}, entry["importance"]["operator_rating"] or {}
    return (proposed.get("source"), proposed.get("score"), proposed.get("decision_receipt_id"), rating.get("band"), rating.get("score"), rating.get("operator_decision_id"))


class ContractWorld(RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.build_world()

    def build_world(self) -> None:
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', '2026-09-27T09:00:00Z')")
        self.to_scoping()
        self.x("UPDATE queue_entries SET status = 'awaiting_scope_approval', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        assert self.decide("opd_scope0001", "scope_approval", {"kind": "scoping_report", "ref": "scope-1", "revision": 1, "hash": h("5")})["status"] == "applied"
        r1, rated = contract_doc(1, None, rated=False), contract_doc(2, 1)
        self.store_draft(r1)
        payload = {"facets": {f["facet_id"]: {"band": f["importance"]["operator_rating"]["band"], "score": f["importance"]["operator_rating"].get("score")}
                              for f in rated["facet_map"]["facets"]},
                   "obligations": {o["obligation_id"]: {"band": o["importance"]["operator_rating"]["band"], "score": o["importance"]["operator_rating"].get("score")}
                                   for o in rated["obligations"]}}
        assert self.decide("opd_rate0001", "rating_approval", {"kind": "contract_revision", "revision": 1, "hash": r1["content_hash"]}, payload=payload)["status"] == "applied"
        self.store_draft(rated)
        assert self.decide("opd_cntr0002", "contract_approval", {"kind": "contract_revision", "revision": 2, "hash": rated["content_hash"]})["status"] == "applied"

    def store_draft(self, doc: dict) -> None:
        """A first draft and its rows (raw SQL: contract construction is Phase 2)."""
        self.x("INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?)", doc["topic_id"], doc["revision"], doc["parent_revision"], doc["protocol_revision"],
               doc["facet_map"]["framing_version"], doc["content_hash"], jcs(doc).decode(), doc["created_at"])
        for f in doc["facet_map"]["facets"]:
            self.x("INSERT INTO facets (topic_id, contract_revision, facet_id, proposed_importance_source, proposed_importance_score, proposed_decision_receipt_id, "
                   "operator_importance_band, operator_importance_score, operator_rating_decision_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   doc["topic_id"], doc["revision"], f["facet_id"], *columns(f))
        for o in doc["obligations"]:
            self.x("INSERT INTO obligations (topic_id, contract_revision, obligation_id, template_id, template_version, claim_type, facet_ids, stopping_profile_id, exploratory, "
                   "proposed_importance_source, proposed_importance_score, proposed_decision_receipt_id, operator_importance_band, operator_importance_score, operator_rating_decision_id) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", doc["topic_id"], doc["revision"], o["obligation_id"], o["template"]["template_id"],
                   o["template"]["template_version"], o["template"]["claim_type"], json.dumps(o["facet_ids"]), o["stopping_profile_id"], int(o["exploratory"]), *columns(o))

    def propose(self, revision: int, edit=None, parent: int | None = None) -> dict:
        doc = contract_doc(revision, revision - 1 if parent is None else parent, edit=edit)
        out = self.router.propose_amendment({"document": doc})
        assert out["status"] == "recorded", out
        return doc

    def approve(self, doc: dict, kind: str = "amendment_approval", did: str | None = None) -> dict:
        return self.decide(did or f"opd_amend{doc['revision']:04d}", kind, {"kind": "contract_revision", "revision": doc["revision"], "hash": doc["content_hash"]})

    def impact(self, did: str) -> dict:
        return json.loads(self.value("SELECT document FROM amendment_impacts WHERE decision_id = ?", did))

    def research(self, inv: str = "inv_research01", *, load_bearing: bool = True) -> dict:
        """A research pass under revision 2 that screens (an inclusion and an
        exclusion), captures a claim (load-bearing, at full text, unless
        `load_bearing` is False) and observes a search."""
        grant = self.started(inv)
        text = self.artifact(b"a load-bearing claim")
        outcome = empty_outcome(inv, "interim_transition")
        outcome["claims"] = [{"claim_id": "clm_00000001", "revision": 1, "text_ref": text, "load_bearing": load_bearing,
                               "required_access_tier": "full_text" if load_bearing else None}]
        outcome["screening_assessments"] = [
            {"assessment_id": "asm_000000000001", "work_id": "wrk_00000001", "stage": "abstract", "decision": "include", "reason_code": None,
             "criterion_results": {"EC-outcome": "met"}, "actor_kind": "primary", "decision_receipt_id": None, "supersedes_assessment_id": None},
            {"assessment_id": "asm_000000000002", "work_id": "wrk_00000001", "stage": "abstract", "decision": "exclude", "reason_code": "EC-outcome",
             "criterion_results": {"EC-outcome": "not_met"}, "actor_kind": "primary", "decision_receipt_id": None, "supersedes_assessment_id": None}]
        assert self.router.commit_outcome(self.envelope(grant, "op_capture0001", outcome, refs=[text]))["status"] == "committed"
        request = {"q": "intake omissions"}
        observation = {"observation_id": "obs_000000000001", "request": request, "request_identity": canonical.logical_hash(request), "attempt": 1, "lane": "crossref",
                       "obligation_ids": ["O-1"], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:01Z", "coverage_state": "searched_empty",
                       "result_count": 0, "completeness": "complete", "error_class": None, "capability_fact_id": None, "policy_version": "pol-1", "cost_units": None,
                       "gateway_call_ref": None}
        assert self.router.record_observation({"capability_id": grant["capability_id"], "invocation_id": inv, "observation": observation, "retrieval_events": []})["status"] == "recorded"
        return grant

    def verify(self) -> dict:
        verifier = self.started("inv_verify01", "verification")
        own = {**empty_outcome("inv_verify01", "interim_transition"), "verification_receipts": [test_router_commit.AuthorityTest.verification_receipt(self, verifier)]}
        assert self.router.commit_outcome(self.envelope(verifier, "op_verify0001", own))["status"] == "committed"
        return verifier

    def refused_command(self, method, request: dict, reason: str, detail: str | None = None) -> None:
        before = self.state()
        out = getattr(self.router, method)(request)
        self.assertEqual((out["status"], out["reason"]), ("refused", reason), out)
        if detail is not None:
            self.assertIn(detail, out["detail"])
        self.assertEqual(self.state(), before)


class AmendmentProposalTest(ContractWorld):
    """The 1b bootstrap ruling: an amendment is proposed through the router as
    the next revision, a draft whose parent is the approved revision, with
    its facet and obligation rows."""

    def test_an_amendment_is_recorded_as_a_draft_with_its_rows(self) -> None:
        doc = contract_doc(3, 2, edit=compatible)
        self.assertEqual(self.router.propose_amendment({"document": doc}), {"status": "recorded", "topic_id": TOPIC, "revision": 3, "against_approved": "compatible"})
        self.assertEqual(self.rows("SELECT revision, parent_revision, status, content_hash FROM contract_revisions WHERE revision = 3"), [(3, 2, "draft", doc["content_hash"])])
        self.assertEqual(json.loads(self.value("SELECT document FROM contract_revisions WHERE revision = 3")), doc)
        self.assertEqual(self.rows("SELECT facet_id, proposed_importance_source, proposed_importance_score, proposed_decision_receipt_id, operator_importance_band, "
                                   "operator_importance_score, operator_rating_decision_id FROM facets WHERE contract_revision = 3 ORDER BY rowid"),
                         [(f["facet_id"], *columns(f)) for f in doc["facet_map"]["facets"]])
        self.assertEqual(self.rows("SELECT obligation_id, template_id, stopping_profile_id, facet_ids FROM obligations WHERE contract_revision = 3 ORDER BY rowid"),
                         [(o["obligation_id"], o["template"]["template_id"], o["stopping_profile_id"], json.dumps(o["facet_ids"], separators=(",", ":")))
                          for o in doc["obligations"]])

    def test_the_proposal_is_classed_against_the_approved_revision(self) -> None:
        for revision, (edit, expected) in enumerate(((compatible, "compatible"), (protocol_changed, "protocol_changed"), (reframed, "reframed")), start=3):
            with self.subTest(expected):  # sibling drafts of revision 2, each proposed as the next revision
                out = self.router.propose_amendment({"document": contract_doc(revision, 2, edit=edit)})
                self.assertEqual((out["status"], out["against_approved"]), ("recorded", expected), out)

    def test_each_defect_is_refused_alone(self) -> None:
        good = contract_doc(3, 2, edit=compatible)
        untrue = copy.deepcopy(good)
        untrue["decision_record"]["feeds"]["description"] = "edited after hashing"
        cases = (("another revision number", contract_doc(4, 2, edit=compatible), "request_invalid", "is revision 3"),
                 ("a parent that is not the approved revision", contract_doc(3, 1, edit=compatible), "request_invalid", "the approved revision 2"),
                 ("a hash that is not its content's", untrue, "request_invalid", "does not hash to its content hash"),
                 ("a document the schema refuses", {k: v for k, v in good.items() if k != "method_design"}, "request_invalid", "contract-v2.schema.json"))
        for name, doc, reason, detail in cases:
            with self.subTest(name):
                self.refused_command("propose_amendment", {"document": doc}, reason, detail)
        self.assertEqual(self.router.propose_amendment({"document": good})["status"], "recorded")
        self.refused_command("propose_amendment", {"document": {**contract_doc(3, 2, edit=reframed)}}, "amendment_conflict")  # the key is the revision
        before = self.state()
        self.assertEqual(self.router.propose_amendment({"document": good})["status"], "replayed")
        self.assertEqual(self.state(), before)

    def test_no_approved_contract_takes_no_amendment(self) -> None:
        self.to_scoping(OTHER)
        doc = {**contract_doc(1, None, edit=compatible), "topic_id": OTHER}
        doc["content_hash"] = canonical.content_hash({k: v for k, v in doc.items() if k != "content_hash"})
        self.refused_command("propose_amendment", {"document": doc}, "no_approved_contract")


class AmendmentApprovalTest(ContractWorld):
    """G-1, G-6, G-7: an approval supersedes exactly the approved revision it
    revises; a framing change is approved as a reframe and only as one."""

    def test_an_amendment_revises_the_approved_revision(self) -> None:
        r3 = self.propose(3, compatible)
        self.assertEqual(self.approve(r3)["status"], "applied")
        self.assertEqual(self.rows("SELECT revision, status FROM contract_revisions ORDER BY revision"), [(1, "draft"), (2, "superseded"), (3, "approved")])
        stale = contract_doc(4, 2, edit=protocol_changed)  # a sibling of revision 3, written around the router
        self.store_draft(stale)
        before = self.state()
        out = self.approve(stale)
        self.assertEqual((out["status"], out["reason"]), ("rejected", "decision_refused"), out)
        self.assertIn("does not revise the approved revision 3", out["detail"])
        self.assertEqual(self.state(), before)

    def test_a_framing_change_is_approved_as_a_reframe_and_only_as_one(self) -> None:
        r3 = self.propose(3, reframed)
        compat = self.propose(4, compatible, parent=2)
        before = self.state()
        for doc, kind in ((r3, "amendment_approval"), (compat, "reframe_approval")):
            with self.subTest(kind):
                out = self.approve(doc, kind, did=f"opd_wrong{doc['revision']:04d}")
                self.assertEqual((out["status"], out["reason"]), ("rejected", "decision_refused"), out)
                self.assertEqual(self.state(), before)
        self.assertEqual(self.approve(r3, "reframe_approval")["status"], "applied")

    def test_an_approved_amendment_requeues_a_completed_topic(self) -> None:
        self.x("UPDATE queue_entries SET status = 'active', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), "2026-09-27T09:00:00Z")
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) "
               "VALUES (?, 1, 2, 1, 'eval-1', ?, ?, ?)", TOPIC, h("3"), h("7"), "2026-09-27T09:00:00Z")
        self.assertEqual(self.decide("opd_complete01", "completion_approval", {"kind": "dossier", "revision": 1, "hash": h("3")})["status"], "applied")
        self.assertEqual(self.status(), "completed_with_qualified_conclusions")
        out = self.approve(self.propose(3, compatible))
        self.assertEqual(out["effects"]["queue_transition"], {"from": "completed_with_qualified_conclusions", "to": "queued"})
        self.assertEqual(self.rows("SELECT status, status_decision_id, active_contract_revision FROM queue_entries WHERE topic_id = ?", TOPIC), [("queued", None, 3)])
        self.assertEqual(self.impact("opd_amend0003")["dossiers"], [{"dossier_revision": 1, "contract_revision": 2, "disposition": "not_current"}])


class ImpactTest(ContractWorld):
    """G-1: an approval that supersedes a revision identifies what was pinned
    to it and disposes of each, in its own transaction; nothing is silently
    reused and nothing silently discarded."""

    def test_a_compatible_amendment_lets_admitted_work_complete_under_its_pins(self) -> None:
        grant = self.research()
        verifier = self.verify()
        out = self.approve(self.propose(3, compatible))
        self.assertEqual(out["effects"]["impact"]["classification"], "compatible")
        record = self.impact("opd_amend0003")
        self.assertEqual({w["invocation_id"]: (w["disposition"], w["cancel_requested"]) for w in record["work"]},
                         {"inv_research01": ("completes_under_pins", False), "inv_verify01": ("completes_under_pins", False)})
        self.assertEqual([(a["assessment_id"], a["disposition"]) for a in record["screening_labels"]], [("asm_000000000001", "valid"), ("asm_000000000002", "valid")])
        self.assertEqual((record["reopened_exclusions"], [c["disposition"] for c in record["claims"]], [v["disposition"] for v in record["verifications"]]),
                         ([], ["valid"], ["valid"]))
        self.assertEqual(self.rows("SELECT cancel_requested_at FROM invocations WHERE invocation_id IN ('inv_research01', 'inv_verify01')"), [(None,), (None,)])
        # the admitted pass completes under revision 2 within its deadline, and its claim is promoted
        outcome = {**empty_outcome("inv_research01"), "claim_promotions": [{"claim_id": "clm_00000001", "revision": 1}]}
        response = self.finish(grant, "op_final000001", outcome)
        self.assertEqual(response["status"], "committed", response)
        self.assertEqual(response["receipt"]["admission"]["contract"]["revision"], 2)
        self.assertEqual(self.value("SELECT status FROM claims WHERE claim_id = 'clm_00000001'"), "accepted_support")
        self.assertIsNotNone(verifier)

    def test_a_protocol_change_fences_admitted_work_of_every_kind(self) -> None:
        """All kinds, a delegate among them: running work has its cancellation
        requested, admitted work is cancelled at once (nothing was spawned),
        and a staged result is refused at commit and stays retained."""
        grant = self.research()
        self.verify()
        ready = self.started("inv_disco001", "discovery")
        checkpoint = self.claim("inv_checkpt01", "checkpoint")  # admitted, never launched
        self.started("inv_deleg001", "delegate", parent=grant)
        staged, _ = self.stage(empty_outcome("inv_disco001"))
        self.ready(ready, staged)
        r3 = self.propose(3, protocol_changed)
        out = self.approve(r3)
        record = self.impact("opd_amend0003")
        self.assertEqual(record["classification"], "protocol_changed")
        self.assertEqual({w["invocation_id"]: (w["state"], w["disposition"], w["cancel_requested"]) for w in record["work"]},
                         {"inv_research01": ("running", "fenced", True), "inv_verify01": ("running", "fenced", True), "inv_disco001": ("result_ready", "fenced", False),
                          "inv_checkpt01": ("admitted", "fenced", True), "inv_deleg001": ("running", "fenced", True)})
        self.assertEqual(out["effects"]["impact"]["work"], record["work"])
        self.assertEqual(self.rows("SELECT invocation_id, state, cancel_requested_by FROM invocations ORDER BY invocation_id"),
                         [("inv_checkpt01", "cancelled", "router"), ("inv_deleg001", "running", "router"), ("inv_disco001", "result_ready", None),
                          ("inv_research01", "running", "router"), ("inv_verify01", "running", "router")])
        self.assertEqual(self.value("SELECT released_at IS NOT NULL FROM leases WHERE lease_id = ?", checkpoint["lease"]["lease_id"]), 1)
        self.assertEqual([(a["assessment_id"], a["disposition"]) for a in record["screening_labels"]],
                         [("asm_000000000001", "stale_under_new_protocol"), ("asm_000000000002", "stale_under_new_protocol")])
        self.assertEqual((record["reopened_exclusions"], [c["disposition"] for c in record["claims"]], [v["disposition"] for v in record["verifications"]]),
                         (["asm_000000000002"], ["stale_under_new_protocol"], ["stale_under_new_protocol"]))
        # the staged result is fenced at commit, and stays retained: nothing is written, the invocation keeps its result
        env = self.envelope(ready, "op_disco00001", empty_outcome("inv_disco001"))
        env["payload_digest"], env["payload_size_bytes"] = staged, len(jcs(empty_outcome("inv_disco001")))
        before = self.state()
        response = self.router.commit_outcome(env)
        self.assertEqual((response["status"], response["reason"]), ("rejected", "amendment_pending"), response)
        self.assertIn("contract revision 2 was superseded (protocol_changed)", response["detail"])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.rows("SELECT state, result_payload_digest FROM invocations WHERE invocation_id = 'inv_disco001'"), [("result_ready", staged)])

    def test_a_stale_claim_is_not_promoted_and_an_adopted_revision_is(self) -> None:
        """V-10 decided for amendments: a claim produced under a revision an
        amendment made incompatible is not promoted; work under the current
        revision adopts it as a new revision of its own production."""
        grant = self.research(load_bearing=False)  # promotable but for the amendment: no receipt rule reads it (V-4)
        self.approve(self.propose(3, protocol_changed))  # the pass's cancellation is requested (router)
        ended = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": "inv_research01", "to_state": "cancelled",
                                               "end_evidence_ref": self.evidence(grant, ())})
        self.assertEqual(ended["status"], "recorded", ended)
        self.assertEqual(self.router.requeue({"invocation_id": "inv_research01", "requested_by": "operator", "reason": "re-run under revision 3"})["status"], "requeued")
        adopter = self.started("inv_research02", retry_of="inv_research01")  # admitted under revision 3
        promote = {**empty_outcome("inv_research02", "interim_transition"), "claim_promotions": [{"claim_id": "clm_00000001", "revision": 1}]}
        env = self.envelope(adopter, "op_promote0001", promote)
        before = self.state()
        response = self.router.commit_outcome(env)
        self.assertEqual((response["status"], response["reason"]), ("rejected", "amendment_pending"), response)
        self.assertIn("contract-admitted work adopts it as a new revision", response["detail"])
        self.assertEqual(self.state(), before)
        text = self.artifact(b"a load-bearing claim")
        adopt = {**empty_outcome("inv_research02", "interim_transition"),
                 "claims": [{"claim_id": "clm_00000001", "revision": 2, "text_ref": text, "load_bearing": False, "required_access_tier": None}],
                 "claim_promotions": [{"claim_id": "clm_00000001", "revision": 2}]}
        self.assertEqual(self.router.commit_outcome(self.envelope(adopter, "op_adopt000001", adopt, refs=[text]))["status"], "committed")
        self.assertEqual(self.rows("SELECT revision, status FROM claims ORDER BY revision"), [(1, "provisional"), (2, "accepted_support")])

    def test_a_reframe_marks_coverage_and_labels_stale_and_reopens_exclusions(self) -> None:
        self.research()
        self.approve(self.propose(3, reframed), "reframe_approval")
        record = self.impact("opd_amend0003")
        self.assertEqual((record["classification"], [a["disposition"] for a in record["screening_labels"]], record["reopened_exclusions"]),
                         ("reframed", ["stale_under_new_framing"] * 2, ["asm_000000000002"]))
        self.assertEqual(record["coverage"], [{"observation_id": "obs_000000000001", "disposition": "stale_under_new_framing"}])

    def test_the_record_lists_what_stood_until_now(self) -> None:
        """Revision 2's labels are stale once 3 reframes; 4, compatible with 3,
        lists what stood under 3, and does not list 2's again."""
        self.research()
        self.approve(self.propose(3, reframed), "reframe_approval")
        self.approve(self.propose(4, lambda doc: (reframed(doc), compatible(doc))))  # revision 3's framing, and a decision-record edit
        record = self.impact("opd_amend0004")
        self.assertEqual((record["classification"], record["superseded"], record["current"]["revision"]),
                         ("compatible", {"revision": 3, "content_hash": self.value("SELECT content_hash FROM contract_revisions WHERE revision = 3")}, 4))
        self.assertEqual((record["screening_labels"], record["claims"], record["coverage"]), ([], [], []))
        self.assertEqual([w["disposition"] for w in record["work"]], ["fenced"])  # the pass pinned to 2 is still admitted: still incompatible, still fenced

    def test_an_impact_is_recorded_once_with_its_approval(self) -> None:
        r3 = self.propose(3, compatible)
        self.approve(r3)
        self.assertEqual(self.rows("SELECT decision_id, kind, classification FROM amendment_impacts"), [("opd_amend0003", "contract", "compatible")])
        before = self.state()
        self.assertEqual(self.approve(r3)["status"], "replayed")
        self.assertEqual(self.state(), before)


class BriefVersionTest(RouterTestCase):
    """G-4 and the bootstrap ruling: a re-version, an owner reassignment and a
    deadline extension are each a new immutable version awaiting
    confirmation; a confirmed version stays confirmed until its successor
    is."""

    def version(self, version: int, *, owner: str = "user", deadline: str = "2026-10-05T00:00:00Z", **changes) -> dict:
        return {"document": self.brief_document(TOPIC, version, **changes), "owner_operator_id": owner, "review_deadline": deadline}

    def refused_command(self, request: dict, reason: str, detail: str | None = None) -> None:
        before = self.state()
        out = self.router.version_brief(request)
        self.assertEqual((out["status"], out["reason"]), ("refused", reason), out)
        if detail is not None:
            self.assertIn(detail, out["detail"])
        self.assertEqual(self.state(), before)

    def test_a_new_version_supersedes_the_one_awaiting_confirmation(self) -> None:
        self.brief()
        out = self.router.version_brief(self.version(2, owner="user-2", feeds="rebuild, or buy"))
        self.assertEqual(out, {"status": "recorded", "topic_id": TOPIC, "brief_id": "brief-1", "version": 2, "superseded": 1})
        self.assertEqual(self.rows("SELECT version, status, owner_operator_id, review_deadline FROM intake_briefs ORDER BY version"),
                         [(1, "superseded", "user", "2026-10-01T00:00:00Z"), (2, "awaiting_confirmation", "user-2", "2026-10-05T00:00:00Z")])
        v1 = self.brief_document(TOPIC, 1)["content_hash"]
        refused = self.decide("opd_brief0001", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": v1})
        self.assertEqual(refused["status"], "rejected")  # a superseded version is never confirmed
        v2 = self.brief_document(TOPIC, 2, feeds="rebuild, or buy")["content_hash"]
        self.assertEqual(self.decide("opd_brief0002", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 2, "hash": v2})["status"], "applied")
        self.assertEqual(self.status(), "scoping")

    def test_owner_reassignment_and_deadline_extension_are_new_versions(self) -> None:
        self.brief()
        self.clock.set("2026-10-01T00:00:00Z")
        self.assertEqual(self.router.mark_brief_overdue({"topic_id": TOPIC, "brief_id": "brief-1", "version": 1})["status"], "marked")
        self.assertEqual(self.router.version_brief(self.version(2, owner="user-2", deadline="2026-10-08T00:00:00Z"))["status"], "recorded")
        self.assertEqual(self.rows("SELECT version, status, owner_operator_id, review_deadline, overdue_since IS NOT NULL FROM intake_briefs ORDER BY version"),
                         [(1, "superseded", "user", "2026-10-01T00:00:00Z", 1), (2, "awaiting_confirmation", "user-2", "2026-10-08T00:00:00Z", 0)])

    def test_a_confirmed_version_stays_confirmed_until_its_successor_is(self) -> None:
        self.to_scoping()
        self.assertEqual(self.router.version_brief(self.version(2, feeds="rebuild, or buy"))["superseded"], None)
        self.assertEqual(self.rows("SELECT version, status FROM intake_briefs ORDER BY version"), [(1, "confirmed"), (2, "awaiting_confirmation")])

    def test_each_defect_is_refused_alone(self) -> None:
        self.brief()
        good = self.version(2)
        untrue = copy.deepcopy(good)
        untrue["document"]["feeds"] = "edited after hashing"
        future = self.version(2)
        future["document"] = self.brief_document(TOPIC, 2, created_at="2026-09-28T00:00:00Z")
        cases = (("another version number", self.version(3), "request_invalid", "the next version of brief-1 is 2"),
                 ("another parent", {**good, "document": {**self.brief_document(TOPIC, 2), "parent_version": None}}, "request_invalid", None),
                 ("a hash that is not its content's", untrue, "request_invalid", "does not hash to its content hash"),
                 ("created after now", future, "request_invalid", "created by now"),
                 ("a deadline not after now", self.version(2, deadline="2026-09-27T10:00:00Z"), "request_invalid", "reviewed after now"),
                 ("a document the schema refuses", {**good, "document": {k: v for k, v in good["document"].items() if k != "feeds"}}, "request_invalid", "intake-brief.schema.json"))
        for name, request, reason, detail in cases:
            with self.subTest(name):
                self.refused_command(request, reason, detail)
        self.assertEqual(self.router.version_brief(good)["status"], "recorded")
        before = self.state()
        self.assertEqual(self.router.version_brief(good)["status"], "replayed")
        self.assertEqual(self.state(), before)
        self.refused_command({**good, "owner_operator_id": "user-3"}, "brief_version_conflict")

    def test_a_closed_or_unknown_brief_takes_no_version(self) -> None:
        self.refused_command(self.version(2), "unknown_brief")
        self.brief()
        self.x("UPDATE intake_briefs SET status = 'cancelled', closed_by = 'user', closed_at = ?, close_reason = 'withdrawn' WHERE version = 1", "2026-09-27T09:30:00Z")
        self.refused_command(self.version(2), "brief_closed")


class OverdueTest(RouterTestCase):
    """G-4: expiry marks a brief overdue on the router's clock, and never
    advances it; a deadline at instant E is over at E."""

    def test_overdue_is_marked_once_the_deadline_has_passed(self) -> None:
        self.brief()
        key = {"topic_id": TOPIC, "brief_id": "brief-1", "version": 1}
        self.clock.set("2026-09-30T23:59:59.998Z")  # the next reading is one millisecond before the deadline
        before = self.state()
        out = self.router.mark_brief_overdue(key)
        self.assertEqual((out["status"], out["reason"]), ("refused", "not_overdue"), out)
        self.assertEqual(self.state(), before)
        self.clock.set("2026-09-30T23:59:59.999Z")  # the next reading is the deadline itself
        self.assertEqual(self.router.mark_brief_overdue(key), {"status": "marked", "overdue_since": "2026-10-01T00:00:00.000Z"})
        before = self.state()
        self.assertEqual(self.router.mark_brief_overdue(key), {"status": "replayed", "overdue_since": "2026-10-01T00:00:00.000Z"})
        self.assertEqual(self.state(), before)
        self.assertEqual(self.rows("SELECT status FROM intake_briefs"), [("awaiting_confirmation",)])  # expiry never advances it
        v1 = self.brief_document(TOPIC, 1)["content_hash"]
        self.assertEqual(self.decide("opd_brief0001", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": v1})["status"], "applied")

    def test_only_a_version_awaiting_confirmation_is_marked(self) -> None:
        self.to_scoping()
        self.clock.set("2026-10-02T00:00:00Z")
        before = self.state()
        out = self.router.mark_brief_overdue({"topic_id": TOPIC, "brief_id": "brief-1", "version": 1})
        self.assertEqual((out["status"], out["reason"]), ("refused", "brief_not_awaiting"), out)
        self.assertEqual(self.state(), before)


class BriefImpactTest(RouterTestCase):
    """G-1 before any contract: pre-contract work pinned to a brief version a
    newly confirmed one supersedes completes under its pins if only the
    lineage changed, and is fenced if the content did."""

    def confirm(self, version: int, did: str, **changes) -> dict:
        request = {"document": self.brief_document(TOPIC, version, **changes), "owner_operator_id": "user-2", "review_deadline": "2026-10-05T00:00:00Z"}
        assert self.router.version_brief(request)["status"] == "recorded"
        return self.decide(did, "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": version, "hash": request["document"]["content_hash"]})

    def test_a_lineage_only_version_lets_scoping_work_complete(self) -> None:
        self.to_scoping()
        grant = self.started("inv_scoping01")
        out = self.confirm(2, "opd_brief0002")  # an owner reassignment: the same content under a new version
        self.assertEqual(out["effects"]["impact"], {"classification": "lineage_only", "work": [
            {"invocation_id": "inv_scoping01", "state": "running", "disposition": "completes_under_pins", "cancel_requested": False}]})
        response = self.finish(grant, "op_scope00001", empty_outcome("inv_scoping01"))
        self.assertEqual(response["status"], "committed", response)
        self.assertEqual(response["receipt"]["admission"]["brief"]["version"], 1)

    def test_a_content_change_fences_scoping_work(self) -> None:
        self.to_scoping()
        grant = self.started("inv_scoping01")
        out = self.confirm(2, "opd_brief0002", feeds="rebuild, or buy")
        self.assertEqual(out["effects"]["impact"]["classification"], "content_changed")
        self.assertEqual(self.rows("SELECT state, cancel_requested_by FROM invocations"), [("running", "router")])
        record = json.loads(self.value("SELECT document FROM amendment_impacts WHERE decision_id = 'opd_brief0002'"))
        self.assertEqual((record["kind"], record["superseded"]["version"], record["current"]["version"]), ("brief", 1, 2))
        env = self.envelope(grant, "op_scope00001", empty_outcome("inv_scoping01"))
        before = self.state()
        response = self.router.commit_outcome(env)
        self.assertEqual((response["status"], response["reason"]), ("rejected", "amendment_pending"), response)
        self.assertEqual(self.state(), before)


class AmendmentRestartTest(ContractWorld):
    """RG-9: impact records and the pins they judge survive a restart; a
    reopened router still fences what an approval made incompatible."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)
        api.open_store(self.directory / "store.sqlite3", create=True).close()
        self.db = sqlite3.connect(self.directory / "store.sqlite3", isolation_level=None)
        self.db.executescript(store_fixtures.CONNECTION_TEXT)
        self.store = api.open_store(self.directory / "store.sqlite3")
        self.spool, self.clock, self.ids, self.faults = rf.Spool(), rf.Clock(), rf.Ids(), {}
        self.router = self.make_router()
        self.seed()
        self.build_world()

    def tearDown(self) -> None:
        self.router.close()
        self.db.close()
        self._tmp.cleanup()

    def reopen(self) -> None:
        self.router.close()
        self.store = api.open_store(self.directory / "store.sqlite3")
        self.router = self.make_router()

    def test_impacts_and_pins_survive_a_restart(self) -> None:
        self.research()
        fenced_work = self.started("inv_disco001", "discovery")
        staged, size = self.stage(empty_outcome("inv_disco001"))
        self.ready(fenced_work, staged)
        self.approve(self.propose(3, compatible))
        self.approve(self.propose(4, protocol_changed))
        tables = ("amendment_impacts", "contract_revisions", "invocations")
        before = {t: self.rows(f"SELECT * FROM {t} ORDER BY rowid") for t in tables}
        self.reopen()
        self.assertEqual({t: self.rows(f"SELECT * FROM {t} ORDER BY rowid") for t in tables}, before)
        env = self.envelope(fenced_work, "op_disco00001", empty_outcome("inv_disco001"))
        env["payload_digest"], env["payload_size_bytes"] = staged, size
        self.assertEqual(self.router.commit_outcome(env)["reason"], "amendment_pending")


class CompatibilityRuleTest(RouterTestCase):
    """The structural rule, one dimension at a time, on the example contract:
    each edit and the class a hand reading of the module docstring gives it."""

    def test_each_dimension_decides_alone(self) -> None:
        from gen2.router.amendments import brief_compatibility, contract_compatibility
        base = contract_doc(2, 1)

        def edited(edit) -> dict:
            doc = copy.deepcopy(base)
            edit(doc)
            return doc
        cases = (("a decision-record edit", compatible, "compatible"),
                 ("an importance change only", lambda d: d["obligations"][1]["importance"]["operator_rating"].update(band="limited"), "compatible"),
                 ("a new obligation (inventory)", lambda d: d["obligations"].append({**copy.deepcopy(d["obligations"][1]), "obligation_id": "O-3"}), "compatible"),
                 ("the protocol revision alone", lambda d: d.update(protocol_revision=2), "protocol_changed"),
                 ("an eligibility criterion alone", lambda d: d["eligibility_protocol"]["criteria"][1].update(description="Reports cost."), "protocol_changed"),
                 ("a stopping profile alone", lambda d: d["stopping_profiles"][0].update(profile_id="SP-other"), "protocol_changed"),
                 ("the applicability rules alone", lambda d: d.update(applicability_rules=d["applicability_rules"][:1] + d["applicability_rules"][:1]), "protocol_changed"),
                 ("a shared obligation redefined", lambda d: d["obligations"][0].update(text="Compare cost only."), "protocol_changed"),
                 ("the framing version", reframed, "reframed"))
        for name, edit, expected in cases:
            with self.subTest(name):
                self.assertEqual(contract_compatibility(base, edited(edit)), expected)
        v1 = self.brief_document(TOPIC, 1)
        self.assertEqual(brief_compatibility(v1, self.brief_document(TOPIC, 2)), "lineage_only")
        self.assertEqual(brief_compatibility(v1, self.brief_document(TOPIC, 2, feeds="rebuild, or buy")), "content_changed")
