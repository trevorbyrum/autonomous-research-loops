"""Every outbound call is a row in gateway.calls (PLAN.md I-6)."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict


@dataclass
class CallRecord:
    source_id: str
    request_type: str
    status: int | None
    latency_ms: int
    job_id: int | None = None
    identity: str | None = None
    query: str | None = None
    ratelimit: dict | None = None
    credits: float | None = None
    cache_hit: bool = False
    result_count: int | None = None
    failure_class: str = "ok"
    domain_resolved: str | None = None
    client_id: str | None = None   # which front-door client asked (queued jobs carry it; inline requests set it directly)


def classify(status: int | None, *, network_error: bool = False, body: str = "") -> str:
    """Map an outcome to the failure classes the plan names (§2 gateway.calls)."""
    if network_error:
        return "outage"
    if status is None:
        return "outage"
    if status in (401, 403):
        return "botwall" if ("challenge" in body.lower() or "cloudflare" in body.lower() or "anubis" in body.lower()) else "auth"
    if status == 429:
        return "quota"
    if status == 404:
        return "notfound"
    if status >= 500:
        return "outage"
    if 200 <= status < 300:
        return "ok"
    if 300 <= status < 400:
        return "redirect"   # a real dispatch (it counts against budgets), followed by a validated hop (D-24)
    return "refused"


def ratelimit_headers(headers) -> dict:
    """Keep only rate-limit-related headers, lower-cased, for the log."""
    out = {}
    for k, v in headers.items():
        lk = k.lower()
        if "ratelimit" in lk or lk == "retry-after":
            out[lk] = v
    return out


class AuditError(RuntimeError):
    """The call log could not be written. The gateway fails closed: a request that cannot be
    audited does not keep dispatching (I-6, D-23). Raised instead of the database's own error
    so callers can tell 'logging broke' from 'a source misbehaved'."""


def record(conn, rec: CallRecord) -> int:
    try:
        return _record(conn, rec)
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise AuditError(f"call log write failed: {type(e).__name__}: {e}") from e


def attempt(conn, rec: CallRecord) -> int:
    """Write the dispatch row BEFORE the request leaves (failure_class 'attempt', no status).
    If this cannot be written, nothing is dispatched at all — auditing precedes the call, so a
    crash mid-request still leaves its row (I-6, D-25). Raises AuditError on failure."""
    pre = CallRecord(**{**asdict(rec), "status": None, "latency_ms": 0, "ratelimit": None,
                        "result_count": None, "failure_class": "attempt"})
    return record(conn, pre)


def complete(conn, attempt_id: int, rec: CallRecord) -> None:
    """Fill the attempt row in with the outcome. Raises AuditError on failure."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE gateway.calls SET status = %s, latency_ms = %s, ratelimit = %s, credits = %s, "
                "result_count = %s, failure_class = %s WHERE id = %s",
                (rec.status, rec.latency_ms, json.dumps(rec.ratelimit) if rec.ratelimit is not None else None,
                 rec.credits, rec.result_count, rec.failure_class, attempt_id))
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise AuditError(f"call log completion failed: {type(e).__name__}: {e}") from e


def _record(conn, rec: CallRecord) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO gateway.calls (job_id, source_id, request_type, identity, query, status, latency_ms, "
            "ratelimit, credits, cache_hit, result_count, failure_class, domain_resolved, client_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (rec.job_id, rec.source_id, rec.request_type, rec.identity, rec.query, rec.status, rec.latency_ms,
             json.dumps(rec.ratelimit) if rec.ratelimit is not None else None, rec.credits, rec.cache_hit,
             rec.result_count, rec.failure_class, rec.domain_resolved, rec.client_id),
        )
        row_id = cur.fetchone()[0]
    conn.commit()
    return row_id


def to_dict(rec: CallRecord) -> dict:
    return asdict(rec)
