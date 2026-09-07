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
doors; worker coroutines in the gateway process; one token bucket per source
per credential seeded from the registry's rate policy; daily budgets;
`Retry-After` honoured; a circuit breaker per source that opens after repeated
limit errors and routes to the substitution group. Nothing is dispatched
without a rate policy row.

## Records, cache, dedup

A canonical record per identity, with each contributing source's raw payload
kept for provenance (normalisation is lossy). Cache keyed by identity with a
per-source TTL; sources whose terms forbid redistribution are cached in memory
only and never persisted or exported. Dedup by normalised identifier, then
exact identity, then fuzzy title + year + first author. Paging uses stateless
resumption tokens.

## Local index (Tier 0)

Registries with bulk routes (OpenAlex sources snapshot, Crossref journals,
DOAJ, DataCite repositories, re3data) are loaded on a schedule into a Postgres
full-text index. `find` consults the index first and live lanes for freshness
and the long tail. Embedding and reranking tiers are optional later additions
and degrade to this tier — no GPU or vector database is required.

## Front doors

An HTTP API with bearer-token clients; a stdio MCP client mounted by the
research loops as a local tool; an MCP adapter that registers the same five
tools on an external MCP gateway. All three call the same service, so all
three share the same limits.
