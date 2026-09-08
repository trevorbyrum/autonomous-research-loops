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
        with frozen_clock():   # stamps are frozen AT FIXTURE CONSTRUCTION, not merely at run time
            a = rec("crossref", "10.1234/abc", "Reranking at scale (crossref)")   # same work, two lanes,
            b = rec("doaj", "10.1234/abc", "Reranking at scale (doaj copy)")      # DIFFERENT titles: the
            c = rec("doaj", "10.9999/solo", "First independent doaj result")      # winner is discriminable
            d = rec("doaj", "10.9999/second", "Second independent doaj result")
        self.assertEqual(a["retrieved_at"], "2026-09-08T00:00:00+00:00", "fixture stamps ARE the frozen value")
        payload = {"request_type": "find", "kind": "article", "query": "reranking", "domain": "finance"}
        serial = self.run_find(payload, find_fn([a]), find_fn([b, c, d]), find_fn([]), width=1)

        # parallel, with completion order REVERSED: doaj answers before crossref may finish
        doaj_done = threading.Event()
        parallel = self.run_find(payload, find_fn([a], before=doaj_done),
                                 find_fn([b, c, d], after=doaj_done), find_fn([]), width=4)
        self.assertEqual(json.dumps(serial, sort_keys=True, default=str),
                         json.dumps(parallel, sort_keys=True, default=str),
                         "shuffled completion must not change one byte of the answer")
        winner = parallel["records"][0]
        self.assertEqual((winner["source_id"], winner["title"], winner["sources"]),
                         ("crossref", "Reranking at scale (crossref)", ["crossref", "doaj"]),
                         "the canonical winner is the PLAN-order first member — fields included, "
                         "not just the sources list")
        self.assertEqual([m["source_id"] for m in winner["provenance"]], ["crossref", "doaj"])
        self.assertEqual([ln["source"] for ln in parallel["lanes"]],
                         ["openalex_snapshot", "crossref", "doaj"])
        self.assertEqual([r["identity"] for r in parallel["records"]],
                         ["doi:10.1234/abc", "doi:10.9999/solo", "doi:10.9999/second"],
                         "TWO nonduplicate results from one lane keep their within-lane order")
        for ln in parallel["lanes"][1:]:
            self.assertIn("exhausted", ln, "a completed find lane without a cursor says so")

    def test_licence_filtering_holds_under_reversed_completion(self):
        # dataset plan (datacite, huggingface, openml): huggingface is a PER-ITEM source, so
        # its unlicensed record must drop no matter which lane finishes first
        with frozen_clock():
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




class AuditAdmission(unittest.TestCase):
    """9·2b: fatal-state publication and dispatch admission share ONE lock (client.db_lock),
    so no lane can pass admission between an audit failure and its discovery."""

    def test_calllog_failure_sets_abort_under_the_admission_lock(self):
        class BrokenConn:
            def cursor(self):
                raise RuntimeError("db down")
            def rollback(self):
                pass
        c = make_client()
        c.conn = BrokenConn()
        with self.assertRaises(calllog.AuditError):
            c.local("crossref", "find", query="q")
        self.assertTrue(c.abort.is_set(), "the FAILING write publishes the fatal state itself")

    def test_admission_refuses_dispatch_before_any_write_once_abort_is_set(self):
        writes: list = []

        class HealthyConn:
            def cursor(self):
                writes.append(1)
                raise AssertionError("a write was attempted after abort")
            def rollback(self):
                pass
        c = make_client()
        c.conn = HealthyConn()
        c.abort.set()
        with self.assertRaises(calllog.AuditError):
            c._attempt("crossref", "find", None, "q")
        self.assertEqual(writes, [], "an aborted client never writes another attempt row — "
                                     "and therefore never dispatches (the attempt row precedes transport)")


class InlineSerialBound(unittest.TestCase):
    """The aggregate bound covers the SERIAL/INLINE lane paths too — data/catalog/fetch
    requests bypass both the worker pool and the find-lane pool."""

    def setUp(self):
        R._LANE_SLOTS = None

    def tearDown(self):
        R._LANE_SLOTS = None

    def test_concurrent_inline_data_requests_respect_lane_total(self):
        gate = threading.Lock()
        in_flight = {"now": 0, "max": 0}

        def tracked_data(client, params):
            with gate:
                in_flight["now"] += 1
                in_flight["max"] = max(in_flight["max"], in_flight["now"])
            threading.Event().wait(0.15)
            with gate:
                in_flight["now"] -= 1
            return {"records": []}

        r = R.Router(SEED, ADAPTERS)
        sources = ("fred", "bls", "bea")
        with mock.patch.dict(os.environ, {"RESEARCH_GATEWAY_LANE_TOTAL": "1"}), \
             mock.patch.object(ADAPTERS["fred"], "data", tracked_data), \
             mock.patch.object(ADAPTERS["bls"], "data", tracked_data), \
             mock.patch.object(ADAPTERS["bea"], "data", tracked_data):
            threads = [threading.Thread(target=R.execute,
                                        args=(r, {"request_type": "data", "source": sid, "params": {}},
                                              make_client()))
                       for sid in sources]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        self.assertEqual(in_flight["now"], 0)
        self.assertEqual(in_flight["max"], 1,
                         "three concurrent inline data requests, RESEARCH_GATEWAY_LANE_TOTAL=1: "
                         "one adapter dispatch in flight at a time")


class BreakerSequenceOrdering(unittest.TestCase):
    """A close racing a reopen can never persist as newer than the reopen: every transition's
    sequence is allocated in the same critical section as its state mutation."""

    def test_persisted_state_never_regresses_live_state_under_close_open_races(self):
        events: list = []
        b = Broker({"src": RatePolicy(per_second=100000)},
                   on_breaker_change=lambda s, st, ra, r, q: events.append((q, st)))
        rounds = 200
        barrier = threading.Barrier(2)

        def closer():
            for _ in range(rounds):
                barrier.wait(10)
                b.close_breaker("src")

        def opener():
            for _ in range(rounds):
                barrier.wait(10)
                b.record("src", 429, retry_after=3600)

        threads = [threading.Thread(target=closer), threading.Thread(target=opener)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        # a persister that applies only newer-than-applied sequences must end at the live state
        applied_seq, applied_state = -1, None
        for q, st in events:
            if q > applied_seq:
                applied_seq, applied_state = q, st
        self.assertEqual(applied_state == "open", b.breaker_open("src"),
                         "the highest-sequence event IS the live state — a delayed callback can "
                         "never leave persistence behind the broker")

    def test_closing_a_nonexistent_breaker_emits_nothing(self):
        events: list = []
        b = Broker({"src": RatePolicy(per_second=100)},
                   on_breaker_change=lambda s, st, ra, r, q: events.append((q, st)))
        b.close_breaker("src")
        self.assertEqual(events, [], "no state was cleared, so no transition is announced")


class OpenAireSingleFlight(unittest.TestCase):
    def test_concurrent_mint_is_single_flight_and_registers_per_client(self):
        from research_gateway.adapters import openaire
        openaire.reset_token()
        creds = {("openaire", "client_id"): "id", ("openaire", "client_secret"): "sec"}
        t = FakeTransport()
        t.add("POST", "https://aai.openaire.eu/oidc/token", body={"access_token": "tok-single", "expires_in": 3600})
        clients = [Client(broker=Broker({"openaire": RatePolicy(per_second=100000)}), transport=t,
                          secrets=lambda n, f=None: creds.get((n, f))) for _ in range(8)]
        errors: list = []

        def go(i):
            try:
                openaire._headers(clients[i])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(30)
        self.assertEqual(errors, [])
        mints = [c for c in t.calls if c[0] == "POST" and "oidc/token" in c[1]]
        self.assertEqual(len(mints), 1, "eight concurrent callers, ONE token exchange")
        for i, c in enumerate(clients):
            self.assertIn("tok-single", c.secret_values,
                          f"client {i} registered the shared token for redaction despite not minting it")


class SameSourceContention(unittest.TestCase):
    """9·2b broker-under-contention: parallel same-source entries — rate reservations,
    credits, a 429 Retry-After opening the breaker, refusals for late arrivals, and
    restart reconstruction of usage AND the open breaker from what was recorded."""

    def test_parallel_entries_credits_breaker_and_restart_reconstruction(self):
        from research_gateway.core.broker import BreakerOpen
        t = FakeTransport()
        t.add("GET", "https://api.example.org/limited", status=429, headers={"Retry-After": "3600"})
        t.add("GET", "https://api.example.org/ok", body={"items": []})
        broker = Broker({"src": RatePolicy(per_second=1000, per_day=100)})
        c = Client(broker=broker, transport=t)
        results: list = []

        def ok_call(i):
            results.append(("ok", c.get("src", "data", "https://api.example.org/ok", credits=1.0).status))

        threads = [threading.Thread(target=ok_call, args=(i,)) for i in range(6)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(30)
        self.assertEqual([r for r in results if r == ("ok", 200)], [("ok", 200)] * 6)
        # one call hits the limiter: Retry-After opens the breaker for everyone
        resp = c.get("src", "data", "https://api.example.org/limited", credits=1.0)
        self.assertEqual(resp.status, 429)
        self.assertTrue(broker.breaker_open("src"))
        refused = c.get("src", "data", "https://api.example.org/ok", credits=1.0)
        self.assertIsNone(refused.status, "a parallel sibling is REFUSED while the breaker is open")
        self.assertIn("BreakerOpen", refused.error or "")
        # accounting: dispatched calls and credits are consistent between broker and log
        st = broker.status()["src"]
        dispatched_rows = [r for r in c.log if r.failure_class not in ("attempt",) and not r.cache_hit
                           and r.failure_class != "refused"]
        self.assertEqual(st["dispatched_today"], len(dispatched_rows))
        self.assertEqual(st["credits_today"], sum(r.credits or 0 for r in dispatched_rows))
        # restart: a fresh broker seeded from the recorded usage and persisted breaker
        # deadline carries BOTH the counters and the open restriction forward
        reborn = Broker({"src": RatePolicy(per_second=1000, per_day=100)})
        reborn.seed_usage({"src": (st["dispatched_today"], st["credits_today"])})
        reborn.seed_breakers([("src", 3600.0)])
        self.assertTrue(reborn.breaker_open("src"), "restart never forgets a live restriction")
        self.assertEqual(reborn.status()["src"]["dispatched_today"], st["dispatched_today"])
        self.assertEqual(reborn.status()["src"]["credits_today"], st["credits_today"])


class _ScriptedConn:
    """DB stand-in with real-enough cursor semantics for calllog: INSERTs return ids,
    UPDATEs can be scripted to fail. Thread-safe; counts every write."""

    def __init__(self, fail_update_n: int | None = None, fail_first_use: bool = False):
        self._lock = threading.Lock()
        self.inserts = self.updates = self.rollbacks = 0
        self._fail_update_n = fail_update_n
        self._fail_first_use = fail_first_use
        outer = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=None):
                with outer._lock:
                    if outer._fail_first_use:
                        outer._fail_first_use = False
                        raise RuntimeError("db down")
                    if sql.lstrip().upper().startswith("INSERT"):
                        outer.inserts += 1
                        self._last = (outer.inserts,)
                    else:
                        outer.updates += 1
                        self._last = None
                        if outer._fail_update_n is not None and outer.updates == outer._fail_update_n:
                            raise RuntimeError("completion write refused")

            def fetchone(self):
                return self._last
        self._cur = Cur

    def cursor(self):
        return self._cur()

    def commit(self):
        pass

    def rollback(self):
        with self._lock:
            self.rollbacks += 1


class _SpyEvent(threading.Event):
    """Records whether db_lock was HELD at the moment set() ran — the exact ordering
    property the abort design promises (publication under the admission lock)."""

    def __init__(self, lock):
        super().__init__()
        self._spied_lock = lock
        self.set_while_locked: bool | None = None

    def set(self):
        self.set_while_locked = self._spied_lock.locked()
        super().set()


class AbortPublicationOrdering(unittest.TestCase):
    def test_publication_holds_the_admission_lock_and_a_racing_sibling_never_writes(self):
        c = make_client()
        c.abort = _SpyEvent(c.db_lock)
        c.conn = _ScriptedConn(fail_first_use=True)
        with self.assertRaises(calllog.AuditError):
            c.local("crossref", "find", query="q")
        self.assertTrue(c.abort.is_set())
        self.assertIs(c.abort.set_while_locked, True,
                      "abort is published while db_lock is HELD — publishing after release "
                      "reopens the admission window and must fail this pin")
        got: dict = {}

        def sibling():
            try:
                c._attempt("doaj", "find", None, "q")
            except calllog.AuditError as e:
                got["e"] = e
        t = threading.Thread(target=sibling)
        t.start()
        t.join(10)
        self.assertIsInstance(got.get("e"), calllog.AuditError)
        self.assertEqual(c.conn.inserts, 0, "the refused sibling never wrote an attempt row")

    def test_completion_write_failure_publishes_under_lock_and_blocks_the_next_dispatch(self):
        t = FakeTransport()
        t.add("GET", "https://api.example.org/ok", body={"items": []})
        c = Client(broker=Broker({"src": RatePolicy(per_second=100000)}), transport=t)
        c.abort = _SpyEvent(c.db_lock)
        c.conn = _ScriptedConn(fail_update_n=1)   # the attempt INSERT succeeds; its completion fails
        with self.assertRaises(calllog.AuditError):
            c.get("src", "data", "https://api.example.org/ok")
        self.assertIs(c.abort.set_while_locked, True)
        inserts_before = c.conn.inserts
        with self.assertRaises(calllog.AuditError):
            c.get("src", "data", "https://api.example.org/ok")
        self.assertEqual(c.conn.inserts, inserts_before,
                         "after a completion-write failure, the next dispatch is refused at "
                         "admission — no new attempt row, nothing sent")

    def test_concurrent_shared_connection_dispatches_with_redirect_and_limiter(self):
        """Two threads dispatch CONCURRENTLY over one shared connection (redirect chain and
        a 429 included); every hop's attempt commits before transport and completes; a later
        completion failure aborts the client for everyone."""
        t = FakeTransport()
        t.add("GET", "https://93.184.216.34/hop", status=302,   # literal IPs: the redirect guard
              headers={"Location": "https://93.184.216.34/ok"})  # needs no DNS in tests
        t.add("GET", "https://93.184.216.34/ok", body={"items": []})
        t.add("GET", "https://api.example.org/limited", status=429, headers={"Retry-After": "1"})
        broker = Broker({"src": RatePolicy(per_second=100000)})
        c = Client(broker=broker, transport=t)
        c.conn = _ScriptedConn()
        barrier = threading.Barrier(2)
        errors: list = []

        def redirecting():
            barrier.wait(10)
            errors.append(("redir", c.get("src", "fetch", "https://93.184.216.34/hop").status))

        def plain():
            barrier.wait(10)
            errors.append(("plain", c.get("src", "data", "https://93.184.216.34/ok").status))
        threads = [threading.Thread(target=redirecting), threading.Thread(target=plain)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(30)
        self.assertIn(("redir", 200), errors)
        self.assertIn(("plain", 200), errors)
        # the limiter case runs AFTER the joins: its Retry-After legitimately opens the
        # breaker for the whole source, which would otherwise race the redirect's own hops
        self.assertEqual(c.get("src", "data", "https://api.example.org/limited").status, 429)
        hops = [rec.hop for rec in c.log if rec.request_type == "fetch"]
        self.assertEqual(hops, [0, 1], "redirect hops carry their index — hop rows are transport "
                                       "legs of ONE logical dispatch, never repeated lookups")
        self.assertEqual(c.conn.inserts, 4, "every dispatch leg wrote its attempt row (2 hops + plain + limited)")
        self.assertEqual(c.conn.updates, 4, "and each attempt row was completed")
        self.assertFalse(c.abort.is_set())


class StopDrainsInline(unittest.TestCase):
    def test_stop_leaves_connections_open_while_an_inline_request_runs_and_refuses_new_ones(self):
        from research_gateway import app as app_module

        class CloseRecordingConn:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True
        gw = app_module.Gateway(app_module.Settings(tokens={"t": "t"}, workers=1, sync_timeout=1),
                                use_db=False, transport=FakeTransport())
        gw.cache.conn = CloseRecordingConn()    # the shared resource stop() would close
        release = threading.Event()
        started = threading.Event()

        def blocked_data(client, params):
            started.set()
            assert release.wait(30)
            return {"records": []}
        with mock.patch.dict(os.environ, {"RESEARCH_GATEWAY_STOP_TIMEOUT": "1"}), \
             mock.patch.object(ADAPTERS["fred"], "data", blocked_data):
            t = threading.Thread(target=gw.run_inline,
                                 args=({"request_type": "data", "source": "fred", "params": {}}, "t"))
            t.start()
            self.assertTrue(started.wait(10))
            gw.stop()
            self.assertFalse(gw.cache.conn.closed, "an ACTIVE inline request keeps shared connections open")
            with self.assertRaises(RuntimeError):
                gw.run_inline({"request_type": "data", "source": "fred", "params": {}}, "t")
            release.set()
            t.join(10)
        self.assertFalse(t.is_alive())


class CrossProcessActivity(unittest.TestCase):
    def test_fail_then_recover_across_two_processes_keeps_order_and_recovery(self):
        import subprocess
        import sys as _sys
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "research-activity-test.jsonl")
            script = ("import sys, json; from research_gateway.clients import mcp_stdio as m; "
                      "m.record_activity(sys.argv[1], 'research_find', {'query': 'q'}, "
                      "None if sys.argv[2] == 'fail' else "
                      "{'payload': {'request_type': 'find', 'lanes': [{'source': 'crossref', 'coverage': 'searched_ok'}]}}, "
                      "error=('gateway_unavailable' if sys.argv[2] == 'fail' else None))")
            env = dict(os.environ, PYTHONPATH=os.getcwd())
            for phase in ("fail", "recover"):   # two INDEPENDENT processes, no shared state map
                r = subprocess.run([_sys.executable, "-c", script, path, phase],
                                   env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)
            lines = [json.loads(ln) for ln in open(path).read().splitlines() if ln.strip()]
            gateway_cov = [ln["coverage"] for ln in lines if ln.get("source") == "gateway"]
            self.assertEqual(gateway_cov[0], "provider_unavailable",
                             "append-all: the first process's failure observation survives")
            self.assertEqual(gateway_cov[-1], "searched_ok",
                             "the second (INDEPENDENT) process's recovery is the LAST state in "
                             "file order — exactly what the chassis summarizer reads, so the "
                             "blocker clears despite no shared in-process state map")


if __name__ == "__main__":
    unittest.main()
