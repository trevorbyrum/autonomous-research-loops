# Architecture

The gateway is one service with five request types, a registry that drives
routing, a Postgres-backed job queue that owns every rate limit, and two front
doors. Full detail and the rules each part must satisfy are in `PLAN.md`
(§2 data model, §4 routing, §5 queue and broker, §6 cache and dedup).

## Five request types, five kinds of source

The sources are not all "search engines", so the gateway does not expose one
search call:

| Request | Meaning | Sources that answer it |
|---|---|---|
| `find` | discovery by keywords and filters | article indexes, dataset indexes, the local index |
| `resolve` | look up by a permanent identifier (DOI, ISSN, dataset id) | the registry that issued the identifier, then fallbacks |
| `enrich` | citations, open-access location, full text — opt-in per request | citation graph, resolvers |
| `fetch` | retrieve a file from a registry-known host | dataset repositories, document stores |
| `data` | a statistical series or table, by source-native identifier | statistical APIs, one source per request |

## Routing

Rules R-1 to R-10 in `PLAN.md` §4. The shape: a **base lane** per kind
(Crossref plus the local OpenAlex snapshot plus DOAJ for articles; DataCite
for datasets), **domain lanes** that add sources tagged for the request's
domain (never suppressing a base lane), a **catch-all domain `other`** that
adds every domain lane so mis-tagging never loses coverage, and the
**commercial filter** that removes any source whose verdict is not `allow`
(or `per-item` when the caller opts in). Identifier lookups go to the
registry that issued the identifier (Crossref vs DataCite, decided by a cached
registration-agency lookup), with a substitution group as fallback.

## Queue and broker

A Postgres jobs table (`SELECT … FOR UPDATE SKIP LOCKED`) fed by both front
doors; worker threads in the gateway process, each handing its job a metered
client bound to the job id so every outbound call lands in the call log;
sliding windows per source (second/minute/hour) and per-UTC-day budgets seeded
from the registry's rate policy; `Retry-After` honoured, otherwise a 10→80 s
backoff; a circuit breaker per source that opens after repeated limit errors
and routes to the substitution group. Nothing is dispatched without a rate
policy row. Without a database the same client runs inline.

## Records, cache, dedup

A canonical record per identity, with each contributing source's raw payload
kept for provenance (normalisation is lossy). Cache keyed by identity with a
per-class TTL (metadata seven days, searches one hour, anything with a
restricted member one hour); sources whose terms forbid redistribution are cached in memory
only (bounded, at most an hour) and never persisted or exported — a merged
record persists only its redistributable members. Dedup by normalised
identifier, then exact identity, then fuzzy title with the same year and first
author (all three present), greedily in lane order. Cache hits are re-checked
against the commercial rule before they answer.

## Local index (Tier 0)

Registries with bulk routes (the OpenAlex sources snapshot, Crossref journals,
DOAJ journals, DataCite repositories — re3data arrives through DataCite's
identifiers) are loaded on a schedule into a Postgres full-text index of
venues and repositories. `find` consults the index first and live lanes for
freshness and the long tail. Embedding and reranking tiers are optional later
additions and degrade to this tier — no GPU or vector database is required.

## Front doors

An HTTP API with bearer-token clients (`/v1/*`); a stdio MCP server mounted
by the research loops as a local tool, which forwards to that API; and a
stateless MCP-over-HTTP endpoint (`POST /mcp`) that an external MCP gateway
registers as a peer, serving the same tools in-process. All three go through
the same broker and call log, so all three share the same limits. File bytes
and full text are delivered inline and never stored in a job result.

Routing itself is derived from data, not written into the router: base and
domain lanes from the seed's `base_for` and `domains`, enrichment lanes from
each adapter's `ENRICHES`, resolve/fetch targets from `SCHEMES`/`HOSTS`, DOI
primaries from `AGENCIES`. A new source is a seed row plus an adapter file.
