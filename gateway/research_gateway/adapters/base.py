"""The metered HTTP client every adapter uses (PLAN.md I-1, I-6, §5).

`Client.get()` / `Client.post()`:
  1. ask the broker for a slot (waits within bounds, or raises);
  2. perform the request through a Transport (real urllib, or a fake in tests);
  3. record the call (log row when a connection is available, else in memory);
  4. feed the outcome back to the broker (429/5xx open breakers, Retry-After honoured);
  5. return a Response with parsed JSON when the body is JSON.

Adapters never import urllib; that is the invariant the tests check.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote  # re-exported: adapters quote path segments through base, never urllib directly

from ..core import calllog
from ..core.broker import Broker, BreakerOpen, BudgetExhausted, NoPolicy


@dataclass
class Response:
    status: int | None
    headers: dict
    body: bytes
    url: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    @property
    def json(self):
        try:
            return json.loads(self.body) if self.body else None
        except ValueError:
            return None

    def retry_after_seconds(self) -> float | None:
        v = self.headers.get("retry-after") or self.headers.get("Retry-After")
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            return None


class Transport:
    """Real network transport."""

    def request(self, method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> Response:
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return Response(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read(), url)
        except urllib.error.HTTPError as e:
            return Response(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read() or b"", url)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return Response(None, {}, b"", url, error=f"{type(e).__name__}: {e}")


class FakeTransport:
    """Test transport: canned responses matched by (method, url-prefix)."""

    def __init__(self):
        self.routes: list[tuple[str, str, Response]] = []
        self.calls: list[tuple[str, str, dict, bytes | None]] = []

    def add(self, method: str, url_prefix: str, status: int = 200, body: bytes | str | dict | list = b"",
            headers: dict | None = None) -> None:
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.routes.append((method.upper(), url_prefix, Response(status, {k.lower(): v for k, v in (headers or {}).items()}, body, url_prefix)))

    def request(self, method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> Response:
        self.calls.append((method.upper(), url, headers, body))
        for m, prefix, resp in self.routes:
            if m == method.upper() and url.startswith(prefix):
                return Response(resp.status, resp.headers, resp.body, url)
        return Response(404, {}, b"", url)


@dataclass
class Client:
    broker: Broker
    transport: Transport | FakeTransport = field(default_factory=Transport)
    secrets: Callable[[str, str | None], str | None] = lambda name, field=None: None
    contact_email: str = "gateway@example.org"
    user_agent: str = "research-gateway/0.1 (mailto:gateway@example.org)"
    conn: object | None = None                 # psycopg connection for the call log, or None
    timeout: float = 30.0
    max_wait: float = 120.0
    sleep: Callable[[float], None] = time.sleep   # injected in tests so backoff waits are not real
    log: list[calllog.CallRecord] = field(default_factory=list)  # in-memory mirror (tests, status)
    job_id: int | None = None
    domain_resolved: str | None = None

    def secret(self, name: str, field: str | None = None) -> str | None:
        return self.secrets(name, field)

    def get(self, source_id: str, request_type: str, url: str, *, params: dict | None = None,
            headers: dict | None = None, identity: str | None = None, query: str | None = None,
            credits: float = 0.0) -> Response:
        return self._call("GET", source_id, request_type, url, params, headers, None, identity, query, credits)

    def post(self, source_id: str, request_type: str, url: str, *, body: dict | bytes | None = None,
             headers: dict | None = None, identity: str | None = None, query: str | None = None,
             credits: float = 0.0) -> Response:
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        hdrs = dict(headers or {})
        if isinstance(body, dict):
            hdrs.setdefault("Content-Type", "application/json")
        return self._call("POST", source_id, request_type, url, None, hdrs, data, identity, query, credits)

    def _call(self, method, source_id, request_type, url, params, headers, body, identity, query, credits) -> Response:
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)
        try:
            self.broker.acquire_blocking(source_id, credits=credits, max_wait=self.max_wait, sleep=self.sleep)
        except (NoPolicy, BreakerOpen, BudgetExhausted) as e:
            resp = Response(None, {}, b"", url, error=f"{type(e).__name__}: {e}")
            self._record(source_id, request_type, identity, query, resp, 0, credits, refused=True)
            return resp
        hdrs = {"User-Agent": self.user_agent, "Accept": "application/json"}
        hdrs.update(headers or {})
        t0 = time.monotonic()
        resp = self.transport.request(method, url, hdrs, body, self.timeout)
        latency = int((time.monotonic() - t0) * 1000)
        self.broker.record(source_id, resp.status, retry_after=resp.retry_after_seconds(),
                           network_error=resp.status is None)
        self._record(source_id, request_type, identity, query, resp, latency, credits)
        return resp

    def _record(self, source_id, request_type, identity, query, resp: Response, latency: int, credits: float,
                refused: bool = False) -> None:
        count = None
        j = resp.json if resp.ok else None
        if isinstance(j, list):
            count = len(j)
        elif isinstance(j, dict):
            for k in ("items", "results", "data", "observations", "hits", "message"):
                v = j.get(k)
                if isinstance(v, list):
                    count = len(v)
                    break
                if isinstance(v, dict) and isinstance(v.get("items"), list):
                    count = len(v["items"])
                    break
        rec = calllog.CallRecord(
            source_id=source_id, request_type=request_type, status=resp.status, latency_ms=latency,
            job_id=self.job_id, identity=identity, query=(query or "")[:500] or None,
            ratelimit=calllog.ratelimit_headers(resp.headers), credits=credits or None,
            result_count=count, domain_resolved=self.domain_resolved,
            failure_class="refused" if refused else calllog.classify(resp.status, network_error=resp.status is None,
                                                                     body=resp.text[:2000] if resp.status in (401, 403) else ""),
        )
        self.log.append(rec)
        if self.conn is not None:
            calllog.record(self.conn, rec)


class AdapterError(Exception):
    """Raised by adapters for malformed input; never for source failures (those are Responses)."""


class SourceUnavailable(Exception):
    """A source answered with an error (or the broker refused). The router turns
    this into a capability fact on the job (R-10); it is never a 'not found'."""

    def __init__(self, source_id: str, response: Response):
        detail = response.error or f"HTTP {response.status}"
        super().__init__(f"{source_id}: {detail}")
        self.source_id, self.response = source_id, response


def check(source_id: str, resp: Response, *, allow_404: bool = True) -> bool:
    """True when usable; False on 404 (when allowed); raises SourceUnavailable otherwise."""
    if resp.ok:
        return True
    if resp.status == 404 and allow_404:
        return False
    raise SourceUnavailable(source_id, resp)
