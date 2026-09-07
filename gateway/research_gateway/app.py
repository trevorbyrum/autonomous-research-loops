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
import os
import threading
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import adapters
from .adapters.base import Client
from .core import db, queue
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
    tokens: dict[str, str] = field(default_factory=dict)   # client name -> bearer token

    @property
    def host(self) -> str:
        return self.listen.rsplit(":", 1)[0]

    @property
    def port(self) -> int:
        return int(self.listen.rsplit(":", 1)[1])


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
    s.listen = env.get("RESEARCH_GATEWAY_LISTEN", s.listen)
    s.contact_email = env.get("RESEARCH_GATEWAY_CONTACT_EMAIL", s.contact_email)
    s.secrets_backend = env.get("RESEARCH_GATEWAY_SECRETS", s.secrets_backend)
    s.workers = int(env.get("RESEARCH_GATEWAY_WORKERS", s.workers))
    s.tokens = parse_tokens(env.get("RESEARCH_GATEWAY_TOKENS"))
    if not s.tokens:
        s.tokens = parse_tokens(from_config(s.secrets_backend).get("research_gateway", "tokens"))
    return s


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
                 transport=None, secrets=None):
        self.settings = settings
        self.use_db = db.configured() if use_db is None else use_db
        self.conn = db.connect() if self.use_db else None
        self.sources = sources or (sources_from_db(self.conn) if self.conn is not None else read_seed())
        if self.conn is not None:
            policies = load_policies(self.conn)
            on_change = persist_breaker(self.conn)
        else:
            rows = [{"source_id": s["id"], **(s.get("rate") or {})} for s in self.sources
                    if s.get("enabled") and (s.get("rate") or {}).get("verified")]
            policies, on_change = policies_from_rows(rows), None
        self.broker = Broker(policies, on_breaker_change=on_change)
        self.secrets = secrets if secrets is not None else from_config(settings.secrets_backend)
        self.transport = transport
        self.cache = Cache(self.conn)
        self.router = Router(self.sources, adapters.load_all())
        self.handlers = make_handlers(self.router, self.cache)
        self.stop_event = threading.Event()
        self.workers: list[queue.Worker] = []
        self.started_at = time.time()
        self._lock = threading.Lock()   # the control connection is shared by HTTP threads

    # ------------------------------------------------------------ clients
    def make_client(self, conn, job: dict | None = None) -> Client:
        kw = {"transport": self.transport} if self.transport is not None else {}
        return Client(broker=self.broker, secrets=self.secrets.get, contact_email=self.settings.contact_email,
                      user_agent=f"research-gateway/{VERSION} (mailto:{self.settings.contact_email})",
                      conn=conn, job_id=(job or {}).get("id"), **kw)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self.conn is None:
            return
        for i in range(self.settings.workers):
            w = queue.Worker(db.connect, self.handlers, self.stop_event, self.make_client, name=f"gateway-worker-{i}")
            w.start()
            self.workers.append(w)

    def stop(self) -> None:
        self.stop_event.set()
        for w in self.workers:
            w.join(timeout=5)
        if self.conn is not None:
            self.conn.close()

    # ------------------------------------------------------------ requests
    @staticmethod
    def is_inline_only(payload: dict) -> bool:
        """File bytes and full text never go through the queue (D-17)."""
        return bool((payload.get("params") or {}).get("download")) or payload.get("what") == "full_text"

    def run_inline(self, payload: dict, client_id: str) -> dict:
        if self.conn is None:
            return execute(self.router, payload, self.make_client(None), self.cache)
        with db.connect() as conn:  # own connection: the call log commits independently of the HTTP thread
            return execute(self.router, payload, self.make_client(conn), self.cache)

    def submit(self, payload: dict, client_id: str, *, priority: str = "interactive") -> tuple[int, bool]:
        with self._lock:
            return queue.enqueue(self.conn, payload["request_type"], {k: v for k, v in payload.items() if k != "request_type"},
                                 client_id=client_id, priority=PRIORITIES.get(priority, queue.PRIORITY_INTERACTIVE),
                                 topic_id=payload.get("topic_id"), commercial=bool(payload.get("commercial")))

    def job(self, job_id: int) -> dict | None:
        with self._lock:
            return queue.get(self.conn, job_id)

    def wait(self, job_id: int, timeout: float) -> dict | None:
        deadline = time.monotonic() + timeout
        while True:
            j = self.job(job_id)
            if j is None or j["status"] in ("done", "failed") or time.monotonic() >= deadline:
                return j
            time.sleep(0.1)

    def handle(self, payload: dict, client_id: str, *, timeout: float | None = None, priority: str = "interactive") -> dict:
        """One request end to end: inline when there is no queue or the payload must not be stored;
        otherwise queued, deduplicated and awaited (a timeout returns the job id to poll)."""
        if self.conn is None or self.is_inline_only(payload):
            out = self.run_inline(payload, client_id)
            return out if self.is_inline_only(payload) else redact_for_storage(out)
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

    def health(self) -> dict:
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
        return {"ok": ok, "version": VERSION, "db": db_ok, "workers": {"alive": alive, "expected": len(self.workers)},
                "sources": sum(1 for s in self.sources if s.get("enabled")), "uptime_s": int(time.time() - self.started_at)}

    def status(self) -> dict:
        out = {"health": self.health(), "broker": self.broker.status(), "cache": self.cache.stats(),
               "workers": [{"name": w.name, "alive": w.is_alive(), "processed": w.processed, "error": w.error} for w in self.workers]}
        if self.conn is not None:
            with self._lock:
                out["jobs"] = queue.stats(self.conn)
        return out
