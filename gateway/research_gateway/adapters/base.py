"""The metered HTTP client every adapter uses (PLAN.md I-1, I-6, §5).

`Client.get()` / `Client.post()`:
  1. ask the broker for a slot (waits within bounds, or raises);
  2. perform the request through a Transport (real urllib, or a fake in tests);
  3. record the call (log row when a connection is available, else in memory);
  4. feed the outcome back to the broker (429/5xx open breakers, Retry-After honoured);
  5. return the Response, sealed: it carries the answer's bytes and no parsed JSON; an adapter reads them only through `decode`, against the schema it declares.

Adapters never import urllib; that is the invariant the tests check.

What the client is made of (task 2q-b5): the response it returns (`_response.py`), the transport that makes the request and enforces the message framing (`_transport.py`) and the RFC 8288
Link reader (`_links.py`: `next_link`, `own_link`, which an adapter that pages by link imports from there) are modules of their own; this one keeps the metered client, the adapter's reading
of a decoded answer (`decode`, `members`, `first_member`, `total`, `offset_after`, `identified`, `identity_from`, `check`) and the data-parameter contract.

`__all__` is the whole of what an adapter may import from here (tests/test_member_isolation.py reads it from the source): a name that is
not in it — a module this one happens to import, a parser, a helper of its own — is not for adapters, and importing it, however it is
spelled (`from .base import json as j`, `from .base import *`), is refused.
"""
from __future__ import annotations

import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote  # re-exported: adapters quote path segments through base, never urllib directly

from ..core import calllog
from ..core.broker import Broker, BreakerOpen, BudgetExhausted, NoPolicy
from ..core.identity import meaningful
from ..core.payload import MEMBER_ERRORS, OMIT, AdapterError, ContinuationInvalid, MemberList, PayloadError, Rec, SourceUnavailable, is_unreadable  # noqa: F401 (re-exported: adapters read and raise through base)
from ..core.schema import decode as _decode
from ..core.wire import Malformed, open_json as _open_json
from ._response import Response
from ._transport import CREDENTIAL_HEADERS, MAX_REDIRECTS, REDIRECT_STATUSES, FakeTransport, Transport, redirect_target, same_origin


def _text_of(resp: Response) -> str:
    """The body as text, for the client's own bookkeeping (a refusal's reason) — never for an adapter."""
    return resp._body.decode("utf-8", "replace")


def _count_of(resp: Response) -> int | None:
    """How many results the call log says an answer held, for bookkeeping only. The bytes are opened by the decoder's own opener (core/wire.py), so an answer the decoder
    would refuse — a name twice, `NaN`, not UTF-8 — has no count here either, not a count of whichever reading a lenient parser chose."""
    try:
        j = _open_json(resp._body) if resp.ok and resp._body else None
    except Malformed:
        return None
    if isinstance(j, list):
        return len(j)
    if isinstance(j, dict):
        for k in ("items", "results", "data", "observations", "hits", "message"):
            v = j.get(k)
            if isinstance(v, list):
                return len(v)
            if isinstance(v, dict) and isinstance(v.get("items"), list):
                return len(v["items"])
    return None


def decode(source_id: str, spec, resp: Response):
    """The answer `resp` as `spec` says it must be (core/schema.py): the only way an adapter reads a provider's answer. It takes the client's response and nothing else —
    not a value an adapter has parsed or copied out — so the schema it names is the schema the answer is held to."""
    if not isinstance(resp, Response):
        raise TypeError(f"{source_id}: decode() takes the client's response, not a {type(resp).__name__}: an adapter reads a provider's answer through its declared schema only")
    return _decode(source_id, spec, resp)


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
        count = _count_of(resp)
        rec = calllog.CallRecord(
            source_id=source_id, request_type=request_type, status=resp.status, latency_ms=latency,
            job_id=self.job_id, identity=identity, query=(query or "")[:500] or None,
            ratelimit=calllog.ratelimit_headers(resp.headers), credits=credits or None,
            result_count=count, domain_resolved=self.domain_resolved, client_id=self.client_id,
            iteration=self.iteration, batch_entry=self.batch_entry, wait_ms=wait_ms,
            topic=self.topic, params_fp=self.request_fingerprint, hop=hop, **self.correlation(),
            failure_class="refused" if refused else calllog.classify(resp.status, network_error=resp.status is None,
                                                                     body=_text_of(resp)[:2000] if resp.status in (401, 403) else ""),
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
    decoded alone, in a list that cannot be iterated, indexed or searched — so the public API offers no way to lose one to another's malformed fields, and
    no other way to pass over the list than through here. A field an adapter reads and the schema does not declare raises UndeclaredRead,
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
        if not allow_html and resp._body:
            ctype = next((v for k, v in (resp.headers or {}).items() if k.lower() == "content-type"), "")
            head = resp._body.lstrip(b"\xef\xbb\xbf \t\r\n")[:15].lower()
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
    # what a record is named by, and a provider's metadata: totals and the end (the next page by link: `_links.py`)
    "identity_from", "offset_after", "total", "identified", "quote",
)
