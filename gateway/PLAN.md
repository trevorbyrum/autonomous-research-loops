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
- **I-10 No placeholders.** Nothing merges with `TODO`, `FIXME`, `XXX`,
  `NotImplementedError`, `pass  # stub`, "placeholder", or a function whose body
  only raises/returns a dummy. Every shipped function does its job; every
  declared capability works against its fixture. Docs may be short; they may
  not be lorem-ipsum.
- **I-11 ≤ 1,500 lines per file, hard.** Enforced by a test
  (`tests/test_file_limits.py`) that fails the suite. Split by concern, never by
  arbitrary cut.
- **I-12 Simplest thing that works.** Standard library first; one small HTTP
  framework and one Postgres driver are the only third-party runtime
  dependencies allowed in v1. No abstraction with a single implementation except
  the adapter interface and the secrets backend. No configuration knob without
  a documented reason. If a 40-line function does what a class hierarchy would,
  ship the function.
- **I-13 Independent review each phase.** Before a phase is declared done, a
  separate agent on a different model (Terra — `gpt-5.6-terra` via Codex, or
  the nearest available) reviews the diff against this plan with the review
  brief in §13a. Findings are fixed or logged in §16 with a reason; the phase's
  acceptance record names the reviewer and the commit reviewed.
- **I-14 Tests and logs are part of every phase**, not a later phase: each
  module ships with its tests; each externally-observable action writes a
  `gateway.calls` or structured log line. A phase with code but no tests is
  not done.

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
      seed/sources.toml       the working set (§3) with kinds, capabilities, rate policy,
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
sources.example.toml          public example config (env-var secrets), user-editable
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
                        started_at, finished_at, result jsonb, error_class)      -- result inline (D-15)
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
| BEA | S | data | key (`bea`) | 100/min (verify); the 100 MB/min volume cap is not broker-enforced (D-15) | allow |
| US Census | S | data | key (`census`) | keyed: no stated cap → 5/s conservative (verify) | allow |
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

Domains in v1: `finance`, `market`, `social`, `management`, `ai-ml`, `software`,
`biomed`, and **`other`**. `other` is the permissive catch-all: base lanes plus
**every** domain lane the commercial flag and budgets allow. A request with no
domain, or with a domain the registry does not know, is treated as `other` —
mis-tagging costs extra calls, never missed coverage (D-12).

R-1  `resolve` with a DOI → look up registration agency (cached, via the
     `doi_org` source) → the enabled resolver whose adapter declares that agency
     in `AGENCIES` (Crossref → Crossref; DataCite → DataCite; `*` = OpenAIRE
     for any other or unknown agency). Fallback on failure/breaker: the
     primary's substitution group from the registry — resolvers first, then
     members that can return metadata through an `oa_location` enrichment
     (Unpaywall). Nothing in this rule is hard-coded (D-16).
R-2  `find` kind=article → Crossref + local OpenAlex index; add DOAJ always
     (open-access long tail); add Semantic Scholar only when `domain` ∈
     {ai-ml, software}; add Europe PMC only when `domain` ∈ {biomed} (out of
     scope today, present for completeness). OpenAIRE and Unpaywall are NOT
     discovery lanes (measured 96–99% overlap with Crossref).
R-3  `find` kind=dataset → DataCite (base) + every registry source of kind
     dataset whose `domains` list contains the request domain (D-16: the seed,
     not this text, is the routing table). With the 2026-09-07 seed:
     social → Harvard Dataverse (per-item, D-23), QDR (personal only);
     ai-ml → Kaggle (personal only), Hugging Face, OpenML;
     software → Kaggle (personal only), Hugging Face;
     market → GovInfo, Harvard Dataverse (per-item), Socrata, Kaggle (personal only);
     finance → GovInfo, Harvard Dataverse (per-item), Socrata; management → GovInfo,
     Harvard Dataverse (per-item), QDR (personal only). A source with no `domains` and no
     `base_for` is never a discovery lane (OpenAIRE, Unpaywall).
R-4  `enrich` is opt-in per request; lanes are the enabled sources whose adapter
     declares the requested kind in `ENRICHES`, dedicated bases first (D-16):
     citations → OpenCitations, then Semantic Scholar (personal only);
     references → OpenCitations, then Crossref, then Semantic Scholar;
     oa_location → Unpaywall; full_text → Semantic Scholar then CORE (both
     personal-only; results never persisted). The first lane that answers wins;
     later lanes are for failure only.
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
R-9a `domain=other` (or absent/unknown) → base lanes + all domain lanes, filtered
     only by R-8 and R-10. Logged with `domain_resolved=other` so mis-tagging is
     visible in the call log.
R-10 A source with an open breaker or exhausted budget is skipped and the job
     result records `capability_fact` for it; the job still completes.

---

## 5. Queue, broker, breakers (Phase 2 — nothing runs unmetered)

- Jobs table with `SELECT … FOR UPDATE SKIP LOCKED`; N worker coroutines in the
  gateway process; priorities: interactive (loop iteration) > enrichment > harvest.
- Sliding windows per source seeded from `rate_policies` (the registry holds one
  credential per source, so `(source, credential)` collapses to source — D-15);
  shared across all workers and both front doors (I-1).
- Daily budgets (`per_day`, `cost_cap_per_day`) are counters per UTC day, not
  trailing 24 h windows; they reset at UTC midnight.
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
  never written to `record_sources`, never exported. A merged record persists
  only its redistributable provenance members. Memory caches are bounded
  (oldest evicted). A cache hit is re-checked against R-8 before it answers a
  commercial request.
- Allow-listed licences permit commercial reuse with attribution at most:
  CC0, CC-BY, public domain, ODC-BY/PDDL, MIT/Apache/BSD/ISC/zlib/Unlicense,
  U.S. federal works. NC, ND and share-alike variants — including ODbL, whose
  share-alike terms this list once wrongly included — are not allow-listed
  (D-18, corrected by D-23). Recognition is exact (SPDX ids, names, canonical
  URLs); unknown or annotated licence text fails closed.
- Dedup stages: DOI normalise → exact identity → fuzzy (title ≥ 0.92 AND same
  year AND same first author, all three present — a missing year or author
  never merges) → cluster, greedily in lane order (the base lane's record is
  canonical); provenance kept for every member.
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
repositories (monthly). Loaded into `gateway.index_docs` with Postgres
full-text search. `find` consults the index first, live lanes for
freshness/long tail (R-7). Embedding/reranking tiers are optional later
phases and degrade to Tier 0 (no GPU, no vector DB required).

What the index holds (D-19): **venues and repositories** — journals,
conference series, book series, ebook platforms, data and publication
repositories — one record per identity (`issn:<ISSN-L>` when there is one,
else `venue:`/`repository:<registry>:<id>`), merged across the four registries
with a provenance row per registry and the fields of later loaders filling in
(never erasing). Works are not indexed: there is no works snapshot and the
gateway returns links, not papers (I-7). `find kind=venue|repository` is served
by the index alone; `find kind=article|dataset` runs the index lane first
(adapters declare `LOCAL = True`), then the live lanes. re3data is not loaded:
it is not a registry source (no row, no adapter) and its repositories reach the
index through DataCite's `re3data` identifiers.

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

- [ ] `git grep -nE '192\.168\.|10\.0\.|vault-token|X-Vault|postgresql://[^ ]+:[^ ]+@|api_key=[A-Za-z0-9]|KGAT_|hvs\.' -- gateway/ ':!gateway/PLAN.md' ':!gateway/research_gateway/core/secrets.py' ':!gateway/tests/test_core_foundations.py'` returns nothing (`core/secrets.py` is the generic Vault KV client: it names the protocol header and the default token-file path, never an address or a value; the foundations test names a private address precisely to assert the transport REFUSES redirecting to it)
- [ ] no file under `gateway/research_gateway/` or `gateway/docs/` references the repository's
      parking folder by name, Duke, Fuqua, WRDS, or Elsevier keys (this plan and the test files may
      state the rule itself)
- [ ] `sources.example.toml` contains no real credentials
- [ ] no data files (CSV/JSONL/parquet) under `gateway/` except test fixtures ≤ 50 KB
- [ ] `gateway/docs/SOURCES.md` matches `registry/docs.py` output
- [ ] no adapter exists for a source that is not in `seed/sources.toml`
- [ ] `git grep -nE 'TODO|FIXME|XXX|NotImplementedError|placeholder|lorem' -- gateway/research_gateway/ ':!gateway/research_gateway/*/__pycache__'` returns nothing (I-10 — shipped code; the plan, the docs that state this rule, and the test that enforces it necessarily name the markers)
- [ ] `pytest tests/test_file_limits.py` passes: no file > 1,500 lines (I-11)
- [ ] `pytest -q` green, and every module touched in the commit has a test file touched or added (I-14)

---

## 13. Phases, deliverables, acceptance checks

Each phase is a branch commit series on `research-gateway`; merge to main only
after its checks pass and the operator has reviewed (two-bucket rule).

**Phase 0 — Contract (this document).** Acceptance: operator approval logged in §16.

**Phase 1 — Registry + schema + seed + docs stubs.**
Deliverables: `registry/schema.sql`, `seed/sources.toml` (§3 verbatim), `load.py`,
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
Review (Terra, 2026-09-07, `private/reviews/phase1-2-588c6f4.md`): Phase 1 PASS
WITH FINDINGS, Phase 2 FAIL — 11 findings. Blockers fixed (handlers receive a
job-bound metered client so every call is logged with its job id; `per_day` is a
UTC-day counter); 10→80 s backoff and the enqueue re-read race fixed; seed
numeric validation added; Census keyed rate corrected; README DSN example
de-credentialed; the remainder resolved by D-15.

**Phase 3 — Adapters (contract tests, recorded fixtures) + identity.**
One adapter per §3 row that is not "manual only"; each with a fixture-based
test for every capability it declares; `identity.py` tests for DOI/ISSN
normalisation and registration-agency routing. Check: `pytest tests/contract`
passes offline; a live smoke (`--live`, operator-run) hits each adapter once
and records observed rate-limit headers into `rate_policies.evidence`,
resolving every "(verify)" in §3 before that source is `enabled`.
Smoke run 2026-09-07 (`python3 -m research_gateway.smoke --live`, report in
`private/reviews/smoke-2026-09-07.json`): 23 of 24 network sources answered 200
on the first call with real credentials; BIS answered 406 because its v2 API
serves SDMX-ML only, so the adapter now reads XML. Observed headers (OpenAIRE
7,200/h, CORE 150, GovInfo 36,000/h, Hugging Face 500 per 300 s) and the smoke
outcome are recorded in each seed row's `rate.evidence`; every "(verify)" row is
now `verified=true, enabled=true`, with sources whose documentation states no
limit carrying an explicit self-imposed ceiling. GLOBE stays disabled (static
files, nothing to probe, commercial verdict unknown); Pew is manual.
Review (Terra, 2026-09-07, `private/reviews/phase3-44efdc2.md`): FAIL — 7
findings, all resolved: raw payloads are now the source objects (I-8); file
bytes/full text never reach `jobs.result`; Socrata portals are catalog-vouched
(R-6); GovInfo fetch lists real formats; enqueue contention is bounded with a
retryable error; unreadable responses become capability facts; logging is
guaranteed by construction (D-17). Test backoff waits now run on a fake clock.

**Phase 4 — Router + cache + dedup + licence enforcement.**
Checks: every rule R-1..R-10 has a passing test; commercial=true excludes
deny/unknown sources; per-item records without allow-listed licence dropped;
non-redistributable payloads never appear in `record_sources`.
Built 2026-09-07 (`tests/test_routing.py`, `tests/test_cache_dedup.py`).
Review (Terra, `private/reviews/phase4-c570832.md`): FAIL — 9 findings, all
resolved by D-18 and its tests (per-member persistence, cache/queue commercial
gating, bounded caches, strict fuzzy dedup, broad lane fault containment,
declared schemes, share-alike, registry-declared DOI agencies).

**Phase 5 — HTTP API, auth, two front doors.**
Checks: `/v1/health` green; stdio client mounted in a station profile returns a
`find` result; homelab-gateway registration lists the five tools; a request
with a bad token is refused; killing the gateway makes the client return
`capability_fact: gateway_unavailable` (I-1).
Built 2026-09-07: `app.py` (assembled process; inline mode without a DB),
`api/http.py` (bearer tokens; `/v1/*`; `POST /mcp` stateless MCP for the
homelab gateway, which consumes peers from its `external-mcp.json` —
`mcp/homelab_adapter.peer_entry()` renders the entry, the operator applies it
on the tower), `clients/mcp_stdio.py`, `clients/cli.py`. End-to-end run on the
workstation: health green in queued mode (2 workers), stdio client listed the
six tools and resolved a DOI through a queued job, the CLI ran a live `find`
(Crossref + DOAJ + local index), bad token → 401. Station mounting waits for
the tower deployment (Phase 7).
Review (Terra, `private/reviews/phase5-43fef3e.md`): FAIL — 7 findings, all
resolved by D-20 and its tests.

**Phase 6 — Harvest loaders + Tier 0 index + docs complete.**
Checks: index row counts ≥ snapshot record counts − dedup; `find` on a known
title hits the index before any live lane (call log proves it); all §11 docs
present; §12 checklist clean.
Built and loaded 2026-09-07, rebuilt after the D-22 identity fixes: 306,794
records — 294,942 venues and 11,839 repositories — with provenance from
OpenAlex sources (283,688 rows), Crossref journals (151,493), DOAJ (23,286)
and DataCite repositories (4,483); the ISSN map joins print/electronic/ISSN-L
twins into one record. Loaders run one at a time under an advisory lock
(concurrent first runs deadlocked). `find kind=venue "supply chain
management"` answered from the index alone, and for articles the call log
reads `openalex_snapshot, crossref, doaj` in that order.

**Phase 7 — Regression + deploy.**
Checks: `tests/regression/overlap_probe.py` reproduces the 2026-09 per-source
presence expectations within ±5 %; container deployed on the tower; ntfy alert
fires on a forced breaker; loops switched from direct web access to the tool
for one topic, iteration completes, call log shows only gateway-routed calls.
Status 2026-09-07: regression replay of 40 sampled works against 7 sources
(`private/regression/replay-2026-09-07.json`) — every source within
tolerance (Crossref 80/80 %, DOAJ 32/32, OpenAIRE 85/85, Unpaywall 80/80,
Semantic Scholar 67/69, CORE 35/35, Europe PMC 20/20; agreement ≥ 97 %).
Alerts (§7) built in `core/alerts.py` with the watcher thread; a forced
breaker alert was delivered to the operator's ntfy topic. Deployment files in
`deploy/` (Dockerfile, compose, systemd units + monthly harvest timer,
README with the operator steps). **Not done, operator decisions (D-21):**
where the gateway runs (tower container vs. this workstation), the Vault
bundle for its tokens, the homelab gateway peer entry, and switching a loop
topic to the tool.
Review (Terra, `private/reviews/phase6-7-2a0cc84.md`): FAIL/FAIL — 10
findings, resolved by D-22 and its tests; the operational checks stay pending.

### 13a. Independent review gate (every phase; I-13)

Reviewer: a Codex-backed agent on `gpt-5.6-terra` (fallback: `gpt-5.6-sol`),
given the phase's diff, this plan, and this brief. It must answer, with file
and line references:
1. Does any code call a source outside `adapters/`, or an adapter without a
   registry row? (I-1, I-2)
2. Is there any placeholder, stub, dead branch, or unreachable capability? (I-10)
3. Any file over 1,500 lines, or a module that should be split by concern? (I-11)
4. Anything over-engineered — abstraction with one implementation, config with
   no consumer, framework where the stdlib would do? (I-12)
5. Which acceptance checks in §13 for this phase are NOT actually exercised by
   a test? Name each.
6. Does anything under `gateway/` violate the public/private checklist (§12)?
7. Where does the code contradict this plan? Quote both.
Findings are resolved in the same phase or logged in §16 with a reason. The
reviewer's report is saved to `private/reviews/<phase>-<commit>.md` (not
public) and its commit hash recorded in the phase's acceptance note.

---

## 14. Session checklist (anti-drift; run at the start of every gateway session)

1. Re-read §0 invariants and §16 Decision log; note any operator ruling since.
2. `git status` clean on `research-gateway`; on the right worktree.
3. `pytest -q` green; if red, fix before new work.
4. Registry vs code: every file in `adapters/` has a row in `seed/sources.toml`
   and vice versa (`python -m research_gateway.registry.load --check-adapters`).
5. Docs vs registry: `python -m research_gateway.registry.docs --check`.
6. §12 boundary checklist.
7. Grep for direct source calls outside adapters:
   `git grep -nE 'api\.(crossref|datacite|openaire|semanticscholar|core|unpaywall|opencitations|stlouisfed|bea|census)' -- research_gateway | grep -v adapters/` → must be empty.
8. Confirm no OpenAlex API URL anywhere in `research_gateway/` except a
   commented reference in `harvest/openalex_snapshot.py` (D-2).
9. State in the session log which phase/check is being worked; if the task
   isn't in §13, it's scope creep — stop and record a decision.
10. Placeholder grep (I-10) empty; file-limit test (I-11) green; every changed
    module has tests (I-14).
11. Before declaring a phase done: run the §13a review, record reviewer + commit.

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
- **D-10 (2026-09-07)** Working set fixed as §3 (27 sources: 26 with adapters plus Pew, manual) after operator approval of the loop's Part B batch.
- **D-11 (2026-09-07)** `private/` is the gitignored parking folder; SOURCES.md to be purged from public history by the operator.
- **D-12 (2026-09-07)** Add a permissive catch-all domain `other` (= base + all domain lanes); absent/unknown domains resolve to it, so mis-tagging never loses coverage.
- **D-13 (2026-09-07)** Engineering rules, hard: no placeholders in shipped code (I-10); ≤ 1,500 lines per file (I-11); simplest thing that works (I-12); independent Terra/Codex review each phase (I-13); tests and logs ship with every module (I-14).
- **D-14 (2026-09-07)** Phase 0 approved by the operator ("approved"). Phase 1 begins.
- **D-27a (2026-09-07)** Pass-6 amendment (`private/reviews/pass6-b6452a0-astra.md`; pass 6 verified all three pass-5 items resolved and every D-27 claim accurate except one new gap): version segments on exact-id licence routes are an explicit per-route WHITELIST (the Open Data Commons deeds have 1.0; MIT and ISC have none), never a digits-and-dots pattern — an invented `/9.9/` or malformed `/1../` identifies nothing.
- **D-27 (2026-09-07)** Fifth-pass resolutions (Astra pass 5, `private/reviews/pass5-78968b7-astra.md`; everything else from pass 4 verified resolved there): exact-id licence routes now require the id to END at the route (an encoded or plain `MIT-noncommercial` is a different id), with only a numeric version segment permitted after it — which also restores the versioned Open Data Commons deed URLs the D-26 regex had wrongly dropped; and an EMPTY deployed policy set is authoritative for all three maintenance runners (a deployment that enabled nothing dispatches nothing — the seed no longer fills that silence). D-26's "deployed policies whenever a database exists" claim is accurate as of this entry.
- **D-26 (2026-09-07)** Verdict-pass resolutions (Astra pass 4, `private/reviews/verdict-0ea8135-astra.md`): the maintenance-guard absence predicate was INVERTED in the D-25 commit and is fixed with its truth table pinned by test; the cache's synthesized member list now mirrors the router's exactly (sources-order, only the record's own source carries raw), so a member index authorized in one place can never land on a different member in the other, and dedup expands sources-only records the same way; CC URL versions are the deeds' real ones (1.0/2.0/2.5/3.0/4.0; CC0 and the mark only 1.0), encoded traversal decodes before checks, and non-CC routes accept at most one path segment; the pre-dispatch attempt row carries the credits charged at acquire, so a crash restores them; Transfer-Encoding is checked across ALL header instances; `finish` requires a live claim (`running`) while `fail` may also refuse a queued job; the index read joins on record kind and reindex deletes label-mismatched rows; all three maintenance runners (smoke, harvest, regression replay) use the deployed database policies when one exists and seed the day's usage and persisted breakers. Two residual descriptions D-24 got wrong are corrected in place (personal-mode restricted bytes ARE delivered; ISSN twins need a full rebuild). Accepted residuals added: a mislabelled index row now simply never surfaces (rather than surfacing mislabelled); FRED's fail-closed note parsing withholds some genuinely usable series under commercial topics; consumers tailing the call log by row id must revisit `attempt` rows for their completion.
- **D-25 (2026-09-07)** Third-pass resolutions (Astra pass 3, `private/reviews/final-05c60af-astra.md`): the audit row is written BEFORE dispatch and completed after (a crash mid-request leaves its row; an unwritable log dispatches nothing); provenance gating is index-based per member with each member's own licence, an absent licence counts as unlicensed, `sources` lists without provenance produce one member per source, and dedup carries every existing member through a re-merge; the whole result (lane errors included) is redacted before caching, short secrets as whole tokens; licence URLs parse the real hostname (userinfo bypass closed), reject queries/fragments/traversal, and accept only versions the deeds have; the local index serves and reindexes venue/repository rows only and deletes wrong-kind leftovers; terminal lease sweeps clear the fencing token and finish/fail require `running`; FRED fails closed on shapeless metadata and its restriction markers cover common phrasings; Dataverse refuses commercial downloads with extra terms of use or restricted member files; the maintenance guard treats only a refused connection or unresolvable name as absence, and maintenance brokers seed the day's usage and persisted breakers from the database; catalogue envelopes must be lists; async is a 400 for inline-only requests; chunked bodies are refused; the regression floor of 10 observations is a clamp, not a default. Accepted residuals carried forward from D-24, plus: canonical metadata FIELDS (a title, a link) contributed by a restricted member remain in the merged record — facts are not payloads; FRED note parsing is substring-based over free text and errs toward withholding; inline execution is bounded by source timeouts rather than the queue timeout; concurrent maintenance processes can race the guard check; two gateway processes sharing one database still each own in-memory windows (one service per database is the deployment rule).
- **D-24 (2026-09-07)** Re-verification resolutions (Astra pass 2, `private/reviews/reverify-a86dbe0-astra.md`): `fetch` and `data` are ALWAYS inline — their rows, files and text are delivered and discarded, never queued or stored, which also restores the table data the first fix wrongly stripped from answers; cross-origin redirect hops degrade to bare GETs (no body travels either) and 3xx rows are class `redirect` (counted by budget re-seeding; credits once per request); licence URLs match host-exactly and only versions the licences actually have; download-capable adapters refuse restricted fetches BEFORE any bytes move (the executor sets `client.commercial`), the exact Hugging Face revision's licence is checked, and FRED fails closed when its metadata is unavailable; secret redaction runs before caching, covers keys/tuples, and includes exchanged bearer tokens; job claims carry a fencing token so a reclaimed job's stale worker cannot overwrite the retry; the maintenance guard fails safe (any answer or a hang counts as a running service); harvest loaders fail on 200-but-not-the-envelope catalogues; the smoke marks credential refusals `unverified` and the regression gate needs ≥ 10 comparable observations per source; payload validation rejects NaN/non-JSON and non-boolean download flags on both doors; the cache rolls back failed transactions; one domain vocabulary (the registry's). Documented residuals, accepted: a second DNS answer between check and connect (TLS-safe pinning is not worth a custom stack for LAN deployment); a personal-mode fetch transfers AND DELIVERS restricted-licence bytes — the personal baseline permits their use, and only the `commercial` flag withholds them (this line originally claimed the bytes were never released, which was wrong — corrected by D-26); byte-trickling clients are bounded by slots and inactivity timeouts, not an absolute deadline; broker status shows yesterday's counters until the next acquisition; identifier-less `doaj:`/`openaire:` labels do not resolve; pre-existing ISSN twins consolidate only on a FULL rebuild (delete the venue records and reload) — an ordinary incremental reload keeps both identities (the original wording overstated this — corrected by D-26).
- **D-23 (2026-09-07)** Full-tree review resolutions (Astra, GPT-6-Astra, `private/reviews/full-f9efc63-astra.md`, verdict FAIL — 12 blockers, 19 should-fixes, all addressed):
  transport follows no redirect on its own — each hop is validated (no scheme downgrade, no non-global destination), re-metered, logged, and credentials never cross origins; the transport never raises, so the call row always exists, and a call-log write failure fails the job closed (`calllog.AuditError`) — refusals that never touch the network and prefix-cached agency lookups are capability facts, not phantom call rows;
  licence recognition is exact (SPDX ids, names, canonical URLs; extra words fail closed; share-alike is out, ODbL is recognised but NOT allow-listed — the §6 mention of ODbL as allow-listed was wrong and is corrected here); every commercial and persistence decision is per provenance member with that member's own licence; a record with any restricted member lives ≤ 1 hour in memory; downloads carry the fetched item's licence and are authorized before bytes leave; `jobs.result` stores canonical metadata only (no raw, rows, text, or bytes); secret values handed to adapters are redacted from results; FRED metadata is always fetched and third-party-restricted series fail the commercial gate; Harvard Dataverse's verdict is `per-item` (depositors choose licences);
  index answers are never written back as fetched records, reindex covers venue/repository kinds only, harvest merges union list fields and build the search vector from the merged record, loaders build their ISSN state under the loader lock, and a failed page or malformed catalogue fails the load loudly;
  the broker enforces fractional rates as spacing, treats burst as capacity over a sustained average, honours HTTP-date Retry-After, never shortens an active breaker, closes elapsed breakers observably, and re-seeds daily budgets from the call log at startup; maintenance runners (harvest, smoke, regression) refuse to run while a service answers on the gateway URL unless RESEARCH_GATEWAY_ALLOW_CONCURRENT=1, and log under their own client ids; OpenAIRE/Census/BLS refuse keyless calls because their enabled policies assume the keyed tier;
  job identity includes the client (no cross-client dedup); workers reconnect instead of dying and a lease sweep requeues jobs stuck `running` (3 attempts, then failed); both front doors validate payloads through one parser; the HTTP server bounds concurrency and read timeouts; gateway JSON envelopes carry a marker header so clients never parse a downloaded JSON file as an answer; the regression gate requires paired agreement ≥ 90 % and full source coverage; smoke probes are declared per adapter (`SMOKE`), and call-log retention (default 180 days) is enforced by the watcher.
- **D-22 (2026-09-07)** Phase 6–7 review resolutions: broker callbacks run after its lock is released and alerts are delivered from a bounded queue on their own thread (a slow or broken ntfy never stalls a request); journal identity is the identity already holding any of the journal's ISSNs (an in-memory ISSN map per load, OpenAlex's ISSN-L first), no-ISSN venues are keyed by registry + full title + publisher; the index merge is additive by design — a wrong non-empty value is corrected by a later non-empty value from any loader, a value is removed only by deleting the record and reloading; the zero-results watcher compares the same query pattern (lower-cased first 80 characters) across the two periods; the regression gate is paired agreement ≥ 90 % as well as the rate tolerance; the index query guards the `works_count` cast and clamps `limit` to 1..100; responses over 256 MB are errors; systemd units use a virtual environment; the tower-token file path no longer matches the §12 grep. Phase 7's operational checks remain pending on the operator (D-21).
- **D-21 (2026-09-07)** Alerts are an `Alerter` (once per key per hour, ntfy) fed by broker callbacks (breaker open, 80 % of a daily budget) and a watcher thread over `gateway.calls` (auth/bot-wall failures, zero-results pattern, health). Deployment is handed to the operator with `deploy/`: the tower gate cannot build images or write files, so placing the service (tower vs. workstation), storing its client tokens in Vault, adding the homelab peer entry and switching a loop topic to the tool are operator steps, listed in `deploy/README.md`.
- **D-20 (2026-09-07)** Phase 5 review resolutions: every call-log row carries `client_id` (queued jobs pass theirs to the metered client; inline requests set it directly, with their own connection and `job_id` NULL); inline mode *without* a database keeps the log in process only and is a laptop mode, not a deployment; clients see only their own jobs; the unauthenticated health answer is ok/version/mode only; front-door payload fields are type-checked (400 otherwise) and `/v1/jobs/<id>` is digits only; the cache has its own connection and lock; the shared client never relays non-JSON error bodies.
- **D-19 (2026-09-07)** The Tier 0 index is a venue/repository index (§8), not a works index; `venue` and `repository` are record kinds; the OpenAlex loader reads snapshot part files from disk only (the operator syncs the public `data/sources/` snapshot); re3data is reached through DataCite identifiers rather than loaded directly.
- **D-18 (2026-09-07)** Phase 4 review resolutions: a merged record persists only redistributable provenance members; the `commercial` flag is part of a job's identity and cache hits are re-gated by R-8; memory caches are bounded; fuzzy dedup requires title, year and first author all present and equal; share-alike licences are not allow-listed (attribution at most), ISC/zlib/Unlicense are; identity schemes are only those built in or registered by adapters (a title like "AI:ML" is a title); DOI registration-agency routing is declared by adapters (`AGENCIES`) and the fallback chain comes from the registry's substitution group; any exception a lane raises is a capability fact.
- **D-17 (2026-09-07)** Phase 3 review resolutions: `raw` is the source's own object for the record (I-8), minus only CORE's `fullText` field (I-7); file bytes and full text never enter `jobs.result` (`router.redact_for_storage`) — they are delivered only on the inline path and discarded; Socrata portals must be vouched for by the discovery catalog before they are called (R-6); a response an adapter cannot read becomes a capability fact, not a job failure (R-10); call logging is guaranteed by construction (adapters cannot reach the network except through `base.Client`, and only the gateway's own factories build clients — both tested) rather than by a transport-level interceptor.
- **D-16 (2026-09-07)** Routing is derived, not written: domain lanes come from each seed row's `domains`, enrich lanes from each adapter's `ENRICHES`, resolve/fetch targets from each adapter's `SCHEMES`/`HOSTS`. §4's per-domain lists are the 2026-09-07 rendering of the seed; a new source is a seed row plus an adapter, never a router edit (I-2).
- **D-15 (2026-09-07)** Phase 1–2 review resolutions: broker state is keyed per source (one credential per source in the registry; revisit if a second credential is ever added); `jobs.result` is inline jsonb rather than a `result_ref`; BEA's 100 MB/min volume cap is not broker-enforced (the adapter requests single tables; the 100/min request cap is).
