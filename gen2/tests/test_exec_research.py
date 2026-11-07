"""gen2/exec research view and builder, and the research prompt. Oracles: outcome-document.schema.json for the whole
built outcome, judgment-research.schema.json for the prompt's example, hashlib for byte digests; the router's own
authority (cross-topic works, obligation existence, protocol criteria) is not restated. Limits: rows follow
topic_records' ticket-plan shape; the retained abstract shape is T12-G's fixture (gateway_response.records[]).
Judgments are hand-written; no model runs."""
import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.exec import common, orders, research, views
from gen2.router.schemas import SchemaSet
from gen2.tests import children
from gen2.tests.test_exec_scope import HASH, TOPIC, Exchanges, lineage, staged

SCHEMAS = SchemaSet()
ADMISSION = {"context": "contract/1", "contract": {"revision": 1, "content_hash": HASH}}
JUDGMENT = {**json.loads(Path(children.path("gen2/schema/examples/judgment-research/valid-example.json")).read_text())["instance"]}
JUDGMENT["claims"][0]["sources"][0]["contribution"] = "answer"
RAW = canonical.canonical_bytes({"gateway_response": {"records": [{"identity": "doi:10.1/a", "abstract": "An abstract."}]}})


RUBRICS = {"low": "One study, or studies that disagree.", "high": "Two or more independent studies agree."}


def contract(**doc):
    return {"revision": 1, "content_hash": HASH, "framing_version": 2,
            "document": {"eligibility_protocol": {"protocol_version": 3, "criteria": [{"criterion_id": "c-1"}]},
                         "confidence_scheme": {"scheme_id": "s", "version": 1, "labels": RUBRICS},
                         "decision_record": {"objective": {"operator_words": "Does sleep loss lower adolescent attention?"},
                                             "feeds": {"kind": "decision", "description": "School start times."},
                                             "evidence_that_would_change_it": [{"entry_id": "e1", "text": "A null multi-site trial."}]},
                         "facet_map": {"analytic_framework": {"links": [{"link_id": "l1", "key_question": "Does duration change attention?"}]},
                                       "facets": [{"facet_id": "f1", "label": "Sleep duration", "kind": "exposure", "importance": 5}]},
                         "obligations": [{"obligation_id": "ob-1", "template": {"claim_type": "effect"}, "text": "Estimate the effect of under 7 hours of sleep on sustained attention.",
                                          "slots": {"population": "adolescents 13-17"}, "facet_ids": ["f1"]}], **doc}}


def records(**over):
    base = {**lineage(), "contract_revisions": [contract()],
            "works": [{"work_id": "wrk_aaaaaaaa", "identity_scheme": "doi", "identity_value": "10.1/a"},
                      {"work_id": "wrk_bbbbbbbb", "identity_scheme": "doi", "identity_value": "10.1/b"}],
            "claims": [{"claim_id": "clm_prior0001", "revision": 1, "load_bearing": 0, "text_ref": "sha256:" + "d" * 64}]}
    return {**base, **over}


def exchanges(data=RAW):
    ref = {"content_hash": canonical.bytes_digest(data), "size_bytes": len(data), "media_type": "application/json"}
    return Exchanges({"call-1": (ref, data)})


def stage(data, media):
    return {"content_hash": canonical.bytes_digest(data), "size_bytes": len(data), "media_type": media}


class Reader:
    def __init__(self, recs):
        self.recs = recs

    def topic_records(self, request):
        return {"status": "ok", "topic_id": request["topic_id"], "records": {f: self.recs[f] for f in request["families"]}}


def work(recs=None, ex=None, truncation=None):
    view = views.research_view(ADMISSION, recs or records(), ex or exchanges(), lambda ref: "prior text", "2026-11-05T12:00:00Z", 7,
                               truncation if truncation is not None else [])
    return {"invocation_id": "inv_aaaaaaaa", "topic_id": TOPIC, "view": view}


def build(w=None, judgment=None, recs=None, ex=None, stager=stage):
    return research.build_research(w or work(), judgment or copy.deepcopy(JUDGMENT), Reader(recs or records()), ex or exchanges(), stager)


class ViewTest(unittest.TestCase):
    def test_only_retained_works_appear_with_their_retained_abstract(self):
        view = work()["view"]
        self.assertEqual(view["works"], [{"work_id": "wrk_aaaaaaaa", "identity": "doi:10.1/a", "abstract": "An abstract."}])
        self.assertEqual(view["claims"][0]["text"], "prior text")
        self.assertEqual((view["state_revision"], view["contract"]["framing_version"]), (7, 2))

    def test_the_view_carries_the_contracts_own_wording(self):
        contract_view = work()["view"]["contract"]
        self.assertEqual(contract_view["objective"], "Does sleep loss lower adolescent attention?")
        self.assertEqual(contract_view["feeds"], {"kind": "decision", "description": "School start times."})
        self.assertEqual(contract_view["key_questions"], [{"link_id": "l1", "key_question": "Does duration change attention?"}])
        self.assertEqual(contract_view["facets"], [{"facet_id": "f1", "label": "Sleep duration", "kind": "exposure"}])
        self.assertEqual(contract_view["confidence_scheme"], {"scheme_id": "s", "version": 1, "labels": RUBRICS})
        self.assertEqual(work()["view"]["obligations"], [{"obligation_id": "ob-1", "claim_type": "effect", "facet_ids": ["f1"],
                         "text": "Estimate the effect of under 7 hours of sleep on sustained attention.", "slots": {"population": "adolescents 13-17"}}])

    def test_changed_wording_changes_the_input_and_an_oversized_input_is_refused(self):
        document = contract()["document"]
        edited = copy.deepcopy(document)
        edited["obligations"][0]["text"] = "Estimate something else."
        edited["confidence_scheme"]["labels"]["high"] = "Three replications."
        other = work(records(contract_revisions=[{**contract(), "document": edited}]))["view"]
        self.assertEqual((other["obligations"][0]["text"], other["contract"]["confidence_scheme"]["labels"]["high"]), ("Estimate something else.", "Three replications."))
        self.assertNotEqual(other, work()["view"])
        entry = {"max_input_bytes": 500}
        document_ = {"view": work()["view"]}
        with tempfile.TemporaryDirectory() as root, self.assertRaises(common.Refused):
            orders.write_inputs(Path(root), entry=entry, prompt=b"", document=document_)

    def test_a_response_without_a_usable_abstract_gives_a_work_without_one(self):
        for case, data in (("missing", canonical.canonical_bytes({"gateway_response": {"records": [{"identity": "doi:10.1/a"}]}})),
                           ("blank", canonical.canonical_bytes({"gateway_response": {"records": [{"identity": "doi:10.1/a", "abstract": ""}]}})),
                           ("other record", canonical.canonical_bytes({"gateway_response": {"records": [{"identity": "doi:10.1/z", "abstract": "x"}]}})),
                           ("not json", b"\xff")):
            with self.subTest(case):
                self.assertEqual(work(ex=exchanges(data))["view"]["works"], [{"work_id": "wrk_aaaaaaaa", "identity": "doi:10.1/a"}])

    def test_a_long_abstract_is_cut_and_the_cut_is_recorded(self):
        data = canonical.canonical_bytes({"gateway_response": {"records": [{"identity": "doi:10.1/a", "abstract": "x" * 2000}]}})
        notes: list = []
        view = work(ex=exchanges(data), truncation=notes)["view"]
        self.assertEqual(len(view["works"][0]["abstract"]), views.ABSTRACT_CAP)
        self.assertEqual(notes, [{"family": "abstracts", "kept": 0, "total": 1}])

    def test_contract_must_be_exactly_the_pinned_row(self):
        for case, recs, admission in (("other hash", records(contract_revisions=[{**contract(), "content_hash": "sha256:" + "b" * 64}]), ADMISSION),
                                      ("duplicate", records(contract_revisions=[contract(), contract()]), ADMISSION),
                                      ("scoping admission", records(), {"context": "pre-contract/1"})):
            with self.subTest(case), self.assertRaises(common.Refused):
                views.research_view(admission, recs, exchanges(), lambda ref: None, "2026-11-05T12:00:00Z", 1, [])


class BuilderTest(unittest.TestCase):
    def test_outcome_is_schema_valid_and_every_binding_is_the_systems(self):
        outcome = build()
        self.assertEqual(SCHEMAS.errors({k: v for k, v in outcome.items() if k != "search_proposals"}, "outcome-document.schema.json"), [])
        digest = canonical.bytes_digest(RAW)
        self.assertEqual(outcome["source_artifacts"], [{"work_id": "wrk_aaaaaaaa", "source_version": digest,
                                                       "artifact_ref": {"content_hash": digest, "size_bytes": len(RAW), "media_type": "application/json"}}])
        (link,) = outcome["claim_source_links"]
        self.assertEqual((link["claim_id"], link["source_version"], link["evidence_origin_lineage"], link["analytical_method"]),
                         (outcome["claims"][0]["claim_id"], digest, "semanticscholar:doi:10.1/a", None))
        text = JUDGMENT["claims"][0]["text"].encode()
        self.assertEqual(outcome["claims"][0]["text_ref"]["content_hash"], "sha256:" + hashlib.sha256(text).hexdigest())
        self.assertEqual([p["proposer"] for p in outcome["search_proposals"]], ["research_pass.research"])
        self.assertEqual((outcome["next_queue_state"], outcome["review_triggers"]), ("resting", [
            {"reason_code": "persistent_contradiction", "cause_ref": "inv_aaaaaaaa", "source_revision": 7, "observed_at": "2026-11-05T12:00:00Z"}]))

    def test_obligation_assessment_pins_the_contract_and_maps_the_outcome(self):
        (record,) = build()["obligation_assessments"]
        self.assertEqual((record["contract_revision"], record["contract_content_hash"], record["framing_version"], record["eligibility_protocol_version"]),
                         (1, HASH, 2, 3))
        self.assertEqual((record["disposition"], record["confidence"], record["subject"]),
                         ("unresolved", {"basis": "recorded_assessment", "scheme": {"scheme_id": "s", "version": 1}, "label": "low"}, "ob-1: unknown"))
        self.assertEqual(record["evidence_refs"][0]["media_type"], "application/json")

    def test_table_of_obligation_outcomes_confidence_and_evidence(self):
        for outcome, label, cited, disposition, basis, evidence_type in (
                ("satisfied", "high", True, "supported", "recorded_assessment", "application/json"),
                ("not_satisfied", "low", True, "unresolved", "recorded_assessment", "application/json"),
                ("unknown", "certain", False, "unresolved", "unknown", "text/plain")):
            with self.subTest(outcome=outcome):
                judgment = copy.deepcopy(JUDGMENT)
                judgment["obligations"] = [{"obligation_id": "ob-1", "outcome": outcome, "confidence": label, "summary": "s"}]
                if not cited:
                    judgment["claims"][0]["sources"][0]["obligation_id"] = "ob-2"
                (record,) = build(judgment=judgment)["obligation_assessments"]
                self.assertEqual((record["disposition"], record["confidence"]["basis"], record["evidence_refs"][0]["media_type"]),
                                 (disposition, basis, evidence_type))

    def test_a_replay_builds_identical_bytes(self):
        self.assertEqual(common.outcome_bytes(build()), common.outcome_bytes(build()))

    def test_refusals_leave_nothing_invented(self):
        def judged(edit):
            judgment = copy.deepcopy(JUDGMENT)
            edit(judgment)
            return judgment
        cases = {"load-bearing claim without a tier": dict(judgment=judged(lambda j: j["claims"][0].update(required_access_tier=None))),
                 "off-enum contribution": dict(judgment=judged(lambda j: j["claims"][0]["sources"][0].update(contribution="primary estimate"))),
                 "work never retrieved": dict(judgment=judged(lambda j: j["claims"][0]["sources"][0].update(work_id="wrk_bbbbbbbb"))),
                 "no staged response": dict(ex=Exchanges({})),
                 "staged bytes differ from their reference": dict(ex=Exchanges({"call-1": staged(lie=True)})),
                 "spool returns another text's reference": dict(stager=lambda data, media: {**stage(data, media), "content_hash": HASH}),
                 "more links than one commit carries": dict(judgment=judged(lambda j: j["claims"][0].update(sources=j["claims"][0]["sources"] * 257)))}
        for name, kwargs in cases.items():
            with self.subTest(name), self.assertRaises(common.Refused):
                build(w=work(), **kwargs)


class PromptTest(unittest.TestCase):
    def test_example_is_a_valid_judgment_in_the_contribution_enum(self):
        text = Path(children.path("gen2/prompts/research_pass.research.md")).read_text()
        example = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
        self.assertEqual(SCHEMAS.errors(example, "judgment-research.schema.json"), [])
        self.assertLessEqual({s["contribution"] for c in example["claims"] for s in c["sources"]}, set(research.CONTRIBUTIONS))
        for word in research.CONTRIBUTIONS:
            self.assertIn(f"`{word}`", text)
