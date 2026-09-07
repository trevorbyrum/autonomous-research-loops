# Operations

## Requirements

Python 3.12, PostgreSQL 14+ (a database the gateway can create the `gateway`
schema in), and the `psycopg` driver. No other runtime dependencies in Phase 1.

## Configuration

Copy `sources.example.toml` to `sources.local.toml` (gitignored) and set the
contact email, the listen address, and which seeded sources this deployment
enables. Secrets are never in files under version control:

- `RESEARCH_GATEWAY_DSN` — libpq URI for the database.
- `RESEARCH_GATEWAY_SECRET_<NAME>` — one variable per secret name listed in
  `docs/SOURCES.md` (for example `RESEARCH_GATEWAY_SECRET_FRED`). Two-part
  secrets use suffixes (`_OPENAIRE_CLIENT_ID` / `_OPENAIRE_CLIENT_SECRET`,
  `_KAGGLE_USERNAME` / `_KAGGLE_KEY`).
- Deployments that keep secrets in a vault set `secrets_backend = "vault"`
  and supply that backend's settings outside this repository.

## Registry

```bash
python3 -m research_gateway.registry.load --dry-run          # validate
python3 -m research_gateway.registry.load --schema --load    # create schema, mirror seed
python3 -m research_gateway.registry.docs --check            # committed docs match seed
```

Re-run `--load` after editing the seed; it upserts. A source is only
scheduled if it is `enabled` and its rate policy is `verified`.

## Obtaining keys

Per-source instructions are in `docs/SOURCES.md` under "How to get access".
Several U.S. federal APIs email a key that must be activated by clicking a
link in that email before it works (BEA, Census).

## Health, logs, alerts

Every outbound call is a row in `gateway.calls` (source, request type,
identity or query, status, latency, rate-limit headers, credits, cache hit,
result count, failure class). Alerts are raised — never automatic routing
changes — when a breaker opens, a daily budget passes 80 %, a source starts
failing authentication, a source that used to return results starts
returning none for the same query pattern, or the health endpoint fails.
Retention for `gateway.calls` is a deployment setting (default 180 days).

## Adding a source

See `README.md` — seed row with evidence, adapter with a fixture test,
regenerate docs, run tests. Sources without an API, or whose terms have not
been read, are documented but not scheduled.
