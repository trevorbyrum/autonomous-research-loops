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
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import adapters
from .adapters.base import Client
from .core import alerts, db, queue
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

        def on_breaker(source_id, state, retry_after_wall, reason):
            if persist is not None:
                with self._lock:
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

    # ------------------------------------------------------------ clients
    def make_client(self, conn, job: dict | None = None, client_id: str | None = None) -> Client:
        kw = {"transport": self.transport} if self.transport is not None else {}
        return Client(broker=self.broker, secrets=self.secrets.get, contact_email=self.settings.contact_email,
                      user_agent=f"research-gateway/{VERSION} (mailto:{self.settings.contact_email})",
                      conn=conn, job_id=(job or {}).get("id"), client_id=(job or {}).get("client_id") or client_id, **kw)

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
        self.stop_event.set()
        for w in self.workers:
            w.join(timeout=5)
        if self.watcher is not None:
            self.watcher.join(timeout=5)
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
        return (payload.get("request_type") in ("fetch", "data")
                or bool((payload.get("params") or {}).get("download"))
                or payload.get("what") == "full_text")

    def run_inline(self, payload: dict, client_id: str) -> dict:
        """Inline requests carry the client id into every call-log row; with a database they are as
        durable as queued ones (own connection, job_id NULL). Without a database the log is in-process
        only — that mode is for a laptop, not a deployment (docs/OPERATIONS.md)."""
        if self.conn is None:
            return execute(self.router, payload, self.make_client(None, client_id=client_id), self.cache)
        with db.connect() as conn:
            return execute(self.router, payload, self.make_client(conn, client_id=client_id), self.cache)

    def submit(self, payload: dict, client_id: str, *, priority: str = "interactive") -> tuple[int, bool]:
        with self._lock:
            return queue.enqueue(self.conn, payload["request_type"], {k: v for k, v in payload.items() if k != "request_type"},
                                 client_id=client_id, priority=PRIORITIES.get(priority, queue.PRIORITY_INTERACTIVE),
                                 topic_id=payload.get("topic_id"), commercial=bool(payload.get("commercial")))

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

    def handle(self, payload: dict, client_id: str, *, timeout: float | None = None, priority: str = "interactive") -> dict:
        """One request end to end. Inline requests (no queue, or a fetch/data/full-text payload)
        return the FULL result — redaction is a storage rule, not a delivery rule (D-24); queued
        requests store and return canonical metadata (a timeout returns the job id to poll)."""
        if self.conn is None or self.is_inline_only(payload):
            return self.run_inline(payload, client_id)
        job_id, created = self.submit(payload, client_id, priority=priority)
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
            return {"ok": ok, "version": VERSION, "mode": "queued" if self.conn is not None else "inline"}
        return {"ok": ok, "version": VERSION, "mode": "queued" if self.conn is not None else "inline", "db": db_ok,
                "workers": {"alive": alive, "expected": len(self.workers)},
                "sources": sum(1 for s in self.sources if s.get("enabled")), "uptime_s": int(time.time() - self.started_at)}

    def status(self) -> dict:
        out = {"health": self.health(detailed=True), "broker": self.broker.status(), "cache": self.cache.stats(),
               "workers": [{"name": w.name, "alive": w.is_alive(), "processed": w.processed, "error": w.error} for w in self.workers],
               "alerts": {"enabled": self.alerter.enabled, "recent": [{"at": t, "key": k, "title": ti} for t, k, ti in self.alerter.history[-10:]],
                          "watcher": {"passes": self.watcher.passes, "error": self.watcher.error} if self.watcher else None}}
        if self.conn is not None:
            with self._lock:
                out["jobs"] = queue.stats(self.conn)
        return out
