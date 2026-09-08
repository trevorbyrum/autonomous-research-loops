"""Phase 9·2b acceptance: parallel find lanes change WHEN provider waits happen, never
WHAT the request answers. Determinism is pinned against shuffled completion order with
retrieval timestamps frozen in the fixtures (never by rewriting real stamps); AuditError
stays fatal mid-parallel with running lanes joined and undispatched lanes never
dispatched; the aggregate slot bound covers concurrent requests, inline included."""
import json
import os
import threading
import types
import unittest
from unittest import mock

from research_gateway import adapters
from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core import calllog
from research_gateway.core import canonical
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.registry.load import read_seed

SEED = read_seed()
ADAPTERS = adapters.load_all()
FROZEN = "2026-09-08T00:00:00+00:00"


class _FrozenDatetime:
    @staticmethod
    def now(tz=None):
        from datetime import datetime
        return datetime.fromisoformat(FROZEN)


def frozen_clock():
    """Fixture stamps are FROZEN (plan v3): both the serial and the parallel run mint the
    same retrieved_at, so byte-identity compares content, not the wall clock."""
    return mock.patch.object(canonical, "datetime", _FrozenDatetime)


def make_client():
    return Client(broker=Broker({s["id"]: RatePolicy(per_second=100) for s in SEED}), transport=FakeTransport())


def rec(source_id: str, doi: str, title: str, license: str | None = "cc-by-4.0") -> dict:
    return canonical.make_record(identity=f"doi:{doi}", kind="article", source_id=source_id,
                                 title=title, year=2021, license=license,
                                 links=[f"https://{source_id}.example/{doi}"])


def find_fn(records: list[dict], before: threading.Event | None = None,
            after: threading.Event | None = None, calls: list | None = None):
    """A fake adapter `find` with the real signature. `before` delays completion until set
    (shuffling completion order); `after` is set once this lane's answer is built."""
    def find(client, query, limit=20, kind=None, domain=None):
        if calls is not None:
            calls.append(threading.get_ident())
        if before is not None:
            assert before.wait(10), "test orchestration event never fired"
        out = {"records": [json.loads(json.dumps(r)) for r in records]}
        if after is not None:
            after.set()
        return out
    return find


class MergeDeterminism(unittest.TestCase):
    """Finance find plan: openalex_snapshot, crossref, doaj — three real lanes, fake finds."""

    def run_find(self, payload, crossref_find, doaj_find, snapshot_find, width):
        r = R.Router(SEED, ADAPTERS)
        with frozen_clock(), \
             mock.patch.dict(os.environ, {"RESEARCH_GATEWAY_LANE_CONCURRENCY": str(width)}), \
             mock.patch.object(ADAPTERS["crossref"], "find", crossref_find), \
             mock.patch.object(ADAPTERS["doaj"], "find", doaj_find), \
             mock.patch.object(ADAPTERS["openalex_snapshot"], "find", snapshot_find):
            return R.execute(r, payload, make_client())

    def test_parallel_answer_is_byte_identical_to_serial_under_reversed_completion(self):
        a = rec("crossref", "10.1234/abc", "Reranking at scale")      # same work, two lanes:
        b = rec("doaj", "10.1234/abc", "Reranking at scale")          # the canonical winner is
        c = rec("doaj", "10.9999/solo", "An unrelated result")        # the PLAN-order first
        payload = {"request_type": "find", "kind": "article", "query": "reranking", "domain": "finance"}
        serial = self.run_find(payload, find_fn([a]), find_fn([b, c]), find_fn([]), width=1)

        # parallel, with completion order REVERSED: doaj answers before crossref may finish
        doaj_done = threading.Event()
        parallel = self.run_find(payload, find_fn([a], before=doaj_done),
                                 find_fn([b, c], after=doaj_done), find_fn([]), width=4)
        self.assertEqual(json.dumps(serial, sort_keys=True, default=str),
                         json.dumps(parallel, sort_keys=True, default=str),
                         "shuffled completion must not change one byte of the answer")
        self.assertEqual(parallel["records"][0]["sources"], ["crossref", "doaj"],
                         "dedup winner and member order follow PLAN order, not completion order")
        self.assertEqual([m["source_id"] for m in parallel["records"][0]["provenance"]],
                         ["crossref", "doaj"])
        self.assertEqual([ln["source"] for ln in parallel["lanes"]],
                         ["openalex_snapshot", "crossref", "doaj"])
        self.assertEqual([r["identity"] for r in parallel["records"]],
                         ["doi:10.1234/abc", "doi:10.9999/solo"], "within-lane order preserved")
        for ln in parallel["lanes"][1:]:
            self.assertIn("exhausted", ln, "a completed find lane without a cursor says so")

    def test_licence_filtering_holds_under_reversed_completion(self):
        # dataset plan (datacite, huggingface, openml): huggingface is a PER-ITEM source, so
        # its unlicensed record must drop no matter which lane finishes first
        allowed = canonical.make_record(identity="hf:owner/corpus", kind="dataset", source_id="huggingface",
                                        title="Licensed corpus", license="cc-by-4.0")
        denied = canonical.make_record(identity="hf:owner/mystery", kind="dataset", source_id="huggingface",
                                       title="Mystery corpus", license=None)
        payload = {"request_type": "find", "kind": "dataset", "query": "corpus", "domain": "ai-ml",
                   "commercial": True, "accept_per_item": True}
        hf_done = threading.Event()
        r = R.Router(SEED, ADAPTERS)
        with frozen_clock(), \
             mock.patch.dict(os.environ, {"RESEARCH_GATEWAY_LANE_CONCURRENCY": "4"}), \
             mock.patch.object(ADAPTERS["datacite"], "find", find_fn([], before=hf_done)), \
             mock.patch.object(ADAPTERS["huggingface"], "find", find_fn([allowed, denied], after=hf_done)), \
             mock.patch.object(ADAPTERS["openml"], "find", find_fn([])):
            out = R.execute(r, payload, make_client())
        self.assertEqual([rc["identity"] for rc in out["records"]], ["hf:owner/corpus"])
        self.assertTrue(any("not usable commercially (R-8)" in f for f in out["facts"]))

    def test_exhausted_cursor_lane_is_never_dispatched_in_parallel_mode(self):
        calls: list = []
        payload = {"request_type": "find", "kind": "article", "query": "q", "domain": "finance",
                   "cursors": {"crossref": R.EXHAUSTED_CURSOR}}
        out = self.run_find(payload, find_fn([rec("crossref", "10.1/x", "t")], calls=calls),
                            find_fn([]), find_fn([]), width=4)
        self.assertEqual(calls, [], "the caller's exhaustion marker is honoured, not re-fetched")
        entry = next(ln for ln in out["lanes"] if ln["source"] == "crossref")
        self.assertEqual(entry["coverage"], R.COVERAGE_EXHAUSTED)
        self.assertEqual(out["next"]["crossref"], R.EXHAUSTED_CURSOR)

    def test_concurrency_one_rollback_runs_on_the_caller_thread(self):
        calls: list = []
        payload = {"request_type": "find", "kind": "article", "query": "q", "domain": "finance"}
        self.run_find(payload, find_fn([], calls=calls), find_fn([], calls=calls),
                      find_fn([], calls=calls), width=1)
        self.assertEqual(set(calls), {threading.get_ident()},
                         "RESEARCH_GATEWAY_LANE_CONCURRENCY=1 is a true serial rollback")


def _fake_router(mods: dict) -> types.SimpleNamespace:
    return types.SimpleNamespace(adapters=mods)


def _mod(source_id: str, find) -> types.SimpleNamespace:
    return types.SimpleNamespace(SOURCE_ID=source_id, find=find)


def _plan(*source_ids: str) -> R.Plan:
    return R.Plan(request_type="find", lanes=[R.Lane(s, "base") for s in source_ids])


class AuditErrorStaysFatal(unittest.TestCase):
    def test_running_lanes_join_and_undispatched_lanes_never_dispatch(self):
        b_started, release, b_finished = threading.Event(), threading.Event(), threading.Event()
        c_calls: list = []

        def find_a(client, query, limit=20):
            assert b_started.wait(10)
            raise calllog.AuditError("attempt row could not be written")

        def find_b(client, query, limit=20):
            b_started.set()
            assert release.wait(10), "lane B was abandoned instead of joined"
            b_finished.set()
            return {"records": []}

        router = _fake_router({"a": _mod("a", find_a), "b": _mod("b", find_b),
                               "c": _mod("c", find_fn([], calls=c_calls))})
        out = {"facts": [], "lanes": []}
        result: dict = {}

        def run():
            try:
                R._run_find_lanes(router, {"request_type": "find", "query": "q"}, make_client(),
                                  _plan("a", "b", "c"), out)
            except BaseException as e:
                result["exc"] = e

        with mock.patch.dict(os.environ, {"RESEARCH_GATEWAY_LANE_CONCURRENCY": "2"}):
            t = threading.Thread(target=run)
            t.start()
            self.assertTrue(b_started.wait(10))
            t.join(0.3)
            self.assertTrue(t.is_alive(), "the request returned while lane B was still running")
            release.set()
            t.join(10)
        self.assertFalse(t.is_alive())
        self.assertIsInstance(result.get("exc"), calllog.AuditError,
                              "a broken call log fails the WHOLE find, never a degraded partial answer")
        self.assertTrue(b_finished.is_set(), "running lanes are joined before the request returns")
        self.assertEqual(c_calls, [], "a lane queued behind the failure never dispatches (I-6)")


class AggregateBound(unittest.TestCase):
    def setUp(self):
        R._LANE_SLOTS = None

    def tearDown(self):
        R._LANE_SLOTS = None

    def test_lane_total_bounds_concurrent_requests_including_inline(self):
        gate = threading.Lock()
        in_flight = {"now": 0, "max": 0}
        proceed = threading.Event()

        def tracked_find(client, query, limit=20):
            with gate:
                in_flight["now"] += 1
                in_flight["max"] = max(in_flight["max"], in_flight["now"])
            proceed.wait(0.2)   # hold the slot long enough for overlap to be observable
            with gate:
                in_flight["now"] -= 1
            return {"records": []}

        router = _fake_router({s: _mod(s, tracked_find) for s in ("a", "b", "c", "d")})
        with mock.patch.dict(os.environ, {"RESEARCH_GATEWAY_LANE_CONCURRENCY": "4",
                                          "RESEARCH_GATEWAY_LANE_TOTAL": "2"}):
            threads = [threading.Thread(target=R._run_find_lanes,
                                        args=(router, {"request_type": "find", "query": "q"},
                                              make_client(), _plan("a", "b", "c", "d"),
                                              {"facts": [], "lanes": []}))
                       for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        self.assertEqual(in_flight["now"], 0)
        self.assertLessEqual(in_flight["max"], 2,
                             "12 wanted lanes across 3 concurrent requests, never more than "
                             "RESEARCH_GATEWAY_LANE_TOTAL=2 dispatches in flight")
        self.assertGreaterEqual(in_flight["max"], 2, "the bound throttles; it does not serialize")


if __name__ == "__main__":
    unittest.main()
