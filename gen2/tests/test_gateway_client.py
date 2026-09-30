"""The engine's gateway client (task 2b; gen2/gateway_client; BOUNDARIES.md Gateway).

Oracle: the gateway's own recorded answers (gen2/tests/fixtures/gateway_answers/, written
and re-verified against the real service by gateway/tests/test_engine_fixtures.py). A
replaying transport checks the client sends exactly the requests the gateway was asked —
method, path, body, correlation headers, which credential — and hands back the recorded
answers; the resulting observations are then recorded through a real router
(record_observation) so what 2c/2d consume is known to be admissible, not just
well-shaped. Negatives mutate a recorded answer one property at a time (each paired with
the unmutated answer as its control), or replace the transport's outcome.

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


def search(test, name, request=FIND, **kw):
    c, replay = client(test, fixture(name)["exchanges"])
    out = c.search(request, invocation_id=INV, attempt=1, policy_version="gw-policy/1", **kw)
    test.assertEqual(replay.exchanges, [], "every recorded exchange was asked for")
    return out


def by_lane(out) -> dict:
    return {o["observation"]["lane"]: o for o in out["observations"]}


def summary(obs) -> tuple:
    o = obs["observation"]
    return (o["coverage_state"], o["completeness"], o["result_count"], o["error_class"],
            [e["provider_record_id"] for e in obs["retrieval_events"]])


class RecordedAnswers(unittest.TestCase):
    def test_a_complete_answer_is_one_observation_per_lane(self):
        out = search(self, "find_complete")
        lanes = by_lane(out)
        self.assertEqual(summary(lanes["crossref"]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))
        self.assertEqual(summary(lanes["doaj"]), ("searched_empty", "complete", 0, None, []))
        for obs in lanes.values():
            o = obs["observation"]
            self.assertEqual(o["request_identity"], canonical.logical_hash(o["request"]), "H-5: the identity is the request's hash")
            self.assertEqual((o["attempt"], o["policy_version"], o["gateway_call_ref"], o["cost_units"]), (1, "gw-policy/1", "gw-call:101", None))
            self.assertEqual(o["request"]["gateway_request_identity"], out["gateway_request_identity"])
            self.assertEqual(o["request"]["delivery"]["served"], "dispatched")
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

    def test_an_uncaptured_request_is_an_explicit_telemetry_loss(self):
        out = search(self, "find_not_captured")
        self.assertEqual(out["telemetry_losses"], [{"reason": "no durable call log: this gateway runs without a database",
                                                    "invocation_id": INV, "attempt": 1}])
        self.assertTrue(all(o["observation"]["gateway_call_ref"] is None for o in out["observations"]))
        self.assertEqual(summary(by_lane(out)["crossref"])[:3], ("searched_ok", "complete", 1), "what the engine read still stands")

    def test_an_unreadable_lane_is_never_zero(self):
        lanes = by_lane(search(self, "find_unreadable_lane"))
        self.assertEqual(summary(lanes["crossref"]), ("provider_unavailable", "unobserved", None, "payload_invalid", []))
        self.assertEqual(summary(lanes["doaj"]), ("searched_empty", "complete", 0, None, []))

    def test_dropped_records_are_a_lower_bound(self):
        lanes = by_lane(search(self, "find_partial_records", {"request_type": "find", "query": "q", "kind": "article", "lanes": ["stub"]}))
        self.assertEqual(summary(lanes["stub"]), ("searched_ok", "partial", 2, "payload_invalid", ["doi:10.1234/p1", "doi:10.1234/p2"]))

    def test_a_failed_continuation_page_leaves_a_lower_bound(self):
        lanes = by_lane(search(self, "find_paged_then_failed", pages=2))
        self.assertEqual(summary(lanes["crossref"]), ("searched_ok", "partial", 1, "partial_pagination", ["doi:10.1234/abc"]),
                         "one record read, the provider claimed three: the count is what was read, never rounded up")
        self.assertEqual(lanes["crossref"]["observation"]["gateway_call_ref"], "gw-call:101,gw-call:102")
        self.assertEqual(summary(lanes["doaj"]), ("searched_empty", "complete", 0, None, []), "a finished lane is not asked again")
        self.assertEqual(lanes["crossref"]["observation"]["request"]["pages"], 2)

    def test_pages_that_all_answer_are_one_complete_observation(self):
        lanes = by_lane(search(self, "find_paged_complete", pages=2))
        self.assertEqual(summary(lanes["crossref"]), ("searched_ok", "complete", 2, None, ["doi:10.1234/abc", "doi:10.1234/def"]))
        self.assertEqual(summary(lanes["doaj"]), ("searched_empty", "complete", 0, None, []))

    def test_control_one_page_of_the_same_answer_is_complete(self):
        c, _ = client(self, fixture("find_paged_then_failed")["exchanges"][:1])
        lanes = by_lane(c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1"))
        self.assertEqual(summary(lanes["crossref"]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))

    def test_a_failing_secrets_read_carries_its_fact_and_no_count(self):
        out = search(self, "data_secrets_failing", {"request_type": "data", "source": "fred", "params": {"series": "GDP"}})
        (fact,) = out["capability_facts"]
        self.assertEqual({k: fact[k] for k in ("capability", "state", "since", "last_success_at", "affected_lanes", "detail")},
                         {"capability": "gateway.secrets.vault", "state": "failing", "since": "2026-09-21T19:47:00Z",
                          "last_success_at": None, "affected_lanes": ["fred"], "detail": "403"})
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
        for field, value in (("invocation_id", "inv_someone_else"), ("attempt", 2)):
            with self.subTest(field):
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
                              ("no lanes", lambda r: r["body"].pop("lanes"))):
            with self.subTest(label):
                lanes = self.lanes_of(mutated("find_complete", 0, mutate))
                self.assertEqual([summary(o) for o in lanes.values()], [("unknown", "unobserved", None, "payload_invalid", [])])

    def test_a_repeated_identity_is_one_candidate(self):
        def repeat(r):
            lane = r["body"]["lanes"][0]
            lane["retrieved"] *= 2
            lane["count"] = 2
        self.assertEqual(summary(self.lanes_of(mutated("find_complete", 0, repeat))["crossref"]),
                         ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))

    def test_metadata_only_with_nothing_returned_is_an_empty_query(self):
        def fulltext_empty(r):
            r["body"]["lanes"][1]["coverage"] = "metadata_only"
        self.assertEqual(summary(self.lanes_of(mutated("find_complete", 0, fulltext_empty))["doaj"]),
                         ("searched_empty", "complete", 0, None, []))


class TransportOutcomes(unittest.TestCase):
    def outcome(self, status, body=None, error=None, headers=None, request=FIND):
        def transport(method, url, hdrs, data, timeout):
            return status, headers or {"content-type": "application/json", "x-research-gateway": "result"}, \
                json.dumps(body).encode() if body is not None else b"", error
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

    def queued_client(self, answers) -> GatewayClient:
        answers = iter(answers)

        def transport(method, url, hdrs, data, timeout):
            status, body = next(answers)
            return status, {"content-type": "application/json", "x-research-gateway": "result"}, json.dumps(body).encode(), None
        return GatewayClient(BASE, ENGINE_TOKEN, transport=transport, clock=lambda: "2026-09-30T10:00:00Z", sleep=lambda s: None, deadline=2)

    def test_a_queued_answer_is_polled_to_its_result(self):
        done = fixture("find_complete")["exchanges"][0]["response"]["body"]
        queued = {**self.QUEUED, "observation": done["observation"]}
        c = self.queued_client([(202, queued), (200, {"status": "running"}), (200, {"status": "done", "result": done})])
        lanes = by_lane(c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1"))
        self.assertIn("crossref", lanes, "the polled job's lanes, not the queued answer's (which has none)")
        self.assertEqual(summary(lanes["crossref"]), ("searched_ok", "complete", 1, None, ["doi:10.1234/abc"]))

    def test_a_queued_answer_is_polled_and_a_job_that_never_ends_is_a_timeout(self):
        done = fixture("find_complete")["exchanges"][0]["response"]["body"]
        queued = {**self.QUEUED, "observation": done["observation"]}
        for final, expected in (({"status": "running"}, "timeout"), ({"status": "failed", "result": {}}, "transport_failure")):
            with self.subTest(final=final):
                c = self.queued_client([(202, queued)] + [(200, final)] * 10)
                out = c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
                self.assertEqual([summary(o) for o in out["observations"]], [("unknown", "unobserved", None, expected, [])])

    def test_a_refused_grant_raises(self):
        c = GatewayClient(BASE, ENGINE_TOKEN, transport=lambda *a: (403, {"content-type": "application/json", "x-research-gateway": "result"},
                                                                     b'{"error": "only a configured grantor may mint grants"}', None))
        with self.assertRaises(GrantRefused):
            c.grant(topic_id="t", commercial=False, accept_per_item=False, invocation_id=INV)


class OverRealHttp(unittest.TestCase):
    """The default transport against a loopback server replaying a recorded answer, and a
    redirect it must not follow (the bearer token is never sent elsewhere)."""

    def serve(self, handler_body):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                handler_body(self)

            do_GET = do_POST
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, f"http://127.0.0.1:{server.server_port}"

    def test_the_default_transport_reads_a_real_answer(self):
        resp = fixture("find_complete")["exchanges"][0]["response"]

        def answer(h):
            raw = json.dumps(resp["body"]).encode()
            h.send_response(200)
            h.send_header("Content-Type", "application/json")
            h.send_header("X-Research-Gateway", "result")
            h.send_header("Content-Length", str(len(raw)))
            h.end_headers()
            h.wfile.write(raw)
        _, url = self.serve(answer)
        c = GatewayClient(url, ENGINE_TOKEN, transport=http_transport)
        self.assertEqual(summary(by_lane(c.search(FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1"))["crossref"])[:3],
                         ("searched_ok", "complete", 1))

    def test_a_redirect_is_never_followed(self):
        seen = []
        elsewhere, other = self.serve(lambda h: seen.append(h.headers.get("Authorization")))
        for code in (301, 302, 303, 307, 308):   # urllib would follow a POST's 301-303 on its own, carrying the token
            with self.subTest(code):
                def redirect(h, code=code):
                    h.send_response(code)
                    h.send_header("Location", other + "/v1/find")
                    h.send_header("Content-Length", "0")
                    h.end_headers()
                _, url = self.serve(redirect)
                out = GatewayClient(url, ENGINE_TOKEN, transport=http_transport, timeout=5).search(
                    FIND, invocation_id=INV, attempt=1, policy_version="gw-policy/1")
                self.assertEqual([summary(o) for o in out["observations"]], [("unknown", "unobserved", None, "transport_failure", [])])
                self.assertEqual(seen, [], "the token went nowhere else")


class RecordedByTheRouter(RouterTestCase):
    """What the client returns is what the router records (2c/2d consume these rows)."""

    def setUp(self) -> None:
        super().setUp()
        self.to_scoping()
        self.grant = self.started(INV, "discovery")

    def record(self, out) -> list[dict]:
        replies = []
        for obs in out["observations"]:
            replies.append(self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": INV,
                                                           "observation": obs["observation"], "retrieval_events": obs["retrieval_events"]}))
        return replies

    def admissible(self, name: str, request: dict = FIND, **kw) -> dict:
        out = search(self, name, request, **kw)
        self.assertEqual([r["status"] for r in self.record(out)], ["recorded"] * len(out["observations"]))
        self.assertEqual([r["status"] for r in self.record(out)], ["replayed"] * len(out["observations"]), "idempotent")
        self.assertEqual(self.value("SELECT count(*) FROM search_observations WHERE result_count = 0 AND coverage_state != 'searched_empty'"), 0)
        return out

    def test_a_complete_answer_is_admissible(self):
        self.admissible("find_complete")

    def test_an_uncaptured_answer_is_admissible(self):
        self.admissible("find_not_captured")

    def test_an_unreadable_lane_is_admissible_and_counts_nothing(self):
        self.admissible("find_unreadable_lane")
        self.assertEqual(self.rows("SELECT lane, coverage_state, result_count FROM search_observations ORDER BY lane"),
                         [("crossref", "provider_unavailable", None), ("doaj", "searched_empty", 0)])

    def test_a_partial_answer_is_admissible(self):
        self.admissible("find_partial_records", {"request_type": "find", "query": "q", "kind": "article", "lanes": ["stub"]})
        self.assertEqual(self.value("SELECT count(*) FROM retrieval_events"), 2, "the lower bound's identities, one event each")

    def test_a_failed_continuation_is_admissible_as_a_lower_bound(self):
        self.admissible("find_paged_then_failed", pages=2)
        self.assertEqual(self.rows("SELECT lane, coverage_state, completeness, result_count, error_class FROM search_observations "
                                   "WHERE lane = 'crossref'"), [("crossref", "searched_ok", "partial", 1, "partial_pagination")])

    def test_pages_that_all_answer_are_admissible_as_one_complete_observation(self):
        self.admissible("find_paged_complete", pages=2)
        self.assertEqual(self.value("SELECT count(*) FROM retrieval_events"), 2)

    def test_one_attempt_is_one_observation(self):
        """A different outcome for the same invocation, request and attempt is refused at the
        receipt (H-1: attempt identity is immutable; a retry is a new attempt)."""
        self.admissible("find_complete")
        conflicting = search(self, "find_unreadable_lane")
        replies = {o["observation"]["lane"]: r for o, r in zip(conflicting["observations"], self.record(conflicting))}
        self.assertEqual((replies["crossref"]["status"], replies["crossref"]["reason"]), ("refused", "observation_id_conflict"))
        self.assertEqual(replies["doaj"]["status"], "replayed", "control: the lane whose outcome is the same replays")

    def test_a_secrets_failure_is_recorded_against_its_fact(self):
        out = search(self, "data_secrets_failing", {"request_type": "data", "source": "fred", "params": {"series": "GDP"}})
        (fact,) = out["capability_facts"]
        (reply,) = self.record(out)
        self.assertEqual(reply["status"], "refused", "the fact must exist first: the router has no command for it yet (2c/2e)")
        self.x("INSERT INTO capability_facts (fact_id, capability, state, detail, since, last_success_at, affected_lanes, recorded_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", fact["fact_id"], fact["capability"], fact["state"], fact["detail"], fact["since"],
               fact["last_success_at"], json.dumps(fact["affected_lanes"]), "2026-09-30T10:00:00Z")
        (reply,) = self.record(out)
        self.assertEqual(reply["status"], "recorded")
        self.assertEqual(self.rows("SELECT coverage_state, result_count, error_class, capability_fact_id FROM search_observations"),
                         [("provider_unavailable", None, "secrets_backend_failing", fact["fact_id"])])


if __name__ == "__main__":
    unittest.main()
