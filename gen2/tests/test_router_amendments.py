"""Brief and contract versions, and G-1 amendment impact (task 1d).

Trace: INVARIANTS G-1, G-4, G-6, G-7, C-10, C-12, V-10, §13 (Phase 1: the
fake-executor lifecycle of briefs, confirmation/amendment fencing, owner
reassignment and deadline extension); the 1b review's bootstrap ruling
(minimal router-owned brief and amendment version commands) and its ruling
on proposal 3 (amendment_pending was interim fail-closed); the 1a review
(G-1 impact before Phase 1 acceptance); the 1d review's findings 1 (framing
content, version binding, no revival of stale pins) and 6 (each half of a
version's lineage refused alone); the 1d-repair review's finding 1 (the
approved inventory: an obligation removed or issued again under another id,
and a coverage cell withdrawn, are not compatible) and its ruling on the
flagged classification choices; gen2/router/amendments.py.

The contract world: revision 1 is the draft the operator rated (a fixture,
contract construction being Phase 2), revision 2 carries those ratings and
is approved through the router; amendments are proposed and approved
through the router. Documents follow the schema-valid example contract.

Oracles: hand-written expectations and dispositions; raw SQL read-back of
the whole store (every table but the audit log) around each refusal; the
class of each contract edit comes from DESIGN_ORACLE, which cites the
governing design (G-1, G-2, G-5, G-6, G-7, RG-6, the flow architecture and
the methodology synthesis) for every section, not from amendments.py.

Structural limits: work is exercised at the router, with fixture
invocations standing in for executors (the supervisor's side of a
cancellation is test_supervisor_*'s); the compatibility rule is structural,
so these tests show which edits it classes as which by section, not that a
given edit is semantically harmful (a harmless edit to protocol or framing
text is still incompatible, by design). A revision written around the
router (raw SQL) stands in for history the router itself refuses to write,
such as a framing label used again.
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
    """A surveillance-policy edit — when a completed topic is re-checked
    (flow S8) — with no framing, protocol or obligation change
    (CompatibilityRuleTest states why it is compatible)."""
    doc["surveillance_policy"]["freshness_requirement"]["max_currency_age_days"] = 90


def protocol_changed(doc: dict) -> None:
    doc["protocol_revision"] = 2
    doc["eligibility_protocol"]["protocol_version"] = 2
    doc["eligibility_protocol"]["criteria"][1]["description"] = "Reports an omission, coverage or cost outcome for elicited requirements."


REFRAMED_QUESTION = "Which facets does intake design cause to be missed, and at what operator cost?"


def reframed(doc: dict) -> None:
    """A reframe: a framework link's key question reworded, under the next framing version (G-6)."""
    doc["facet_map"]["framing_version"] = 2
    doc["facet_map"]["analytic_framework"]["links"][0]["key_question"] = REFRAMED_QUESTION


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
        document = self.value("SELECT document FROM amendment_impacts WHERE decision_id = ?", did)
        self.assertIsNotNone(document, f"no impact is recorded for {did}")
        return json.loads(document)

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

    def promote_revision_one(self, grant: dict, op: str) -> dict:
        outcome = {**empty_outcome(grant["invocation_id"], "interim_transition"), "claim_promotions": [{"claim_id": "clm_00000001", "revision": 1}]}
        before = self.state()
        response = self.router.commit_outcome(self.envelope(grant, op, outcome))
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("contract-admitted work adopts it as a new revision", response.get("detail"))
        self.assertEqual(self.state(), before)
        return response

    def adopt(self, grant: dict) -> None:
        text = self.artifact(b"a load-bearing claim")
        adopt = {**empty_outcome(grant["invocation_id"], "interim_transition"),
                 "claims": [{"claim_id": "clm_00000001", "revision": 2, "text_ref": text, "load_bearing": False, "required_access_tier": None}],
                 "claim_promotions": [{"claim_id": "clm_00000001", "revision": 2}]}
        self.assertEqual(self.router.commit_outcome(self.envelope(grant, "op_adopt000001", adopt, refs=[text]))["status"], "committed")
        self.assertEqual(self.rows("SELECT revision, status FROM claims ORDER BY revision"), [(1, "provisional"), (2, "accepted_support")])

    def refused_command(self, method, request: dict, reason: str, detail: str | None = None) -> None:
        before = self.state()
        out = getattr(self.router, method)(request)
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        if detail is not None:
            self.assertIn(detail, out.get("detail", ""))
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

    def test_the_same_amendment_again_replays(self) -> None:
        """The accepted path of the amendment-conflict guard, on its own."""
        doc = contract_doc(3, 2, edit=compatible)
        self.assertEqual(self.router.propose_amendment({"document": doc})["status"], "recorded")
        before = self.state()
        self.assertEqual(self.router.propose_amendment({"document": copy.deepcopy(doc)}), {"status": "replayed", "topic_id": TOPIC, "revision": 3})
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
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"), out)
        self.assertIn("does not revise the approved revision 3", out.get("detail"))
        self.assertEqual(self.state(), before)

    def test_a_framing_change_is_approved_as_a_reframe_and_only_as_one(self) -> None:
        r3 = self.propose(3, reframed)
        compat = self.propose(4, compatible, parent=2)
        before = self.state()
        for doc, kind in ((r3, "amendment_approval"), (compat, "reframe_approval")):
            with self.subTest(kind):
                out = self.approve(doc, kind, did=f"opd_wrong{doc['revision']:04d}")
                self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"), out)
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
        self.assertEqual(out.get("effects", {}).get("queue_transition"), {"from": "completed_with_qualified_conclusions", "to": "queued"})
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
        self.assertEqual(out.get("effects", {}).get("impact", {}).get("classification"), "compatible")
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

    def test_a_compatible_amendment_lets_every_kind_complete_under_its_pins(self) -> None:
        """All five kinds, a delegate among them, admitted under revision 2
        and running through a compatible approval, commit under revision 2."""
        parent = self.started("inv_research01")
        grants = [parent, *(self.started(f"inv_{kind[:6]}01", kind) for kind in ("discovery", "verification", "checkpoint"))]
        delegate = self.started("inv_deleg001", "delegate", parent=parent)
        self.approve(self.propose(3, compatible))
        record = self.impact("opd_amend0003")
        self.assertEqual({w["invocation_id"]: (w["disposition"], w["cancel_requested"]) for w in record["work"]},
                         {g["invocation_id"]: ("completes_under_pins", False) for g in (*grants, delegate)})
        for n, grant in enumerate((delegate, *grants[1:], parent)):  # the delegate before its parent's final outcome
            with self.subTest(grant["kind"]):
                response = self.finish(grant, f"op_kind{n:07d}")
                self.assertEqual(response["status"], "committed", response)
                self.assertEqual(response["receipt"]["admission"]["contract"]["revision"], 2)

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
        self.assertEqual(out.get("effects", {}).get("impact", {}).get("work"), record["work"])
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
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("contract revision 2 was superseded (protocol_changed)", response.get("detail"))
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
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("contract-admitted work adopts it as a new revision", response.get("detail"))
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
        self.assertEqual((self.impact("opd_amend0003")["standing"], record["standing"]),
                         ([{"revision": 2, "classification": "reframed"}], [{"revision": 3, "classification": "compatible"}]))
        self.assertEqual((record["screening_labels"], record["claims"], record["coverage"]), ([], [], []))
        self.assertEqual([w["disposition"] for w in record["work"]], ["fenced"])  # the pass pinned to 2 is still admitted: still incompatible, still fenced

    def test_an_impact_is_recorded_once_with_its_approval(self) -> None:
        r3 = self.propose(3, compatible)
        self.approve(r3)
        self.assertEqual(self.rows("SELECT decision_id, kind, classification FROM amendment_impacts"), [("opd_amend0003", "contract", "compatible")])
        before = self.state()
        self.assertEqual(self.approve(r3)["status"], "replayed")
        self.assertEqual(self.state(), before)


class VersionBindingTest(ContractWorld):
    """G-6, C-12: in a topic's history a framing version names one framing,
    and a protocol revision one protocol (amendments.py, "Versions name
    content"). Each refusal leaves the whole store as it was; each has an
    accepted twin differing from it in the label alone."""

    def test_a_changed_framing_needs_a_new_framing_version(self) -> None:
        for name, expected, _, basis, edit in DESIGN_ORACLE:
            if expected != FRAMING or name == "the framing version alone":
                continue
            with self.subTest(name, basis=basis):  # the review's probe (a key question reworded, the label kept) among them
                self.refused_command("propose_amendment", {"document": contract_doc(3, 2, edit=edit)}, "request_invalid",
                                     "a changed framing takes a new framing version, above every recorded one (1)")
        twin = contract_doc(3, 2, edit=lambda d: (d["facet_map"]["analytic_framework"]["links"][0].update(key_question=REFRAMED_QUESTION),
                                                  d["facet_map"].update(framing_version=2)))
        self.assertEqual(self.router.propose_amendment({"document": twin}), {"status": "recorded", "topic_id": TOPIC, "revision": 3, "against_approved": "reframed"})

    def test_an_unchanged_framing_keeps_its_version(self) -> None:
        self.refused_command("propose_amendment", {"document": contract_doc(3, 2, edit=lambda d: d["facet_map"].update(framing_version=2))},
                             "request_invalid", "the framing is the approved revision's, so it keeps framing version 1")
        self.assertEqual(self.router.propose_amendment({"document": contract_doc(3, 2, edit=compatible)})["against_approved"], "compatible")

    def test_a_framing_version_never_names_another_framing(self) -> None:
        self.approve(self.propose(3, reframed), "reframe_approval")
        back = contract_doc(4, 3)  # revision 2's framing, under its old label
        self.refused_command("propose_amendment", {"document": back}, "request_invalid", "above every recorded one (2)")
        other = contract_doc(4, 3, edit=lambda d: (reframed(d), d["facet_map"]["analytic_framework"]["links"][1].update(key_question="Another question.")))
        self.refused_command("propose_amendment", {"document": other}, "request_invalid", "above every recorded one (2)")  # label 2, not revision 3's framing
        twin = contract_doc(4, 3, edit=lambda d: d["facet_map"].update(framing_version=3))  # revision 2's framing back, as a new framing version
        self.assertEqual(self.router.propose_amendment({"document": twin})["against_approved"], "reframed")

    def test_a_protocol_revision_names_one_protocol(self) -> None:
        criterion = lambda d: d["eligibility_protocol"]["criteria"][1].update(description="Reports cost.")  # noqa: E731
        self.refused_command("propose_amendment", {"document": contract_doc(3, 2, edit=criterion)}, "request_invalid",
                             "a changed protocol takes a new protocol revision, above every recorded one (1)")
        self.refused_command("propose_amendment", {"document": contract_doc(3, 2, edit=lambda d: d.update(protocol_revision=2))}, "request_invalid",
                             "the protocol is the approved revision's, so it keeps protocol revision 1")
        self.approve(self.propose(3, protocol_changed))
        self.refused_command("propose_amendment", {"document": contract_doc(4, 3)}, "request_invalid", "above every recorded one (2)")  # revision 2's protocol, its old label
        twin = contract_doc(4, 3, edit=lambda d: d.update(protocol_revision=3))
        self.assertEqual(self.router.propose_amendment({"document": twin})["against_approved"], "protocol_changed")


class StandingTest(ContractWorld):
    """G-1: incompatible results are never silently reused. What a recorded
    impact made stale stays stale when a later revision matches it again;
    only new work under the current revision restores authority (V-10).
    The oracle: the impact records (raw SQL) and hand-written refusals; the
    pairwise rule is asserted to call the two revisions compatible, so the
    refusal is the record's."""

    def test_a_framing_label_written_back_revives_no_claim(self) -> None:
        """The review's history: a claim under framing 1, a reframe to 2,
        then revision 2's very document again as revision 4 — framing 1's
        label and content. The router refuses that label (VersionBindingTest),
        so this draft is written around it; its approval is a reframe."""
        from gen2.router.amendments import contract_compatibility
        self.assertEqual(self.finish(self.research(load_bearing=False), "op_finish0001")["status"], "committed")
        self.approve(self.propose(3, reframed), "reframe_approval")
        back = contract_doc(4, 3)
        self.store_draft(back)
        self.assertEqual(self.approve(back, "reframe_approval")["status"], "applied")
        self.assertEqual(contract_compatibility(contract_doc(2, 1), back), "compatible")
        third, fourth = self.impact("opd_amend0003"), self.impact("opd_amend0004")
        self.assertEqual((third["standing"], [(c["claim_id"], c["disposition"]) for c in third["claims"]]),
                         ([{"revision": 2, "classification": "reframed"}], [("clm_00000001", "stale_under_new_framing")]))
        self.assertEqual((fourth["standing"], fourth["claims"], fourth["screening_labels"], fourth["coverage"], fourth["reopened_exclusions"]),
                         ([{"revision": 3, "classification": "reframed"}], [], [], [], []))  # revision 2 stays as the third impact left it
        promoter = self.started("inv_research02")
        self.promote_revision_one(promoter, "op_promote0001")
        self.adopt(promoter)

    def test_a_restored_obligation_revives_no_work_or_claim(self) -> None:
        """Through the router alone: revision 3 redefines an obligation
        (protocol_changed), revision 4 restores revision 2's definition
        (protocol_changed from 3). Pairwise, 2 and 4 are compatible."""
        from gen2.router.amendments import contract_compatibility
        grant = self.research(load_bearing=False)  # running under revision 2, with a provisional claim
        redefined = {"text": "Compare missed-facet rates at matched operator cost only.", "importance": {"proposed": None, "operator_rating": None}}  # unrated: its rating was of the old one (G-2)
        self.approve(self.propose(3, lambda d: d["obligations"][0].update(redefined)))
        self.assertEqual(self.approve(self.propose(4))["status"], "applied")
        self.assertEqual(contract_compatibility(contract_doc(2, 1), contract_doc(4, 3)), "compatible")
        fourth = self.impact("opd_amend0004")
        self.assertEqual((fourth["classification"], fourth["standing"], [(w["invocation_id"], w["disposition"]) for w in fourth["work"]]),
                         ("protocol_changed", [{"revision": 3, "classification": "protocol_changed"}], [("inv_research01", "fenced")]))
        before = self.state()
        response = self.router.commit_outcome(self.envelope(grant, "op_final000001", empty_outcome("inv_research01")))
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("contract revision 2 was superseded (protocol_changed)", response.get("detail"))
        self.assertEqual(self.state(), before)
        ended = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": "inv_research01", "to_state": "cancelled",
                                               "end_evidence_ref": self.evidence(grant, ())})
        self.assertEqual(ended["status"], "recorded", ended)
        self.assertEqual(self.router.requeue({"invocation_id": "inv_research01", "requested_by": "operator", "reason": "re-run under revision 4"})["status"], "requeued")
        adopter = self.started("inv_research02", retry_of="inv_research01")
        self.promote_revision_one(adopter, "op_promote0001")
        self.adopt(adopter)

    def test_a_version_no_impact_lists_is_not_reused(self) -> None:
        """Fail closed: an impact recorded without standing (the shape before
        it was recorded) leaves the version it superseded unjudged, and its
        work is fenced as `unrecorded`, not taken to be compatible."""
        grant = self.research()
        insert = self.router._store.insert

        def without_standing(table: str, row: dict) -> None:
            if table == "amendment_impacts":
                row = {**row, "document": {k: v for k, v in row["document"].items() if k != "standing"}}
            insert(table, row)
        self.router._store.insert = without_standing
        self.approve(self.propose(3, compatible))
        self.router._store.insert = insert
        self.assertNotIn("standing", self.impact("opd_amend0003"))
        before = self.state()
        response = self.router.commit_outcome(self.envelope(grant, "op_final000001", empty_outcome("inv_research01")))
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("(unrecorded)", response.get("detail"))
        self.assertEqual(self.state(), before)


class InventoryImpactTest(ContractWorld):
    """G-1 for the approved inventory (Astra 1d-repair review finding 1): an
    amendment withdrawing an obligation — removed, or issued again under
    another id — or a coverage cell's scope is protocol_changed, so what is
    pinned to the revision it supersedes is fenced as a whole (a revision-wide
    fence; the review's ruling finds that sufficient at Phase 1's scope): the
    running pass's cancellation requested and its final commit refused, its
    coverage and claim listed stale, the claim promoted only as a revision
    adopted under the current revision (V-10). Nothing listed is rewritten:
    the claim, the observation scoped to the withdrawn obligation and the
    claim's link to it stay. An addition stays compatible. The review's
    probes, through the router's proposal and approval; the claim's typed
    link to O-2 is seeded (raw SQL: Phase 1's outcome schema has no
    link-writing operation). The withdrawals one at a time are
    CompatibilityRuleTest's (DESIGN_ORACLE)."""

    def cost_result(self) -> dict:
        """The review's world: a research pass under revision 2, still
        running, with a provisional cost claim linked to O-2 and a search
        observation scoped to O-2."""
        grant = self.started("inv_research01")
        text = self.artifact(b"Author plus audit costs less than committee intake in the five-station fleet.")
        outcome = empty_outcome("inv_research01", "interim_transition")
        outcome["claims"] = [{"claim_id": "clm_00000001", "revision": 1, "text_ref": text, "load_bearing": False, "required_access_tier": None}]
        self.assertEqual(self.router.commit_outcome(self.envelope(grant, "op_capture0001", outcome, refs=[text]))["status"], "committed")
        self.x("INSERT INTO claim_source_links (claim_id, claim_revision, work_id, source_version, topic_id, contract_revision, obligation_id, spans, contribution, "
               "evidence_origin_lineage, created_at) VALUES ('clm_00000001', 1, 'wrk_00000001', 'v1', ?, 2, 'O-2', '[]', 'answer', 'review-source', "
               "'2026-09-27T10:00:00Z')", TOPIC)
        request = {"q": "cost comparison"}
        observation = {"observation_id": "obs_cost000001", "request": request, "request_identity": canonical.logical_hash(request), "attempt": 1, "lane": "crossref",
                       "obligation_ids": ["O-2"], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:01Z", "coverage_state": "searched_empty",
                       "result_count": 0, "completeness": "complete", "error_class": None, "capability_fact_id": None, "policy_version": "pol-1", "cost_units": None,
                       "gateway_call_ref": None}
        self.assertEqual(self.router.record_observation({"capability_id": grant["capability_id"], "invocation_id": "inv_research01", "observation": observation,
                                                         "retrieval_events": []})["status"], "recorded")
        return grant

    def retained(self) -> list:
        return [self.rows(f"SELECT * FROM {table} ORDER BY rowid") for table in ("claims", "search_observations", "claim_source_links")]

    def fenced(self, grant: dict, did: str) -> None:
        """`did`'s impact fences the pass and lists its coverage and claim
        stale; the pass's final commit is refused, the store unchanged."""
        record = self.impact(did)
        self.assertEqual((record["classification"], [(w["invocation_id"], w["disposition"], w["cancel_requested"]) for w in record["work"]],
                          record["coverage"], [(c["claim_id"], c["disposition"]) for c in record["claims"]]),
                         ("protocol_changed", [("inv_research01", "fenced", True)], [{"observation_id": "obs_cost000001", "disposition": "stale_under_new_protocol"}],
                          [("clm_00000001", "stale_under_new_protocol")]))
        before = self.state()
        response = self.router.commit_outcome(self.envelope(grant, "op_final000001", empty_outcome("inv_research01")))
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("contract revision 2 was superseded (protocol_changed)", response.get("detail"))
        self.assertEqual(self.state(), before)

    def adopted_only(self, grant: dict) -> None:
        """The fenced pass ends and is re-queued; its retry, under the current
        revision, cannot promote the old claim, and adopts it as revision 2."""
        ended = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": "inv_research01", "to_state": "cancelled",
                                               "end_evidence_ref": self.evidence(grant, ())})
        self.assertEqual(ended["status"], "recorded", ended)
        self.assertEqual(self.router.requeue({"invocation_id": "inv_research01", "requested_by": "operator", "reason": "re-run under the current revision"})["status"],
                         "requeued")
        adopter = self.started("inv_research02", retry_of="inv_research01")
        self.promote_revision_one(adopter, "op_promote0001")
        self.adopt(adopter)

    def withdrawal(self, edit) -> None:
        """Propose and approve `edit` as revision 3 over the cost result: classed
        protocol_changed at proposal and approval, fencing it; nothing listed
        is rewritten; only adoption promotes the claim."""
        grant = self.cost_result()
        kept = self.retained()
        doc = contract_doc(3, 2, edit=edit)
        self.assertEqual(self.router.propose_amendment({"document": doc}), {"status": "recorded", "topic_id": TOPIC, "revision": 3, "against_approved": "protocol_changed"})
        out = self.approve(doc)
        self.assertEqual((out["status"], out["effects"]["impact"]["classification"]), ("applied", "protocol_changed"), out)
        self.fenced(grant, "opd_amend0003")
        self.assertEqual(self.retained(), kept)
        self.adopted_only(grant)

    def test_a_removed_obligation_fences_its_work_coverage_and_claim(self) -> None:
        """The review's removal probe: O-2 removed, its cell marked deliberately out."""
        self.withdrawal(removed)

    def test_an_obligation_removed_alone_fences(self) -> None:
        """O-2 removed, the matrix untouched (its cell still names it): the removal alone withdraws it."""
        self.withdrawal(lambda d: d["obligations"].pop(1))

    def test_a_scope_removing_cell_alone_fences(self) -> None:
        """O-2 kept as it was, its cell put deliberately out: the cell alone withdraws it."""
        self.withdrawal(lambda d: (cost_cell(d).pop("obligation_ids"), cost_cell(d).update(state="deliberately_out", rationale="Cost is no longer in scope.")))

    def test_a_redefinition_under_its_own_id_is_fenced(self) -> None:
        """The review's control: O-2 redefined as O-2."""
        self.withdrawal(redefined_cost)

    def test_a_redefinition_under_a_new_id_is_fenced_the_same(self) -> None:
        """The review's replacement probe: the same redefinition issued as
        O-new, its cell naming O-new, is fenced as the redefinition under O-2
        is (the previous test): the id's spelling decides nothing."""
        self.withdrawal(reissued)

    def test_a_filled_gap_lets_work_complete_and_its_claim_promote(self) -> None:
        """The accepted control (G-5, R ruling 2): an obligation added in an
        existing facet, filling its gap cell, leaves the pass to complete
        under revision 2 and its claim to be promoted."""
        grant = self.cost_result()
        doc = contract_doc(3, 2, edit=gap_filled)
        self.assertEqual(self.router.propose_amendment({"document": doc})["against_approved"], "compatible")
        self.assertEqual(self.approve(doc)["effects"]["impact"]["classification"], "compatible")
        record = self.impact("opd_amend0003")
        self.assertEqual(([(w["invocation_id"], w["disposition"], w["cancel_requested"]) for w in record["work"]], record["coverage"],
                          [(c["claim_id"], c["disposition"]) for c in record["claims"]]),
                         ([("inv_research01", "completes_under_pins", False)], [{"observation_id": "obs_cost000001", "disposition": "valid"}],
                          [("clm_00000001", "valid")]))
        response = self.finish(grant, "op_final000001", {**empty_outcome("inv_research01"), "claim_promotions": [{"claim_id": "clm_00000001", "revision": 1}]})
        self.assertEqual(response["status"], "committed", response)
        self.assertEqual(response["receipt"]["admission"]["contract"]["revision"], 2)
        self.assertEqual(self.rows("SELECT revision, status FROM claims"), [(1, "accepted_support")])

    def test_a_restored_obligation_revives_nothing(self) -> None:
        """Revision 3 removes O-2, revision 4 restores revision 2's inventory
        (itself a withdrawal from 3: its deliberately-out cell brought back).
        Pairwise, 2 and 4 are compatible; the record still fences the pass,
        and the claim is still promoted only by adoption."""
        from gen2.router.amendments import contract_compatibility
        grant = self.cost_result()
        self.approve(self.propose(3, removed))
        fourth = self.propose(4)
        self.assertEqual(self.approve(fourth)["status"], "applied")
        self.assertEqual(contract_compatibility(contract_doc(2, 1), fourth), "compatible")
        record = self.impact("opd_amend0004")
        self.assertEqual((record["classification"], record["standing"], [(w["invocation_id"], w["disposition"]) for w in record["work"]], record["claims"], record["coverage"]),
                         ("protocol_changed", [{"revision": 3, "classification": "protocol_changed"}], [("inv_research01", "fenced")], [], []))
        before = self.state()
        response = self.router.commit_outcome(self.envelope(grant, "op_final000001", empty_outcome("inv_research01")))
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("contract revision 2 was superseded (protocol_changed)", response.get("detail"))
        self.assertEqual(self.state(), before)
        self.adopted_only(grant)


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
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        if detail is not None:
            self.assertIn(detail, out.get("detail", ""))
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
        self.assertEqual(self.router.version_brief(self.version(2, feeds="rebuild, or buy")).get("superseded"), None)
        self.assertEqual(self.rows("SELECT version, status FROM intake_briefs ORDER BY version"), [(1, "confirmed"), (2, "awaiting_confirmation")])

    def test_each_defect_is_refused_alone(self) -> None:
        self.brief()
        good = self.version(2)
        untrue = copy.deepcopy(good)
        untrue["document"]["feeds"] = "edited after hashing"
        future = self.version(2)
        future["document"] = self.brief_document(TOPIC, 2, created_at="2026-09-28T00:00:00Z")
        lineage = "the next version of brief-1 is 2, with parent 1"
        cases = (("another version number, the parent right", {**good, "document": self.brief_document(TOPIC, 3, parent_version=1)}, "request_invalid", lineage),
                 ("another parent, the version right", {**good, "document": self.brief_document(TOPIC, 2, parent_version=None)}, "request_invalid", lineage),
                 ("the version as its own parent", {**good, "document": self.brief_document(TOPIC, 2, parent_version=2)}, "request_invalid", lineage),
                 ("a hash that is not its content's", untrue, "request_invalid", "does not hash to its content hash"),
                 ("created after now", future, "request_invalid", "created by now"),
                 ("a deadline not after now", self.version(2, deadline="2026-09-27T10:00:00Z"), "request_invalid", "reviewed after now"),
                 ("a document the schema refuses", {**good, "document": {k: v for k, v in good["document"].items() if k != "feeds"}}, "request_invalid", "intake-brief.schema.json"))
        for name, request, reason, detail in cases:
            with self.subTest(name):
                if detail == lineage:  # its lineage alone is wrong: the document hashes true, so only the lineage check can refuse it
                    self.assertEqual(canonical.content_hash(request["document"]), request["document"]["content_hash"])
                self.refused_command(request, reason, detail)
        self.clock.set("2026-10-04T23:59:59.999Z")  # the next reading is the requested deadline itself: over at that instant, so refused
        self.refused_command(self.version(2, deadline="2026-10-05T00:00:00Z"), "request_invalid", "reviewed after now")
        self.clock.set("2026-09-27T10:00:00Z")
        self.assertEqual(self.router.version_brief(good)["status"], "recorded")
        before = self.state()
        self.assertEqual(self.router.version_brief(good)["status"], "replayed")
        self.assertEqual(self.state(), before)
        self.refused_command({**good, "owner_operator_id": "user-3"}, "brief_version_conflict")

    def test_the_same_version_again_replays(self) -> None:
        """The accepted path of the brief-version conflict guard, on its own."""
        self.brief()
        request = self.version(2, owner="user-2")
        self.assertEqual(self.router.version_brief(request)["status"], "recorded")
        before = self.state()
        self.assertEqual(self.router.version_brief(copy.deepcopy(request)), {"status": "replayed", "topic_id": TOPIC, "brief_id": "brief-1", "version": 2})
        self.assertEqual(self.state(), before)

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
        self.assertEqual((out["status"], out.get("reason")), ("refused", "not_overdue"), out)
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
        self.assertEqual((out["status"], out.get("reason")), ("refused", "brief_not_awaiting"), out)
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
        self.assertEqual(out.get("effects", {}).get("impact"), {"classification": "lineage_only", "work": [
            {"invocation_id": "inv_scoping01", "state": "running", "disposition": "completes_under_pins", "cancel_requested": False}]})
        response = self.finish(grant, "op_scope00001", empty_outcome("inv_scoping01"))
        self.assertEqual(response["status"], "committed", response)
        self.assertEqual(response["receipt"]["admission"]["brief"]["version"], 1)

    def test_a_content_change_fences_scoping_work(self) -> None:
        self.to_scoping()
        grant = self.started("inv_scoping01")
        out = self.confirm(2, "opd_brief0002", feeds="rebuild, or buy")
        self.assertEqual(out.get("effects", {}).get("impact", {}).get("classification"), "content_changed")
        self.assertEqual(self.rows("SELECT state, cancel_requested_by FROM invocations"), [("running", "router")])
        record = json.loads(self.value("SELECT document FROM amendment_impacts WHERE decision_id = 'opd_brief0002'"))
        self.assertEqual((record["kind"], record["superseded"]["version"], record["current"]["version"]), ("brief", 1, 2))
        env = self.envelope(grant, "op_scope00001", empty_outcome("inv_scoping01"))
        before = self.state()
        response = self.router.commit_outcome(env)
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertEqual(self.state(), before)


    def test_a_brief_restored_revives_no_scoping_work(self) -> None:
        """G-1 before any contract: v2 changes the content, v3 restores v1's.
        Pairwise v1 and v3 differ in lineage alone; v1's work stays fenced."""
        from gen2.router.amendments import brief_compatibility
        self.to_scoping()
        grant = self.started("inv_scoping01")
        self.confirm(2, "opd_brief0002", feeds="rebuild, or buy")
        out = self.confirm(3, "opd_brief0003")
        self.assertEqual(brief_compatibility(self.brief_document(TOPIC, 1), self.brief_document(TOPIC, 3)), "lineage_only")
        self.assertEqual(out.get("effects", {}).get("impact"), {"classification": "content_changed", "work": [
            {"invocation_id": "inv_scoping01", "state": "running", "disposition": "fenced", "cancel_requested": False}]})  # requested already, by v2's
        record = json.loads(self.value("SELECT document FROM amendment_impacts WHERE decision_id = 'opd_brief0003'"))
        self.assertEqual((record["brief_id"], record["standing"]), ("brief-1", [{"version": 2, "classification": "content_changed"}]))
        before = self.state()
        response = self.router.commit_outcome(self.envelope(grant, "op_scope00001", empty_outcome("inv_scoping01")))
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("brief brief-1 v1 was superseded (content_changed)", response.get("detail"))
        self.assertEqual(self.state(), before)


class BriefLineageTest(RouterTestCase):
    """G-1 before any contract, with two briefs in one topic's history (one
    confirmed at a time, DDL): a pin is judged by its own brief's lineage
    and that brief's impacts only."""

    def second_brief(self, version: int, did: str, **changes) -> dict:
        """brief-2 (raw SQL for its first version: intake's, Phase 2), confirmed."""
        doc = self.brief_document(TOPIC, version, brief_id="brief-2", objective_in_operator_words="is intake the bottleneck", **changes)
        if version == 1:
            self.x("INSERT INTO intake_briefs (topic_id, brief_id, version, parent_version, content_hash, document, owner_operator_id, status, created_at, review_deadline) "
                   "VALUES (?, 'brief-2', 1, NULL, ?, ?, 'user', 'awaiting_confirmation', ?, ?)", TOPIC, doc["content_hash"], json.dumps(doc), doc["created_at"],
                   "2026-10-01T00:00:00Z")
        else:
            request = {"document": doc, "owner_operator_id": "user-2", "review_deadline": "2026-10-05T00:00:00Z"}
            assert self.router.version_brief(request)["status"] == "recorded"
        out = self.decide(did, "brief_confirmation", {"kind": "intake_brief", "ref": "brief-2", "revision": version, "hash": doc["content_hash"]})
        assert out["status"] == "applied", out
        return out

    def first_brief_v2(self, **changes) -> None:
        doc = self.brief_document(TOPIC, 2, **changes)
        assert self.router.version_brief({"document": doc, "owner_operator_id": "user-2", "review_deadline": "2026-10-05T00:00:00Z"})["status"] == "recorded"
        assert self.decide("opd_brief0102", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 2, "hash": doc["content_hash"]})["status"] == "applied"
        self.x("UPDATE intake_briefs SET status = 'archived', closed_by = 'user', closed_at = ?, close_reason = 'replaced by brief-2' "
               "WHERE brief_id = 'brief-1' AND version = 2", "2026-09-27T10:00:00Z")

    def test_a_pin_whose_brief_is_no_longer_current_is_fenced(self) -> None:
        self.to_scoping()
        grant = self.started("inv_scoping01")  # pinned to brief-1 v1
        self.first_brief_v2()  # lineage only: the pass could complete under v1 while brief-1 is current
        self.second_brief(1, "opd_brief0201")  # brief-1 archived, brief-2 now the topic's confirmed brief
        before = self.state()
        response = self.router.commit_outcome(self.envelope(grant, "op_scope00001", empty_outcome("inv_scoping01")))
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("brief brief-1 v1 was superseded (superseded)", response.get("detail"))
        self.assertEqual(self.state(), before)

    def test_another_briefs_impacts_do_not_judge_a_pin(self) -> None:
        self.to_scoping()
        self.first_brief_v2(feeds="rebuild, or buy")  # brief-1's impact lists its version 1 stale (content_changed)
        self.second_brief(1, "opd_brief0201")
        grant = self.started("inv_scoping01")  # pinned to brief-2 v1
        self.second_brief(2, "opd_brief0202")  # lineage only: brief-2 v1 still stands
        response = self.finish(grant, "op_scope00001", empty_outcome("inv_scoping01"))
        self.assertEqual(response["status"], "committed", response)
        brief = response["receipt"]["admission"]["brief"]
        self.assertEqual((brief["brief_id"], brief["version"]), ("brief-2", 1))


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
        self.assertEqual(self.router.commit_outcome(env).get("reason"), "amendment_pending")

    def test_standing_survives_a_restart(self) -> None:
        """What an impact made stale is still stale after reopening, with a
        revision matching it again current."""
        grant = self.research(load_bearing=False)
        redefined = {"text": "Compare missed-facet rates at matched operator cost only.", "importance": {"proposed": None, "operator_rating": None}}
        self.approve(self.propose(3, lambda d: d["obligations"][0].update(redefined)))
        self.approve(self.propose(4))  # revision 2's obligation again
        self.reopen()
        response = self.router.commit_outcome(self.envelope(grant, "op_final000001", empty_outcome("inv_research01")))
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("contract revision 2 was superseded (protocol_changed)", response.get("detail"))


def gap_filled(doc: dict) -> None:
    """A new obligation filling the example's one gap cell (F-cost x effect),
    the cell now covered by it: a sub-question inside an existing facet."""
    doc["obligations"].append({**copy.deepcopy(doc["obligations"][1]), "obligation_id": "O-3", "text": "Compare omission rates on the cost facet.",
                               "importance": {"proposed": None, "operator_rating": None}})
    cell = next(c for c in doc["facet_map"]["coverage_matrix"]["cells"] if c["state"] == "gap")
    cell.pop("rationale")
    cell.update(state="covered", obligation_ids=["O-3"])


def cost_cell(doc: dict) -> dict:
    """The example's covered F-cost x cost cell, which O-2 alone covers."""
    return next(c for c in doc["facet_map"]["coverage_matrix"]["cells"] if (c["facet_id"], c["question_type"]) == ("F-cost", "cost"))


def removed(doc: dict) -> None:
    """The review's removal probe: O-2 removed, its cell marked deliberately out."""
    doc["obligations"].pop(1)
    cell = cost_cell(doc)
    cell.pop("obligation_ids")
    cell.update(state="deliberately_out", rationale="Cost is no longer in scope.")


def redefined_cost(doc: dict) -> None:
    """O-2's comparator and question changed, under its own id (protocol_changed as a shared obligation redefined)."""
    doc["obligations"][1]["slots"]["comparator"] = "No structured intake"
    doc["obligations"][1].update(text="Compare cost against no structured intake.", importance={"proposed": None, "operator_rating": None})


def reissued(doc: dict) -> None:
    """The review's replacement probe: O-2's redefinition issued as O-new, its cell naming O-new."""
    redefined_cost(doc)
    doc["obligations"][1]["obligation_id"] = "O-new"
    cost_cell(doc)["obligation_ids"] = ["O-new"]


# Each edit of the example contract, the class the governing design gives it
# (not the router's docstring), the class of its revert (the edited revision
# superseded by the example again: an addition's revert is a withdrawal, so the
# rule is not symmetric), and where the design says so. F = flow architecture,
# M = methodology synthesis, INV = docs/gen2/INVARIANTS.md, R = Astra's
# 1d-repair review (finding 1 and its ruling on coverage cells and removal).
FRAMING, PROTOCOL = "reframed", "protocol_changed"
DESIGN_ORACLE = (
    # The framing: G-6 / F §6.5 "a reframe versions the facet map"; M §2 step 1 the analytic framework is drawn from the
    # decision and "each link generates a key question"; M §5 "decision record + framing version + facet map ... what changed
    # at each reframe"; M §2 taxonomy: "replace the framing ... the decision question is not answerable as formulated".
    ("the decision record's objective reworded", FRAMING, FRAMING, "M §5, M §2 taxonomy (changed objective)",
     lambda d: d["decision_record"]["objective"].update(operator_words="Decide whether intake needs any audit at all.")),
    ("what the decision feeds", FRAMING, FRAMING, "M §5; F S1/S3 (the decision record is what every obligation traces to)",
     lambda d: d["decision_record"]["feeds"].update(description="Intake station design for the six-station fleet.")),
    ("a key question reworded, the framing version kept", FRAMING, FRAMING, "G-6, M §2 step 1 (a link's key question is the framing)",
     lambda d: d["facet_map"]["analytic_framework"]["links"][0].update(key_question=REFRAMED_QUESTION)),
    ("a framework node added", FRAMING, FRAMING, "G-6, M §2 step 1",
     lambda d: d["facet_map"]["analytic_framework"]["nodes"].append({"node_id": "N-cost", "label": "Operator cost", "kind": "decision_outcome"})),
    ("a facet redefined", FRAMING, FRAMING, "G-6 (the facet map), G-5 (a new facet always needs an amendment)",
     lambda d: d["facet_map"]["facets"][0].update(label="Effect of design on decision quality")),
    ("a facet added", FRAMING, FRAMING, "G-5, G-6",
     lambda d: d["facet_map"]["facets"].append({**copy.deepcopy(d["facet_map"]["facets"][1]), "facet_id": "F-latency", "label": "Latency"})),
    ("a coverage question type added", FRAMING, FRAMING, "G-6; M §2 step 4 (the facet x question-type matrix)",
     lambda d: d["facet_map"]["coverage_matrix"]["question_types"].append("mechanism")),
    ("what is deliberately out", FRAMING, FRAMING, "G-6; F S1 (scope)",
     lambda d: d["facet_map"]["deliberately_out"].clear()),
    ("the framing version alone", FRAMING, FRAMING, "G-6 (a declared reframe is a reframe)",
     lambda d: d["facet_map"].update(framing_version=2)),
    # The protocol: G-1 "hash-locked with its protocol revision ... the eligibility/stopping/applicability protocol" and "the
    # approved inventory"; G-7 "eligibility, estimand, required access tier, or stopping interpretation"; RG-6 "labels made under
    # the old protocol do not count under the new one".
    ("the protocol revision alone", PROTOCOL, PROTOCOL, "G-1", lambda d: d.update(protocol_revision=2)),
    ("an eligibility criterion", PROTOCOL, PROTOCOL, "G-1, G-7, RG-6", lambda d: d["eligibility_protocol"]["criteria"][1].update(description="Reports cost.")),
    ("the required access tier", PROTOCOL, PROTOCOL, "G-7", lambda d: d["eligibility_protocol"]["required_access_tier"].update(other="full_text")),
    ("a stopping profile", PROTOCOL, PROTOCOL, "G-1, G-7 (stopping interpretation)", lambda d: d["stopping_profiles"][0].update(profile_id="SP-other")),
    ("the applicability rules", PROTOCOL, PROTOCOL, "G-1", lambda d: d["applicability_rules"][0].update(target_context="Any intake.")),
    ("a shared obligation redefined", PROTOCOL, PROTOCOL, "G-1 (the approved inventory; a claim answers its obligation)",
     lambda d: d["obligations"][0].update(text="Compare cost only.")),
    ("a shared obligation's slots", PROTOCOL, PROTOCOL, "G-1", lambda d: d["obligations"][0]["slots"].update(comparator="No intake review")),
    # The approved inventory withdrawn from: G-1 "the lock covers the approved inventory"; M §2 step 4 "the obligation set is
    # approved with its matrix, so 'what we chose not to ask' is recorded with the same weight as what we asked"; G-5 authorizes
    # additions inside an existing facet, not removals; R finding 1 (removal, re-issue under a new id and scope-removing cells are
    # not compatible; a conservative revision-wide fence suffices). Each withdrawal alone, then the review's two probes.
    ("an obligation removed, the matrix untouched", PROTOCOL, "compatible", "G-1, R finding 1 (removal); its revert adds an obligation",
     lambda d: d["obligations"].pop(1)),
    ("a covered cell put deliberately out, its obligation kept", PROTOCOL, PROTOCOL, "M §2 step 4, R finding 1 (a scope-removing cell)",
     lambda d: (cost_cell(d).pop("obligation_ids"), cost_cell(d).update(state="deliberately_out", rationale="Cost is no longer in scope."))),
    ("a gap put deliberately out", PROTOCOL, PROTOCOL, "M §2 step 4 (an exclusion is a decision about what is asked), R finding 1",
     lambda d: next(c for c in d["facet_map"]["coverage_matrix"]["cells"] if c["state"] == "gap").update(state="deliberately_out")),
    ("a covered cell's obligation swapped for another, both kept", PROTOCOL, PROTOCOL, "M §2 step 4, R finding 1 (the cell loses O-2)",
     lambda d: cost_cell(d).update(obligation_ids=["O-1"])),
    ("a gap cell dropped from the matrix", PROTOCOL, "compatible", "M §2 step 4 (an empty cell is a visible decision); its revert lists a gap",
     lambda d: d["facet_map"]["coverage_matrix"]["cells"].pop(3)),
    ("a covered cell's entry otherwise changed, its obligations kept", PROTOCOL, PROTOCOL,
     "M §2 step 4; the rule is conservative (a cell is kept as it was or added to, nothing else)",
     lambda d: cost_cell(d).update(rationale="Costed with operator time.")),
    ("an obligation removed, its cell marked out", PROTOCOL, PROTOCOL, "G-1, M §2 step 4, R finding 1 (the review's removal probe)", removed),
    ("an obligation redefined under a new id", PROTOCOL, PROTOCOL, "G-1, R finding 1 (as protocol_changed as under its own id)", reissued),
    ("an obligation issued again unchanged under a new id", PROTOCOL, PROTOCOL, "G-1, R finding 1 (its id is how work answers it)",
     lambda d: (d["obligations"][1].update(obligation_id="O-new"), cost_cell(d).update(obligation_ids=["O-new"]))),
    # Neither, so compatible: what earlier results were produced against is untouched, or only added to.
    ("an obligation added in an existing facet, filling a gap cell", "compatible", PROTOCOL,
     "G-5 (a sub-question inside an existing facet, even auto-promoted); M §2 taxonomy ('fill a known gap': none needed); R ruling 2", gap_filled),
    ("an obligation added to a covered cell", "compatible", PROTOCOL, "G-5, R ruling 2 (additive coverage preserving existing questions)",
     lambda d: (d["obligations"].append({**copy.deepcopy(d["obligations"][1]), "obligation_id": "O-3", "text": "Compare operator cost alone.",
                                         "importance": {"proposed": None, "operator_rating": None}}), cost_cell(d)["obligation_ids"].append("O-3"))),
    ("a facet's importance", "compatible", "compatible", "G-2 (a rating is authority for later actions, given by its own decision); R ruling 2",
     lambda d: d["facet_map"]["facets"][1]["importance"]["operator_rating"].update(band="limited")),
    ("an obligation's importance", "compatible", "compatible", "G-2; R ruling 2",
     lambda d: d["obligations"][1]["importance"]["operator_rating"].update(band="limited")),
    ("the surveillance policy", "compatible", "compatible", "F S8 (when a completed topic reopens), design review §4", compatible),
    ("the method design's envelope", "compatible", "compatible", "F S5, G-7 (the envelope bounds self-serve adjustment, not results)",
     lambda d: d["method_design"]["operational_envelope"]["permitted_adjustments"].append("Add a citation-chaining lane")),
)


class CompatibilityRuleTest(RouterTestCase):
    """G-1, G-6, G-7: the rule, one section of the example contract at a
    time. The oracle is DESIGN_ORACLE: each edit's class from the governing
    design, and its revert's, with its citation, written independently of the
    router's docstring. Structural limit: these are the sections the design
    names; the rule is structural, so it does not judge whether an edit is
    harmless in meaning (a harmless reframe is still a reframe, a withdrawn
    obligation fences work that did not answer it)."""

    def test_each_section_is_classed_as_the_design_says(self) -> None:
        from gen2.router.amendments import contract_compatibility
        base = contract_doc(2, 1)
        for name, expected, reverted, basis, edit in DESIGN_ORACLE:
            with self.subTest(name, basis=basis):
                doc = copy.deepcopy(base)
                edit(doc)
                self.assertNotEqual(doc, base)
                self.assertEqual((contract_compatibility(base, doc), contract_compatibility(doc, base)), (expected, reverted))  # the edit, then its revert

    def test_a_cell_for_a_pair_not_listed_before_is_added_only_in_scope(self) -> None:
        """M §2 step 4, R finding 1: a pinned matrix without the F-cost x
        effect cell; a later revision listing it covered or as a gap only adds
        to the inventory, listing it deliberately out withdraws it — as does a
        deliberately-out or gap cell added beside a pair's kept one."""
        from gen2.router.amendments import contract_compatibility
        unlisted = contract_doc(2, 1, edit=lambda d: d["facet_map"]["coverage_matrix"]["cells"].pop(3))
        for name, expected, edit in (
                ("a gap", "compatible", lambda d: None),
                ("covered", "compatible", gap_filled),
                ("deliberately out", PROTOCOL, lambda d: d["facet_map"]["coverage_matrix"]["cells"][3].update(state="deliberately_out"))):
            with self.subTest(name):
                self.assertEqual(contract_compatibility(unlisted, contract_doc(3, 2, edit=edit)), expected)
        for state in ("deliberately_out", "gap"):
            with self.subTest(f"{state} beside a kept cell"):
                beside = contract_doc(3, 2, edit=lambda d: d["facet_map"]["coverage_matrix"]["cells"].append(
                    {"facet_id": "F-cost", "question_type": "cost", "state": state, "rationale": "Cost is no longer in scope."}))
                self.assertEqual(contract_compatibility(contract_doc(2, 1), beside), PROTOCOL)

    def test_a_brief_is_compatible_only_in_its_lineage(self) -> None:
        from gen2.router.amendments import brief_compatibility
        v1 = self.brief_document(TOPIC, 1)
        self.assertEqual(brief_compatibility(v1, self.brief_document(TOPIC, 2)), "lineage_only")
        self.assertEqual(brief_compatibility(v1, self.brief_document(TOPIC, 2, feeds="rebuild, or buy")), "content_changed")
