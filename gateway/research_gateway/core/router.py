"""Router: request → lanes (PLAN.md §4, rules R-1..R-10), and the executor that
runs the lanes through the metered client, dedups, enforces licences, caches.

Everything routable comes from the registry rows plus what each adapter
declares about itself (CAPABILITIES, ENRICHES, SCHEMES, HOSTS): adding a
source is a seed row and an adapter file, never an edit here (I-2).
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
        kinds = [payload["kind"]] if payload.get("kind") in ("article", "dataset") else ["article", "dataset"]
        recent = is_recent(payload)
        for kind in kinds:
            base = [sid for sid in self._ordered("find") if kind in (self.sources[sid].get("base_for") or [])]
            for sid in base:
                if recent and self.adapters[sid].__name__.endswith("openalex_snapshot"):
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
            primary = {"Crossref": "crossref", "DataCite": "datacite"}.get(agency or "", "openaire")
            group = self.sources.get(primary, {}).get("substitution_group") or "doi-metadata"
            fallbacks = [sid for sid in self._ordered("resolve")
                         if sid != primary and self.sources[sid].get("substitution_group") == group]
            if self._usable(primary, "resolve") and self._commercial_gate(primary, payload, plan):
                plan.lanes.append(Lane(primary, "primary", f"registration agency {agency or 'unknown'}"))
            for sid in fallbacks:
                if self._commercial_gate(sid, payload, plan):
                    plan.lanes.append(Lane(sid, "fallback"))
            if self._usable("unpaywall", "enrich") and self._commercial_gate("unpaywall", payload, plan):
                plan.lanes.append(Lane("unpaywall", "fallback", "oa_location as metadata of last resort"))
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
                             identity=identity, query=query, cache_hit=True, result_count=1, domain_resolved=client.domain_resolved)
    client.log.append(rec)
    if client.conn is not None:
        calllog.record(client.conn, rec)


def _drop_unlicensed(records: list[dict], router: Router, payload: dict, facts: list[str]) -> list[dict]:
    """R-8 second half: under commercial=true, per-item records need an allow-listed licence."""
    if not payload.get("commercial"):
        return records
    kept, dropped = [], 0
    for r in records:
        src = router.sources.get(r.get("source_id"), {})
        if src.get("use_commercial") == "per-item" and not licenses.allow_listed(r.get("license")):
            dropped += 1
            continue
        kept.append(r)
    if dropped:
        facts.append(f"{dropped} per-item record(s) dropped: no allow-listed licence (R-8)")
    return kept


def execute(router: Router, payload: dict, client: Client, cache: Cache | None = None,
            agencies: ident.RegistrationAgencies | None = None) -> dict:
    """Run a request end to end. Never raises for source trouble: those become facts (R-10)."""
    rt = payload.get("request_type")
    client.domain_resolved = resolve_domain(payload.get("domain"))
    agency = None
    if rt == "resolve" and ident.parse(payload.get("identity") or "")[0] == "doi":
        if cache is not None:
            hit = cache.get_record(payload["identity"])
            if hit:
                _log_cache_hit(client, rt, payload["identity"], None)
                return {"request_type": rt, "records": [hit], "facts": [], "lanes": [], "cache_hit": True}
        try:
            agency = (agencies or ident.RegistrationAgencies(client)).agency(ident.parse(payload["identity"])[1])
        except (SourceUnavailable, AdapterError):
            agency = None
    plan = router.plan(payload, agency=agency)
    out = {"request_type": rt, "records": [], "facts": list(plan.facts), "lanes": [], "domain_resolved": plan.domain_resolved}
    if rt == "find" and cache is not None:
        key = cache.search_key(rt, {k: v for k, v in payload.items() if k != "request_type"})
        hit = cache.get_search(key)
        if hit:
            _log_cache_hit(client, rt, None, payload.get("query"))
            return {**hit, "cache_hit": True}
    records: list[dict] = []
    for lane in plan.lanes:
        mod, entry = router.adapters[lane.source_id], {"source": lane.source_id, "role": lane.role}
        try:
            if rt == "find":
                res = _call_find(mod, client, payload)
                got = res.get("records") or []
                entry.update(count=len(got), total=res.get("total"))
                if res.get("capability_fact"):
                    out["facts"].append(f"{lane.source_id}: {res['capability_fact']}")
            elif rt == "resolve":
                if lane.source_id == "unpaywall":
                    items = mod.enrich(client, payload["identity"], "oa_location").get("items") or []
                    got = [dict(items[0], kind="article")] if items else []
                else:
                    rec = mod.resolve(client, payload["identity"])
                    got = [rec] if rec else []
                entry.update(count=len(got))
            elif rt == "enrich":
                res = mod.enrich(client, payload["identity"], payload["what"])
                got = res.get("items") or []
                entry.update(count=len(got))
            elif rt == "data":
                res = mod.data(client, payload.get("params") or {})
                got = res.get("records") or []
                entry.update(count=len(got))
                if res.get("capability_fact"):
                    out["facts"].append(f"{lane.source_id}: {res['capability_fact']}")
            else:  # fetch
                fparams = {k: v for k, v in (payload.get("params") or {}).items()
                           if k in inspect.signature(mod.fetch).parameters}
                res = mod.fetch(client, payload["target"], **fparams)
                got = res.get("records") or []
                entry.update(count=len(got), has_content="content" in res)
                if res.get("capability_fact"):
                    out["facts"].append(f"{lane.source_id}: {res['capability_fact']}")
                if "content" in res:
                    out["content"], out["content_type"] = res["content"], res.get("content_type")
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
        out["lanes"].append(entry)
        records.extend(r for r in got if isinstance(r, dict))
        if rt in ("resolve", "enrich") and got:
            break  # primary answered; fallbacks are for failure only
    records = _drop_unlicensed(records, router, payload, out["facts"])
    if rt == "find":
        records = dedup.cluster(records)
    out["records"] = records
    if cache is not None:
        for r in records:
            src = router.sources.get(r.get("source_id"), {})
            if rt in ("resolve", "find") and r.get("identity"):
                cache.put_record(r, redistributable=licenses.redistributable(src, r))
        if rt == "find":
            cache.put_search(cache.search_key(rt, {k: v for k, v in payload.items() if k != "request_type"}), out)
    return out


def make_handlers(router: Router, cache: Cache | None = None) -> dict[str, Callable]:
    """Queue handlers: (client, job) → result, one per request type."""
    def handler(client: Client, job: dict) -> dict:
        payload = dict(job["payload"])
        payload.setdefault("request_type", job["request_type"])
        payload.setdefault("commercial", bool(job.get("commercial")))
        return execute(router, payload, client, cache)
    return {rt: handler for rt in ("find", "resolve", "enrich", "fetch", "data")}
