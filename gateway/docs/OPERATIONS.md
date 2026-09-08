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

Concurrency knobs (Phase 9·2 — each has a serial rollback):

- `RESEARCH_GATEWAY_LANE_CONCURRENCY` (default 4, **gateway process**) — a find
  plan's base+domain lanes run through a bounded pool; results merge in plan
  order, so the answer is byte-identical to serial execution. `1` restores the
  serial loop. Only find lanes overlap: resolve/enrich/fetch/data/catalog plans
  are fallback chains and stay serial.
- `RESEARCH_GATEWAY_LANE_TOTAL` (default 16, gateway process) — aggregate bound
  on lane dispatches in flight across ALL concurrent requests, the inline path
  (which bypasses the worker pool) included. Read once at first use.
- `RESEARCH_GATEWAY_BATCH_CONCURRENCY` (default 5, **station MCP process**) —
  parallel `research_batch` entries in the stdio client. Setting the gateway's
  lane knobs does not configure this one; it lives in the station's environment.

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

## Maintenance window, retention, snapshot refresh (Phase 8f)

- **Harvest runs in an exclusive window.** The loaders refuse while a service answers
  on the gateway URL (I-1). `deploy/research-gateway-maintenance.sh` is the sanctioned
  window: it stops the service unit, runs every registry loader, and ALWAYS restores
  the service's prior state (a failed harvest never leaves the gateway down). The
  monthly `research-gateway-harvest.timer` invokes it. A completed loader stamps
  `gateway.meta` (`harvest:<loader>`), surfaced under `/v1/status` `harvest` — partial
  batch commits make "last row updated" insufficient evidence of a completed refresh.
- **Quarterly OpenAlex snapshot refresh.** Sync the public snapshot's `data/sources/`
  part files into `private/openalex-sources/` (the operator syncs; the loader reads
  disk only, D-19), then run the maintenance window with the snapshot included:
  `RESEARCH_GATEWAY_SNAPSHOT_DIR=private/openalex-sources bash
  deploy/research-gateway-maintenance.sh` (or standalone inside a window:
  `python3 -m research_gateway.harvest.openalex_snapshot private/openalex-sources`).
  A completed load stamps `gateway.meta` like every other loader. ISSN twins consolidate only on a
  FULL rebuild (delete venue records, reload all loaders) — see D-26.
- **Catalogue reload vs. deployment switches.** `registry/load.py --load` updates the
  catalogue and PRESERVES each existing row's deployed `enabled` flag; pass
  `--seed-operational` only to deliberately reassert the seed's switches (fresh
  deploy or reset). The running service snapshots sources and rate policies at
  startup: any registry or policy change needs a service restart to take effect.
- **Retention.** The watcher enforces: call log 180 days
  (`RESEARCH_GATEWAY_CALLS_RETENTION_DAYS`), terminal jobs 30 days
  (`RESEARCH_GATEWAY_JOBS_RETENTION_DAYS`), and expired FETCHED cache records 30 days
  past `last_seen` (`RESEARCH_GATEWAY_RECORDS_RETENTION_DAYS`) — harvested
  venue/repository rows are index data and are never retention-deleted. Service
  stdout/stderr goes to the journal: bound it with `SystemMaxUse=` in journald.conf
  or a `LogRateLimit`/`StandardOutput=append:` file with logrotate.

## Token rotation (two lifecycles, one procedure)

Source API keys and gateway client tokens rotate differently — rotate BOTH sides
deliberately:

1. **Source keys** (Vault `services/<source>`): write the new key in Vault; the
   gateway's Vault cache expires within 15 minutes (`secrets.py`), no restart needed.
   A 401 forces one immediate refetch.
2. **Gateway client tokens** (Vault `services/research_gateway`, field `tokens`):
   write the new `name=token` list in Vault, then restart the service (tokens load at
   startup only), then update every client that holds the old value: the loops
   wrapper (`~/bin/research-loops-research-mcp` fetches per launch — next iteration
   picks it up), the homelab peer entry's hydrated environment (restart that
   gateway), and any CLI environment.

## Backup and restore

The evidence of record lives in the topics; the gateway schema is still worth a
backup: the call log is the budget/audit history and the records/index tables are
days of harvest work. `deploy/backup-gateway.sh` runs
`pg_dump --schema=gateway --format=custom` to a dated file (default
`private/backups/`). Restore with
`pg_restore --schema=gateway --clean --if-exists -d "$DSN" <file>` — stop the
service first (one service per database, D-25), and rehearse the restore against a
scratch database before trusting it.
