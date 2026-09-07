"""Rate broker: the single owner of every source's limits (PLAN.md I-1, I-3, §5).

One `Broker` per gateway process. `acquire()` is called before every outbound
call; it either grants immediately, tells the caller how long to wait, or
refuses (no policy, open breaker, exhausted daily budget). `record()` is
called after every call so limit errors can open the breaker and `Retry-After`
is honoured.

Second/minute/hour windows are sliding: a request is allowed when fewer than
`per_<window>` dispatches happened in the trailing window. That is exact, needs
no refill maths, and is easy to test with an injected clock. Daily budgets
(`per_day`, `cost_cap_per_day`) are counters per UTC day (§5). A limit error
without `Retry-After` backs the source off 10→80 s before the breaker opens.

Callbacks (breaker changes, budget warnings) are invoked after the broker's
lock is released, so a slow or faulty listener can never stall acquisitions.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


@dataclass(frozen=True)
class RatePolicy:
    per_second: float | None = None
    per_minute: float | None = None
    per_hour: float | None = None
    per_day: float | None = None
    cost_cap_per_day: float | None = None
    burst: int | None = None

    def windows(self) -> list[tuple[float, float]]:
        """(window length in seconds, allowed count) for each configured limit.

        A fractional per-second rate becomes one call per 1/rate seconds (0.5/s = every 2 s,
        not 1/s). `burst` is CAPACITY on top of the sustained rate, not a replacement: it widens
        the short window to `burst` calls while a second window holds the average at the
        sustained rate (D-23)."""
        out = []
        if self.per_second:
            ps = float(self.per_second)
            if self.burst:
                # one window says it all: at most `burst` in any burst/rate seconds — that is an
                # instantaneous cap of `burst` AND a sustained average of `rate`, whether the
                # burst is larger or smaller than the per-second figure (D-24)
                bp = float(self.burst)
                out.append((bp / ps, bp))
            elif ps >= 1.0:
                out.append((1.0, float(int(ps))))   # 1.5/s floors to 1/s: conservative, never above the limit
            else:
                out.append((1.0 / ps, 1.0))
        if self.per_minute:
            out.append((60.0, float(self.per_minute)))
        if self.per_hour:
            out.append((3600.0, float(self.per_hour)))
        return out

    def is_empty(self) -> bool:
        return not self.windows() and not self.per_day and not self.cost_cap_per_day


class NoPolicy(Exception):
    """The source has no rate policy: it must not be scheduled (I-3)."""


class BreakerOpen(Exception):
    def __init__(self, source_id: str, until: float, reason: str):
        super().__init__(f"{source_id}: breaker open until {until:.0f} ({reason})")
        self.source_id, self.until, self.reason = source_id, until, reason


class BudgetExhausted(Exception):
    def __init__(self, source_id: str, what: str):
        super().__init__(f"{source_id}: daily {what} exhausted")
        self.source_id, self.what = source_id, what


@dataclass
class _State:
    windows: list[deque]
    consecutive_limit_errors: int = 0
    backoff_until: float = 0.0
    breaker_until: float = 0.0
    breaker_reason: str = ""
    day: str = ""
    credits_today: float = 0.0
    dispatched_today: int = 0
    budget_alerted: dict = field(default_factory=dict)   # what -> set of UTC days already reported at 80 %


class Broker:
    LIMIT_STATUSES = {429, 503}

    def __init__(
        self,
        policies: dict[str, RatePolicy],
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        breaker_window: float = 900.0,
        errors_to_open: int = 3,
        on_breaker_change: Callable[[str, str, float | None, str], None] | None = None,
        on_budget: Callable[[str, str, float, float], None] | None = None,
        budget_warn: float = 0.8,
    ):
        self._policies = dict(policies)
        self._clock, self._wall = clock, wall
        self._breaker_window, self._errors_to_open = breaker_window, errors_to_open
        self._on_breaker_change = on_breaker_change
        self._on_budget, self._budget_warn = on_budget, budget_warn   # (source, what, used, cap) once per UTC day (§7)
        self._lock = threading.Lock()
        self._state: dict[str, _State] = {}

    # ---------------------------------------------------------------- policies
    def has_policy(self, source_id: str) -> bool:
        p = self._policies.get(source_id)
        return p is not None and not p.is_empty()

    def policy(self, source_id: str) -> RatePolicy:
        return self._policies[source_id]

    def _state_for(self, source_id: str) -> _State:
        st = self._state.get(source_id)
        if st is None:
            st = _State(windows=[deque() for _ in self._policies[source_id].windows()])
            self._state[source_id] = st
        today = datetime.fromtimestamp(self._wall(), timezone.utc).strftime("%Y-%m-%d")
        if st.day != today:
            st.day, st.credits_today, st.dispatched_today = today, 0.0, 0
        return st

    @staticmethod
    def _fire(pending: list) -> None:
        """Run listener callbacks outside the lock; a listener's failure is its own problem."""
        for fn in pending:
            try:
                fn()
            except Exception:
                pass

    # ---------------------------------------------------------------- acquire
    def acquire(self, source_id: str, *, credits: float = 0.0) -> float:
        """Reserve one dispatch. Returns seconds to wait before sending (0 = now).

        Raises NoPolicy, BreakerOpen, or BudgetExhausted. A positive wait means
        the reservation is NOT taken; call again after waiting.
        """
        if not self.has_policy(source_id):
            raise NoPolicy(source_id)
        pending: list = []
        try:
            return self._acquire_locked(source_id, credits, pending)
        finally:
            self._fire(pending)   # a raise between state change and callbacks never swallows them (D-24)

    def _acquire_locked(self, source_id: str, credits: float, pending: list) -> float:
        with self._lock:
            st = self._state_for(source_id)
            now = self._clock()
            if st.breaker_until > now:
                raise BreakerOpen(source_id, st.breaker_until, st.breaker_reason)
            if st.breaker_until:  # the window elapsed: the breaker closes on the next acquisition, observably
                st.breaker_until, st.breaker_reason = 0.0, ""
                if self._on_breaker_change:
                    pending.append(lambda s=source_id: self._on_breaker_change(s, "closed", None, "window elapsed"))
            pol = self._policies[source_id]
            if pol.cost_cap_per_day and st.credits_today + credits > pol.cost_cap_per_day:
                raise BudgetExhausted(source_id, "cost cap")
            if pol.per_day and st.dispatched_today >= pol.per_day:
                raise BudgetExhausted(source_id, "request budget")
            wait = max(0.0, st.backoff_until - now)
            for (length, allowed), dq in zip(pol.windows(), st.windows):
                while dq and dq[0] <= now - length:
                    dq.popleft()
                if len(dq) >= allowed:
                    wait = max(wait, dq[0] + length - now)
            if wait > 0:
                return wait
            for dq in st.windows:
                dq.append(now)
            st.credits_today += credits
            st.dispatched_today += 1
            if self._on_budget:
                self._budget_watch(source_id, pol, st, pending)
            return 0.0

    def _budget_watch(self, source_id: str, pol: RatePolicy, st: _State, pending: list) -> None:
        for what, used, cap in (("requests", st.dispatched_today, pol.per_day), ("credits", st.credits_today, pol.cost_cap_per_day)):
            if cap and used >= self._budget_warn * cap and st.day not in st.budget_alerted.get(what, set()):
                st.budget_alerted.setdefault(what, set()).add(st.day)
                pending.append(lambda s=source_id, w=what, u=float(used), c=float(cap): self._on_budget(s, w, u, c))

    def acquire_blocking(self, source_id: str, *, credits: float = 0.0, sleep: Callable[[float], None] = time.sleep,
                         max_wait: float = 120.0) -> None:
        """Wait (bounded) until a reservation is granted; raises like acquire()."""
        waited = 0.0
        while True:
            wait = self.acquire(source_id, credits=credits)
            if wait <= 0:
                return
            if waited + wait > max_wait:
                raise BudgetExhausted(source_id, f"wait exceeds {max_wait:.0f}s")
            sleep(wait)
            waited += wait

    # ---------------------------------------------------------------- results
    def record(self, source_id: str, status: int | None, *, retry_after: float | None = None,
               network_error: bool = False) -> None:
        """Feed the outcome of a call back so breakers reflect reality (§5)."""
        pending: list = []
        with self._lock:
            st = self._state_for(source_id)
            limited = (status in self.LIMIT_STATUSES) or network_error or (status is not None and status >= 500)
            if not limited:
                st.consecutive_limit_errors, st.backoff_until = 0, 0.0
            else:
                st.consecutive_limit_errors += 1
                if retry_after is not None:
                    self._open(source_id, st, retry_after, f"retry-after {retry_after:.0f}s (status {status})", pending)
                elif st.consecutive_limit_errors >= self._errors_to_open:
                    self._open(source_id, st, self._breaker_window, f"{st.consecutive_limit_errors} consecutive limit/outage errors", pending)
                else:
                    st.backoff_until = self._clock() + min(10.0 * 2 ** (st.consecutive_limit_errors - 1), 80.0)
        self._fire(pending)

    def _open(self, source_id: str, st: _State, seconds: float, reason: str, pending: list) -> None:
        until = self._clock() + seconds
        if until <= st.breaker_until:
            return  # a shorter, later-arriving Retry-After never truncates an active deadline (D-23)
        st.breaker_until = until
        st.breaker_reason = reason
        st.consecutive_limit_errors, st.backoff_until = 0, 0.0
        if self._on_breaker_change:
            wall_until = self._wall() + seconds
            pending.append(lambda: self._on_breaker_change(source_id, "open", wall_until, reason))

    def breaker_open(self, source_id: str) -> bool:
        pending: list = []
        with self._lock:
            st = self._state.get(source_id)
            if st is None:
                return False
            if st.breaker_until and st.breaker_until <= self._clock():
                st.breaker_until = 0.0
                if self._on_breaker_change:
                    pending.append(lambda: self._on_breaker_change(source_id, "closed", None, "window elapsed"))
                result = False
            else:
                result = st.breaker_until > self._clock()
        self._fire(pending)
        return result

    def close_breaker(self, source_id: str) -> None:
        with self._lock:
            st = self._state.get(source_id)
            if st:
                st.breaker_until, st.breaker_reason, st.consecutive_limit_errors = 0.0, "", 0
        if self._on_breaker_change:
            self._fire([lambda: self._on_breaker_change(source_id, "closed", None, "operator")])

    def seed_usage(self, usage: dict[str, tuple[int, float]]) -> None:
        """Restore today's dispatched/credit counters (from gateway.calls) so a restart never
        resets a daily budget (D-23). Only counts for the current UTC day should be passed."""
        with self._lock:
            for source_id, (dispatched, credits) in usage.items():
                if source_id not in self._policies:
                    continue
                st = self._state_for(source_id)
                st.dispatched_today = max(st.dispatched_today, int(dispatched))
                st.credits_today = max(st.credits_today, float(credits or 0.0))

    # ---------------------------------------------------------------- status
    def status(self) -> dict[str, dict]:
        with self._lock:
            out = {}
            for sid, st in self._state.items():
                pol = self._policies[sid]
                out[sid] = {
                    "breaker_open": st.breaker_until > self._clock(),
                    "breaker_reason": st.breaker_reason,
                    "backoff_seconds": max(0.0, st.backoff_until - self._clock()),
                    "dispatched_today": st.dispatched_today,
                    "credits_today": st.credits_today,
                    "per_day": pol.per_day,
                    "cost_cap_per_day": pol.cost_cap_per_day,
                }
            return out


def policies_from_rows(rows: list[dict]) -> dict[str, RatePolicy]:
    """Build policies from `gateway.rate_policies` rows (dicts keyed by column)."""
    out = {}
    for r in rows:
        out[r["source_id"]] = RatePolicy(
            per_second=float(r["per_second"]) if r.get("per_second") else None,
            per_minute=float(r["per_minute"]) if r.get("per_minute") else None,
            per_hour=float(r["per_hour"]) if r.get("per_hour") else None,
            per_day=float(r["per_day"]) if r.get("per_day") else None,
            cost_cap_per_day=float(r["cost_cap_per_day"]) if r.get("cost_cap_per_day") else None,
            burst=int(r["burst"]) if r.get("burst") else None,
        )
    return out


def load_policies(conn) -> dict[str, RatePolicy]:
    """Policies for enabled, rate-verified sources only (PLAN §3)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.source_id, p.per_second, p.per_minute, p.per_hour, p.per_day, p.cost_cap_per_day, p.burst "
            "FROM gateway.rate_policies p JOIN gateway.sources s ON s.id = p.source_id "
            "WHERE s.enabled AND p.verified"
        )
        cols = [d.name for d in cur.description]
        return policies_from_rows([dict(zip(cols, row)) for row in cur.fetchall()])


def persist_breaker(conn) -> Callable[[str, str, float | None, str], None]:
    """on_breaker_change callback that mirrors state into gateway.breakers."""
    def _cb(source_id: str, state: str, retry_after_wall: float | None, reason: str) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO gateway.breakers (source_id, state, opened_at, retry_after, reason) "
                "VALUES (%s, %s, CASE WHEN %s = 'open' THEN now() END, to_timestamp(%s), %s) "
                "ON CONFLICT (source_id) DO UPDATE SET state = EXCLUDED.state, opened_at = EXCLUDED.opened_at, "
                "retry_after = EXCLUDED.retry_after, reason = EXCLUDED.reason",
                (source_id, state, state, retry_after_wall, reason),
            )
        conn.commit()
    return _cb
