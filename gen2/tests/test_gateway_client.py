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
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.gateway_client import observe
from gen2.gateway_client.client import GatewayClient, GrantRefused, http_transport
from gen2.router.service import Router
from gen2.store import api
from gen2.tests import children
from gen2.tests.router_fixtures import OTHER, RouterTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gateway_answers"
BASE = "http://gateway.invalid:8765"
INV = "inv_fixture0001"
INV_B = "inv_fixture0002"   # a second invocation, of another topic
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
FIND_PAGED = {**FIND, "limit": 1}   # the paged scenarios ask pages of one: a page of one record is full, so it continues
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


class VirtualTime:
    """A monotonic clock the test moves: `sleep` advances it and so does a transport that takes time (`took`), so
    polling is exercised without waiting, and what it costs in (virtual) seconds is exact."""

    def __init__(self) -> None:
        self.now, self.sleeps = 0.0, []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def took(self, seconds: float, timeout: float) -> bool:
        """Spend a request's time, up to its timeout: True when the transport answered inside it, False when it timed out."""
        self.now += min(seconds, timeout)
        return seconds <= timeout


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
        pages = by_page(search(self, "find_paged_then_failed", FIND_PAGED, pages=2))
        self.assertEqual(sorted(pages), [("crossref", 1), ("crossref", 2), ("doaj", 1)], "a finished lane is not asked again")
        self.assertEqual(summary(pages["crossref", 1]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))
        self.assertEqual(summary(pages["crossref", 2]), ("provider_unavailable", "unobserved", None, "provider_outage", []))
        self.assertEqual(pages["crossref", 2]["observation"]["request"],
                         {"lane": "crossref", "page": 2, "request": {**FIND_PAGED, "cursors": {"crossref": "c2"}, "lanes": ["crossref"]}})
        self.assertEqual([pages[k]["observation"]["gateway_call_ref"] for k in (("crossref", 1), ("crossref", 2))], ["gw-call:101", "gw-call:102"])
        self.assertEqual(summary(pages["doaj", 1]), ("searched_empty", "complete", 0, None, []))

    def test_pages_that_all_answer_are_each_complete(self):
        pages = by_page(search(self, "find_paged_complete", FIND_PAGED, pages=2))
        self.assertEqual(summary(pages["crossref", 1]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))
        self.assertEqual(summary(pages["crossref", 2]), ("searched_ok", "complete", 1, None, ["doi:10.1234/def"]))
        self.assertEqual(summary(pages["doaj", 1]), ("searched_empty", "complete", 0, None, []))
        self.assertNotEqual(pages["crossref", 1]["observation"]["observation_id"], pages["crossref", 2]["observation"]["observation_id"])

    def test_control_one_page_of_the_same_answer_is_complete(self):
        c, _ = client(self, fixture("find_paged_then_failed")["exchanges"][:1])
        out = c.search(FIND_PAGED, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        self.assertEqual(summary(by_lane(out)["crossref"]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))
        two = by_page(search(self, "find_paged_then_failed", FIND_PAGED, pages=2))
        self.assertEqual(by_lane(out)["crossref"]["observation"]["observation_id"], two["crossref", 1]["observation"]["observation_id"],
                         "page 1 is the same observation however many pages were asked for")

    def test_a_failing_secrets_read_carries_its_fact_and_no_count(self):
        out = search(self, "data_secrets_failing", {"request_type": "data", "source": "fred", "params": {"series": "GDP"}})
        (fact,) = out["capability_facts"]
        self.assertEqual({k: fact[k] for k in ("capability", "state", "since", "last_success_at", "affected_lanes", "detail", "revision")},
                         {"capability": "gateway.secrets.vault", "state": "failing", "since": "2026-09-21T19:47:00Z",
                          "last_success_at": None, "affected_lanes": ["fred"], "detail": "403", "revision": 1})
        self.assertEqual(fact["fact_id"], canonical.gateway_fact_id({"capability": "gateway.secrets.vault", "state": "failing", "detail": "403",
                                                                      "since": "2026-09-21T19:47:00Z", "last_success_at": None,
                                                                      "affected_lanes": ["fred"], "revision": 1}))
        obs = by_lane(out)["fred"]
        self.assertEqual(summary(obs), ("provider_unavailable", "unobserved", None, "secrets_backend_failing", []))
        self.assertEqual(obs["observation"]["capability_fact_id"], fact["fact_id"])

    def test_a_fact_without_its_revision_is_no_fact(self):
        """2b-repair-3 R2: a snapshot is placed among its episode's by its revision; one the
        gateway did not give a revision (a positive integer) is not a fact the router can place."""
        body = fixture("data_secrets_failing")["exchanges"][0]["response"]["body"]["capability_facts"][0]
        self.assertEqual(observe.capability_fact(body)["revision"], 1, "control: the recorded fact")
        for label, revision in (("zero", 0), ("a string", "1"), ("a fraction", 1.5), ("a boolean", True)):
            with self.subTest(label):
                self.assertIsNone(observe.capability_fact({**body, "revision": revision}))
        self.assertIsNone(observe.capability_fact({k: v for k, v in body.items() if k != "revision"}))

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


class PageOutcomes(unittest.TestCase):
    """Gate D #3 (task 2b-repair-13b): each page observation says why pagination ended or continued — `exhausted` only on the
    lane's own reported end, `continuation` or `limit_reached` with the cursor handed back, `end_unknown` and `failed` — and a
    page read whole (`completeness`) is never the search population exhausted. Inputs are the gateway's recorded answers and
    answers stated by hand from STATION-CONTRACT.md; the expected outcomes are stated by hand."""

    @staticmethod
    def outcomes(out) -> dict:
        return {k: (o["observation"]["page_outcome"], o["observation"]["continuation"]) for k, o in by_page(out).items()}

    @staticmethod
    def lane_answer(**lane) -> dict:
        base = {"source": "crossref", "role": "base", "coverage": "searched_ok", "completeness": "complete", "count": 1, "retrieved": ["doi:10.1/a"]}
        return {"lanes": [{**base, **lane}], "records": [{"identity": "doi:10.1/a", "source_id": "crossref"}],
                "observation": {"invocation_id": INV, "attempt": 1, "served": "dispatched", "captured": True, "call_ref": 1}}

    def one_page(self, pages: int = 1, **lane) -> tuple[dict, list]:
        sent: list = []
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(lambda payload: sent.append(payload) or self.lane_answer(**lane)),
                          clock=lambda: "2026-09-30T10:00:00Z", sleep=lambda s: None)
        return c.search({**FIND, "lanes": ["crossref"]}, invocation_id=INV, attempt=1, policy_version="gw-policy/1", pages=pages), sent

    def test_each_page_says_why_pagination_ended_or_continued(self):
        cases = (
            ("an answer whose lanes report their end", "find_complete", FIND, {},
             {("crossref", 1): ("exhausted", None), ("doaj", 1): ("exhausted", None)}),
            ("a continuation followed, then the page cap", "find_paged_complete", FIND_PAGED, {"pages": 2},
             {("crossref", 1): ("continuation", {"cursor": "c2"}), ("crossref", 2): ("limit_reached", {"cursor": "c3"}), ("doaj", 1): ("exhausted", None)}),
            ("a continuation, then its page failed", "find_paged_then_failed", FIND_PAGED, {"pages": 2},
             {("crossref", 1): ("continuation", {"cursor": "c2"}), ("crossref", 2): ("failed", None), ("doaj", 1): ("exhausted", None)}),
            ("a lane the gateway could only call a lower bound", "find_partial_records",
             {"request_type": "find", "query": "q", "kind": "article", "lanes": ["crossref"]}, {}, {("crossref", 1): ("end_unknown", None)}),
            ("an answer the gateway did not capture", "find_not_captured", FIND, {},
             {("crossref", 1): ("end_unknown", None), ("doaj", 1): ("failed", None)}),
            ("an unreadable lane beside one that ended", "find_unreadable_lane", FIND, {},
             {("crossref", 1): ("failed", None), ("doaj", 1): ("exhausted", None)}),
            ("a request that does not page", "resolve_from_the_record_cache", RESOLVE, {"exchanges": fixture("resolve_from_the_record_cache")["exchanges"][:1]},
             {("crossref", 1): ("end_unknown", None)}))
        for label, name, request, kw, expected in cases:
            with self.subTest(label):
                self.assertEqual(self.outcomes(search(self, name, request, **kw)), expected)
        with self.subTest("a find's page read whole that says nothing of its end"):
            out, _ = self.one_page()
            self.assertEqual(self.outcomes(out), {("crossref", 1): ("end_unknown", None)}, "no cursor is not an end: the lane has to say it")

    def test_a_page_read_whole_is_not_the_population_exhausted(self):
        """The first page of a continuing lane is complete — read whole, nothing rounded — and says more remains; it is
        the lane's own end, not the page's completeness, that ends the population."""
        pages = by_page(search(self, "find_paged_complete", FIND_PAGED, pages=2))
        for key in (("crossref", 1), ("crossref", 2)):
            self.assertEqual(pages[key]["observation"]["completeness"], "complete")
            self.assertNotEqual(pages[key]["observation"]["page_outcome"], "exhausted")
        self.assertEqual([e["provider_record_id"] for e in pages["crossref", 2]["retrieval_events"]], ["doi:10.1234/def"],
                         "the records read before the cap stand as read")

    def test_gate_d_a_page_with_more_to_read_and_a_finished_one_are_different_records(self):
        """Gate D's probe: with one page asked, a lane answering with a cursor and one reporting its end gave identical client
        outputs and identical router commands. They now differ in the one fact the handoff was dropping."""
        outs = {}
        for label, lane in (("more", {"next": "cursor-for-page-two"}), ("end", {"exhausted": True})):
            outs[label], _ = self.one_page(**lane)
        commands = {k: observe.router_requests(v, capability_id="cap_probe", invocation_id=INV) for k, v in outs.items()}
        self.assertNotEqual(outs["more"], outs["end"])
        self.assertNotEqual(commands["more"], commands["end"])
        got = {k: {f: v["observations"][0]["observation"][f] for f in ("page_outcome", "continuation", "completeness", "result_count")} for k, v in outs.items()}
        self.assertEqual(got, {"more": {"page_outcome": "limit_reached", "continuation": {"cursor": "cursor-for-page-two"}, "completeness": "complete", "result_count": 1},
                               "end": {"page_outcome": "exhausted", "continuation": None, "completeness": "complete", "result_count": 1}})
        self.assertEqual(outs["more"]["observations"][0]["observation"]["observation_id"], outs["end"]["observations"][0]["observation"]["observation_id"],
                         "attempted-request identity is untouched: the same attempt answered another way, which the router refuses as a conflict")

    def test_a_request_that_does_not_page_has_no_end_to_report(self):
        """Astra's 13b contract probe: a resolve, enrich, fetch or data answer whose lane says `exhausted: true` (or hands back a `next`)
        was recorded `exhausted` (or `limit_reached` with a cursor). Such a request has no end to know: its page is `end_unknown`, whatever
        the lane says; the same lane in a find is the control."""
        for kind in ("resolve", "enrich", "fetch", "data"):
            for claim in ({"exhausted": True}, {"exhausted": True, "next": "exhausted"}, {"next": "c2"}, {"next": "c2", "exhausted": True}):
                with self.subTest(kind=kind, claim=claim):
                    sent: list = []
                    c = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(lambda payload: sent.append(payload) or self.lane_answer(**claim)),
                                      clock=lambda: "2026-09-30T10:00:00Z", sleep=lambda s: None)
                    out = c.search({"request_type": kind, "identity": "doi:10.1/a"}, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
                    [only] = out["observations"]
                    self.assertEqual((only["observation"]["completeness"], only["observation"]["page_outcome"], only["observation"]["continuation"]),
                                     ("complete", "end_unknown", None))
                    self.assertEqual(only["observation"]["request"]["request"]["request_type"], kind, "and the observation names the request it answers")
        out, _ = self.one_page(exhausted=True)
        self.assertEqual(self.outcomes(out), {("crossref", 1): ("exhausted", None)}, "the control: a find's lane that says it, in a page read whole")

    def test_a_lane_that_was_not_read_reports_no_end_whatever_it_restates(self):
        """Astra's 13b probe: an unobserved lane marked `coverage: exhausted, exhausted: true` ignored a contradictory malformed `next` and
        persisted `exhausted`, and a plain restatement did too. Nothing was read from it, so nothing ends."""
        for label, extra in (("a restatement", {}), ("a restatement with a malformed next", {"next": ["more"]}), ("a restatement with a cursor", {"next": "c2"}),
                             ("the sentinel", {"next": "exhausted"})):
            with self.subTest(label):
                lane = {"source": "crossref", "coverage": "exhausted", "completeness": "unobserved", "exhausted": True, **extra}
                answer = {"lanes": [lane], "records": [], "observation": {"invocation_id": INV, "attempt": 1, "served": "dispatched", "captured": True, "call_ref": 1}}
                c = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(lambda payload: answer), clock=lambda: "2026-09-30T10:00:00Z", sleep=lambda s: None)
                out = c.search({**FIND, "lanes": ["crossref"]}, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
                self.assertEqual(self.outcomes(out), {("crossref", 1): ("end_unknown", None)})

    def test_a_continuation_outranks_a_reported_end(self):
        out, sent = self.one_page(pages=2, next="c2", exhausted=True)
        self.assertEqual(len(sent), 2, "the cursor is followed")
        self.assertEqual(self.outcomes(out), {("crossref", 1): ("continuation", {"cursor": "c2"}), ("crossref", 2): ("limit_reached", {"cursor": "c2"})})

    def test_an_integer_cursor_keeps_its_type(self):
        out, sent = self.one_page(pages=2, next=20)
        self.assertEqual([p.get("cursors") for p in sent], [None, {"crossref": 20}])
        self.assertEqual(self.outcomes(out), {("crossref", 1): ("continuation", {"cursor": 20}), ("crossref", 2): ("limit_reached", {"cursor": 20})})

    def test_a_continuation_that_cannot_be_used_is_not_an_end_and_not_a_cursor(self):
        """A `next` that is a boolean, a float, empty, too long to keep, negative, a list, or the finished-lane sentinel is no
        cursor: the page's records stand as read, the page is still complete, nothing is asked again — and the end stays unknown
        even beside the lane's own `exhausted`, which a `next` it cannot read contradicts."""
        for bad in (True, 1.5, "", "c" * 8001, -1, ["c2"], {"cursor": "c2"}):
            for ended in (None, True):
                with self.subTest(next=repr(bad)[:20], exhausted=ended):
                    out, sent = self.one_page(pages=3, next=bad, **({"exhausted": True} if ended else {}))
                    self.assertEqual(len(sent), 1)
                    obs = out["observations"][0]["observation"]
                    self.assertEqual((obs["page_outcome"], obs["continuation"], obs["completeness"], obs["result_count"]), ("end_unknown", None, "complete", 1))
        out, sent = self.one_page(pages=3, next="exhausted")   # the sentinel alone is no report of an end
        self.assertEqual((len(sent), out["observations"][0]["observation"]["page_outcome"]), (1, "end_unknown"))
        out, _ = self.one_page(pages=3, next="exhausted", exhausted=True)   # the sentinel with the lane's own report is one
        self.assertEqual(out["observations"][0]["observation"]["page_outcome"], "exhausted")
        out, sent = self.one_page(pages=3, next="c" * 8000)   # control: the longest cursor kept is followed
        self.assertEqual((len(sent), out["observations"][0]["observation"]["page_outcome"]), (3, "continuation"))

    def test_an_end_is_reported_by_a_page_read_whole_only(self):
        """A partial page and an uncaptured one never end the population, whatever the lane said."""
        for label, lane in (("partial", {"completeness": "partial", "error_class": "payload_invalid", "exhausted": True}),):
            with self.subTest(label):
                out, _ = self.one_page(**lane)
                self.assertEqual(self.outcomes(out), {("crossref", 1): ("end_unknown", None)})
        out, _ = self.one_page(exhausted=True)   # control: the same lane read whole ends
        self.assertEqual(self.outcomes(out), {("crossref", 1): ("exhausted", None)})

    def test_a_partial_page_keeps_the_cursor_it_was_handed_without_following_it(self):
        """Not followed, and not a page cap either: the cap is what stops a lane that could go on, and this page is a lower bound
        whatever the cap (the same on the last page the client was asked for as before it)."""
        for pages in (1, 3):
            with self.subTest(pages=pages):
                out, sent = self.one_page(pages=pages, completeness="partial", error_class="payload_invalid", next="c2")
                self.assertEqual(len(sent), 1, "a lower bound never continues (2b-repair A2)")
                obs = out["observations"][0]["observation"]
                self.assertEqual((obs["completeness"], obs["page_outcome"], obs["continuation"]), ("partial", "continuation", {"cursor": "c2"}))

    def test_a_lane_not_searched_and_a_lane_restating_its_end_report_no_end(self):
        def body(payload):
            return {"lanes": [{"source": "crossref", "role": "base", "coverage": "not_searched", "completeness": "unobserved"},
                              {"source": "doaj", "role": "base", "coverage": "exhausted", "completeness": "unobserved", "cursor": "exhausted", "exhausted": True},
                              {"source": "core", "role": "base", "coverage": "exhausted", "completeness": "unobserved"}],
                    "records": [], "observation": {"invocation_id": INV, "attempt": 1, "served": "dispatched", "captured": True, "call_ref": 1}}
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(body), clock=lambda: "2026-09-30T10:00:00Z", sleep=lambda s: None)
        out = c.search({**FIND, "lanes": ["crossref", "doaj", "core"]}, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        self.assertEqual(self.outcomes(out), {("crossref", 1): ("end_unknown", None), ("doaj", 1): ("end_unknown", None), ("core", 1): ("end_unknown", None)},
                         "a page nothing was read from reports no end: not a lane never searched, not one restating an end it reported earlier (that "
                         "earlier page holds it), and not one whose restatement is explicit")


class TransportOutcomes(unittest.TestCase):
    def outcome(self, status, body=None, error=None, headers=None, request=FIND):
        def transport(method, url, hdrs, data, timeout):
            return status, headers or HEADERS, json.dumps(body).encode() if body is not None else b"", error
        clock = VirtualTime()
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=transport, clock=lambda: "2026-09-30T10:00:00Z", deadline=2,
                          sleep=clock.sleep, monotonic=clock.monotonic)
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
        answers, clock = iter(answers), VirtualTime()

        def transport(method, url, hdrs, data, timeout):
            if seen is not None:
                seen.append((method, hdrs.get("X-Research-Invocation"), hdrs.get("X-Research-Attempt")))
            status, body = next(answers)
            return status, HEADERS, json.dumps(body).encode(), None
        return GatewayClient(BASE, ENGINE_TOKEN, transport=transport, clock=lambda: "2026-09-30T10:00:00Z", deadline=2,
                             sleep=clock.sleep, monotonic=clock.monotonic)

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
            self.body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            handler_body(self)

        do_GET = do_POST
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_port}"


def _write(h, resp: dict) -> None:
    raw = json.dumps(resp["body"]).encode()
    h.send_response(resp["status"])
    h.send_header("Content-Type", resp["content_type"])
    h.send_header("X-Research-Gateway", resp["x_research_gateway"])
    h.send_header("Content-Length", str(len(raw)))
    h.end_headers()
    h.wfile.write(raw)


def recorded_answer(name: str, index: int = 0):
    """A loopback answer replaying one recorded response, headers and body as the gateway sent them."""
    return lambda h: _write(h, fixture(name)["exchanges"][index]["response"])


def recorded_in_order(name: str, seen: list):
    """Loopback answers replaying one scenario's recorded responses in order; each request that
    arrives is kept in `seen` as (path, body) for the test to compare with what was recorded."""
    responses = [e["response"] for e in fixture(name)["exchanges"]]

    def answer(h):
        seen.append((h.path, canonical.parse_json_strict(h.body) if h.body else None))
        _write(h, responses[len(seen) - 1])
    return answer


class PollDeadline(unittest.TestCase):
    """Gate D #4 (task 2b-repair-13b): polling a queued job has ONE absolute monotonic deadline. A poll's own time comes out
    of it, each poll's timeout is clamped to what remains, and each sleep is bounded by it. Virtual time: no test waits,
    and every figure is the exact number of (virtual) seconds."""
    CTX = {"token": "synthetic", "invocation_id": INV, "attempt": 1}
    RUNNING = {"x-research-gateway": "result", "content-type": "application/json"}

    def close(self, got: list, want: list, label: str = "") -> None:
        self.assertEqual(len(got), len(want), f"{label}: {got} != {want}")
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, msg=f"{label}: {got} != {want}")

    def poller(self, request_seconds: float, *, deadline: float, timeout: float = 130.0, answers=None):
        """(client, clock, the timeouts its polls were given). A poll takes `request_seconds` and is cut off at its timeout."""
        clock, timeouts, answers = VirtualTime(), [], iter(answers or ())

        def transport(method, url, headers, body, request_timeout):
            timeouts.append(request_timeout)
            if not clock.took(request_seconds, request_timeout):
                return None, {}, b"", "timeout"
            status, doc = next(answers, (200, {"status": "running"}))
            return status, self.RUNNING, json.dumps(doc).encode(), None
        return GatewayClient(BASE, ENGINE_TOKEN, timeout=timeout, deadline=deadline, transport=transport, sleep=clock.sleep,
                             monotonic=clock.monotonic), clock, timeouts

    def test_gate_d_a_slow_gateway_cannot_stretch_one_second_into_three(self):
        """Gate D's probe: deadline 1 s, each poll 0.6 s, timeout 130. The old loop counted only its half-second sleeps — three
        polls, each handed the full 130, 3.3 s in all. Now the first poll is handed the one second there is, and polling stops there."""
        c, clock, timeouts = self.poller(0.6, deadline=1.0)
        self.assertEqual(c._poll(1, self.CTX), (None, None))
        self.close(timeouts, [1.0], "the one poll the deadline allows, clamped to the deadline, not the client's 130")
        self.assertAlmostEqual(clock.now, 1.0)
        self.assertLessEqual(clock.now, 1.0 + 1e-9)

    def test_each_poll_is_clamped_to_what_remains_and_each_sleep_to_the_same(self):
        c, clock, timeouts = self.poller(0.0, deadline=2.0)
        self.assertEqual(c._poll(1, self.CTX), (None, None))
        self.close(timeouts, [2.0, 1.5, 1.0, 0.5])
        self.close(clock.sleeps, [0.5, 0.5, 0.5, 0.5])
        c, clock, timeouts = self.poller(0.0, deadline=0.7)
        c._poll(1, self.CTX)
        self.close(timeouts, [0.7, 0.2])
        self.close(clock.sleeps, [0.5, 0.2], "the last sleep ends at the deadline, not half a second after it")
        c, _, timeouts = self.poller(0.0, deadline=2.0, timeout=0.7)
        c._poll(1, self.CTX)
        self.close(timeouts, [0.7, 0.7, 0.7, 0.5], "a poll is never given more than the client's own timeout either")

    def test_the_defaults_end_within_the_deadline_where_gate_d_counted_about_21_hours(self):
        c, clock, timeouts = self.poller(130.0, deadline=300.0)
        self.assertEqual(c._poll(1, self.CTX), (None, None))
        self.close(timeouts, [130.0, 130.0, 39.0])
        self.assertAlmostEqual(clock.now, 300.0)

    def test_a_deadline_that_passes_is_a_timeout_observation_and_never_an_empty_result(self):
        clock, timeouts = VirtualTime(), []
        queued = TransportOutcomes.QUEUED

        def transport(method, url, headers, body, request_timeout):
            timeouts.append(request_timeout)
            if method == "POST":
                return 202, HEADERS, json.dumps({**queued, "observation": fixture("find_complete")["exchanges"][0]["response"]["body"]["observation"]}).encode(), None
            clock.took(130.0, request_timeout)
            return None, {}, b"", "timeout"   # every poll waits out its timeout
        c = GatewayClient(BASE, ENGINE_TOKEN, deadline=5.0, transport=transport, sleep=clock.sleep, monotonic=clock.monotonic, clock=lambda: "2026-09-30T10:00:00Z")
        out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        self.assertEqual([summary(o) for o in out["observations"]], [("unknown", "unobserved", None, "timeout", [])])
        self.close(timeouts[1:], [5.0], "one poll, given the five seconds there are")
        self.assertAlmostEqual(clock.now, 5.0)

    def test_control_a_job_that_finishes_inside_the_deadline_is_read(self):
        done = {"status": "done", "result": {"lanes": [], "records": []}, "observation": TransportOutcomes.POLLED}
        c, clock, timeouts = self.poller(0.1, deadline=2.0, answers=[(200, {"status": "running"}), (200, {"status": "running"}), (200, done)])
        job, poll = c._poll(7, self.CTX)
        self.assertEqual((job["status"], poll["call_ref"]), ("done", 900))
        self.assertEqual(len(timeouts), 3, "polled until it finished, and no longer")
        self.assertLess(clock.now, 2.0)

    def test_a_reply_that_arrives_inside_its_timeout_and_is_not_the_end_leaves_only_what_remains_to_sleep(self):
        """Final-sleep arithmetic, not a late reply (that is the next test, and test_gateway_exchange's real ones): the reply
        arrives at 0.4 s of a 0.5 s deadline, inside its clamped timeout, and the sleep after it is the 0.1 s that is left."""
        c, clock, timeouts = self.poller(0.4, deadline=0.5)
        self.assertEqual(c._poll(1, self.CTX), (None, None))
        self.close(timeouts, [0.5])
        self.close(clock.sleeps, [0.1])

    def test_a_terminal_reply_that_completes_after_the_deadline_is_a_timeout_whatever_it_says(self):
        """The client's own check, over a transport that breaks the contract it is handed (a fake that honoured the timeout
        could not show it): a `done` that returns after the exchange's whole budget is no result, and neither is a failed job
        or one that is still running. Then the poll is over, and the search says `timeout`, never what the late reply said."""
        for status in ("done", "failed", "running"):
            with self.subTest(status):
                clock = VirtualTime()

                def transport(method, url, headers, body, request_timeout, status=status):
                    clock.now += request_timeout + 0.1   # the reply is in hand 0.1 s after the exchange's whole budget
                    doc = {"status": status, "result": {"lanes": [{"source": "crossref", "coverage": "searched_empty", "completeness": "complete",
                                                                  "count": 0, "retrieved": [], "exhausted": True}], "records": []},
                           "observation": TransportOutcomes.POLLED}
                    return 200, self.RUNNING, json.dumps(doc).encode(), None
                c = GatewayClient(BASE, ENGINE_TOKEN, deadline=2.0, transport=transport, sleep=clock.sleep, monotonic=clock.monotonic)
                self.assertEqual(c._poll(1, self.CTX), (None, None))
                self.assertEqual(sum(clock.sleeps), 0, "no time is waited on a deadline that has passed")

    def test_the_search_whose_poll_answers_after_the_deadline_observes_a_timeout(self):
        clock = VirtualTime()
        done = {"status": "done", "observation": TransportOutcomes.POLLED,
                "result": {"lanes": [{"source": "crossref", "coverage": "searched_empty", "completeness": "complete", "count": 0, "retrieved": [], "exhausted": True}],
                           "records": []}}
        queued = {**TransportOutcomes.QUEUED, "observation": fixture("find_complete")["exchanges"][0]["response"]["body"]["observation"]}

        def transport(method, url, headers, body, request_timeout):
            if method == "POST":
                return 202, HEADERS, json.dumps(queued).encode(), None
            clock.now += request_timeout + 1.0
            return 200, HEADERS, json.dumps(done).encode(), None
        c = GatewayClient(BASE, ENGINE_TOKEN, deadline=5.0, transport=transport, sleep=clock.sleep, monotonic=clock.monotonic, clock=lambda: "2026-09-30T10:00:00Z")
        out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        self.assertEqual([summary(o) for o in out["observations"]], [("unknown", "unobserved", None, "timeout", [])])
        self.assertEqual(out["observations"][0]["observation"]["page_outcome"], "failed")

    def test_a_reply_to_any_exchange_that_outlasts_the_clients_timeout_is_a_timeout(self):
        """The first request's own budget is the client's timeout, and the same check holds it."""
        clock = VirtualTime()

        def transport(method, url, headers, body, request_timeout):
            clock.now += request_timeout + 0.5
            return 200, HEADERS, json.dumps(fixture("find_complete")["exchanges"][0]["response"]["body"]).encode(), None
        c = GatewayClient(BASE, ENGINE_TOKEN, timeout=3.0, transport=transport, sleep=clock.sleep, monotonic=clock.monotonic, clock=lambda: "2026-09-30T10:00:00Z")
        out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
        self.assertEqual({summary(o)[:4] for o in out["observations"]}, {("unknown", "unobserved", None, "timeout")})


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
        self.admissible("find_paged_then_failed", FIND_PAGED, pages=2)
        self.assertEqual(self.observations(), [("crossref", 1, "searched_ok", "complete", 1, None),
                                               ("crossref", 2, "provider_unavailable", "unobserved", None, "provider_outage"),
                                               ("doaj", 1, "searched_empty", "complete", 0, None)])
        self.assertEqual([(json.loads(r)["request"].get("cursors"), ref) for r, ref in self.rows(
                          "SELECT request, gateway_call_ref FROM search_observations WHERE json_extract(request, '$.page') = 2")],
                         [({"crossref": "c2"}, "gw-call:102")], "the durable row keeps the failed page's own cursor and its own call")

    def test_pages_that_all_answer_are_each_admissible(self):
        self.admissible("find_paged_complete", FIND_PAGED, pages=2)
        self.assertEqual(self.rows("SELECT provider_record_id FROM retrieval_events ORDER BY provider_record_id"),
                         [("doi:10.1234/abc",), ("doi:10.1234/def",)])

    def test_how_pagination_ended_is_recorded_with_its_cursor(self):
        """Gate D #3: the durable row says why each page ended or continued, and a page read whole stays complete
        whatever it says of the population."""
        self.admissible("find_paged_complete", FIND_PAGED, pages=2)
        self.assertEqual(self.rows("SELECT lane, json_extract(request, '$.page'), completeness, page_outcome, continuation FROM search_observations "
                                   "ORDER BY lane, json_extract(request, '$.page')"),
                         [("crossref", 1, "complete", "continuation", '{"cursor":"c2"}'), ("crossref", 2, "complete", "limit_reached", '{"cursor":"c3"}'),
                          ("doaj", 1, "complete", "exhausted", None)])
        self.assertEqual(self.rows("SELECT json_extract(request, '$.request.cursors.crossref'), json_extract(continuation, '$.cursor') FROM search_observations "
                                   "WHERE lane = 'crossref' ORDER BY json_extract(request, '$.page')"),
                         [(None, "c2"), ("c2", "c3")], "each continuation is the cursor the next page was asked with")

    def test_a_request_that_does_not_page_is_recorded_with_its_type_and_no_end(self):
        """The client's output for each request type is admitted by the router and the store (the admission contract: gen2/router/boundary.py),
        its type in the row, and a lane's claim of an end for a request that does not page stays an unknown one."""
        kinds = ("resolve", "enrich", "fetch", "data")
        for kind in kinds:
            c = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(lambda payload: PageOutcomes.lane_answer(exhausted=True)),
                              clock=lambda: "2026-09-30T10:00:00Z", sleep=lambda s: None)
            out = c.search({"request_type": kind, "identity": "doi:10.1/a"}, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
            self.assertEqual([r["status"] for r in self.record(out)], ["recorded"], kind)
        self.assertEqual(sorted(self.rows("SELECT json_extract(request, '$.request.request_type'), page_outcome, completeness, gateway_call_ref FROM search_observations")),
                         sorted((kind, "end_unknown", "complete", "gw-call:1") for kind in kinds))

    def test_a_failed_page_is_recorded_failed_and_a_lower_bound_end_unknown(self):
        self.admissible("find_paged_then_failed", FIND_PAGED, pages=2)
        self.admissible("find_not_captured")
        self.assertEqual(self.rows("SELECT lane, json_extract(request, '$.page'), coverage_state, page_outcome, continuation FROM search_observations "
                                   "WHERE invocation_id = ? ORDER BY lane, json_extract(request, '$.page'), page_outcome", INV),
                         [("crossref", 1, "searched_ok", "continuation", '{"cursor":"c2"}'), ("crossref", 1, "searched_ok", "end_unknown", None),
                          ("crossref", 2, "provider_unavailable", "failed", None), ("doaj", 1, "searched_empty", "exhausted", None),
                          ("doaj", 1, "unknown", "failed", None)])

    def test_the_same_attempt_answered_with_another_end_is_a_conflict_not_a_second_observation(self):
        """Gate D's probe through the router: one attempt that said `more remains` cannot later say `finished`."""
        more, end = (self.client_for(lane) for lane in ({"next": "c2"}, {"exhausted": True}))
        self.assertEqual([r["status"] for r in self.record(more)], ["recorded"])
        self.assertEqual([r["status"] for r in self.record(more)], ["replayed"])
        refused = self.record(end)
        self.assertEqual((refused[0]["status"], refused[0].get("reason")), ("refused", "observation_id_conflict"))
        self.assertEqual(self.value("SELECT count(*) FROM search_observations"), 1)

    def test_linkage_suggestions_are_neither_equivalence_nor_a_denominator(self):
        """The 2b-repair-13a review's acceptance condition for this handoff: the gateway reports candidates that merely look alike in
        an optional top-level `linkage_suggestions` list, for a later governed assessment. The engine keeps the distinct candidates
        and their raw retrieved identities as retrieved; a suggestion changes no observation, no count, no event and no record,
        reaches no router command, and registers no work (equivalence is a recorded assessment, never a retrieval helper's)."""
        ids = ["doi:10.1000/a", "doi:10.1000/b"]
        suggestion = {"type": "possible_same_work", "identities": ids, "basis": ["same kind, year and first-author surname; similar title"],
                      "differing_identifiers": ["doi"], "provenance": [{"source_id": "crossref"}], "disposition": "unassessed"}

        def answer(with_suggestions: bool) -> dict:
            body = {"lanes": [{"source": "crossref", "role": "base", "coverage": "searched_ok", "completeness": "complete", "count": 2, "retrieved": ids,
                               "exhausted": True}],
                    "records": [{"identity": i, "kind": "article", "source_id": "crossref", "title": "Annual survey", "year": 2021} for i in ids],
                    "observation": {"invocation_id": INV, "attempt": 1, "served": "dispatched", "captured": True, "call_ref": 1}}
            return {**body, "linkage_suggestions": [suggestion]} if with_suggestions else body
        outs = []
        for with_suggestions in (False, True):
            c = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(lambda payload, b=answer(with_suggestions): b), clock=lambda: "2026-09-30T10:00:00Z",
                              sleep=lambda s: None)
            outs.append(c.search({**FIND, "lanes": ["crossref"]}, invocation_id=INV, attempt=1, policy_version="gw-policy/1"))
        self.assertEqual(outs[0], outs[1], "a suggestion changes nothing the client returns")
        commands = observe.router_requests(outs[1], capability_id=self.grant["capability_id"], invocation_id=INV)
        self.assertNotIn("linkage", json.dumps(commands), "and nothing of it reaches the router")
        observation = outs[1]["observations"][0]
        self.assertEqual((observation["observation"]["result_count"], [e["provider_record_id"] for e in observation["retrieval_events"]],
                          [r["identity"] for r in observation["records"]]), (2, ids, ids), "two distinct candidates, as retrieved")
        self.assertEqual([r["status"] for r in self.record(outs[1])], ["recorded"])
        self.assertEqual(self.rows("SELECT provider_record_id FROM retrieval_events ORDER BY provider_record_id"), [(i,) for i in ids])
        self.assertEqual((self.value("SELECT count(*) FROM works"), self.value("SELECT count(*) FROM record_work_links")), (0, 0))

    def client_for(self, lane: dict) -> dict:
        answer = PageOutcomes.lane_answer(**lane)
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(lambda payload: answer), clock=lambda: "2026-09-30T10:00:00Z", sleep=lambda s: None)
        return c.search({**FIND, "lanes": ["crossref"]}, invocation_id=INV, attempt=1, policy_version="gw-policy/1", pages=1)

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

    def test_a_lane_is_paged_to_its_reported_end_and_a_lower_bound_never_continues(self):
        """2b-repair-6 F3, the engine half: the gateway's local-index pages (offset 2, offset 4, then
        the page holding what was left, exhausted) are each asked and each recorded whole; a lane
        the gateway could only call a lower bound (`partial_pagination`: records, no continuation,
        no reported end) is recorded partial and never asked again. Answers stated by hand."""
        venues = [f"issn:0000-000{n}" for n in range(5)]
        observation = {"invocation_id": INV, "attempt": 1, "served": "dispatched", "captured": True}

        def page(ids, call_ref, **lane):
            return {"lanes": [{"source": "openalex_snapshot", "role": "base", "coverage": "searched_ok", "completeness": "complete",
                               "count": len(ids), "retrieved": ids, **lane}],
                    "records": [{"identity": i, "kind": "venue", "source_id": "openalex_snapshot"} for i in ids],
                    "observation": {**observation, "call_ref": call_ref}}
        pages = {None: page(venues[:2], 1, next=2), 2: page(venues[2:4], 2, cursor=2, next=4),
                 4: page(venues[4:], 3, cursor=4, exhausted=True)}
        sent = []

        def body_of(payload):
            sent.append(payload)
            return pages[(payload.get("cursors") or {}).get("openalex_snapshot")]
        request = {"request_type": "find", "query": "q", "kind": "venue", "limit": 2}
        out = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(body_of), clock=lambda: "2026-09-30T10:00:00Z").search(
            request, invocation_id=INV, attempt=1, policy_version="gw-policy/1", pages=5)
        self.assertEqual([(p.get("cursors"), p.get("lanes")) for p in sent],
                         [(None, None), ({"openalex_snapshot": 2}, ["openalex_snapshot"]), ({"openalex_snapshot": 4}, ["openalex_snapshot"])],
                         "asked until the gateway said the lane ended, not until its pages ran out")
        self.assertEqual([r["status"] for r in self.record(out)], ["recorded"] * 3)
        self.assertEqual(self.observations(), [("openalex_snapshot", 1, "searched_ok", "complete", 2, None),
                                               ("openalex_snapshot", 2, "searched_ok", "complete", 2, None),
                                               ("openalex_snapshot", 3, "searched_ok", "complete", 1, None)])
        self.assertEqual(sorted(i for (i,) in self.rows("SELECT provider_record_id FROM retrieval_events")), venues)
        lower = {"lanes": [{"source": "kaggle", "role": "base", "coverage": "searched_ok", "completeness": "partial", "count": 2,
                            "retrieved": ["kaggle:a/b", "kaggle:c/d"], "error_class": "partial_pagination"}],
                 "records": [], "observation": {**observation, "call_ref": 4}}
        sent.clear()
        out = GatewayClient(BASE, ENGINE_TOKEN, transport=answering(lambda payload: sent.append(payload) or lower),
                            clock=lambda: "2026-09-30T10:00:00Z").search({**request, "kind": "dataset"}, invocation_id=INV, attempt=1,
                                                                        policy_version="gw-policy/1", pages=5)
        self.assertEqual((len(sent), [r["status"] for r in self.record(out)]), (1, ["recorded"]))
        self.assertEqual(self.rows("SELECT completeness, result_count, error_class FROM search_observations WHERE lane = 'kaggle'"),
                         [("partial", 2, "partial_pagination")], "a lower bound, kept as one")

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

    def test_an_outage_that_widens_is_recorded_snapshot_by_snapshot(self):
        """2b-repair-2 R2: ONE Vault outage the real gateway answered three times (fixture
        data_secrets_outage_widens, replayed in order over a real socket) — FRED fails, GovInfo
        joins the same outage, Vault then fails another way. Each answer is recorded through the
        router's own commands: each snapshot of the one episode supersedes the last and keeps its
        onset, and each observation names the snapshot it was answered with — never a stale one."""
        seen = []
        c = GatewayClient(serve(self, recorded_in_order("data_secrets_outage_widens", seen)), ENGINE_TOKEN, transport=http_transport)
        requests = ({"request_type": "data", "source": "fred", "params": {"series": "GDP"}},
                    {"request_type": "find", "query": "appropriations", "kind": "dataset", "lanes": ["govinfo"]},
                    {"request_type": "data", "source": "fred", "params": {"series": "UNRATE"}})
        outs = [c.search(r, invocation_id=INV, attempt=1, policy_version="gw-policy/1") for r in requests]
        self.assertEqual(seen, [(e["request"]["path"], e["request"]["body"]) for e in fixture("data_secrets_outage_widens")["exchanges"]])
        replies = [self.record(out) for out in outs]
        self.assertEqual([[r["status"] for r in rs] for rs in replies], [["recorded", "recorded"]] * 3, "every answer is recorded, fact then observation")
        ids = [out["capability_facts"][0]["fact_id"] for out in outs]
        since = "2026-09-21T19:47:00Z"
        self.assertEqual([(*r[:4], json.loads(r[4]), r[5]) for r in self.rows(
            "SELECT fact_id, state, since, detail, affected_lanes, superseded_by_fact_id FROM capability_facts WHERE capability = 'gateway.secrets.vault'")],
            [(ids[0], "failing", since, "403", ["fred"], ids[1]), (ids[1], "failing", since, "403", ["fred", "govinfo"], ids[2]),
             (ids[2], "failing", since, "503", ["fred", "govinfo"], None)], "one onset; each snapshot kept, the last current")
        self.assertEqual([(lane, detail, json.loads(lanes)) for lane, detail, lanes in self.rows(
            "SELECT o.lane, f.detail, f.affected_lanes FROM search_observations o JOIN capability_facts f ON f.fact_id = o.capability_fact_id "
            "ORDER BY o.rowid")],
            [("fred", "403", ["fred"]), ("govinfo", "403", ["fred", "govinfo"]), ("fred", "503", ["fred", "govinfo"])],
            "each observation names the snapshot it was answered with")
        self.assertEqual([r["status"] for r in self.record(outs[1])], ["replayed", "replayed"], "an answer recorded again replays")
        self.assertEqual(self.value("SELECT fact_id FROM capability_facts WHERE capability = 'gateway.secrets.vault' AND superseded_by_fact_id IS NULL"),
                         ids[2], "and moves nothing")

    def current(self, router=None) -> list[tuple]:
        """The operator's current secrets fact (router status), as (fact_id, detail, lanes)."""
        return [(f["fact_id"], f["detail"], f["affected_lanes"]) for f in (router or self.router).status({})["capability_facts"]
                if f["capability"] == "gateway.secrets.vault"]

    def test_an_outage_that_says_again_what_it_said_before_is_current_as_said_last(self):
        """2b-repair-3 R2, Astra's reproduction 2 (no race): ONE invocation, each answer recorded
        before the next is asked — FRED 403, GovInfo joins, a fresh FRED read 503, then a fresh
        GovInfo read 403 again (fixture data_secrets_outage_recurs, the real gateway's answers,
        replayed in order over a real socket). The fourth answer says what the second said, but
        is a new gateway call and a later snapshot: its fact is recorded, not replayed as the
        second, and the operator's current fact is the fourth — after every answer, the latest."""
        seen = []
        c = GatewayClient(serve(self, recorded_in_order("data_secrets_outage_recurs", seen)), ENGINE_TOKEN, transport=http_transport)
        requests = ({"request_type": "data", "source": "fred", "params": {"series": "GDP"}},
                    {"request_type": "find", "query": "appropriations", "kind": "dataset", "lanes": ["govinfo"]},
                    {"request_type": "data", "source": "fred", "params": {"series": "UNRATE"}},
                    {"request_type": "find", "query": "budget after 503", "kind": "dataset", "lanes": ["govinfo"]})
        outs, replies, current = [], [], []
        for request in requests:
            outs.append(c.search(request, invocation_id=INV, attempt=1, policy_version="gw-policy/1"))
            replies.append(self.record(outs[-1]))
            current.append(self.current())
        self.assertEqual(seen, [(e["request"]["path"], e["request"]["body"]) for e in fixture("data_secrets_outage_recurs")["exchanges"]])
        ids = [out["capability_facts"][0]["fact_id"] for out in outs]
        wide = ["fred", "govinfo"]
        self.assertEqual(current, [[(ids[0], "403", ["fred"])], [(ids[1], "403", wide)], [(ids[2], "503", wide)], [(ids[3], "403", wide)]],
                         "the operator's current fact is the latest answer's, after each")
        self.assertEqual([[r["status"] for r in rs] for rs in replies], [["recorded", "recorded"]] * 4,
                         "the fourth answer's fact is recorded, never replayed as the second")
        self.assertEqual(len(set(ids)), 4, "four snapshots, though the fourth says what the second said")
        self.assertEqual(self.rows("SELECT o.lane, f.fact_id, f.detail FROM search_observations o JOIN capability_facts f "
                                   "ON f.fact_id = o.capability_fact_id ORDER BY o.rowid"),
                         [("fred", ids[0], "403"), ("govinfo", ids[1], "403"), ("fred", ids[2], "503"), ("govinfo", ids[3], "403")],
                         "each observation names the snapshot it was answered with")
        self.assertEqual([[r["status"] for r in self.record(outs[i])] for i in (1, 2)], [["replayed", "replayed"]] * 2,
                         "an earlier answer recorded again replays")
        self.assertEqual(self.current(), [(ids[3], "403", wide)], "and moves nothing")

    def test_a_report_recorded_after_a_newer_one_never_displaces_it(self):
        """2b-repair-3 R2, Astra's reproduction 1: two invocations of two topics are answered
        from one Vault outage — A's FRED read first (the narrow snapshot), then B's GovInfo read
        (the wider one); fixture data_secrets_outage_two_invocations. Two recorder processes
        open one durable store; A's is held until B's has committed. B's snapshot stays current
        after A's delayed write, which is kept behind it for A's observation to name; B's exact
        redelivery replays, and B's fresh GovInfo answer — the same snapshot again — keeps the
        wider fact current."""
        self.to_scoping(OTHER)
        grant_b = self.started(INV_B, "discovery", tid=OTHER)
        seen = []
        c = GatewayClient(serve(self, recorded_in_order("data_secrets_outage_two_invocations", seen)), ENGINE_TOKEN, transport=http_transport)
        narrow = c.search({"request_type": "data", "source": "fred", "params": {"series": "GDP"}}, invocation_id=INV, attempt=1,
                          policy_version="gw-policy/1")
        wider = c.search({"request_type": "find", "query": "appropriations", "kind": "dataset", "lanes": ["govinfo"]}, invocation_id=INV_B,
                         attempt=1, policy_version="gw-policy/1")
        fresh = c.search({"request_type": "find", "query": "budget", "kind": "dataset", "lanes": ["govinfo"]}, invocation_id=INV_B,
                         attempt=1, policy_version="gw-policy/1")
        self.assertEqual(seen, [(e["request"]["path"], e["request"]["body"]) for e in fixture("data_secrets_outage_two_invocations")["exchanges"]])
        a, b = narrow["capability_facts"][0]["fact_id"], wider["capability_facts"][0]["fact_id"]
        self.assertEqual(fresh["capability_facts"][0]["fact_id"], b, "the fresh read changed nothing: the same snapshot")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = str(Path(tmp.name) / "engine.sqlite")
        disk = sqlite3.connect(path)
        self.db.backup(disk)
        disk.close()
        now = self.clock()
        workers = []
        for grant, out in ((self.grant, narrow), (grant_b, wider)):
            job = Path(tmp.name) / f"{grant['invocation_id']}.json"
            job.write_text(json.dumps({"db": path, "now": now, "out": out, "capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"]}))
            # both are started, and each reaped when the test ends, before either is waited on; a recorder that does not say `ready` within
            # the bound fails the test with its exit status and stderr (2b-repair-13d: the unexplained startup failure was an empty
            # first line, a recorder that had died in open_store, and the test kept nothing of why)
            workers.append(children.started(self, ["-c", RECORDER, str(job)], stdin=subprocess.PIPE))
        for worker in workers:
            children.await_line(self, worker, "ready", wait=30)
        replies = {}
        for label, worker in (("wider first", workers[1]), ("narrow delayed", workers[0])):
            stdout, stderr = worker.communicate("go\n", timeout=60)
            self.assertEqual(worker.returncode, 0, stderr)
            replies[label] = [r["status"] for r in json.loads(stdout)]
        self.assertEqual(replies, {"wider first": ["recorded", "recorded"], "narrow delayed": ["recorded", "recorded"]})
        read = sqlite3.connect(path)
        self.addCleanup(read.close)
        with api.open_store(path) as store:
            router = Router(store, None, clock=self.clock)
            wide = ["fred", "govinfo"]
            self.assertEqual(self.current(router), [(b, "403", wide)], "the delayed narrower snapshot does not displace the newer one")
            joined = "SELECT o.invocation_id, o.lane, o.capability_fact_id FROM search_observations o ORDER BY o.rowid"
            self.assertEqual(read.execute("SELECT fact_id, superseded_by_fact_id FROM capability_facts WHERE capability = 'gateway.secrets.vault' "
                                          "ORDER BY rowid").fetchall(), [(b, None), (a, b)], "the delayed snapshot is kept, behind")
            self.assertEqual(read.execute(joined).fetchall(), [(INV_B, "govinfo", b), (INV, "fred", a)], "each observation names its own")
            who = {"capability_id": grant_b["capability_id"], "invocation_id": INV_B}
            again = [getattr(router, cmd)(req) for cmd, req in observe.router_requests(wider, **who)]
            self.assertEqual([r["status"] for r in again], ["replayed", "replayed"], "B's exact redelivery replays")
            self.assertEqual(self.current(router), [(b, "403", wide)])
            later = [getattr(router, cmd)(req) for cmd, req in observe.router_requests(fresh, **who)]
            self.assertEqual([r["status"] for r in later], ["replayed", "recorded"], "the same snapshot again; a new observation")
            self.assertEqual(self.current(router), [(b, "403", wide)], "the wider fact stays current")
            self.assertEqual(read.execute(joined).fetchall(), [(INV_B, "govinfo", b), (INV, "fred", a), (INV_B, "govinfo", b)])

    def test_pages_answered_under_two_snapshots_record_each_in_page_order(self):
        """2b-repair-2 R2: a search whose pages were answered under two snapshots of one outage is
        two fact commands in page order (a command holds one fact per capability), each page's
        observation naming its own. Input: the recorded paged answer, a lane of page 1 and the
        continuation of page 2 failing on secrets as the gateway answers it (the lanes and facts of
        data_secrets_outage_widens)."""
        paged, outage = fixture("find_paged_complete")["exchanges"], fixture("data_secrets_outage_widens")["exchanges"]
        exchanges = copy.deepcopy(paged)
        one, two = (e["response"]["body"] for e in exchanges)
        one["lanes"].append(outage[1]["response"]["body"]["lanes"][0])
        one["capability_facts"] = outage[1]["response"]["body"]["capability_facts"]
        two["lanes"] = [{**outage[2]["response"]["body"]["lanes"][0], "source": "crossref", "role": "base", "cursor": "c2"}]
        two["capability_facts"] = outage[2]["response"]["body"]["capability_facts"]
        two["records"] = []
        out = search(self, "find_paged_complete", FIND_PAGED, exchanges=exchanges, pages=2)
        requests = observe.router_requests(out, capability_id=self.grant["capability_id"], invocation_id=INV)
        self.assertEqual([[(f["detail"], f["affected_lanes"]) for f in r["facts"]] for c, r in requests if c == "record_gateway_facts"],
                         [[("403", ["fred", "govinfo"])], [("503", ["fred", "govinfo"])]], "one command per snapshot, in page order")
        self.assertEqual([r["status"] for r in self.record(out)], ["recorded"] * 6, "two fact commands, then four observations")
        self.assertEqual(self.rows("SELECT o.lane, json_extract(o.request, '$.page'), f.detail FROM search_observations o "
                                   "LEFT JOIN capability_facts f ON f.fact_id = o.capability_fact_id ORDER BY o.rowid"),
                         [("crossref", 1, None), ("doaj", 1, None), ("govinfo", 1, "403"), ("crossref", 2, "503")])

    def test_an_observation_naming_an_unrecorded_fact_is_refused(self):
        out = search(self, "data_secrets_failing", {"request_type": "data", "source": "fred", "params": {"series": "GDP"}})
        (obs,) = out["observations"]
        reply = self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": INV,
                                                "observation": obs["observation"], "retrieval_events": obs["retrieval_events"]})
        self.assertEqual(reply["status"], "refused", "the fact is recorded first (router_requests' order)")


RECORDER = """import json, sys
from gen2.gateway_client import observe
from gen2.router.service import Router
from gen2.store import api
job = json.loads(open(sys.argv[1]).read())
with api.open_store(job["db"]) as store:
    router = Router(store, None, clock=lambda: job["now"])
    print("ready", flush=True)
    sys.stdin.readline()
    who = {"capability_id": job["capability_id"], "invocation_id": job["invocation_id"]}
    print(json.dumps([getattr(router, cmd)(req) for cmd, req in observe.router_requests(job["out"], **who)]), flush=True)
"""   # one recorder process: it opens the durable store, waits for its turn, records one search


class GatewayFactsCommand(RouterTestCase):
    """record_gateway_facts (2b-repair A6): the router's typed, bounded path for the facts the
    gateway reports. Oracle: the rules stated in gen2/router/capabilities.py, by hand."""

    SINCE = "2026-09-21T19:47:00Z"

    def setUp(self) -> None:
        super().setUp()
        self.to_scoping()
        self.grant = self.started(INV, "discovery")

    def fact(self, since: str = SINCE, **over) -> dict:
        doc = {"capability": "gateway.secrets.vault", "state": "failing", "revision": 1, "detail": "403", "since": since, "last_success_at": None,
               "affected_lanes": ["fred"], **over}
        return {"fact_id": canonical.gateway_fact_id(doc), **doc}

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
                 ("a state outside the vocabulary", self.fact(state="broken")),
                 ("an id naming other content", {**self.fact(), "detail": "other"}),
                 ("no revision", {k: v for k, v in self.fact().items() if k != "revision"}),
                 ("a revision below one", self.fact(revision=0)),
                 ("a revision that is no integer", self.fact(revision=1.5)))
        for label, fact in cases:
            with self.subTest(label):
                self.assertEqual(self.put(fact).get("reason"), "request_invalid")
        self.assertEqual(self.put(self.fact(), self.fact(detail="again")).get("reason"), "request_invalid", "one fact per capability")
        self.put(self.fact())
        self.assertEqual(self.put(self.fact(state="degraded", revision=2)).get("reason"), "fact_conflict", "another state since the same instant")
        self.assertEqual(self.put(self.fact(detail="503")).get("reason"), "fact_conflict", "one revision of the episode, other contents")
        self.assertEqual(self.value("SELECT count(*) FROM capability_facts WHERE capability LIKE 'gateway.%'"), 1)

    def test_a_later_snapshot_of_the_episode_supersedes_it_and_keeps_its_onset(self):
        """2b-repair-2 R2: an ongoing outage that widens, then fails another way, is three
        snapshots of one episode — each recorded, superseding the last, `since` kept; the lanes
        are a set; an earlier snapshot recorded again replays and moves nothing."""
        first, wider, other = self.fact(), self.fact(affected_lanes=["fred", "govinfo"], revision=2), self.fact(affected_lanes=["fred", "govinfo"], detail="503", revision=3)
        self.assertEqual([self.put(f)["status"] for f in (first, wider, other)], ["recorded"] * 3)
        self.assertEqual(self.rows("SELECT fact_id, since, superseded_by_fact_id FROM capability_facts WHERE capability = 'gateway.secrets.vault' "
                                   "ORDER BY rowid"),
                         [(first["fact_id"], self.SINCE, wider["fact_id"]), (wider["fact_id"], self.SINCE, other["fact_id"]),
                          (other["fact_id"], self.SINCE, None)])
        self.assertEqual(self.put(self.fact(affected_lanes=["govinfo", "fred"], revision=2))["status"], "replayed", "the same lanes in another order")
        self.assertEqual(self.current(), [(other["fact_id"], "failing", self.SINCE)])

    def test_an_earlier_revision_recorded_late_is_kept_behind_the_current_fact(self):
        """2b-repair-3 R2: the episode's snapshots are ordered by their revision, not by when the
        router hears of them. Revision 2 recorded after revision 3 is kept (its observation names
        it) behind the current fact, which stays current and replays as it was; revision 4,
        saying again what revision 2 said, is the next snapshot and becomes current."""
        one, two, three = self.fact(), self.fact(affected_lanes=["fred", "govinfo"], revision=2), self.fact(affected_lanes=["fred", "govinfo"], detail="503", revision=3)
        self.assertEqual([self.put(f)["status"] for f in (one, three, two)], ["recorded"] * 3)
        self.assertEqual(self.current(), [(three["fact_id"], "failing", self.SINCE)], "the newest revision is current")
        self.assertEqual(self.put(two)["status"], "replayed")
        four = self.fact(affected_lanes=["fred", "govinfo"], revision=4)
        self.assertEqual(self.put(four)["status"], "recorded", "what revision 2 said, said later")
        self.assertEqual(self.rows("SELECT fact_id, since, superseded_by_fact_id FROM capability_facts WHERE capability = 'gateway.secrets.vault' "
                                   "ORDER BY rowid"),
                         [(one["fact_id"], self.SINCE, three["fact_id"]), (three["fact_id"], self.SINCE, four["fact_id"]),
                          (two["fact_id"], self.SINCE, three["fact_id"]), (four["fact_id"], self.SINCE, None)])

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
