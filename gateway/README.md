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

Phase 1 (registry, schema, seed, documentation) — see `PLAN.md` §13 for the
phase list and acceptance checks. Nothing serves traffic yet.

## Layout

```
gateway/
  PLAN.md                    the build contract
  docs/                      SOURCES, ARCHITECTURE, OPERATIONS, PUBLIC-PRIVATE, LICENSING
  research_gateway/          Python 3.12 package (standard library + psycopg)
    registry/                schema.sql, seed/sources.toml, load.py, docs.py
  tests/                     unittest suite (python -m unittest discover -s tests -t .)
  sources.example.toml       deployment config example (no secrets)
```

## Quick start (Phase 1)

```bash
cd gateway
python3 -m unittest discover -s tests -t .            # validate seed, docs, limits
python3 -m research_gateway.registry.load --dry-run    # seed summary
python3 -m research_gateway.registry.docs --check      # docs match the seed
export RESEARCH_GATEWAY_DSN='postgresql://user:pass@host:5432/research_loops'
python3 -m research_gateway.registry.load --schema --load
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
