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
from typing import Callable

import psycopg

REQUEST_TYPES = ("find", "resolve", "enrich", "fetch", "data")
PRIORITY_INTERACTIVE, PRIORITY_ENRICH, PRIORITY_HARVEST = 1, 5, 9

Handler = Callable[[object, dict], dict]          # (client, job) -> result
ClientFactory = Callable[[object, dict], object]  # (conn, job) -> metered client
ENQUEUE_ATTEMPTS = 10


class EnqueueContention(RuntimeError):
    """Retryable: an identical job kept racing this one to completion."""


def payload_hash(request_type: str, payload: dict, commercial: bool = False) -> str:
    """Identity of a job for in-flight dedup; the commercial flag is part of it because it
    changes which lanes may run (R-8), so a personal and a commercial twin never share a result."""
    canon = json.dumps({"t": request_type, "p": payload, "c": bool(commercial)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def enqueue(conn, request_type: str, payload: dict, *, client_id: str, priority: int = PRIORITY_ENRICH,
            topic_id: str | None = None, commercial: bool = False) -> tuple[int, bool]:
    """Returns (job id, created). created=False means an identical job is already in flight."""
    if request_type not in REQUEST_TYPES:
        raise ValueError(f"unknown request type {request_type!r}")
    h = payload_hash(request_type, payload, commercial)
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
    """Claim the highest-priority oldest queued job, or None. Commits."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE gateway.jobs SET status = 'running', started_at = now()
             WHERE id = (SELECT id FROM gateway.jobs WHERE status = 'queued'
                          ORDER BY priority, created_at FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING id, request_type, payload, priority, client_id, topic_id, commercial
            """
        )
        row = cur.fetchone()
    conn.commit()
    if not row:
        return None
    job_id, request_type, payload, priority, client_id, topic_id, commercial = row
    return {"id": job_id, "request_type": request_type, "payload": payload, "priority": priority,
            "client_id": client_id, "topic_id": topic_id, "commercial": commercial}


def finish(conn, job_id: int, result: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE gateway.jobs SET status = 'done', finished_at = now(), result = %s WHERE id = %s",
                    (json.dumps(result), job_id))
    conn.commit()


def fail(conn, job_id: int, error_class: str, detail: dict | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE gateway.jobs SET status = 'failed', finished_at = now(), error_class = %s, result = %s WHERE id = %s",
                    (error_class, json.dumps(detail or {}), job_id))
    conn.commit()


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
    if handler is None:
        fail(conn, job["id"], "refused", {"reason": f"no handler for {job['request_type']}"})
        return True
    try:
        result = handler(make_client(conn, job), job)
    except Exception as e:  # a handler bug must not take the worker down; the job records it
        fail(conn, job["id"], "outage", {"error": f"{type(e).__name__}: {e}"[:500]})
        return True
    finish(conn, job["id"], result if isinstance(result, dict) else {"result": result})
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
        try:
            with self._connect() as conn:
                while not self._stop_event.is_set():
                    if run_once(conn, self._handlers, self._make_client):
                        self.processed += 1
                    else:
                        time.sleep(self._poll)
        except Exception as e:  # surfaced to the supervisor via .error
            self.error = f"{type(e).__name__}: {e}"


def stats(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT status, count(*) FROM gateway.jobs GROUP BY status")
        return {status: n for status, n in cur.fetchall()}
