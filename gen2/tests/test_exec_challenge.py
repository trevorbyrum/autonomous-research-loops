"""Challenge view and builder (T16 PR1). Oracles: outcome-document, completion-record and judgment-challenge schemas
(SchemaSet); the real router's admission of the built outcome (the last class); hashlib for byte digests.
Limits: rows are hand-built to topic_records' shape in the unit classes; the wiring to the discovery job's real
observations is T13/T17's, so a search is matched to its proposal by lane and query only.
"""
import copy
import json
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.exec import challenge, common
from gen2.router.schemas import SchemaSet
from gen2.tests import children
from gen2.tests import router_fixtures as rf
from gen2.tests.completion_fixtures import completion_world

TOPIC = "fleet:topic"
SCHEMAS = SchemaSet()
ADMISSION = {"context": "contract/1", "contract": {"revision": 1, "content_hash": "sha256:" + "a" * 64}}
ME = "inv_challenger"


def claim(n, revision=1, **over):
    return {"claim_id": f"clm_{n:08d}", "revision": revision, "load_bearing": 1, "status": "provisional", "required_access_tier": "abstract",
            "producer_invocation_id": "inv_producer1", "text_ref": f"sha256:{n:064x}", **over}


def observation(n, state="searched_ok", **over):
    return {"observation_id": f"obs_{n:08d}", "lane": "semanticscholar", "coverage_state": state, "completeness": "complete", "result_count": 2,
            "error_class": None, "gateway_call_ref": f"call-{n}", "request": {"request": {"request_type": "find", "query": f"q{n}"}}, **over}


def proposal(n, claim_n=1, **over):
    return {"proposal_version": "search-proposal/1", "proposal_id": f"p{n}", "proposer": "x", "lane": "semanticscholar", "request_type": "find",
            "query": f"q{n}", "page_cap": 1, "obligation_ids": [], "rationale": "tests the claim",
            "subject_ref": {"claim_ref": f"clm_{claim_n:08d}"}, **over}


def records(**over):
    base = {"claims": [claim(1)], "verification_receipts": [], "registry_dispositions": [], "search_observations": []}
    return {**base, **over}


def view(recs=None, proposals=(), **over):
    args = dict(invocation_id=ME, review_episodes=["rev_aaaaaaaa"], proposals=list(proposals), as_of="2026-11-07T10:00:00Z", truncation=[])
    return challenge.challenge_view(ADMISSION, recs or records(), lambda ref: "text " + ref[-4:], **{**args, **over})


class Exchanges:
    """Stages a response for every call except those listed as missing."""
    def __init__(self, missing=()):
        self.missing = set(missing)

    def response(self, call):
        if call in self.missing:
            return None
        data = call.encode()
        return {"content_hash": canonical.bytes_digest(data), "size_bytes": len(data), "media_type": "application/json"}, data


def stage(data, media):
    return {"content_hash": canonical.bytes_digest(data), "size_bytes": len(data), "media_type": media}


def judgment(**over):
    return {"judgment_version": "judgment-challenge/1", "counterevidence": [], "explanations": [], "adjudications": [], "promotions": [],
            "search_proposals": [], **over}


def work(v, **over):
    return {"invocation_id": ME, "topic_id": TOPIC, "admission": ADMISSION, "view": v, **over}


def build(v, j, exchanges=None):
    out = challenge.make_builder(exchanges or Exchanges(), stage)(work(v), j)
    assert SCHEMAS.errors(out, "outcome-document.schema.json") == [], SCHEMAS.errors(out, "outcome-document.schema.json")
    return out


class ViewTest(unittest.TestCase):
    def test_claims_are_the_latest_load_bearing_revisions_of_other_producers(self):
        recs = records(claims=[claim(1), claim(1, 2), claim(2, load_bearing=0), claim(3, status="rejected"), claim(4, producer_invocation_id=ME)])
        self.assertEqual([(c["claim_ref"], c["revision"]) for c in view(recs)["claims"]], [("clm_00000001", 2)])

    def test_adverse_receipts_and_open_contradictions_only(self):
        receipts = [{"verification_receipt_id": f"ver_{n:08d}", "claim_id": "clm_00000001", "claim_revision": rev, "verdict": verdict}
                    for n, rev, verdict in ((1, 1, "does_not_support"), (2, 1, "supports"), (3, 1, "partially_supports"), (4, 2, "does_not_support"))]
        rows = [{"disposition_id": f"rdp_{n}", "registry_kind": kind, "subject": "s", "disposition": disposition, "supersedes_id": sup}
                for n, kind, disposition, sup in ((0, "contradiction", "open", None), (1, "contradiction", "resolved", None),
                                                  (2, "branch", "open", None), (3, "contradiction", "open", None), (4, "contradiction", "open", "rdp_3"))]
        got = view(records(verification_receipts=receipts, registry_dispositions=rows))
        self.assertEqual([r["receipt_id"] for r in got["adverse_receipts"]], ["ver_00000001", "ver_00000003"])
        self.assertEqual([d["disposition_id"] for d in got["contradictions"]], ["rdp_0", "rdp_4"])

    def test_pass_two_attaches_each_proposals_own_observations(self):
        recs = records(search_observations=[observation(1), observation(2, "provider_unavailable", error_class="timeout")])
        got = view(recs, [proposal(1), proposal(2)])
        self.assertEqual(got["pass"], 2)
        self.assertEqual([(s["proposal_id"], [o["observation_id"] for o in s["observations"]]) for s in got["searches"]],
                         [("p1", ["obs_00000001"]), ("p2", ["obs_00000002"])])
        self.assertEqual(view()["pass"], 1)

    def test_refusals(self):
        for case, call in (("other admission", lambda: challenge.challenge_view({"context": "pre-contract/1"}, records(), str, invocation_id=ME,
                                                                                 review_episodes=[], proposals=[], as_of="x", truncation=[])),
                           ("proposal for a claim not in the view", lambda: view(proposals=[proposal(1, claim_n=9)])),
                           ("proposal with no subject", lambda: view(proposals=[{k: v for k, v in proposal(1).items() if k != "subject_ref"}]))):
            with self.subTest(case), self.assertRaises(common.Refused):
                call()

    def test_claim_list_is_capped_and_the_cut_is_recorded(self):
        cut = []
        got = view(records(claims=[claim(n) for n in range(1, 206)]), truncation=cut)
        self.assertEqual((len(got["claims"]), cut), (200, [{"family": "claims", "kept": 200, "total": 205}]))


class PassOneTest(unittest.TestCase):
    def test_proposals_alone_are_committed_with_the_challengers_attribution(self):
        out = build(view(), judgment(search_proposals=[proposal(1)]))
        self.assertEqual([p["proposer"] for p in out["search_proposals"]], [challenge.PROPOSER])
        self.assertTrue(all(not out.get(k) for k in ("completion_records", "claim_promotions", "review_closures")))

    def test_a_proposal_must_name_a_claim_of_the_view(self):
        for bad in (proposal(1, claim_n=9), {k: v for k, v in proposal(1).items() if k != "subject_ref"}):
            with self.assertRaises(common.Refused):
                build(view(), judgment(search_proposals=[bad]))

    def test_the_builder_is_deterministic(self):
        j = judgment(search_proposals=[proposal(1)])
        self.assertEqual(canonical.canonical_bytes(build(view(), j)), canonical.canonical_bytes(build(view(), j)))


class PassTwoTest(unittest.TestCase):
    def setUp(self):
        self.recs = records(search_observations=[observation(1)])
        self.view = view(self.recs, [proposal(1)])

    def counter(self, outcome, searched=("p1",), v=None, exchanges=None):
        j = judgment(counterevidence=[{"claim_ref": "clm_00000001", "outcome": outcome, "summary": "s", "searched": list(searched)}])
        return build(v or self.view, j, exchanges)["completion_records"]

    def test_counterevidence_outcome_follows_the_recorded_searches(self):
        degraded = view(records(search_observations=[observation(1, "provider_unavailable", error_class="timeout")]), [proposal(1)])
        partial = view(records(search_observations=[observation(1, completeness="partial")]), [proposal(1)])
        empty = view(records(search_observations=[observation(1, "searched_empty", result_count=0)]), [proposal(1)])
        for case, outcome, searched, v, exchanges, expected in (
                ("clean search, nothing contradicts", "resolved", ("p1",), None, None, "none_found"),
                ("clean empty search is still a search", "resolved", ("p1",), empty, None, "none_found"),
                ("degraded search never reads as none_found", "resolved", ("p1",), degraded, None, "incomplete"),
                ("partial pagination never reads as none_found", "resolved", ("p1",), partial, None, "incomplete"),
                ("no staged response for the search", "resolved", ("p1",), None, Exchanges(["call-1"]), None),
                ("no search cited", "resolved", (), None, None, "incomplete"),
                ("counterevidence the model reports stands", "unresolved", ("p1",), degraded, None, "counterevidence_found"),
                ("the model cannot tell", "unknown", ("p1",), None, None, "incomplete")):
            with self.subTest(case):
                records_ = self.counter(outcome, searched, v, exchanges)
                self.assertEqual([r["assessment"]["outcome"] for r in records_], [expected] if expected else [])

    def test_evidence_is_the_searchs_own_retained_response(self):
        record = self.counter("resolved")[0]
        self.assertEqual(record["evidence_refs"], [Exchanges().response("call-1")[0]])
        self.assertEqual((record["kind"], record["subject_ref"], record["subject_revision"], record["contract_revision"]),
                         ("counterevidence_search", "clm_00000001", 1, 1))
        self.assertEqual(SCHEMAS.errors(record, "completion-record.schema.json"), [])

    def test_a_search_of_another_claim_cannot_be_cited(self):
        both = view(records(claims=[claim(1), claim(2)], search_observations=[observation(1), observation(2)]), [proposal(1), proposal(2, claim_n=2)])
        with self.assertRaises(common.Refused):
            self.counter("resolved", ("p2",), both)

    def test_explanations_adjudications_promotions_and_closures(self):
        recs = records(registry_dispositions=[{"disposition_id": "rdp_0", "registry_kind": "contradiction", "subject": "s", "disposition": "open",
                                               "supersedes_id": None}],
                       verification_receipts=[{"verification_receipt_id": f"ver_{n:08d}", "claim_id": "clm_00000001", "claim_revision": 1,
                                               "verdict": "does_not_support"} for n in (1, 2, 3)])
        j = judgment(explanations=[{"disposition_id": "rdp_0", "outcome": "unresolved", "summary": "s"}],
                     adjudications=[{"receipt_id": "ver_00000001", "outcome": "resolved", "summary": "s"},
                                    {"receipt_id": "ver_00000002", "outcome": "unresolved", "summary": "s"},
                                    {"receipt_id": "ver_00000003", "outcome": "unknown", "summary": "s"}], promotions=["clm_00000001"])
        out = build(view(recs), j)
        self.assertEqual([(r["kind"], r["subject_ref"], r["assessment"]["outcome"]) for r in out["completion_records"]],
                         [("competing_explanation", "rdp_0", "explanation_stands"), ("verification_adjudication", "ver_00000001", "verdict_upheld"),
                          ("verification_adjudication", "ver_00000002", "verdict_overturned")])
        self.assertEqual(out["claim_promotions"], [{"claim_id": "clm_00000001", "revision": 1}])
        self.assertEqual(out["review_closures"], [{"episode_id": "rev_aaaaaaaa"}])
        self.assertEqual(len({r["record_id"] for r in out["completion_records"]}), 3)

    def test_references_outside_the_view_are_refused(self):
        for case, over in (("claim", {"promotions": ["clm_00000009"]}),
                           ("contradiction", {"explanations": [{"disposition_id": "rdp_9", "outcome": "unknown", "summary": "s"}]}),
                           ("receipt", {"adjudications": [{"receipt_id": "ver_00000009", "outcome": "resolved", "summary": "s"}]}),
                           ("claim counterevidence", {"counterevidence": [{"claim_ref": "clm_00000009", "outcome": "unknown", "summary": "s", "searched": []}]}),
                           ("a second search round", {"search_proposals": [proposal(2)]})):
            with self.subTest(case), self.assertRaises(common.Refused):
                build(self.view, judgment(**over))

    def test_a_staged_response_that_does_not_hash_to_its_reference_is_refused(self):
        class Lying(Exchanges):
            def response(self, call):
                ref, data = super().response(call)
                return ref, data + b"x"
        with self.assertRaises(common.Refused):
            self.counter("resolved", exchanges=Lying())

    def test_the_example_judgment_and_prompt_agree_with_the_schema(self):
        example = json.loads(Path(children.path("gen2/schema/examples/judgment-challenge/valid-example.json")).read_text())["instance"]
        self.assertEqual(SCHEMAS.errors(example, "judgment-challenge.schema.json"), [])
        prompt = Path(children.path("gen2/prompts/checkpoint.challenge.md")).read_text()
        block = prompt.split("```json\n")[1].split("\n```")[0]
        self.assertEqual(SCHEMAS.errors(json.loads(block), "judgment-challenge.schema.json"), [])


class RouterAdmitsTest(rf.ContractWorld):
    """The oracle the builder cannot grade itself on: the real router commits (and refuses) what it builds."""

    def setUp(self):
        super().setUp()
        self.f = completion_world(self)

    def stage_ref(self, data, media):
        self.staged.append(self.artifact(data, media))
        return self.staged[-1]

    def built(self, outcome_judgment):
        self.staged = []
        records_ = self.router.topic_records({"topic_id": rf.TOPIC, "families": list(challenge.FAMILIES)})["records"]
        grant = self.started(self.ids("inv_"), "checkpoint")
        v = challenge.challenge_view(ADMISSION, records_, lambda ref: "text", invocation_id=grant["invocation_id"], review_episodes=[],
                                     proposals=[], as_of=rf.STAMP, truncation=[])
        ref = self.f.ref
        exchanges = type("E", (), {"response": staticmethod(lambda call: (ref, b"independent review and challenge evidence"))})()
        w = {"invocation_id": grant["invocation_id"], "topic_id": rf.TOPIC, "admission": {"context": "contract/1", "contract": {"revision": self.f.pin}}, "view": v}
        return grant, v, challenge.make_builder(exchanges, self.stage_ref)(w, outcome_judgment)

    def test_a_challenge_built_from_the_real_records_commits(self):
        records_ = self.router.topic_records({"topic_id": rf.TOPIC, "families": list(challenge.FAMILIES)})["records"]
        claim_id = records_["claims"][-1]["claim_id"]
        grant, v, outcome = self.built(judgment(
            counterevidence=[{"claim_ref": claim_id, "outcome": "unknown", "summary": "no search", "searched": []}],
            explanations=[{"disposition_id": "rdp_history00", "outcome": "resolved", "summary": "rejected"}],
            adjudications=[{"receipt_id": "ver_adverse001", "outcome": "resolved", "summary": "upheld"}]))
        self.assertEqual([r["kind"] for r in outcome["completion_records"]], ["competing_explanation", "verification_adjudication"])
        response = self.finish(grant, self.ids("op_"), outcome, refs=self.staged)
        self.assertEqual(response["status"], "committed", response)

    def test_the_router_refuses_what_the_builder_will_not_write(self):
        with self.assertRaises(common.Refused):
            self.built(judgment(promotions=[self.router.topic_records({"topic_id": rf.TOPIC, "families": ["claims"]})["records"]["claims"][-1]["claim_id"]]))
