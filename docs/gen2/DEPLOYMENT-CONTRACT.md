# Gen-2 deployment contract

The operator-facing specification of how gen-2 runs. It is a **contract, not a
description**: no compose file, image or volume in it exists yet. Task 0c writes
the specification; Phase 1 and later build against it, and Astra's Gate A checks
each phase diff against this file the same way it checks `BOUNDARIES.md`. Where
this file and a later deployment disagree, one of them changes through the
charter's amendment path.

**Trace.** Flow architecture (`gen2-flow-architecture-20260924.md`, amended
2026-09-25): §0 actor roster; §4.1–4.4 observability spine (one invocation ID,
dated capability facts, silence-is-never-success, typed holds); S8 publication
contract items 1–4; §5 "Jev question storage" (mounted versioned registry, a
restart not a rebuild). Design review
(`reviews/gen2-design-astra-review-20260922.md`): §6 container isolation and
mounted bundles (the paragraph this file's baked/mounted table implements); §5
(a new `ControlBackend` adapter is engine code, so an image change); §9 gateway
repairs; §10 release gate 9 (restart/replacement preserves configuration pins,
auth-volume access and permissions). Design review task
(`reviews/gen2-design-review-task-20260922.md`) fixed constraint: "container;
engine baked, config/prompts/contracts/thresholds/auth mounted;
restart-not-rebuild for everything except engine bugs".
`docs/gen2/BOUNDARIES.md`: *Router*, *Station supervisor*, *Gateway*,
*Projector / publication*, *Operator*. `docs/gen2/INVARIANTS.md`: H-2
(capability facts, the vault-outage fixture), H-4, P-1–P-4, RG-3, RG-4, G-10
(protocol data vs execution policy), B-2 (no gen-2 module imports the gateway's
internals). `docs/gen2/ENVIRONMENT.md` covers the *build* environment; this file
covers the *runtime* one.

**Hard boundary against gen-1.** Nothing here touches the running gen-1
deployment. On this host (observed 2026-09-25) `research-gateway.service` is
active and listening on `127.0.0.1:8765`, with PostgreSQL on `5432`. The gen-2
stack gets its own gateway container, its own database, and its own host ports
(below). One gateway service per database is a gen-1 decision (`D-25`) that
holds here too: pointing a gen-2 container at gen-1's database or its port is a
deployment error, not a configuration choice.

---

## 1. The stack

Five gen-2 containers and four referenced external services. "Referenced" means
this stack does not create, own, upgrade or back them up; it connects to them
and reports a dated capability fact when it cannot.

| Service | What it is | Image | Referenced or ours |
|---|---|---|---|
| `engine` | Router (sole writer, owns the control store) + station supervisor + composition root. The operator command service (CLI/HTTP/MCP behind one service, design review §10) is exposed from here. | baked gen-2 image | ours |
| `gateway` | A second instance of the federated research gateway (`gateway/research_gateway`), the only door to external research sources. Run as a service and reached over HTTP; never imported (B-2). | the gateway's own image (`gateway/deploy/Dockerfile`), unmodified | ours (separate instance from gen-1's) |
| `projector` | Outbox consumer: publishes approved generations to Neo4j and Qdrant, and hands approved bundles to the enabled export sinks (`docs/gen2/EXPORT-SINKS.md`). | baked gen-2 image, same image as `engine`, different entrypoint | ours |
| `tier0` | The local NLI claim-vs-span screen. Optional: with it absent the engine records a dated capability fact and verification proceeds without the screen (the screen never gated a load-bearing claim anyway — BOUNDARIES.md *Tier-0 checker*). | its own pinned image | ours |
| `gateway-db` | PostgreSQL for the gen-2 gateway instance only. | `postgres` pinned | ours |
| Neo4j | Physical publication sink. | — | referenced |
| Qdrant | Physical publication sink. | — | referenced |
| Vault | Secrets backend, when the vault backend is selected. | — | referenced |
| Decision provider (Jev API, LLM fallback) | Reached over the network by `gen2/decision`. **Not a build or run dependency**: the charter requires the engine to run and be testable with the decision layer disabled. | — | referenced |

The control store (`gen2/store`, SQLite) is **not** a service. It is a file on a
mounted volume that only the `engine` container opens, because the router is the
sole writer (BOUNDARIES.md *Router*). `projector` and `operator` transports
reach state only through the `ControlBackend` protocol inside `engine` — no
second process opens the SQLite file. A deployment that mounts the control
store into two containers has broken the sole-writer invariant no matter what
the code does.

### 1.1 Port map

Container ports are fixed by the images. Host ports are defaults chosen to
avoid what was already listening on this host on 2026-09-25 (8765, 8766, 5432,
6767, 8642, 8643, 8652, 11434, 18000, 18080); the operator confirms them at
deploy time rather than trusting this list.

| Service | Container port | Default host port | Exposure | Protocol |
|---|---|---|---|---|
| `engine` operator service | 8770 | 127.0.0.1:8770 | loopback only | HTTP + `POST /mcp` (stateless MCP over HTTP, one JSON-RPC message per request — the gateway's proven shape) |
| `engine` health | 8770 | — | in-network | `GET /v1/health`, no token |
| `gateway` | 8765 | 127.0.0.1:8771 | loopback only | HTTP + `POST /mcp` |
| `projector` health | 8772 | — | in-network only | `GET /v1/health`, no token |
| `tier0` | 8773 | — | in-network only | HTTP |
| `gateway-db` | 5432 | not published | in-network only | PostgreSQL |
| Neo4j | 7687 (bolt) | — | external service | bolt |
| Qdrant | 6333 | — | external service | HTTP |
| Vault | 8200 | — | external service | HTTPS |

Nothing in this stack binds `0.0.0.0` on the host. The operator service carries
operator authority; it is loopback (or a private network) plus a bearer token,
never a published port.

### 1.2 Healthchecks

Every container declares a healthcheck, and every healthcheck answers about the
thing that container owns — not about a dependency.

| Service | Check | Healthy means | Explicitly **not** part of the check |
|---|---|---|---|
| `engine` | `GET /v1/health`: control store opens through the compatibility gate (`gen2/store/compat.py`), the schema matches `schema.sql` exactly, the last scheduler tick is within its interval | the router can commit | whether any provider, sink or the gateway is reachable |
| `gateway` | the gateway image's own healthcheck (`GET /v1/health`, no token) | the service answers | whether any source lane is working |
| `projector` | `GET /v1/health`: the outbox can be read through the `ControlBackend` and the worker's last loop is within its interval | the consumer is alive | whether Neo4j, Qdrant or an export sink accepted anything |
| `tier0` | model loaded, one fixed probe pair classified | the screen answers | — |
| `gateway-db` | `pg_isready` | — | — |

**A dependency's failure is a capability fact, never an unhealthy container**
(flow §4.2; INVARIANTS H-2, RG-3). A failing Vault, a dead Qdrant, a 429 from a
provider and an unreachable Jev endpoint all leave their container healthy and
raise a dated capability fact with `since`, last success, and affected lanes —
which alerts on the *transition*. Restarting a container because a remote
service is down destroys the `since` timestamp, which is the one piece of
information the 2026-09-21..24 vault outage proved is needed: three days of
degradation were reported as "no key configured".

---

## 2. Baked versus mounted

The rule the table implements: **restart, not rebuild, for everything except
engine code.** Anything executable is baked. Anything the operator decides is
mounted. There is exactly one exception, `wrappers/`, and it is an explicit,
documented operator act (§4).

| Item | Baked / mounted | Change takes effect by | Why |
|---|---|---|---|
| Gen-2 engine code (`gen2/`), the composition root, the DDL, every validator | **baked** | rebuild + release | Engine bugs and migrations are image releases (design review §6). |
| `gen2/store/schema.sql` and its migrations | **baked** | rebuild + release, then a migration run | A store migration is an engine change with a data step. |
| Schema files (`gen2/schema/*.schema.json`) and the router's validation boundary | **baked** | rebuild + release | The validators are code's contract with itself; a mounted schema would let a config edit widen what the router accepts. |
| `ControlBackend` implementations (a second store backend) | **baked** | rebuild + release | "A new backend adapter is engine code and therefore an image change, not just a mounted DSN" — design review §5. |
| Decision-provider adapters, tier-0 client, gateway client, export-sink adapters | **baked** | rebuild + release | Executable adapters require an image release (design review §6). Bespoke export sinks are reviewed code, not operator config (`EXPORT-SINKS.md` §5). |
| Pinned provider CLIs used to launch model invocations (the model vendors' own command-line tools, at pinned versions) | **baked** | rebuild + release | An agent must never be able to introduce an executable. Pinning them in the image makes the set of runnable binaries a reviewed property of the release. |
| `stations.yaml` (station roster, per-station model assignment, concurrency) | **mounted**, read-only | restart | Operator's fleet shape; no code depends on its contents being any particular value. |
| Fleet policy / execution policy bundle (retry ceilings, heartbeats, timeouts, deadlines, checkpoint cadence, budgets) | **mounted**, read-only | restart | G-10: execution policy is data with a different owner than the contract's scientific protocol. |
| Prompts | **mounted**, read-only | restart | Prompt changes are evaluated on retained cases (design review §6), not shipped with code. |
| Jev question registry (question IDs, content, versions, hashes) | **mounted**, read-only | restart | Flow §5: rewording is a *visible calibration event* and a restart, not a rebuild. |
| Decision thresholds and action-policy versions | **mounted**, read-only | restart | Same reason; they pin to question versions. |
| Approved contracts, evidence, dossiers, receipts (the control store) | **mounted**, read-write, `engine` only | live | The record of scientific work; never in an image. |
| Logs, spool, staged artifacts | **mounted**, read-write | live | Content-addressed staging under trusted station code. |
| Secrets (`.env` file, or Vault token files) | **mounted**, read-only, `0400` service-owned | restart (env) / ≤15 min (Vault cache) | §3. |
| Per-provider agent auth homes | **mounted**, read-write, one volume per provider | live | §4. |
| `wrappers/` | **mounted**, read-only, **operator-owned and explicitly operator-trusted** | restart | §4. The one place a non-image executable enters. |
| Export-sink enablement and per-topic export options | **mounted**, read-only | restart | `EXPORT-SINKS.md` §4; connection strings are secrets, not config. |

**Versioned bundles, pinned in flight.** Every mounted configuration set is
activated as a *versioned bundle*: it is validated on load, given a bundle
identity, and recorded. In-flight work keeps the bundle it was admitted under
(design review §6; INVARIANTS C-12 already pins the config bundle on every
commit receipt). A mounted edit therefore never retroactively changes work
already running — it applies to the next admission. A bundle that fails
validation is refused with a dated capability fact; the previous bundle stays
active. The engine does not start on an invalid bundle.

**What "restart" means here.** Stop the container, start it with the same
volumes. Release gate 9 (design review §10) is the test: restart and
*replacement* must preserve configuration pins, auth-volume access and
permissions, and status must still answer why every waiting item waits. That
gate is a Phase 1+ obligation; this file states what it will be run against.

---

## 3. Secrets

Two backends, exactly as the gateway already implements
(`gateway/research_gateway/core/secrets.py`), extended to the engine's own
secrets. Logical secret names live in the registry and in `deploy/gen2.env.example`;
values never do.

### 3.1 The `env` backend

One mounted file, `deploy/gen2.env`, gitignored, `0400`, owned by the service
user, passed to the containers that need it. Every name in it, with its
grouping and comments, is generated: `deploy/gen2.env.example` (see
`docs/gen2/SOURCE-CATALOG.md`). Source keys are
`RESEARCH_GATEWAY_SECRET_<NAME>[_<FIELD>]` — the gateway's own scheme, because
the gen-2 stack runs the gateway unmodified.

### 3.2 The `vault` backend

`RESEARCH_GATEWAY_SECRETS=vault` selects Vault for the gateway; the engine's
equivalent is `GEN2_SECRETS=vault`. Settings, never values:

| Setting | Meaning |
|---|---|
| `…_VAULT_ADDR` | Vault address. Empty address ⇒ the backend reads nothing (and that is a failure, §3.3). |
| `…_VAULT_TOKEN_FILE` | **Required explicitly for every service.** See below. |
| `…_VAULT_MOUNT` | KV v2 mount (gateway default `secret`). |
| `…_VAULT_PREFIX` | Path prefix (gateway default `services`). |
| `…_VAULT_ALIASES` | `logical=vault-name,…` for deployments whose Vault paths do not match the registry's logical names. |

Reads are `GET {addr}/v1/{mount}/data/{prefix}/{name}`; redirects are refused so
a token is never re-sent elsewhere; successful reads cache 15 minutes and
failures 1 minute, so a rotated key lands without a restart.

### 3.3 The two outage-hardening rules

These are not recommendations. They are the two rules the 2026-09-21..24 vault
outage produced, and both are testable.

**Rule 1 — every service names its own token file explicitly.** The gateway's
`VaultBackend` falls back to `os.path.expanduser("~/.vault-token")` when
`RESEARCH_GATEWAY_VAULT_TOKEN_FILE` is unset. In a container, `HOME` is whatever
the image and the runtime happened to set, so the fallback resolves somewhere
nobody chose, and a missing token file is indistinguishable from a missing key.
Every service in this stack therefore sets its own token-file path explicitly —
`RESEARCH_GATEWAY_VAULT_TOKEN_FILE` for the gateway, `GEN2_VAULT_TOKEN_FILE` for
the engine and projector — each mounted read-only from a distinct path, each
`0400`. A service whose backend is `vault` and whose token-file variable is
unset **refuses to start**; it does not fall back to a home directory. That
refusal is a startup error with the variable named, not a silent degradation.

**Rule 2 — a failed secrets read is a dated `secrets backend failing`
capability fact, never "no key configured".** The failure surface is exact:
`VaultBackend._read` catches `OSError`/`ValueError` and returns `{}`, and `get`
then returns `None` — which is the same value a source with no key configured
produces. Everything downstream reads "no key". Under this contract the
distinction is carried, not collapsed:

- A read that *fails* (transport error, non-200, 403, unreadable token file,
  unparseable payload) records a capability fact
  `capability = secrets.<backend>`, `state = failing`, `since` = first
  observation, `last_success_at`, and the affected lanes, and alerts on the
  transition. `gen2/store/schema.sql` already holds these rows
  (`capability_facts`) and already models a failed secrets read as a search
  observation's `error_class = 'secrets_backend_failing'`.
- A read that *succeeds and finds nothing* is "no secret configured for this
  name" — a different, non-alarming fact.
- Affected lanes are never reported as `searched_empty`, and never contribute a
  zero to any count or denominator (INVARIANTS RG-4, RG-U).
- Under this design the vault outage reads, on day one:
  `secrets backend failing since Sep 21 19:47 (403); 9 lanes degraded`.

A backend that cannot tell those two cases apart is not admissible as a secrets
backend in this stack.

---

## 4. Custom model CLIs, auth homes, and the `wrappers/` volume

Model invocations are launched by the station supervisor as child processes of
pinned provider CLIs. Three separate concerns, deliberately not merged:

**Pinned CLIs are baked.** The provider command-line tools live in the image at
pinned versions. The set of executables a station can launch is therefore a
property of a reviewed release.

**Auth homes are persistent per-provider volumes.** Each provider gets one
named, access-controlled volume holding only that provider's credential state,
mounted at a fixed path, owned by the service user with stable uid/gid, `0700`.
They survive restart and container replacement (design review §6: "persistent,
access-controlled provider-auth volumes use stable ownership and survive
restart/replacement"). No auth home is mounted into a job that does not need
that provider. No job ever receives the control store, the operator token, or
broad gateway credentials.

*Testing requirement (release gate 9).* Before Phase 1 is accepted, the
deployment must demonstrate, with the pinned runner: (a) a credential **refresh**
inside a live auth volume is picked up without a rebuild; (b) container
**replacement** preserves auth-volume access and permissions; (c) **concurrent**
use of one auth home by two simultaneous invocations behaves as specified rather
than corrupting the credential state; (d) a **revoked or expired** credential
produces a dated capability fact and a typed capability hold, not a silent
zero-result pass. Untested auth-volume refresh is how a fleet discovers on a
Monday that every station has been unauthenticated since Friday.

**`wrappers/` is the one operator-trusted executable mount.** Some providers
need a small shell wrapper the image cannot ship (a site-specific login shim, a
locally patched invocation). `wrappers/` is mounted read-only into the
supervisor's job environment, and it is **operator-owned and explicitly
operator-trusted**:

- Only the operator writes it, on the host, outside any container. No engine
  path, no agent, and no mounted-config reload can create, modify or choose a
  file in it.
- Mounting it is **an operator act, recorded as one**: the deployment records
  which wrapper files were present, with their content hashes, in the
  configuration bundle identity, so a receipt says which wrapper set the work
  ran under.
- It is read-only in every container, and it is never writable by the same
  volume a job can write to.
- **Agents can never introduce executables.** An agent-produced file is staged
  content-addressed in the protected spool, is never placed on an executable
  path, and is never `exec`'d (BOUNDARIES.md *Router*: never execute
  agent-supplied code; `gen2/boundaries.toml` additionally refuses
  `eval`/`exec`/`compile`/`__import__` statically).
- **Engine adapters stay image-baked.** `wrappers/` is not an extension point
  for the engine. A new execution adapter, decision provider, sink or
  `ControlBackend` is engine code and needs an image release (design review §5,
  §6). A wrapper that starts making decisions has become engine code in the
  wrong place, and Gate A should say so.

**Per-job writable workspaces and env allowlists.** Every invocation gets a
fresh writable workspace, its own path, discarded after its results are staged;
approved inputs are mounted read-only. The job's environment is an
**allowlist**, not the engine's environment minus some names: a variable reaches
a job only if the station's policy lists it. Nothing carrying operator
authority, the control store path, or a broad gateway token is on any job's
allowlist. The invocation ID is passed in, and it is the same one the whole
chain carries (flow §4.1: router → station → delegate → gateway lane → decision
layer → commit receipt).

---

## 5. Control-store backup, restore, and the restore drill

The control store is the record of scientific work: contracts, approvals,
receipts, ordinals, dossiers, holds. Losing it loses the authority history, and
restoring it carelessly loses operator decisions made after the backup.

**Volumes.** The control store lives on its own named volume, separate from
logs and spool. Backups go to a second volume the engine mounts read-only for
nothing and the backup job mounts read-write; a backup destination the engine
can write to is not a backup.

**Taking a backup.** SQLite is backed up with a consistent-snapshot mechanism
(the online backup API or `VACUUM INTO`), never by copying the file under a live
writer. Each backup is dated, and its SHA-256 recorded alongside it. The spool's
content-addressed artifacts are backed up separately; a control store whose
`artifacts` rows point at a spool that was not restored to the same generation
is an incomplete restore, and the drill must show that being detected.

**Restoring is not a rollback.** This is the design review's ruling (§10) and it
matters more than the mechanics: *after new writes have occurred, rollback needs
state reconciliation or repair-forward, not restoring a stale database over new
operator decisions.* Restoring a backup over a store that has accepted operator
decisions since is data loss dressed as recovery. Keeping the old store
read-only aids forensics; it is not a rollback mechanism.

**The restore drill** (documented, rehearsed, and re-rehearsed whenever the DDL
changes — never first attempted during an incident):

1. Restore the dated backup into a **scratch** volume, never over the live one.
2. Open it through `gen2/store` `open_store`, which runs the SQLite
   compatibility gate and admits the store only if its schema is exactly
   `schema.sql`. A restored store that fails the gate is a failed restore, not a
   store to be repaired by hand.
3. Reconcile counts and authority history against the last known-good report:
   topics, contract revisions and their approvals, receipts and ordinals (dense,
   one per invocation), dossiers, open holds, publication generations per sink.
   Record what did not reconcile. This is the same reconciliation Phase 4's
   import owes (INVARIANTS §12).
4. Restore the matching spool generation and verify that every `artifacts`
   content hash the restored rows reference is present. Missing artifacts are
   reported, never silently tolerated.
5. Confirm the operator status view answers "why is every waiting item waiting"
   on the restored store (release gate 9 / H-4).
6. Record the drill: date, backup identity and hash, what reconciled, what did
   not, and how long it took. An undated, unrecorded drill is not evidence the
   restore works.

**Three facts stay separate during recovery** (S8 item 4, INVARIANTS P-4):
historical scientific completion at a dossier revision, current publication
delivery, and surveillance currency as of a time. A restore that cannot
re-deliver to a sink leaves publication *partial* and raises a capability
incident; it does not undo completion and does not stop surveillance.

---

## 6. What this file does not settle

- **No compose file, image or volume is committed by task 0c.** This is the
  specification they are built against. The `engine`, `projector` and `tier0`
  images do not exist yet; the gen-2 `gateway` image is the existing gateway's,
  unchanged.
- **Port defaults are a starting point**, chosen against one observation of one
  host on 2026-09-25. The operator confirms them.
- **Migration and cutover** (freeze, import, reconcile, single-writer cutover)
  are Phase 4 and live in the migration contract, not here.
- **Nothing here is evidence that a mechanism works.** Every rule above is a
  requirement on a deployment that does not exist yet; the release gates named
  in §2, §4 and §5 are where it becomes evidence.
