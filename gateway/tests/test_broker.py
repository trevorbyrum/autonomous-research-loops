"""Phase 2 acceptance for the rate broker (PLAN.md §5, §13 Phase 2)."""
import threading
import unittest

from research_gateway.core.broker import Broker, BreakerOpen, BudgetExhausted, NoPolicy, RatePolicy, policies_from_rows


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def make(policies, **kw):
    clock = FakeClock()
    wall = FakeClock(1_800_000_000.0)
    b = Broker(policies, clock=clock, wall=wall, **kw)
    return b, clock, wall


class Windows(unittest.TestCase):
    def test_per_second_never_exceeded_under_concurrency(self):
        b, clock, _ = make({"src": RatePolicy(per_second=10)})
        granted = []

        def worker():
            for _ in range(20):
                if b.acquire("src") == 0.0:
                    granted.append(1)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(granted), 10, "100 concurrent attempts, exactly 10 grants in the 1s window")

    def test_wait_is_reported_then_window_frees(self):
        b, clock, _ = make({"src": RatePolicy(per_second=2)})
        self.assertEqual(b.acquire("src"), 0.0)
        self.assertEqual(b.acquire("src"), 0.0)
        wait = b.acquire("src")
        self.assertGreater(wait, 0.0)
        self.assertLessEqual(wait, 1.0)
        clock.advance(wait)
        self.assertEqual(b.acquire("src"), 0.0)

    def test_burst_overrides_per_second_count(self):
        b, _, _ = make({"src": RatePolicy(per_second=2, burst=5)})
        self.assertEqual([b.acquire("src") for _ in range(5)], [0.0] * 5)
        self.assertGreater(b.acquire("src"), 0.0)

    def test_hourly_window(self):
        b, clock, _ = make({"src": RatePolicy(per_hour=3)})
        for _ in range(3):
            self.assertEqual(b.acquire("src"), 0.0)
        wait = b.acquire("src")
        self.assertGreater(wait, 3599.0)
        clock.advance(3600.0)
        self.assertEqual(b.acquire("src"), 0.0)

    def test_daily_limit_is_a_budget_not_a_wait(self):
        b, _, _ = make({"src": RatePolicy(per_day=2)})
        b.acquire("src")
        b.acquire("src")
        with self.assertRaises(BudgetExhausted):
            b.acquire("src")

    def test_cost_cap(self):
        b, _, _ = make({"src": RatePolicy(per_second=100, cost_cap_per_day=1.0)})
        b.acquire("src", credits=0.6)
        with self.assertRaises(BudgetExhausted):
            b.acquire("src", credits=0.6)

    def test_daily_counters_reset_at_utc_midnight(self):
        b, _, wall = make({"src": RatePolicy(per_second=100, cost_cap_per_day=1.0)})
        b.acquire("src", credits=1.0)
        with self.assertRaises(BudgetExhausted):
            b.acquire("src", credits=0.1)
        wall.advance(86400.0)
        self.assertEqual(b.acquire("src", credits=0.1), 0.0)

    def test_per_day_is_a_utc_day_counter_not_a_trailing_window(self):
        b, clock, wall = make({"src": RatePolicy(per_day=2)})
        b.acquire("src")
        clock.advance(60.0)
        b.acquire("src")
        with self.assertRaises(BudgetExhausted):
            b.acquire("src")
        wall.advance(3600.0)  # same UTC day: still exhausted
        with self.assertRaises(BudgetExhausted):
            b.acquire("src")
        wall.advance(86400.0)  # next UTC day: budget is back even though <24h passed since the second call
        self.assertEqual(b.acquire("src"), 0.0)
        self.assertEqual(b.status()["src"]["dispatched_today"], 1)

    def test_limit_errors_without_retry_after_back_off_10_to_80_seconds(self):
        b, clock, _ = make({"src": RatePolicy(per_second=100)}, errors_to_open=6)
        for want in (10.0, 20.0, 40.0, 80.0, 80.0):
            b.record("src", 429)
            self.assertAlmostEqual(b.acquire("src"), want)
            self.assertAlmostEqual(b.status()["src"]["backoff_seconds"], want)
            clock.advance(want)
            self.assertEqual(b.acquire("src"), 0.0)
        b.record("src", 200)
        self.assertEqual(b.acquire("src"), 0.0)
        self.assertEqual(b.status()["src"]["backoff_seconds"], 0.0)


class Refusals(unittest.TestCase):
    def test_source_without_policy_is_refused(self):
        b, _, _ = make({"src": RatePolicy(per_second=1)})
        with self.assertRaises(NoPolicy):
            b.acquire("unknown")

    def test_empty_policy_counts_as_no_policy(self):
        b, _, _ = make({"src": RatePolicy()})
        with self.assertRaises(NoPolicy):
            b.acquire("src")


class Breakers(unittest.TestCase):
    def test_opens_after_three_limit_errors_and_closes_after_window(self):
        events = []
        b, clock, _ = make({"src": RatePolicy(per_second=100)}, breaker_window=600,
                           on_breaker_change=lambda s, st, ra, r, q=0: events.append((s, st)))
        b.record("src", 429)
        b.record("src", 429)
        self.assertFalse(b.breaker_open("src"))
        b.record("src", 503)
        self.assertTrue(b.breaker_open("src"))
        with self.assertRaises(BreakerOpen):
            b.acquire("src")
        clock.advance(600.1)
        self.assertFalse(b.breaker_open("src"))
        self.assertEqual(b.acquire("src"), 0.0)
        self.assertEqual(events, [("src", "open"), ("src", "closed")])

    def test_success_resets_error_count(self):
        b, _, _ = make({"src": RatePolicy(per_second=100)})
        b.record("src", 429)
        b.record("src", 429)
        b.record("src", 200)
        b.record("src", 429)
        self.assertFalse(b.breaker_open("src"))

    def test_retry_after_opens_immediately_for_that_long(self):
        b, clock, _ = make({"src": RatePolicy(per_second=100)})
        b.record("src", 429, retry_after=75.0)
        self.assertTrue(b.breaker_open("src"))
        clock.advance(74.0)
        self.assertTrue(b.breaker_open("src"))
        clock.advance(1.5)
        self.assertFalse(b.breaker_open("src"))

    def test_network_errors_count_as_outage(self):
        b, _, _ = make({"src": RatePolicy(per_second=100)}, errors_to_open=2)
        b.record("src", None, network_error=True)
        b.record("src", None, network_error=True)
        self.assertTrue(b.breaker_open("src"))

    def test_operator_close(self):
        b, _, _ = make({"src": RatePolicy(per_second=100)})
        b.record("src", 429, retry_after=1000)
        b.close_breaker("src")
        self.assertFalse(b.breaker_open("src"))


class Blocking(unittest.TestCase):
    def test_acquire_blocking_sleeps_then_grants(self):
        b, clock, _ = make({"src": RatePolicy(per_second=1)})
        slept = []

        def fake_sleep(s):
            slept.append(s)
            clock.advance(s)

        b.acquire_blocking("src", sleep=fake_sleep)
        b.acquire_blocking("src", sleep=fake_sleep)
        self.assertEqual(len(slept), 1)
        self.assertLessEqual(slept[0], 1.0)

    def test_acquire_blocking_bounded(self):
        b, clock, _ = make({"src": RatePolicy(per_minute=1)})
        b.acquire("src")
        with self.assertRaises(BudgetExhausted):
            b.acquire_blocking("src", sleep=lambda s: clock.advance(s), max_wait=10)


class FromRows(unittest.TestCase):
    def test_policies_from_rows(self):
        pol = policies_from_rows([{"source_id": "a", "per_second": "2", "burst": 5, "per_day": None},
                                  {"source_id": "b", "per_hour": 7200}])
        self.assertEqual(pol["a"].per_second, 2.0)
        self.assertEqual(pol["a"].burst, 5)
        self.assertEqual(pol["b"].per_hour, 7200.0)
        self.assertEqual(pol["a"].windows(), [(2.5, 5.0)],
                         "burst is capacity over a sustained 2/s average, not a 5/s replacement (D-23/D-24)")
        self.assertEqual(RatePolicy(per_second=10, burst=2).windows(), [(0.2, 2.0)],
                         "a burst smaller than the rate caps the instantaneous count at the burst (D-24)")
        self.assertEqual(RatePolicy(per_second=1.5).windows(), [(1.0, 1.0)],
                         "a fractional rate above one floors: conservative, never above the limit")
        self.assertEqual(RatePolicy(per_second=0.5).windows(), [(2.0, 1.0)],
                         "a fractional rate is spacing: one call every two seconds")

    def test_fractional_rate_and_burst_are_enforced_as_documented(self):
        b, clock, _ = make({"core": RatePolicy(per_second=0.5)})
        self.assertEqual(b.acquire("core"), 0.0)
        wait = b.acquire("core")
        self.assertGreater(wait, 1.0, "0.5/s means the second call waits ~2s, not ~1s")
        clock.advance(wait)
        self.assertEqual(b.acquire("core"), 0.0)
        b2, clock2, _ = make({"doaj": RatePolicy(per_second=2, burst=5)})
        grants = sum(1 for _ in range(10) if b2.acquire("doaj") == 0.0)
        self.assertEqual(grants, 5, "burst capacity")
        clock2.advance(1.1)
        grants2 = sum(1 for _ in range(10) if b2.acquire("doaj") == 0.0)
        self.assertLess(grants2, 5, "after a burst the sustained 2/s average holds, not 5 more per second")

    def test_retry_after_http_date_and_no_shortening(self):
        import email.utils
        import time as _time
        from research_gateway.adapters.base import Response
        when = email.utils.formatdate(_time.time() + 120, usegmt=True)
        r = Response(429, {"retry-after": when}, b"", "u")
        self.assertAlmostEqual(r.retry_after_seconds(), 120, delta=5)
        b, clock, _ = make({"src": RatePolicy(per_second=100)})
        b.record("src", 429, retry_after=900)
        b.record("src", 429, retry_after=3)
        with self.assertRaises(BreakerOpen):
            b.acquire("src")
        clock.advance(10)
        with self.assertRaises(BreakerOpen):
            b.acquire("src")  # the later, shorter Retry-After did not truncate the 900s deadline

    def test_elapsed_breaker_closes_on_acquire_with_callback(self):
        events = []
        b, clock, _ = make({"src": RatePolicy(per_second=100)},
                           on_breaker_change=lambda s, state, until, reason, q=0: events.append((s, state)))
        b.record("src", 429, retry_after=5)
        clock.advance(6)
        self.assertEqual(b.acquire("src"), 0.0)
        self.assertEqual(events, [("src", "open"), ("src", "closed")])

    def test_callbacks_run_outside_the_lock_and_cannot_break_acquisition(self):
        def bad(*a):
            raise RuntimeError("listener broke")
        b, _, _ = make({"src": RatePolicy(per_second=100, per_day=10)}, on_budget=bad, on_breaker_change=bad)
        for _ in range(10):
            b.acquire("src")  # the failing budget listener never surfaces
        b.record("src", 429, retry_after=1)  # nor the failing breaker listener

    def test_seed_usage_restores_daily_budgets(self):
        b, _, _ = make({"src": RatePolicy(per_second=100, per_day=5)})
        b.seed_usage({"src": (5, 0.0), "unknown": (3, 0.0)})
        with self.assertRaises(BudgetExhausted):
            b.acquire("src")


if __name__ == "__main__":
    unittest.main()
