# Gen-2 deployment contract

The operator-facing specification of how gen-2 runs. It is a **contract, not a
description**: when it was written no compose file, image or volume in it
existed (task 1f has since added the first engine slice, §6). Task 0c writes
the specification; Phase 1 and later build against it, and Astra's Gate A checks
each phase diff against this file the same way it checks `BOUNDARIES.md`. Where
this file and a later deployment disagree, one of them changes through the
charter's amendment path.

*Amended by operator ruling 2026-09-26: the stack is the engine, the research gateway and the
exporter, with their supporting containers. No database that receives exports
is part of it or named in it; each connects through the one export API
(`docs/gen2/EXPORT-API.md`), like anyone else's.*

**Trace.** Flow architecture (`gen2-flow-architecture-20260924.md`, amended
2026-09-25): §0 actor roster; §4.1–4.4 observability spine (one invocation ID,
dated capability facts, silence-is-never-success, typed holds); S8 publication
contract items 1–4, as amended by the operator ruling 2026-09-26; §5 "Jev question storage" (mounted versioned registry, a
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
*Exporter*, *Operator*. `docs/gen2/INVARIANTS.md`: H-2
(capability facts, the vault-outage fixture), H-4, P-1–P-4, RG-3, RG-4, G-10
(protocol data vs execution policy), B-2 (no gen-2 module imports the gateway's
internals). `docs/gen2/ENVIRONMENT.md` covers the *build* environment; this file
covers the *runtime* one.

**A dedicated stack.** Each gen-2 deployment is one dedicated stack instance:
its own gateway container, its own gateway database, and its own host ports
(below). It shares none of them with any other deployment on the same machine.
One gateway service per database (`D-25`, a decision carried over from gen-1)
holds here too: pointing a gen-2 container at another deployment's gateway
database or listener is a deployment error, not a configuration choice.

---

## 1. The stack

Five gen-2 containers and two referenced external services. "Referenced" means
this stack does not create, own, upgrade or back them up; it connects to them
and reports a dated capability fact when it cannot. The databases an operator
connects to the export API are not services of this stack at all: each is a
connector destination named in mounted config (§2), and the stack neither
creates nor owns nor names any of them (operator ruling 2026-09-26).

| Service | What it is | Image | Referenced or ours |
|---|---|---|---|
| `engine` | Router (sole writer, owns the control store) + station supervisor + composition root. The operator command service (CLI/HTTP/MCP behind one service, design review §10) is exposed from here. | baked gen-2 image | ours |
| `gateway` | This stack's own instance of the federated research gateway (`gateway/research_gateway`), the only door to external research sources. Run as a service and reached over HTTP; never imported (B-2). | the gateway's own image (`gateway/deploy/Dockerfile`). The current image is admissible in the `env` secrets mode only; `vault` mode needs a reviewed gateway release (§3.4) | ours (dedicated to this stack) |
| `exporter` | Outbox consumer: delivers each approved export manifest's bundle to every enabled connector through the one connector contract (`docs/gen2/EXPORT-API.md`; operator ruling 2026-09-26, was `projector`). | baked gen-2 image, same image as `engine`, different entrypoint; reference connectors in the core, reviewed extension connectors from their own packages | ours |
| `tier0` | The local NLI claim-vs-span screen. Optional: with it absent the engine records a dated capability fact and verification proceeds without the screen (the screen never gated a load-bearing claim anyway — BOUNDARIES.md *Tier-0 checker*). | its own pinned image | ours |
| `gateway-db` | PostgreSQL for the gen-2 gateway instance only. | `postgres` pinned | ours |
| Vault | Secrets backend, when the vault backend is selected. | — | referenced |
| Decision provider (Jev API, LLM fallback) | Reached over the network by `gen2/decision`. **Not a build or run dependency**: the charter requires the engine to run and be testable with the decision layer disabled. | — | referenced |

The control store (`gen2/store`, SQLite) is **not** a service. It is a file on a
mounted volume that only the `engine` container opens, because the router is the
sole writer (BOUNDARIES.md *Router*). `exporter` and `operator` transports
reach state only through the `ControlBackend` protocol inside `engine` — no
second process opens the SQLite file. The exporter does so over the Compose
network: it calls the engine's listener at `GEN2_ENGINE_URL`
(`http://engine:8770`) with its own bearer token (§1.1). A deployment that
mounts the control store into two containers has broken the sole-writer
invariant no matter what the code does.

### 1.1 Port map

Container ports are fixed by the images. The host ports below are the product's
defaults, not a survey of any machine. Each deployment checks that every host
port it publishes is free on the deploying host, and changes a port that is
taken in its own configuration; it never shares one.

**A listen address and a host publication are different things.** A service's
listen address is inside its own container's network namespace. Its host
publication is the port Compose maps on the host. `127.0.0.1` inside a container
is that container's own loopback: nothing else can reach it, not the exporter,
not another container, and not a host port published to it. So every service
listens on `0.0.0.0` inside its container, meaning all of that container's
interfaces (its loopback and its Compose-network interface). Where a service is
published at all, the publication is bound to host loopback only, for example
`ports: ["127.0.0.1:8770:8770"]`.

| Service | Listens on, inside its container | Host publication | Reached by | Protocol |
|---|---|---|---|---|
| `engine` operator service | `0.0.0.0:8770` (`GEN2_OPERATOR_LISTEN`) | `127.0.0.1:8770` only | operator clients on the host (operator token); the exporter at `http://engine:8770` (`GEN2_ENGINE_URL`, exporter token) | HTTP + `POST /mcp` (stateless MCP over HTTP, one JSON-RPC message per request — the gateway's proven shape) |
| `engine` health | the same listener: `GET /v1/health`, no token | the same, `127.0.0.1:8770` | its own container healthcheck; anything on the Compose network | HTTP |
| `gateway` | `0.0.0.0:8765` (`RESEARCH_GATEWAY_LISTEN`) | `127.0.0.1:8771` only | the engine at `http://gateway:8765` (`GEN2_GATEWAY_URL`); host clients | HTTP + `POST /mcp` |
| `exporter` health | `0.0.0.0:8772` (`GEN2_EXPORTER_HEALTH_LISTEN`): `GET /v1/health`, no token | not published | its own container healthcheck; the Compose network | HTTP |
| `tier0` | port 8773 on its container's interfaces (its image's setting) | not published | the engine at `http://tier0:8773` (`GEN2_TIER0_URL`) | HTTP |
| `gateway-db` | 5432 on its container's interfaces | not published | the gateway only | PostgreSQL |
| Connector destinations | — | — | the exporter, one per enabled connector: a SQL connection string, a mounted directory, a webhook endpoint, or what a reviewed extension names (`EXPORT-API.md` §5; operator ruling 2026-09-26) | per connector |
| Vault | — | — | a service in vault mode, once admissible (§3.4) | HTTPS, 8200 |

Nothing is published beyond host loopback. Every host publication is
`127.0.0.1:<port>`, and a `0.0.0.0` listen address appears only inside a
container, where it means that container's own interfaces. The engine's
listener carries operator authority, so every route on it except
`GET /v1/health` requires a bearer token, and its publication stays on host
loopback. Exposing it on a private network is an operator decision recorded at
deployment, never a default. Two kinds of token reach it.
`GEN2_OPERATOR_TOKENS` are the operator's. `GEN2_SECRET_EXPORTER_TOKEN` is the
exporter's, and the engine accepts it only for the exporter's `ControlBackend`
calls (claiming outbox events, acknowledging deliveries); it never carries
operator authority.

### 1.2 Healthchecks

Every container declares a healthcheck, and every healthcheck answers about the
thing that container owns — not about a dependency.

| Service | Check | Healthy means | Explicitly **not** part of the check |
|---|---|---|---|
| `engine` | `GET http://127.0.0.1:8770/v1/health` from inside the container (the `0.0.0.0` listener includes the container's loopback): control store opens through the compatibility gate (`gen2/store/compat.py`), the schema matches `schema.sql` exactly, the last scheduler tick is within its interval | the router can commit | whether any provider, connector or the gateway is reachable |
| `gateway` | the gateway image's own healthcheck (`GET /v1/health`, no token) | the service answers | whether any source lane is working |
| `exporter` | `GET http://127.0.0.1:8772/v1/health` from inside the container: the outbox can be read through the `ControlBackend` at `GEN2_ENGINE_URL`, and the worker's last loop is within its interval | the consumer is alive | whether any connector's destination accepted anything |
| `tier0` | model loaded, one fixed probe pair classified | the screen answers | — |
| `gateway-db` | `pg_isready` | — | — |

**A dependency's failure is a capability fact, never an unhealthy container**
(flow §4.2; INVARIANTS H-2, RG-3). A failing Vault, a dead connector destination, a 429 from a
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
| Decision-provider adapters, tier-0 client, gateway client, reference connectors, extension connectors | **baked** | rebuild + release | Executable adapters require an image release (design review §6). An extension connector is reviewed code from its own package outside the core, never operator config (`EXPORT-API.md` §7; operator ruling 2026-09-26). |
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
| Connector enablement and per-topic export options | **mounted**, read-only | restart | `EXPORT-API.md` §5; connection strings are secrets, not config. |

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

Two backends, with the gateway's names and read path
(`gateway/research_gateway/core/secrets.py`), extended to the engine's own
secrets. Logical secret names live in the registry and in `deploy/gen2.env.example`;
values never do.

**Only `env` is admissible today.** The `vault` backend is not admissible for any
service until its implementation passes §3.4. The current gateway's vault backend
breaks both rules in §3.3, and the engine's does not exist yet.

### 3.1 The `env` backend

One mounted file, `deploy/gen2.env`, gitignored, `0400`, owned by the service
user, passed to the containers that need it. Every name in it, with its
grouping and comments, is generated: `deploy/gen2.env.example` (see
`docs/gen2/SOURCE-CATALOG.md`). Source keys are
`RESEARCH_GATEWAY_SECRET_<NAME>[_<FIELD>]`, the gateway's own scheme, which the
gen-2 stack keeps. In this mode the current gateway image meets this contract
as it is. `EnvBackend.get` reads the process environment, so a value is either
present or absent. No read can fail and be mistaken for an absence.

### 3.2 The `vault` backend

`RESEARCH_GATEWAY_SECRETS=vault` selects Vault for the gateway; the engine's
equivalent is `GEN2_SECRETS=vault`. Neither may be selected until §3.4 is met.
Settings, never values:

| Setting | Meaning |
|---|---|
| `…_VAULT_ADDR` | Vault address. Empty address ⇒ the backend reads nothing (and that is a failure, §3.3). |
| `…_VAULT_TOKEN_FILE` | **Required explicitly for every service.** See below. |
| `…_VAULT_MOUNT` | KV v2 mount (gateway default `secret`). |
| `…_VAULT_PREFIX` | Path prefix (gateway default `services`). |
| `…_VAULT_ALIASES` | `logical=vault-name,…` for deployments whose Vault paths do not match the registry's logical names. |

Reads are `GET {addr}/v1/{mount}/data/{prefix}/{name}`; redirects are refused so
a token is never re-sent elsewhere; successful reads cache 15 minutes and
failures 1 minute, so a rotated key lands without a restart. That much the
current gateway already does.

### 3.3 The two outage-hardening rules

These are not recommendations. They are the two rules the 2026-09-21..24 vault
outage produced, and both are testable. They are requirements on a service's
vault backend, and the current gateway image meets neither. §3.4 is what has to
change before any service runs in vault mode.

**Rule 1 — every service names its own token file explicitly.** The gateway's
`VaultBackend` falls back to `os.path.expanduser("~/.vault-token")` when
`RESEARCH_GATEWAY_VAULT_TOKEN_FILE` is unset. In a container, `HOME` is whatever
the image and the runtime happened to set, so the fallback resolves somewhere
nobody chose, and a missing token file is indistinguishable from a missing key.
Every service in this stack therefore sets its own token-file path explicitly —
`RESEARCH_GATEWAY_VAULT_TOKEN_FILE` for the gateway, `GEN2_VAULT_TOKEN_FILE` for
the engine and exporter — each mounted read-only from a distinct path, each
`0400`. A service whose backend is `vault` and whose token-file variable is
unset **refuses to start**; it does not fall back to a home directory. That
refusal is a startup error with the variable named, not a silent degradation.
Setting `RESEARCH_GATEWAY_VAULT_TOKEN_FILE` in a deployment keeps the current
gateway off its fallback, but it does not give that gateway the refusal: with
the variable unset, the current image still reads the home directory.

**Rule 2 — a failed secrets read is a dated `secrets backend failing`
capability fact, never "no key configured".** The failure surface is exact:
`VaultBackend._read` catches `OSError`/`ValueError` and returns `{}`, and `get`
then returns `None` — which is the same value a source with no key configured
produces. Everything downstream reads "no key". Setting the token file does
not fix this. The engine cannot repair it downstream either: by the time a
lane's result reaches the engine over HTTP, the gateway has already turned the
failure into an absence. Under this contract the distinction is carried, not
collapsed:

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
backend in this stack, and today that includes the current gateway image's
`vault` backend.

### 3.4 Vault mode waits for a reviewed release that passes these tests

**Status today.** No service in this stack may run with `vault` selected. The
current gateway image breaks both rules. With `RESEARCH_GATEWAY_VAULT_TOKEN_FILE`
unset it falls back to `~/.vault-token` (`VaultBackend.__init__`). Every failed
read (an unreadable token file, a transport error, a non-200, an unparseable
payload) becomes `{}` and then `None`, the value of a missing key
(`VaultBackend._read`, `get`). The engine's and exporter's vault backend is
gen-2 code that does not exist yet. Until the release below exists, the gen-2
gateway runs with `RESEARCH_GATEWAY_SECRETS=env` and the engine with
`GEN2_SECRETS=env`, both from the one mounted `.env` (§3.1).

**What makes it admissible.** For the gateway: a reviewed gateway release that
keeps the outcome of every secret read (a failed read is not an absent one),
requires an explicit token file, and has no home-directory fallback. For the
engine and exporter: the gen-2 secrets backend, built to §3.3. Each becomes
admissible only once it passes every test below with the vault backend selected.

**Owner.** The gateway repair work in the adjudicated phase plan
(`docs/gen2/BUILD-STATE.md`, "Phase plan"). This belongs to Phase 2's "gateway
observations repair", because the read outcome decides what a lane reports; any
part that touches the gateway's budget or shutdown paths falls to Phase 3's
"gateway budget/shutdown repairs". This contract names the requirement and
grants no authority to change gateway code. Authorizing that work and accepting
its release are the user's. The engine's backend belongs to whichever phase first
builds the engine's secret reads, and it passes the same tests.

**Acceptance tests the release must pass.** Each runs against the service in
its container with the vault backend selected, and each is a fixture, not an
inspection:

1. *No fallback.* Token-file variable unset, with a valid `~/.vault-token` under
   `HOME`: the service refuses to start, names the variable, and never opens the
   home-directory file.
2. *An explicit file that cannot be read.* Token-file variable set to a missing
   path, then to an unreadable file, at startup and after the file is removed
   while running: the service refuses to start, or records each read as
   *failing*. Never as *absent*.
3. *Transport and status failures.* Vault unreachable, timing out, answering 403,
   answering 5xx, answering 404 because the mount itself does not exist (a
   misconfigured mount or prefix, which would make every key look absent), and
   answering 200 with an unparseable body: each read is
   *failing*, distinct from *absent*. It is surfaced as a dated
   `secrets backend failing` capability fact with `since` (the first failure),
   `last_success_at` and the affected lanes, and it alerts on the transition.
4. *Genuinely absent.* Vault answers 404 for a secret path under a mount that
   exists, or 200 with an entry that lacks the field: the read is *absent* ("no
   secret configured for this name"),
   does not alarm, and is distinct from every case in test 3.
5. *The outcome survives the HTTP boundary.* When a request's lanes needed a
   failing secret, the gateway's response says so per lane
   (`secrets_backend_failing`; never `searched_empty`, never "no key
   configured"). The engine records it as a search observation with
   `error_class = 'secrets_backend_failing'` and never counts a zero.
6. *The cache does not launder a failure.* A failure cached for its retry
   interval is replayed as *failing*, not as *absent*, and a recovery moves the
   fact back with its `last_success_at`.
7. *Redirects are still refused*, so a token is never re-sent elsewhere
   (regression).
8. *The outage replay.* Every read answers 403 from a fixed time. From the first
   failed read on, operator status reads
   `secrets backend failing since <that time> (403); N lanes degraded`, and no
   lane in that window reports `searched_empty` or adds a zero to any count or
   denominator (INVARIANTS H-2, RG-4, RG-U).

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

*Operator amendment to (d) (the user, 2026-09-29; normative).* For the Phase 1
gate, (d) is satisfied by its offline scope: a credential the pinned runner
rejects on its own, and a credential whose own declared expiry has passed (read
offline from the credential), each produce a dated capability fact and a typed
capability hold. A declared expiry is recorded as a **`degraded`** fact (the
credential's own claim, not the provider's answer), and refresh-token presence
is recorded but never taken as proof that the credential can be refreshed. The
residual — a **revoked** credential, or one that has expired without declaring
it — changes no local byte and cannot be seen offline. It becomes a binding
**requirement gating the first live provider execution** (Phase 2's live
single-topic run; corrected same day from "Phase 3", since the first live call
happens in Phase 2): when a real
invocation's authentication fails, the engine must record a dated `failing`
capability fact and open a typed capability hold, and the invocation must end as
a failure with that evidence — never as a zero-result pass. That requirement is
tested with the pinned runner against a genuinely rejected credential before any
live provider call is admissible. An optional provider liveness check (a
non-billing token exchange) may be added later as a deployment choice; it is not
required.

*Status (task 1f, 2026-09-28, corrected by task 1f-repair, 2026-09-29;
evidence `docs/gen2/AUTH-DEMO.md`; this note changes no requirement).* With
the pinned runner codex 0.153.2, (a), (b) and (c) are demonstrated, and (d)
is demonstrated for a credential the runner rejects on its own and for one
whose own declared expiry has passed (read offline from the credential;
not the provider's answer; counted by the operator amendment above). (d) for
a **revoked** credential, or one expired
without declaring it, is outside the offline scope: neither changes a local byte, so a
probe that makes no network call cannot be sure to see it (AUTH-DEMO.md F1;
resolved by the operator amendment above). AUTH-DEMO.md F2–F4 name the places where this
section's and §3.1's wording and the slice differ.

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
  for the engine. A new execution adapter, decision provider, connector or
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
   one per invocation), dossiers, open holds, export manifests and connector
   watermarks.
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
historical scientific completion at a dossier revision, current export
delivery, and surveillance currency as of a time. A restore that cannot
re-deliver to a connector leaves export delivery *partial* and raises a
capability incident; it does not undo completion and does not stop
surveillance.

---

## 6. What this file does not settle

- **No compose file, image or volume is committed by task 0c.** This is the
  specification they are built against. Task 1f added the minimal `engine`
  slice only: the engine image with its pinned runner (`deploy/gen2/Dockerfile`)
  and a compose file for the engine, its control-store volume and one auth
  volume (`deploy/gen2/compose.yaml`; `docs/gen2/AUTH-DEMO.md`). The `exporter`
  and `tier0` images do not exist yet, and the gateway is not in that slice.
  The gen-2 `gateway` runs the existing gateway image in the `env` secrets mode
  only.
- **Vault mode for any service** waits for §3.4's acceptance tests. The gateway
  release it needs is Phase 2/3 repair work, and authorizing it is the user's.
- **Port defaults are only defaults** (§1.1). Whether each is free is checked
  at every deployment, on the host being deployed to.
- **Migration and cutover** (freeze, import, reconcile, single-writer cutover)
  are Phase 4 and live in the migration contract, not here.
- **Nothing here is evidence that a mechanism works.** Every rule above is a
  requirement on a deployment that does not exist yet; the release gates named
  in §2, §4 and §5 are where it becomes evidence.
