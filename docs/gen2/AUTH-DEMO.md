# Auth-volume demonstrations (DEPLOYMENT-CONTRACT §4) — task 1f evidence

`DEPLOYMENT-CONTRACT.md` §4 requires, before Phase 1 is accepted, that the
deployment demonstrate with the pinned runner: (a) a credential refresh inside
a live auth volume picked up without a rebuild; (b) container replacement
preserving auth-volume access and permissions; (c) two simultaneous
invocations against one auth home not corrupting its credential state; (d) a
revoked or expired credential producing a dated capability fact and a typed
capability hold, not a silent zero-result pass.

**Outcome.** (a), (b) and (c) are demonstrated, and (c)'s concurrency is
now shown at the level of the runner's processes, with a negative control
that fails as it must (corrected after the 1f review, finding 2). (d) is
demonstrated for a credential the pinned runner rejects on its own (absent,
unparseable, unreadable: d1), and for one whose own declared expiry has
passed (d2a): the probe reads the credential's declared expiry offline and
records a dated `degraded` fact and the typed hold, labeled as the
credential's claim, not the provider's answer (whether that counts toward
(d) is the operator's, F1). **(d) for a revoked
credential, or one that expired without declaring it, is not met:** neither
changes a local byte, so no local probe can be sure to see it. The
demonstration that asserts it (d2b) fails, reproducibly: the driver exits 1,
and `make` exits 2. This is finding F1 below, corrected after the review
(finding 1): it needs the operator's ruling. The requirement has not been
reworded to make anything pass.

**Evidence runs.** 2026-09-29, from commit `440a932`; logs under
`/var/tmp/gen2-auth-demo/<run>/`. `make gen2-auth-demo`
(`20260929T032419Z`): every demonstration passes but d2b; the driver exits
1 and `make` exits 2. `make gen2-auth-demo DEMOS=a,b,c,c-control,d1,d2a,e`,
twice in a row (`20260929T032518Z`, `20260929T032616Z`): each exits 0,
driver and `make`. Runner `codex-cli 0.153.2`; each run builds its image
through the compose target (the full run's `sha256:72fd3056…17140ea2`; the
image ID differs from build to build, as it did in the review's runs, and
(a) asserts the image built at a run's own setup); Docker 29.8.1, Compose
v5.5.1; the engine on `127.0.0.1:8770`. The table is the full run.

| Demonstration | Result | Assertions | Key evidence |
|---|---|---|---|
| setup | PASS | 10/10 | a fresh volume: an empty 0700 directory of 10001:10001; with no credential the first probe records `failing`, and with a credential written the next records `healthy` |
| (a) refresh | PASS | 18/18 | removed → `failing` and a hold; refreshed → a new `healthy` fact dated after the refresh; the same container (`c20348b8…`), start time, image and zero restarts |
| (b) restart, replacement | PASS | 24/24 | restart: the same container, started again. Replacement: `c20348b8…` → `cec85c00…`; the same volumes, not re-created; auth home and credential identical (bytes, mode, owner, inode); the fact recorded before (`fact_d4e5f7c1…`) carries on with no transition |
| (c) concurrency | PASS | 68/68 | 40/40 probes `usable`; the credential as before after each of the 20 rounds; two `codex login status` processes live at one instant in 20/20 rounds (40 processes seen, 44,462 scans); no fact moved, no hold opened |
| (c-control) serialized runner | PASS | 73/73 | the serialized copy of probe.py running (SHA-256 checked); 40 login status processes seen, 2 in every round; **no** two live at one instant, so (c)'s overlap assertion fails, as it must; the old whole-probe windows still intersected in 20/20 rounds; the image's probe restored and checked |
| (d1) invalid credential | PASS | 13/13 | `failing` fact dated at the probe, with `last_success_at`; status `waiting` holds exactly the capability hold (class capability, operator-owned, deadlined, bound to the fact) |
| (d2a) declared expiry passed | PASS | 15/15 | outcome `declared_expired`; `degraded` fact (`fact_203f90e5…`) dated at the probe, with `last_success_at`; the typed hold, remedy `needs_remediation`; `declared_expiry` names 2001-09-09T01:46:40Z for both tokens and a refresh credential present; the fact's detail says "the credential's own claim, not the provider's answer" |
| (d2b) revoked, or expiry undeclared | **FAIL** | 6/7 | the credential byte for byte the one just probed usable; "never a silent success" failed: outcome `usable`, fact `healthy` (F1) |
| (e) characterization | PASS | 42/42 | the table below, both outcomes per row |
| store read-back | PASS | 6/6 | 98 probes recorded = 98 replies, each identical; fact chain failing→healthy three times, then degraded→healthy; 4 holds, each cleared by an operator decision; no WAL left at stop |

The two subset runs gave the same per-demonstration results and assertion
counts as the full run (95 probes each, without d2b). The throwaway
operator token appears in no kept file of any of the three runs (checked by
each run itself; see F4 for the two earlier runs whose logs do contain
one). The 1f runs before this repair (`20260929T003539Z` and the rest) are
superseded: their (c) overlap rested on the whole-probe windows, which the
review showed admit a serial run.

## What ran

| Piece | Where | What it is |
|---|---|---|
| Pinned runner | `deploy/gen2/Dockerfile` | codex **0.153.2**, the static musl binary from the public npm tarball `@openai/codex@0.153.2-linux-x64` (Apache-2.0). The build checks the tarball against the registry's published sha512 integrity (`CPUPhFmy…Q9AJlTw==`, hex `08f50f84…f402654f`), the binary against its SHA-256 (`f8786262ebc0fa1337448a2977332beadec66c8d0cda0ce973c7849766d7943c`), and `codex --version` against `codex-cli 0.153.2`. The binary is byte-identical to the codex 0.153.2 installed on the build host. Baked, per §2. |
| Engine image | `deploy/gen2/Dockerfile` | `ubuntu:24.04` by digest (Python 3.12.3 and SQLite 3.45.1: the pair the gen-2 suite and its compatibility gate ran on, `ENVIRONMENT.md`); the runtime lock installed with `--require-hashes --no-deps`; `gen2/` without its tests; service user uid/gid 10001; `/var/lib/gen2/state` and `/auth/codex` created 0700 and owned by that user, so a fresh named volume takes both over. |
| Compose slice | `deploy/gen2/compose.yaml` | The `engine` service alone, per §1: listening on `0.0.0.0:8770` inside its container, published on `127.0.0.1:8770` only; its control-store volume (`state`), one auth volume (`auth-codex` at `/auth/codex`), the config bundle mounted read-only, secrets from one env file (§3.1). Read-only root filesystem, `/tmp` a tmpfs, all capabilities dropped, `no-new-privileges`. `init-store` (profile `init`) creates the store once, explicitly. No gateway, exporter, tier0 or research workflow. |
| The probe | `gen2/supervisor/probe.py` | Station-supervisor code (BOUNDARIES *Station supervisor*: capability probes). It checks the auth home is a 0700 directory, not a link, of the service user; then it runs `codex --version` (the pinned version, or `runner_error`) and `codex login status` in a fresh workspace, with exactly `PATH`, `HOME` and `CODEX_HOME` in its environment. It classifies the exit code and output by fixed rules into `usable`, `unusable_credential` or `runner_error`. When the runner reads the credential as usable, the probe reads the same file (`auth.json`, not following a link, at most 1 MiB) for the expiry it declares: the JWT `exp` of the access and ID tokens, and whether a refresh token is present (`declared_expiry`). An access token declaring an expiry at or before the observation makes the outcome `declared_expired` (F1). Nothing the runner printed is recorded, and of the credential only those instants and that presence. |
| The record | `gen2/router/capabilities.py` | The router records each observation whole, as an audit event keyed by its probe id. The capability `provider-auth:codex` gets a dated fact on a transition only (`healthy`, `degraded` for `declared_expired`, `failing` or `unknown`), following the newest observation; a fact not healthy names its last success. A `declared_expired` observation must name its access token's declared instant, at or before it was observed. A non-usable observation opens the capability's hold when none is open. The hold is class `capability`, owned by the operator and deadlined, and it clears only by an operator `hold_clearance` (G-13). |
| The command | `probe_capability` (`gen2/operator/service.py`) | The operator's request, over HTTP, MCP or the CLI. The engine runs the runner on the request's thread and only the record on the router's owner thread, so two probes really run at once. Status shows the engine's own `waiting` hold(s) beside the capability facts. |
| The demonstrations | `deploy/gen2/demo/auth_demo.py`, `make gen2-auth-demo` | Builds the image, brings the slice up under compose project `gen2-authdemo`, and runs the setup, (a), (b), (c), (c)'s negative control, (d1), (d2a), (d2b), (e) and a final store read-back, each asserting mechanically. The driver exits 0 only when every one passes, 1 when any fails, 2 when the run could not be set up; `make` reports a failing driver as its own exit 2. |

Why codex and not claude (both on this host). Three reasons. First, codex's
check (`codex login status`) is purely local and deterministic: it gives the
same verdict, in about 15 ms, with `--network none`, and it never writes the
credential file. With an expired stored token, claude 2.1.283's
`claude auth status` took its OAuth refresh lock in the manual run of the
appendix: offline, it left an `.oauth_refresh.lock` directory in the auth
home. That is inferred from the lock, not seen on the wire, and the 1f
review's own claude fixture reproduced the verdict and the config and backup
writes but not the lock; a refresh needs the provider, so a probe built on
that command is not plainly a no-network probe. Second, codex's public distribution can be
pinned by content — the registry's own integrity hash for the tarball, the
binary's SHA-256 — and the binary is static, so the image needs no Node.
Third, codex is Apache-2.0, so an image built from this public Dockerfile can
carry it. The cost is that codex's local check is weak on content: `{}` and
an empty API key read as logged in (the table in (e)). Neither CLI's local
status command rejects an expired token; both credential formats declare an
expiry that can be read offline, which the probe now reads beside the
command (F1).

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
- **(c) Concurrency.** Twenty rounds. In each round, two `probe_capability` requests leave a barrier together, from two threads using the CLI's own client function. Asserted every round: both answered, both recorded, both `usable`; and, read after the round, the credential's bytes, mode, owner and inode are as before (between rounds, not during one: a change made and undone within a round would not be seen). After all rounds: the fact carries on unchanged, and no hold opened. Overlap is asserted from the runner's processes, not from the probes' records: throughout the rounds a sampler runs inside the engine container, in its process table, and records every `codex login status` process it sees live (its exec'd command line read from `/proc`, not a zombie) and every instant two were live together. A pair is counted only when the first process is read live, then the second, then the first again, the same process (pid and start time); since a process lives over one interval, both were live when the second was read. Asserted: in at least one round, two login status processes were live at one instant. The probes' own recorded start and end bracket the whole probe (auth-home check, workspace, `--version`, `login status`, the declared-expiry read, cleanup), so their intersection is logged beside it but asserts nothing: the review showed it admits a fully serial run. The sampler's record is kept as `c-processes.json`.
- **(c-control) The negative control for (c).** The engine is recreated with a copy of `gen2/supervisor/probe.py` mounted read-only over the image's, in which one lock serializes each probe's runner runs after the probe has recorded its start (the review's counterexample). Asserted: the engine runs that copy (its SHA-256 in the container); the sampler saw login status processes in every round; and (c)'s own overlap assertion, the same function, fails: no two login status processes were live at one instant. The other (c) assertions still pass. Then the engine is recreated on the image's own probe, and that is asserted too. Its record: `c-control-processes.json`, and the copy and its compose override under `c-control/`.
- **(d1) Invalid credential.** A credential whose ID token is not a JWT; codex answers "invalid ID token format". Asserted: the probe did not record it usable; a `failing` fact dated at the probe (`since` after the call began); status shows that fact with its `last_success_at`; status's engine `waiting` holds exactly the capability's hold, which is class `capability`, owner and required authority `operator`, bound to that fact, deadlined after it, not yet overdue, saying what clears it, recoverability `needs_remediation`.
- **(d2a) An expired credential that declares its expiry.** Throwaway ChatGPT-mode tokens whose access and ID tokens' JWT `exp` is 2001-09-09T01:46:40Z, with a refresh token. codex 0.153.2 reports "Logged in using ChatGPT" (exit 0); the probe reads the declared expiry and records `declared_expired`. Asserted, as for (d1): never a silent success; a `degraded` fact dated at the probe, with its `last_success_at`; one capability hold, operator-owned, deadlined, bound to the fact, remedy `needs_remediation`. And: the record names both declared instants and that a refresh credential is present, and the fact's detail says the expiry is the credential's own claim, not the provider's answer.
- **(d2b) The residual of (d): a revoked credential, or one expired without declaring it.** Neither changes a local byte, so it is modeled by leaving the usable credential (a throwaway API key, which declares no expiry) exactly as the probe has just read it; that it is byte for byte unchanged is asserted. It asserts what the contract requires, the same as (d1). **It fails**: the probe records `usable` and the fact stays `healthy`, which is what (d) forbids. That failure is the finding F1 leaves to the operator.
- **(e) Characterization.** The pinned runner from the image, with no network at all (`--network none`), over each throwaway credential shape in a fresh 0700 auth home. The probe's own rules are applied to its raw output; then, for a shape the runner reads as usable, the probe's own reader and rule take the declared expiry from the same bytes. This pins what codex 0.153.2's local check tells apart, and what the declared expiry adds:

| Credential shape (throwaway) | codex exit | its stderr line | the runner's answer, by the rules | the probe's outcome | Gap, or what decides |
|---|---|---|---|---|---|
| absent | 1 | `Not logged in` | unusable_credential | unusable_credential | |
| API key | 0 | `Logged in using an API key - sk-throw***…` | usable | usable | |
| empty API key `""` | 0 | `Logged in using an API key - ***` | usable | usable | an empty key reads as a credential |
| `{}` | 0 | `Logged in using ChatGPT` | usable | usable | an empty object reads as ChatGPT tokens |
| ChatGPT tokens, unexpired (2100) | 0 | `Logged in using ChatGPT` | usable | usable | |
| ChatGPT tokens, expired (2001) | 0 | `Logged in using ChatGPT` | usable | **declared_expired** | the command reads them as logged in; the tokens' own declared expiry decides, not the provider (a refresh token is present) |
| the same, empty refresh token | 0 | `Logged in using ChatGPT` | usable | **declared_expired** | as above; no refresh credential |
| access token expired (2001), ID token unexpired (2100) | 0 | `Logged in using ChatGPT` | usable | **declared_expired** | the access token's declared expiry decides |
| access token opaque, ID token expired (2001) | 0 | `Logged in using ChatGPT` | usable | usable | an opaque access token declares no expiry; the ID token's decides nothing |
| an API key beside expired tokens | 0 | `Logged in using an API key - sk-throw***…` | usable | usable | codex uses the key, which declares no expiry |
| ID token not a JWT | 1 | `Error checking login status: invalid ID token format …` | unusable_credential | unusable_credential | |
| malformed JSON | 1 | `Error checking login status: key must be a string …` | unusable_credential | unusable_credential | |
| empty file | 1 | `Error checking login status: EOF while parsing a value …` | unusable_credential | unusable_credential | |
| mode 000 | 1 | `Error checking login status: Permission denied (os error 13)` | unusable_credential (permission denied) | unusable_credential | |

Each row is asserted, both outcomes. A future runner version that tells more
cases apart fails its row, and the rules and the reader are reviewed with
the version pin. (Also seen by hand with the pinned binary, offline: an
`OPENAI_API_KEY` string, even empty, is what codex uses over tokens beside
it, and an auth.json with no `refresh_token` field is a parse error, exit 1.
The reader follows the first.)

- **Store read-back.** After the engine stops (SIGINT, its own close path; asserted: no WAL file is left), a copy of the store file is read. It checks that every probe reply the run received is recorded and nothing else is, with each recorded reply equal to the one received; that the fact history of `provider-auth:codex` is one chain of state changes; that every capability hold is bound to a fact not healthy; and that every hold the run opened was cleared by an operator decision. The run also checks that the throwaway operator token appears in no kept file: the run log, the engine log, the store copy or the characterization output.

## What this does and does not establish

It establishes, for this image and runner version:
- The auth volume survives restart and replacement. Its ownership (10001:10001), its mode (0700), the credential's bytes, mode and inode, and the router's record of the capability all carry across a new container.
- A credential replaced in the live volume is read by the next probe. No rebuild, recreation or restart is needed, because the runner reads its auth home afresh on every run and the volume is mounted as a directory.
- Two probes run the pinned runner against one auth home at the same moment: two `codex login status` processes were live at one instant, seen in the engine container's process table, and a serialized runner fails that assertion (c-control). Neither probe misclassifies, and the credential file is as before after every round.
- A credential the pinned runner itself rejects becomes a dated failing fact and a typed, owned, deadlined operator hold, visible in operator status. It never reads as a success.
- A credential whose access token declares an expiry that has passed becomes a dated degraded fact and the same hold, labeled as the credential's own claim.
- The probe's classification needs no network: every verdict in (e) was reached with none, and the declared expiry is read from the file.

It does not establish:
- **Anything about a live provider.** No request was sent to any provider, and no credential in this run can authenticate anywhere. "Usable" means only that codex 0.153.2's local check reads a credential. It does not mean the provider would accept it.
- **Revocation, or an expiry the credential does not declare** (F1, (d2b)). Nor that a declared-expired credential is refused by the provider, or that one declaring a later expiry is accepted: a declaration is read, never verified, and a refresh credential may renew an expired access token. An empty API key and an empty JSON object also still read as usable.
- **Concurrent credential writes.** `login status` only reads the credential. codex writes it when it refreshes ChatGPT tokens, which needs a live provider, so two simultaneous refreshes against one auth home were not exercised. codex does write beside the credential on every run: a `tmp/arg0/codex-arg0*` helper directory with a lock file (F2). Those concurrent writes were exercised, and the credential stayed intact.
- **Per-job auth-home isolation.** The auth volume is mounted into the engine container, and the supervisor's jobs are processes in that container under the same uid. So every job can read every mounted auth home (F3). The contract's "no auth home is mounted into a job that does not need that provider" holds only at the container level here.
- **No egress.** The engine's Compose network is an ordinary bridge. A Compose `internal` network has no egress, but it also cannot carry the contract's host publication (tried: the published port refused connections). The runner's independence from the network is shown by (e), not by fencing the engine.
- **Other runner versions.** The rules are codex 0.153.2's. Any other version is a `runner_error` by construction (the probe checks `--version` first), so a runner upgrade must re-run (e) and review the rules.
- **Alert on transition** (H-2's alert channel is Phase 3). The fact and the hold are recorded and shown; nothing pages anyone.

## Findings (where reality and the contract differ)

**F1 — what a local probe can and cannot see of an expired or revoked credential (normative; operator decision).**
Corrected after the 1f review (finding 1), which showed the first version of
this finding conflated three different questions. Four facts, each stated
at its own size:

- **What the selected status commands report.** codex 0.153.2's
  `login status` reads ChatGPT tokens whose JWTs expired in 2001 as
  `Logged in using ChatGPT`, exit 0 ((e)). claude 2.1.283's `auth status`
  says `loggedIn: true`, exit 0, for an OAuth token whose `expiresAt` has
  passed (appendix). The review reproduced both offline (`--network none`).
  Nearby signals are no better: `codex doctor --json` reports
  `auth.credentials: ok` for the expired tokens (its separate network checks
  fail offline, so it is not a local check), and a credential file's age is
  not an expiry signal (a fresh file of expired tokens and an old file of
  unexpired ones both read as logged in).
- **Locally visible declared expiry: it exists.** A JWT's `exp` claim is
  the instant on or after which it must not be accepted (RFC 7519
  §4.1.4). codex's access and ID tokens are JWTs: the (d2a) fixture's both
  decode to `exp` 1000000000, 2001-09-09T01:46:40Z, and the unexpired
  fixture's to 4102444800, 2100-01-01. claude's credential JSON states
  `expiresAt` directly, in milliseconds. None of this needs the provider.
  The probe now reads it (task 1f-repair): once the runner reads a
  credential as usable, the probe reads the same file for what it declares,
  records each token's declared instant and whether a refresh credential is
  present (`declared_expiry`), and, when the access token declares an
  expiry at or before the observation, records the new outcome
  `declared_expired`: a dated `degraded` fact and the typed hold, labeled
  "the credential's own claim, not the provider's answer" ((d2a)). The
  runner's rules are unchanged, and `usable` still means the runner reads a
  credential whose access token does not declare itself expired. The probe
  also carries a reader for claude's `expiresAt` (`claude_declared`), for a
  claude runner once one is pinned; no claude runner is pinned in this
  image, so that reader is shown only by the unit tests' fake runner.
- **Refreshability.** Reading a claim is not authentication: these
  fixtures are unsigned, and the probe verifies nothing. ID-token and
  access-token expiry are different things: the access token is what is
  presented to the provider, so only its declared expiry decides, and the ID
  token's is recorded and decides nothing ((e): an opaque access token beside
  an expired ID token reads usable). An expired access token can sit beside
  a usable refresh credential, which the runner may use to renew it on its
  next use; the probe records whether a refresh credential is present, and
  cannot tell whether a refresh would succeed without asking the provider.
  So a `degraded` fact from a declared expiry can be a false alarm: where a
  provider's access tokens are short-lived and renewed on use, a credential
  idle past its access token's expiry reads degraded and opens a hold
  though it may still work. How often that happens depends on the
  provider's token lifetime, which was not measured. Opaque credentials (an
  API key, an opaque token) declare no expiry, and this signal gives no
  verdict on them.
- **Unseen revocation.** A revocation at the provider changes no local byte
  and no metadata, and neither does an expiry the credential does not
  declare. With no new information from the provider, identical local
  inputs give an identical local verdict, so no local inspection can be
  guaranteed to see either. This is a conditional indistinguishability
  argument, not an empirical test: no live revocation was performed.
  (d2b) shows its local side: the credential left byte for byte as the probe
  just read it usable is read usable again, and the demonstration asserting
  (d) for it fails.

So, of what (d) names, a dated fact and a typed hold are shown for a
credential the runner rejects (d1) and for one whose declared expiry has
passed (d2a, with the limits above: a claim read, not the provider's
answer), and not for a revoked credential or an undeclared expiry (d2b).
Whether that satisfies (d) is the operator's ruling. Options, for the
operator (none is taken here):
- **(i)** Allow the probe an authenticated, non-billing exchange with the provider. For OAuth runners that is the token-refresh handshake (claude's status command appeared to start one in the manual run of the appendix, not reproduced by the review). It would see revocation and real expiry, and settle whether a declared-expired token still renews. It needs network access to the provider's auth endpoint and real credentials, so it cannot be demonstrated with throwaway credentials except against a provider stub.
- **(ii)** Amend (d)'s Phase 1 obligation to what local inspection covers: a credential the pinned runner rejects, and one whose declared expiry has passed (with whether that is `degraded` or `failing`, and whether a present refresh credential should change it, stated). Make a later-phase obligation of the residual that actually prevents the Monday discovery the contract describes: a real invocation's authentication failure is classified by the supervisor as a capability failure (a fact and a hold), never as a zero-result pass.
- **(iii)** Both.

The declared-expiry reading is a supplementary signal, added under the
repair brief; whether it counts toward (d), and the fact state it maps to,
are the operator's to confirm. The contract has not been changed. §4's
status note points here.

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
now asks `docker inspect` of the container for only the fields it asserts
on. Its image and volume inspections still keep the whole documents; those
carry the image's baked defaults and the volumes' options, not the env-file
secrets.

**Deployment notes (not contract discrepancies):**
- The engine installs no SIGTERM handler, and the `app` module has no `signal` grant. The compose slice stops it with `SIGINT`, which reaches its own `KeyboardInterrupt` → `Engine.close()` path, and runs it under `init: true`. The read-back asserts that close ran: no WAL file is left beside the stopped store. Without that setting, `docker stop` sends SIGTERM, not SIGKILL after the grace period: with `init: true` the engine ends on it at once (the 1f review measured exit 143 in about 0.12 s against a 3 s grace; SIGINT, exit 0 in about 0.58 s), without running its close path, so the store's WAL durability is all that protects it then.
- The store is created once, explicitly (`init-store`). A missing store is a startup error, not a mode (INVARIANTS §11.2).
- Mount auth homes as directories, never as single-file bind mounts. An atomic credential replacement (rename) is not visible through a single-file bind mount. This is Docker behaviour and was not demonstrated here.

## Reproduce

```
make gen2-auth-demo                 # everything; the driver exits 1 (make: 2) while F1 stands (d2b)
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
`summary.json`; `engine.log`; `characterization.json`;
`c-processes.json` and `c-control-processes.json`, the sampler's records;
`c-control/`, the serialized probe and its compose override; and `store/`,
the store copy.

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
  - The same token with `expiresAt` in 2001: `loggedIn: true`, exit 0, and an `.oauth_refresh.lock` directory left behind (in this run; the 1f review's own fixture reproduced the verdict, not the lock).

  Every run wrote `.claude.json` and a `backups/` entry into the config
  directory.

