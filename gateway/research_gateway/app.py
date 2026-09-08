"""The assembled gateway process (PLAN.md §5, §9, §10): registry + broker +
secrets + cache + router + queue workers, behind one `Gateway` object that the
HTTP front door, the CLI and the tests all drive the same way.

With a database, requests are queued and served by worker threads (dedup of
in-flight twins, priorities, SKIP LOCKED). Without one, every request runs
inline through the same metered client, so a laptop can use the gateway with
nothing but the seed and environment secrets.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
import sys
import time
import tomllib
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from . import adapters
from .adapters.base import Client
from .core import alerts, calllog, db, queue
from .core.broker import Broker, load_policies, persist_breaker, policies_from_rows
from .core.cache import Cache
from .core.router import Router, execute, make_handlers, redact_for_storage
from .core.secrets import from_config
from .registry.load import read_seed

VERSION = "0.1"
LOCAL_CONFIG = Path(__file__).resolve().parent.parent / "sources.local.toml"
PRIORITIES = {"interactive": queue.PRIORITY_INTERACTIVE, "enrich": queue.PRIORITY_ENRICH, "harvest": queue.PRIORITY_HARVEST}


@dataclass
class Settings:
    listen: str = "127.0.0.1:8765"
    contact_email: str = "gateway@example.org"
    secrets_backend: str = "env"
    workers: int = 2
    sync_timeout: float = 60.0
    watch_interval: float = 300.0
    tokens: dict[str, str] = field(default_factory=dict)   # client name -> bearer token

    @property
    def host(self) -> str:
        return self.listen.rsplit(":", 1)[0]

    @property
    def port(self) -> int:
        return int(self.listen.rsplit(":", 1)[1])


# payload fields a request may carry, with the type each must have; both front doors (HTTP and
# MCP) validate through this one table before anything reaches the router or the queue (D-23)
FIELD_TYPES = {"query": str, "identity": str, "target": str, "what": str, "source": str, "kind": str, "domain": str,
               "topic_id": str, "published_after": str, "priority": str, "params": dict, "cursors": dict,
               "within": str, "cursor": (str, int),
               "commercial": bool, "accept_per_item": bool, "limit": int, "year_from": int, "timeout": (int, float)}


def validate_payload(body: dict) -> str | None:
    """The reason a body is unacceptable, or None."""
    if not isinstance(body, dict):
        return "payload must be an object"
    try:
        json.dumps(body, allow_nan=False)   # NaN/Infinity and non-JSON values end here, not in a job row
    except (TypeError, ValueError):
        return "payload must be plain JSON (no NaN/Infinity or non-JSON values)"
    download = (body.get("params") or {}).get("download") if isinstance(body.get("params"), dict) else None
    if download is not None and not isinstance(download, bool):
        return "params.download must be a boolean"
    for k, v in (body.get("cursors") or {}).items() if isinstance(body.get("cursors"), dict) else ():
        if not isinstance(v, (str, int)) or isinstance(v, bool):
            return f"cursors[{k!r}] must be a string or integer"
    for key, value in body.items():
        want = FIELD_TYPES.get(key)
        if want is None:
            return f"unknown field {key!r}"
        if value is None:
            continue
        if isinstance(value, bool) and want is not bool:
            return f"{key} must be {getattr(want, '__name__', 'a number')}"
        if not isinstance(value, want):
            return f"{key} must be {getattr(want, '__name__', 'a number')}"
        if key in ("limit", "year_from", "timeout") and value <= 0:
            return f"{key} must be positive"
    return None


def parse_tokens(text: str | None) -> dict[str, str]:
    """'loops=abc,mcp=def' → {'loops': 'abc', 'mcp': 'def'}."""
    out = {}
    for pair in (text or "").split(","):
        if "=" in pair:
            name, value = pair.split("=", 1)
            if name.strip() and value.strip():
                out[name.strip()] = value.strip()
    return out


def load_settings(path: Path | None = None, environ: dict | None = None) -> Settings:
    """sources.local.toml [gateway] with environment overrides; tokens only from the environment
    (RESEARCH_GATEWAY_TOKENS) or the secrets backend (secret 'research_gateway', field 'tokens')."""
    env = os.environ if environ is None else environ
    s = Settings()
    cfg_path = path or LOCAL_CONFIG
    if cfg_path.exists():
        with open(cfg_path, "rb") as f:
            g = tomllib.load(f).get("gateway") or {}
        s.listen = g.get("listen", s.listen)
        s.contact_email = g.get("contact_email", s.contact_email)
        s.secrets_backend = g.get("secrets_backend", s.secrets_backend)
        s.workers = int(g.get("workers", s.workers))
        s.sync_timeout = float(g.get("sync_timeout", s.sync_timeout))
        s.watch_interval = float(g.get("watch_interval", s.watch_interval))
    s.listen = env.get("RESEARCH_GATEWAY_LISTEN", s.listen)
    s.contact_email = env.get("RESEARCH_GATEWAY_CONTACT_EMAIL", s.contact_email)
    s.secrets_backend = env.get("RESEARCH_GATEWAY_SECRETS", s.secrets_backend)
    s.workers = int(env.get("RESEARCH_GATEWAY_WORKERS", s.workers))
    s.tokens = parse_tokens(env.get("RESEARCH_GATEWAY_TOKENS"))
    if not s.tokens:
        s.tokens = parse_tokens(from_config(s.secrets_backend).get("research_gateway", "tokens"))
    return s


def todays_usage(conn) -> dict[str, tuple[int, float]]:
    """Per-source dispatched/credit counts for the current UTC day, from the call log — the shared
    record every gateway or maintenance process writes, so budgets are owned jointly (I-1, D-23)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_id, count(*), coalesce(sum(credits), 0) FROM gateway.calls "
            "WHERE at >= date_trunc('day', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc' "
            "AND failure_class NOT IN ('refused') AND NOT cache_hit GROUP BY source_id")
        # 'redirect' rows count: each validated hop was a real dispatch; credits appear once per
        # request (only the first hop's row carries them), so the sum matches what was charged (D-24)
        usage = {sid: (int(n), float(c)) for sid, n, c in cur.fetchall()}
    conn.commit()
    return usage


def open_breakers(conn) -> list[tuple[str, float]]:
    """(source_id, seconds remaining) for breakers persisted open with time still on the clock."""
    with conn.cursor() as cur:
        cur.execute("SELECT source_id, greatest(0, extract(epoch FROM retry_after - now())) FROM gateway.breakers "
                    "WHERE state = 'open' AND retry_after > now()")
        rows = [(sid, float(secs)) for sid, secs in cur.fetchall()]
    conn.commit()
    return rows


def sources_from_db(conn) -> list[dict]:
    cols = ("id", "name", "kind", "capabilities", "identifiers", "base_for", "domains", "auth", "secret_ref",
            "use_commercial", "substitution_group", "enabled")
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(cols)} FROM gateway.sources ORDER BY id")
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.commit()
    seed_order = {s["id"]: i for i, s in enumerate(read_seed())}
    rows.sort(key=lambda r: seed_order.get(r["id"], len(seed_order)))  # lane order = seed order (§4)
    return rows


class Gateway:
    def __init__(self, settings: Settings, *, use_db: bool | None = None, sources: list[dict] | None = None,
                 transport=None, secrets=None, alerter: alerts.Alerter | None = None):
        self.settings = settings
        self.use_db = db.configured() if use_db is None else use_db
        self.conn = db.connect() if self.use_db else None
        self._lock = threading.Lock()   # the control connection is shared by HTTP threads and callbacks
        self.sources = sources or (sources_from_db(self.conn) if self.conn is not None else read_seed())
        self.secrets = secrets if secrets is not None else from_config(settings.secrets_backend)
        self.alerter = alerter if alerter is not None else alerts.from_env(self.secrets)
        if self.conn is not None:
            policies = load_policies(self.conn)
            persist = persist_breaker(self.conn)
        else:
            rows = [{"source_id": s["id"], **(s.get("rate") or {})} for s in self.sources
                    if s.get("enabled") and (s.get("rate") or {}).get("verified")]
            policies, persist = policies_from_rows(rows), None

        applied_breaker_seq: dict[str, int] = {}

        def on_breaker(source_id, state, retry_after_wall, reason, seq=0):
            # callbacks deliver OUTSIDE the broker lock and can reorder under concurrency:
            # only monotonically newer events reach persistence, so a delayed older deadline
            # can never regress the live broker's state (9·2b, plan v3)
            with self._lock:
                if seq and seq <= applied_breaker_seq.get(source_id, 0):
                    return
                if seq:
                    applied_breaker_seq[source_id] = seq
                if persist is not None:
                    persist(source_id, state, retry_after_wall, reason)
            self.alerter.breaker(source_id, state, retry_after_wall, reason)

        self.broker = Broker(policies, on_breaker_change=on_breaker, on_budget=self.alerter.budget)
        if self.conn is not None:
            self.broker.seed_usage(todays_usage(self.conn))       # budgets survive restarts (D-23)
            self.broker.seed_breakers(open_breakers(self.conn))   # so do open breakers (D-25)
        self.transport = transport
        # the cache persists from worker threads and HTTP threads alike: it gets its own connection and lock
        self.cache = Cache(db.connect() if self.conn is not None else None)
        self.router = Router(self.sources, adapters.load_all())
        self.handlers = make_handlers(self.router, self.cache)
        self.stop_event = threading.Event()
        self.workers: list[queue.Worker] = []
        self.watcher: alerts.Watcher | None = None
        self.started_at = time.time()
        # 9·2b lifecycle: inline requests are USERS of the shared connections too — they are
        # counted in, refused during drain, and waited for before anything shared is closed
        self._inline_lock = threading.Lock()
        self._inline_cv = threading.Condition(self._inline_lock)
        self._inline_active = 0
        self._draining = False

    def _enter_request(self) -> None:
        with self._inline_lock:
            if self._draining:
                raise RuntimeError("gateway is stopping; no new requests")
            self._inline_active += 1

    def _exit_request(self) -> None:
        with self._inline_lock:
            self._inline_active -= 1
            self._inline_cv.notify_all()

    # ------------------------------------------------------------ clients
    def make_client(self, conn, job: dict | None = None, client_id: str | None = None,
                    iteration: str | None = None, batch_entry: int | None = None,
                    topic: str | None = None) -> Client:
        kw = {"transport": self.transport} if self.transport is not None else {}
        return Client(broker=self.broker, secrets=self.secrets.get, contact_email=self.settings.contact_email,
                      user_agent=f"research-gateway/{VERSION} (mailto:{self.settings.contact_email})",
                      conn=conn, job_id=(job or {}).get("id"), client_id=(job or {}).get("client_id") or client_id,
                      iteration=(job or {}).get("iteration") or iteration,
                      batch_entry=(job or {}).get("batch_entry") if (job or {}).get("batch_entry") is not None else batch_entry,
                      topic=(job or {}).get("topic_id") or (job or {}).get("topic") or topic,
                      **kw)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self.conn is None:
            return
        for i in range(self.settings.workers):
            w = queue.Worker(db.connect, self.handlers, self.stop_event, self.make_client, name=f"gateway-worker-{i}")
            w.start()
            self.workers.append(w)
        self.watcher = alerts.Watcher(db.connect, self.alerter, lambda: self.health(detailed=True), self.stop_event,
                                      interval=self.settings.watch_interval,
                                      sweep=lambda conn: queue.reclaim_stale(conn))
        self.watcher.start()

    def stop(self) -> None:
        """Drain before closing (9-2b): workers and the watcher are JOINED - a lane can sit in
        a legitimate broker wait or provider request far past any polite timeout, and its
        eventual broker callback or cache write must never land on a closed connection. If a
        thread will not finish inside RESEARCH_GATEWAY_STOP_TIMEOUT (default 300 s), shared
        connections are LEFT OPEN (the process is exiting anyway): a leak on the way out is
        safe; a use-after-close is not."""
        self.stop_event.set()
        with self._inline_lock:
            self._draining = True   # no NEW inline users from here; existing ones are waited for below
        deadline = time.monotonic() + max(1.0, float(os.environ.get("RESEARCH_GATEWAY_STOP_TIMEOUT", "300") or 300))
        stragglers = []
        for w in [*self.workers, *([self.watcher] if self.watcher is not None else [])]:
            w.join(timeout=max(0.1, deadline - time.monotonic()))
            if w.is_alive():
                stragglers.append(w.name)
        with self._inline_cv:
            while self._inline_active and time.monotonic() < deadline:
                self._inline_cv.wait(timeout=max(0.1, deadline - time.monotonic()))
            if self._inline_active:
                stragglers.append(f"{self._inline_active} inline request(s)")
        if stragglers:
            print(f"gateway stop: {len(stragglers)} thread(s) still running after the drain timeout "
                  f"({', '.join(stragglers)}); shared connections left open for process exit", file=sys.stderr)
            return
        if self.conn is not None:
            self.conn.close()
        if self.cache.conn is not None:
            self.cache.conn.close()

    # ------------------------------------------------------------ requests
    @staticmethod
    def is_inline_only(payload: dict) -> bool:
        """`fetch` and `data` requests are ALWAYS inline: their results are rows, files and text —
        things that are delivered and discarded, never stored in a job result (D-17, D-24). So is a
        full-text enrichment. The queue serves find/resolve/enrich, whose results are metadata."""
        return (payload.get("request_type") in ("fetch", "data", "catalog")
                or bool((payload.get("params") or {}).get("download"))
                or payload.get("what") == "full_text")

    def run_inline(self, payload: dict, client_id: str, trace: dict | None = None) -> dict:
        """Inline requests carry the client id into every call-log row; with a database they are as
        durable as queued ones (own connection, job_id NULL). Without a database the log is in-process
        only — that mode is for a laptop, not a deployment (docs/OPERATIONS.md)."""
        trace = trace or {}
        self._enter_request()
        try:
            return self._run_inline_locked(payload, client_id, trace)
        finally:
            self._exit_request()

    def _run_inline_locked(self, payload: dict, client_id: str, trace: dict) -> dict:
        if self.conn is None:
            return execute(self.router, payload, self.make_client(None, client_id=client_id, **trace), self.cache)
        with db.connect() as conn:
            return execute(self.router, payload, self.make_client(conn, client_id=client_id, **trace), self.cache)

    def submit(self, payload: dict, client_id: str, *, priority: str = "interactive",
               iteration: str | None = None, batch_entry: int | None = None,
               topic: str | None = None) -> tuple[int, bool]:
        with self._lock:
            job_id, created = queue.enqueue(self.conn, payload["request_type"], {k: v for k, v in payload.items() if k != "request_type"},
                                            client_id=client_id, priority=PRIORITIES.get(priority, queue.PRIORITY_INTERACTIVE),
                                            topic_id=payload.get("topic_id"), commercial=bool(payload.get("commercial")),
                                            iteration=iteration, batch_entry=batch_entry, topic=topic)
            if not created:
                # the coalesced WAITER's request observation (9·0 amendment): the shared dispatch
                # stays the creator's; each later caller still leaves a durable row under its own
                # tracing. Telemetry only — its failure never blocks the request itself.
                try:
                    calllog.record(self.conn, calllog.CallRecord(
                        source_id="coalesce", request_type=payload["request_type"], status=200, latency_ms=0,
                        job_id=job_id, identity=payload.get("identity") or payload.get("target"),
                        query=(payload.get("query") or "")[:500] or None, failure_class="ok",
                        client_id=client_id, iteration=iteration, batch_entry=batch_entry,
                        topic=payload.get("topic_id") or topic))
                except Exception:
                    pass
            return job_id, created

    def job(self, job_id: int, client_id: str | None = None) -> dict | None:
        """A job, or None; with client_id, only that client's own job (clients never see each other's)."""
        with self._lock:
            j = queue.get(self.conn, job_id)
        if j is not None and client_id is not None and j.get("client_id") != client_id:
            return None
        return j

    def wait(self, job_id: int, timeout: float) -> dict | None:
        deadline = time.monotonic() + timeout
        while True:
            j = self.job(job_id)
            if j is None or j["status"] in ("done", "failed") or time.monotonic() >= deadline:
                return j
            time.sleep(0.1)

    def source_descriptions(self, source: str | None = None) -> dict:
        """The registry, projected for agents (research_sources, D-31): public-safe fields only —
        never a secret reference or a key. With `source`, that source's exact declared data
        contract and capabilities; without, concise summaries of every registered source."""
        from .adapters.base import data_contract
        public = ("id", "name", "kind", "homepage", "capabilities", "identifiers", "base_for",
                  "domains", "use_commercial", "license", "freshness_lag", "enabled")
        if source is None:
            return {"sources": [{k: s.get(k) for k in public} for s in self.sources]}
        row = next((s for s in self.sources if s.get("id") == source), None)
        if row is None:
            return {"capability_fact": "gateway_error_404",
                    "error": f"unknown source {source!r} — call research_sources with no arguments for the list"}
        out = {k: row.get(k) for k in public}
        mod = self.router.adapters.get(source)
        if mod is not None:
            contract = data_contract(mod)
            if contract:
                out["data_params"] = contract
            for attr, key in (("ENRICHES", "enriches"), ("SCHEMES", "schemes"), ("HOSTS", "hosts")):
                value = getattr(mod, attr, None)
                if value:
                    out[key] = list(value)
        return out

    def handle(self, payload: dict, client_id: str, *, timeout: float | None = None, priority: str = "interactive",
               trace: dict | None = None) -> dict:
        """One request end to end. Inline requests (no queue, or a fetch/data/full-text payload)
        return the FULL result — redaction is a storage rule, not a delivery rule (D-24); queued
        requests store and return canonical metadata (a timeout returns the job id to poll)."""
        # the request — its telemetry tail INCLUDED — is a counted lifecycle user of the
        # shared connections: stop() cannot close them between the work and the span write
        self._enter_request()
        t0 = time.monotonic()
        started_at = datetime.now(timezone.utc)
        try:
            out = self._handle(payload, client_id, timeout=timeout, priority=priority, trace=trace)
        finally:
            # the CALLER's request span (9·0 amendment): one `request` row per handled request —
            # coalesced waiters and cache-served callers included. `at` is the TRUE recorded
            # start (immune to lock wait before the write); the duration is measured AT WRITE
            # TIME, so time the caller spent waiting on the control lock is part of the span.
            try:
                if self.conn is not None:
                    with self._lock:
                        calllog.record(self.conn, calllog.CallRecord(
                            source_id="request", request_type=payload.get("request_type") or "?",
                            status=200, latency_ms=int((time.monotonic() - t0) * 1000),
                            at_utc=started_at,
                            identity=payload.get("identity") or payload.get("target"),
                            query=(payload.get("query") or "")[:500] or None, failure_class="ok",
                            client_id=client_id, iteration=(trace or {}).get("iteration"),
                            batch_entry=(trace or {}).get("batch_entry"),
                            topic=payload.get("topic_id") or (trace or {}).get("topic")))
            except Exception:
                pass
            finally:
                self._exit_request()
        return out

    def _handle(self, payload: dict, client_id: str, *, timeout: float | None = None, priority: str = "interactive",
                trace: dict | None = None) -> dict:
        if payload.get("request_type") == "data":
            # validate against the adapter's DECLARED contract before any budget or dispatch:
            # a blind call fails instantly WITH the contract, so the first mistake teaches (D-31)
            from .adapters.base import data_contract, validate_data_params
            mod = self.router.adapters.get(payload.get("source") or "")
            if mod is not None:
                problem = validate_data_params(mod, payload.get("params"))
                if problem:
                    return {"capability_fact": "gateway_error_400",
                            "error": f"{payload.get('source')}: {problem}",
                            "contract": data_contract(mod)}
        if self.conn is None or self.is_inline_only(payload):
            return self.run_inline(payload, client_id, trace=trace)
        job_id, created = self.submit(payload, client_id, priority=priority,
                                      iteration=(trace or {}).get("iteration"),
                                      batch_entry=(trace or {}).get("batch_entry"),
                                      topic=(trace or {}).get("topic"))
        j = self.wait(job_id, self.settings.sync_timeout if timeout is None else timeout)
        if j is None or j["status"] not in ("done", "failed"):
            return {"job_id": job_id, "status": "queued" if j is None else j["status"], "created": created}
        result = j.get("result") or {}
        if j["status"] == "failed":
            result = {"facts": [f"job failed: {j.get('error_class')}"], "records": [], **result}
        return {"job_id": job_id, "status": j["status"], "created": created, **result}

    # ------------------------------------------------------------ auth + status
    def authenticate(self, header: str | None) -> str | None:
        """Bearer token → client name, or None."""
        if not header or not header.lower().startswith("bearer "):
            return None
        presented = header.split(" ", 1)[1].strip()
        for name, token in self.settings.tokens.items():
            if hmac.compare_digest(presented, token):
                return name
        return None

    def health(self, detailed: bool = False) -> dict:
        """Unauthenticated callers get ok/version only; the authenticated status carries the detail."""
        db_ok = None
        if self.conn is not None:
            try:
                with self._lock, self.conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                self.conn.commit()
                db_ok = True
            except Exception as e:  # health must answer even when the database is gone
                db_ok = f"{type(e).__name__}: {e}"[:200]
        alive = sum(1 for w in self.workers if w.is_alive())
        ok = (db_ok in (None, True)) and (self.conn is None or alive == len(self.workers))
        if not detailed:
            # non-sensitive in-memory aggregates so a station can stamp PER-ITERATION provider
            # health into its measurement record without a bearer token (9·0 amendment): counts
            # only — never source names, deadlines, or anything a token-holder gets from /v1/status
            try:
                breakers_open = sum(1 for st in self.broker.status().values() if st.get("breaker_open"))
            except Exception:
                breakers_open = None
            cache_records = None
            if self.cache.conn is not None:
                with self.cache._lock:   # the CACHE's own lock guards its connection AND transaction
                    try:  # planner ESTIMATE — instant, never a live count over a large table
                        with self.cache.conn.cursor() as cur:
                            cur.execute("SELECT reltuples::bigint FROM pg_class "
                                        "WHERE oid = 'gateway.records'::regclass")
                            row = cur.fetchone()
                        self.cache.conn.commit()
                        cache_records = int(row[0]) if row else None
                    except Exception:
                        try:   # telemetry must NEVER leave the shared transaction aborted for
                            self.cache.conn.rollback()   # the next real cache lookup
                        except Exception:
                            pass
                        cache_records = None
            mem = self.cache.stats()   # the cache's OWN synchronized, expiry-aware aggregates
            return {"ok": ok, "version": VERSION, "mode": "queued" if self.conn is not None else "inline",
                    "workers_alive": alive, "breakers_open": breakers_open,
                    "cache_memory": mem.get("records_in_memory", 0) + mem.get("searches_in_memory", 0),
                    "cache_searches_memory": mem.get("searches_in_memory", 0),
                    "cache_records_estimate": cache_records,
                    # EFFECTIVE values, clamped exactly as execution clamps them (router max(1, ...))
                    "lane_concurrency": max(1, int(os.environ.get("RESEARCH_GATEWAY_LANE_CONCURRENCY", "4") or 4)),
                    "lane_total": max(1, int(os.environ.get("RESEARCH_GATEWAY_LANE_TOTAL", "16") or 16))}
        return {"ok": ok, "version": VERSION, "mode": "queued" if self.conn is not None else "inline", "db": db_ok,
                "workers": {"alive": alive, "expected": len(self.workers)},
                "sources": sum(1 for s in self.sources if s.get("enabled")), "uptime_s": int(time.time() - self.started_at)}

    def status(self) -> dict:
        out = {"health": self.health(detailed=True), "broker": self.broker.status(), "cache": self.cache.stats(),
               "workers": [{"name": w.name, "alive": w.is_alive(), "processed": w.processed, "error": w.error} for w in self.workers],
               "alerts": {"enabled": self.alerter.enabled, "delivered": self.alerter.delivered,
                          "delivery_failures": self.alerter.delivery_failures, "dropped": self.alerter.dropped,
                          "recent": [{"at": t, "key": k, "title": ti} for t, k, ti in self.alerter.history[-10:]],
                          "watcher": {"passes": self.watcher.passes, "error": self.watcher.error,
                                      "seconds_since_pass": (time.time() - self.watcher.last_pass_at
                                                             if self.watcher.last_pass_at else None)}
                          if self.watcher else None}}
        if self.conn is not None:
            with self._lock:
                out["jobs"] = {**queue.stats(self.conn), **queue.oldest_ages(self.conn)}
                out["harvest"] = self._harvest_state()
        return out

    def _harvest_state(self) -> dict:
        """Last PROVEN-complete harvest per loader (gateway.meta, written only after a loader
        finishes — partial batch commits make 'last row updated' insufficient, 8f)."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT key, value, updated_at FROM gateway.meta WHERE key LIKE 'harvest:%'")
                rows = cur.fetchall()
            self.conn.commit()
            return {key.split(":", 1)[1]: {**value, "updated_at": str(at)} for key, value, at in rows}
        except Exception:  # a pre-8f database without gateway.meta still answers status
            try:
                self.conn.rollback()
            except Exception:
                pass
            return {}
