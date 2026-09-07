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

## Running the gateway

```bash
export RESEARCH_GATEWAY_DSN='postgresql://gateway@db-host:5432/research_loops'   # omit for inline mode (no queue)
export RESEARCH_GATEWAY_TOKENS='loops=<token>,mcp=<token>'                      # one bearer token per client
python3 -m research_gateway.api.http                                             # listens on [gateway].listen
```

With a database the gateway runs **queued mode**: requests become jobs
(identical in-flight requests collapse, priorities apply, worker threads claim
with `SKIP LOCKED`) and the HTTP call waits for the result (or returns a job id
with `?async=1`). Without one it runs **inline mode**: the same metered client,
the same limits, no queue — enough for a laptop with the seed and environment
secrets, but the call log then lives only in the process, so a deployment
always has a database. File downloads and full text are always served inline
and never stored (`PLAN.md` D-17); with a database those calls are logged too,
with the client's id and no job id. Every call-log row names the client that
asked; a client can read only its own jobs.

Client tokens come from `RESEARCH_GATEWAY_TOKENS` or, with the vault backend,
from the secret `research_gateway`, field `tokens`, in the same
`name=token,name=token` form. The gateway refuses to start without any.

Routes: `GET /v1/health` (no token), `GET /v1/status`, `GET /v1/jobs/{id}`,
`POST /v1/{find|resolve|enrich|fetch|data}` with a JSON body, and `POST /mcp`
(stateless MCP over HTTP, one JSON-RPC message per request).

## Mounting the tools

- **Research loops / any MCP host over stdio** — add to the station's MCP
  config, with `RESEARCH_GATEWAY_URL` and `RESEARCH_GATEWAY_TOKEN` (or
  `RESEARCH_GATEWAY_TOKEN_FILE`) in that process's environment:

  ```json
  {"research": {"type": "stdio", "command": "python3", "args": ["-m", "research_gateway.clients.mcp_stdio"]}}
  ```

  Tools: `research_find`, `research_resolve`, `research_enrich`,
  `research_fetch`, `research_data`, `research_status`. When the gateway is
  down every tool answers `capability_fact: gateway_unavailable`.
- **An external MCP gateway that consumes peer servers** — point it at
  `POST /mcp` with the bearer token; `python3 -c 'from research_gateway.mcp.homelab_adapter import peer_entry; print(peer_entry("http://host:8765"))'`
  prints the entry shape (the token is a `${VAR}` reference, never a value).
- **Command line** — `python3 -m research_gateway.clients.cli --help`.

## Verifying live access

`python3 -m research_gateway.smoke --live` makes one minimal call per adapter
with the configured secrets and prints status, latency and any rate-limit
headers. Record what you observe in the seed row's `rate.evidence` before
flipping `verified`/`enabled`; the seed, not the smoke, is the registry.

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
Alerts go to an ntfy topic (`RESEARCH_GATEWAY_NTFY_URL`/`_TOPIC`, or the
secrets backend's `ntfy` entry); each (source, kind) fires at most once an
hour; the last ten are listed on `/v1/status`. Without ntfy settings the
gateway stays silent and `/v1/status` says so.
Retention for `gateway.calls` is a deployment setting (default 180 days).

## Adding a source

See `README.md` — seed row with evidence, adapter with a fixture test,
regenerate docs, run tests. Sources without an API, or whose terms have not
been read, are documented but not scheduled.
