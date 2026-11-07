"""proposal_ref (Astra #125 F2): an observation belongs to the proposal that caused it, by identity. Oracles: the gateway
client's own id derivation on an UNSTAMPED observation (the parity test), `canonical.logical_hash` for the request identity,
and a real Router and store for acceptance (record, replay, the stored request). Limits: the challenge view that reads the
ref is T16's; the proposing invocation id is the driver's to supply from the committed payload and is only shape-checked here."""
import json
import unittest

from gen2.core import canonical
from gen2.discovery import child, recorder, stamp
from gen2.exec.common import Refused
from gen2.tests.router_fixtures import RouterTestCase
from gen2.tests.test_discovery_child import INV, Fixture, Gateway, committed, proposal
from gen2.gateway_client.client import GatewayClient

BASE = "http://127.0.0.1:8765"
REF = "inv_proposer01"


def result_of(case):
    return canonical.parse_json_strict((case.root / "discovery-result.json").read_bytes())


def observations(result):
    return [o for s in result["searches"] for o in s["out"]["observations"]]


class ParityTest(unittest.TestCase):
    def test_the_derivation_reproduces_the_clients_own_ids_for_an_unstamped_observation(self):
        client = GatewayClient(BASE, "t", transport=Gateway(), clock=lambda: "2026-11-05T12:00:00Z", sleep=lambda s: None)
        token = client.grant(topic_id="fleet:topic", commercial=False, accept_per_item=False, invocation_id=INV)["token"]
        out = client.search({"request_type": "find", "query": "q", "lanes": ["crossref"]}, invocation_id=INV, attempt=1, policy_version="gw/1", token=token)
        (item,) = out["observations"]
        doc = item["observation"]
        self.assertEqual(doc["request_identity"], canonical.logical_hash(doc["request"]))
        self.assertEqual(doc["observation_id"], "obs_" + stamp.digest("observation", INV, 1, doc["request_identity"]))
        self.assertEqual([e["event_id"] for e in item["retrieval_events"]],
                         ["rev_" + stamp.digest("event", doc["observation_id"], e["provider_record_id"]) for e in item["retrieval_events"]])

    def test_a_retained_string_request_cannot_be_stamped(self):
        out = {"observations": [{"observation": {"request": "{raw}", "request_identity": "x", "observation_id": "o"}, "retrieval_events": []}]}
        with self.assertRaises(Refused):
            stamp.stamp(out, "inv_aaaaaaaa:p1", invocation_id=INV, attempt=1)


class ChildStampsTest(Fixture, unittest.TestCase):
    def test_same_lane_and_query_under_two_proposals_are_two_observations(self):
        self.run_child(self.stage([proposal(1, query="same", obligation_ids=[]), proposal(2, query="same", obligation_ids=[])]))
        a, b = observations(result_of(self))
        self.assertEqual((a["observation"]["request"]["proposal_ref"], b["observation"]["request"]["proposal_ref"]), (f"{REF}:p1", f"{REF}:p2"))
        self.assertEqual(a["observation"]["request"]["request"], b["observation"]["request"]["request"], "the same attempted request")
        self.assertEqual(a["observation"]["lane"], b["observation"]["lane"])
        self.assertNotEqual(a["observation"]["request_identity"], b["observation"]["request_identity"])
        self.assertNotEqual(a["observation"]["observation_id"], b["observation"]["observation_id"])
        self.assertTrue({e["event_id"] for e in a["retrieval_events"]}.isdisjoint({e["event_id"] for e in b["retrieval_events"]}))
        for item in (a, b):
            self.assertEqual(item["observation"]["request_identity"], canonical.logical_hash(item["observation"]["request"]))

    def test_the_stamped_request_is_a_recorded_superset_of_what_was_sent_and_still_links_to_the_gateways_call(self):
        self.run_child(self.stage([proposal(1, query="same", obligation_ids=[])]))
        (search,) = result_of(self)["searches"]
        (item,) = search["out"]["observations"]
        doc, (page,) = item["observation"], search["out"]["pages"]
        sent = [{"request_type": "find", **body} for path, _, body in self.gateway.calls if path == "/v1/find"]   # the client sends the type in the path
        self.assertEqual(doc["request"]["request"], sent[0], "the sent payload is carried unchanged")
        self.assertEqual(doc["request"]["request"], page["sent"])
        self.assertEqual(doc["gateway_call_ref"], f"gw-call:{page['call_ref']}", "the link to the gateway's own call row is untouched")
        original = {k: v for k, v in doc["request"].items() if k != "proposal_ref"}
        unstamped = GatewayClient(BASE, "t", transport=Gateway(), clock=lambda: "2026-11-05T12:00:00Z", sleep=lambda s: None)
        token = unstamped.grant(topic_id="fleet:topic", commercial=False, accept_per_item=True, invocation_id=INV)["token"]
        again = unstamped.search(sent[0], invocation_id=INV, attempt=1, policy_version="gw/1", token=token)
        self.assertEqual(canonical.logical_hash(original), again["observations"][0]["observation"]["request_identity"],
                         "the identity the client alone would have given is recomputable from the stamped request")
        self.assertNotEqual(doc["request_identity"], canonical.logical_hash(original))

    def test_a_degraded_attempt_is_stamped_too(self):
        self.gateway.fail = True
        self.run_child(self.stage([proposal(1, obligation_ids=[])]))
        (item,) = observations(result_of(self))
        doc = item["observation"]
        self.assertEqual((doc["coverage_state"], doc["error_class"], doc["request"]["proposal_ref"]), ("unknown", "timeout", f"{REF}:p1"))
        self.assertEqual(doc["request_identity"], canonical.logical_hash(doc["request"]))

    def test_the_proposer_comes_only_from_the_committed_outcome(self):
        """A proposer supplied beside the committed bytes, or a receipt that names another (well-formed) invocation, refuses before any request."""
        env = self.stage([proposal(1, obligation_ids=[])], proposed_by="inv_forged0001")
        with self.assertRaises(Refused):
            self.run_child(env)
        self.tearDown()
        self.setUp()
        view = committed([proposal(1, obligation_ids=[])])
        view["committed"]["receipt"]["invocation_id"] = "inv_forged0001"
        env = self.stage([], **{"committed": view["committed"]})
        with self.assertRaises(Refused):
            self.run_child(env)
        self.assertEqual((self.built, self.gateway.calls), ([], []))


class RouterAcceptsStampedTest(Fixture, RouterTestCase):
    """The real router and store: the extra request key passes the SQL CHECK and the identity check, and replays."""
    def setUp(self):
        RouterTestCase.setUp(self)
        Fixture.setUp(self)
        self.to_scoping()
        self.grant = self.started(INV, "discovery")

    def tearDown(self):
        Fixture.tearDown(self)
        RouterTestCase.tearDown(self)

    def test_stamped_observations_record_replay_and_keep_their_ref(self):
        self.run_child(self.stage([proposal(1, query="same", obligation_ids=[]), proposal(2, query="same", obligation_ids=[]), proposal(3, query="other", obligation_ids=[])]))
        self.gateway.fail = False
        replies = []
        for _ in range(2):
            for item in observations(result_of(self)):
                replies.append(self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": INV,
                                                               "observation": item["observation"], "retrieval_events": item["retrieval_events"]})["status"])
        self.assertEqual(replies, ["recorded"] * 3 + ["replayed"] * 3)
        self.assertEqual(self.rows("SELECT json_extract(request, '$.proposal_ref') FROM search_observations ORDER BY 1"),
                         [(f"{REF}:p1",), (f"{REF}:p2",), (f"{REF}:p3",)])

    def test_a_degraded_stamped_attempt_is_recorded_unknown(self):
        self.gateway.fail = True
        self.run_child(self.stage([proposal(1, obligation_ids=[])]))
        (item,) = observations(result_of(self))
        reply = self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": INV,
                                                "observation": item["observation"], "retrieval_events": item["retrieval_events"]})
        self.assertEqual(reply["status"], "recorded")
        self.assertEqual(self.rows("SELECT coverage_state, completeness, json_extract(request, '$.proposal_ref') FROM search_observations"),
                         [("unknown", "unobserved", f"{REF}:p1")])
