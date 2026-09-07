"""Router: request → lanes (PLAN.md §4, rules R-1..R-10), and the executor that
runs the lanes through the metered client, dedups, enforces licences, caches.

Everything routable comes from the registry rows plus what each adapter
declares about itself (CAPABILITIES, ENRICHES, SCHEMES, HOSTS, AGENCIES):
adding a source is a seed row and an adapter file, never an edit here (I-2).
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable
from urllib.parse import urlsplit

from ..adapters.base import AdapterError, Client, SourceUnavailable
from . import calllog, dedup, licenses
from . import identity as ident
from .cache import Cache

from ..registry.load import DOMAINS  # one domain vocabulary: the registry's (I-2, D-24)
OTHER = "other"
RECENT_DAYS = 30
FIND_KINDS = ("article", "dataset", "venue", "repository")   # venue/repository come from the local index (§8)
CURSOR_PARAMS = ("cursor", "page", "offset", "offset_mark")  # whichever of these an adapter pages by
NEXT_KEYS = ("next_cursor", "next_page", "next_offset", "next_offset_mark")


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

    def _members(self, record: dict) -> list[dict]:
        """Every provenance member of a (possibly merged) record, with its OWN licence — the lead
        record's licence never speaks for a member's, and a member whose licence is simply absent
        counts as unlicensed, never as inheriting the lead's (fail closed, D-25). A record with a
        `sources` list but no provenance gets one member per named source, only the record's own
        source carrying the record's licence."""
        provenance = record.get("provenance")
        if provenance:
            return [{"source_id": p.get("source_id"), "license": p.get("license"), "raw": p.get("raw")} for p in provenance]
        sources = record.get("sources") or [record.get("source_id")]
        return [{"source_id": s, "license": record.get("license") if s == record.get("source_id") else None,
                 "raw": record.get("raw") if s == record.get("source_id") else None} for s in sources]

    def record_allowed(self, record: dict, payload: dict) -> bool:
        """R-8 for one record: EVERY member must pass (used for cache hits too, so a
        personal-mode cache — or a merge led by an allowed source — never leaks a denied
        member into a commercial answer)."""
        if not payload.get("commercial"):
            return True
        if record.get("third_party_restricted"):
            return False  # e.g. FRED series flagged by the source as carrying third-party terms
        return all(licenses.commercially_usable(self.sources.get(m["source_id"], {}),
                                                {"kind": record.get("kind"), "license": m["license"]}, payload)
                   for m in self._members(record))

    def persistable_members(self, record: dict) -> list[int]:
        """INDEXES of the provenance members whose source and OWN licence let the gateway keep
        their raw payload (§6). Indexes, not source ids: two members from the same source with
        different licences are judged separately (D-25)."""
        return [i for i, m in enumerate(self._members(record))
                if licenses.redistributable(self.sources.get(m["source_id"], {}),
                                            {"kind": record.get("kind"), "license": m["license"]})]

    def redistributable_all(self, record: dict) -> bool:
        """True only when every member may be kept: anything less caches in memory for ≤ 1 hour (§6)."""
        return all(licenses.redistributable(self.sources.get(m["source_id"], {}),
                                            {"kind": record.get("kind"), "license": m["license"]})
                   for m in self._members(record))

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
    cursor = (payload.get("cursors") or {}).get(getattr(mod, "SOURCE_ID", ""))
    if cursor is not None:  # §6 continuation: the caller hands back what the lane reported as `next`
        for name in CURSOR_PARAMS:
            if name in params:
                kwargs[name] = cursor
                break
    return mod.find(client, payload.get("query") or "", **{k: v for k, v in kwargs.items() if k in params and v is not None})


def _lane_next(res: dict):
    for key in NEXT_KEYS:
        if res.get(key) is not None:
            return res[key]
    return None


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
        if "resolve" not in getattr(mod, "CAPABILITIES", ()):
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
        if "content" in res and res["content"] is not None:
            # a download is authorized BEFORE its bytes leave the gateway: the fetched item's own
            # licence (reported by the adapter) must pass R-8, exactly like a record would (D-23)
            pseudo = {"kind": "file", "source_id": lane.source_id, "license": res.get("license")}
            if router.record_allowed(pseudo, payload):
                out["content"], out["content_type"] = res["content"], res.get("content_type")
            else:
                out["facts"].append(f"{lane.source_id}: download withheld — licence "
                                    f"{res.get('license') or 'unknown'} is not usable commercially (R-8)")
    if not isinstance(res, dict):
        raise TypeError(f"adapter returned {type(res).__name__}, not a result dict")
    if res.get("capability_fact"):
        out["facts"].append(f"{lane.source_id}: {res['capability_fact']}")
    nxt = _lane_next(res)
    if nxt is not None:
        out.setdefault("next", {})[lane.source_id] = nxt
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
    client.commercial = bool(payload.get("commercial"))
    out = {"request_type": rt, "records": [], "facts": [], "lanes": [], "domain_resolved": client.domain_resolved}
    agency = None
    if rt == "resolve" and ident.parse(payload.get("identity") or "")[0] == "doi":
        try:
            hit = cache.get_record(payload["identity"]) if cache is not None else None
        except Exception:
            hit = None
        if hit and router.record_allowed(hit, payload):
            _log_cache_hit(client, rt, payload["identity"], None)
            return {**out, "records": [hit], "cache_hit": True}
        if "doi_org" in router.adapters and router._usable("doi_org", "resolve"):
            try:
                agency = (router.adapters["doi_org"].resolve(client, payload["identity"]) or {}).get("agency")
            except calllog.AuditError:
                raise  # a broken call log stops the job here too, before any more dispatch (I-6)
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
        except calllog.AuditError:
            raise  # a broken call log fails the whole job: nothing runs unaudited (I-6, D-23)
        except Exception as e:  # anything else a lane throws is a source fact, never a dead job
            entry["error"] = f"{type(e).__name__}: {e}"[:300]
            out["facts"].append(f"{lane.source_id}: malformed response ({type(e).__name__}) — treated as unavailable (R-10)")
            out["lanes"].append(entry)
            continue
        out["lanes"].append(entry)
        if entry.get("count") is not None and lane.source_id in (out.get("next") or {}):
            entry["next"] = out["next"][lane.source_id]
        records.extend(got)
        if rt in ("resolve", "enrich") and got:
            break  # primary answered; fallbacks are for failure only
        if rt == "fetch" and (got or out.get("content") is not None):
            break  # a fetch that answered never runs again on a fallback lane (D-23)
    records = _drop_unlicensed(records, router, payload, out["facts"])
    if rt == "find":
        records = dedup.cluster(records)
    out["records"] = records
    # redaction covers the WHOLE result — records, facts, lane errors — and runs BEFORE anything
    # is cached, so no stored copy a later request could serve back carries a secret (D-24, D-25)
    out = redact_secrets(out, client.secret_values)
    records = out["records"]
    if cache is not None:
        try:
            for r in records:
                if rt not in ("resolve", "find") or not r.get("identity"):
                    continue
                if any(getattr(router.adapters.get(m["source_id"]), "LOCAL", False) for m in router._members(r)):
                    continue  # index answers came FROM the store; writing them back would erase harvested payloads (D-23)
                cache.put_record(r, redistributable=router.redistributable_all(r), persist_members=router.persistable_members(r))
            if rt == "find":
                cache.put_search(cache.search_key(rt, _search_payload(payload)), out)
        except Exception as e:  # a broken cache degrades to no cache, never a failed request
            out["facts"].append(f"cache unavailable ({type(e).__name__})")
    return out


STORAGE_STRIPPED = ("raw", "text", "rows", "content", "provenance")


MIN_SUBSTRING_SECRET = 8   # below this, only whole-token matches are replaced: substring replacement of
                           # a short value would mangle ordinary words ("id" inside "identity", D-24/D-25)


def redact_secrets(obj, values: set):
    """Replace any occurrence of a secret value the client handed out inside strings of the
    result — some sources echo request parameters back (D-23). Applied before caching, so no
    stored copy carries a secret either (D-24). Dictionary keys and tuples are covered; bytes
    (downloads) are untouched. Long secrets are replaced anywhere; short ones only where they
    stand alone between non-word characters."""
    long_vals = {v for v in values if v and len(v) >= MIN_SUBSTRING_SECRET}
    short_res = [re.compile(r"(?<![A-Za-z0-9_])" + re.escape(v) + r"(?![A-Za-z0-9_])")
                 for v in values if v and 0 < len(v) < MIN_SUBSTRING_SECRET]
    if not long_vals and not short_res:
        return obj

    def redact(x):
        if isinstance(x, str):
            for v in long_vals:
                if v in x:
                    x = x.replace(v, "[redacted]")
            for pat in short_res:
                x = pat.sub("[redacted]", x)
            return x
        if isinstance(x, dict):
            return {redact(k): redact(v) for k, v in x.items()}
        if isinstance(x, list):
            return [redact(v) for v in x]
        if isinstance(x, tuple):
            return tuple(redact(v) for v in x)
        return x

    return redact(obj)


def redact_for_storage(result: dict) -> dict:
    """What a persisted job result may hold: canonical metadata, links and counts only. Raw
    payloads, row data, full text and file bytes never enter `gateway.jobs` — persistence with
    provenance is the cache's job, under the licence rules (§6, I-7, D-23). The inline path
    delivers the full result and discards it."""
    out = dict(result)
    if "content" in out:
        out["content_bytes"] = len(out["content"] or b"")
        out["content"] = None

    def slim(v):
        """Any dict at any depth loses the storage-stripped fields; lists (however nested) recurse (D-25)."""
        if isinstance(v, dict):
            cleaned = {}
            for k, inner in v.items():
                if k in STORAGE_STRIPPED:
                    if k in ("text", "rows") and inner is not None:
                        cleaned[f"{k}_dropped"] = True
                    continue
                cleaned[k] = slim(inner)
            if "source_id" in v or "sources" in v:
                cleaned["sources"] = v.get("sources") or [v.get("source_id")]
            return cleaned
        if isinstance(v, list):
            return [slim(x) for x in v]
        if isinstance(v, tuple):
            return tuple(slim(x) for x in v)
        return v

    out["records"] = [slim(r) for r in out.get("records") or []]
    return out


def make_handlers(router: Router, cache: Cache | None = None) -> dict[str, Callable]:
    """Queue handlers: (client, job) → result, one per request type. The stored result is redacted."""
    def handler(client: Client, job: dict) -> dict:
        payload = dict(job["payload"])
        payload.setdefault("request_type", job["request_type"])
        payload.setdefault("commercial", bool(job.get("commercial")))
        return redact_for_storage(execute(router, payload, client, cache))
    return {rt: handler for rt in ("find", "resolve", "enrich", "fetch", "data")}
