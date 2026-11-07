"""The offline fixtures themselves (T18, O18.1/O18.2): the canned gateway behind the real GatewayClient, and the canned
judgment writers. Oracles: the real client's observations, the judgment schemas (SchemaSet), and `exec.job.run`'s file
contract. Views are hand-shaped like the T14/T16 views they stand for; the end-to-end run that feeds the agent real views
waits for T15 and T17. Limits: nothing here shows research quality; the fixtures only have to be valid and responsive."""
import json
import tempfile
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.exec import common, job, orders
from gen2.gateway_client.client import GatewayClient
from gen2.router.schemas import SchemaSet
from gen2.tests import offline_agent, offline_gateway, offline_world

SCHEMAS = SchemaSet()
INV, BASE = "inv_offline001", "http://gateway.invalid:8765"
HASH = "sha256:" + "a" * 64


def search(gateway, query, lane, attempt=1):
    client = GatewayClient(BASE, "engine-token", transport=gateway, clock=lambda: "2026-11-07T12:00:00Z", sleep=lambda s: None)
    token = client.grant(topic_id="fleet:topic", commercial=False, accept_per_item=True, invocation_id=INV)["token"]
    request = {"request_type": "find", "query": query, "lanes": [lane]}
    return client.search(request, invocation_id=INV, attempt=attempt, policy_version="gw/1", token=token)


def seen(out):
    (o,) = [x["observation"] for x in out["observations"]]
    return o["coverage_state"], o["completeness"], o["result_count"], o["error_class"]


class GatewayTest(unittest.TestCase):
    def test_modes_answer_through_the_real_client(self):
        cases = [("empty", "adolescent sleep attention", "semanticscholar", ("searched_ok", "complete", 2, None)),
                 ("empty", "adolescent sleep attention", "crossref", ("searched_ok", "complete", 2, None)),
                 ("empty", "counterevidence to a claim", "semanticscholar", ("searched_empty", "complete", 0, None)),
                 ("found", "counterevidence to a claim", "semanticscholar", ("searched_ok", "complete", 1, None)),
                 ("degraded", "counterevidence to a claim", "semanticscholar", ("unknown", "unobserved", None, "timeout")),
                 ("degraded", "adolescent sleep attention", "semanticscholar", ("searched_ok", "complete", 2, None))]
        for counter, query, lane, expected in cases:
            with self.subTest(counter=counter, lane=lane, query=query[:12]):
                self.assertEqual(seen(search(offline_gateway.OfflineGateway(counter=counter), query, lane)), expected)

    def test_only_the_content_lane_carries_an_abstract(self):
        def records(gateway, lane):
            sent = {"request_type": "find", "query": "q", "lanes": [lane]}
            headers = {"X-Research-Invocation": INV, "X-Research-Attempt": "1"}
            _, _, body, _ = gateway("POST", f"{BASE}/v1/find", headers, canonical.canonical_bytes(sent), 1)
            return canonical.parse_json_strict(body)["records"]
        gateway = offline_gateway.OfflineGateway()
        self.assertTrue(all(r["abstract"] for r in records(gateway, "semanticscholar")))
        self.assertTrue(all("abstract" not in r for r in records(gateway, "crossref")))
        self.assertTrue(all("abstract" not in r for r in records(offline_gateway.OfflineGateway(abstracts=False), "semanticscholar")))

    def test_the_call_numbers_are_distinct_and_unknown_modes_are_refused(self):
        gateway = offline_gateway.OfflineGateway()
        first, second = search(gateway, "q", "semanticscholar"), search(gateway, "q2", "crossref")
        self.assertNotEqual(first["pages"][0]["call_ref"], second["pages"][0]["call_ref"])
        with self.assertRaises(ValueError):
            offline_gateway.OfflineGateway(counter="slow")


CONTRACT = {"revision": 1, "content_hash": HASH, "framing_version": 1,
            "eligibility_protocol": {"protocol_version": 1, "criteria": [{"criterion_id": "c-1"}, {"criterion_id": "c-2"}]},
            "confidence_scheme": {"scheme_id": "s", "version": 1, "labels": {"low": "r1", "high": "r2"}}}
WORKS = [{"work_id": "wrk_aaaaaaaa", "identity": "doi:10.1/offline-a", "abstract": "An abstract."}, {"work_id": "wrk_bbbbbbbb", "identity": "doi:10.1/offline-b"}]


def observation(coverage="searched_empty", count=0, completeness="complete", error=None):
    return {"observation_id": "obs_00000001", "coverage_state": coverage, "completeness": completeness, "result_count": count,
            "error_class": error, "gateway_call_ref": "gw-call:1"}


def challenge_view(passes, observations=None):
    claims = [{"claim_ref": "clm_aaaaaaaa", "revision": 1, "tier": "abstract", "status": "provisional", "text": "A claim."}]
    searches = [] if passes == 1 else [{"proposal_id": "p1", "claim_ref": "clm_aaaaaaaa", "lane": "semanticscholar", "query": "q",
                                        "observations": [observation()] if observations is None else observations}]
    return {"pass": passes, "claims": claims, "searches": searches}


def work(kind, purpose, view):
    return {"kind": kind, "purpose": purpose, "view": view}


class AgentTest(unittest.TestCase):
    def valid(self, schema, judgment):
        self.assertEqual(SCHEMAS.errors(judgment, f"{schema}.schema.json"), [])

    def test_scope_proposes_searches_first_then_describes_the_territory(self):
        first = offline_agent.scope(work("research_pass", "scope", {"observations": []}))
        later = offline_agent.scope(work("research_pass", "scope", {"observations": [observation()]}))
        self.valid("judgment-scope", first)
        self.valid("judgment-scope", later)
        self.assertEqual(([p["lane"] for p in first["search_proposals"]], later["search_proposals"]), (["semanticscholar", "crossref"], []))

    def test_research_cites_only_a_work_with_a_retained_abstract_and_uses_the_contracts_words(self):
        view = {"contract": CONTRACT, "obligations": [{"obligation_id": "ob-1"}], "works": WORKS}
        judgment = offline_agent.research(work("research_pass", "research", view))
        self.valid("judgment-research", judgment)
        (claim,) = judgment["claims"]
        self.assertEqual([s["work_id"] for s in claim["sources"]], ["wrk_aaaaaaaa"])
        self.assertIn("An abstract.", claim["text"])
        self.assertEqual(judgment["obligations"][0]["confidence"], "high")
        self.assertEqual(set(judgment["screening"][0]["criteria"]), {"c-1", "c-2"})
        nothing = offline_agent.research(work("research_pass", "research", {**view, "works": WORKS[1:]}))
        self.assertEqual(nothing["claims"], [])

    def test_challenge_pass_one_proposes_a_search_for_each_claim(self):
        judgment = offline_agent.challenge(work("checkpoint", "challenge", challenge_view(1)))
        self.valid("judgment-challenge", judgment)
        self.assertEqual([(p["subject_ref"], p["lane"]) for p in judgment["search_proposals"]], [({"claim_ref": "clm_aaaaaaaa"}, "semanticscholar")])
        self.assertEqual((judgment["counterevidence"], judgment["promotions"]), ([], []))

    def test_challenge_pass_two_records_only_what_the_searches_recorded(self):
        table = [("read, found nothing", [observation()], "resolved", ["clm_aaaaaaaa"]),
                 ("read, found a contrary work", [observation("searched_ok", 1)], "unresolved", []),
                 ("no answer", [observation("unknown", None, "unobserved", "timeout")], "unknown", []),
                 ("partial, nothing read", [observation("searched_ok", 0, "partial", "partial_pagination")], "unknown", []),
                 ("no observation recorded", [], "unknown", [])]
        for name, observations, outcome, promoted in table:
            with self.subTest(name):
                judgment = offline_agent.challenge(work("checkpoint", "challenge", challenge_view(2, observations)))
                self.valid("judgment-challenge", judgment)
                self.assertEqual(([c["outcome"] for c in judgment["counterevidence"]], judgment["promotions"]), ([outcome], promoted))
                self.assertEqual(judgment["counterevidence"][0]["searched"], ["p1"])

    def test_review_and_the_file_contract_through_the_job(self):
        self.valid("judgment-review", offline_agent.review(work("checkpoint", "review", {})))
        agent = offline_agent.OfflineAgent()
        with tempfile.TemporaryDirectory() as root:
            entry = {"max_input_bytes": 100_000, "max_output_bytes": 100_000}
            document = orders.work_input(kind="checkpoint", purpose="review", invocation_id=INV, topic_id="fleet:topic",
                                         admission={"context": "contract/1", "contract": {"revision": 1, "content_hash": HASH}}, entry=entry, view={}, truncation=[])
            digest = orders.write_inputs(Path(root), entry=entry, prompt=b"prompt", document=document)
            path = job.run("review", Path(root), input_digest=digest, agent=agent, builder=lambda w, j: common.scaffold(w["invocation_id"], w["topic_id"], search_proposals=[j]),
                           validate=lambda purpose, judgment: self.valid("judgment-review", judgment))
            self.assertEqual(canonical.parse_json_strict(path.read_bytes())["search_proposals"][0]["outcome"], "sufficient")
            self.assertEqual(agent.calls, [("checkpoint", "review")])

    def test_a_purpose_without_a_responder_exits_nonzero_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            raw = canonical.canonical_bytes({"kind": "discovery", "purpose": "search", "view": {}})
            self.assertEqual(offline_agent.OfflineAgent()(b"", raw, Path(root)), 2)
            self.assertEqual(list(Path(root).iterdir()), [])


class VerifyResponderTest(unittest.TestCase):
    CLAIM = {"claim_ref": "clm_aaaaaaaa", "revision": 1, "tier": "abstract", "text": "A claim.", "producer": "inv_producer01"}

    def source(self, content, tier="abstract"):
        return {"work_id": "wrk_aaaaaaaa", "source_version": HASH, "identity": "doi:10.1/a", "content_tier": tier, "content": content}

    def judge(self, claim):
        judgment = offline_agent.verify(work("verification", "verify", {"claims": [claim]}))
        self.assertEqual(SCHEMAS.errors(judgment, "judgment-verify.schema.json"), [])
        return judgment["items"][0]

    def test_a_plain_quote_from_the_retained_text_supports_the_claim(self):
        text = offline_gateway.WORKS["doi:10.1/offline-a"][1]
        item = self.judge({**self.CLAIM, "sources": [self.source(text)]})
        (cited,) = item["cited_spans"]
        self.assertEqual(item["verdict"], "supports")
        self.assertTrue(text.startswith(cited["quote"]) and 0 < len(cited["quote"]) <= 60)

    def test_a_quote_is_only_what_json_writes_unchanged_and_ends_at_a_word(self):
        quote = offline_agent.plain_quote('He said "yes" and then left the room quietly.')
        self.assertEqual(quote, "He said")
        self.assertEqual(offline_agent.plain_quote("Alpha beta gamma delta", limit=12), "Alpha beta")
        self.assertEqual(offline_agent.plain_quote('"leading mark'), "")

    def test_a_tier_the_text_cannot_reach_is_not_assessed(self):
        for name, claim in (("abstract-only content for a full-text claim", {**self.CLAIM, "tier": "full_text", "sources": [self.source("An abstract.")]}),
                            ("no usable content", {**self.CLAIM, "sources": [self.source(None, "bibliographic")]})):
            with self.subTest(name):
                item = self.judge(claim)
                self.assertEqual((item["verdict"], item["cited_spans"]), ("cannot_assess_at_required_tier", []))


class WorldTest(unittest.TestCase):
    def test_the_contract_is_valid_hash_true_and_carries_the_confidence_scheme(self):
        doc = offline_world.contract()
        self.assertEqual(SCHEMAS.errors(doc, "contract-v2.schema.json"), [])
        self.assertEqual(doc["content_hash"], canonical.content_hash(doc))
        self.assertEqual(sorted(doc["confidence_scheme"]["labels"]), ["high", "low"])

    def test_the_bundle_carries_the_executors_and_validates(self):
        entry = {"kind": "research_pass", "purpose": "scope", "prompt": {"version": 1, "content_hash": "sha256:" + "a" * 64},
                 "deadline_s": 60, "lease_s": 90, "max_input_bytes": 1000, "max_output_bytes": 1000}
        doc = offline_world.bundle([entry])
        self.assertEqual(SCHEMAS.errors(doc, "config-bundle.schema.json"), [])
        self.assertEqual(orders.executor_entry(doc, "research_pass", "scope")["lease_s"], 90)
        with self.assertRaises(common.Refused):
            orders.executor_entry(doc, "verification", "verify")
