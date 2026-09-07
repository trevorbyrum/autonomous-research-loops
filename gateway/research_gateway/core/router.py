"""Router: request → lanes (PLAN.md §4, rules R-1..R-10), and the executor that
runs the lanes through the metered client, dedups, enforces licences, caches.

Everything routable comes from the registry rows plus what each adapter
declares about itself (CAPABILITIES, ENRICHES, SCHEMES, HOSTS, AGENCIES):
adding a source is a seed row and an adapter file, never an edit here (I-2).
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable
from urllib.parse import urlsplit

from ..adapters.base import AdapterError, Client, SourceUnavailable
from . import calllog, dedup, licenses
from . import identity as ident
from .cache import Cache

DOMAINS = {"finance", "market", "social", "management", "ai-ml", "software", "biomed"}
OTHER = "other"
RECENT_DAYS = 30
FIND_KINDS = ("article", "dataset", "venue", "repository")   # venue/repository come from the local index (§8)
FIND_KWARGS = ("limit", "year_from_", "kind", "domain")


@dataclass
class Lane:
    source_id: str
    role: str                       # base | domain | primary | fallback | single
    note: str | None = None


@dataclass
class Plan:
    request_type: str
    lanes: list[Lane] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)   # capability facts (R-8, R-10, refusals)
    domain_resolved: str = OTHER


def resolve_domain(domain: str | None) -> str:
    return domain if domain in DOMAINS else OTHER


def is_recent(payload: dict, today: date | None = None) -> bool:
    """R-7: a request for items dated within the last 30 days."""
    after = payload.get("published_after")
    if not after:
        return False
    try:
        d = date.fromisoformat(str(after)[:10])
    except ValueError:
        return False
    return d >= (today or date.today()) - timedelta(days=RECENT_DAYS)


def _schemes(mod) -> tuple[str, ...]:
    return tuple(getattr(mod, "SCHEMES", (getattr(mod, "SOURCE_ID", ""),)))


def _hosts(mod) -> tuple[str, ...]:
    hosts = getattr(mod, "HOSTS", None)
    if hosts:
        return tuple(urlsplit(h).netloc or h for h in hosts)
    base = getattr(mod, "BASE", None) or getattr(mod, "HOST", None)
    return (urlsplit(base).netloc,) if base else ()


def matches_scheme(mod, target: str) -> int:
    """SCHEMES entries are 'scheme' (matches 'scheme:...') or a full prefix containing ':'.
    Returns the length of the longest matching entry (0 = no match) so callers can
    prefer the most specific source, e.g. the WMS row over the generic Dataverse row."""
    t = target.lower()
    best = 0
    for s in _schemes(mod):
        s = s.lower()
        if (":" in s and t.startswith(s)) or (":" not in s and t.startswith(s + ":")):
            best = max(best, len(s))
    return best


class Router:
    def __init__(self, sources: list[dict], adapters: dict[str, object]):
        self.sources = {s["id"]: s for s in sources}
        self.adapters = adapters
        ident.register_schemes(s for mod in adapters.values() for s in _schemes(mod) if ":" not in s)
        ident.register_schemes(adapters)

    # ------------------------------------------------------------ helpers
    def _usable(self, sid: str, cap: str) -> bool:
        s = self.sources.get(sid)
        return bool(s and s.get("enabled") and cap in (s.get("capabilities") or []) and sid in self.adapters)

    def _ordered(self, cap: str) -> list[str]:
        return [sid for sid in self.sources if self._usable(sid, cap)]

    def _commercial_gate(self, sid: str, payload: dict, plan: Plan) -> bool:
        """R-8: with commercial=true, deny/unknown lanes are dropped and per-item
        lanes need accept_per_item. Returns True when the lane may run."""
        if not payload.get("commercial"):
            return True
        verdict = self.sources[sid].get("use_commercial")
        if verdict == "allow":
            return True
        if verdict == "per-item" and payload.get("accept_per_item"):
            return True
        plan.facts.append(f"{sid}: skipped, commercial verdict {verdict}"
                          + (" (set accept_per_item to include per-item lanes)" if verdict == "per-item" else ""))
        return False

    def _domain_lanes(self, kind: str, cap: str, domain: str, exclude: set[str]) -> list[str]:
        out = []
        for sid in self._ordered(cap):
            s = self.sources[sid]
            if sid in exclude or s.get("kind") != kind or not s.get("domains"):
                continue  # a source with no domains and no base_for is not a discovery lane (e.g. OpenAIRE, R-2)
            if domain == OTHER or domain in s["domains"]:
                out.append(sid)
        return out

    def record_allowed(self, record: dict, payload: dict) -> bool:
        """R-8 for one record (used for cache hits too, so a personal-mode cache never leaks
        into a commercial answer)."""
        src = self.sources.get(record.get("source_id"), {})
        return licenses.commercially_usable(src, record, payload)

    def persistable_sources(self, record: dict) -> set[str]:
        """Provenance members whose source lets the gateway keep their raw payload (§6)."""
        return {p.get("source_id") for p in record.get("provenance") or [{"source_id": record.get("source_id")}]
                if licenses.redistributable(self.sources.get(p.get("source_id"), {}), record)}

    # ------------------------------------------------------------ planning
    def plan(self, payload: dict, *, agency: str | None = None) -> Plan:
        rt = payload.get("request_type")
        plan = Plan(request_type=rt, domain_resolved=resolve_domain(payload.get("domain")))
        method = getattr(self, f"_plan_{rt}", None)
        if method is None:
            plan.facts.append(f"unknown request type {rt!r}")
            return plan
        method(payload, plan, agency)
        return plan

    def _plan_find(self, payload: dict, plan: Plan, _agency) -> None:
        kinds = [payload["kind"]] if payload.get("kind") in FIND_KINDS else ["article", "dataset"]
        recent = is_recent(payload)
        for kind in kinds:
            base = [sid for sid in self._ordered("find") if kind in (self.sources[sid].get("base_for") or [])]
            base.sort(key=lambda sid: 0 if getattr(self.adapters[sid], "LOCAL", False) else 1)  # local index first (§8)
            for sid in base:
                if recent and getattr(self.adapters[sid], "LOCAL", False):
                    plan.facts.append(f"{sid}: skipped, request is for the last {RECENT_DAYS} days (R-7)")
                    continue
                if self._commercial_gate(sid, payload, plan):
                    plan.lanes.append(Lane(sid, "base"))
            for sid in self._domain_lanes(kind, "find", plan.domain_resolved, set(base)):
                if self._commercial_gate(sid, payload, plan):
                    plan.lanes.append(Lane(sid, "domain"))

    def _plan_resolve(self, payload: dict, plan: Plan, agency: str | None) -> None:
        identity = payload.get("identity") or ""
        scheme, value = ident.parse(identity)
        if scheme == "doi":
            # R-1: the primary is the enabled resolver that declares this registration agency
            # (or '*' for any other); fallbacks are its substitution group, resolvers first,
            # then members that can at least return metadata through an OA-location enrichment.
            resolvers = self._ordered("resolve")
            primary = next((sid for sid in resolvers if agency and agency in getattr(self.adapters[sid], "AGENCIES", ())), None)
            if primary is None:
                primary = next((sid for sid in resolvers if "*" in getattr(self.adapters[sid], "AGENCIES", ())), None)
            group = (self.sources.get(primary, {}).get("substitution_group") if primary else None) or "doi-metadata"
            members = [sid for sid, s in self.sources.items() if s.get("substitution_group") == group and sid != primary]
            fallbacks = [sid for sid in members if self._usable(sid, "resolve")]
            fallbacks += [sid for sid in members if sid not in fallbacks and self._usable(sid, "enrich")
                          and "oa_location" in getattr(self.adapters[sid], "ENRICHES", ())]
            if primary and self._commercial_gate(primary, payload, plan):
                plan.lanes.append(Lane(primary, "primary", f"registration agency {agency or 'unknown'}"))
            for sid in fallbacks:
                if self._commercial_gate(sid, payload, plan):
                    plan.lanes.append(Lane(sid, "fallback"))
            if not plan.lanes:
                plan.facts.append("no DOI resolver available")
            return
        for sid in self._ordered("resolve"):
            if matches_scheme(self.adapters[sid], f"{scheme}:{value}") and self._commercial_gate(sid, payload, plan):
                plan.lanes.append(Lane(sid, "primary" if not plan.lanes else "fallback"))
        if not plan.lanes:
            plan.facts.append(f"no source resolves {scheme}: identities")

    def _plan_enrich(self, payload: dict, plan: Plan, _agency) -> None:
        what = payload.get("what")
        if not what:
            plan.facts.append("enrich needs 'what'")
            return
        lanes = [sid for sid in self._ordered("enrich") if what in getattr(self.adapters[sid], "ENRICHES", ())]
        # dedicated enrichment bases (citation graph, OA resolver) first, then platforms in seed order
        lanes.sort(key=lambda sid: 0 if {"citation", "oa-location"} & set(self.sources[sid].get("base_for") or []) else 1)
        for sid in lanes:
            if self._commercial_gate(sid, payload, plan):
                plan.lanes.append(Lane(sid, "primary" if not plan.lanes else "fallback"))
        if not plan.lanes:
            plan.facts.append(f"no source enriches {what!r}")

    def _plan_data(self, payload: dict, plan: Plan, _agency) -> None:
        sid = payload.get("source")
        if not sid or not self._usable(sid, "data") or self.sources[sid].get("kind") != "statistical":
            plan.facts.append(f"data needs 'source' naming an enabled statistical source (got {sid!r})")
            return
        if self._commercial_gate(sid, payload, plan):
            plan.lanes.append(Lane(sid, "single"))

    def _plan_fetch(self, payload: dict, plan: Plan, _agency) -> None:
        target = payload.get("target") or ""
        if not target:
            plan.facts.append("fetch needs 'target'")
            return
        url = target[4:] if target.startswith("url:") else target if target.startswith("http") else None
        candidates = []
        for sid in self._ordered("fetch"):
            mod = self.adapters[sid]
            if url:
                score = 1 if ("url" in _schemes(mod) and urlsplit(url).netloc in _hosts(mod)) else 0
            else:
                score = matches_scheme(mod, target)
            if score:
                candidates.append((-score, len(candidates), sid))
        for _, _, sid in sorted(candidates):
            if self._commercial_gate(sid, payload, plan):
                plan.lanes.append(Lane(sid, "primary" if not plan.lanes else "fallback"))
        if not plan.lanes:
            plan.facts.append(f"refused: {target!r} does not belong to a registry source with fetch (R-6)")


# ---------------------------------------------------------------- execution
def _call_find(mod, client: Client, payload: dict) -> dict:
    params = inspect.signature(mod.find).parameters
    kwargs = {"limit": payload.get("limit") or 20, "year_from_": payload.get("year_from"),
              "kind": payload.get("kind"), "domain": resolve_domain(payload.get("domain"))}
    return mod.find(client, payload.get("query") or "", **{k: v for k, v in kwargs.items() if k in params and v is not None})


def _log_cache_hit(client: Client, request_type: str, identity: str | None, query: str | None) -> None:
    rec = calllog.CallRecord(source_id="cache", request_type=request_type, status=200, latency_ms=0, job_id=client.job_id,
                             identity=identity, query=query, cache_hit=True, result_count=1, domain_resolved=client.domain_resolved,
                             client_id=client.client_id)
    client.log.append(rec)
    if client.conn is not None:
        calllog.record(client.conn, rec)


def _valid_records(items, facts: list[str], source_id: str) -> list[dict]:
    """Only well-formed canonical records count as an answer; the rest is a fact (R-10)."""
    good = [r for r in (items or []) if isinstance(r, dict) and r.get("identity") and r.get("kind")]
    if len(good) != len(items or []):
        facts.append(f"{source_id}: {len(items) - len(good)} malformed record(s) dropped")
    return good


def _run_lane(router: Router, rt: str, lane: Lane, payload: dict, client: Client, out: dict) -> list[dict]:
    mod = router.adapters[lane.source_id]
    if rt == "find":
        res = _call_find(mod, client, payload)
    elif rt == "resolve":
        if lane.source_id != lane.source_id.strip() or "resolve" not in getattr(mod, "CAPABILITIES", ()):
            items = mod.enrich(client, payload["identity"], "oa_location").get("items") or []
            res = {"records": [dict(items[0], kind="article")] if items else []}
        else:
            rec = mod.resolve(client, payload["identity"])
            res = {"records": [rec] if rec else []}
    elif rt == "enrich":
        res = mod.enrich(client, payload["identity"], payload["what"])
        res = {"records": res.get("items"), **{k: v for k, v in res.items() if k != "items"}}
    elif rt == "data":
        res = mod.data(client, payload.get("params") or {})
    else:  # fetch
        fparams = {k: v for k, v in (payload.get("params") or {}).items() if k in inspect.signature(mod.fetch).parameters}
        res = mod.fetch(client, payload["target"], **fparams)
        if "content" in res:
            out["content"], out["content_type"] = res["content"], res.get("content_type")
    if not isinstance(res, dict):
        raise TypeError(f"adapter returned {type(res).__name__}, not a result dict")
    if res.get("capability_fact"):
        out["facts"].append(f"{lane.source_id}: {res['capability_fact']}")
    return _valid_records(res.get("records"), out["facts"], lane.source_id)


def _drop_unlicensed(records: list[dict], router: Router, payload: dict, facts: list[str]) -> list[dict]:
    """R-8 second half: under commercial=true every returned record must pass the per-record gate."""
    if not payload.get("commercial"):
        return records
    kept = [r for r in records if router.record_allowed(r, payload)]
    if len(kept) != len(records):
        facts.append(f"{len(records) - len(kept)} record(s) dropped: not usable commercially (R-8)")
    return kept


def _search_payload(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k != "request_type"}


def execute(router: Router, payload: dict, client: Client, cache: Cache | None = None) -> dict:
    """Run a request end to end. Never raises for source trouble: those become facts (R-10)."""
    rt = payload.get("request_type")
    client.domain_resolved = resolve_domain(payload.get("domain"))
    out = {"request_type": rt, "records": [], "facts": [], "lanes": [], "domain_resolved": client.domain_resolved}
    agency = None
    if rt == "resolve" and ident.parse(payload.get("identity") or "")[0] == "doi":
        hit = cache.get_record(payload["identity"]) if cache is not None else None
        if hit and router.record_allowed(hit, payload):
            _log_cache_hit(client, rt, payload["identity"], None)
            return {**out, "records": [hit], "cache_hit": True}
        if "doi_org" in router.adapters and router._usable("doi_org", "resolve"):
            try:
                agency = (router.adapters["doi_org"].resolve(client, payload["identity"]) or {}).get("agency")
            except Exception as e:  # the lookup is metered like any call; its failure is a fact, not a crash
                out["facts"].append(f"doi_org: registration-agency lookup failed ({type(e).__name__}) — routing as unknown")
    if rt == "find" and cache is not None:
        hit = cache.get_search(cache.search_key(rt, _search_payload(payload)))
        if hit:
            _log_cache_hit(client, rt, None, payload.get("query"))
            return {**hit, "cache_hit": True}
    plan = router.plan(payload, agency=agency)
    out["facts"].extend(plan.facts)
    records: list[dict] = []
    for lane in plan.lanes:
        entry = {"source": lane.source_id, "role": lane.role}
        try:
            got = _run_lane(router, rt, lane, payload, client, out)
            entry["count"] = len(got)
        except SourceUnavailable as e:
            entry["error"] = str(e)
            out["facts"].append(f"{lane.source_id}: unavailable ({e.response.error or e.response.status}) — R-10")
            out["lanes"].append(entry)
            continue
        except AdapterError as e:
            entry["error"] = str(e)
            out["facts"].append(f"{lane.source_id}: refused ({e})")
            out["lanes"].append(entry)
            continue
        except Exception as e:  # anything else a lane throws is a source fact, never a dead job
            entry["error"] = f"{type(e).__name__}: {e}"[:300]
            out["facts"].append(f"{lane.source_id}: malformed response ({type(e).__name__}) — treated as unavailable (R-10)")
            out["lanes"].append(entry)
            continue
        out["lanes"].append(entry)
        records.extend(got)
        if rt in ("resolve", "enrich") and got:
            break  # primary answered; fallbacks are for failure only
    records = _drop_unlicensed(records, router, payload, out["facts"])
    if rt == "find":
        records = dedup.cluster(records)
    out["records"] = records
    if cache is not None:
        for r in records:
            if rt in ("resolve", "find") and r.get("identity"):
                src = router.sources.get(r.get("source_id"), {})
                cache.put_record(r, redistributable=licenses.redistributable(src, r), persist_sources=router.persistable_sources(r))
        if rt == "find":
            cache.put_search(cache.search_key(rt, _search_payload(payload)), out)
    return out


def redact_for_storage(result: dict) -> dict:
    """What a persisted job result may hold: never file bytes or full text (I-7).
    Those are delivered only on the inline path and discarded afterwards."""
    out = dict(result)
    if "content" in out:
        out["content_bytes"] = len(out["content"] or b"")
        out["content"] = None
    records = []
    for r in out.get("records") or []:
        if r.get("kind") == "full_text" and r.get("text") is not None:
            r = {**r, "text": None, "text_chars": len(r["text"])}
        records.append(r)
    out["records"] = records
    return out


def make_handlers(router: Router, cache: Cache | None = None) -> dict[str, Callable]:
    """Queue handlers: (client, job) → result, one per request type. The stored result is redacted."""
    def handler(client: Client, job: dict) -> dict:
        payload = dict(job["payload"])
        payload.setdefault("request_type", job["request_type"])
        payload.setdefault("commercial", bool(job.get("commercial")))
        return redact_for_storage(execute(router, payload, client, cache))
    return {rt: handler for rt in ("find", "resolve", "enrich", "fetch", "data")}
