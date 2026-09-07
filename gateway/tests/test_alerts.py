"""Phase 7 (§7): alert events, once-per-interval delivery, budget warning at 80 %, the call-log checks."""
import threading
import unittest
import uuid

from research_gateway.core import alerts, calllog, db
from research_gateway.core.broker import Broker, RatePolicy


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Delivery(unittest.TestCase):
    def test_once_per_interval_per_key(self):
        sent, clock = [], FakeClock()
        a = alerts.Alerter(lambda t, m, p: sent.append((t, p)), clock=clock, min_interval=3600)
        self.assertTrue(a.enabled)
        self.assertTrue(a.alert("breaker:crossref", "crossref: breaker open", "429 storm", "high"))
        self.assertFalse(a.alert("breaker:crossref", "crossref: breaker open", "again", "high"), "same key within the hour is swallowed")
        self.assertTrue(a.alert("breaker:doaj", "doaj: breaker open", "x", "high"))
        clock.t += 3601
        self.assertTrue(a.alert("breaker:crossref", "crossref: breaker open", "later", "high"))
        a.flush()
        self.assertEqual([t for t, _ in sent], ["crossref: breaker open", "doaj: breaker open", "crossref: breaker open"])
        self.assertEqual(len(a.history), 3)
        self.assertEqual(a.delivered, 3)

    def test_delivery_is_off_the_callers_thread_and_never_raises(self):
        import threading
        calls, gate = [], threading.Event()

        def slow_then_broken(title, message, priority):
            calls.append(title)
            gate.wait(5)
            raise RuntimeError("ntfy down")

        a = alerts.Alerter(slow_then_broken)
        self.assertTrue(a.alert("k1", "first", "m"))
        self.assertTrue(a.alert("k2", "second", "m"), "the caller returns while the sender is still blocked")
        gate.set()
        a.flush()
        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(a.delivered, 0, "sender errors are swallowed, not raised")

    def test_silent_when_unconfigured_and_events_have_shapes(self):
        a = alerts.Alerter(None)
        self.assertFalse(a.enabled)
        a.breaker("crossref", "open", None, "3 consecutive limit errors")
        a.breaker("crossref", "closed", None, "window elapsed")
        a.budget("core", "requests", 160, 200)
        a.failures("semanticscholar", "auth", 4, 10)
        a.zero_results("doaj", "supply chain", 6, 40)
        a.health("db down")
        self.assertEqual([k for _, k, _ in a.history], ["breaker:crossref", "budget:core:requests", "auth:semanticscholar", "zero:doaj:supply chain", "health"])
        self.assertEqual(alerts.from_env(None, environ={}).enabled, False)
        self.assertTrue(alerts.from_env(None, environ={"RESEARCH_GATEWAY_NTFY_URL": "http://ntfy.local", "RESEARCH_GATEWAY_NTFY_TOPIC": "t"}).enabled)

    def test_broker_warns_at_eighty_percent_once_per_day(self):
        warned = []
        b = Broker({"src": RatePolicy(per_second=100, per_day=10)}, on_budget=lambda s, w, u, c: warned.append((s, w, u, c)))
        for _ in range(10):
            b.acquire("src")
        self.assertEqual(warned, [("src", "requests", 8.0, 10.0)], "fires once when crossing 80 %, not on every call after")
        credits = []
        bc = Broker({"src": RatePolicy(per_second=100, cost_cap_per_day=1.0)}, on_budget=lambda s, w, u, c: credits.append((w, u)))
        for _ in range(9):
            bc.acquire("src", credits=0.1)
        self.assertEqual(len(credits), 1)
        self.assertEqual(credits[0][0], "credits")


@unittest.skipUnless(db.configured(), "RESEARCH_GATEWAY_DSN not set")
class CallLogChecks(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.src = f"alert-test-{uuid.uuid4().hex[:6]}"

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.calls WHERE source_id = %s", (self.src,))
        self.conn.commit()
        self.conn.close()

    def _row(self, **kw):
        rec = calllog.CallRecord(source_id=self.src, request_type=kw.pop("request_type", "find"), status=kw.pop("status", 200),
                                 latency_ms=1, **kw)
        return calllog.record(self.conn, rec)

    def test_auth_failures_and_zero_results_are_detected(self):
        sent = []
        a = alerts.Alerter(lambda t, m, p: sent.append(t))
        for _ in range(3):
            self._row(status=401, failure_class="auth")
        for _ in range(3):
            self._row(result_count=0, query="Supply Chain resilience")
        for _ in range(3):
            self._row(result_count=0, query="another query")
        seen = alerts.check_calls(self.conn, a)
        self.assertEqual(seen["failures"], [(self.src, "auth", 3)])
        self.assertEqual(seen["zero_results"], [], "no earlier hits for these queries, so silence is not news")
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO gateway.calls (source_id, request_type, query, status, latency_ms, result_count, failure_class, at) "
                        "VALUES (%s, 'find', 'supply chain RESILIENCE', 200, 1, 7, 'ok', now() - interval '2 days')", (self.src,))
        self.conn.commit()
        seen = alerts.check_calls(self.conn, a)
        self.assertEqual(seen["zero_results"], [(self.src, "supply chain resilience", 3, 1)],
                         "the same query pattern used to return results; the other query never did")
        a.flush()
        self.assertEqual(sent, [f"{self.src}: 3 auth failure(s) in 10 min", f"{self.src}: find returns nothing for a query that used to"])

    def test_watcher_runs_and_stops(self):
        stop = threading.Event()
        a = alerts.Alerter(None)
        w = alerts.Watcher(db.connect, a, lambda: {"ok": True}, stop, interval=0.05)
        w.start()
        for _ in range(100):
            if w.passes >= 2:
                break
            threading.Event().wait(0.02)
        stop.set()
        w.join(timeout=5)
        self.assertGreaterEqual(w.passes, 2)
        self.assertIsNone(w.error)


if __name__ == "__main__":
    unittest.main()
