"""What a commit may record: claims and their production, screening,
decision receipts, exports, triggers, ordinals (task 1b).

Trace: INVARIANTS V-10 and Astra's 1a review (bind actual production and
adoption to authenticated, atomic commits and their receipts), C-7, C-12,
E-9, D-2, D-4, D-5, RG-1b(e), P-1, P-5, G-12; gen2/store/README.md "What
stays router logic" (A10: a screening receipt against its assessment and
protocol version); EXPORT-API.md §5 and §7 (manifest validation and
extension admission before outbox admission).

Oracles: hand-written expectations; raw SQL read-back; for refusals, every
table but the audit log unchanged.

Structural limits: no qualification or extension registry exists yet — the
fakes here admit exactly what a test lists, so these tests show the router
consults them and fails closed without them, not what 1d/Phase 3 will
admit; export bundles are fixture documents, not assembled from committed
state (Phase 3).
"""
from __future__ import annotations

import json
from pathlib import Path

from gen2.core import canonical
from gen2.tests.router_fixtures import TOPIC, Registry, RouterTestCase, empty_outcome, h, jcs

EXAMPLES = Path(__file__).resolve().parents[1] / "schema" / "examples"
T = "2026-09-27T10:00:00Z"


class EvidenceCase(RouterTestCase):
    def committed(self, grant: dict, op: str, outcome: dict, refs=()) -> dict:
        response = self.router.commit_outcome(self.envelope(grant, op, outcome, refs=refs))
        self.assertEqual(response["status"], "committed", response)
        return response["receipt"]

    def refused(self, grant: dict, op: str, outcome: dict, reason: str, refs=(), detail: str | None = None) -> None:
        """`detail` pins a generic reason to the rule that must have fired."""
        before = self.state()
        response = self.router.commit_outcome(self.envelope(grant, op, outcome, refs=refs))
        self.assertEqual((response["status"], response.get("reason")), ("rejected", reason), response)
        if detail is not None:
            self.assertIn(detail, response.get("detail", ""))
        self.assertEqual(self.state(), before)

    def claim_entry(self, cid: str, revision: int, text: dict, load_bearing: bool = False) -> dict:
        return {"claim_id": cid, "revision": revision, "text_ref": text, "load_bearing": load_bearing,
                "required_access_tier": "full_text" if load_bearing else None}


class ProductionAndAdoptionTest(EvidenceCase):
    """Astra 1a review, carried: production and adoption are bound to the
    commit that records them. The producer of a claim revision is the
    committing invocation, found through its capability; the commit's
    receipt and audit event name the revision; a scoping revision is adopted
    only by a new revision a contract-admitted commit produces."""

    def test_a_scoping_claim_is_adopted_by_a_revision_the_admitted_commit_produces(self) -> None:
        self.to_scoping()
        scoping = self.started("inv_scoping01")  # pre-contract research pass (S2)
        text = self.artifact(b"a scoping claim")
        response = self.finish(scoping, "op_scoping0001", {**empty_outcome("inv_scoping01"), "claims": [self.claim_entry("clm_00000001", 1, text)]}, refs=[text])
        self.assertEqual(response["status"], "committed", response)
        receipt = response["receipt"]
        self.assertEqual(self.rows("SELECT revision, producer_invocation_id, status FROM claims"), [(1, "inv_scoping01", "provisional")])
        audit = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", receipt["effects"]["audit_event_id"]))
        self.assertEqual((audit["claims"], receipt["invocation_id"]), ([["clm_00000001", 1]], "inv_scoping01"))

        # the topic reaches an approved contract; admitted work adopts the claim as revision 2
        chash = self.contract_draft(TOPIC, 1)
        self.x("UPDATE queue_entries SET status = 'awaiting_scope_approval', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        self.decide("opd_scope0001", "scope_approval", {"kind": "scoping_report", "ref": "s", "revision": 1, "hash": h("5")})
        self.decide("opd_cntr0001", "contract_approval", {"kind": "contract_revision", "revision": 1, "hash": chash})
        admitted = self.started("inv_research01")
        # the scoping revision itself cannot be promoted, even by admitted work (V-10, the store's second layer)
        self.refused(admitted, "op_promote0001", {**empty_outcome("inv_research01", "interim_transition"),
                                                  "claim_promotions": [{"claim_id": "clm_00000001", "revision": 1}]}, "payload_invalid", detail="V-10")
        # a revision number must be the next one: no gaps to launder lineage through
        self.refused(admitted, "op_adopt000001", {**empty_outcome("inv_research01", "interim_transition"),
                                                  "claims": [self.claim_entry("clm_00000001", 3, text)]}, "payload_invalid", detail="the next revision is 2")
        receipt = self.committed(admitted, "op_adopt000001", {**empty_outcome("inv_research01", "interim_transition"),
                                                              "claims": [self.claim_entry("clm_00000001", 2, text)],
                                                              "claim_promotions": [{"claim_id": "clm_00000001", "revision": 2}]})
        self.assertEqual(self.rows("SELECT revision, producer_invocation_id, status FROM claims ORDER BY revision"),
                         [(1, "inv_scoping01", "provisional"), (2, "inv_research01", "accepted_support")])
        audit = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", receipt["effects"]["audit_event_id"]))
        self.assertEqual((audit["claims"], audit["claim_promotions"]), ([["clm_00000001", 2]], [["clm_00000001", 2]]))
        self.assertEqual(self.value("SELECT invocation_id FROM operation_receipts WHERE operation_id = 'op_adopt000001'"), "inv_research01")

    def test_scoping_work_promotes_nothing(self) -> None:
        """C-12: a pre-contract commit carries no promotion at all (refused at
        the section, before the store's V-10 gate would refuse it)."""
        self.to_scoping()
        scoping = self.started("inv_scoping01")
        text = self.artifact(b"a scoping claim")
        outcome = {**empty_outcome("inv_scoping01", "interim_transition"), "claims": [self.claim_entry("clm_00000001", 1, text)],
                   "claim_promotions": [{"claim_id": "clm_00000001", "revision": 1}]}
        self.refused(scoping, "op_scoping0001", outcome, "kind_not_permitted", refs=[text], detail="scoping material only")

    def test_only_a_provisional_or_contested_revision_is_promoted(self) -> None:
        self.to_queued()
        grant = self.started("inv_research01")
        text = self.artifact(b"the claim")
        self.committed(grant, "op_capture0001", {**empty_outcome("inv_research01", "interim_transition"), "claims": [self.claim_entry("clm_00000001", 1, text)],
                                                 "claim_promotions": [{"claim_id": "clm_00000001", "revision": 1}]}, refs=[text])
        self.refused(grant, "op_promote0001", {**empty_outcome("inv_research01", "interim_transition"),
                                               "claim_promotions": [{"claim_id": "clm_00000001", "revision": 1}]}, "payload_invalid", detail="is accepted_support")

    def test_a_claims_text_is_staged_or_recorded(self) -> None:
        self.to_queued()
        grant = self.started("inv_research01")
        unstaged = {"content_hash": h("8"), "size_bytes": 10, "media_type": "text/plain"}
        self.refused(grant, "op_capture0001", {**empty_outcome("inv_research01", "interim_transition"),
                                               "claims": [self.claim_entry("clm_00000001", 1, unstaged)]}, "payload_missing")
        text = self.artifact(b"the claim")
        self.refused(grant, "op_capture0001", {**empty_outcome("inv_research01", "interim_transition"),
                                               "claims": [self.claim_entry("clm_00000001", 1, {**text, "media_type": "text/html"})]}, "payload_invalid", refs=[text], detail="disagrees with the artifact")


class ScreeningBase(EvidenceCase):
    SPEC = "dspec_screen0001"

    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.grant = self.started("inv_research01")
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        self.spec_hash = self.spec()
        self.raw = self.artifact(b'{"selected":"include"}', "application/json")

    def spec(self, *, protocol_version: int = 1, true_hash: bool = True) -> str:
        doc = {"spec_version": "decision-spec/1", "spec_id": self.SPEC, "decision_class": "screening", "provider": "jev", "primitive": "choice",
               "action_policy": {"policy_id": "P1", "version": 1}, "options": {"include": {"criteria": "eligible"}, "exclude": {"criteria": "not"}},
               "protocol": {"topic_id": TOPIC, "contract": {"revision": 1, "content_hash": h("a")}, "eligibility_protocol_version": protocol_version}}
        spec_hash = canonical.logical_hash(doc) if true_hash else h("6")
        self.x("INSERT INTO decision_specs (spec_hash, spec_id, decision_class, provider, primitive, policy_id, policy_version, protocol_topic_id, document, created_at) "
               "VALUES (?, ?, 'screening', 'jev', 'choice', 'P1', 1, ?, ?, ?)", spec_hash, self.SPEC, TOPIC, json.dumps(doc), T)
        return spec_hash

    def assessment(self, decision: str = "include", results=None, *, stage: str = "abstract", actor: str = "primary", receipt: str | None = None,
                   reason: str | None = None) -> dict:
        return {"assessment_id": "asm_000000000001", "work_id": "wrk_00000001", "stage": stage, "decision": decision,
                "reason_code": reason or ("C-1" if decision == "exclude" else None), "criterion_results": {"C-1": "met"} if results is None else results,
                "actor_kind": actor, "decision_receipt_id": receipt, "supersedes_assessment_id": None}

    def decision_receipt(self, op: str, option: str = "include", *, work: str = "wrk_00000001", authority: str = "qualified") -> dict:
        return {"receipt_version": "decision-receipt/1", "decision_receipt_id": "dec_000000000001", "invocation_id": "inv_research01", "topic_id": TOPIC,
                "decided_at": T, "hash_contract": {"canonicalization": "jcs-rfc8785/1"}, "spec": {"spec_id": self.SPEC, "spec_hash": self.spec_hash},
                "decision_class": "screening", "provider": "jev", "subject": {"kind": "work", "ref": work},
                "input_manifest": {"snapshot_digest": h("6"), "input_record_ids": [], "input_status": "complete"},
                "provider_response": {"status": "answered", "raw_response_digest": self.raw["content_hash"], "raw_response_artifact": self.raw,
                                      "answer": {"primitive": "choice", "selected_option_id": option, "distribution": {"include": 0.8, "exclude": 0.2}, "confidence": 0.7}},
                "policy": {"policy_id": "P1", "version": 1}, "authorization": {"authority_level": authority, "qualification_ref": "qual-1" if authority == "qualified" else None},
                "action": "commit_reversible_action" if authority == "qualified" else "attach_proposal",
                "outcome": {"commit_operation_id": op if authority == "qualified" else None, "proposal_ref": None if authority == "qualified" else "prop-1", "hold_id": None},
                "blind_sample": {"selected": False, "initial_disposition_ref": None}}

    def screen(self, *assessments: dict, receipts=()) -> dict:
        return {**empty_outcome("inv_research01", "interim_transition"), "screening_assessments": list(assessments), "decision_receipts": list(receipts)}


class ScreeningTest(ScreeningBase):
    """A10: an assessment's criteria are its pinned protocol's, each decided
    no earlier than its stage; an exclusion rests on a criterion not met."""

    def test_a_primary_assessment_under_the_pinned_protocol(self) -> None:
        self.committed(self.grant, "op_screen00001", self.screen(self.assessment()))
        self.assertEqual(self.rows("SELECT contract_revision, eligibility_protocol_version, framing_version, invocation_id, recorded_by_operation_id FROM screening_assessments"),
                         [(1, 1, 1, "inv_research01", "op_screen00001")])

    def test_criterion_results_are_the_protocols_and_consistent(self) -> None:
        cases = {
            "not in eligibility protocol version 1": self.assessment(results={"C-9": "met"}),
            "an exclusion needs a criterion not met": self.assessment("exclude", {"C-1": "unknown"}),  # missing information is unknown, not excluded
            "an inclusion cannot have criteria not met": self.assessment("include", {"C-1": "not_met"}),
            "cannot be met at the abstract stage": self.assessment("include", {"C-2": "met"}),  # a full-text criterion
        }
        for fragment, assessment in cases.items():
            with self.subTest(fragment):
                self.refused(self.grant, "op_screen00001", self.screen(assessment), "payload_invalid", detail=fragment)
        self.committed(self.grant, "op_screen00001", self.screen(self.assessment("exclude", {"C-1": "not_met", "C-2": "unknown"})))

    def test_pre_contract_work_records_no_screening(self) -> None:
        self.to_scoping(tid="fleet-a:t2")
        scoping = self.started("inv_scoping01", tid="fleet-a:t2")
        outcome = {**empty_outcome("inv_scoping01", "interim_transition", topic="fleet-a:t2"), "screening_assessments": [self.assessment()]}
        self.refused(scoping, "op_screen00001", outcome, "kind_not_permitted")


class ProviderScreeningTest(ScreeningBase):
    """A10 / D-2 / D-4: a provider-written assessment is exactly its qualified
    screening receipt's committed answer, about this work, under a spec (whose
    hash is true) for this protocol version; without a registry entry there
    is no qualified authority."""

    def setUp(self) -> None:
        super().setUp()
        self.qualify()

    def qualify(self) -> None:
        self.router = self.make_router(qualifications=Registry({("jev", "screening", self.spec_hash, "qual-1")}))

    def provider(self, op: str = "op_screen00001", **kwargs) -> dict:
        return self.screen(self.assessment(kwargs.pop("decision", "include"), actor="decision_provider", receipt="dec_000000000001"),
                           receipts=[self.decision_receipt(op, **kwargs)])

    def test_a_qualified_receipts_committed_answer(self) -> None:
        self.committed(self.grant, "op_screen00001", self.provider(), refs=[self.raw])
        self.assertEqual(self.rows("SELECT decision_receipt_id, commit_operation_id FROM decision_receipts"), [("dec_000000000001", "op_screen00001")])
        self.assertEqual(self.rows("SELECT actor_kind, decision_receipt_id FROM screening_assessments"), [("decision_provider", "dec_000000000001")])

    def test_the_assessment_must_be_the_receipts_answer(self) -> None:
        self.refused(self.grant, "op_screen00001", self.provider(option="exclude"), "payload_invalid", refs=[self.raw], detail="committed answer about this work")
        self.refused(self.grant, "op_screen00001", self.provider(work="wrk_00000002"), "payload_invalid", refs=[self.raw], detail="committed answer about this work")

    def test_no_registry_entry_means_no_qualified_authority(self) -> None:
        self.router = self.make_router()  # the default registry: nothing is qualified
        self.refused(self.grant, "op_screen00001", self.provider(), "payload_invalid", refs=[self.raw], detail="no qualification registry")

    def test_the_spec_must_hash_to_its_label_and_be_for_this_protocol(self) -> None:
        self.SPEC = "dspec_screen0002"  # specs are immutable: each probe is a spec of its own
        self.spec_hash = self.spec(protocol_version=2)
        self.qualify()
        self.refused(self.grant, "op_screen00001", self.provider(), "payload_invalid", refs=[self.raw], detail="not for eligibility protocol version 1")
        self.SPEC = "dspec_screen0003"
        self.spec_hash = self.spec(true_hash=False)
        self.qualify()
        self.refused(self.grant, "op_screen00001", self.provider(), "payload_invalid", refs=[self.raw], detail="does not hash to")

    def test_a_receipt_records_a_call_of_the_committing_invocation(self) -> None:
        other = self.started("inv_checkpt01", "checkpoint")
        receipt = {**self.decision_receipt("op_screen00001"), "invocation_id": "inv_checkpt01"}
        outcome = self.screen(self.assessment(actor="decision_provider", receipt="dec_000000000001"), receipts=[receipt])
        self.refused(self.grant, "op_screen00001", outcome, "capability_invocation_mismatch", refs=[self.raw], detail="inv_checkpt01")
        self.assertEqual(other["status"], "granted")

    def test_an_abstention_hold_is_one_this_commit_creates_or_one_recorded(self) -> None:
        receipt = self.decision_receipt("op_screen00001", authority="advisory")
        receipt.update(action="abstain_hold", outcome={"commit_operation_id": None, "proposal_ref": None, "hold_id": "hold_000000000001"})
        hold = {"hold_id": "hold_000000000001", "subject_ref": "work:wrk_00000001", "hold_class": "judgment", "cause": "low confidence",
                "recoverability": "needs_decision", "required_authority": "primary", "owner": "primary", "deadline_at": "2026-10-01T00:00:00Z",
                "clears_when": "the primary screens it", "capability_fact_id": None}
        outcome = self.screen(receipts=[receipt])
        self.refused(self.grant, "op_screen00001", outcome, "payload_invalid", refs=[self.raw], detail="neither created here nor recorded")
        self.committed(self.grant, "op_screen00001", {**outcome, "holds": [hold]}, refs=[self.raw])
        self.assertEqual(self.rows("SELECT action, hold_id FROM decision_receipts"), [("abstain_hold", "hold_000000000001")])

    def test_the_raw_response_must_be_staged(self) -> None:
        self.refused(self.grant, "op_screen00001", self.provider(), "payload_missing")

    def test_a_receipt_committed_by_another_operation_is_refused(self) -> None:
        self.refused(self.grant, "op_screen00001", self.provider(op="op_elsewhere01"), "payload_invalid", refs=[self.raw], detail="recorded by op_elsewhere01")


class ExportTest(EvidenceCase):
    """EXPORT-API.md §5, §7: every manifest is validated against
    export-manifest/2, its extension connectors admitted, and its bundle
    staged, canonical and schema-valid, before it enters the outbox."""

    EXTENSIONS = (("acme_graph_connector", "review-2026-10-01"),)

    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.grant = self.started("inv_checkpt01", "checkpoint")
        self.decide("opd_publish001", "publication_approval", {"kind": "publication_source", "ref": "dossier-1", "revision": 1, "hash": h("1")})
        bundle = json.loads((EXAMPLES / "export-bundle" / "valid-completed-topic.json").read_text())["instance"]
        self.bundle = {**bundle, "topic_id": TOPIC, "bundle_id": "exb_gen00000001"}
        self.bundle_ref = self.artifact(jcs(self.bundle), "application/json")

    def manifest(self, **overrides) -> dict:
        manifest = json.loads((EXAMPLES / "export-manifest" / "valid-completion-generation-1.json").read_text())["instance"]
        manifest.update(manifest_id="man_gen00000001", topic_id=TOPIC, source={"revision": 1, "content_hash": h("1")},
                        approval={"operator_decision_id": "opd_publish001", "approved_revision": 1},
                        bundle={"bundle_id": "exb_gen00000001", "bundle_version": "export-bundle/1", "content_hash": self.bundle_ref["content_hash"]})
        manifest.update(overrides)
        return manifest

    def exporting(self, manifest: dict) -> dict:
        return {**empty_outcome("inv_checkpt01", "interim_transition"), "exports": [manifest]}

    def test_an_approved_manifest_enters_the_outbox_with_its_hash(self) -> None:
        manifest = self.manifest()
        receipt = self.committed(self.grant, "op_export00001", self.exporting(manifest), refs=[self.bundle_ref])
        rows = self.rows("SELECT outbox_event_id, manifest_hash, committed_by_operation_id FROM outbox_events")
        self.assertEqual(rows, [(receipt["effects"]["outbox_event_ids"][0], canonical.logical_hash(manifest), "op_export00001")])

    def test_an_extension_is_admitted_only_by_the_registry(self) -> None:
        extension = {"connector_type": "extension", "implementation": {"module": "acme_graph_connector", "review_ref": "review-2026-10-01"}}
        unreviewed = {"connector_type": "extension", "implementation": {"module": "acme_graph_connector", "review_ref": "review-none"}}
        self.refused(self.grant, "op_export00001", self.exporting(self.manifest(expected_connectors={"graph": unreviewed})), "payload_invalid", refs=[self.bundle_ref], detail="is not admitted")
        no_impl = {"connector_type": "extension"}
        self.refused(self.grant, "op_export00001", self.exporting(self.manifest(expected_connectors={"graph": no_impl})), "payload_invalid", refs=[self.bundle_ref], detail="implementation")  # the schema's rule
        self.committed(self.grant, "op_export00001", self.exporting(self.manifest(expected_connectors={"graph": extension})), refs=[self.bundle_ref])

    def test_the_bundle_is_staged_canonical_and_valid(self) -> None:
        self.refused(self.grant, "op_export00001", self.exporting(self.manifest()), "payload_missing")  # not staged with this commit
        pretty = json.dumps(self.bundle, indent=1).encode()
        pretty_ref = self.artifact(pretty, "application/json")
        self.refused(self.grant, "op_export00001", self.exporting(self.manifest(bundle={"bundle_id": "exb_gen00000001", "bundle_version": "export-bundle/1",
                                                                                      "content_hash": pretty_ref["content_hash"]})),
                     "payload_invalid", refs=[pretty_ref], detail="canonical (JCS) form")
        broken = jcs({**self.bundle, "completion": None})
        broken_ref = self.artifact(broken, "application/json")
        self.refused(self.grant, "op_export00001", self.exporting(self.manifest(bundle={"bundle_id": "exb_gen00000001", "bundle_version": "export-bundle/1",
                                                                                      "content_hash": broken_ref["content_hash"]})),
                     "payload_invalid", refs=[broken_ref], detail="export-bundle.schema.json")

    def test_the_staged_bundle_is_the_one_the_manifest_names(self) -> None:
        other = jcs({**self.bundle, "bundle_id": "exb_other0001"})
        other_ref = self.artifact(other, "application/json")
        manifest = self.manifest(bundle={"bundle_id": "exb_gen00000001", "bundle_version": "export-bundle/1", "content_hash": other_ref["content_hash"]})
        self.refused(self.grant, "op_export00001", self.exporting(manifest), "payload_invalid", refs=[other_ref], detail="the staged bundle is exb_other0001")

    def test_unapproved_or_foreign_material_is_not_exported(self) -> None:
        self.refused(self.grant, "op_export00001", self.exporting(self.manifest(source={"revision": 2, "content_hash": h("2")},
                                                                               approval={"operator_decision_id": "opd_publish001", "approved_revision": 2})),
                     "payload_invalid", refs=[self.bundle_ref], detail="never exported")  # the approval is about revision 1 (the store's P-5 gate)
        self.refused(self.grant, "op_export00001", self.exporting(self.manifest(topic_id="fleet-a:t2")), "cross_topic", refs=[self.bundle_ref])

    def test_only_primary_class_work_commits_exports(self) -> None:
        verifier = self.started("inv_verify001", "verification")
        outcome = {**empty_outcome("inv_verify001", "interim_transition"), "exports": [self.manifest()]}
        self.refused(verifier, "op_export00001", outcome, "kind_not_permitted", refs=[self.bundle_ref])


class TriggerAndOrdinalTest(EvidenceCase):
    TRIGGER = {"reason_code": "persistent_contradiction", "cause_ref": "clm_a vs clm_b", "source_revision": 4, "observed_at": T}

    def ordinal(self, response: dict):
        self.assertEqual(response["status"], "committed", response)
        return response["receipt"]["effects"]["research_ordinal"]

    def test_a_replayed_trigger_opens_nothing_new(self) -> None:
        """RG-1b(e): once handled, the same trigger identity is never recorded
        or reopened again."""
        self.to_queued()
        grant = self.started("inv_research01")
        receipt = self.committed(grant, "op_trigger0001", {**empty_outcome("inv_research01", "interim_transition"), "review_triggers": [self.TRIGGER]})
        identity = receipt["effects"]["trigger_identities"][0]
        self.assertEqual(identity, canonical.logical_hash({"topic_id": TOPIC, "reason_code": "persistent_contradiction", "cause_ref": "clm_a vs clm_b", "source_revision": 4}))
        self.x("UPDATE review_triggers SET handled_at = ? WHERE trigger_identity = ?", T, identity)  # handled (episodes are later work)
        before = self.rows("SELECT * FROM review_triggers")
        again = self.committed(grant, "op_trigger0002", {**empty_outcome("inv_research01", "interim_transition"), "review_triggers": [self.TRIGGER]})
        self.assertEqual(again["effects"]["trigger_identities"], [])
        self.assertEqual(self.rows("SELECT * FROM review_triggers"), before)
        audit = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", again["effects"]["audit_event_id"]))
        self.assertEqual(audit["triggers_already_recorded"], [identity])
        new = self.committed(grant, "op_trigger0003", {**empty_outcome("inv_research01", "interim_transition"), "review_triggers": [{**self.TRIGGER, "source_revision": 5}]})
        self.assertEqual(len(new["effects"]["trigger_identities"]), 1)

    def test_only_contract_research_passes_earn_ordinals(self) -> None:
        """C-7 / C-12."""
        self.to_scoping()
        scoping = self.started("inv_scoping01")
        self.assertEqual(self.ordinal(self.finish(scoping, "op_scoping0001")), None)
        self.to_queued("fleet-a:t2")
        for kind in ("discovery", "verification", "checkpoint"):
            grant = self.started(f"inv_{kind[:8]}01", kind, tid="fleet-a:t2")
            self.assertEqual(self.ordinal(self.finish(grant, f"op_{kind[:8]}0001")), None, kind)
        first = self.started("inv_research01", tid="fleet-a:t2")
        self.assertEqual(self.ordinal(self.finish(first, "op_research0001")), 1)
        self.x("UPDATE queue_entries SET status = 'queued', state_revision = state_revision + 1 WHERE topic_id = 'fleet-a:t2' AND status = 'resting'")
        second = self.started("inv_research02", tid="fleet-a:t2")
        self.assertEqual(self.ordinal(self.finish(second, "op_research0002")), 2)
        self.assertEqual(self.rows("SELECT ordinal, invocation_id FROM research_ordinals ORDER BY ordinal"), [(1, "inv_research01"), (2, "inv_research02")])


class HoldTest(EvidenceCase):
    def test_a_capability_hold_cites_a_recorded_fact(self) -> None:
        self.to_queued()
        grant = self.started("inv_research01")
        hold = {"hold_id": "hold_000000000001", "subject_ref": "lane:crossref", "hold_class": "capability", "cause": "vault 403", "recoverability": "needs_remediation",
                "required_authority": "router", "owner": "router", "deadline_at": "2026-10-01T00:00:00Z", "clears_when": "secrets backend healthy",
                "capability_fact_id": "fact_vault0001"}
        self.refused(grant, "op_hold00000001", {**empty_outcome("inv_research01", "interim_transition"), "holds": [hold]}, "payload_invalid", detail="is not recorded")
        self.x("INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, recorded_at) VALUES ('fact_vault0001', 'secrets_backend', 'failing', 'vault 403', ?, '[]', ?)", T, T)
        receipt = self.committed(grant, "op_hold00000001", {**empty_outcome("inv_research01", "interim_transition"), "holds": [hold]})
        self.assertEqual(receipt["effects"]["holds_created"], ["hold_000000000001"])
        self.assertEqual(self.rows("SELECT owner, deadline_at, cleared_at, created_by_operation_id FROM holds"), [("router", "2026-10-01T00:00:00Z", None, "op_hold00000001")])
