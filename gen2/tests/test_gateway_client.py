"""The engine's gateway client (task 2b; gen2/gateway_client; BOUNDARIES.md Gateway).

Oracle: the gateway's own recorded answers (gen2/tests/fixtures/gateway_answers/, written
and re-verified against the real service by gateway/tests/test_engine_fixtures.py, which
also asserts their contract facts by hand) as INPUTS, and the observation tuples below,
stated by hand from STATION-CONTRACT.md and the store's rules, as the expected values. A
replaying transport checks the client sends exactly the requests the gateway was asked —
method, path, body, correlation headers, which credential — and hands back the recorded
answers; the resulting observations are then recorded through a real router
(record_gateway_facts, record_observation) so what 2c/2d consume is known to be
admissible, not just well-shaped. Negatives mutate a recorded answer one property at a
time (each paired with the unmutated answer as its control), or replace the transport's
outcome.

What these tests cannot show: that a different gateway release answers the same way (the
fixture check on the gateway side is what catches drift), or the live network.
"""
from __future__ import annotations

import copy
import http.server
import json
import threading
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.gateway_client import observe
from gen2.gateway_client.client import GatewayClient, GrantRefused, http_transport
from gen2.tests.router_fixtures import RouterTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gateway_answers"
BASE = "http://gateway.invalid:8765"
INV = "inv_fixture0001"
ENGINE_TOKEN = "tok-engine-secret"
HEADERS = {"content-type": "application/json", "x-research-gateway": "result"}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class Replay:
    """A transport answering with recorded exchanges, in order, after checking each request."""

    def __init__(self, test: unittest.TestCase, exchanges: list[dict]):
        self.test, self.exchanges, self.sent = test, list(exchanges), []

    def __call__(self, method, url, headers, body, timeout):
        self.test.assertTrue(self.exchanges, f"an unexpected request: {method} {url}")
        want = self.exchanges.pop(0)
        req, resp = want["request"], want["response"]
        self.sent.append((method, url, headers, body))
        self.test.assertEqual((method, url), (req["method"], BASE + req["path"]))
        self.test.assertEqual(canonical.parse_json_strict(body) if body else None, req["body"], "the body the gateway was asked")
        corr = req["correlation"]
        self.test.assertEqual((headers.get("X-Research-Invocation"), headers.get("X-Research-Attempt")),
                              (corr["invocation_id"], str(corr["attempt"])) if corr else (None, None))
        bearer = headers["Authorization"].removeprefix("Bearer ")
        self.test.assertEqual("grant" if bearer.startswith("gwg1.") else "engine", req["authorization"])
        return (resp["status"], {"content-type": resp["content_type"], "x-research-gateway": resp["x_research_gateway"]},
                json.dumps(resp["body"]).encode(), None)


def client(test, exchanges, **kw) -> tuple[GatewayClient, Replay]:
    replay = Replay(test, exchanges)
    return GatewayClient(BASE, ENGINE_TOKEN, transport=replay, clock=lambda: "2026-09-30T10:00:00Z", sleep=lambda s: None, **kw), replay


FIND = {"request_type": "find", "query": "reranking", "kind": "article", "domain": "finance"}
RESOLVE = {"request_type": "resolve", "identity": "doi:10.1234/abc"}


def search(test, name, request=FIND, exchanges=None, **kw):
    c, replay = client(test, fixture(name)["exchanges"] if exchanges is None else exchanges)
    out = c.search(request, invocation_id=INV, attempt=1, policy_version="gw-policy/1", **kw)
    test.assertEqual(replay.exchanges, [], "every recorded exchange was asked for")
    return out


def by_lane(out) -> dict:
    return {o["observation"]["lane"]: o for o in out["observations"]}


def by_page(out) -> dict:
    return {(o["observation"]["lane"], o["observation"]["request"]["page"]): o for o in out["observations"]}


def summary(obs) -> tuple:
    o = obs["observation"]
    return (o["coverage_state"], o["completeness"], o["result_count"], o["error_class"],
            [e["provider_record_id"] for e in obs["retrieval_events"]])


def answering(body_of) -> callable:
    """A transport answering every POST with the body body_of(sent payload) returns (echoing this invocation)."""
    def transport(method, url, headers, body, timeout):
        return 200, HEADERS, json.dumps(body_of(canonical.parse_json_strict(body))).encode(), None
    return transport


class RecordedAnswers(unittest.TestCase):
    def test_a_complete_answer_is_one_observation_per_lane(self):
        out = search(self, "find_complete")
        lanes = by_lane(out)
        self.assertEqual(summary(lanes["crossref"]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))
        self.assertEqual(summary(lanes["doaj"]), ("searched_empty", "complete", 0, None, []))
        for lane, obs in lanes.items():
            o = obs["observation"]
            self.assertEqual(o["request_identity"], canonical.logical_hash(o["request"]), "H-5: the identity is the request's hash")
            self.assertEqual(o["request"], {"lane": lane, "page": 1, "request": FIND}, "what the engine attempted, nothing the answer said")
            self.assertEqual((o["attempt"], o["policy_version"], o["gateway_call_ref"], o["cost_units"]), (1, "gw-policy/1", "gw-call:101", None))
            self.assertEqual(obs["delivery"]["served"], "dispatched")
        recorded = fixture("find_complete")["exchanges"][0]["response"]["body"]
        self.assertEqual((out["pages"][0]["gateway_request_identity"], out["pages"][0]["effective_request"]),
                         (recorded["request_identity"], recorded["effective_request"]), "the gateway's echo is kept beside, not inside, identity")
        self.assertNotEqual(lanes["crossref"]["observation"]["observation_id"], lanes["doaj"]["observation"]["observation_id"])
        self.assertEqual(out["telemetry_losses"], [])
        (rec,) = lanes["crossref"]["records"]
        self.assertEqual(set(rec["permissions"]), {"availability", "access", "storage", "redistribution"})

    def test_the_same_answer_twice_is_the_same_observation(self):
        a, b = search(self, "find_complete"), search(self, "find_complete")
        self.assertEqual(a["observations"], b["observations"], "deterministic ids: re-recording replays, never duplicates")
        c, _ = client(self, fixture("find_complete")["exchanges"])
        other = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1", obligation_ids=["O1"])
        self.assertEqual([o["observation"]["observation_id"] for o in other["observations"]],
                         [o["observation"]["observation_id"] for o in a["observations"]],
                         "the observation's identity is the invocation, attempt and request — not what it is linked to")

    def test_an_uncaptured_answer_is_a_lower_bound_never_negative_evidence(self):
        """2b-repair A1 (replaces the test that kept complete coverage after a lost durable row):
        the loss is explicit, what was read stays as a lower bound, and the empty lane is not
        evidence of absence."""
        out = search(self, "find_not_captured")
        self.assertEqual(out["telemetry_losses"], [{"reason": "no durable call log: this gateway runs without a database",
                                                    "invocation_id": INV, "attempt": 1}])
        lanes = by_lane(out)
        self.assertEqual(summary(lanes["crossref"]), ("searched_ok", "partial", 1, "telemetry_missing", ["doi:10.1234/abc"]))
        self.assertEqual(summary(lanes["doaj"]), ("unknown", "unobserved", None, "telemetry_missing", []))
        self.assertTrue(all(o["observation"]["gateway_call_ref"] is None for o in out["observations"]))

    def test_control_an_uncaptured_lane_with_records_keeps_them_as_a_lower_bound(self):
        ex = mutated("find_not_captured", 0, lambda r: r["body"]["lanes"].pop(1))
        c, _ = client(self, ex)
        (obs,) = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")["observations"]
        self.assertEqual(summary(obs), ("searched_ok", "partial", 1, "telemetry_missing", ["doi:10.1234/abc"]))

    def test_control_a_captured_answer_keeps_its_complete_lanes(self):
        lanes = by_lane(search(self, "find_complete"))
        self.assertEqual([summary(lanes[s])[:4] for s in ("crossref", "doaj")],
                         [("searched_ok", "complete", 1, None), ("searched_empty", "complete", 0, None)])

    def test_an_unreadable_lane_is_never_zero(self):
        lanes = by_lane(search(self, "find_unreadable_lane"))
        self.assertEqual(summary(lanes["crossref"]), ("provider_unavailable", "unobserved", None, "payload_invalid", []))
        self.assertEqual(summary(lanes["doaj"]), ("searched_empty", "complete", 0, None, []))

    def test_dropped_records_are_a_lower_bound(self):
        """Through the real Crossref parser (the fixture's members 7 and {} are unreadable)."""
        lanes = by_lane(search(self, "find_partial_records", {"request_type": "find", "query": "q", "kind": "article", "lanes": ["crossref"]}))
        self.assertEqual(summary(lanes["crossref"]), ("searched_ok", "partial", 2, "payload_invalid", ["doi:10.1234/abc", "doi:10.1234/def"]))

    def test_each_page_is_its_own_observation_and_a_failed_one_keeps_its_cursor(self):
        """2b-repair A2: the failed continuation is its own observation — its request the
        page actually sent (cursor c2, lane crossref), its outcome the gateway's — and the
        first page's read stands on its own: nothing rounded up."""
        pages = by_page(search(self, "find_paged_then_failed", pages=2))
        self.assertEqual(sorted(pages), [("crossref", 1), ("crossref", 2), ("doaj", 1)], "a finished lane is not asked again")
        self.assertEqual(summary(pages["crossref", 1]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))
        self.assertEqual(summary(pages["crossref", 2]), ("provider_unavailable", "unobserved", None, "provider_outage", []))
        self.assertEqual(pages["crossref", 2]["observation"]["request"],
                         {"lane": "crossref", "page": 2, "request": {**FIND, "cursors": {"crossref": "c2"}, "lanes": ["crossref"]}})
        self.assertEqual([pages[k]["observation"]["gateway_call_ref"] for k in (("crossref", 1), ("crossref", 2))], ["gw-call:101", "gw-call:102"])
        self.assertEqual(summary(pages["doaj", 1]), ("searched_empty", "complete", 0, None, []))

    def test_pages_that_all_answer_are_each_complete(self):
        pages = by_page(search(self, "find_paged_complete", pages=2))
        self.assertEqual(summary(pages["crossref", 1]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))
        self.assertEqual(summary(pages["crossref", 2]), ("searched_ok", "complete", 1, None, ["doi:10.1234/def"]))
        self.assertEqual(summary(pages["doaj", 1]), ("searched_empty", "complete", 0, None, []))
        self.assertNotEqual(pages["crossref", 1]["observation"]["observation_id"], pages["crossref", 2]["observation"]["observation_id"])

    def test_control_one_page_of_the_same_answer_is_complete(self):
        c, _ = client(self, fixture("find_paged_then_failed")["exchanges"][:1])
        out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        self.assertEqual(summary(by_lane(out)["crossref"]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))
        two = by_page(search(self, "find_paged_then_failed", pages=2))
        self.assertEqual(by_lane(out)["crossref"]["observation"]["observation_id"], two["crossref", 1]["observation"]["observation_id"],
                         "page 1 is the same observation however many pages were asked for")

    def test_a_failing_secrets_read_carries_its_fact_and_no_count(self):
        out = search(self, "data_secrets_failing", {"request_type": "data", "source": "fred", "params": {"series": "GDP"}})
        (fact,) = out["capability_facts"]
        self.assertEqual({k: fact[k] for k in ("capability", "state", "since", "last_success_at", "affected_lanes", "detail")},
                         {"capability": "gateway.secrets.vault", "state": "failing", "since": "2026-09-21T19:47:00Z",
                          "last_success_at": None, "affected_lanes": ["fred"], "detail": "403"})
        self.assertEqual(fact["fact_id"], canonical.gateway_fact_id("gateway.secrets.vault", "2026-09-21T19:47:00Z"))
        obs = by_lane(out)["fred"]
        self.assertEqual(summary(obs), ("provider_unavailable", "unobserved", None, "secrets_backend_failing", []))
        self.assertEqual(obs["observation"]["capability_fact_id"], fact["fact_id"])

    def test_a_grant_and_the_policy_it_binds(self):
        exchanges = fixture("grant_and_policy_refusal")["exchanges"]
        c, replay = client(self, exchanges)
        grant = c.grant(topic_id="topic-fixture", commercial=True, accept_per_item=False, invocation_id=INV)
        self.assertEqual((grant["client_id"], grant["invocation_id"]), ("engine@topic-fixture", INV))
        out = c.search({"request_type": "resolve", "identity": "doi:10.1234/abc", "commercial": False}, invocation_id=INV, attempt=1,
                       policy_version="gw-policy/1", token=grant["token"])
        self.assertEqual(summary(out["observations"][0]), ("not_searched", "unobserved", None, None, []),
                         "a request the topic's policy refuses was not searched, and is not an empty search")
        self.assertEqual(out["observations"][0]["observation"]["lane"], observe.GATEWAY_LANE)


def mutated(name: str, index: int, mutate) -> list[dict]:
    exchanges = copy.deepcopy(fixture(name)["exchanges"])
    mutate(exchanges[index]["response"])
    return exchanges


class UnreadableAnswers(unittest.TestCase):
    """One property of a recorded answer broken at a time; the control is the unbroken answer."""

    def lanes_of(self, exchanges, request=FIND, **kw) -> dict:
        c, _ = client(self, exchanges)
        return by_lane(c.search(request, invocation_id=INV, attempt=1, policy_version="gw-policy/1", **kw))

    def test_an_answer_for_another_invocation_is_not_attributed(self):
        for field, value in (("invocation_id", "inv_someone_else"), ("attempt", 2), ("attempt", True)):
            with self.subTest(field, value=value):
                ex = mutated("find_complete", 0, lambda r: r["body"]["observation"].__setitem__(field, value))
                c, _ = client(self, ex)
                out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
                self.assertEqual([summary(o) for o in out["observations"]], [("unknown", "unobserved", None, "payload_invalid", [])])
                self.assertIn("did not echo", out["telemetry_losses"][0]["reason"])

    def test_a_count_without_its_identities_is_not_a_count(self):
        for label, mutate in (("count up", lambda r: r["body"]["lanes"][0].__setitem__("count", 5)),
                              ("identities dropped", lambda r: r["body"]["lanes"][0].pop("retrieved")),
                              ("empty with a count", lambda r: r["body"]["lanes"][1].__setitem__("count", 3)),
                              ("partial without a reason", lambda r: r["body"]["lanes"][0].__setitem__("completeness", "partial")),
                              ("unknown vocabulary", lambda r: r["body"]["lanes"][0].update(
                                  coverage="searched_mostly", completeness="unobserved", error_class="payload_invalid", count=None, retrieved=None)),
                              ("unknown error class", lambda r: r["body"]["lanes"][0].update(
                                  coverage="provider_unavailable", completeness="unobserved", error_class="provider_down", count=None, retrieved=None)),
                              ("unobserved with a count", lambda r: r["body"]["lanes"][0].update(
                                  coverage="provider_unavailable", completeness="unobserved", error_class="provider_outage")),
                              ("observed with the wrong completeness", lambda r: r["body"]["lanes"][0].__setitem__("completeness", "unobserved"))):
            with self.subTest(label):
                lanes = self.lanes_of(mutated("find_complete", 0, mutate))
                broken = [sid for sid, obs in lanes.items() if summary(obs) == ("unknown", "unobserved", None, "payload_invalid", [])]
                self.assertEqual(len(broken), 1, label)
        self.assertEqual(summary(self.lanes_of(fixture("find_complete")["exchanges"])["crossref"])[0], "searched_ok", "control")

    def test_a_success_that_is_not_a_gateway_answer_is_unreadable(self):
        for label, mutate in (("no envelope header", lambda r: r.__setitem__("x_research_gateway", None)),
                              ("not JSON", lambda r: r.__setitem__("content_type", "text/html")),
                              ("no lanes", lambda r: r["body"].pop("lanes")),
                              ("no records list", lambda r: r["body"].pop("records")),
                              ("records not a list", lambda r: r["body"].__setitem__("records", {"doi:10.1234/abc": {}}))):
            with self.subTest(label):
                lanes = self.lanes_of(mutated("find_complete", 0, mutate))
                self.assertEqual([summary(o) for o in lanes.values()], [("unknown", "unobserved", None, "payload_invalid", [])])

    def test_an_answer_without_lanes_is_only_a_record_cache_hit_that_says_so(self):
        """2b-repair A1: `lanes: []` is read only as the record cache's one repeated record,
        marked as such; every other lane-less answer observed nothing — never an empty search."""
        hit = fixture("resolve_from_the_record_cache")["exchanges"][1:]
        cases = (("no records field", lambda r: r["body"].pop("records")),
                 ("no records", lambda r: r["body"].__setitem__("records", [])),
                 ("not marked a cache hit", lambda r: r["body"].pop("cache_hit")),
                 ("from another cache", lambda r: r["body"].__setitem__("served_from", "search_cache")),
                 ("two records", lambda r: r["body"]["records"].append(copy.deepcopy(r["body"]["records"][0]))),
                 ("a record without its identity", lambda r: r["body"]["records"][0].pop("identity")),
                 ("a record without its source", lambda r: r["body"]["records"][0].pop("source_id")))
        for label, mutate in cases:
            with self.subTest(label):
                ex = copy.deepcopy(hit)
                mutate(ex[0]["response"])
                self.assertEqual([summary(o) for o in self.lanes_of(ex, RESOLVE).values()], [("unknown", "unobserved", None, "payload_invalid", [])])
        empty = mutated("find_complete", 0, lambda r: r["body"].update(lanes=[], records=[]))
        self.assertEqual([summary(o) for o in self.lanes_of(empty).values()], [("unknown", "unobserved", None, "payload_invalid", [])],
                         "a find that names no lane observed nothing")

    def test_control_a_record_cache_hit_is_its_sources_record(self):
        lanes = self.lanes_of(fixture("resolve_from_the_record_cache")["exchanges"][1:], RESOLVE)
        self.assertEqual({k: summary(v) for k, v in lanes.items()}, {"crossref": ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"])})

    def test_a_named_lane_the_answer_leaves_out_is_unobserved(self):
        request = {**FIND, "lanes": ["crossref", "doaj"]}
        ex = mutated("find_complete", 0, lambda r: r["body"]["lanes"].pop(1))
        ex[0]["request"]["body"]["lanes"] = ["crossref", "doaj"]
        lanes = self.lanes_of(ex, request)
        self.assertEqual({k: summary(v)[:4] for k, v in lanes.items()},
                         {"crossref": ("searched_ok", "complete", 1, None), "doaj": ("unknown", "unobserved", None, "payload_invalid")})

    def test_a_repeated_identity_is_one_candidate(self):
        def repeat(r):
            lane = r["body"]["lanes"][0]
            lane["retrieved"] *= 2
            lane["count"] = 2
        self.assertEqual(summary(self.lanes_of(mutated("find_complete", 0, repeat))["crossref"]),
                         ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))

    def test_metadata_only_names_the_held_record(self):
        """2b-repair A1 (replaces metadata_only-to-searched_empty, test 115): an enrich of a held
        identity that found no full text is metadata_only for THAT record."""
        enrich = {"request_type": "enrich", "identity": "doi:10.1234/abc", "what": "full_text"}
        answer = {"lanes": [{"source": "unpaywall", "coverage": "metadata_only", "completeness": "complete", "count": 0, "retrieved": []}],
                  "records": [], "observation": {"invocation_id": INV, "attempt": 1, "served": "dispatched", "captured": True, "call_ref": 7}}
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(lambda sent: answer), clock=lambda: "2026-09-30T10:00:00Z")
        (obs,) = c.search(enrich, invocation_id=INV, attempt=1, policy_version="gw-policy/1")["observations"]
        self.assertEqual(summary(obs), ("metadata_only", "complete", 1, None, ["doi:10.1234/abc"]))

    def test_metadata_only_naming_nothing_is_unreadable_never_an_empty_query(self):
        """... and metadata_only naming nothing on any other request is unreadable, never inferred absence."""
        lanes = self.lanes_of(mutated("find_complete", 0, lambda r: r["body"]["lanes"][1].__setitem__("coverage", "metadata_only")))
        self.assertEqual(summary(lanes["doaj"]), ("unknown", "unobserved", None, "payload_invalid", []))

    def test_control_metadata_only_that_names_its_record_stays(self):
        def found(r):
            r["body"]["lanes"][0]["coverage"] = "metadata_only"
        self.assertEqual(summary(self.lanes_of(mutated("find_complete", 0, found))["crossref"]), ("metadata_only", "complete", 1, None, ["doi:10.1234/abc"]))


class TransportOutcomes(unittest.TestCase):
    def outcome(self, status, body=None, error=None, headers=None, request=FIND):
        def transport(method, url, hdrs, data, timeout):
            return status, headers or HEADERS, json.dumps(body).encode() if body is not None else b"", error
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=transport, clock=lambda: "2026-09-30T10:00:00Z", sleep=lambda s: None, deadline=2)
        return [summary(o) + (o["observation"]["lane"],) for o in
                c.search(request, invocation_id=INV, attempt=1, policy_version="gw-policy/1")["observations"]]

    def test_nothing_answered_is_unknown_never_empty(self):
        cases = ((None, None, "transport_failure", ("unknown", "unobserved", None, "transport_failure", [], "gateway")),
                 (None, None, "timeout", ("unknown", "unobserved", None, "timeout", [], "gateway")),
                 (500, {"error": "boom"}, None, ("unknown", "unobserved", None, "transport_failure", [], "gateway")),
                 (401, {"error": "token"}, None, ("auth_failed", "unobserved", None, "credentials_rejected", [], "gateway")),
                 (400, {"error": "bad"}, None, ("unknown", "unobserved", None, "payload_invalid", [], "gateway")),
                 (302, None, None, ("unknown", "unobserved", None, "transport_failure", [], "gateway")))
        for status, body, error, expected in cases:
            with self.subTest(status=status, error=error):
                self.assertEqual(self.outcome(status, body, error), [expected])

    def test_named_lanes_each_get_their_unknown(self):
        request = {**FIND, "lanes": ["crossref", "doaj"]}
        self.assertEqual(self.outcome(None, None, "timeout", request=request),
                         [("unknown", "unobserved", None, "timeout", [], lane) for lane in ("crossref", "doaj")])

    QUEUED = {"status": "queued", "job_id": 7, "created": True}
    POLLED = {"invocation_id": INV, "attempt": 1, "served": "polled", "job_id": 7, "captured": True, "call_ref": 900, "capture_loss": None}

    def queued_client(self, answers, seen=None) -> GatewayClient:
        answers = iter(answers)

        def transport(method, url, hdrs, data, timeout):
            if seen is not None:
                seen.append((method, hdrs.get("X-Research-Invocation"), hdrs.get("X-Research-Attempt")))
            status, body = next(answers)
            return status, HEADERS, json.dumps(body).encode(), None
        return GatewayClient(BASE, ENGINE_TOKEN, transport=transport, clock=lambda: "2026-09-30T10:00:00Z", sleep=lambda s: None, deadline=2)

    def done(self):
        done = fixture("find_complete")["exchanges"][0]["response"]["body"]
        return done, {**self.QUEUED, "observation": done["observation"]}

    def test_a_queued_answer_is_polled_to_its_result_under_this_invocation(self):
        done, queued = self.done()
        seen = []
        c = self.queued_client([(202, queued), (200, {"status": "running"}), (200, {"status": "done", "result": done, "observation": self.POLLED})], seen)
        lanes = by_lane(c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1"))
        self.assertIn("crossref", lanes, "the polled job's lanes, not the queued answer's (which has none)")
        self.assertEqual(summary(lanes["crossref"]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))
        self.assertEqual(seen, [("POST", INV, "1"), ("GET", INV, "1"), ("GET", INV, "1")], "every poll carries this invocation and attempt (A5)")

    def test_a_queued_answer_is_polled_and_a_job_that_never_ends_is_a_timeout(self):
        done, queued = self.done()
        for final, expected in (({"status": "running"}, "timeout"), ({"status": "failed", "result": {}, "observation": self.POLLED}, "transport_failure")):
            with self.subTest(final=final):
                c = self.queued_client([(202, queued)] + [(200, final)] * 10)
                out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
                self.assertEqual([summary(o) for o in out["observations"]], [("unknown", "unobserved", None, expected, [])])

    def test_a_poll_not_attributed_to_this_caller_or_not_captured_degrades(self):
        """2b-repair A5: the poll's own observation must echo this caller; one the gateway did
        not durably record is a telemetry loss (A1): its lanes keep what they read as a lower bound."""
        done, queued = self.done()
        for label, poll_obs in (("another invocation", {**self.POLLED, "invocation_id": "inv_other"}), ("no observation", None)):
            with self.subTest(label):
                final = {"status": "done", "result": done, **({"observation": poll_obs} if poll_obs else {})}
                out = self.queued_client([(202, queued), (200, final)]).search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
                self.assertEqual([summary(o) for o in out["observations"]], [("unknown", "unobserved", None, "payload_invalid", [])])
                self.assertIn("poll did not echo", out["telemetry_losses"][-1]["reason"])
        uncaptured = {**self.POLLED, "captured": False, "call_ref": None, "capture_loss": "poll row not written: OperationalError"}
        out = self.queued_client([(202, queued), (200, {"status": "done", "result": done, "observation": uncaptured})]).search(
            FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        self.assertEqual({k: summary(v)[:4] for k, v in by_lane(out).items()},
                         {"crossref": ("searched_ok", "partial", 1, "telemetry_missing"), "doaj": ("unknown", "unobserved", None, "telemetry_missing")})
        self.assertEqual(out["telemetry_losses"][-1]["reason"], "poll row not written: OperationalError")

    def test_a_refused_grant_raises(self):
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=lambda *a: (403, HEADERS, b'{"error": "only a configured grantor may mint grants"}', None))
        with self.assertRaises(GrantRefused):
            c.grant(topic_id="t", commercial=False, accept_per_item=False, invocation_id=INV)


def serve(test, handler_body) -> str:
    """A loopback HTTP server whose every request is answered by handler_body(handler)."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            handler_body(self)

        do_GET = do_POST
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_port}"


def recorded_answer(name: str, index: int = 0):
    """A loopback answer replaying one recorded response, headers and body as the gateway sent them."""
    resp = fixture(name)["exchanges"][index]["response"]

    def answer(h):
        raw = json.dumps(resp["body"]).encode()
        h.send_response(resp["status"])
        h.send_header("Content-Type", resp["content_type"])
        h.send_header("X-Research-Gateway", resp["x_research_gateway"])
        h.send_header("Content-Length", str(len(raw)))
        h.end_headers()
        h.wfile.write(raw)
    return answer


class OverRealHttp(unittest.TestCase):
    """The default transport against a loopback server replaying a recorded answer, and a
    redirect it must not follow (the bearer token is never sent elsewhere)."""

    def test_the_default_transport_reads_a_real_answer(self):
        c = GatewayClient(serve(self, recorded_answer("find_complete")), ENGINE_TOKEN, transport=http_transport)
        self.assertEqual(summary(by_lane(c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1"))["crossref"])[:3],
                         ("searched_ok", "complete", 1))

    def test_a_redirect_is_never_followed(self):
        seen = []
        other = serve(self, lambda h: seen.append(h.headers.get("Authorization")))
        for code in (301, 302, 303, 307, 308):   # urllib would follow a POST's 301-303 on its own, carrying the token
            with self.subTest(code):
                def redirect(h, code=code):
                    h.send_response(code)
                    h.send_header("Location", other + "/v1/find")
                    h.send_header("Content-Length", "0")
                    h.end_headers()
                out = GatewayClient(serve(self, redirect), ENGINE_TOKEN, transport=http_transport, timeout=5).search(
                    FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
                self.assertEqual([summary(o) for o in out["observations"]], [("unknown", "unobserved", None, "transport_failure", [])])
                self.assertEqual(seen, [], "the token went nowhere else")


class RecordedByTheRouter(RouterTestCase):
    """What the client returns is what the router records (2c/2d consume these rows), in the
    order observe.router_requests gives: the gateway's facts, then the observations."""

    def setUp(self) -> None:
        super().setUp()
        self.to_scoping()
        self.grant = self.started(INV, "discovery")

    def record(self, out) -> list[dict]:
        replies = []
        for command, request in observe.router_requests(out, capability_id=self.grant["capability_id"], invocation_id=INV):
            replies.append(getattr(self.router, command)(request))
        return replies

    def admissible(self, name: str, request: dict = FIND, **kw) -> dict:
        out = search(self, name, request, **kw)
        n = len(observe.router_requests(out, capability_id="-", invocation_id=INV))
        self.assertEqual([r["status"] for r in self.record(out)], ["recorded"] * n)
        self.assertEqual([r["status"] for r in self.record(out)], ["replayed"] * n, "idempotent")
        self.assertEqual(self.value("SELECT count(*) FROM search_observations WHERE result_count = 0 AND coverage_state != 'searched_empty'"), 0)
        return out

    def observations(self) -> list[tuple]:
        return self.rows("SELECT lane, json_extract(request, '$.page'), coverage_state, completeness, result_count, error_class "
                         "FROM search_observations ORDER BY lane, json_extract(request, '$.page')")

    def test_a_complete_answer_is_admissible(self):
        self.admissible("find_complete")

    def test_an_uncaptured_answer_is_recorded_as_a_lower_bound(self):
        """2b-repair A1 (replaces recording it complete): the durable rows say what was lost —
        the candidate identities kept, no complete coverage, no complete empty search."""
        self.admissible("find_not_captured")
        self.assertEqual(self.observations(), [("crossref", 1, "searched_ok", "partial", 1, "telemetry_missing"),
                                               ("doaj", 1, "unknown", "unobserved", None, "telemetry_missing")])
        self.assertEqual(self.rows("SELECT provider_record_id FROM retrieval_events"), [("doi:10.1234/abc",)])
        self.assertEqual(self.value("SELECT count(*) FROM search_observations WHERE completeness = 'complete' OR gateway_call_ref IS NOT NULL"), 0)

    def test_an_unreadable_lane_is_admissible_and_counts_nothing(self):
        self.admissible("find_unreadable_lane")
        self.assertEqual(self.rows("SELECT lane, coverage_state, result_count FROM search_observations ORDER BY lane"),
                         [("crossref", "provider_unavailable", None), ("doaj", "searched_empty", 0)])

    def test_a_partial_answer_is_admissible(self):
        self.admissible("find_partial_records", {"request_type": "find", "query": "q", "kind": "article", "lanes": ["crossref"]})
        self.assertEqual(self.value("SELECT count(*) FROM retrieval_events"), 2, "the lower bound's identities, one event each")

    def test_a_failed_continuation_is_its_own_observation_with_its_cursor(self):
        self.admissible("find_paged_then_failed", pages=2)
        self.assertEqual(self.observations(), [("crossref", 1, "searched_ok", "complete", 1, None),
                                               ("crossref", 2, "provider_unavailable", "unobserved", None, "provider_outage"),
                                               ("doaj", 1, "searched_empty", "complete", 0, None)])
        self.assertEqual([(json.loads(r)["request"].get("cursors"), ref) for r, ref in self.rows(
                          "SELECT request, gateway_call_ref FROM search_observations WHERE json_extract(request, '$.page') = 2")],
                         [({"crossref": "c2"}, "gw-call:102")], "the durable row keeps the failed page's own cursor and its own call")

    def test_pages_that_all_answer_are_each_admissible(self):
        self.admissible("find_paged_complete", pages=2)
        self.assertEqual(self.rows("SELECT provider_record_id FROM retrieval_events ORDER BY provider_record_id"),
                         [("doi:10.1234/abc",), ("doi:10.1234/def",)])

    def test_one_attempt_is_one_observation(self):
        """A different outcome for the same invocation, request and attempt is refused at the
        receipt (H-1: attempt identity is immutable; a retry is a new attempt)."""
        self.admissible("find_complete")
        conflicting = search(self, "find_unreadable_lane")
        replies = {o["observation"]["lane"]: r for o, r in zip(conflicting["observations"], self.record(conflicting))}
        self.assertEqual((replies["crossref"]["status"], replies["crossref"]["reason"]), ("refused", "observation_id_conflict"))
        self.assertEqual(replies["doaj"]["status"], "replayed", "control: the lane whose outcome is the same replays")

    def test_different_failed_requests_are_different_observations(self):
        """2b-repair A2: with nothing answered there is no echo; each attempted request — query,
        kind, cursor — is its own observation, recorded, never replayed as another's."""
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=lambda *a: (None, {}, b"", "timeout"), clock=lambda: "2026-09-30T10:00:00Z")
        requests = [FIND, {**FIND, "kind": "dataset"}, {**FIND, "query": "retrieval"}, {**FIND, "cursors": {"crossref": "c2"}, "lanes": ["crossref"]}]
        outs = [c.search(r, invocation_id=INV, attempt=1, policy_version="gw-policy/1") for r in requests]
        self.assertEqual([[r["status"] for r in self.record(o)] for o in outs], [["recorded"]] * 4)
        self.assertEqual([json.loads(r)["request"] for (r,) in self.rows("SELECT request FROM search_observations ORDER BY rowid")], requests,
                         "the attempted request is retained whole, with no answer to echo it")

    def test_the_design_reviews_collision_is_two_observations(self):
        """DR §9's probe through record_observation: q/article/cursor c1 and q/dataset/cursor c2 both answered."""
        body = fixture("find_complete")["exchanges"][0]["response"]["body"]
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(lambda sent: body), clock=lambda: "2026-09-30T10:00:00Z")
        a = {"request_type": "find", "query": "q", "kind": "article", "cursors": {"crossref": "c1"}}
        b = {"request_type": "find", "query": "q", "kind": "dataset", "cursors": {"crossref": "c2"}}
        replies = [self.record(c.search(r, invocation_id=INV, attempt=1, policy_version="gw-policy/1")) for r in (a, b)]
        self.assertEqual([[x["status"] for x in r] for r in replies], [["recorded", "recorded"]] * 2)
        self.assertEqual(self.value("SELECT count(DISTINCT request_identity) FROM search_observations"), 4)

    def test_a_delivery_change_is_never_a_second_observation(self):
        """2b-repair A2: the same attempt answered again from the gateway's cache is the same
        observation — refused as a conflict (its own call row differs), never recorded twice."""
        exchanges = fixture("find_served_from_cache")["exchanges"]
        first = search(self, "find_served_from_cache", exchanges=exchanges[:1])
        again = search(self, "find_served_from_cache", exchanges=exchanges[1:])
        self.assertEqual([o["delivery"]["served"] for o in again["observations"]], ["cache", "cache"])
        self.assertEqual([o["observation"]["observation_id"] for o in again["observations"]],
                         [o["observation"]["observation_id"] for o in first["observations"]], "delivery is not identity")
        self.assertEqual([r["status"] for r in self.record(first)], ["recorded", "recorded"])
        self.assertEqual([(r["status"], r.get("reason")) for r in self.record(again)], [("refused", "observation_id_conflict")] * 2)
        self.assertEqual((self.value("SELECT count(*) FROM search_observations"), self.value("SELECT count(*) FROM retrieval_events")), (2, 1))
        resolved = search(self, "resolve_from_the_record_cache", RESOLVE, exchanges=fixture("resolve_from_the_record_cache")["exchanges"][:1])
        cached = search(self, "resolve_from_the_record_cache", RESOLVE, exchanges=fixture("resolve_from_the_record_cache")["exchanges"][1:])
        self.assertEqual([r["status"] for r in self.record(resolved)], ["recorded"])
        self.assertEqual([(r["status"], r.get("reason")) for r in self.record(cached)], [("refused", "observation_id_conflict")],
                         "the record cache's repeat of crossref's dispatch is that lane's observation, not another")

    def test_control_the_same_delivery_again_replays(self):
        exchanges = copy.deepcopy(fixture("find_served_from_cache")["exchanges"])
        exchanges[1]["response"]["body"]["observation"]["call_ref"] = 101   # only `served` differs from the first
        first = search(self, "find_served_from_cache", exchanges=exchanges[:1])
        again = search(self, "find_served_from_cache", exchanges=exchanges[1:])
        self.assertEqual([r["status"] for r in self.record(first)], ["recorded", "recorded"])
        self.assertEqual([r["status"] for r in self.record(again)], ["replayed", "replayed"])

    def test_metadata_only_is_admissible_as_its_own_state(self):
        answer = {"lanes": [{"source": "unpaywall", "coverage": "metadata_only", "completeness": "complete", "count": 0, "retrieved": []}],
                  "records": [], "observation": {"invocation_id": INV, "attempt": 1, "served": "dispatched", "captured": True, "call_ref": 7}}
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(lambda sent: answer), clock=lambda: "2026-09-30T10:00:00Z")
        out = c.search({"request_type": "enrich", "identity": "doi:10.1234/abc", "what": "full_text"}, invocation_id=INV, attempt=1,
                       policy_version="gw-policy/1")
        self.assertEqual([r["status"] for r in self.record(out)], ["recorded"])
        self.assertEqual(self.rows("SELECT coverage_state, result_count FROM search_observations"), [("metadata_only", 1)])

    def test_a_secrets_failure_is_recorded_through_the_routers_own_commands(self):
        """DEPLOYMENT-CONTRACT §3.4 fixture 5, engine half (2b-repair A6; replaces the direct SQL
        insert): the gateway's HTTP answer, over a real socket, to the dated fact recorded by
        record_gateway_facts and the observation naming it — the router's commands only."""
        c = GatewayClient(serve(self, recorded_answer("data_secrets_failing")), ENGINE_TOKEN, transport=http_transport)
        out = c.search({"request_type": "data", "source": "fred", "params": {"series": "GDP"}}, invocation_id=INV, attempt=1,
                       policy_version="gw-policy/1")
        (fact,) = out["capability_facts"]
        self.assertEqual([(r["status"], r.get("facts")) for r in self.record(out)],
                         [("recorded", [{"fact_id": fact["fact_id"], "status": "recorded"}]), ("recorded", None)])
        self.assertEqual(self.rows("SELECT capability, state, since, detail, affected_lanes, observed_by_invocation_id FROM capability_facts "
                                   "WHERE capability LIKE 'gateway.%'"),
                         [("gateway.secrets.vault", "failing", "2026-09-21T19:47:00Z", "403", '["fred"]', INV)])
        self.assertEqual(self.rows("SELECT coverage_state, result_count, error_class, capability_fact_id FROM search_observations"),
                         [("provider_unavailable", None, "secrets_backend_failing", fact["fact_id"])])
        self.assertEqual([r["status"] for r in self.record(out)], ["replayed", "replayed"], "the same report replays whole")

    def test_an_observation_naming_an_unrecorded_fact_is_refused(self):
        out = search(self, "data_secrets_failing", {"request_type": "data", "source": "fred", "params": {"series": "GDP"}})
        (obs,) = out["observations"]
        reply = self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": INV,
                                                "observation": obs["observation"], "retrieval_events": obs["retrieval_events"]})
        self.assertEqual(reply["status"], "refused", "the fact is recorded first (router_requests' order)")


class GatewayFactsCommand(RouterTestCase):
    """record_gateway_facts (2b-repair A6): the router's typed, bounded path for the facts the
    gateway reports. Oracle: the rules stated in gen2/router/capabilities.py, by hand."""

    SINCE = "2026-09-21T19:47:00Z"

    def setUp(self) -> None:
        super().setUp()
        self.to_scoping()
        self.grant = self.started(INV, "discovery")

    def fact(self, since: str = SINCE, **over) -> dict:
        capability = over.pop("capability", "gateway.secrets.vault")
        return {"fact_id": canonical.gateway_fact_id(capability, since), "capability": capability, "state": "failing", "detail": "403",
                "since": since, "last_success_at": None, "affected_lanes": ["fred"], **over}

    def put(self, *facts, grant=None) -> dict:
        grant = grant or self.grant
        return self.router.record_gateway_facts({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "facts": list(facts)})

    def current(self) -> list[tuple]:
        return self.rows("SELECT fact_id, state, since FROM capability_facts WHERE capability = 'gateway.secrets.vault' AND superseded_by_fact_id IS NULL")

    def test_a_fact_is_recorded_and_replays(self):
        self.assertEqual(self.put(self.fact())["status"], "recorded")
        self.assertEqual(self.put(self.fact()), {"status": "replayed", "facts": [{"fact_id": self.fact()["fact_id"], "status": "replayed"}]})
        self.assertEqual(self.current(), [(self.fact()["fact_id"], "failing", self.SINCE)])

    def test_a_later_episode_supersedes_and_an_earlier_one_is_refused(self):
        self.put(self.fact())
        later = self.fact("2026-09-22T08:00:00Z", state="healthy", detail="recovered", last_success_at="2026-09-22T08:00:00Z")
        self.assertEqual(self.put(later)["status"], "recorded")
        self.assertEqual(self.current(), [(later["fact_id"], "healthy", "2026-09-22T08:00:00Z")])
        earlier = self.fact("2026-09-20T00:00:00Z")
        reply = self.put(earlier)
        self.assertEqual((reply["status"], reply.get("reason")), ("refused", "fact_superseded"))
        self.assertEqual(self.current(), [(later["fact_id"], "healthy", "2026-09-22T08:00:00Z")], "nothing moved")

    def test_what_is_not_a_gateway_fact_is_refused(self):
        cases = (("another namespace", self.fact(capability="provider-auth:claude")),
                 ("an id that is not its content's", {**self.fact(), "fact_id": "fact_" + "0" * 32}),
                 ("a since that is no instant", {**self.fact(), "since": "yesterday"}),
                 ("a state outside the vocabulary", self.fact(state="broken")))
        for label, fact in cases:
            with self.subTest(label):
                self.assertEqual(self.put(fact).get("reason"), "request_invalid")
        self.assertEqual(self.put(self.fact(), self.fact(detail="again")).get("reason"), "request_invalid", "one fact per capability")
        self.put(self.fact())
        self.assertEqual(self.put(self.fact(detail="other")).get("reason"), "fact_conflict", "other content under a recorded id")
        self.assertEqual(self.value("SELECT count(*) FROM capability_facts WHERE capability LIKE 'gateway.%'"), 1)

    def test_only_a_running_invocation_records_but_a_lost_reply_replays(self):
        self.put(self.fact())
        wrong = self.router.record_gateway_facts({"capability_id": self.grant["capability_id"], "invocation_id": "inv_someone_else",
                                                  "facts": [self.fact("2026-09-22T08:00:00Z")]})
        self.assertEqual(wrong.get("reason"), "capability_invocation_mismatch")
        self.clock.set("2027-01-01T00:00:00Z")   # the lease has expired
        self.assertEqual(self.put(self.fact())["status"], "replayed")
        reply = self.put(self.fact("2026-09-22T08:00:00Z"))
        self.assertEqual((reply["status"], reply.get("reason")), ("refused", "lease_not_current"))


if __name__ == "__main__":
    unittest.main()
