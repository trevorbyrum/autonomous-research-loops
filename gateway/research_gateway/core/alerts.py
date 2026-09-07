"""Alerts (PLAN.md §7): trouble detection only, never automatic routing changes (D-6).

Raised when a breaker opens, a daily budget passes 80 %, a source starts failing
authentication or answering with a bot wall, a source that used to return results
for `find` returns none, or the health check fails. Delivered to an ntfy topic;
each (source, kind) fires at most once per `min_interval` so a bad hour is one
message, not a hundred.
"""
from __future__ import annotations

import base64
import os
import queue as queue_module
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

Sender = Callable[[str, str, str], None]   # (title, message, priority)


def ntfy_sender(url: str, topic: str, *, username: str | None = None, password: str | None = None,
                token: str | None = None, timeout: float = 10.0) -> Sender:
    endpoint = url.rstrip("/") + "/" + topic.strip("/")
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif username and password:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

    def send(title: str, message: str, priority: str) -> None:
        req = urllib.request.Request(endpoint, data=message.encode(), method="POST",
                                     headers={**headers, "Title": title, "Priority": priority, "Tags": "research-gateway"})
        try:
            with urllib.request.urlopen(req, timeout=timeout):
                pass
        except (urllib.error.URLError, TimeoutError, OSError):
            pass  # an alert that cannot be delivered must never take the gateway down
    return send


class Alerter:
    """Delivery runs on its own daemon thread from a bounded queue: the caller (a broker callback,
    the watcher, a request thread) never waits on the network and never sees a sender error."""

    def __init__(self, send: Sender | None, *, clock: Callable[[], float] = time.time, min_interval: float = 3600.0,
                 queue_size: int = 100):
        self._send, self._clock, self.min_interval = send, clock, min_interval
        self._last: dict[str, float] = {}
        self.history: list[tuple[float, str, str]] = []   # (when, key, title) — the status page shows the tail
        self._lock = threading.Lock()
        self._queue: queue_module.Queue = queue_module.Queue(maxsize=queue_size)
        self.dropped = 0
        self.delivered = 0
        self._thread: threading.Thread | None = None
        if send is not None:
            self._thread = threading.Thread(target=self._pump, name="gateway-alerts", daemon=True)
            self._thread.start()

    @property
    def enabled(self) -> bool:
        return self._send is not None

    def _pump(self) -> None:
        while True:
            title, message, priority = self._queue.get()
            try:
                self._send(title, message, priority)
                self.delivered += 1
            except Exception:
                pass  # a sender that fails must never take anything else down
            finally:
                self._queue.task_done()

    def flush(self, timeout: float = 5.0) -> None:
        """Wait until queued alerts are delivered (tests, shutdown)."""
        if self._thread is None:
            return
        deadline = time.monotonic() + timeout
        while not self._queue.empty() or self._queue.unfinished_tasks:
            if time.monotonic() > deadline:
                return
            time.sleep(0.01)

    def alert(self, key: str, title: str, message: str, priority: str = "default") -> bool:
        """Queue for delivery unless the same key fired within min_interval. Returns True when queued."""
        now = self._clock()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self.min_interval:
                return False
            self._last[key] = now
            self.history.append((now, key, title))
            del self.history[:-50]
        if self._send is not None:
            try:
                self._queue.put_nowait((title, message, priority))
            except queue_module.Full:
                self.dropped += 1
        return True

    # ------------------------------------------------------------ the events §7 names
    def breaker(self, source_id: str, state: str, retry_after_wall: float | None, reason: str) -> None:
        if state == "open":
            self.alert(f"breaker:{source_id}", f"{source_id}: breaker open", reason, "high")

    def budget(self, source_id: str, what: str, used: float, cap: float) -> None:
        self.alert(f"budget:{source_id}:{what}", f"{source_id}: daily {what} at {used / cap:.0%}",
                   f"{used:.0f} of {cap:.0f} {what} used today; the rest of the day runs on the substitution group when exhausted")

    def failures(self, source_id: str, failure_class: str, count: int, window_minutes: int) -> None:
        self.alert(f"{failure_class}:{source_id}", f"{source_id}: {count} {failure_class} failure(s) in {window_minutes} min",
                   "check the key or the source's terms; the lane keeps running until its breaker opens", "high")

    def zero_results(self, source_id: str, pattern: str, recent: int, earlier_hits: int) -> None:
        self.alert(f"zero:{source_id}:{pattern}", f"{source_id}: find returns nothing for a query that used to",
                   f"query {pattern!r}: {recent} calls in the last hour returned 0 results; "
                   f"{earlier_hits} call(s) returned results in the past 7 days (bot wall or index change?)", "high")

    def health(self, detail: str) -> None:
        self.alert("health", "research gateway unhealthy", detail, "urgent")


def from_env(secrets=None, environ: dict | None = None) -> Alerter:
    """An Alerter wired to ntfy when configured (RESEARCH_GATEWAY_NTFY_URL/_TOPIC, or the secrets
    backend's `ntfy` entry: url, default_topic, username/password or token); otherwise silent."""
    env = os.environ if environ is None else environ
    get = (lambda field: secrets.get("ntfy", field)) if secrets is not None else (lambda field: None)
    url = env.get("RESEARCH_GATEWAY_NTFY_URL") or get("url")
    topic = env.get("RESEARCH_GATEWAY_NTFY_TOPIC") or get("default_topic") or "research-gateway"
    if not url:
        return Alerter(None)
    return Alerter(ntfy_sender(url, topic, username=env.get("RESEARCH_GATEWAY_NTFY_USERNAME") or get("username"),
                               password=env.get("RESEARCH_GATEWAY_NTFY_PASSWORD") or get("password"),
                               token=env.get("RESEARCH_GATEWAY_NTFY_TOKEN") or get("token")))


# ---------------------------------------------------------------- the periodic checks
FAILURE_WINDOW_MIN = 10
FAILURE_THRESHOLD = 3
ZERO_MIN_CALLS = 3
# a "query pattern" is the lower-cased first 80 characters of the logged query
PATTERN_SQL = "lower(left(query, 80))"


def check_calls(conn, alerter: Alerter) -> dict:
    """One pass over gateway.calls for the patterns §7 names; returns what it saw (for tests/status).
    Also enforces call-log retention (RESEARCH_GATEWAY_CALLS_RETENTION_DAYS, default 180)."""
    retention = max(1, int(os.environ.get("RESEARCH_GATEWAY_CALLS_RETENTION_DAYS", "180") or 180))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM gateway.calls WHERE at < now() - make_interval(days => %s)", (retention,))
    conn.commit()
    seen = {"failures": [], "zero_results": []}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_id, failure_class, count(*) FROM gateway.calls "
            "WHERE at > now() - make_interval(mins => %s) AND failure_class IN ('auth', 'botwall') "
            "GROUP BY source_id, failure_class HAVING count(*) >= %s", (FAILURE_WINDOW_MIN, FAILURE_THRESHOLD))
        for source_id, failure_class, count in cur.fetchall():
            seen["failures"].append((source_id, failure_class, count))
            alerter.failures(source_id, failure_class, count, FAILURE_WINDOW_MIN)
        cur.execute(
            f"WITH recent AS (SELECT source_id, {PATTERN_SQL} AS pattern, count(*) AS n, max(result_count) AS best FROM gateway.calls "
            "  WHERE request_type = 'find' AND status = 200 AND query IS NOT NULL AND at > now() - interval '1 hour' "
            "  GROUP BY source_id, pattern), "
            f"earlier AS (SELECT source_id, {PATTERN_SQL} AS pattern, count(*) AS hits FROM gateway.calls "
            "  WHERE request_type = 'find' AND status = 200 AND result_count > 0 AND query IS NOT NULL "
            "    AND at BETWEEN now() - interval '7 days' AND now() - interval '1 hour' GROUP BY source_id, pattern) "
            "SELECT r.source_id, r.pattern, r.n, e.hits FROM recent r JOIN earlier e USING (source_id, pattern) "
            "WHERE r.n >= %s AND coalesce(r.best, 0) = 0 AND e.hits > 0", (ZERO_MIN_CALLS,))
        for source_id, pattern, n, hits in cur.fetchall():
            seen["zero_results"].append((source_id, pattern, n, hits))
            alerter.zero_results(source_id, pattern, n, hits)
    conn.commit()
    return seen


class Watcher(threading.Thread):
    """Runs check_calls and the health check every `interval` seconds on its own connection."""

    def __init__(self, connect, alerter: Alerter, health: Callable[[], dict], stop: threading.Event,
                 interval: float = 300.0, name: str = "gateway-watcher", sweep: Callable | None = None):
        super().__init__(name=name, daemon=True)
        self._connect, self._alerter, self._health, self._stop_event, self._interval = connect, alerter, health, stop, interval
        self._sweep = sweep   # e.g. the queue's stale-job reclaim, run on the watcher's cadence
        self.passes = 0
        self.error: str | None = None

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                with self._connect() as conn:
                    check_calls(conn, self._alerter)
                    if self._sweep is not None:
                        self._sweep(conn)
                h = self._health()
                if not h.get("ok"):
                    self._alerter.health(str({k: v for k, v in h.items() if k in ("db", "workers")}))
                self.passes += 1
                self.error = None
            except Exception as e:  # the watcher reports; it never dies quietly
                self.error = f"{type(e).__name__}: {e}"[:300]
                self._alerter.health(f"watcher: {self.error}")
            self._stop_event.wait(self._interval)
