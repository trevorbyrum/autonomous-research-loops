# Research Gateway — Build Plan

Status: **approved scope, not yet built.** This document is the contract the build
is checked against. Every session that touches the gateway starts with the
"Session checklist" at the bottom; every phase ends with its acceptance checks
passing, verbatim. If the code and this plan disagree, the plan wins until the
plan is amended in the Decision log — never silently.

Operator decisions this plan encodes are dated in the Decision log (§16). Facts
about sources (limits, licences) come from the `research_loops` Postgres tables
built 2026-09-05..07 and are cited there; nothing below is from memory.

---

## 0. Purpose, scope, invariants

**Purpose.** One service through which every research agent and every tool
queries external research sources — so that rate limits are honoured by
construction, every call is logged, licences are enforced mechanically, and
nothing is searched twice across overlapping platforms.

**In scope.** Discovery (`find`), lookup (`resolve`), enrichment (`enrich`),
file retrieval (`fetch`), and statistical-series queries (`data`) across the
working set in §3; a Postgres-backed job queue and rate broker; a local text
index over harvested registries; two front doors (a local client for the
research loops; an MCP registration on the homelab gateway); public
documentation of every source's access and licence terms.

**Out of scope (non-goals).** GitHub (stays its own tool). Full-text storage
(links only; see I-7). Automatic re-tuning of routing from logs (logs are for
trouble detection only — D-6). Institutional / Duke-licensed sources (D-3).
The OpenAlex live API (D-2). Any research judgment — the gateway finds and
records; the loops judge.

**Invariants — checked every session, never negotiable without a Decision-log entry.**

- **I-1 Single owner of limits.** Only the gateway process calls a source.
  Clients (loop tool, MCP adapter, CLI) never contact a source directly. If the
  gateway is down, clients return `capability_fact: gateway_unavailable`, they
  do not fall back to direct calls.
- **I-2 Registry-driven.** Which sources exist, what they support, their limits,
  licences and commercial verdicts live in the `gateway.sources` tables, not in
  code. An adapter without a registry row is never scheduled. Adding a source =
  a row + an adapter file + a docs entry, never a routing edit.
- **I-3 Unknown fails closed.** A source whose commercial verdict is `unknown`
  is never used for a topic flagged `commercial`; a source with no rate policy
  row is never scheduled.
- **I-4 Personal is the baseline.** Every adopted source already passed
  personal / non-commercial use; the only routing flag is `commercial`.
- **I-5 Nothing private in the public tree.** No keys, no Vault paths, no
  internal hostnames/IPs, no cached payloads, no harvested data, no
  Duke-specific material, nothing from `private/`. §12 is the checklist.
- **I-6 Every call is logged** with source, request type, identity/query,
  status, latency, rate-limit headers, credits, cache hit, result count,
  failure class. No silent calls.
- **I-7 Links, not papers.** Records carry identifiers, metadata and links. Full
  text is fetched to satisfy a request and discarded, except open-licensed
  (CC0/CC-BY) texts a *completed topic actually cited*, which the completion
  hook may cache alongside its knowledge-graph ingest (D-9).
- **I-8 Raw payload kept.** Normalisation is lossy (corpus SRC-133); every
  canonical record keeps each contributing source's raw payload with provenance.
- **I-9 Docs mirror the registry.** `gateway/docs/SOURCES.md` lists exactly the
  registry's sources with their links, key instructions, licence and commercial
  verdict — generated from the registry, then committed; a drift check fails if
  they diverge.

---

## 1. Repository layout (public, in `research-loops-public`)

```
gateway/
  PLAN.md                     this document
  README.md                   what it is, how to run it, how to add a source
  docs/
    SOURCES.md                every source: link, kind, how to get a key, rate limit,
                              licence, commercial verdict (unknowns stated as unknown)
    ARCHITECTURE.md           request types, routing, queue/broker, cache, index
    OPERATIONS.md             deploy, health, alerts, key rotation, adding a source
    PUBLIC-PRIVATE.md         what is and is not in this tree, and why (§12)
    LICENSING.md              how verdicts are derived; per-item rule; caveats
  research_gateway/           Python package (3.12, stdlib + psycopg + a small HTTP framework)
    registry/
      schema.sql              gateway.* tables (§2)
      seed/sources.yaml       the working set (§3) with kinds, capabilities, rate policy,
                              licence, commercial verdict, evidence URL
      load.py                 seed -> tables; validates that every seeded source has an adapter
    adapters/
      base.py                 Adapter interface: capabilities(), find(), resolve(), enrich(), fetch(), data()
      crossref.py datacite.py doaj.py openaire.py semanticscholar.py core.py
      unpaywall.py opencitations.py europepmc.py
      fred.py bea.py census.py bls.py bis.py ecb.py govinfo.py
      dataverse.py socrata.py kaggle.py huggingface.py openml.py qdr.py
      globe.py wms.py (Harvard Dataverse-backed; no key)
    core/
      identity.py             DOI/ISSN/arXiv/handle normalisation; registration-agency lookup (doi.org/ra)
      queue.py                Postgres job queue (SKIP LOCKED), priorities, dedup of in-flight identical jobs
      broker.py               per-source per-credential token buckets; daily budgets; Retry-After; breakers
      router.py               request -> lanes (§4); domain tags; commercial filter
      cache.py                identity-keyed cache with per-source TTL and redistribution policy
      dedup.py                staged dedup (§6)
      canonical.py            canonical record model + provenance
      calllog.py              I-6
      secrets.py              pluggable backend: env vars (public default) | Vault (private config)
    api/
      http.py                 /v1/find /v1/resolve /v1/enrich /v1/fetch /v1/data /v1/health /v1/jobs/{id}
      auth.py                 bearer token per client
    clients/
      mcp_stdio.py            the loops' local tool: MCP server over stdio -> HTTP client
      cli.py                  research-gateway <find|resolve|enrich|fetch|data|status>
    mcp/
      homelab_adapter.py      registers the same five tools on the homelab MCP gateway
    harvest/
      openalex_snapshot.py    quarterly sources+works-lite loader (no API)
      crossref_journals.py doaj_journals.py datacite_repositories.py
      index.py                Postgres full-text index (Tier 0); optional embedding tier later
  deploy/
    Dockerfile  docker-compose.gateway.yml  research-gateway.service
  tests/
    contract/                 one recorded-fixture test per adapter (no network)
    routing/                  routing table tests (§4) — every rule has a test
    broker/                   token bucket, Retry-After, breaker, budget tests
    regression/
      overlap_probe.py        replays a fixed DOI sample; asserts per-source presence
                              against recorded expectations (the 2026-09 probe)
sources.example.yaml          public example config (env-var secrets), user-editable
```

Private material stays out of the tree: `private/` (gitignored), the
`registry-harvest` branch (discovery tooling, unmerged), Vault.

---

## 2. Data model (`gateway` schema in the `research_loops` database)

```sql
gateway.sources        (id, name, kind, homepage, docs_url, capabilities[],   -- find|resolve|enrich|fetch|data
                        identifiers[], domains[], auth, secret_ref,          -- secret_ref = logical name only
                        use_commercial, use_evidence, license, freshness_lag,
                        substitution_group, enabled)
gateway.rate_policies  (source_id, per_second, per_minute, per_hour, per_day,
                        cost_cap_per_day, burst, evidence)
gateway.jobs           (id, request_type, payload jsonb, priority, status,       -- queued|running|done|failed
                        client_id, topic_id, commercial bool, created_at,
                        started_at, finished_at, result_ref, error_class)
gateway.calls          (id, job_id, source_id, request_type, identity, query,
                        status, latency_ms, ratelimit jsonb, credits, cache_hit,
                        result_count, failure_class, at)                       -- I-6
gateway.breakers       (source_id, state, opened_at, retry_after, reason)
gateway.records        (identity, kind, canonical jsonb, first_seen, last_seen)  -- one per merged identity
gateway.record_sources (identity, source_id, raw jsonb, fetched_at, license,
                        redistributable bool)                                    -- I-8, cache policy
gateway.index_docs     (identity, kind, tsv tsvector, domain, year)             -- Tier 0 index
```

Rules: `records` never stores full text. `record_sources.redistributable`
derives from `sources.use_commercial`/licence and gates export and cache
persistence. `jobs` are deduplicated on `(request_type, payload hash)` while
in flight.

---

## 3. Working set (seed) — the only sources the gateway knows

Kinds: A = article index, D = dataset/repository index, C = citation graph,
R = resolver/enrichment, S = statistical data API. Commercial verdicts are the
2026-09-07 values from `platform_access` / `source_decisions`; **rate limits
marked (verify) must be confirmed from response headers or docs during Phase 2
and the evidence URL recorded before the source is enabled.**

| Source | Kind | Requests | Auth (logical secret) | Rate policy | Commercial |
|---|---|---|---|---|---|
| Crossref | A, C(refs) | find, resolve, enrich | none (mailto) | ~50/s polite pool, no daily cap | allow |
| DataCite | D | find, resolve | none | not stated → 5/s conservative (verify) | allow |
| DOAJ | A | find, resolve | none | 2/s, bursts of 5; 1,000 records/query cap | allow |
| OpenAIRE | A, D | find, resolve | client credentials (`openaire`) | 7,200/h registered; hourly bearer | allow (CC-BY) |
| OpenAlex (snapshot only) | A | find (local index) | none | no live calls (D-2) | allow |
| Semantic Scholar | A, R(full text) | find, resolve, enrich | key (`semantic_scholar`) | 1/s keyed | **deny** |
| CORE | R(full text) | resolve, enrich | key (`core`) | 1 per 2 s, daily budget 200 (observed quota) | **deny** (API); dumps ODC-By |
| Unpaywall | R(OA location) | enrich | none (email) | 100,000/day | allow (CC0) |
| OpenCitations | C | enrich | none | not stated → 5/s (verify) | allow |
| Europe PMC | A | find, resolve | none | not stated → 5/s (verify) | per-item |
| FRED | S | data | key (`fred`) | 120/min (verify) | allow (attribution; some series restricted) |
| BEA | S | data | key (`bea`) | 100/min, 100 MB/min (verify) | allow |
| US Census | S | data | key (`census`) | keyed: no stated cap (verify) | allow |
| BLS (CEX, CPI) | S | data | none / optional key | v2: 500 queries/day keyed (verify) | allow |
| BIS SDMX | S | data | none | not stated → 5/s (verify) | allow |
| ECB SDMX | S | data | none | not stated → 5/s (verify) | allow |
| GovInfo (api.data.gov) | D(documents) | find, resolve, fetch | key (`api_data_gov`) | header-reported 36,000/h | allow |
| Harvard Dataverse | D | find, resolve, fetch | none (optional token) | not stated → 5/s (verify) | allow (CC0 default) |
| World Management Survey | D | fetch (Dataverse DOI 10.7910/DVN/OY6CBK) | none | via Dataverse | allow (CC0) |
| GLOBE | D | fetch | none | n/a (static files) | unknown |
| Socrata (SODA) | D | find, resolve, fetch | optional app token | 1,000/h with token (verify) | per-item |
| Kaggle | D | find, fetch | username+key (`kaggle`) | not stated (verify) | **deny** |
| Hugging Face Hub | D | find, resolve, fetch | optional token (`huggingface`) | not stated (verify) | per-item |
| OpenML | D | find, resolve, fetch | none | not stated (verify) | per-item |
| QDR | D | find, resolve | key (`qdr`) | Dataverse, not stated (verify) | **deny** |
| Pew Research | — | manual only | account | — | allow (public domain) — documented, not wired |

Not in the seed and never scheduled: OpenAlex live API, Google Scholar, Lens,
Scilit, BASE (until whitelist reply — then `deny` commercial), Elsevier
(parked, D-3), any Duke/Fuqua subscription, UN Comtrade (deny; may be added
later as personal-only), the keep-on-hand set (73 rows in `source_decisions`).

---

## 4. Routing rules (each rule has a test in `tests/routing/`)

Inputs: `request_type`, `identity` (if any), `kind_filter`, `domain` (explicit
from caller; never inferred in v1), `commercial` flag, breaker states, budgets.

R-1  `resolve` with a DOI → look up registration agency (cached) →
     Crossref-registered: Crossref; DataCite-registered: DataCite; else OpenAIRE.
     Fallback on failure/breaker: substitution group {Crossref, OpenAIRE, Unpaywall}.
R-2  `find` kind=article → Crossref + local OpenAlex index; add DOAJ always
     (open-access long tail); add Semantic Scholar only when `domain` ∈
     {ai-ml, software}; add Europe PMC only when `domain` ∈ {biomed} (out of
     scope today, present for completeness). OpenAIRE and Unpaywall are NOT
     discovery lanes (measured 96–99% overlap with Crossref).
R-3  `find` kind=dataset → DataCite (base) + domain lanes by tag:
     finance/economics → none extra (data requests go to S sources);
     social → Harvard Dataverse, QDR (personal only);
     ai-ml/software → Hugging Face, OpenML, Kaggle (personal only);
     market/consumer → Socrata, GovInfo, Kaggle (personal only).
R-4  `enrich` is opt-in per request: citations → OpenCitations (fallback Crossref
     references); oa_location → Unpaywall; full_text → Semantic Scholar then CORE
     (both personal-only; results never persisted).
R-5  `data` → exactly one S source chosen by the caller's `source` parameter
     (FRED/BEA/Census/BLS/BIS/ECB); no fan-out; series identifiers are source-native.
R-6  `fetch` → the URL's host must belong to a registry source with `fetch`
     capability; otherwise refuse (no arbitrary downloads).
R-7  Freshness: `find`/`resolve` for items dated within 30 days skip the local
     index and go to origin registries first.
R-8  `commercial=true` removes every lane whose verdict ≠ allow, and removes
     per-item lanes unless the caller opts in with `accept_per_item=true`, in
     which case records lacking an allow-listed licence are dropped.
R-9  Domain lanes ADD to base lanes; nothing ever suppresses a base lane.
R-10 A source with an open breaker or exhausted budget is skipped and the job
     result records `capability_fact` for it; the job still completes.

---

## 5. Queue, broker, breakers (Phase 2 — nothing runs unmetered)

- Jobs table with `SELECT … FOR UPDATE SKIP LOCKED`; N worker coroutines in the
  gateway process; priorities: interactive (loop iteration) > enrichment > harvest.
- Token bucket per `(source, credential)` seeded from `rate_policies`; refill on
  the documented interval; shared across all workers and both front doors (I-1).
- Daily budgets (`per_day`, `cost_cap_per_day`) reset at the source's stated
  boundary (UTC midnight unless documented otherwise).
- On 429/503: honour `Retry-After` when present, else exponential backoff
  10→80 s; after 3 consecutive limit errors open the breaker for the source's
  documented window (default 15 min), route to substitution group, log
  `failure_class=quota|outage`.
- Identity: `User-Agent: research-gateway/<version> (mailto:<configured>)`;
  `mailto` on Crossref/Unpaywall; BASE's registered user-agent when enabled.

---

## 6. Cache, dedup, licence enforcement

- Cache key = normalised identity (DOI lower-case, prefix-stripped) or a hash of
  `(source, query)`. TTL per source (default 7 days metadata; 1 hour search).
- `redistributable=false` sources (Semantic Scholar, CORE, BASE, per-item
  records without an allow-listed licence) are cached in memory only, ≤ 1 hour,
  never written to `record_sources`, never exported.
- Dedup stages: DOI normalise → exact identity → (title normalised + year +
  first author) fuzzy ≥ 0.92 → cluster; provenance kept for every member.
- Paging is stateless: opaque resumption token = (query hash, offset, lane cursor set).

---

## 7. Logging and alerts (trouble detection only — D-6)

`gateway.calls` per I-6. Alerts via the homelab ntfy channel when: a breaker
opens; a daily budget passes 80 %; auth failures on a source; a source returns
zero results for a query pattern that returned results in the last 7 days
(bot-wall detector); gateway health check fails. No automatic routing changes.

---

## 8. Harvest and local index (Tier 0)

Loaders run on a schedule (tower systemd timers): OpenAlex sources snapshot
(quarterly), Crossref journals (monthly), DOAJ journals CSV (monthly), DataCite
repositories (monthly), re3data (monthly). Loaded into `gateway.index_docs`
with Postgres full-text search. `find` consults the index first, live lanes
for freshness/long tail (R-7). Embedding/reranking tiers are optional later
phases and degrade to Tier 0 (no GPU, no vector DB required).

---

## 9. Front doors and auth

- HTTP API on the tower, bearer token per client (loop stations, MCP adapter,
  CLI); tokens in Vault privately, env vars publicly.
- `clients/mcp_stdio.py`: mounted by the loops via `--mcp-config` exactly like
  the existing `github-ro` tool; exposes `research_find`, `research_resolve`,
  `research_enrich`, `research_fetch`, `research_data`, `research_status`.
- `mcp/homelab_adapter.py`: registers the same five tools on the homelab MCP
  gateway, calling the same HTTP API with its own token (I-1).

---

## 10. Deployment (private config, public code)

Tower container (`deploy/`), Postgres `research_loops` DB, secrets from Vault
`services/*` via `secrets.py`'s Vault backend (private) or env vars (public
default). Health endpoint polled by the homelab monitor. Rollback = previous
image; schema migrations are additive only in v1.

---

## 11. Documentation deliverables (Phase 6, but stubs from Phase 1)

`docs/SOURCES.md` — for every registry source: name, kind, what it holds, link,
**how to obtain a key** (or "no key"), rate limit with evidence link, licence,
**commercial verdict with its evidence**, unknowns stated as unknown, personal
use noted as baseline. Generated from the registry by `research_gateway/registry/docs.py`
and committed; the drift check (§14) diffs generated vs committed.
Plus README, ARCHITECTURE, OPERATIONS, PUBLIC-PRIVATE, LICENSING.

---

## 12. Public / private boundary checklist (run before every commit on this branch)

- [ ] `git grep -nE '192\.168\.|vault-token|X-Vault|BluDevi|api_key=|KGAT_|hvs\.' -- gateway/` returns nothing
- [ ] no file under `gateway/` references `private/`, Duke, Fuqua, WRDS, Elsevier keys
- [ ] `sources.example.yaml` contains no real credentials
- [ ] no data files (CSV/JSONL/parquet) under `gateway/` except test fixtures ≤ 50 KB
- [ ] `gateway/docs/SOURCES.md` matches `registry/docs.py` output
- [ ] no adapter exists for a source that is not in `seed/sources.yaml`

---

## 13. Phases, deliverables, acceptance checks

Each phase is a branch commit series on `research-gateway`; merge to main only
after its checks pass and the operator has reviewed (two-bucket rule).

**Phase 0 — Contract (this document).** Acceptance: operator approval logged in §16.

**Phase 1 — Registry + schema + seed + docs stubs.**
Deliverables: `registry/schema.sql`, `seed/sources.yaml` (§3 verbatim), `load.py`,
`registry/docs.py`, stub docs. Checks:
- `python -m research_gateway.registry.load --dry-run` validates every seeded
  source has kind, capabilities, rate policy, verdict + evidence
- `SELECT count(*) FROM gateway.sources` = number of rows in §3 minus "manual only"
- `docs.py` output == committed `docs/SOURCES.md`

**Phase 2 — Queue, broker, breakers, call log.**
Checks (tests/broker): bucket never exceeds policy under 100 concurrent
requests; `Retry-After` honoured; breaker opens after 3 limit errors and
closes after window; every dispatched call has a `gateway.calls` row; a source
without a rate policy is refused (I-3).

**Phase 3 — Adapters (contract tests, recorded fixtures) + identity.**
One adapter per §3 row that is not "manual only"; each with a fixture-based
test for every capability it declares; `identity.py` tests for DOI/ISSN
normalisation and registration-agency routing. Check: `pytest tests/contract`
passes offline; a live smoke (`--live`, operator-run) hits each adapter once
and records observed rate-limit headers into `rate_policies.evidence`,
resolving every "(verify)" in §3 before that source is `enabled`.

**Phase 4 — Router + cache + dedup + licence enforcement.**
Checks: every rule R-1..R-10 has a passing test; commercial=true excludes
deny/unknown sources; per-item records without allow-listed licence dropped;
non-redistributable payloads never appear in `record_sources`.

**Phase 5 — HTTP API, auth, two front doors.**
Checks: `/v1/health` green; stdio client mounted in a station profile returns a
`find` result; homelab-gateway registration lists the five tools; a request
with a bad token is refused; killing the gateway makes the client return
`capability_fact: gateway_unavailable` (I-1).

**Phase 6 — Harvest loaders + Tier 0 index + docs complete.**
Checks: index row counts ≥ snapshot record counts − dedup; `find` on a known
title hits the index before any live lane (call log proves it); all §11 docs
present; §12 checklist clean.

**Phase 7 — Regression + deploy.**
Checks: `tests/regression/overlap_probe.py` reproduces the 2026-09 per-source
presence expectations within ±5 %; container deployed on the tower; ntfy alert
fires on a forced breaker; loops switched from direct web access to the tool
for one topic, iteration completes, call log shows only gateway-routed calls.

---

## 14. Session checklist (anti-drift; run at the start of every gateway session)

1. Re-read §0 invariants and §16 Decision log; note any operator ruling since.
2. `git status` clean on `research-gateway`; on the right worktree.
3. `pytest -q` green; if red, fix before new work.
4. Registry vs code: every file in `adapters/` has a row in `seed/sources.yaml`
   and vice versa (`python -m research_gateway.registry.load --check-adapters`).
5. Docs vs registry: `python -m research_gateway.registry.docs --check`.
6. §12 boundary checklist.
7. Grep for direct source calls outside adapters:
   `git grep -nE 'api\.(crossref|datacite|openaire|semanticscholar|core|unpaywall|opencitations|stlouisfed|bea|census)' -- research_gateway | grep -v adapters/` → must be empty.
8. Confirm no OpenAlex API URL anywhere in `research_gateway/` except a
   commented reference in `harvest/openalex_snapshot.py` (D-2).
9. State in the session log which phase/check is being worked; if the task
   isn't in §13, it's scope creep — stop and record a decision.

---

## 15. Open questions (must be closed with a Decision-log entry before the phase that needs them)

- Q-1 Bearer-token issuance for clients: static per-client tokens in Vault (v1) vs. OAuth later. Needed by Phase 5.
- Q-2 BASE: enable when the whitelist reply arrives (commercial=deny). Phase 3+.
- Q-3 CORE: keep as personal-only full-text lane with a 200/day budget, or drop until a member tier exists. Phase 3.
- Q-4 Whether `data` requests should also be recorded as `records` (series metadata) for provenance. Phase 4.
- Q-5 Retention for `gateway.calls` (proposed 180 days). Phase 2.

---

## 16. Decision log

- **D-1 (2026-09-06)** Enumeration is a registry lookup; the loops judge. Gateway finds, loops decide.
- **D-2 (2026-09-06)** No OpenAlex API calls; snapshot only.
- **D-3 (2026-09-06/07)** Institutional (Duke/Fuqua) sources are manual-only; WRDS excluded outright; a source qualifies only with an API, terms read, usage understood. Elsevier parked with key in Vault.
- **D-4 (2026-09-07)** Regional and non-priority-domain sources are keep-on-hand.
- **D-5 (2026-09-07)** Single `commercial` flag per topic; personal is the baseline; unknown fails closed; `per-item` verdict added.
- **D-6 (2026-09-07)** Logs are for trouble detection; no automatic lane re-tuning.
- **D-7 (2026-09-07)** Gateway lives in this repo AND is registered on the homelab MCP gateway; Postgres is the queue and store; no Redis.
- **D-8 (2026-09-07)** Harvest branch and registries stay unmerged/private; only the registry schema and seed carry over.
- **D-9 (2026-09-07)** Links not papers; topic findings stay in topic results; open-licensed cited full texts may be cached at completion alongside the knowledge-graph ingest.
- **D-10 (2026-09-07)** Working set fixed as §3 (28 sources) after operator approval of the loop's Part B batch.
- **D-11 (2026-09-07)** `private/` is the gitignored parking folder; SOURCES.md to be purged from public history by the operator.
