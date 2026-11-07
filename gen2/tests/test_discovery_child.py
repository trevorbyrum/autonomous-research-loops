"""gen2/discovery requests and the supervised child. Oracles: the search-proposal schema (SchemaSet), hashlib/canonical
digests, and the gateway client's own observations (the child adds none). The gateway is a canned transport behind the real
GatewayClient, never a socket. Limits: recording into the router and staging exchanges are the recorder's (separate tests);
the deadline that bounds a hung lookup is the supervisor's, not tested here."""
import json
import tempfile
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.discovery import child, requests
from gen2.exec import common, orders
from gen2.gateway_client.client import GatewayClient, GrantRefused
from gen2.router.schemas import SchemaSet

SCHEMAS = SchemaSet()
INV, TOPIC, BASE = "inv_discover1", "fleet:topic", "http://127.0.0.1:8765"
ABSTRACT = "The retained abstract of the adapter-shaped record."
HEADERS = {"content-type": "application/json", "x-research-gateway": "result"}


def validate(name, instance):
    errors = SCHEMAS.errors(instance, f"{name}.schema.json")
    if errors:
        raise common.Refused(f"{name}: {errors}")


def proposal(n=1, **over):
    return {"proposal_version": "search-proposal/1", "proposal_id": f"p{n}", "proposer": "primary", "lane": "crossref", "request_type": "find",
            "query": f"query {n}", "page_cap": 1, "obligation_ids": ["ob-1"], "rationale": "r", **over}


PROPOSER = "inv_proposer01"


def committed(proposals, by=PROPOSER, topic=TOPIC):
    """The `committed` part of a discovery view: an outcome payload as the router would have committed it, and its receipt."""
    payload = canonical.canonical_bytes({"outcome_version": "outcome/1", "invocation_id": by, "topic_id": topic, "search_proposals": proposals})
    return {"committed": {"payload": payload.decode(), "receipt": {"invocation_id": by, "payload_digest": canonical.bytes_digest(payload)}}}


class Gateway:
    """A canned gateway: mints a grant, answers a find with one lane that retrieved one record, or fails as told."""
    def __init__(self, grant_status=201, fail=False):
        self.calls, self.grant_status, self.fail = [], grant_status, fail

    def records(self, lane):
        return [{"identity": "doi:10.1/a", "title": "t", "source_id": lane, "abstract": ABSTRACT}]

    def __call__(self, method, url, headers, body, timeout):
        sent = canonical.parse_json_strict(body)
        self.calls.append((url.removeprefix(BASE), headers, sent))
        if url.endswith("/v1/grants"):
            return self.grant_status, HEADERS, json.dumps({"token": "gwg1.minted"} if self.grant_status == 201 else {"error": "no"}).encode(), None
        if self.fail:
            return None, {}, b"", "timeout"
        lane = sent["lanes"][0]
        answer = {"observation": {"invocation_id": INV, "attempt": 1, "captured": True, "call_ref": 100 + len(self.calls)},
                  "lanes": [{"source": lane, "coverage": "searched_ok", "completeness": "complete", "count": 1, "retrieved": [r["identity"] for r in self.records(lane)], "exhausted": True}],
                  "records": self.records(lane)}
        return 200, HEADERS, json.dumps(answer).encode(), None


class RequestsTest(unittest.TestCase):
    def payload(self, proposals, by=PROPOSER, topic=TOPIC):
        c = committed(proposals, by, topic)["committed"]
        return c["payload"].encode(), c["receipt"]

    def test_intake_returns_the_proposals_and_the_invocation_that_committed_them(self):
        data, receipt = self.payload([proposal(1), proposal(2)])
        got = requests.intake(data, receipt, TOPIC, 10_000, validate)
        self.assertEqual((got.invocation_id, [p["proposal_id"] for p in got.proposals]), (PROPOSER, ["p1", "p2"]))

    def test_intake_refuses_whole(self):
        ok, receipt = self.payload([proposal(1)])
        other, _ = self.payload([proposal(1)], by="inv_forged0001")
        cases = {"not the receipt's bytes": (other, receipt, 10_000),
                 "document names another invocation than its receipt": (other, {**receipt, "payload_digest": canonical.bytes_digest(other)}, 10_000),
                 "document names another topic": (*self.payload([proposal(1)], topic="fleet:other")[:1], self.payload([proposal(1)], topic="fleet:other")[1], 10_000),
                 "over the byte cap": (ok, receipt, 10),
                 "too many": (*self.payload([proposal(n) for n in range(33)]), 10**7),
                 "repeated id": (*self.payload([proposal(1), proposal(1, query="other")]), 10_000),
                 "schema refusal": (*self.payload([proposal(1, page_cap=0)]), 10_000)}
        for name, (data, rcpt, cap) in cases.items():
            with self.subTest(name), self.assertRaises(common.Refused):
                requests.intake(data, rcpt, TOPIC, cap, validate)

    def test_select_runs_all_or_only_named_proposals_and_refuses_a_name_the_payload_lacks(self):
        data, receipt = self.payload([proposal(1), proposal(2)])
        got = requests.intake(data, receipt, TOPIC, 10_000, validate)
        self.assertEqual([p["proposal_id"] for p in requests.select(got, None)], ["p1", "p2"])
        self.assertEqual([p["proposal_id"] for p in requests.select(got, ["p2"])], ["p2"])
        with self.assertRaises(common.Refused):
            requests.select(got, ["p2", "p9"])

    def test_requests_by_type_are_deterministic(self):
        table = [(proposal(request_type="find", filters={"kind": "article", "limit": 5}), {"request_type": "find", "query": "query 1", "lanes": ["crossref"], "kind": "article", "limit": 5}, 1),
                 (proposal(request_type="find", page_cap=3), {"request_type": "find", "query": "query 1", "lanes": ["crossref"]}, 3),
                 (proposal(request_type="resolve", page_cap=4), {"request_type": "resolve", "identity": "query 1", "lanes": ["crossref"]}, 1),
                 (proposal(request_type="enrich", filters={"what": "citations"}), {"request_type": "enrich", "target": "query 1", "lanes": ["crossref"], "what": "citations"}, 1),
                 (proposal(request_type="data", filters={"params": {"a": 1}}), {"request_type": "data", "target": "query 1", "lanes": ["crossref"], "params": {"a": 1}}, 1)]
        for p, expected, page_count in table:
            with self.subTest(p["request_type"]):
                self.assertEqual(requests.gateway_request(p), expected)
                self.assertEqual(requests.gateway_request(p), requests.gateway_request(dict(p)))
                self.assertEqual(requests.pages(p), page_count)

    def test_a_filter_the_type_does_not_take_is_refused_not_dropped(self):
        for p in (proposal(filters={"what": "citations"}), proposal(filters={"limit": "5"}), proposal(filters={"limit": True}),
                  proposal(request_type="resolve", filters={"kind": "article"})):
            with self.subTest(p.get("filters")), self.assertRaises(common.Refused):
                requests.gateway_request(p)


class Fixture:
    """A scratch directory, a canned gateway and the child's staging, shared with the recorder tests (not itself a test case)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gateway = Gateway()
        self.built = []

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, proposals, committed_by=PROPOSER, **view):
        document = orders.work_input(kind="discovery", purpose="search", invocation_id=INV, topic_id=TOPIC,
                                     admission={"context": "contract/1", "contract": {"revision": 1, "content_hash": "sha256:" + "a" * 64}},
                                     entry={"max_input_bytes": 100_000, "max_output_bytes": 100_000},
                                     view={**committed(proposals, committed_by), "attempt": 1, "gateway": {"policy_version": "gw/1", "commercial": False, "accept_per_item": True}, **view},
                                     truncation=[])
        (self.root / "inputs").mkdir()
        data = canonical.canonical_bytes(document)
        (self.root / "inputs" / "input.json").write_bytes(data)
        return {"GEN2_INPUT_DIGEST": canonical.bytes_digest(data), child.URL: BASE, child.TOKEN: "engine-token"}

    def factory(self, url, token):
        self.built.append((url, token))
        return GatewayClient(url, token, transport=self.gateway, clock=lambda: "2026-11-05T12:00:00Z", sleep=lambda s: None)

    def run_child(self, env):
        return child.run(self.root, environ=env, validate=validate, factory=self.factory)


class ChildTest(Fixture, unittest.TestCase):
    def test_proposals_run_serially_under_a_minted_grant_and_the_result_keeps_every_observation(self):
        env = self.stage([proposal(1), proposal(2, lane="doaj")])
        outcome = self.run_child(env)
        self.assertEqual(self.built, [(BASE, "engine-token")])
        paths = [call[0] for call in self.gateway.calls]
        self.assertEqual(paths, ["/v1/grants", "/v1/find", "/v1/find"])
        grant_body = self.gateway.calls[0][2]
        self.assertEqual((grant_body["topic_id"], grant_body["commercial"], grant_body["accept_per_item"], grant_body["invocation_id"]), (TOPIC, False, True, INV))
        for _, headers, _ in self.gateway.calls[1:]:
            self.assertEqual((headers["Authorization"], headers["X-Research-Invocation"], headers["X-Research-Attempt"]), ("Bearer gwg1.minted", INV, "1"))
        result = canonical.parse_json_strict((self.root / "discovery-result.json").read_bytes())
        self.assertEqual([s["proposal_id"] for s in result["searches"]], ["p1", "p2"])
        lanes = [o["observation"]["lane"] for s in result["searches"] for o in s["out"]["observations"]]
        self.assertEqual(lanes, ["crossref", "doaj"])
        self.assertEqual(result["searches"][0]["out"]["observations"][0]["observation"]["obligation_ids"], ["ob-1"])
        self.assertEqual(SCHEMAS.errors(canonical.parse_json_strict(outcome.read_bytes()), "outcome-document.schema.json"), [])
        self.assertEqual(canonical.parse_json_strict(outcome.read_bytes())["claims"], [])

    def test_a_search_that_got_no_answer_is_an_unknown_observation_never_zero_results(self):
        self.gateway.fail = True
        self.run_child(self.stage([proposal(1)]))
        result = canonical.parse_json_strict((self.root / "discovery-result.json").read_bytes())
        (observation,) = [o["observation"] for o in result["searches"][0]["out"]["observations"]]
        self.assertEqual((observation["coverage_state"], observation["result_count"], observation["error_class"]), ("unknown", None, "timeout"))

    def test_refusals_happen_before_any_gateway_contact_and_leave_no_result(self):
        good = self.stage([proposal(1)])
        cases = {"digest drift": {**good, "GEN2_INPUT_DIGEST": "sha256:" + "0" * 64}}
        for name, env in cases.items():
            with self.subTest(name), self.assertRaises(common.Refused):
                self.run_child(env)
        self.assertEqual((self.built, list((self.root).glob("*.json"))), ([], []))

    def test_an_invalid_proposal_or_filter_stops_the_whole_job_before_any_request(self):
        for name, proposals in (("schema", [proposal(1), proposal(2, page_cap=0)]), ("filter", [proposal(1), proposal(2, filters={"what": "x"})])):
            with self.subTest(name):
                self.tmp.cleanup()
                self.setUp()
                env = self.stage(proposals)
                with self.assertRaises(common.Refused):
                    self.run_child(env)
                self.assertEqual((self.built, self.gateway.calls), ([], []))

    def test_a_refused_grant_raises_and_no_search_is_sent(self):
        self.gateway.grant_status = 403
        env = self.stage([proposal(1)])
        with self.assertRaises(GrantRefused):
            self.run_child(env)
        self.assertEqual([c[0] for c in self.gateway.calls], ["/v1/grants"])
        self.assertFalse((self.root / "discovery-result.json").exists())

    def test_a_stale_endpoint_is_resolved_before_each_search(self):
        events = []

        class Client:
            endpoint_stale = True
            last_resolution = None

            def grant(self, **kw):
                return {"token": "t"}

            def resolve(self):
                events.append("resolve")

            def search(self, request, **kw):
                events.append("search")
                return {"observations": [], "capability_facts": [], "telemetry_losses": [], "pages": []}
        child.run(self.root, environ=self.stage([proposal(1), proposal(2)]), validate=validate, factory=lambda url, token: Client())
        self.assertEqual(events, ["resolve", "search", "resolve", "search"])

    def test_an_oversized_result_is_refused(self):
        env = self.stage([proposal(1)])
        data = json.loads((self.root / "inputs" / "input.json").read_bytes())
        data["limits"]["max_output_bytes"] = 50
        raw = canonical.canonical_bytes(data)
        (self.root / "inputs" / "input.json").write_bytes(raw)
        with self.assertRaises(common.Refused):
            self.run_child({**env, "GEN2_INPUT_DIGEST": canonical.bytes_digest(raw)})
        self.assertFalse((self.root / "outcome.json").exists())
