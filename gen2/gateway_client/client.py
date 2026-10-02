"""The engine's typed door to the Gateway service (task 2b; BOUNDARIES.md Gateway).

The gateway runs as its own process and is never imported (INVARIANTS B-2); this client
speaks its HTTP API (gateway/docs/STATION-CONTRACT.md, OPERATIONS.md). It carries the
invocation and attempt on every request and every job poll (H-1; the gateway refuses a
research request without them), mints per-invocation grants for stations (the gateway
enforces a grant's topic policy on every door), and turns every answer — and every
failure to get one — into search-observation documents for the router's
record_observation (observe.py), plus the capability facts the gateway reported (for the
router's record_gateway_facts, first: observe.router_requests gives the order) and the
telemetry the gateway could not capture durably. Nothing it cannot read becomes zero
results: a transport failure, a timeout, a refused or unreadable answer, a job that
failed or never finished, an answer that does not echo the invocation it was asked under
— each is an observation with coverage `unknown` (or the gateway's own degraded state)
and no count (RG-4, RG-U).

Every answer variant is validated whole (2b-repair A1): a dispatched answer names its
lanes and carries its records list; an answer without lanes is only ever a record-cache
hit that says so and carries the one record it repeats; a queued answer is polled to a
finished job. A named lane the answer leaves out is unobserved. An answer the gateway did
not capture durably is a telemetry loss, and its lanes keep what they read only as a lower
bound (observe.uncaptured).

Pagination (find, pages > 1; 2b-repair A2): each lane still answering with a `next`
cursor is asked again, alone with the other continuing lanes (the `lanes` filter), under
the same invocation and attempt. EACH PAGE a lane was asked is its own observation — its
`request` the exact payload sent for that page (its cursors) — so a failed continuation
keeps its own cursor and outcome, and what the earlier pages read stands on their own
observations; nothing is rounded up to what the provider claimed.

Each page observation also says why pagination ended or continued (Gate D #3, task
2b-repair-13b; observe.page_end): `exhausted` only on the lane's own reported end, a page read
whole and a population exhausted being different facts; `continuation` with the cursor the
lane handed back; `limit_reached` when this client's `pages` cap stopped a lane with its
cursor in hand; `end_unknown` for a page with neither a continuation nor a reported end (and the
only outcome, but `failed`, of a request that does not page — resolve, enrich, fetch, data — which has no
end to know: 2b-repair-13d); and `failed`. The cursor is kept on the observation, so neither the cap
nor an unfollowed continuation hides that more remains.

Queued answers are polled until the job finishes or the client's deadline passes; a
deadline that passes is `unknown`/`timeout`, never an empty result. The deadline is ONE
absolute point on the monotonic clock, set when polling starts (Gate D #4, task
2b-repair-13b): each poll's timeout is clamped to what remains of it, each sleep is
bounded by it, and the time a request itself takes counts.

And so is each exchange's (2b-repair-13d, Astra R13B-1): the `timeout` a transport is handed is the
WHOLE exchange's — connect, request, status line and headers, body — not the longest it waits on one
socket operation, which a reply arriving a chunk at a time renews for ever. The default transport
(http_transport) takes one absolute deadline when it is called and arms every blocking socket call with what
is left of it, so no reply can outlast it by arriving a chunk at a time; and no exchange resolves a name
(2b-repair-15, Astra's final 2b review F2): `getaddrinfo` cannot be interrupted in-process, and the
constraints below leave no way to give it a deadline, so it is kept off every deadline the client holds.
An exchange connects to an address it was handed (an IP literal is its own address; a name was looked up
beforehand, `GatewayClient.resolve`) and keeps the NAME for the TLS server name and the certificate check.
The lookup is made at construction (the default transport, a name) and again only when the owner calls
`resolve()` between operations, which a connection failure invites (`endpoint_stale`); never by an exchange,
a poll or a search. A connection failure, or a lookup that finds nothing, withdraws the addresses (2b-repair-16,
Astra R15-1): no exchange connects, or sends its request and token, until the owner's `resolve()` succeeds. The
time it takes is the CALLER's, outside every exchange's and poll's deadline; the client cannot bound it (see
`resolve`). The client does not rest on the transport for the rest either: a reply that completes after its
exchange's budget is a timeout whatever it says (`_exchange`), so a late `done` is never a result, for any
transport. The mechanism is in-process and stdlib-only on purpose: the client has no spawn capability (BOUNDARIES: the
supervisor owns every lifecycle) and a thread cannot be killed, so a worker thread left behind a timed wait
would be exactly what a deadline must not leave.

What this client does not do: write the store (the router records what it returns) or
pick lanes or policy (the gateway plans; the grant binds).
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
import types
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Mapping, NamedTuple, Sequence

from gen2.core import canonical, pagination
from gen2.gateway_client import observe

REQUEST_TYPES = pagination.REQUEST_TYPES
POLL_SECONDS = 0.5
NO_NAMES: Mapping = types.MappingProxyType({})   # no name was looked up beforehand: only an IP literal can be connected to


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None   # a gateway answer is never a redirect; following one could send the bearer token elsewhere


class _Deadline:
    """One absolute point on the monotonic clock, shared by every blocking step of one exchange."""

    def __init__(self, seconds: float) -> None:
        self._at = time.monotonic() + seconds

    def remaining(self) -> float:
        """Seconds left, or TimeoutError when none are: a step that would start after the deadline never starts."""
        left = self._at - time.monotonic()
        if left <= 0:
            raise TimeoutError("the exchange's deadline passed")
        return left


class _DeadlineSocket(socket.socket):
    """A socket whose every blocking call is armed with what is left of the exchange's deadline, never with a fresh
    timeout: a reply that trickles in, one chunk inside each socket timeout, still stops at the deadline. (`sendall`'s
    timeout is already the whole call's.)"""
    deadline: _Deadline | None = None

    def _arm(self) -> None:
        if self.deadline is not None:
            self.settimeout(self.deadline.remaining())

    def recv(self, *args):
        self._arm()
        return super().recv(*args)

    def recv_into(self, *args):
        self._arm()
        return super().recv_into(*args)

    def send(self, *args):
        self._arm()
        return super().send(*args)

    def sendall(self, *args):
        self._arm()
        return super().sendall(*args)


class _DeadlineSSLSocket(ssl.SSLSocket):
    """The same for a TLS socket, whose reads and writes go through `read` and `send`; its handshake, done inside
    wrap_socket, runs under the timeout the connected socket was armed with, itself the time that was left."""
    deadline: _Deadline | None = None

    def _arm(self) -> None:
        if self.deadline is not None:
            self.settimeout(self.deadline.remaining())

    def read(self, *args):
        self._arm()
        return super().read(*args)

    def send(self, *args):
        self._arm()
        return super().send(*args)


def _literal(host: str, port: int) -> list | None:
    """The address a host that IS an address (an IPv4 or IPv6 literal) stands for, as getaddrinfo would give it; None for a name."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if ip.version == 6:
        return [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, port, 0, 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, port))]


def _connect(address: tuple, deadline: _Deadline, resolved: Mapping = NO_NAMES) -> _DeadlineSocket:
    """A connected socket, whose connect took only the time left. It never resolves a name: an IP literal is its own address, and a name must
    have been looked up beforehand (`resolved`: (lower-case host, port) -> getaddrinfo's results); one that was not is a failed connect."""
    host, port = address
    error: OSError = OSError(f"{host}:{port} has no resolved address: an exchange never resolves a name")
    deadline.remaining()
    for family, kind, proto, _, target in _literal(host, port) or resolved.get((host.lower(), port), ()):
        sock = _DeadlineSocket(family, kind, proto)
        sock.deadline = deadline
        try:
            sock.settimeout(deadline.remaining())
            sock.connect(target)
            sock.settimeout(deadline.remaining())   # the next step (a TLS handshake) runs under what is left after the connect
            return sock
        except OSError as e:   # a TimeoutError among them: the next address finds no time either, and the last error is raised
            sock.close()
            error = e
    raise error


class _DeadlineHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, deadline: _Deadline, resolved: Mapping = NO_NAMES, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._deadline = deadline
        self._create_connection = lambda address, timeout, source_address: _connect(address, deadline, resolved)


class _DeadlineHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, deadline: _Deadline, resolved: Mapping = NO_NAMES, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._deadline = deadline
        self._create_connection = lambda address, timeout, source_address: _connect(address, deadline, resolved)
        self._context.sslsocket_class = _DeadlineSSLSocket

    def connect(self) -> None:
        super().connect()
        self.sock.deadline = self._deadline


def _opener(deadline: _Deadline, resolved: Mapping) -> urllib.request.OpenerDirector:
    class Http(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(lambda host, **kw: _DeadlineHTTPConnection(host, deadline=deadline, resolved=resolved, **kw), req)

    class Https(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(lambda host, **kw: _DeadlineHTTPSConnection(host, deadline=deadline, resolved=resolved, **kw), req, context=self._context)
    return urllib.request.build_opener(_NoRedirect, Http, Https)


def http_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float, resolved: Mapping | None = None) -> tuple:
    """(status, headers, body, error): one HTTP exchange that never raises and never follows a redirect.

    `timeout` is the whole exchange's: one absolute deadline, taken when the call starts, over the connect, the
    request, the status line and headers, and the body. Every blocking socket operation is given what is left of it
    (_DeadlineSocket) and an operation that would start after it does not, so no reply can outlast it by arriving a
    chunk at a time. The exchange resolves no name (2b-repair-15, Astra F2: getaddrinfo cannot be interrupted
    in-process, so a lookup inside the deadline can run past it by the resolver's own time): the host of `url` is an IP
    literal, or a name in `resolved` ((lower-case host, port) -> getaddrinfo's results, looked up beforehand by the
    caller: GatewayClient.resolve), and a name that is in neither is a transport failure at once. The name stays the
    host of the request: it is what the TLS server name and the certificate check use, and the Host header says."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with _opener(_Deadline(timeout), NO_NAMES if resolved is None else resolved).open(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read(), None
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except Exception:
            raw = b""
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, raw, None
    except (TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        return None, {}, b"", "timeout" if isinstance(reason, TimeoutError) or "timed out" in str(reason) else "transport_failure"


# a refused HTTP status → the observation that says what is known (never a count)
REFUSED = {400: ("unknown", "payload_invalid"), 401: ("auth_failed", "credentials_rejected"),
           403: ("not_searched", None), 404: ("unknown", "transport_failure")}


def _echoes(obs: dict, ctx: dict) -> bool:
    """The gateway's observation names THIS invocation and attempt (H-1): anything else cannot be attributed to it."""
    return obs.get("invocation_id") == ctx["invocation_id"] and type(obs.get("attempt")) is int and obs["attempt"] == ctx["attempt"]


def _captured(obs: dict) -> bool:
    return obs.get("captured") is True and type(obs.get("call_ref")) is int


class Resolution(NamedTuple):
    """One lookup of the gateway's name, as the record of it for whoever owns the call to keep: what was asked, what came back (the addresses) or why nothing did, and how long it took."""
    host: str
    port: int
    addresses: tuple
    error: str | None
    elapsed: float
    at: str


class GatewayClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 130.0, deadline: float = 300.0,
                 transport: Callable | None = None, clock: Callable[[], str] = utc_now,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic,
                 resolver: Callable | None = None):
        """`transport` None (or `http_transport` itself) is the real one, over the addresses this client looked up. With it and a gateway that is a name
        (`http://gateway:8765`, GEN2_GATEWAY_URL), the name is looked up HERE, once (`resolve`), outside any exchange: a failed lookup does not fail the construction
        (a dependency's failure is a capability fact, not an outage of the engine: DEPLOYMENT-CONTRACT 1.2), it leaves the endpoint stale, and every exchange then fails at
        once as a transport failure until the owner's `resolve()` succeeds. A transport handed in (a test's) is not the client's to resolve for, and an IP literal needs
        no lookup. `resolver` is getaddrinfo's signature (socket.getaddrinfo when None, looked up at each call)."""
        self.base_url, self.token, self.timeout, self.deadline = base_url.rstrip("/"), token, timeout, deadline
        self._clock, self._sleep, self._monotonic, self._resolver = clock, sleep, monotonic, resolver
        parts = urllib.parse.urlsplit(self.base_url)
        self._origin = ((parts.hostname or "").lower(), parts.port or (443 if parts.scheme == "https" else 80))   # the key http_transport's `resolved` is looked up by
        self._resolved: dict = {}
        self._stale, self.last_resolution = False, None
        real = transport is None or transport is http_transport
        self._transport = self._resolving_transport if real else transport
        if real and _literal(*self._origin) is None:
            self.resolve()

    def _resolving_transport(self, method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple:
        return http_transport(method, url, headers, body, timeout, resolved=self._resolved)

    @property
    def endpoint_stale(self) -> bool:
        """True when the gateway's name has no good lookup (the last one failed, or an exchange has failed to connect since): no exchange connects to it until the owner's `resolve()` succeeds."""
        return self._stale

    def _withdraw(self) -> None:
        """The endpoint is stale, and a stale endpoint has no addresses to connect to: both facts change here, together (2b-repair-16, Astra R15-1: a flag no exchange read let a failed re-lookup,
        or a connection that had failed, keep sending the bearer token to whatever now answers at the old address). `last_resolution` stays as the record of what the last lookup found."""
        self._stale = True
        self._resolved.pop(self._origin, None)

    def resolve(self) -> Resolution:
        """Look the gateway's name up (again), now: the one place besides the construction where this client resolves a name, and never called by an exchange, a poll or
        a search (2b-repair-15, Astra F2: an exchange that resolves can run past its deadline by the resolver's own time, which cannot be interrupted). A connection failure
        withdraws the endpoint's addresses (`endpoint_stale`) and nothing else; looking again is the OWNER's call, made between operations and before the next exchange's deadline
        starts. A lookup that finds nothing withdraws them too: until a lookup finds addresses, every exchange is a transport failure at once, with no connection made and no request
        or token sent. The Resolution is returned and kept (`last_resolution`) for the owner to record.

        The time this takes is the caller's, and it is NOT bounded here: getaddrinfo cannot be interrupted, and the client may not leave a thread running or start a process
        (BOUNDARIES: the supervisor owns every lifecycle), so whichever call this is made from waits for the resolver. Nothing in gen-2 constructs a GatewayClient or calls
        this yet; the first caller must place it under a bound it owns."""
        host, port = self._origin
        began, at = self._monotonic(), self._clock()
        found, error = _literal(host, port), None   # an address needs no lookup
        if found is None:
            try:
                found = list((self._resolver or socket.getaddrinfo)(host, port, 0, socket.SOCK_STREAM))
                error = None if found else f"{host}:{port} resolved to no address"
            except OSError as e:
                found, error = [], f"{type(e).__name__}: {e}"
        if found:
            self._resolved[self._origin] = found
            self._stale = False
        else:
            self._withdraw()
        self.last_resolution = Resolution(host, port, tuple(sorted({info[4][0] for info in found})), error, self._monotonic() - began, at)
        return self.last_resolution

    def _exchange(self, method: str, path: str, body: dict | None, token: str, headers: dict | None = None, timeout: float | None = None):
        """(status, parsed JSON dict or None, error class or None). `timeout`: this exchange's own, never above the client's,
        and the whole exchange's (the transport's contract): a reply that completes after it is a timeout, whatever it says."""
        hdrs = {"Accept": "application/json", "Authorization": f"Bearer {token}", **(headers or {})}
        data = None
        if body is not None:
            data = canonical.canonical_bytes(body)
            hdrs["Content-Type"] = "application/json"
        budget = self.timeout if timeout is None else min(self.timeout, timeout)
        started = self._monotonic()
        status, resp_headers, raw, error = self._transport(method, self.base_url + path, hdrs, data, budget)
        if status is None:
            if (error or "transport_failure") == "transport_failure" and _literal(*self._origin) is None:
                self._withdraw()   # a connection failure withdraws the addresses and invites a new lookup: the owner's `resolve()`, never made here
            return None, None, error or "transport_failure"
        if self._monotonic() - started > budget:
            return None, None, "timeout"   # a terminal reply that arrives after the deadline is not a result (Astra R13B-1)
        if resp_headers.get("x-research-gateway") != "result" or "json" not in resp_headers.get("content-type", ""):
            return status, None, "payload_invalid"   # not a gateway answer (a proxy page, a raw file)
        try:
            doc = canonical.parse_json_strict(raw)
        except canonical.CanonicalizationError:
            return status, None, "payload_invalid"
        return status, doc if isinstance(doc, dict) else None, None if isinstance(doc, dict) else "payload_invalid"

    # ------------------------------------------------------------------ grants
    def grant(self, *, topic_id: str, commercial: bool, accept_per_item: bool, invocation_id: str,
              domain: str | None = None, ttl_seconds: int = 3600) -> dict:
        """Mint a station grant for one invocation of one topic (the engine's token must be a
        configured grantor). Raises GrantRefused with the gateway's reason."""
        req = {"topic_id": topic_id, "commercial": commercial, "accept_per_item": accept_per_item,
               "invocation_id": invocation_id, "ttl_seconds": ttl_seconds, **({"domain": domain} if domain else {})}
        status, doc, error = self._exchange("POST", "/v1/grants", req, self.token)
        if status != 201 or doc is None or not isinstance(doc.get("token"), str):
            raise GrantRefused(f"HTTP {status}: {(doc or {}).get('error') or error}")
        return doc

    # ------------------------------------------------------------------ search
    def search(self, request: dict, *, invocation_id: str, attempt: int, policy_version: str,
               obligation_ids: Sequence[str] = (), pages: int = 1, token: str | None = None) -> dict:
        """One logical request: `request` is a gateway payload with its `request_type`. Returns
        {"observations": [{"observation", "retrieval_events", "records", "delivery"}],
        "capability_facts", "telemetry_losses", "pages": [{"page", "sent", "effective_request",
        "gateway_request_identity", "delivery", "call_ref"}]} — one observation per lane per page."""
        rt = request.get("request_type")
        if rt not in REQUEST_TYPES or not isinstance(attempt, int) or attempt < 1 or pages < 1:
            raise ValueError("a search is a find/resolve/enrich/fetch/data request, attempt >= 1, pages >= 1")
        if pages > 1 and rt != "find":
            raise ValueError("only find answers page")
        ctx = {"invocation_id": invocation_id, "attempt": attempt, "obligation_ids": list(obligation_ids),
               "policy_version": policy_version, "token": token or self.token}
        out = {"observations": [], "capability_facts": [], "telemetry_losses": [], "pages": []}
        sent = request
        for page in range(1, pages + 1):
            started = self._clock()
            answer = self._answer(sent, ctx)
            ended = self._clock()
            out["capability_facts"] += answer["facts"]
            out["telemetry_losses"] += answer["losses"]
            out["pages"].append({"page": page, "sent": sent, "effective_request": answer["effective"],
                                 "gateway_request_identity": answer["gateway_identity"], "delivery": answer["delivery"],
                                 "call_ref": answer["call_ref"]})
            fact_id = next((f["fact_id"] for f in answer["facts"] if f["capability"].startswith("gateway.secrets")), None)
            call_ref = f"gw-call:{answer['call_ref']}" if answer["call_ref"] is not None else None
            going = {e["source"]: observe.cursor_of(e) for e in answer["lanes"]
                     if e.get("completeness") == "complete" and observe.cursor_of(e) is not None}
            for entry in answer["lanes"]:
                # a lane still going when the page cap is reached ends here with its cursor in hand: limit_reached, not an end
                obs = observe.observation(entry, request={"lane": entry["source"], "page": page, "request": sent},
                                          started_at=started, ended_at=ended, call_ref=call_ref, fact_id=fact_id,
                                          capped=page == pages and entry["source"] in going,
                                          **{k: ctx[k] for k in ("invocation_id", "attempt", "obligation_ids", "policy_version")})
                obs["records"] = observe.lane_records({"records": answer["records"]}, entry["source"])
                obs["delivery"] = answer["delivery"]
                out["observations"].append(obs)
            if not going:
                break
            sent = {**request, "cursors": going, "lanes": sorted(going)}
        out["capability_facts"] = list({f["fact_id"]: f for f in out["capability_facts"]}.values())   # one snapshot, however many pages carried it
        return out

    def _answer(self, sent: dict, ctx: dict) -> dict:
        """One gateway request, polled to completion: its lanes (each validated, or replaced by
        an unknown one), records, capability facts, capture losses, delivery and echo."""
        payload = {k: v for k, v in sent.items() if k != "request_type"}
        status, doc, error = self._exchange("POST", f"/v1/{sent['request_type']}", payload, ctx["token"], _headers(ctx))
        named = sent.get("lanes") or [observe.GATEWAY_LANE]
        result = {"lanes": [], "records": [], "facts": [], "losses": [], "call_ref": None, "delivery": None,
                  "effective": None, "gateway_identity": None}

        def failed(coverage: str, error_class: str | None, loss: str | None = None) -> dict:
            result["lanes"] = [observe.unobserved(sid, coverage, error_class) for sid in named]
            if loss:
                result["losses"].append({"reason": loss, **{k: ctx[k] for k in ("invocation_id", "attempt")}})
            return result

        def lost(reason: str) -> None:
            result["losses"].append({"reason": reason, **{k: ctx[k] for k in ("invocation_id", "attempt")}})

        if status is None:                        # nothing answered: a transport failure or a timeout
            return failed("unknown", error)
        if status in REFUSED:                      # the gateway refused the request itself
            return failed(*REFUSED[status])
        if not 200 <= status < 300 or doc is None:  # a gateway error, or a success that is not a gateway answer
            return failed("unknown", "payload_invalid" if 200 <= status < 300 else "transport_failure")
        obs = doc.get("observation") if isinstance(doc.get("observation"), dict) else {}
        if not _echoes(obs, ctx):
            # an answer that does not say it is THIS invocation's cannot be attributed to it (H-1)
            return failed("unknown", "payload_invalid", "the gateway's answer did not echo this invocation and attempt")
        captured = _captured(obs)
        if captured:
            result["call_ref"] = obs["call_ref"]
        else:
            lost(str(obs.get("capture_loss") or "the gateway did not acknowledge a durable request row"))
        result["delivery"] = {"served": obs.get("served"), "dispatched_by": obs.get("dispatched_by"), "job_id": obs.get("job_id")}
        if doc.get("status") in ("queued", "running"):
            job, poll = self._poll(doc.get("job_id"), ctx)
            if job is None:
                return failed("unknown", "timeout")          # never finished by the deadline: nothing observed
            if poll is None:
                return failed("unknown", "payload_invalid", "the gateway's answer to a poll did not echo this invocation and attempt")
            if not _captured(poll):
                captured = False
                lost(str(poll.get("capture_loss") or "the gateway did not acknowledge a durable row for this caller's poll"))
            if job.get("status") != "done" or not isinstance(job.get("result"), dict):
                return failed("unknown", "transport_failure")  # the job failed: what it observed is unknown
            doc = job["result"]
        lanes, records = doc.get("lanes"), doc.get("records")
        if not isinstance(lanes, list) or not isinstance(records, list):
            return failed("unknown", "payload_invalid")   # the whole answer, not only its lanes: no records list is unreadable
        if not lanes:
            lanes = _record_cache_lanes(doc, sent)
            if lanes is None:
                return failed("unknown", "payload_invalid")   # no lanes and not a record-cache hit: nothing observed, never empty
        result["effective"] = doc.get("effective_request") if isinstance(doc.get("effective_request"), dict) else None
        result["gateway_identity"] = doc.get("request_identity") if isinstance(doc.get("request_identity"), str) else None
        for entry in lanes:
            problem = observe.lane_problem(entry)
            sid = entry.get("source") if isinstance(entry, dict) and isinstance(entry.get("source"), str) else None
            if problem and sid is None:
                return failed("unknown", "payload_invalid")
            entry = observe.unobserved(sid, "unknown", "payload_invalid") if problem else observe.metadata_only_named(entry, sent)
            result["lanes"].append(entry if captured else observe.uncaptured(entry))
        answered = {e["source"] for e in result["lanes"]}
        result["lanes"] += [observe.unobserved(sid, "unknown", "payload_invalid") for sid in sent.get("lanes") or [] if sid not in answered]
        result["records"] = [r for r in records if isinstance(r, dict)]
        result["facts"] = [f for f in (observe.capability_fact(x) for x in doc.get("capability_facts") or []) if f]
        return result

    def _poll(self, job_id, ctx: dict) -> tuple[dict | None, dict | None]:
        """(the finished job — done or failed —, this caller's observation of it), polled under
        the caller's own invocation and attempt (the gateway binds and records every poll,
        2b-repair A5): (None, None) when it does not finish by the deadline, (job, None) when
        the poll's answer does not echo this caller. The deadline is one absolute monotonic
        point (Gate D #4): what a poll takes comes out of it, and so does every sleep."""
        if isinstance(job_id, bool) or not isinstance(job_id, int):
            return None, None
        deadline = self._monotonic() + self.deadline
        while (remaining := deadline - self._monotonic()) > 0:
            status, job, _ = self._exchange("GET", f"/v1/jobs/{job_id}", None, ctx["token"], _headers(ctx), timeout=remaining)
            if status == 200 and job and job.get("status") in ("done", "failed"):
                obs = job.get("observation") if isinstance(job.get("observation"), dict) else {}
                return job, (obs if _echoes(obs, ctx) else None)
            self._sleep(min(POLL_SECONDS, max(deadline - self._monotonic(), 0.0)))
        return None, None


def _headers(ctx: dict) -> dict:
    return {"X-Research-Invocation": ctx["invocation_id"], "X-Research-Attempt": str(ctx["attempt"])}


def _record_cache_lanes(doc: dict, sent: dict) -> list[dict] | None:
    """The one lane of a record-cache hit, or None (2b-repair A1, A2). A resolve the gateway
    answered from a record it already holds has no lanes of its own; it must say so
    (cache_hit, served_from record_cache) and carry exactly the one record it repeats, whose
    source's earlier dispatch that is — so that source is its lane, and the same attempt
    delivered again from the cache is the same observation, never a second one."""
    recs = doc.get("records")
    if sent.get("request_type") != "resolve" or doc.get("cache_hit") is not True or doc.get("served_from") != "record_cache" \
            or len(recs) != 1 or not isinstance(recs[0], dict):
        return None
    identity, source = recs[0].get("identity"), recs[0].get("source_id")
    if not (isinstance(identity, str) and identity and isinstance(source, str) and source):
        return None
    return [{"source": source, "coverage": "searched_ok", "completeness": "complete", "count": 1, "retrieved": [identity]}]


class GrantRefused(Exception):
    """The gateway would not mint the grant (not a grantor, a bad request, unreachable)."""
