"""Postgres job queue (PLAN.md §5): SKIP LOCKED claims, priorities, in-flight dedup.

A job is a request (find/resolve/enrich/fetch/data) with a payload. Both
front doors enqueue; worker threads in the gateway process claim and run
them through the handler registered for the request type. Identical
in-flight requests collapse onto one job (unique index on payload hash).

A handler receives `(client, job)`: the client is the metered HTTP client
built for that job by `make_client(conn, job)` (bound to the worker's
connection and the job id), so every outbound call a handler makes is
brokered and lands in `gateway.calls` with its job id (I-1, I-6).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from typing import Callable

import psycopg

REQUEST_TYPES = ("find", "resolve", "enrich", "fetch", "data")
PRIORITY_INTERACTIVE, PRIORITY_ENRICH, PRIORITY_HARVEST = 1, 5, 9

Handler = Callable[[object, dict], dict]          # (client, job) -> result
ClientFactory = Callable[[object, dict], object]  # (conn, job) -> metered client
ENQUEUE_ATTEMPTS = 10


class EnqueueContention(RuntimeError):
    """Retryable: an identical job kept racing this one to completion."""


def payload_hash(request_type: str, payload: dict, commercial: bool = False, client_id: str = "") -> str:
    """Identity of a job for in-flight dedup. The commercial flag is part of it because it changes
    which lanes may run (R-8); the client is part of it because a job, its result and its call
    rows belong to one client — two clients asking the same thing get two audited jobs (D-23)."""
    canon = json.dumps({"t": request_type, "p": payload, "c": bool(commercial), "cl": client_id},
                       sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def enqueue(conn, request_type: str, payload: dict, *, client_id: str, priority: int = PRIORITY_ENRICH,
            topic_id: str | None = None, commercial: bool = False) -> tuple[int, bool]:
    """Returns (job id, created). created=False means an identical job is already in flight."""
    if request_type not in REQUEST_TYPES:
        raise ValueError(f"unknown request type {request_type!r}")
    h = payload_hash(request_type, payload, commercial, client_id)
    in_flight ="SELECT id FROM gateway.jobs WHERE request_type = %s AND payload_hash = %s AND status IN ('queued','running')"
    # The in-flight twin can finish between our unique-violation and the re-read; then we simply insert again,
    # backing off a little each time, and give up with a retryable error only after a bounded run of flaps.
    for attempt in range(ENQUEUE_ATTEMPTS):
        if attempt:
            time.sleep(0.01 * attempt)
        with conn.cursor() as cur:
            cur.execute(in_flight, (request_type, h))
            row = cur.fetchone()
            if row:
                conn.commit()
                return row[0], False
            try:
                cur.execute(
                    "INSERT INTO gateway.jobs (request_type, payload, payload_hash, priority, client_id, topic_id, commercial) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (request_type, json.dumps(payload), h, priority, client_id, topic_id, commercial),
                )
                job_id = cur.fetchone()[0]
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                continue
        conn.commit()
        return job_id, True
    raise EnqueueContention(f"enqueue: an identical job kept appearing and finishing; retry (gave up after {ENQUEUE_ATTEMPTS} attempts)")


def claim(conn) -> dict | None:
    """Claim the highest-priority oldest queued job, or None. Commits. The claim carries a fencing
    token: only the execution holding the CURRENT token may finish or fail the job, so a stale
    worker whose job was reclaimed cannot overwrite the retry's result (D-24)."""
    token = uuid.uuid4().hex
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE gateway.jobs SET status = 'running', started_at = now(), claim_token = %s
             WHERE id = (SELECT id FROM gateway.jobs WHERE status = 'queued'
                          ORDER BY priority, created_at FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING id, request_type, payload, priority, client_id, topic_id, commercial
            """, (token,)
        )
        row = cur.fetchone()
    conn.commit()
    if not row:
        return None
    job_id, request_type, payload, priority, client_id, topic_id, commercial = row
    return {"id": job_id, "request_type": request_type, "payload": payload, "priority": priority,
            "client_id": client_id, "topic_id": topic_id, "commercial": commercial, "claim_token": token}


def finish(conn, job_id: int, result: dict, claim_token: str | None = None) -> bool:
    """False when the claim was fenced off (the job was reclaimed while this worker ran it)."""
    with conn.cursor() as cur:
        cur.execute("UPDATE gateway.jobs SET status = 'done', finished_at = now(), result = %s "
                    "WHERE id = %s AND (%s::text IS NULL OR claim_token = %s) RETURNING id",
                    (json.dumps(result), job_id, claim_token, claim_token))
        won = cur.fetchone() is not None
    conn.commit()
    return won


def fail(conn, job_id: int, error_class: str, detail: dict | None = None, claim_token: str | None = None) -> bool:
    with conn.cursor() as cur:
        cur.execute("UPDATE gateway.jobs SET status = 'failed', finished_at = now(), error_class = %s, result = %s "
                    "WHERE id = %s AND (%s::text IS NULL OR claim_token = %s) RETURNING id",
                    (error_class, json.dumps(detail or {}), job_id, claim_token, claim_token))
        won = cur.fetchone() is not None
    conn.commit()
    return won


def get(conn, job_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id, request_type, payload, priority, status, client_id, topic_id, commercial, "
                    "created_at, started_at, finished_at, result, error_class FROM gateway.jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d.name for d in cur.description]
    return dict(zip(cols, row))


def run_once(conn, handlers: dict[str, Handler], make_client: ClientFactory) -> bool:
    """Claim and execute one job. Returns False when the queue is empty."""
    job = claim(conn)
    if job is None:
        return False
    handler = handlers.get(job["request_type"])
    token = job.get("claim_token")
    if handler is None:
        fail(conn, job["id"], "refused", {"reason": f"no handler for {job['request_type']}"}, claim_token=token)
        return True
    try:
        result = handler(make_client(conn, job), job)
    except Exception as e:  # a handler bug must not take the worker down; the job records it
        fail(conn, job["id"], "outage", {"error": f"{type(e).__name__}: {e}"[:500]}, claim_token=token)
        return True
    finish(conn, job["id"], result if isinstance(result, dict) else {"result": result}, claim_token=token)
    return True


class Worker(threading.Thread):
    """A worker thread with its own connection; stops when `stop` is set."""

    def __init__(self, connect: Callable[[], psycopg.Connection], handlers: dict[str, Handler],
                 stop: threading.Event, make_client: ClientFactory, poll_seconds: float = 0.5, name: str = "gateway-worker"):
        super().__init__(name=name, daemon=True)
        # Not `_stop`: threading.Thread owns that name internally.
        self._connect, self._handlers, self._stop_event, self._poll = connect, handlers, stop, poll_seconds
        self._make_client = make_client
        self.processed = 0
        self.error: str | None = None

    def run(self) -> None:
        """A worker survives its connection: on any failure it reconnects with backoff and keeps
        claiming until stopped (D-23). The abandoned job it may have held is reclaimed by the
        lease sweep. `.error` holds the most recent failure for the status page."""
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                with self._connect() as conn:
                    self.error = None
                    backoff = 1.0
                    while not self._stop_event.is_set():
                        if run_once(conn, self._handlers, self._make_client):
                            self.processed += 1
                        else:
                            self._stop_event.wait(self._poll)
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, 60.0)


RECLAIM_AFTER_MINUTES = 30
MAX_ATTEMPTS = 3


def reclaim_stale(conn, *, after_minutes: int = RECLAIM_AFTER_MINUTES) -> tuple[int, int]:
    """Jobs stuck `running` past the lease (a worker died mid-job) go back to `queued`, up to
    MAX_ATTEMPTS; beyond that they fail with a visible reason. Returns (requeued, failed) (D-23)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE gateway.jobs SET status = 'queued', started_at = NULL, claim_token = NULL, attempts = attempts + 1 "
            "WHERE status = 'running' AND started_at < now() - make_interval(mins => %s) AND attempts < %s "
            "RETURNING id", (after_minutes, MAX_ATTEMPTS - 1))
        requeued = len(cur.fetchall())
        cur.execute(
            "UPDATE gateway.jobs SET status = 'failed', finished_at = now(), error_class = 'outage', "
            "result = %s WHERE status = 'running' AND started_at < now() - make_interval(mins => %s) "
            "AND attempts >= %s RETURNING id",
            (json.dumps({"error": f"abandoned by a dead worker {MAX_ATTEMPTS} times"}), after_minutes, MAX_ATTEMPTS - 1))
        failed = len(cur.fetchall())
    conn.commit()
    return requeued, failed


def stats(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT status, count(*) FROM gateway.jobs GROUP BY status")
        return {status: n for status, n in cur.fetchall()}
