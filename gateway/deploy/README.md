# Deploying the research gateway

Public code, private configuration (`PLAN.md` §10). Nothing here contains an
address, a token or a key; every deployment supplies its own through
`gateway.env` (Docker) or `~/.config/research-loops/gateway.env` (systemd).

## What a deployment needs

| Item | Where it comes from |
|---|---|
| PostgreSQL database with the `gateway` schema | `python3 -m research_gateway.registry.load --schema --load` |
| `RESEARCH_GATEWAY_DSN` | libpq URI; password via `PGPASSWORD`/`~/.pgpass` or the URI |
| `RESEARCH_GATEWAY_TOKENS` | `name=token,...` — one bearer token per client (loops, external MCP gateway, CLI) |
| Source secrets | `RESEARCH_GATEWAY_SECRET_<NAME>` variables, or `RESEARCH_GATEWAY_SECRETS=vault` plus `RESEARCH_GATEWAY_VAULT_ADDR/MOUNT/PREFIX/TOKEN_FILE/ALIASES` |
| Alerts (optional) | `RESEARCH_GATEWAY_NTFY_URL`/`_TOPIC` (+ username/password or token), or the secrets backend's `ntfy` entry |
| Contact e-mail | `RESEARCH_GATEWAY_CONTACT_EMAIL` — Crossref/Unpaywall polite pools and the User-Agent |
| OpenAlex sources snapshot (optional) | a directory of `part_*.gz` files synced from the public snapshot; loaded with `harvest.openalex_snapshot` |

## Docker host

```bash
cd gateway
cp deploy/gateway.env.example deploy/gateway.env      # then fill it in from the table above
cp sources.example.toml sources.local.toml            # contact email, listen address
docker compose -f deploy/docker-compose.gateway.yml build
docker compose -f deploy/docker-compose.gateway.yml up -d
curl -s http://127.0.0.1:8765/v1/health
docker compose -f deploy/docker-compose.gateway.yml --profile harvest run --rm harvest datacite
```

## Linux host from a checkout (systemd user units)

```bash
python3 -m venv ~/.venvs/research-gateway && ~/.venvs/research-gateway/bin/pip install 'psycopg[binary]'
mkdir -p ~/.config/systemd/user
# edit WorkingDirectory in the units if your checkout is not at ~/work/research-loops-public
cp deploy/research-gateway.service deploy/research-gateway-harvest.service deploy/research-gateway-harvest.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now research-gateway research-gateway-harvest.timer
systemctl --user status research-gateway
```

## Wiring the clients

- **Research loops (stdio MCP tool)** — add to the stations' MCP config and give
  those processes `RESEARCH_GATEWAY_URL` and `RESEARCH_GATEWAY_TOKEN`:
  `{"research": {"type": "stdio", "command": "python3", "args": ["-m", "research_gateway.clients.mcp_stdio"]}}`
  (run with the gateway package on `PYTHONPATH`, e.g. `cwd` = the `gateway/` directory).
- **External MCP gateway** — add the peer entry printed by
  `python3 -c 'from research_gateway.mcp.homelab_adapter import peer_entry; print(peer_entry("http://<host>:8765"))'`
  to that gateway's peer list, with the token in its own environment, and restart it.
- **Command line** — `RESEARCH_GATEWAY_URL=... RESEARCH_GATEWAY_TOKEN=... python3 -m research_gateway.clients.cli health`.

## Checks after deploying (PLAN.md §13 Phase 7)

1. `/v1/health` answers `{"ok": true, ...}`; `/v1/status` (with a token) shows the workers alive and the watcher passing.
2. Force a breaker (`curl` a 429-answering test source, or lower a policy) and confirm the ntfy message.
3. Run one research-loop iteration with the tool mounted; `SELECT client_id, source_id, count(*) FROM gateway.calls WHERE at > now() - interval '1 hour' GROUP BY 1, 2` shows only gateway-routed calls.
4. `python3 -m tests.regression.overlap_probe --expectations <private file> --live --sample 40` stays within tolerance.

Rollback: previous image or checkout; the schema only ever adds columns.
