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

import email.utils
import ipaddress
import json
import socket
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
            pass
        try:  # the header's other legal form is an HTTP-date (RFC 9110)
            when = email.utils.parsedate_to_datetime(v)
            return max(0.0, when.timestamp() - time.time())
        except (TypeError, ValueError):
            return None


MAX_BODY_BYTES = 256 * 1024 * 1024   # a response bigger than this is an error, not a memory event
MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
CREDENTIAL_HEADERS = {"authorization", "x-api-key", "x-dataverse-key", "x-app-token", "cookie"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """3xx answers come back to the metered client instead of being followed underneath it (D-23)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def redirect_target(current_url: str, location: str) -> tuple[str | None, str | None]:
    """(next url, None) when the hop is permitted; (None, reason) otherwise. Permitted means:
    http/https only, no https→http downgrade, and no destination outside global address space —
    every address the hostname resolves to must be global (SSRF guard, D-23). Known residual
    (D-24): the connect after the check re-resolves, so a DNS answer that changes between the
    two lookups could still land elsewhere — pinning the vetted address under stdlib TLS would
    break certificate verification, so the residual is documented instead of half-fixed."""
    try:
        nxt = urllib.parse.urljoin(current_url, location)
        old, new = urllib.parse.urlsplit(current_url), urllib.parse.urlsplit(nxt)
        scheme = (new.scheme or "").lower()
        if scheme not in ("http", "https"):
            return None, f"redirect to scheme {new.scheme!r} refused"
        if old.scheme.lower() == "https" and scheme == "http":
            return None, "redirect downgrades https to http"
        host, port = new.hostname or "", new.port  # .port raises ValueError on a malformed port
    except ValueError as e:
        return None, f"unparseable redirect location ({e})"
    if not host:
        return None, "redirect without a host"
    try:
        addresses = [info[4][0] for info in socket.getaddrinfo(host, port or (443 if scheme == "https" else 80),
                                                               proto=socket.IPPROTO_TCP)]
    except OSError as e:
        return None, f"redirect host does not resolve ({e})"
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            return None, f"redirect host resolves to unparseable address {addr!r}"
        if not ip.is_global:
            return None, f"redirect into a non-global address ({ip}) refused"
    return nxt, None


def same_origin(a: str, b: str) -> bool:
    ua, ub = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    return (ua.scheme, ua.hostname, ua.port) == (ub.scheme, ub.hostname, ub.port)


class Transport:
    """Real network transport. Never raises and never follows redirects: every outcome —
    including a 3xx, an oversized body, or a mid-read failure — is a Response, so the
    caller's accounting and logging always run (I-6)."""

    def request(self, method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> Response:
        try:
            req = urllib.request.Request(url, data=body, method=method, headers=headers)
        except Exception as e:  # a URL the stdlib refuses to even build is an error Response too
            return Response(None, {}, b"", url, error=f"{type(e).__name__}: {e}")
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                data = resp.read(MAX_BODY_BYTES + 1)
                if len(data) > MAX_BODY_BYTES:
                    return Response(None, {k.lower(): v for k, v in resp.headers.items()}, b"", url,
                                    error=f"response exceeds {MAX_BODY_BYTES} bytes")
                return Response(resp.status, {k.lower(): v for k, v in resp.headers.items()}, data, url)
        except urllib.error.HTTPError as e:
            try:
                payload = e.read(MAX_BODY_BYTES) or b""
            except Exception:
                payload = b""
            return Response(e.code, {k.lower(): v for k, v in e.headers.items()}, payload, url)
        except Exception as e:  # URLError, timeouts, IncompleteRead, TLS errors, anything: an error Response
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
    secret_values: set = field(default_factory=set)              # every secret handed out through this client
    job_id: int | None = None
    client_id: str | None = None
    domain_resolved: str | None = None
    commercial: bool = False   # set by the executor; download-capable adapters refuse restricted fetches up front (D-24)

    def secret(self, name: str, field: str | None = None) -> str | None:
        value = self.secrets(name, field)
        if value:
            self.secret_values.add(str(value))  # remembered so response echoes can be redacted (D-23)
        return value

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
        for hop in range(MAX_REDIRECTS + 1):
            # the audit row exists BEFORE the request leaves: if writing it fails nothing is sent,
            # and a crash mid-request still leaves its row — CREDITS INCLUDED, so restart
            # accounting restores what was actually charged (I-6, D-25, D-26)
            attempt_id = self._attempt(source_id, request_type, identity, query,
                                       credits=credits if hop == 0 else 0.0)
            t0 = time.monotonic()
            resp = self.transport.request(method, url, hdrs, body, self.timeout)
            latency = int((time.monotonic() - t0) * 1000)
            self.broker.record(source_id, resp.status, retry_after=resp.retry_after_seconds(),
                               network_error=resp.status is None)
            # credits are charged once per request (the broker charged them on the first acquire);
            # each hop still gets its own call row, but only the first carries the credit figure (D-24)
            self._record(source_id, request_type, identity, query, resp, latency,
                         credits if hop == 0 else 0.0, attempt_id=attempt_id)
            if resp.status not in REDIRECT_STATUSES:
                return resp
            location = resp.headers.get("location")
            if not location or hop == MAX_REDIRECTS:
                return Response(None, resp.headers, b"", url,
                                error="redirect without Location" if not location else f"more than {MAX_REDIRECTS} redirects")
            nxt, reason = redirect_target(url, location)
            if nxt is None:
                refused = Response(None, resp.headers, b"", url, error=reason)
                self._record(source_id, request_type, identity, query, refused, 0, 0.0, refused=True)
                return refused
            if not same_origin(url, nxt):
                # nothing sensitive travels to another origin: no credentials, and no request
                # body either — a cross-origin hop always degrades to a bare GET (D-23)
                hdrs = {k: v for k, v in hdrs.items() if k.lower() not in CREDENTIAL_HEADERS}
                method, body = "GET", None
                hdrs.pop("Content-Type", None)
            elif resp.status == 303 or (resp.status in (301, 302) and method == "POST"):
                method, body = "GET", None
                hdrs.pop("Content-Type", None)
            url = nxt
            try:  # each hop is its own metered dispatch under the same source (I-1)
                self.broker.acquire_blocking(source_id, credits=0.0, max_wait=self.max_wait, sleep=self.sleep)
            except (NoPolicy, BreakerOpen, BudgetExhausted) as e:
                refused = Response(None, {}, b"", url, error=f"{type(e).__name__}: {e}")
                self._record(source_id, request_type, identity, query, refused, 0, 0.0, refused=True)
                return refused
        return resp

    def local(self, source_id: str, request_type: str, *, query: str | None = None, identity: str | None = None,
              result_count: int | None = None, latency_ms: int = 0) -> None:
        """Log a lookup that never left the process (the local index): no broker, no transport,
        but a call row all the same, so the log shows what answered before any live lane (§8)."""
        rec = calllog.CallRecord(source_id=source_id, request_type=request_type, status=200, latency_ms=latency_ms,
                                 job_id=self.job_id, identity=identity, query=(query or "")[:500] or None,
                                 result_count=result_count, failure_class="ok", domain_resolved=self.domain_resolved,
                                 client_id=self.client_id)
        self.log.append(rec)
        if self.conn is not None:
            calllog.record(self.conn, rec)

    def _attempt(self, source_id, request_type, identity, query, credits: float = 0.0) -> int | None:
        """The pre-dispatch audit row (D-25). None when there is no database (laptop mode)."""
        if self.conn is None:
            return None
        rec = calllog.CallRecord(source_id=source_id, request_type=request_type, status=None, latency_ms=0,
                                 job_id=self.job_id, identity=identity, query=(query or "")[:500] or None,
                                 credits=credits or None, domain_resolved=self.domain_resolved, client_id=self.client_id)
        return calllog.attempt(self.conn, rec)

    def _record(self, source_id, request_type, identity, query, resp: Response, latency: int, credits: float,
                refused: bool = False, attempt_id: int | None = None) -> None:
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
            result_count=count, domain_resolved=self.domain_resolved, client_id=self.client_id,
            failure_class="refused" if refused else calllog.classify(resp.status, network_error=resp.status is None,
                                                                     body=resp.text[:2000] if resp.status in (401, 403) else ""),
        )
        self.log.append(rec)
        if self.conn is not None:
            if attempt_id is not None:
                calllog.complete(self.conn, attempt_id, rec)   # fill the pre-dispatch row in (D-25)
            else:
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


def check(source_id: str, resp: Response, *, allow_404: bool = True, allow_html: bool = False) -> bool:
    """True when usable; False on 404 (when allowed); raises SourceUnavailable otherwise.
    An HTTP-200 answer whose body is an HTML page is a bot-wall or an error page wearing
    a success status, never a usable API answer — it raises as unavailable instead of
    flowing on to become a false `searched_empty` (pass-1 finding 7). Raw-file fetch
    paths that may legitimately retrieve HTML documents pass allow_html=True."""
    if resp.ok:
        if not allow_html and resp.body:
            ctype = next((v for k, v in (resp.headers or {}).items() if k.lower() == "content-type"), "")
            head = resp.body.lstrip(b"\xef\xbb\xbf \t\r\n")[:15].lower()
            # the declared type is the robust signal (a BOM or leading comment defeats any
            # sniff); the prefix sniff covers answers that omit the header
            # a bare leading comment counts only without a declared type: an XML answer
            # (SDMX) may legitimately open with one and declares itself as xml
            if ("text/html" in str(ctype).lower() or head.startswith((b"<html", b"<!doctype"))
                    or (head.startswith(b"<!--") and not ctype)):
                raise SourceUnavailable(source_id, Response(resp.status, resp.headers, b"", resp.url,
                                                            error="HTML answer with a success status (unreadable)"))
        return True
    if resp.status == 404 and allow_404:
        return False
    raise SourceUnavailable(source_id, resp)
