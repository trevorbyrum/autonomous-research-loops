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

Queued answers are polled until the job finishes or the client's deadline passes; a
deadline that passes is `unknown`/`timeout`, never an empty result.

What this client does not do: write the store (the router records what it returns) or
pick lanes or policy (the gateway plans; the grant binds).
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Sequence

from gen2.core import canonical
from gen2.gateway_client import observe

REQUEST_TYPES = ("find", "resolve", "enrich", "fetch", "data")
POLL_SECONDS = 0.5


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None   # a gateway answer is never a redirect; following one could send the bearer token elsewhere


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple:
    """(status, headers, body, error): one HTTP exchange that never raises and never follows a redirect."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
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


class GatewayClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 130.0, deadline: float = 300.0,
                 transport: Callable = http_transport, clock: Callable[[], str] = utc_now,
                 sleep: Callable[[float], None] = time.sleep):
        self.base_url, self.token, self.timeout, self.deadline = base_url.rstrip("/"), token, timeout, deadline
        self._transport, self._clock, self._sleep = transport, clock, sleep

    def _exchange(self, method: str, path: str, body: dict | None, token: str, headers: dict | None = None):
        """(status, parsed JSON dict or None, error class or None)."""
        hdrs = {"Accept": "application/json", "Authorization": f"Bearer {token}", **(headers or {})}
        data = None
        if body is not None:
            data = canonical.canonical_bytes(body)
            hdrs["Content-Type"] = "application/json"
        status, resp_headers, raw, error = self._transport(method, self.base_url + path, hdrs, data, self.timeout)
        if status is None:
            return None, None, error or "transport_failure"
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
            for entry in answer["lanes"]:
                obs = observe.observation(entry, request={"lane": entry["source"], "page": page, "request": sent},
                                          started_at=started, ended_at=ended, call_ref=call_ref, fact_id=fact_id,
                                          **{k: ctx[k] for k in ("invocation_id", "attempt", "obligation_ids", "policy_version")})
                obs["records"] = observe.lane_records({"records": answer["records"]}, entry["source"])
                obs["delivery"] = answer["delivery"]
                out["observations"].append(obs)
            going = {e["source"]: e["next"] for e in answer["lanes"]
                     if e.get("completeness") == "complete" and type(e.get("next")) in (str, int) and e["next"] != "exhausted"}
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
        the poll's answer does not echo this caller."""
        if isinstance(job_id, bool) or not isinstance(job_id, int):
            return None, None
        waited = 0.0
        while waited <= self.deadline:
            status, job, _ = self._exchange("GET", f"/v1/jobs/{job_id}", None, ctx["token"], _headers(ctx))
            if status == 200 and job and job.get("status") in ("done", "failed"):
                obs = job.get("observation") if isinstance(job.get("observation"), dict) else {}
                return job, (obs if _echoes(obs, ctx) else None)
            self._sleep(POLL_SECONDS)
            waited += POLL_SECONDS
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
