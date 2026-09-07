# Research Gateway

One metered, logged, licence-aware door to research sources for autonomous
research agents. Every query to an external research platform, dataset
registry, citation graph, or statistical API goes through this service, so
that:

- rate limits are honoured by construction (one process owns every limit);
- every call is logged with its outcome and rate-limit state;
- licence terms are enforced mechanically — personal research use is the
  baseline, and a single `commercial` flag removes any source whose terms
  don't allow it;
- overlapping platforms are not searched twice: each lane is scoped to what
  it uniquely contributes, with measured fallbacks.

The contract for the build is [`PLAN.md`](PLAN.md). The sources, their access
routes, key instructions, rate limits and licence verdicts are documented in
[`docs/SOURCES.md`](docs/SOURCES.md), generated from the registry seed.

## Status

Phases 1–7 built: registry and seed, queue and broker, 26 adapters with a live
smoke, router/cache/dedup/licence enforcement, HTTP + MCP front doors and the
CLI, the Tier 0 venue/repository index (310k records from four registries),
alerts, the regression replay and the deployment files (`deploy/`). Placing the
service and wiring the clients are operator steps — see `deploy/README.md`,
`PLAN.md` §13 for the acceptance checks and §16 for decisions.

## Layout

```
gateway/
  PLAN.md                    the build contract
  docs/                      SOURCES, ARCHITECTURE, OPERATIONS, PUBLIC-PRIVATE, LICENSING
  research_gateway/          Python 3.12 package (standard library + psycopg)
    registry/                schema.sql, seed/sources.toml, load.py, docs.py
    adapters/                one module per source; base.py is the only network path
    core/                    identity, secrets, broker, queue, call log, router, cache, dedup, licences
    api/http.py              HTTP front door (+ POST /mcp)
    clients/                 stdio MCP server for the loops, shared HTTP client, CLI
    mcp/homelab_adapter.py   in-process MCP dispatch + the peer entry for an external MCP gateway
    app.py                   the assembled process; smoke.py: one live call per adapter
  tests/                     unittest suite (python -m unittest discover -s tests -t .)
  sources.example.toml       deployment config example (no secrets)
```

## Quick start

```bash
cd gateway
python3 -m unittest discover -s tests -t .            # validate seed, docs, limits, routing, front doors
python3 -m research_gateway.registry.load --dry-run    # seed summary
python3 -m research_gateway.registry.docs --check      # docs match the seed
export RESEARCH_GATEWAY_DSN='postgresql://gateway@db-host:5432/research_loops'   # password via PGPASSWORD or ~/.pgpass
python3 -m research_gateway.registry.load --schema --load
export RESEARCH_GATEWAY_TOKENS='loops=<token>'
python3 -m research_gateway.api.http                   # serve; see docs/OPERATIONS.md for clients
python3 -m research_gateway.clients.cli resolve doi:10.1038/nature12373
```

## Adding a source

1. Add a `[[source]]` block to `research_gateway/registry/seed/sources.toml`
   with its kind, capabilities, rate limit **and the URL you read it from**,
   licence, commercial verdict **and its evidence**, and key instructions.
   Unknown terms are recorded as `unknown`, never guessed.
2. Add an adapter under `research_gateway/adapters/<id>.py` (from Phase 3 on)
   with a fixture-based test.
3. Regenerate the docs: `python3 -m research_gateway.registry.docs`.
4. Run the tests. A source with an unverified rate limit cannot be enabled.

## Rules this code lives by

No placeholders; no file over 1,500 lines; the simplest thing that works;
tests and logs ship with every module; an independent reviewer checks each
phase. See `PLAN.md` §0.
