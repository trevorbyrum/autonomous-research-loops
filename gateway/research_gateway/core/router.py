"""Router: request → lanes (PLAN.md §4, rules R-1..R-10), and the executor that
runs the lanes through the metered client, dedups, enforces licences, caches.

Everything routable comes from the registry rows plus what each adapter
declares about itself (CAPABILITIES, ENRICHES, SCHEMES, HOSTS, AGENCIES):
adding a source is a seed row and an adapter file, never an edit here (I-2).
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable
from urllib.parse import urlsplit

from ..adapters.base import AdapterError, Client, ContinuationInvalid, PayloadError, SourceUnavailable
from . import calllog, dedup, licenses
from . import canonical as canonical_mod
from . import identity as ident
from . import request_identity as request_ident
from .cache import Cache
from .payload import plain
from .secrets import SecretsBackendFailing

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
    skipped: list[str] = field(default_factory=list)  # lanes that exist but were not dispatched (coverage: not_searched)


# coverage-state vocabulary (docs/STATION-CONTRACT.md §2): every lane entry carries one,
# so "searched and found nothing" is never conflated with "not searched" or "unavailable".
# searched_empty means exactly: THIS successful query returned no records — never that the
# provider was down, refused, unreadable, or skipped (pass-1 finding 7).
COVERAGE_OK, COVERAGE_EMPTY = "searched_ok", "searched_empty"
COVERAGE_SKIPPED, COVERAGE_DOWN = "not_searched", "provider_unavailable"
COVERAGE_AUTH, COVERAGE_METADATA_ONLY = "auth_failed", "metadata_only"
COVERAGE_EXHAUSTED = "exhausted"          # a continuation: this lane already returned everything it has
EXHAUSTED_CURSOR = "exhausted"            # the `next` sentinel for such a lane; handing it back skips the lane
# why a lane is degraded, machine-readable beside its coverage (the engine store's
# search_observations.error_class vocabulary, gen2/store/schema/03-evidence-and-decisions.sql)
ERR_SECRETS = "secrets_backend_failing"   # the gateway's own secrets read FAILED: never "no key configured" (DEPLOYMENT-CONTRACT §3.3)


def _add_fact(out: dict, fact: dict | None) -> None:
    """One current capability fact per capability in an answer: the latest snapshot by its
    revision (2b-repair-3 R2), whatever order the lanes that raised it are collected in."""
    if fact:
        facts = out.setdefault("capability_facts", [])
        held = next((f for f in facts if f.get("capability") == fact.get("capability")), None)
        if held is None or fact.get("revision", 0) >= held.get("revision", 0):
            out["capability_facts"] = [f for f in facts if f is not held] + [fact]


def _secrets_failing(entry: dict, facts: list[str], sid: str, e: SecretsBackendFailing) -> None:
    entry["error"] = str(e)
    entry["completeness"] = "unobserved"
    entry["coverage"] = COVERAGE_DOWN   # required research that could not run — never searched_empty, never auth_failed
    entry["error_class"] = ERR_SECRETS
    facts.append(f"{sid}: secrets backend failing ({e.read.reason}) — the lane could not run; this is not a missing key")


def _fact_coverage(fact: str) -> str:
    """A lane that answered 0 records WITH a capability fact was not a successful empty
    search: unconfigured credentials are an auth problem, everything else is the provider
    being unusable (pass-1 finding 7 — keyless BEA/Census must never look searched_empty)."""
    f = fact.lower()
    if "key" in f or "credential" in f or "auth" in f or "token" in f:
        return COVERAGE_AUTH
    return COVERAGE_DOWN


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
        plan.skipped.append(sid)
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
                if licenses.storable(self.sources.get(m["source_id"], {}),
                                     {"kind": record.get("kind"), "license": m["license"]})]

    def storable_all(self, record: dict) -> bool:
        """True only when every member may be kept: anything less caches in memory for ≤ 1 hour (§6)."""
        return all(licenses.storable(self.sources.get(m["source_id"], {}),
                                     {"kind": record.get("kind"), "license": m["license"]})
                   for m in self._members(record))

    def annotate(self, record: dict) -> dict:
        """Licence, freshness and provenance on a returned record (task 2b; design review §9):
        each provenance member gets its source's metadata licence and freshness lag beside its
        own content licence and retrieval time, and the four permission facts
        (licenses.permissions); the record gets its own source's and the most restrictive
        combination of its members'. Recomputed from the registry on every answer (cache hits
        included), so a stored copy never freezes a stale verdict."""
        has_content = bool(record.get("text") or record.get("rows"))
        per = []
        for m in (record.get("provenance") or []) if isinstance(record.get("provenance"), list) else []:
            if isinstance(m, dict):
                self._stamp(m, m.get("source_id"))
                m["permissions"] = licenses.permissions(self.sources.get(m.get("source_id"), {}), m, kind=record.get("kind"),
                                                        has_content=has_content)
                per.append(m["permissions"])
        if not per:
            per = [licenses.permissions(self.sources.get(m["source_id"], {}),
                                        {**m, "redistributable": record.get("redistributable"),
                                         "third_party_restricted": record.get("third_party_restricted")},
                                        kind=record.get("kind"), has_content=has_content) for m in self._members(record)]
        self._stamp(record, record.get("source_id") or ((record.get("sources") or [None])[0]))
        record["permissions"] = licenses.combined(per)
        return record

    def _stamp(self, target: dict, sid) -> None:
        row = self.sources.get(sid) or {}
        for key, field_name in (("metadata_license", "license"), ("freshness_lag", "freshness_lag")):
            if isinstance(row.get(field_name), str) and row[field_name]:
                target[key] = row[field_name]

    # ------------------------------------------------------------ planning
    def plan(self, payload: dict, *, agency: str | None = None) -> Plan:
        rt = payload.get("request_type")
        plan = Plan(request_type=rt, domain_resolved=resolve_domain(payload.get("domain")))
        method = getattr(self, f"_plan_{rt}", None)
        if method is None:
            plan.facts.append(f"unknown request type {rt!r}")
            return plan
        method(payload, plan, agency)
        if rt == "find" and payload.get("lanes"):
            # a find restricted to named lanes (task 2b): a continuation or a retry asks only the
            # lanes it continues, so a lane that failed or finished is never restarted at page 1.
            # A named lane that is not a find lane of this request is a fact, never silently absent.
            wanted = set(payload["lanes"])
            planned = {ln.source_id for ln in plan.lanes} | set(plan.skipped)
            plan.lanes = [ln for ln in plan.lanes if ln.source_id in wanted]
            plan.skipped = [sid for sid in plan.skipped if sid in wanted]
            plan.facts += [f"{sid}: not a find lane for this request (lanes filter)" for sid in sorted(wanted - planned)]
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

    def _plan_catalog(self, payload: dict, plan: Plan, _agency) -> None:
        sid = payload.get("source")
        if not sid or not self._usable(sid, "catalog"):
            plan.facts.append(f"catalog needs 'source' naming an enabled source with catalog support (got {sid!r})")
            return
        # no commercial gate: a catalogue answers WHICH identifiers exist — metadata about
        # the source, not records from it; the data call itself stays fully gated (D-32)
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
    # a cache hit is REAL retrieval activity: it carries the same tracing as a dispatch,
    # or warm-cache iterations vanish from the throughput report exactly when cache state
    # matters for attribution (9·0 amendment)
    rec = calllog.CallRecord(source_id="cache", request_type=request_type, status=200, latency_ms=0, job_id=client.job_id,
                             identity=identity, query=query, cache_hit=True, result_count=1, domain_resolved=client.domain_resolved,
                             client_id=client.client_id, iteration=client.iteration, batch_entry=client.batch_entry,
                             topic=client.topic, params_fp=client.request_fingerprint, **client.correlation())
    client.log.append(rec)
    if client.conn is not None:
        with client.db_lock:
            try:
                calllog.record(client.conn, rec)
            except calllog.AuditError:
                client.abort.set()
                raise


_FP_KEYS = ("params", "cursors", "cursor", "what", "kind", "domain", "limit", "year_from",
            "published_after", "commercial", "accept_per_item", "within", "target", "source")


def _payload_fingerprint(payload: dict) -> str | None:
    """Tracing-only fingerprint of the request's semantic parameters, so the throughput
    report can tell pagination and parameter changes apart from true repeats. NEVER part
    of cache keys or the dedup hash (D-33)."""
    sub = {k: payload[k] for k in _FP_KEYS if payload.get(k) is not None}
    if not sub:
        return None
    return hashlib.sha256(json.dumps(sub, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


def _valid_records(items, facts: list[str], source_id: str) -> tuple[list[dict], int]:
    """Only well-formed canonical records count as an answer; the rest is a fact (R-10).
    Returns (the good records, how many were dropped): an answer that lost records is a
    PARTIAL observation — what was kept is a lower bound, never the total (RG-4)."""
    if items is not None and not isinstance(items, list):
        raise PayloadError(f"{source_id}: adapter answered {type(items).__name__} records, not a list")
    # a record must name something: an identity built from a missing value (url:None) is a
    # fabricated candidate, dropped like any unreadable member (task 2b-repair A4)
    good = [r for r in (items or []) if isinstance(r, dict) and ident.meaningful(r.get("identity")) and r.get("kind")]
    dropped = len(items or []) - len(good)
    if dropped and not good:
        facts.append(f"{source_id}: unreadable answer ({dropped} member(s), none readable) — treated as unavailable, never as no results")
    elif dropped:
        facts.append(f"{source_id}: {dropped} malformed record(s) dropped — the count is a lower bound")
    return good, dropped


def _run_lane(router: Router, rt: str, lane: Lane, payload: dict, client: Client, out: dict) -> tuple[list[dict], str | None, int]:
    mod = router.adapters[lane.source_id]
    if rt == "find":
        res = _call_find(mod, client, payload)
    elif rt == "resolve":
        if "resolve" not in getattr(mod, "CAPABILITIES", ()):
            items = mod.enrich(client, payload["identity"], "oa_location").get("items") or []
            res = {"records": [dict(items[0], kind="article")] if items else []}
        else:
            rec = mod.resolve(client, payload["identity"])
            if isinstance(rec, dict) and rec.get("capability_fact") and not rec.get("identity"):
                res = {"records": [], "capability_fact": rec["capability_fact"]}   # e.g. no key: not "not found"
            else:
                res = {"records": [rec] if rec else []}
    elif rt == "enrich":
        res = mod.enrich(client, payload["identity"], payload["what"])
        res = {"records": res.get("items"), **{k: v for k, v in res.items() if k != "items"}}
    elif rt == "data":
        res = mod.data(client, payload.get("params") or {})
    elif rt == "catalog":
        res = mod.catalog(client, query=payload.get("query"), within=payload.get("within"),
                          cursor=payload.get("cursor"), limit=payload.get("limit") or 20)
        out["entries"] = res.get("entries") or []
        if res.get("next") is not None:
            out["catalog_next"] = res["next"]
        if res.get("notes"):
            out["notes"] = res["notes"]
        res = {"records": [], **{k: v for k, v in res.items() if k == "capability_fact"}}
    else:  # fetch
        fparams = {k: v for k, v in (payload.get("params") or {}).items() if k in inspect.signature(mod.fetch).parameters}
        res = mod.fetch(client, payload["target"], **fparams)
        if "content" in res and res["content"] is not None:
            # a download is authorized BEFORE its bytes leave the gateway: the fetched item's own
            # licence (reported by the adapter) must pass R-8, exactly like a record would (D-23)
            pseudo = {"kind": "file", "source_id": lane.source_id, "license": res.get("license")}
            if router.record_allowed(pseudo, payload):
                out["content"], out["content_type"] = res["content"], res.get("content_type")
                out["content_license"], out["content_source"] = res.get("license"), lane.source_id
            else:
                out["facts"].append(f"{lane.source_id}: download withheld — licence "
                                    f"{res.get('license') or 'unknown'} is not usable commercially (R-8)")
    if not isinstance(res, dict):
        raise TypeError(f"adapter returned {type(res).__name__}, not a result dict")
    fact = res.get("capability_fact")
    if fact:
        out["facts"].append(f"{lane.source_id}: {fact}")
    nxt = _lane_next(res)
    if nxt is not None:
        out.setdefault("next", {})[lane.source_id] = nxt
    if rt == "find" and res.get("exhausted") is True:   # the adapter's own report that nothing remains (2b-repair-6 F3)
        out.setdefault("ended", []).append(lane.source_id)
    got, dropped = _valid_records(res.get("records"), out["facts"], lane.source_id)
    withheld = res.get("withheld") or 0
    if withheld:   # stored matches the serving read refused (2b-repair-5 F2): dropped, never a shorter complete answer
        out["facts"].append(f"{lane.source_id}: {withheld} matching stored record(s) withheld — an earlier writer's rows, never "
                            "served until converted (python -m research_gateway.registry.migrate); the count is a lower bound")
    return got, (str(fact) if fact else None), dropped + withheld


# 9·2b aggregate bound: each request's pool bounds ONE request's fan-out; this semaphore
# bounds the PROCESS — queued workers and the inline path (which bypasses the worker pool
# entirely) together never hold more than RESEARCH_GATEWAY_LANE_TOTAL lane dispatches.
_LANE_SLOTS: threading.BoundedSemaphore | None = None
_LANE_SLOTS_LOCK = threading.Lock()


def _lane_slots() -> threading.BoundedSemaphore:
    global _LANE_SLOTS
    with _LANE_SLOTS_LOCK:
        if _LANE_SLOTS is None:
            _LANE_SLOTS = threading.BoundedSemaphore(
                max(1, int(os.environ.get("RESEARCH_GATEWAY_LANE_TOTAL", "16") or 16)))
        return _LANE_SLOTS


# The lane-outcome mapping (STATION-CONTRACT.md §2; the engine store's search_observations
# vocabulary, gen2/store/schema/03-evidence-and-decisions.sql). Every lane entry carries
# `coverage`, `completeness` (complete | partial | unobserved) and, when degraded or partial,
# `error_class`; `count` exists only for an observed result set, and for a partial one it is
# a lower bound. An unreadable answer is provider_unavailable/payload_invalid — never
# searched_empty, never a zero (H-5, RG-4, RG-U; task 2b).
ERR_PAYLOAD, ERR_OUTAGE, ERR_TIMEOUT, ERR_TRANSPORT = "payload_invalid", "provider_outage", "timeout", "transport_failure"
ERR_RATE, ERR_BREAKER, ERR_BUDGET = "rate_limited", "breaker_open", "budget_refused"
ERR_REJECTED, ERR_UNCONFIGURED = "credentials_rejected", "credentials_not_configured"
ERR_PAGINATION = "partial_pagination"   # more may remain that cannot be asked for: a page read whole with neither a
                                        # continuation nor an end, or a continuation that can no longer be read


def _unavailable(resp) -> tuple[str, str]:
    """(coverage, error_class) for a SourceUnavailable answer."""
    error = resp.error or ""
    if resp.status in (401, 403):
        return COVERAGE_AUTH, ERR_REJECTED
    if resp.status == 429:
        return COVERAGE_DOWN, ERR_RATE
    if error.startswith("BreakerOpen"):
        return COVERAGE_DOWN, ERR_BREAKER
    if error.startswith(("BudgetExhausted", "NoPolicy")):
        return COVERAGE_DOWN, ERR_BUDGET
    if resp.status is not None and 200 <= resp.status < 300:
        return COVERAGE_DOWN, ERR_PAYLOAD          # an unreadable answer wearing a success status (HTML)
    if resp.status is None:
        return COVERAGE_DOWN, ERR_TIMEOUT if "timed out" in error.lower() or "timeout" in error.lower() else ERR_TRANSPORT
    return COVERAGE_DOWN, ERR_OUTAGE


def _lane_failed(entry: dict, facts: list[str], sid: str, e: Exception) -> dict | None:
    """Fill a lane entry for a lane that raised; returns the capability fact it carries, if any.
    calllog.AuditError is never passed here: a broken call log fails the request (I-6)."""
    entry["completeness"] = "unobserved"
    if isinstance(e, SecretsBackendFailing):
        _secrets_failing(entry, facts, sid, e)
        return e.fact
    if isinstance(e, SourceUnavailable):
        entry["error"] = str(e)
        # a broker refusal (budget spent, breaker open, no policy) means required research
        # COULD NOT run — that must block completion like any outage, so it is
        # provider_unavailable, never the non-blocking policy-skip state (finding 4)
        entry["coverage"], entry["error_class"] = _unavailable(e.response)
        facts.append(f"{sid}: unavailable ({e.response.error or e.response.status}) — R-10")
    elif isinstance(e, AdapterError):
        entry["error"] = str(e)
        entry["coverage"] = COVERAGE_SKIPPED  # refused before dispatch (keyless tier, policy)
        facts.append(f"{sid}: refused ({e})")
    elif isinstance(e, ContinuationInvalid):   # the page could not be read where the search left off: not an outage
        entry["error"] = str(e)
        entry["coverage"], entry["error_class"] = COVERAGE_DOWN, ERR_PAGINATION
        facts.append(f"{sid}: {e}")
    else:  # an unreadable answer, or anything else a lane throws: a source fact, never a dead job
        entry["error"] = f"{type(e).__name__}: {e}"[:300]
        entry["coverage"], entry["error_class"] = COVERAGE_DOWN, ERR_PAYLOAD
        facts.append(f"{sid}: unreadable answer ({type(e).__name__}) — treated as unavailable, never as no results (R-10, H-5)")
    return None


def _lane_observed(entry: dict, got: list[dict], fact: str | None, dropped: int, rt: str, payload: dict, out: dict) -> None:
    """Fill a lane entry for a lane that answered."""
    count = len(out.get("entries") or []) if rt == "catalog" else len(got)
    if dropped and not count:
        # every record it answered was unreadable: nothing was observed, and nothing is zero
        entry.update(coverage=COVERAGE_DOWN, completeness="unobserved", error_class=ERR_PAYLOAD)
        return
    if count:
        entry["coverage"] = COVERAGE_OK
    elif fact:  # answered nothing AND explained why: that is not a successful empty search
        entry["coverage"] = _fact_coverage(fact)
        entry["completeness"] = "unobserved"
        entry["error_class"] = ERR_UNCONFIGURED if entry["coverage"] == COVERAGE_AUTH else ERR_OUTAGE
        return
    elif rt == "enrich" and payload.get("what") in ("full_text", "oa_location"):
        # the caller already HOLDS the record's identity: an empty answer here means
        # the requested full text is not retrievable, never that nothing exists (finding 7)
        entry["coverage"] = COVERAGE_METADATA_ONLY
    else:
        entry["coverage"] = COVERAGE_EMPTY
    if rt == "fetch" and (payload.get("params") or {}).get("download") and out.get("content") is None and got:
        entry["coverage"] = COVERAGE_METADATA_ONLY  # found, but the requested file is not retrievable
    entry["count"] = count
    # the identities this lane returned, in its own rank order and before any merge (E-2:
    # retrieval-time identities, so the engine records one retrieval event per candidate
    # and its count is never a bare number); a catalogue's are its entries' ids
    entry["retrieved"] = ([str(e.get("id")) for e in out.get("entries") or []] if rt == "catalog"
                          else [str(r["identity"]) for r in got])
    entry["completeness"] = "partial" if dropped else "complete"
    if dropped:
        entry["error_class"] = ERR_PAYLOAD


def _find_lane_result(router: Router, lane: Lane, payload: dict, client: Client,
                      abort: threading.Event | None = None) -> dict:
    """One find lane, LANE-LOCALLY (9·2b): facts, records, coverage, continuation — nothing
    shared is touched, so lanes may run concurrently and merge deterministically in plan
    order afterward. AuditError propagates AND trips `abort`, so a lane that has not yet
    dispatched when the call log breaks never dispatches (I-6). The process-wide slot
    semaphore bounds total in-flight lane dispatches across queued AND inline requests.
    The entry names the cursor it was asked with, so a failed continuation page can be
    retried from where it failed (task 2b: failed pagination is never lost)."""
    if abort is not None and abort.is_set():
        raise calllog.AuditError("not dispatched: a parallel lane's call log write failed first (I-6)")
    entry: dict = {"source": lane.source_id, "role": lane.role,
                   "cursor": (payload.get("cursors") or {}).get(lane.source_id)}
    lane_out: dict = {"facts": []}
    with _lane_slots():
        if abort is not None and abort.is_set():
            raise calllog.AuditError("not dispatched: a parallel lane's call log write failed first (I-6)")
        try:
            got, fact, dropped = _run_lane(router, "find", lane, payload, client, lane_out)
            _lane_observed(entry, got, fact, dropped, "find", payload, lane_out)
        except calllog.AuditError:
            if abort is not None:
                abort.set()   # set by the FAILING lane, not the merge loop: no window where
            raise             # a queued lane dispatches between the failure and its discovery
        except Exception as e:
            fact = _lane_failed(entry, lane_out["facts"], lane.source_id, e)
            return {"entry": entry, "records": [], "facts": lane_out["facts"], "next": None, "capability_fact": fact}
    nxt = (lane_out.get("next") or {}).get(lane.source_id)
    ended = lane.source_id in lane_out.get("ended", ())
    if nxt is not None and entry["completeness"] != "unobserved":
        entry["next"] = nxt
    elif ended and entry["coverage"] in (COVERAGE_OK, COVERAGE_EMPTY) and entry["completeness"] == "complete":
        # exhausted only on the ADAPTER'S report that nothing remains — a missing cursor proves
        # nothing (2b-repair-6 F3: a bounded answer was declared complete and its rest skipped)
        entry["exhausted"] = True
        nxt = EXHAUSTED_CURSOR
    else:
        nxt = None   # a lane that answered nothing readable has no continuation, and is not exhausted
        if entry["coverage"] == COVERAGE_OK and entry["completeness"] == "complete":
            # records, but neither a continuation nor a reported end: more may remain that no
            # one can ask for, so what was read is a lower bound (RG-4) — never complete, never cached
            entry.update(completeness="partial", error_class=ERR_PAGINATION)
            lane_out["facts"].append(f"{lane.source_id}: {entry['count']} record(s) and no continuation, but the source did not "
                                     "report the end of its results — more may remain; the count is a lower bound")
    return {"entry": entry, "records": got, "facts": lane_out["facts"], "next": nxt}


def _run_find_lanes(router: Router, payload: dict, client: Client, plan: Plan, out: dict, rt: str = "find") -> list[dict]:
    """All find lanes, overlapped up to RESEARCH_GATEWAY_LANE_CONCURRENCY (default 4) and
    merged IN PLAN ORDER — the answer is byte-identical to serial execution for the same
    responses. AuditError cancels unstarted lanes, JOINS running ones (a future's timeout
    does not stop its thread; the pool context waits), then fails the whole request —
    never a degraded lane plus a cached partial success (plan v3)."""
    slots: list = []
    runnable: list[tuple[int, Lane]] = []
    for idx, lane in enumerate(plan.lanes):
        if (payload.get("cursors") or {}).get(lane.source_id) == EXHAUSTED_CURSOR:
            # nothing is dispatched and nothing observed: no count (RG-U), only the fact that
            # this lane already returned everything it has
            entry = {"source": lane.source_id, "role": lane.role, "coverage": COVERAGE_EXHAUSTED,
                     "completeness": "unobserved", "cursor": EXHAUSTED_CURSOR, "exhausted": True}
            slots.append({"entry": entry, "records": [], "facts": [], "next": EXHAUSTED_CURSOR})
        else:
            slots.append(None)
            runnable.append((idx, lane))
    width = max(1, int(os.environ.get("RESEARCH_GATEWAY_LANE_CONCURRENCY", "4") or 4))
    abort = client.abort   # the AUDIT layer publishes failure under db_lock (base.py):
    if len(runnable) > 1 and width > 1:   # router checks are a fast path, not the guarantee
        with ThreadPoolExecutor(max_workers=min(width, len(runnable))) as pool:
            futures = [(idx, pool.submit(_find_lane_result, router, lane, payload, client, abort))
                       for idx, lane in runnable]
            try:
                for idx, future in futures:
                    slots[idx] = future.result()
            except calllog.AuditError:
                for _, f in futures:
                    f.cancel()          # unstarted lanes never start
                raise                   # the pool context joins running lanes before this propagates
    else:
        for idx, lane in runnable:
            slots[idx] = _find_lane_result(router, lane, payload, client, abort)
    records: list[dict] = []
    for slot, lane in zip(slots, plan.lanes):
        out["facts"].extend(slot["facts"])
        out["lanes"].append(slot["entry"])
        _add_fact(out, slot.get("capability_fact"))
        if slot["next"] is not None:
            out.setdefault("next", {})[lane.source_id] = slot["next"]
        records.extend(slot["records"])
    return records


def _run_serial_lanes(router: Router, payload: dict, client: Client, plan: Plan, out: dict, rt: str) -> list[dict]:
    """resolve/enrich/fetch/data/catalog lanes stay serial (9·2b): these plans are fallback
    chains — a later lane runs only because the earlier one did not answer — so overlapping
    them would spend provider budget on answers the merge then throws away."""
    records: list[dict] = []
    for lane in plan.lanes:
        entry = {"source": lane.source_id, "role": lane.role}
        try:
            with _lane_slots():   # the aggregate bound covers EVERY lane dispatch path —
                got, fact, dropped = _run_lane(router, rt, lane, payload, client, out)   # serial and inline included (9·2b)
            _lane_observed(entry, got, fact, dropped, rt, payload, out)
        except calllog.AuditError:
            raise  # a broken call log fails the whole job: nothing runs unaudited (I-6, D-23)
        except Exception as e:
            _add_fact(out, _lane_failed(entry, out["facts"], lane.source_id, e))
            out["lanes"].append(entry)
            continue
        if rt == "fetch" and got:
            # every listed file carries its COMPLETE research_download call, built by the
            # ADAPTER that owns the fetch contract — parent target, native selector, listing
            # revision (D-31a: generic client-side guessing produced calls five adapters
            # rejected). A builder error never breaks the listing itself.
            builder = getattr(router.adapters.get(lane.source_id), "download_request", None)
            if builder is not None:
                for rec in got:
                    try:
                        request = builder(rec, str(payload.get("target") or ""))
                    except Exception:
                        request = None
                    if request:
                        rec["download_request"] = {"tool": "research_download", "arguments": request}
        out["lanes"].append(entry)
        if entry.get("count") is not None and lane.source_id in (out.get("next") or {}):
            entry["next"] = out["next"][lane.source_id]
        records.extend(got)
        if rt in ("resolve", "enrich") and got:
            break  # primary answered; fallbacks are for failure only
        if rt == "fetch" and (got or out.get("content") is not None):
            break  # a fetch that answered never runs again on a fallback lane (D-23)
    return records


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
    client.request_fingerprint = _payload_fingerprint(payload)
    effective = request_ident.effective_request(payload)
    client.request_identity = request_ident.identity_of(effective)
    # the complete effective request and its identity (H-5): content identity, the same for every
    # caller of this request — never a caller's invocation, which the front door adds per caller
    out = {"request_type": rt, "records": [], "facts": [], "lanes": [], "domain_resolved": client.domain_resolved,
           "effective_request": effective, "request_identity": client.request_identity}
    agency = None
    if rt == "resolve" and ident.parse(payload.get("identity") or "")[0] == "doi":
        try:
            hit = cache.get_record(payload["identity"]) if cache is not None else None
        except Exception:
            hit = None
        if hit and router.record_allowed(hit, payload):
            _log_cache_hit(client, rt, payload["identity"], None)
            return {**out, "records": [router.annotate(copy.deepcopy(hit))], "cache_hit": True, "served_from": "record_cache"}
        if "doi_org" in router.adapters and router._usable("doi_org", "resolve"):
            try:
                with _lane_slots():   # metered like any lane: the aggregate bound has no side door
                    agency = (router.adapters["doi_org"].resolve(client, payload["identity"]) or {}).get("agency")
            except calllog.AuditError:
                raise  # a broken call log stops the job here too, before any more dispatch (I-6)
            except Exception as e:  # the lookup is metered like any call; its failure is a fact, not a crash
                out["facts"].append(f"doi_org: registration-agency lookup failed ({type(e).__name__}) — routing as unknown")
    if rt == "find" and cache is not None:
        hit = cache.get_search(cache.search_key(rt, _search_payload(payload)))
        if hit:
            _log_cache_hit(client, rt, None, payload.get("query"))
            hit = copy.deepcopy(hit)   # the cached answer is shared: annotate a copy, never it
            hit["records"] = [router.annotate(r) for r in hit.get("records") or []]
            return {**hit, "cache_hit": True, "served_from": "search_cache"}
    plan = router.plan(payload, agency=agency)
    out["facts"].extend(plan.facts)
    if rt == "data":  # a cited table must be reproducible: echo what was asked of which source (8a)
        out["request"] = {"source": payload.get("source"), "params": payload.get("params") or {}}
    records = (_run_find_lanes if rt == "find" else _run_serial_lanes)(router, payload, client, plan, out, rt=rt)
    for sid in plan.skipped:  # lanes that exist for this request but were never dispatched
        out["lanes"].append({"source": sid, "role": "skipped", "coverage": COVERAGE_SKIPPED, "completeness": "unobserved"})
    records = _drop_unlicensed(records, router, payload, out["facts"])
    if rt == "find":
        records = dedup.cluster(records)   # one record per IDENTITY: nothing else merges (INVARIANTS E-3). The raw retrieval inventory is the lanes' `retrieved`, untouched
        linked = dedup.suggestions(records)   # candidates that look alike are suggested for a governed linkage assessment, with provenance; never merged
        if linked:
            out["linkage_suggestions"] = linked
    out["records"] = [router.annotate(r) for r in records]
    if out.get("content") is not None:
        # a delivered download's own four facts: its content licence decides redistribution
        out["content_permissions"] = licenses.permissions(
            router.sources.get(out.pop("content_source", None), {}), {"license": out.get("content_license")},
            kind="file", has_content=True)
    # THE SERIALIZATION BOUNDARY (2b-repair-13c, core/payload.py): every lane has run and every selection, coverage and licence decision is made. Only now do a record's `raw`, its
    # passive `extra` values and a download's bytes become plain data — a copy, so nothing returned or cached aliases what a decoder kept. Before this point adapter code can read none
    # of them, so none of it could have decided anything.
    out = plain(out)
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
                cache.put_record(r, storable=router.storable_all(r), persist_members=router.persistable_members(r))
            if rt == "find" and all(lane.get("completeness") == "complete" or lane.get("coverage") in (COVERAGE_SKIPPED, COVERAGE_EXHAUSTED)
                                    for lane in out["lanes"]):
                # only an answer every lane completed is served again from memory: a degraded
                # or partial one is re-asked, never replayed as if it were the whole answer
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


# what a STORED provenance member may say (8a): where a citation came from, under which
# CONTENT licence, retrieved when, linked where — canonical.member_summary's scalar-string
# whitelist, so a member can never smuggle a nested raw payload through a field that shares
# a whitelisted name (pass-1 finding 8). `metadata_license` is added from the registry (the
# per-source verdict in docs/LICENSING.md) when the sources map is available.


def _member_summary(m: dict, sources: dict | None = None) -> dict:
    out = canonical_mod.member_summary(m)
    if sources and isinstance(m.get("source_id"), str):
        meta = (sources.get(m["source_id"]) or {}).get("license")
        if isinstance(meta, str) and meta:
            out["metadata_license"] = meta
    return out


def redact_for_storage(result: dict, sources: dict | None = None) -> dict:
    """What a persisted job result may hold: canonical metadata, links, counts, and a whitelisted
    provenance summary per member (source, identity, licence, retrieved_at — a citation's
    ingredients, 8a). Raw payloads, row data, full text and file bytes never enter
    `gateway.jobs` — persistence WITH raw payloads is the cache's job, under the licence rules
    (§6, I-7, D-23). The inline path delivers the full result and discards it."""
    out = dict(result)
    if "content" in out:
        out["content_bytes"] = len(out["content"] or b"")
        out["content"] = None

    def slim(v):
        """Any dict at any depth loses the storage-stripped fields; lists (however nested) recurse (D-25)."""
        if isinstance(v, dict):
            cleaned = {}
            for k, inner in v.items():
                if k == "provenance" and isinstance(inner, list):
                    cleaned[k] = [_member_summary(m, sources) for m in inner if isinstance(m, dict)]
                    continue
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
        return redact_for_storage(execute(router, payload, client, cache), router.sources)
    return {rt: handler for rt in ("find", "resolve", "enrich", "fetch", "data")}
