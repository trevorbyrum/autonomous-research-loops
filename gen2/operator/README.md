# Gen-2 operator surface — one command service (task 1e)

The operator's commands and status, behind one service (`service.py`, design review §10: "CLI/MCP/API operations behind one command service"). The engine's HTTP listener (`gen2/app/engine.py`) carries it, and the CLI (`gen2/app/cli.py`) is a client of the same routes; neither decides anything. Every command is one of the router's existing operations, called through `core.control.OperatorBackend`: this module imports only `core`, holds no store and has no write path of its own, and has no network capability (`gen2/boundaries.toml`; the transports are the composition root's).

| File | What it is |
|---|---|
| `auth.py` | Principals from the mounted secrets, and bearer-token authentication. |
| `service.py` | The routes, the checks in order, authorization per command class, and who acts. |
| `status.py` | Why every waiting item waits, composed from the router's status read and the station's incidents. |

## Principals (`auth.py`; DEPLOYMENT-CONTRACT.md §1.1, §3.1)

- Each `GEN2_OPERATOR_TOKENS` entry (`name=token`, comma-separated) is an operator named by its entry; `GEN2_SECRET_EXPORTER_TOKEN`, when set, is the principal `exporter`. `GEN2_SECRETS` must be `env` (vault waits for §3.4). The engine does not start without an operator token, with a token shorter than 16 characters or not visible ASCII, with a name twice, or with two principals sharing a token; no refusal names a token.
- A presented `Bearer` token is compared in constant time: its SHA-256 digest against every configured digest with `hmac.compare_digest`, all of them, no early exit. Tokens stay in `auth.py`: never logged, echoed, returned or stored.
- **Persistence (RG-9).** The principal set is the mount's, read at every start: a restart or a replacement with the same mount keeps each principal, its role and its permissions; a token rotated out of the mount stops authenticating at the next start. That is how an env token expires (DEPLOYMENT-CONTRACT.md §2: env secrets change by restart); env tokens carry no expiry of their own.

## Routes and checks (`service.py`)

`GET /v1/health`, `GET /v1/status[?topic=<topic_id>]`, `POST /v1/commands/<operation>`, and `POST /mcp` (below). In order — a missing or invalid token is refused before anything but the route is read:

1. `GET /v1/health` needs no token and answers `{"status": "ok"}` (the router can take its store's write lock now) or 503 `{"status": "unavailable"}`, nothing else. Of DEPLOYMENT-CONTRACT.md §1.2's definition, the compatibility gate and the schema-identity check run when the store is opened (`gen2/store/db.py`; the engine does not start otherwise); the last scheduler tick has no scheduler to report until Phase 2.
2. The bearer token names a principal, or 401 (the same reply for every failure). The body is not read, whatever length it declares.
3. The route is status or a command, or 404; the principal's role is the one it needs, or 403 (over MCP the tool is in the body, so this follows step 4).
4. The body: a declared length (411 without, 413 over 1 MiB), strict JSON (C-13: duplicate keys and non-finite numbers refused), an object; 400 otherwise.
5. Who acts is the principal's, never the request's: a body naming `operator_id`, `requested_by`, `closed_by` or `capability_id` is refused (400 `authority_in_request`), and the first three are set from the principal.
6. The router's operation answers (200), whatever it decided: `status` in its reply says what happened, a refusal included.

| Route (`<operation>`) | Role | Supplied from the principal | Router operation |
|---|---|---|---|
| `GET /v1/status` | operator | — | `status` (then `status.py`) |
| `apply_operator_decision` (decisions, hold clearance, amendment and reframe approval) | operator | `operator_id` = the operator's name | `apply_operator_decision` |
| `request_cancel` | operator | `requested_by` = `operator` | `request_cancel` |
| `requeue` | operator | `requested_by` = `operator` | `requeue` |
| `close_brief` | operator | `closed_by` = the operator's name | `close_brief` |
| `activate_config_bundle`, `version_brief`, `mark_brief_overdue`, `propose_amendment` | operator | — | the same |
| `ack_delivery` | exporter | — | `ack_delivery` |

**Authorization per class.** Privileged commands need an operator; the exporter's token authorizes delivery acknowledgement only (no operator command, status included), and an operator's token does not acknowledge a delivery. **Capability-bearing calls** (claim, `record_transition`, `record_observation`, `commit_outcome`, `reconcile`, `invocation_status`, a supervisor's cancellation) are not routes here: the supervisor makes them in the engine's own process under the invocation's capability, and no principal the deployment contract defines holds invocation authority. So an operator's token cannot drive an invocation (404), and a capability — never a bearer token here (401), never accepted in a command body (400) — cannot issue an operator command. The Phase 3 exporter, which will run under an invocation, adds its capability-bearing calls needing both its token and that capability.

**MCP** (`POST /mcp`; DEPLOYMENT-CONTRACT.md §1.1: stateless MCP over HTTP, one JSON-RPC message per request, the gateway's shape). The same token and checks; `initialize`, `ping`, `tools/list` (the tools the principal's role may call: for an operator, `status` and the operator commands; for the exporter, `ack_delivery`) and `tools/call`, which runs the same `_status`/`_command` the routes run, so it is a transport and not a second path. Any refusal — the role, who acts named, an unknown or capability-bearing tool, the router's own — is an in-band tool error (`isError`) carrying its reply. No dependency: JSON-RPC over the same listener.

**Logging.** One line per request — principal (`role:name`, or `-`), method, route, HTTP status, the reply's status — and nothing else: never a header, a token, a query or a body. The engine logs its principals at start as `role:name`.

## Status (`status.py`; INVARIANTS RG-9, H-4)

The router's `status` read (`gen2/router/status.py`) gives the committed rows in one snapshot and its own judgments of them now; the station's incidents come from `Supervisor.incidents()` (the jobs directory). Each topic and each live invocation carries `waiting`, a list of reasons, each read off a fact:

- **Topic**: its status's own (`brief_confirmation`, `scoping_report`, `scope_approval`, `contract_approval`, `claim`, `held`, `capability_blocked`, `stopped_for_resources`, `judgment`; an active topic's work is in its invocations, a completed or retired one waits for nothing); `paused`; each open `hold` (class, cause, owner, deadline, required authority, what clears it, whether its deadline passed); each `brief_awaiting_confirmation` (owner, review deadline, overdue); each `draft_awaiting_approval` an approval could still approve; each lane whose last work ended failed or cancelled: `requeue` (none yet), `retry_claim` (re-queued, not yet claimed) or `requeue_hold` (its exhausted budget's operator hold); `signals` pending; each open `review`; each `incident` of its ended work.
- **Invocation**: the next step of its state (`launch`, `start`, `end`, `commit`, `reconciliation` with its episode, since, and the episode's hold with owner and deadline); `launch_refused` (the router's launch-admission check now); `cancellation` (requested, by whom, not yet confirmed); `deadline_passed`; `lease_expired`; `amendment_pending` (its pins' standing and what superseded them — exactly when its commit would be refused as that); each `incident`, blocking or not — the collected end whose descendants were never confirmed ended stalls as `outcome_unknown_unresolved`, which needs the operator, and an exhausted retry budget is `retry_exhausted`.
- **Engine-wide**: every open incident (owner, deadline, its topic where known), the active config bundle and each bundle live work is pinned to, and the current capability facts (a refused config bundle's `config-bundle` fact included).

Reading status changes nothing: the router's read writes no row, audit events included, and the journals are only read (`test_operator_status.ReadOnlyTest`).

## Tests

All over real HTTP on loopback (`gen2/tests/operator_fixtures.py`: the engine over a durable store, the real spool and a jobs directory; raw-SQL read-backs):
- `test_operator_auth.py`: health; missing, wrong, malformed and rotated-out tokens refused before the body is read; the exporter's token on every operator command and status; an operator's token on delivery acknowledgement and on every capability-bearing call; a capability as a bearer and in a body; each field naming who acts; strict bodies; no token in any log, reply or header; the credential rules.
- `test_operator_commands.py`: each command applied and refused against the real store.
- `test_operator_status.py`: one of each waiting state the task names, each reason on its item with owner and deadline read back from the store; status changes nothing.
- `test_operator_mcp.py`: MCP needs the token, lists only the role's tools, and its tool calls are the routes' own commands, refusals included.
- `test_operator_restart.py`: a restart in process, and a replacement process driven by the CLI process, keep principals, permissions, pins and the waiting answers; a rotated token is refused; an engine without usable secrets does not start and prints no token; the CLI's exit codes.

## Not here, and structural limits

- **TLS** is not built: the listener is published on host loopback only. MCP is the stateless subset above (tools only: no resources, prompts, sessions or streaming).
- **Clearing a station incident** is `Supervisor.recover()`, not a router operation, and no route calls it: status shows the incident with its owner and deadline; the engine does not drive the supervisor until Phase 2's scheduler loop, where recovery is exposed.
- **Tokens live in the engine's environment.** A process running as the same OS user can read another's environment (`/proc/<pid>/environ`); agents get a scrubbed environment (`gen2/supervisor/jobshim.py`), but keeping them from the engine's process is OS-level isolation — another user or container — which is deployment's.
- **The router trusts the surface's names.** It records the `operator_id` and `closed_by` it is handed; it does not check a name against the principal set. What makes them authenticated is that only this surface reaches those operations across a process boundary (the composition root wires it; the boundary graph keeps the store the router's).
- **Status holds the write lock while it reads** (one consistent snapshot), so a large status delays writers for its duration. Supervisor incidents are read from the jobs directory beside that snapshot, not inside it.
- **Capability facts are shown, not pushed.** Status lists each current fact with its `since`; the facts are recorded on transitions (H-2), but no alert is sent anywhere: an alerting channel is Phase 3's (projections).
- **One thread owns the router** (`gen2/app/engine.py`): requests are answered one at a time, in arrival order; a request waits at most 60 s for its turn, then gets 500 (health: 503).
