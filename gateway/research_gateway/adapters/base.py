"""The metered HTTP client every adapter uses (PLAN.md I-1, I-6, §5).

`Client.get()` / `Client.post()`:
  1. ask the broker for a slot (waits within bounds, or raises);
  2. perform the request through a Transport (real urllib, or a fake in tests);
  3. record the call (log row when a connection is available, else in memory);
  4. feed the outcome back to the broker (429/5xx open breakers, Retry-After honoured);
  5. return a Response with parsed JSON when the body is JSON.

Adapters never import urllib; that is the invariant the tests check.

`__all__` is the whole of what an adapter may import from here (tests/test_member_isolation.py reads it from the source): a name that is
not in it — a module this one happens to import, a parser, a helper of its own — is not for adapters, and importing it, however it is
spelled (`from .base import json as j`, `from .base import *`), is refused.
"""
from __future__ import annotations

import email.utils
import ipaddress
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, NamedTuple
from urllib.parse import quote  # re-exported: adapters quote path segments through base, never urllib directly

from ..core import calllog, uri
from ..core.broker import Broker, BreakerOpen, BudgetExhausted, NoPolicy
from ..core.identity import meaningful
from ..core.payload import MEMBER_ERRORS, OMIT, MemberList, PayloadError, Rec, is_unreadable  # noqa: F401 (re-exported: adapters read and raise through base)
from ..core.schema import decode  # noqa: F401 (re-exported: an adapter's only way into a provider's answer)


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
        """The parsed body, as plain data. For the client's own bookkeeping and for `decode(SOURCE_ID, SCHEMA, resp.json)`: an adapter
        reads a provider's answer through its schema and never by hand (tests/test_schema_corruption.py scans for it). An empty or
        unparseable body raises PayloadError instead of standing in as None — the `(resp.json or {})` of an adapter can no longer make
        it 'no results'."""
        if not self.body:
            raise PayloadError(f"empty body (HTTP {self.status})")
        import json   # here and nowhere else at module level or in the module's namespace: nothing in adapters.base is a parser to re-export
        try:
            return json.loads(self.body)
        except (ValueError, UnicodeDecodeError):
            raise PayloadError(f"unparseable JSON (HTTP {self.status}, {len(self.body)} bytes)") from None

    def json_or_none(self):
        """The body parsed, or None — for a check that must never raise (the call log's count; OpenML's error code on a 412)."""
        try:
            return self.json
        except PayloadError:
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


class LinkSyntax(ValueError):
    """A `Link` header (RFC 8288) that cannot be read to its last character, or whose relations cannot be told."""


_TCHAR = frozenset("!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
_QDTEXT = frozenset("\t !") | frozenset(chr(c) for c in (*range(0x23, 0x5C), *range(0x5D, 0x7F), *range(0x80, 0x100)))   # RFC 9110 §5.6.4
_QUOTABLE = frozenset("\t") | frozenset(chr(c) for c in (*range(0x20, 0x7F), *range(0x80, 0x100)))                        # what a `\` may precede
# RFC 8288 §3.3: a relation type is a registered name (`LOALPHA *( LOALPHA / DIGIT / "." / "-" )`, compared without regard to case) or an
# absolute URI (an extension relation, core/uri.py); the `rel` value is one, or several separated by spaces
_REGISTERED_REL = re.compile(r"[A-Za-z][A-Za-z0-9.\-]*")


def parse_links(header: str) -> list[tuple[str, list[tuple[str, str | None]]]]:
    """Every link-value of a `Link` header as (target, [(parameter name lower-cased, value)]), RFC 8288 §3 on the
    list syntax of RFC 9110: `<` target `>` and then `;` parameters in any order, each a token with an optional token
    or quoted-string value (backslash escapes undone; a quoted string holds only what RFC 9110 §5.6.4 allows). A comma
    or semicolon inside `<...>` or a quoted string belongs to it, and empty list elements are ignored. LinkSyntax for
    anything else, wherever it stands: nothing is guessed from a header that does not read through, because the one
    thing a reader cannot do with it is call it free of a next link."""
    n, i, out = len(header), 0, []

    def space(at: int) -> int:
        while at < n and header[at] in " \t":
            at += 1
        return at

    def read_token(at: int) -> tuple[int, str]:
        start = at
        while at < n and header[at] in _TCHAR:
            at += 1
        if at == start:
            raise LinkSyntax(f"Link header: expected a token at character {start}")
        return at, header[start:at]

    while True:
        i = space(i)
        if i == n:
            return out
        if header[i] == ",":
            i += 1
            continue
        end = header.find(">", i + 1) if header[i] == "<" else -1
        if end < 0:
            raise LinkSyntax(f"Link header: no <target> at character {i}")
        target, params, i = header[i + 1:end], [], space(end + 1)
        if not uri.is_uri_reference(target):
            raise LinkSyntax(f"Link header: a target that is no URI-reference (RFC 3986), at character {end}")
        while i < n and header[i] == ";":
            i, name = read_token(space(i + 1))
            i, value = space(i), None
            if i < n and header[i] == "=":
                i = space(i + 1)
                if i < n and header[i] == '"':
                    chars, i = [], i + 1
                    while i < n and header[i] != '"':
                        if header[i] == "\\":
                            i += 1
                            if i == n or header[i] not in _QUOTABLE:
                                raise LinkSyntax(f"Link header: a quoted-pair that is not one, at character {i}")
                        elif header[i] not in _QDTEXT:
                            raise LinkSyntax(f"Link header: a character a quoted string cannot hold, at character {i}")
                        chars.append(header[i])
                        i += 1
                    if i == n:
                        raise LinkSyntax("Link header: a quoted string is not closed")
                    i, value = i + 1, "".join(chars)
                else:
                    i, value = read_token(i)
            params.append((name.lower(), value))
            i = space(i)
        out.append((target, params))
        if i < n and header[i] != ",":
            raise LinkSyntax(f"Link header: unexpected {header[i]!r} at character {i}")


def relation_types(value: str | None) -> list[str]:
    """The relation types a `rel` value names, lower-cased: one or more, each a registered name or an absolute URI, separated by
    spaces (RFC 8288 §3.3). LinkSyntax for a value that is anything else — none at all, empty, a quote character or a control
    character of its own, a comma, a space at either end, another quoting — because a relation that cannot be told is not a relation
    that names no next page."""
    parts = value.split(" ") if value else [""]
    if "" in (parts[0], parts[-1]) or not all(_REGISTERED_REL.fullmatch(p) or uri.is_uri(p) for p in parts if p):
        raise LinkSyntax("Link header: a relation that is not a list of relation types")
    return [p.lower() for p in parts if p]


class NextLink(NamedTuple):
    """What a `Link` header says about the next page: `url` and `known`. A url is the continuation; no url with
    `known` is the header read whole and naming no next link (the absence a provider's own client treats as the end);
    no url and not `known` is a header that could not be read or names several different next pages — nothing is
    established, so it is neither a continuation nor an end."""
    url: str | None
    known: bool


def next_link(resp: Response) -> NextLink:
    """The answer's `Link: <...>; rel="next"` (RFC 8288), its target resolved against the URL asked (§3.1: RFC 3986 §5). Only the first
    `rel` of a link counts (§3.3), and its value must be a list of relation types (`relation_types`): a header that does not
    parse, a `rel` with no value or one that is no such list (`rel='next'`, `rel="\\"next\\""`, `rel=""`, `rel="next, prev"`), or two
    different next targets is not `known`. A link with no `rel` names no relation. A next link is no continuation, and no end either,
    when it is not this listing's: its `anchor` puts its context at another resource (§3.2), or its target is the request itself (a
    continuation that does not move on: asking it again is the same page again)."""
    lines = [v for k, v in resp.headers.items() if k.lower() == "link"]
    try:
        targets, unusable = set(), False
        for target, params in parse_links(", ".join(lines)):
            rel, anchor = (next(((v,) for k, v in params if k == name), None) for name in ("rel", "anchor"))   # the first of each counts; (None,) is one with no value
            if anchor is not None and (anchor[0] is None or not uri.is_uri_reference(anchor[0])):
                raise LinkSyntax("Link header: an anchor that is no URI-reference")
            if rel is None or "next" not in relation_types(rel[0]):
                continue
            url = uri.resolve(resp.url, target)
            if (anchor is not None and not uri.same_resource(uri.resolve(resp.url, anchor[0]), resp.url, fragment=True)) or uri.same_resource(url, resp.url):
                unusable = True
            else:
                targets.add(url)
    except ValueError:   # LinkSyntax
        return NextLink(None, False)
    return NextLink(targets.pop() if len(targets) == 1 and not unusable else None, len(targets) <= 1 and not unusable)


def own_link(url, endpoint: str, **same: str) -> str | None:
    """`url` when a request may follow it as a continuation of `endpoint`, else None. It must keep
    the endpoint's scheme, host, port and path, and carry no user info or fragment, so a continuation
    can never send a request elsewhere or carry credentials of its own: the adapter's credentials
    travel only in its own headers. Each `same` parameter must be named by the URL, with the given value: a continuation that
    leaves one out is some other listing's."""
    if not isinstance(url, str):
        return None
    try:
        u, e = urllib.parse.urlsplit(url), urllib.parse.urlsplit(endpoint)
        if (u.scheme, u.hostname, u.port, u.path) != (e.scheme, e.hostname, e.port, e.path):
            return None
    except ValueError:   # a malformed port
        return None
    if u.username is not None or u.password is not None or u.fragment:
        return None
    named = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    return url if all(named.get(k) == [v] for k, v in same.items()) else None


def same_origin(a: str, b: str) -> bool:
    ua, ub = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    return (ua.scheme, ua.hostname, ua.port) == (ub.scheme, ub.hostname, ub.port)


def header_map(headers) -> dict:
    """Header name (lower-cased) -> value. Field lines that repeat a name are one list-valued field, joined with ", "
    (RFC 9110 §5.3): a dict built line by line kept only the last and dropped the rest, a `Link` relation among them."""
    out: dict = {}
    for name, value in headers.items():
        name = name.lower()
        out[name] = f"{out[name]}, {value}" if name in out else value
    return out


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
                    return Response(None, header_map(resp.headers), b"", url,
                                    error=f"response exceeds {MAX_BODY_BYTES} bytes")
                return Response(resp.status, header_map(resp.headers), data, url)
        except urllib.error.HTTPError as e:
            try:
                payload = e.read(MAX_BODY_BYTES) or b""
            except Exception:
                payload = b""
            return Response(e.code, header_map(e.headers), payload, url)
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
            import json
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
    iteration: str | None = None    # 9·0 tracing (D-33): chassis iteration stamp — travels beside requests,
    batch_entry: int | None = None  # never inside them (cache keys and job dedup hash the payload)
    topic: str | None = None            # caller's topic id — tracing beside requests, like iteration
    request_fingerprint: str | None = None  # payload params/cursors fingerprint set by the executor (repeat classification)
    invocation_id: str | None = None      # task 2b: the caller's invocation and attempt (the job CREATOR's on a
    attempt: int | None = None            # worker), and the complete effective request's identity, on every row
    request_identity: str | None = None
    db_lock: threading.Lock = field(default_factory=threading.Lock)
    abort: threading.Event = field(default_factory=threading.Event)
    # set the moment ANY audit write on this client fails, under db_lock itself — the same
    # lock that admits every dispatch — so "a lane not yet dispatched when the call log
    # breaks never dispatches" holds without a window between failure and publication (9·2b)
    # 9·2b: parallel lanes share this client and its ONE psycopg connection. The driver
    # object is thread-safe; the shared TRANSACTION is not — so every operation-through-
    # commit on client.conn (call-log writes here, direct adapter use like the local
    # index lane) holds this lock. Transports overlap; database work serializes.

    def correlation(self) -> dict:
        """The invocation, attempt and request identity every call row of this client carries."""
        return {"invocation_id": self.invocation_id, "attempt": self.attempt, "request_identity": self.request_identity}

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
        import json
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        hdrs = dict(headers or {})
        if isinstance(body, dict):
            hdrs.setdefault("Content-Type", "application/json")
        return self._call("POST", source_id, request_type, url, None, hdrs, data, identity, query, credits)

    def _call(self, method, source_id, request_type, url, params, headers, body, identity, query, credits) -> Response:
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)
        wait_t0 = time.monotonic()
        try:
            self.broker.acquire_blocking(source_id, credits=credits, max_wait=self.max_wait, sleep=self.sleep)
        except (NoPolicy, BreakerOpen, BudgetExhausted) as e:
            resp = Response(None, {}, b"", url, error=f"{type(e).__name__}: {e}")
            self._record(source_id, request_type, identity, query, resp, 0, credits, refused=True,
                         wait_ms=int((time.monotonic() - wait_t0) * 1000))
            return resp
        wait_ms = int((time.monotonic() - wait_t0) * 1000)   # broker wait, separated from provider latency (9·0)
        hdrs = {"User-Agent": self.user_agent, "Accept": "application/json"}
        hdrs.update(headers or {})
        for hop in range(MAX_REDIRECTS + 1):
            # the audit row exists BEFORE the request leaves: if writing it fails nothing is sent,
            # and a crash mid-request still leaves its row — CREDITS INCLUDED, so restart
            # accounting restores what was actually charged (I-6, D-25, D-26)
            attempt_id = self._attempt(source_id, request_type, identity, query,
                                       credits=credits if hop == 0 else 0.0, hop=hop)
            t0 = time.monotonic()
            resp = self.transport.request(method, url, hdrs, body, self.timeout)
            latency = int((time.monotonic() - t0) * 1000)
            self.broker.record(source_id, resp.status, retry_after=resp.retry_after_seconds(),
                               network_error=resp.status is None)
            # credits are charged once per request (the broker charged them on the first acquire);
            # each hop still gets its own call row, but only the first carries the credit figure (D-24)
            self._record(source_id, request_type, identity, query, resp, latency,
                         credits if hop == 0 else 0.0, attempt_id=attempt_id,
                         wait_ms=wait_ms, hop=hop)   # each hop reports ITS OWN broker wait (9·0: waits are never dropped)
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
            hop_t0 = time.monotonic()
            try:  # each hop is its own metered dispatch under the same source (I-1)
                self.broker.acquire_blocking(source_id, credits=0.0, max_wait=self.max_wait, sleep=self.sleep)
            except (NoPolicy, BreakerOpen, BudgetExhausted) as e:
                refused = Response(None, {}, b"", url, error=f"{type(e).__name__}: {e}")
                self._record(source_id, request_type, identity, query, refused, 0, 0.0, refused=True,
                             wait_ms=int((time.monotonic() - hop_t0) * 1000))
                return refused
            wait_ms = int((time.monotonic() - hop_t0) * 1000)
        return resp

    def local(self, source_id: str, request_type: str, *, query: str | None = None, identity: str | None = None,
              result_count: int | None = None, latency_ms: int = 0) -> None:
        """Log a lookup that never left the process (the local index): no broker, no transport,
        but a call row all the same, so the log shows what answered before any live lane (§8)."""
        rec = calllog.CallRecord(source_id=source_id, request_type=request_type, status=200, latency_ms=latency_ms,
                                 job_id=self.job_id, identity=identity, query=(query or "")[:500] or None,
                                 result_count=result_count, failure_class="ok", domain_resolved=self.domain_resolved,
                                 client_id=self.client_id, iteration=self.iteration, batch_entry=self.batch_entry,
                                 topic=self.topic, params_fp=self.request_fingerprint, backdate_ms=latency_ms,
                                 **self.correlation())
        self.log.append(rec)
        if self.conn is not None:
            with self.db_lock:
                try:
                    calllog.record(self.conn, rec)
                except calllog.AuditError:
                    self.abort.set()
                    raise

    def _attempt(self, source_id, request_type, identity, query, credits: float = 0.0,
                 hop: int | None = None) -> int | None:
        """The pre-dispatch audit row (D-25). None when there is no database (laptop mode)."""
        if self.conn is None:
            return None
        rec = calllog.CallRecord(source_id=source_id, request_type=request_type, status=None, latency_ms=0,
                                 job_id=self.job_id, identity=identity, query=(query or "")[:500] or None,
                                 credits=credits or None, domain_resolved=self.domain_resolved, client_id=self.client_id,
                                 iteration=self.iteration, batch_entry=self.batch_entry,
                                 topic=self.topic, params_fp=self.request_fingerprint, hop=hop, **self.correlation())
        with self.db_lock:   # committed BEFORE dispatch, and never interleaved with a sibling lane's transaction (9·2b)
            if self.abort.is_set():
                raise calllog.AuditError("not dispatched: this request's call log already failed (I-6)")
            try:
                return calllog.attempt(self.conn, rec)
            except calllog.AuditError:
                self.abort.set()   # published under the SAME lock that admits dispatches
                raise

    def _record(self, source_id, request_type, identity, query, resp: Response, latency: int, credits: float,
                refused: bool = False, attempt_id: int | None = None, wait_ms: int | None = None,
                hop: int | None = None) -> None:
        count = None
        j = resp.json_or_none() if resp.ok else None
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
            iteration=self.iteration, batch_entry=self.batch_entry, wait_ms=wait_ms,
            topic=self.topic, params_fp=self.request_fingerprint, hop=hop, **self.correlation(),
            failure_class="refused" if refused else calllog.classify(resp.status, network_error=resp.status is None,
                                                                     body=resp.text[:2000] if resp.status in (401, 403) else ""),
        )
        self.log.append(rec)
        if self.conn is not None:
            with self.db_lock:
                try:
                    if attempt_id is not None:
                        calllog.complete(self.conn, attempt_id, rec)   # fill the pre-dispatch row in (D-25)
                    else:
                        calllog.record(self.conn, rec)
                except calllog.AuditError:
                    self.abort.set()
                    raise


class AdapterError(Exception):
    """Raised by adapters for malformed input; never for source failures (those are Responses)."""


class ContinuationInvalid(Exception):
    """A continuation its source can no longer honour — the population it was counted in has
    changed (2b-repair-7 F3-R1). Nothing is read for it and nothing ends: more may remain
    that it cannot ask for. The router reports it unobserved, `partial_pagination`."""


class SourceUnavailable(Exception):
    """A source answered with an error (or the broker refused). The router turns
    this into a capability fact on the job (R-10); it is never a 'not found'."""

    def __init__(self, source_id: str, response: Response):
        detail = response.error or f"HTTP {response.status}"
        super().__init__(f"{source_id}: {detail}")
        self.source_id, self.response = source_id, response


def data_contract(mod) -> dict | None:
    """The adapter's declared, agent-facing data contract (DATA_PARAMS), or None. The
    declaration is the authority — signature introspection cannot express these (D-31)."""
    spec = getattr(mod, "DATA_PARAMS", None)
    if not isinstance(spec, dict):
        return None
    return {"required": dict(spec.get("required") or {}), "optional": dict(spec.get("optional") or {}),
            "open": bool(spec.get("open")), "example": dict(spec.get("example") or {}),
            "notes": spec.get("notes") or ""}


# declared value shapes (D-31a): a call with the right KEYS but a malformed VALUE must
# also fail preflight with the teaching contract, never reach upstream and spend budget
def _real_date(v) -> bool:
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return False
    import datetime
    try:  # a calendar, not a shape: 2026-99-99 must fail preflight (D-32a finding 2)
        datetime.date.fromisoformat(v)
        return True
    except ValueError:
        return False


def _real_period(v) -> bool:
    """SDMX periods, calendar-true: a year, a real month, a REAL date (2020-02-31 must
    fail preflight, D-32b), a quarter Q1-Q4, a half S1-S2, or a week W01-W53."""
    if not isinstance(v, str):
        return False
    if re.fullmatch(r"\d{4}", v) or re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v):
        return True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return _real_date(v)
    m = re.fullmatch(r"\d{4}-([QS])(\d)", v)
    if m:
        return int(m.group(2)) in ((1, 2, 3, 4) if m.group(1) == "Q" else (1, 2))
    m = re.fullmatch(r"\d{4}-W(\d{2})", v)
    return bool(m) and 1 <= int(m.group(1)) <= 53


_VALUE_CHECKS = {
    "string": lambda v, s: isinstance(v, str) and v.strip() != "",
    "integer": lambda v, s: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v, s: isinstance(v, bool),
    "date": lambda v, s: _real_date(v),
    "period": lambda v, s: _real_period(v),
    "year": lambda v, s: (isinstance(v, int) and not isinstance(v, bool) and 1500 <= v <= 2200)
                         or (isinstance(v, str) and v.isdigit() and 1500 <= int(v) <= 2200),
    "string_or_int": lambda v, s: (isinstance(v, str) and v.strip() != "")
                                  or (isinstance(v, int) and not isinstance(v, bool)),
    "string_or_list": lambda v, s: ((isinstance(v, str) and v.strip() != "")
                                    or (isinstance(v, list) and v
                                        and all(isinstance(x, str) and x.strip() for x in v)
                                        and len(v) <= (s.get("max_items") or len(v)))),
}


def _value_problem(name: str, value, spec) -> str | None:
    if not isinstance(spec, dict):
        return None   # legacy plain-doc entry: presence-only
    kind = spec.get("type") or "string"
    checker = _VALUE_CHECKS.get(kind)
    if checker is None or checker(value, spec):
        return None
    limit = f", at most {spec['max_items']} items" if spec.get("max_items") else ""
    return f"'{name}' must be {kind}{limit} ({spec.get('doc', '')})"


def validate_data_params(mod, params: dict | None) -> str | None:
    """Why these params violate the adapter's declared contract, or None. Runs BEFORE any
    dispatch or budget spend, so a blind call fails instantly with a teaching error
    instead of burning an upstream request (D-31); declared VALUE shapes are checked too
    (D-31a). `open` contracts accept extra keys (BEA methods, Census predicates take
    source-specific pass-through fields) but their declared keys are still typed."""
    spec = data_contract(mod)
    if spec is None:
        return None
    params = params or {}
    problems = []
    for k, entry in spec["required"].items():
        doc = entry.get("doc", "") if isinstance(entry, dict) else entry
        if params.get(k) in (None, "", []):
            problems.append(f"missing required '{k}' ({doc})")
    if not spec["open"]:
        known = set(spec["required"]) | set(spec["optional"])
        problems += [f"unknown parameter '{k}' (accepted: {', '.join(sorted(known))})"
                     for k in params if k not in known]
    for k, value in params.items():
        if value is None:
            continue
        entry = spec["required"].get(k) or spec["optional"].get(k)
        if entry is not None:
            # a SUPPLIED empty value is malformed, not merely absent: limit:"" must fail
            # preflight like limit:"many" does (D-32a finding 2)
            problem = _value_problem(k, value, entry)
            if problem and problem not in problems:
                problems.append(problem)
    return "; ".join(problems) or None


def members(source_id: str, items: MemberList, build) -> list:
    """Each decoded member through `build` on its own (task 2b-repair A4; RG-4): a member the decoder could not read, whose record cannot be built,
    or whose record names no meaningful identity becomes None — dropped and counted by the router, so the members read beside it stand as a PARTIAL
    lower bound instead of the whole answer being lost, and an unreadable member never becomes a fabricated candidate (`url:None`). `build` may
    return OMIT for a member it read whole and found to name nothing to report: no record, and no dropped member either.

    `items` is what the decoder returned for a `members(...)` schema node (core/schema.py, core/payload.py MemberList): every member already
    decoded alone, in a list that cannot be iterated, indexed or searched — so no adapter can have lost one to another's malformed fields, and
    none can pass over the list any other way than through here. A field an adapter reads and the schema does not declare raises UndeclaredRead,
    which is not caught here."""
    if not isinstance(items, MemberList):
        raise TypeError(f"{source_id}: members() takes what the decoder returned for a members(...) node (a MemberList), not a {type(items).__name__}")
    return [rec if isinstance(rec, dict) and meaningful(rec.get("identity")) else None for rec in items.each(build)]


def first_member(source_id: str, items: MemberList, build):
    """The one record a lookup asked for: the first of the provider's results, decoded like any member (None when there are none). An answer
    whose first result cannot be read is unreadable, never 'not found'; and never answered by the result after it, which may be some other work."""
    if not isinstance(items, MemberList):
        raise TypeError(f"{source_id}: first_member() takes what the decoder returned for a members(...) node (a MemberList), not a {type(items).__name__}")
    rec = items.first(build, source_id)
    if rec is None:
        return None
    if not (isinstance(rec, dict) and meaningful(rec.get("identity"))):
        raise PayloadError(f"{source_id}: the answer's first result cannot be read")
    return rec


def offset_after(value, offset: int):
    """A provider's next offset: a whole number past the `offset` this page started at, else None. A boolean, a float, a text, a negative
    number — or one that does not advance, which would ask for this page again for ever — is no continuation."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > offset else None


def total(value, seen: int = 0):
    """A provider's count of its results as a whole number no smaller than the `seen` results already read, else None: a boolean,
    a float, a string, or a count that is smaller than what the provider has itself returned is no count, and a count that cannot be
    read is never an end. (`total: 0` beside three records is not zero results.)"""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= seen else None


def identified(source_id: str, rows, entries: list) -> list:
    """The catalogue entries a listing's rows gave: a listing that has rows and not one names anything is unreadable, not an empty catalogue
    (a readable listing of nothing is not a catalogue; and a row of no id is skipped, never the whole answer)."""
    if rows and not entries:
        raise PayloadError(f"{source_id}: none of the {len(rows)} listed row(s) names an identifier: a listing of nothing is not a catalogue")
    return entries


def identity_from(source_id: str, *candidates: tuple[str, str | None]) -> str:
    """The identity a member is known by: `scheme:value` of the first candidate that has a value, in the order given (the preferred identifier first).
    The candidates are decoded values, so each was read, and refused when of the wrong kind, before any is chosen. A member that carries none of them
    names nothing: PayloadError."""
    for scheme, value in candidates:
        if (isinstance(value, str) and value.strip()) or (isinstance(value, int) and not isinstance(value, bool)):
            return f"{scheme}:{value}"
    raise PayloadError(f"{source_id}: a member that carries no identifier it can be named by")


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


__all__ = (
    # the metered client, and what an adapter says when it cannot answer
    "Client", "AdapterError", "ContinuationInvalid", "PayloadError", "MEMBER_ERRORS", "check",
    # a provider's answer: decoded against the operation's declared schema (core/schema.py), and read as what it decodes to
    "decode", "members", "first_member", "OMIT", "MemberList", "is_unreadable", "Rec",
    # what a record is named by, and a provider's metadata: totals, the end and the next page
    "identity_from", "offset_after", "total", "identified", "next_link", "own_link", "quote",
)
