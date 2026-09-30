"""The engine's typed door to the Gateway service (task 2b; BOUNDARIES.md Gateway).

The gateway runs as its own process and is never imported (INVARIANTS B-2); this client
speaks its HTTP API (gateway/docs/STATION-CONTRACT.md, OPERATIONS.md). It carries the
invocation and attempt on every request (H-1), mints per-invocation grants for stations
(the gateway enforces a grant's topic policy on every door), and turns every answer —
and every failure to get one — into search-observation documents for the router's
record_observation (observe.py), plus the capability facts the gateway reported and the
telemetry the gateway could not capture durably. Nothing it cannot read becomes zero
results: a transport failure, a timeout, a refused or unreadable answer, a job that
failed or never finished, an answer that does not echo the invocation it was asked under
— each is an observation with coverage `unknown` (or the gateway's own degraded state)
and no count (RG-4, RG-U).

Pagination (find, pages > 1): each lane still answering with a `next` cursor is asked
again, alone with the other continuing lanes (the `lanes` filter), under the same
invocation and attempt. A lane's pages are one observation of the logical request
("pages": N): complete when every page read was complete; when a later page fails after
earlier pages were read, `partial` with error_class `partial_pagination` and the
identities actually observed as a LOWER BOUND — never rounded up to what the provider
claimed; the first page failing is that page's own failure (task 2b; INVARIANTS RG-4).

Queued answers are polled until the job finishes or the client's deadline passes; a
deadline that passes is `unknown`/`timeout`, never an empty result.

What this client does not do: write the store (the router records what it returns), pick
lanes or policy (the gateway plans; the grant binds), or record a gateway capability fact
before the observations that reference it — the caller must (the router has no command
for gateway-reported facts yet: an open question for 2c/2e).
"""
from __future__ import annotations

import json
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
        {"observations": [{"observation", "retrieval_events", "records"}], "capability_facts",
        "telemetry_losses", "effective_request", "gateway_request_identity"}."""
        rt = request.get("request_type")
        if rt not in REQUEST_TYPES or not isinstance(attempt, int) or attempt < 1 or pages < 1:
            raise ValueError("a search is a find/resolve/enrich/fetch/data request, attempt >= 1, pages >= 1")
        if pages > 1 and rt != "find":
            raise ValueError("only find answers page")
        token = token or self.token
        ctx = {"invocation_id": invocation_id, "attempt": attempt, "obligation_ids": list(obligation_ids),
               "policy_version": policy_version, "token": token}
        started = self._clock()
        answer = self._answer(request, ctx)
        lanes = {e["source"]: {"entry": e, "pages": [e]} for e in answer["lanes"]}
        refs = [answer["call_ref"]] if answer["call_ref"] else []
        records = answer["records"]
        for _ in range(pages - 1):
            going = {sid: s["pages"][-1]["next"] for sid, s in lanes.items()
                     if s["pages"][-1].get("completeness") == "complete" and isinstance(s["pages"][-1].get("next"), (str, int))
                     and s["pages"][-1]["next"] != "exhausted"}
            if not going:
                break
            page = self._answer({**request, "cursors": going, "lanes": sorted(going)}, ctx)
            refs += [page["call_ref"]] if page["call_ref"] else []
            records += page["records"]
            answer["facts"] += page["facts"]
            answer["losses"] += page["losses"]
            got = {e["source"]: e for e in page["lanes"]}
            for sid in going:
                lanes[sid]["pages"].append(got.get(sid) or observe.unobserved(sid, "unknown", "payload_invalid"))
        ended = self._clock()
        answer["facts"] = list({f["fact_id"]: f for f in answer["facts"]}.values())   # one fact, however many pages carried it
        call_ref = ",".join(f"gw-call:{r}" for r in refs)
        if len(call_ref) > 500:
            call_ref = f"gw-call:{refs[0]}..{refs[-1]} ({len(refs)} requests)"
        out = {"observations": [], "capability_facts": answer["facts"], "telemetry_losses": answer["losses"],
               "effective_request": answer["effective"], "gateway_request_identity": answer["gateway_identity"]}
        fact_id = next((f["fact_id"] for f in answer["facts"] if f["capability"].startswith("gateway.secrets")), None)
        for sid, lane in lanes.items():
            entry = _pages_as_one(lane["pages"]) if pages > 1 else lane["entry"]
            doc = {"lane": sid, "gateway_request": answer["effective"], "gateway_request_identity": answer["gateway_identity"],
                   "pages": pages, "delivery": answer["delivery"]}
            obs = observe.observation(entry, request=doc, started_at=started, ended_at=ended,
                                      call_ref=call_ref or None, fact_id=fact_id, **{
                                          k: ctx[k] for k in ("invocation_id", "attempt", "obligation_ids", "policy_version")})
            obs["records"] = observe.lane_records({"records": records}, sid)
            out["observations"].append(obs)
        return out

    def _answer(self, request: dict, ctx: dict) -> dict:
        """One gateway request, polled to completion: its lanes (each validated, or replaced by
        an unknown one), records, capability facts, capture losses and identity."""
        headers = {"X-Research-Invocation": ctx["invocation_id"], "X-Research-Attempt": str(ctx["attempt"])}
        payload = {k: v for k, v in request.items() if k != "request_type"}
        status, doc, error = self._exchange("POST", f"/v1/{request['request_type']}", payload, ctx["token"], headers)
        named = request.get("lanes") or [observe.GATEWAY_LANE]
        result = {"lanes": [], "records": [], "facts": [], "losses": [], "call_ref": None, "delivery": None,
                  "effective": None, "gateway_identity": None}

        def failed(coverage: str, error_class: str | None, loss: str | None = None) -> dict:
            result["lanes"] = [observe.unobserved(sid, coverage, error_class) for sid in named]
            if loss:
                result["losses"].append({"reason": loss, **{k: ctx[k] for k in ("invocation_id", "attempt")}})
            return result

        if status is None:                        # nothing answered: a transport failure or a timeout
            return failed("unknown", error)
        if status in REFUSED:                      # the gateway refused the request itself
            return failed(*REFUSED[status])
        if not 200 <= status < 300 or doc is None:  # a gateway error, or a success that is not a gateway answer
            return failed("unknown", "payload_invalid" if 200 <= status < 300 else "transport_failure")
        obs = doc.get("observation") if isinstance(doc.get("observation"), dict) else {}
        if (obs.get("invocation_id"), obs.get("attempt")) != (ctx["invocation_id"], ctx["attempt"]):
            # an answer that does not say it is THIS invocation's cannot be attributed to it (H-1)
            return failed("unknown", "payload_invalid", "the gateway's answer did not echo this invocation and attempt")
        if isinstance(obs.get("call_ref"), int) and obs.get("captured"):
            result["call_ref"] = obs["call_ref"]
        else:
            result["losses"].append({"reason": str(obs.get("capture_loss") or "the gateway did not acknowledge a durable request row"),
                                     **{k: ctx[k] for k in ("invocation_id", "attempt")}})
        result["delivery"] = {"served": obs.get("served"), "dispatched_by": obs.get("dispatched_by"), "job_id": obs.get("job_id")}
        if doc.get("status") in ("queued", "running"):
            job = self._poll(doc.get("job_id"), ctx)
            if job is None:
                return failed("unknown", "timeout")          # never finished by the deadline: nothing observed
            if job.get("status") != "done" or not isinstance(job.get("result"), dict):
                return failed("unknown", "transport_failure")  # the job failed: what it observed is unknown
            doc = job["result"]
        lanes = doc.get("lanes")
        if not isinstance(lanes, list) or (not lanes and request.get("lanes")):
            return failed("unknown", "payload_invalid")
        result["effective"] = doc.get("effective_request") if isinstance(doc.get("effective_request"), dict) else None
        result["gateway_identity"] = doc.get("request_identity") if isinstance(doc.get("request_identity"), str) else None
        for entry in lanes:
            problem = observe.lane_problem(entry)
            sid = entry.get("source") if isinstance(entry, dict) and isinstance(entry.get("source"), str) else None
            if problem and sid is None:
                return failed("unknown", "payload_invalid")
            result["lanes"].append(observe.unobserved(sid, "unknown", "payload_invalid") if problem else entry)
        if not lanes:   # an answer served without lanes (a record-cache hit) observed the records it returned
            recs = [r for r in doc.get("records") or [] if isinstance(r, dict) and isinstance(r.get("identity"), str)]
            result["lanes"] = [{"source": doc.get("served_from") or observe.GATEWAY_LANE, "coverage": "searched_ok" if recs else "searched_empty",
                                "completeness": "complete", "count": len(recs), "retrieved": [r["identity"] for r in recs]}]
        result["records"] = [r for r in doc.get("records") or [] if isinstance(r, dict)]
        result["facts"] = [f for f in (observe.capability_fact(x) for x in doc.get("capability_facts") or []) if f]
        return result

    def _poll(self, job_id, ctx: dict) -> dict | None:
        """The finished (done or failed) job, or None when it does not finish by the deadline."""
        if isinstance(job_id, bool) or not isinstance(job_id, int):
            return None
        waited = 0.0
        while waited <= self.deadline:
            status, job, _ = self._exchange("GET", f"/v1/jobs/{job_id}", None, ctx["token"])
            if status == 200 and job and job.get("status") in ("done", "failed"):
                return job
            self._sleep(POLL_SECONDS)
            waited += POLL_SECONDS
        return None


def _pages_as_one(pages: list[dict]) -> dict:
    """A lane's pages as one observation: the first page's failure is the lane's; a later
    page's failure makes what was read a partial set, a lower bound (partial_pagination)."""
    first = pages[0]
    if first.get("completeness") == "unobserved":
        return first
    retrieved = [i for p in pages if p.get("completeness") != "unobserved" for i in p.get("retrieved") or []]
    broken = next((p for p in pages[1:] if p.get("completeness") != "complete"), None)
    partial = broken is not None or any(p.get("completeness") == "partial" for p in pages)
    # a continuation exists only after a first page that returned records, so a partial set
    # always has at least those: its count is what was read, a lower bound
    entry = {"source": first["source"], "coverage": "searched_ok" if retrieved else first["coverage"],
             "count": len(retrieved), "retrieved": retrieved, "completeness": "partial" if partial else "complete"}
    if partial:
        entry["error_class"] = "partial_pagination" if broken is not None else "payload_invalid"
    return entry


class GrantRefused(Exception):
    """The gateway would not mint the grant (not a grantor, a bad request, unreachable)."""
