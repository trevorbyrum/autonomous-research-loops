# Auth-volume demonstrations (DEPLOYMENT-CONTRACT §4) — task 1f evidence

`DEPLOYMENT-CONTRACT.md` §4 requires, before Phase 1 is accepted, that the
deployment demonstrate with the pinned runner: (a) a credential refresh inside
a live auth volume picked up without a rebuild; (b) container replacement
preserving auth-volume access and permissions; (c) two simultaneous
invocations against one auth home not corrupting its credential state; (d) a
revoked or expired credential producing a dated capability fact and a typed
capability hold, not a silent zero-result pass.

**Outcome.** (a), (b) and (c) are demonstrated. (d) is demonstrated for a
credential the pinned runner rejects on its own (absent, unparseable,
unreadable). **(d) as the contract words it — an expired or revoked
credential — is not met:** the pinned runner reads an expired credential as
usable, and no probe that makes no network call can see a revocation. The
demonstration that asserts it (d2) fails, reproducibly, and the run exits 1.
This is finding F1 below. It needs the operator's ruling. The requirement has
not been reworded to make it pass.

**Evidence run.** 2026-09-29, `make gen2-auth-demo` from commit `c00de34`.
Full logs: `/var/tmp/gen2-auth-demo/20260929T003539Z/`. Runner
`codex-cli 0.153.2`; image `sha256:4c296396…29e08f8a`; Docker 29.8.1,
Compose v5.5.1; the engine on `127.0.0.1:8770`.

| Demonstration | Result | Assertions | Key evidence |
|---|---|---|---|
| setup | PASS | 10/10 | a fresh volume: an empty 0700 directory of 10001:10001; with no credential the first probe records `failing`, and with a credential written the next records `healthy` |
| (a) refresh | PASS | 18/18 | removed → `failing` and a hold; refreshed → a new `healthy` fact dated after the refresh; the same container (`acae875c…`), start time, image and zero restarts |
| (b) restart, replacement | PASS | 24/24 | restart: the same container, started again. Replacement: `acae875c…` → `9c4aead7…`; the same volumes, not re-created; auth home and credential identical (bytes, mode, owner, inode); the fact recorded before (`fact_e7311f91…`) carries on with no transition |
| (c) concurrency | PASS | 48/48 | 20/20 rounds had overlapping runner runs; 40/40 probes `usable`; credential unchanged; no fact moved, no hold opened |
| (d1) invalid credential | PASS | 13/13 | `failing` fact dated at the probe, with `last_success_at`; status `waiting` holds exactly the capability hold (class capability, operator-owned, deadlined, bound to the fact) |
| (d2) expired credential | **FAIL** | 5/6 | "never a silent success" failed: outcome `usable`, fact `healthy` (F1) |
| (e) characterization | PASS | 20/20 | the table below |
| store read-back | PASS | 6/6 | 54 probes recorded = 54 replies, each identical; fact chain failing→healthy three times; 3 holds, each cleared by an operator decision; no WAL left at stop |

The run exits 1. The run just before it (`20260929T003456Z`) gave the same
per-demonstration results. `make gen2-auth-demo DEMOS=a,b,c,d1,e`
(`20260929T003619Z`) exits 0. The throwaway operator token appears in no
kept file of these runs (checked by the run itself; see F4 for the two
earlier runs whose logs do contain one).

## What ran

| Piece | Where | What it is |
|---|---|---|
| Pinned runner | `deploy/gen2/Dockerfile` | codex **0.153.2**, the static musl binary from the public npm tarball `@openai/codex@0.153.2-linux-x64` (Apache-2.0). The build checks the tarball against the registry's published sha512 integrity (`CPUPhFmy…Q9AJlTw==`, hex `08f50f84…f402654f`), the binary against its SHA-256 (`f8786262ebc0fa1337448a2977332beadec66c8d0cda0ce973c7849766d7943c`), and `codex --version` against `codex-cli 0.153.2`. The binary is byte-identical to the codex 0.153.2 installed on the build host. Baked, per §2. |
| Engine image | `deploy/gen2/Dockerfile` | `ubuntu:24.04` by digest (Python 3.12.3 and SQLite 3.45.1: the pair the gen-2 suite and its compatibility gate ran on, `ENVIRONMENT.md`); the runtime lock installed with `--require-hashes --no-deps`; `gen2/` without its tests; service user uid/gid 10001; `/var/lib/gen2/state` and `/auth/codex` created 0700 and owned by that user, so a fresh named volume takes both over. |
| Compose slice | `deploy/gen2/compose.yaml` | The `engine` service alone, per §1: listening on `0.0.0.0:8770` inside its container, published on `127.0.0.1:8770` only; its control-store volume (`state`), one auth volume (`auth-codex` at `/auth/codex`), the config bundle mounted read-only, secrets from one env file (§3.1). Read-only root filesystem, `/tmp` a tmpfs, all capabilities dropped, `no-new-privileges`. `init-store` (profile `init`) creates the store once, explicitly. No gateway, exporter, tier0 or research workflow. |
| The probe | `gen2/supervisor/probe.py` | Station-supervisor code (BOUNDARIES *Station supervisor*: capability probes). It checks the auth home is a 0700 directory, not a link, of the service user; then it runs `codex --version` (the pinned version, or `runner_error`) and `codex login status` in a fresh workspace, with exactly `PATH`, `HOME` and `CODEX_HOME` in its environment. It classifies the exit code and output by fixed rules into `usable`, `unusable_credential` or `runner_error`. Nothing the runner printed is recorded. |
| The record | `gen2/router/capabilities.py` | The router records each observation whole, as an audit event keyed by its probe id. The capability `provider-auth:codex` gets a dated fact on a transition only (`healthy`, `failing` or `unknown`), following the newest observation; a failing fact names its last success. A non-usable observation opens the capability's hold when none is open. The hold is class `capability`, owned by the operator and deadlined, and it clears only by an operator `hold_clearance` (G-13). |
| The command | `probe_capability` (`gen2/operator/service.py`) | The operator's request, over HTTP, MCP or the CLI. The engine runs the runner on the request's thread and only the record on the router's owner thread, so two probes really run at once. Status shows the engine's own `waiting` hold(s) beside the capability facts. |
| The demonstrations | `deploy/gen2/demo/auth_demo.py`, `make gen2-auth-demo` | Builds the image, brings the slice up under compose project `gen2-authdemo`, and runs the setup, (a), (b), (c), (d1), (d2), (e) and a final store read-back, each asserting mechanically. Exit 0 only when every one passes. |

Why codex and not claude (both on this host). Three reasons. First, codex's
check (`codex login status`) is purely local and deterministic: it gives the
same verdict, in about 15 ms, with `--network none`, and it never writes the
credential file. With an expired stored token, claude 2.1.283's
`claude auth status` took its OAuth refresh lock: offline, it left an
`.oauth_refresh.lock` directory in the auth home. That is inferred from the
lock, not seen on the wire, but a refresh needs the provider, so a probe built
on it is not plainly a no-network probe. Second, codex's public distribution can be
pinned by content — the registry's own integrity hash for the tarball, the
binary's SHA-256 — and the binary is static, so the image needs no Node.
Third, codex is Apache-2.0, so an image built from this public Dockerfile can
carry it. The cost is that codex's local check is weak on content: `{}` and
an empty API key read as logged in (the table in (e)). Neither CLI's local
check reads expiry.

## Per demonstration

Every demonstration starts from its own stated precondition and asserts it.
"Status" means operator status over the published listener, and "reply"
means the router's answer to that probe. Both are the engine reading its own
store. File checks run inside the engine container as its service user
(`stat` and SHA-256 of every entry of the auth home). The credential is always
written by a separate helper container that mounts the auth volume alone, as
the service user. It writes atomically: a temporary file, fsync, mode 0600,
then rename. That helper is the operator's act, outside the engine.

- **Setup.** The fresh auth volume is an empty 0700 directory of uid/gid 10001. The first probe finds no credential and records a failing fact, the capability's first. A throwaway API key is written. The next probe records the recovery, and the operator clears the hold.
- **(a) Refresh.** The credential is removed from the live volume, and the probe records `failing` and opens the hold (precondition). A new throwaway key is written. The next probe records a new `healthy` fact, dated after the refresh. Asserted: the engine container sees exactly the new bytes, 0600, owned by the service user. The container is unchanged: same id, same start time, zero restarts, the image built at setup, so there was no rebuild, recreation or restart. Status shows the recovery fact. The hold stays open until the operator's `hold_clearance`, since a probe clears nothing, and after that no hold is open.
- **(b) Restart and replacement.** Precondition: the credential is usable. After `docker compose restart`, the container is the same one, started again. The auth home and credential are identical (bytes, mode, owner, inode). The probe agrees, and the same fact carries on with no transition. Then comes replacement: `docker compose down` removes the container and the network and keeps the volumes, and `up` starts a new container id. Asserted: the same volumes at the same paths, not re-created (creation times unchanged); the auth home is the same 0700 directory of 10001; the credential is identical; the new container's probe agrees, and the fact recorded before replacement carries on; the active config-bundle pin is unchanged.
- **(c) Concurrency.** Twenty rounds. In each round, two `probe_capability` requests leave a barrier together, from two threads using the CLI's own client function. Asserted every round: both answered, both recorded, both `usable`. After all rounds: the credential's bytes, mode, owner and inode are unchanged; the fact carries on unchanged, and no hold opened. The two runner runs of at least one round overlapped in time. That is read from the probes' own recorded start and end instants, not assumed from the request timing.
- **(d1) Invalid credential.** A credential whose ID token is not a JWT; codex answers "invalid ID token format". Asserted: the probe did not record it usable; a `failing` fact dated at the probe (`since` after the call began); status shows that fact with its `last_success_at`; status's engine `waiting` holds exactly the capability's hold, which is class `capability`, owner and required authority `operator`, bound to that fact, deadlined after it, not yet overdue, saying what clears it, recoverability `needs_remediation`.
- **(d2) Expired credential — the contract's case.** Throwaway ChatGPT-mode tokens whose JWTs expired in 2001. It asserts what the contract requires, the same as (d1). **It fails**: codex 0.153.2 reports "Logged in using ChatGPT" (exit 0), so the probe records `usable` and the fact stays `healthy`. That is a silent pass, which is exactly what (d) forbids.
- **(e) Characterization.** The pinned runner from the image, with no network at all (`--network none`), over each throwaway credential shape in a fresh 0700 auth home. The probe's own rules are applied to its raw output. This pins what codex 0.153.2's local check tells apart:

| Credential shape (throwaway) | codex exit | its stderr line | the probe's rules | Gap |
|---|---|---|---|---|
| absent | 1 | `Not logged in` | unusable_credential | |
| API key | 0 | `Logged in using an API key - sk-throw***…` | usable | |
| empty API key `""` | 0 | `Logged in using an API key - ***` | usable | an empty key reads as a credential |
| `{}` | 0 | `Logged in using ChatGPT` | usable | an empty object reads as ChatGPT tokens |
| ChatGPT tokens, unexpired (2100) | 0 | `Logged in using ChatGPT` | usable | |
| ChatGPT tokens, expired (2001) | 0 | `Logged in using ChatGPT` | usable | **expiry is not checked locally (F1)** |
| ID token not a JWT | 1 | `Error checking login status: invalid ID token format …` | unusable_credential | |
| malformed JSON | 1 | `Error checking login status: key must be a string …` | unusable_credential | |
| empty file | 1 | `Error checking login status: EOF while parsing a value …` | unusable_credential | |
| mode 000 | 1 | `Error checking login status: Permission denied (os error 13)` | unusable_credential (permission denied) | |

Each row is asserted. A future runner version that tells more cases apart
fails its row, and the rules are reviewed with the version pin.

- **Store read-back.** After the engine stops (SIGINT, its own close path; asserted: no WAL file is left), a copy of the store file is read. It checks that every probe reply the run received is recorded and nothing else is, with each recorded reply equal to the one received; that the fact history of `provider-auth:codex` is one chain of state changes; that every capability hold is bound to a failing or unknown fact; and that every hold the run opened was cleared by an operator decision. The run also checks that the throwaway operator token appears in no kept file: the run log, the engine log, the store copy or the characterization output.

## What this does and does not establish

It establishes, for this image and runner version:
- The auth volume survives restart and replacement. Its ownership (10001:10001), its mode (0700), the credential's bytes, mode and inode, and the router's record of the capability all carry across a new container.
- A credential replaced in the live volume is read by the next probe. No rebuild, recreation or restart is needed, because the runner reads its auth home afresh on every run and the volume is mounted as a directory.
- Two probes can run the pinned runner against one auth home at the same moment. Neither misclassifies, and the credential file is unchanged.
- A credential the pinned runner itself rejects becomes a dated failing fact and a typed, owned, deadlined operator hold, visible in operator status. It never reads as a success.
- The probe's classification needs no network: every verdict in (e) was reached with none.

It does not establish:
- **Anything about a live provider.** No request was sent to any provider, and no credential in this run can authenticate anywhere. "Usable" means only that codex 0.153.2's local check reads a credential. It does not mean the provider would accept it.
- **Expiry or revocation detection** (F1). That includes an empty API key and an empty JSON object, which also read as usable.
- **Concurrent credential writes.** `login status` only reads the credential. codex writes it when it refreshes ChatGPT tokens, which needs a live provider, so two simultaneous refreshes against one auth home were not exercised. codex does write beside the credential on every run: a `tmp/arg0/codex-arg0*` helper directory with a lock file (F2). Those concurrent writes were exercised, and the credential stayed intact.
- **Per-job auth-home isolation.** The auth volume is mounted into the engine container, and the supervisor's jobs are processes in that container under the same uid. So every job can read every mounted auth home (F3). The contract's "no auth home is mounted into a job that does not need that provider" holds only at the container level here.
- **No egress.** The engine's Compose network is an ordinary bridge. A Compose `internal` network has no egress, but it also cannot carry the contract's host publication (tried: the published port refused connections). The runner's independence from the network is shown by (e), not by fencing the engine.
- **Other runner versions.** The rules are codex 0.153.2's. Any other version is a `runner_error` by construction (the probe checks `--version` first), so a runner upgrade must re-run (e) and review the rules.
- **Alert on transition** (H-2's alert channel is Phase 3). The fact and the hold are recorded and shown; nothing pages anyone.

## Findings (where reality and the contract differ)

**F1 — (d) cannot be met for an expired or revoked credential by a probe that makes no network call (normative; operator decision).**
Both runner CLIs on this host have a local status check, and both read an
expired credential as logged in. codex 0.153.2's `login status` does not
check token expiry. Offline, claude 2.1.283's `auth status` says
`loggedIn: true` for an OAuth token whose `expiresAt` has passed (it took its
refresh lock first; see the appendix). A revoked credential is identical, byte for byte, to a
valid one; only the provider knows. So a probe that is local, deterministic
and quota-free (as the brief required) can detect a missing, unparseable or
unreadable credential, but not an expired or revoked one. Demonstration (d2)
asserts the contract's requirement and fails.

Options, for the operator:
- **(i)** Allow the probe an authenticated, non-billing exchange with the provider. For OAuth runners that is the token-refresh handshake claude's status check already attempts. This means network access to the provider's auth endpoint and real credentials, and so it cannot be demonstrated with throwaway credentials except against a provider stub.
- **(ii)** Amend (d)'s Phase 1 obligation to "a credential the pinned runner rejects". Make a later-phase obligation of the case that actually prevents the Monday discovery the contract describes: a real invocation's authentication failure is classified by the supervisor as a capability failure (a fact and a hold), never as a zero-result pass.
- **(iii)** Both.

The contract has not been changed. §4 now carries a status note pointing
here.

**F2 — an auth home does not hold "only that provider's credential state" (normative wording).**
§4: "one named, access-controlled volume holding only that provider's
credential state". Each runner's auth home is its whole home.
- codex creates `tmp/arg0/codex-arg0*/` (helper links and a `.lock`) under `CODEX_HOME` on every run, `login status` and `--version` included. It also keeps its config, logs and sessions there in normal use.
- claude writes `.claude.json`, `backups/` and `.oauth_refresh.lock` into `CLAUDE_CONFIG_DIR`.

Separating the credential would mean a link from a per-job home into the
volume. That conflicts with the no-symlink practice here, and an atomic
refresh by the runner would replace the link. Suggested wording: "…holding
that provider's credential state and what its pinned runner keeps beside it
in its home (named per runner in the evidence)".

**F3 — per-job auth-home isolation is container-level in this slice (normative; a later phase).**
§4: "No auth home is mounted into a job that does not need that provider."
Supervisor jobs are processes in the engine container, and they share its
mounts and uid. The 1e review already deferred OS-level isolation of jobs
until before untrusted execution. This slice does not change that, and it
makes the gap concrete for auth homes.

**F4 — the env-secrets file is read by Compose on the host, not mounted and not "owned by the service user" (§3.1 wording).**
With Compose `env_file`, the Compose CLI reads the file on the host as the
account running it. Its values reach the container as environment variables,
which is what the engine reads (`Credentials.from_environ`). In this demo the
file is 0400, owned by that account, created per run and removed at the end.
"Owned by the service user" (uid 10001 inside the container) has no meaning
for that file. Suggested wording: "…0400, owned by the operator account that
runs Compose, read by Compose and passed to the containers that need it as
environment variables".

The same mechanism puts every secret in the container's configuration, where
`docker inspect` shows it to anyone who can reach the Docker daemon. (Docker
access is already root-equivalent on the host.) The demo's first two full runs
(`20260928T232137Z`, `20260929T003344Z`) logged a full `docker inspect`, and
so wrote the throwaway operator token into their run logs. The run's own token check caught it both times. The driver
now asks `docker inspect` for only the fields it asserts on.

**Deployment notes (not contract discrepancies):**
- The engine installs no SIGTERM handler, and the `app` module has no `signal` grant. The compose slice stops it with `SIGINT`, which reaches its own `KeyboardInterrupt` → `Engine.close()` path, and runs it under `init: true`. The read-back asserts that close ran: no WAL file is left beside the stopped store. Without that setting, `docker stop` ends in SIGKILL after the grace period, and the store's WAL durability is all that protects it.
- The store is created once, explicitly (`init-store`). A missing store is a startup error, not a mode (INVARIANTS §11.2).
- Mount auth homes as directories, never as single-file bind mounts. An atomic credential replacement (rename) is not visible through a single-file bind mount. This is Docker behaviour and was not demonstrated here.

## Reproduce

```
make gen2-auth-demo                 # everything; exit 1 while F1 stands (d2)
make gen2-auth-demo DEMOS=a,b,c,d1  # a subset (the setup and the store read-back always run)
```

The run needs Docker with Compose, and network access for the image build
(the base image, PyPI for the hash-locked runtime lock, the npm registry for
the runner tarball). It uses its own project name, `gen2-authdemo`, and the
contract's default port, which it checks is free (`GEN2_ENGINE_PORT`
overrides). It removes only its own project's containers, network and
volumes. Logs go to `GEN2_AUTH_DEMO_LOG_DIR`, default
`/var/tmp/gen2-auth-demo/<UTC time>/`: `run.log` has every command with its
exit status and full output, and every assertion with its evidence;
`summary.json`; `engine.log`; `characterization.json`; and `store/`, the
store copy.

## Appendix — manual exploration before the scripted run (2026-09-28, not repeated by `make`)

These observations chose the runner and shaped the rules. The scripted (e)
reproduces the codex rows. Each one ran with throwaway credentials only, in a
`ubuntu:24.04` container with `--network none`, running the host's binary
mounted read-only, with its home and auth home in a scratch directory under
`/var/tmp`. No real auth home was read or mounted.
- **codex 0.153.2 `login status`**, CODEX_HOME holding:
  - no file: `Not logged in`, exit 1.
  - `{"OPENAI_API_KEY": "sk-throwaway-…"}`: `Logged in using an API key - sk-throw***00000`, exit 0.
  - `{}`: `Logged in using ChatGPT`, exit 0.
  - `{"OPENAI_API_KEY": ""}`: `Logged in using an API key - ***`, exit 0.
  - ChatGPT tokens whose JWTs expired in 2001: `Logged in using ChatGPT`, exit 0.
  - An ID token that is not a JWT: `Error checking login status: invalid ID token format …`, exit 1.
  - Malformed JSON, or an empty file: `Error checking login status: …` (a parse error), exit 1.
  - A file with mode 000: `Error checking login status: Permission denied (os error 13)`, exit 1.

  Every message is on stderr; stdout is empty. On every run, codex also
  created `tmp/arg0/codex-arg0*/` (helper links and `.lock`) inside CODEX_HOME.
  With CODEX_HOME under `/tmp` it refuses to create them, and prints a warning
  line first. `codex doctor --json` reports `auth.credentials: ok` for the
  expired tokens, and spends about 25 s on network reachability checks.
- **claude 2.1.283 `auth status --json`**, CLAUDE_CONFIG_DIR holding:
  - no file, `{}`, or malformed JSON: `loggedIn: false`, exit 1.
  - `.credentials.json` with a throwaway OAuth token, `expiresAt` in 2100: `loggedIn: true`, exit 0.
  - The same token with `expiresAt` in 2001: `loggedIn: true`, exit 0, and an `.oauth_refresh.lock` directory left behind.

  Every run wrote `.claude.json` and a `backups/` entry into the config
  directory.

