# gen-2 CI design — proposal for Astra review

Status: **PROPOSAL** (orchestrator, 2026-10-04). Nothing here is enabled or merged until the operator rules on §8.

This design builds on the existing platform and does not replace it:
- `trevorbyrum/ci-cd`: `ARCHITECTURE.md`, `PLAN.md`, `docs/archgate.md`, `docs/agent-ci-guide.md`, `lib/vars/standardPipeline.groovy`;
- the `gen2` Jenkinsfile merged in PR #1 (`ea5a699`).

The platform's trust model is adopted unchanged: the ci-manager and ci-worker VMs, the App-pinned required check, and agents with no merge rights.

The operator asked for three things:
- do not just put the current verification routine onto CI;
- use the evidence to decide what CI should do for *this* build;
- note what we don't cover yet.

## 0. What exists today

| Thing | State | Observation |
|---|---|---|
| Jenkins (`ci/std` check) | `Jenkinsfile` calls `standardPipeline(image: 'ci-py312-noble:1', lint: 'make gen2-boundaries gen2-size', build: 'make gen2-venv', unit: 'make gen2-check', timeoutMinutes: 50)` | Runs the whole 13-target `gen2-check` as one "unit" stage, about 32 min on 2 CPU / 4 GB. It produces no JUnit XML. **`make gen2-gateway` is not run at all**, because the image has no PostgreSQL binaries. The platform's `arch-gate` also runs, but in observe mode, because gen2 has no `archgate.toml`. |
| GitHub Actions `gen2-check.yml` | Runs on every push to the public repo, on `ubuntu-latest` | **It fails today.** On a newer Python 3.12 patch release, `test_gateway_routes.TheEndpointForms` expects `::ffff:7f00:1` but gets `::ffff:127.0.0.1` (run 37178375414). The Jenkins PR's dry run found the same thing on 3.12.15. Two CI systems are running one job on two different interpreters, and only one of them matches ENVIRONMENT.md. |
| Orchestrator reruns | For every coder landing, I re-run both targets by hand (about 45–60 min) before or alongside Astra | This is the de facto verifier of record. It runs on the developer machine against the shared working tree and blocks the next coder while it runs. |
| Astra reviews | Each review re-runs both targets in a disposable checkout (about 35–40 min) on top of its adversarial probes | This doubles the target runtime per round and spends Codex budget on work a machine can do. |

## 1. What this build taught us → CI requirements

Each issue below happened during the 2a–2q work and is recorded in REVIEW-LOG. Each maps to a requirement (R#).

1. **Coder self-reports need an independent check; the check has to be cheap and automatic.** The orchestrator's reruns always matched, but each cost about 45–60 min and occupied the shared tree.
   - **R1:** CI on a clean checkout of the exact SHA is the *verifier of record*. Coder claims are compared with CI results, not with a hand rerun.
   - Research: intrinsic self-correction without an external oracle degrades, while external execution feedback works (`llm-performance-evidence`: self-correction findings; Reflexion).
2. **Agents iterate against tests and can game them.** Test-driven iteration raises both genuine pass rates and reward-hacking rates (`llm-performance-evidence`, Conflicting-SWE-bench finding; EvilGenie benchmark). Observed here: the "independent oracle" had to be protected by hand-run `git diff` checks every round. Mutants were "killed" by `KeyError` crashes rather than by assertions (2q-a-repair-2, R4). Tests encoded rejected exemptions (2q-a-repair, R5).
   - **R2:** protected paths and test-integrity diffs are checked by CI, not by people.
   - **R3:** mutation kills are classified, and a crash is not a kill.
3. **Review rounds circled when each finding was fixed in isolation.** The family-level rule and Gate D fixed the process. But each finding also existed only as a reviewer's probe until a coder rebuilt it.
   - **R4:** every accepted review reproduction becomes a permanent regression that runs in CI, with an owner and a trace to its finding ID, so a fixed family cannot quietly reopen.
4. **Feedback was slow and came at the wrong moment.**
   - Full mutation runs every time (about 20 min engine, 15 min gateway).
   - Research: the same static analysis had a near-zero fix rate as a nightly batch but above 70% when delivered at diff/review time (`codegraph-evidence`, Infer at Facebook).
   - Research: mutation testing should be scoped to changed code per PR, with a full run kept as the backstop (`agentic` Branch 14; mutants.rs and Mull docs: "not a substitute for a full run").
   - **R5:** tiered pipeline: fast gates in seconds; tests and diff-scoped mutation per change; full mutation on integration and nightly.
5. **Timing-dependent tests appeared repeatedly.** Examples: the supervisor start-grace race, the recorder-startup race, and readiness helpers. Each was found by chance, and "a green rerun is not a fix" had to be argued every time.
   - **R6:** no automatic retries; flips on an identical SHA are recorded; scheduled stress runs look for timing and order dependence on purpose; quarantine only via PR, with a cap (platform F4).
6. **The environment drifts silently.** The reference environment is pinned at Python 3.12.3 / SQLite 3.45.1, yet a portability defect in the gateway client's canonical origin passed every review because nobody ran another patch release.
   - **R7:** the reference environment stays the *gate*. A scheduled drift job runs current 3.12.x / 3.13 and reports, so drift is found before deployment, not after.
7. **The no-live-calls rule was enforced in software only** (Python audit guards, "make no live provider calls" in every brief).
   - **R8:** test and mutation containers run with **no network** (`--network none`). The rule then holds by construction, for any agent, any test, and any future dependency.
8. **The gateway database suite isn't in CI**, and the static analysis behind the metrics ratchet keeps meeting Python forms it can't model (2q-a, three BLOCKs).
   - **R9:** CI runs the PostgreSQL gateway suite.
   - **R10:** CI enforces whatever supported-source contract Gate D #4 sets, so the analyser only has to be exact inside it. This matches the "soundy" practice: a sound core, plus explicit refusal or under-approximation of named hard features (`codegraph-evidence`, soundiness findings; PyCG recall about 70% on dynamic constructs).
9. **There are two architecture mechanisms for one job.** gen2 has `gen2-metrics` (ratcheted, ledgered, mutation-tested). The platform adds `archgate` (lizard CCN, its own graph and boundary rules). The same function would get two complexity numbers. This is exactly the "two mechanisms for one job" smell Gate D looks for.
   - **R11:** one authoritative ratchet per repository. The platform's slot runs gen2's checker as the adapter, as `ARCHITECTURE.md` Layer 2 already allows for repos with "gen2-grade needs".
10. **Evidence lived in ad hoc directories**, and `/tmp` evidence was lost on reboot.
    - **R12:** CI archives a per-SHA evidence bundle with a stable schema, and the orchestrator and Astra link to it.

## 2. Principles (with evidence)

- **P1 — An external oracle, not self-report.** The coder never certifies their own work. The verdict comes from CI on a clean checkout and from Astra. (`llm-performance-evidence`)
- **P2 — Deliver findings when the change happens.** Fast gates run on every push. Expensive gates still run per change but scoped to the change, with full runs as a backstop. (`codegraph-evidence`, Infer delivery-timing finding)
- **P3 — Determinism over retries.** A failure is real until shown otherwise. A flake is a recorded defect with a deadline. (Platform F4; `agentic` Branch 14 quarantine with a hard cap; Fowler on non-determinism)
- **P4 — Guarantees by construction where it's cheap.** Network isolation, read-only protected paths, and clean checkouts. Promises in briefs are not guarantees.
- **P5 — A soundy analysis with an explicit boundary.** An analysis that is exact on a declared subset and refuses what it can't model. Don't grow an analyser to cover all of Python. (`codegraph-evidence`)
- **P6 — One mechanism per job.** If two checks measure the same property, one must be authoritative and the other removed or explicitly advisory.
- **P7 — Findings become tests.** A fixed review finding is a permanent, traced regression (R4).

## 3. Design

### 3.1 CI's role in the build loop (what changes)

| Today | Proposed |
|---|---|
| Coders commit directly to `gen2` on the one shared working tree; one coder at a time. | Each task is a branch `<agent>/<task>` in its **own git worktree**, opened as a PR into `gen2`. `ci/std` is a required check on `gen2`, and Astra reviews the PR's head SHA. The operator, or the orchestrator under an explicit operator policy, merges. Disjoint tasks could then run in parallel. Under the client-model ruling this only matters for coders; CI capacity limits it (§3.7). |
| The orchestrator re-runs both targets by hand for every landing. | The orchestrator reads the CI result for the PR head SHA. It re-runs locally only if CI is unavailable or disagrees with the coder. |
| Astra re-runs both targets in every review. | Astra cites the CI evidence bundle for the pinned SHA and spends the time on adversarial probes. It still may (not must) re-run any target it doubts. *Saves about 35 min and a large share of Codex budget per round. The trade-off is independence from CI's environment, which is acceptable because CI runs the reviewed reference image. Decision D3.* |
| Review probes live in `private/evidence/astra-*`. | Accepted probes are turned into tests by the next coder (already the practice). CI then tags them with their finding ID (R4), and `ci-results.json` lists the finding-regression set that passed. |

### 3.2 Pipeline tiers

All tiers run in the pinned reference image `ci-py312-noble`. It is extended to include the PostgreSQL server binaries, so `gen2-gateway` runs. Network is `none` from tier 1 on.

| Tier | When | Contents | Target time | Blocking |
|---|---|---|---|---|
| **T0 fast gates** | every push and PR update | `gen2-sqlite`, `gen2-boundaries`, `gen2-size`, `gen2-schemas`, `gen2-ddl`, `gen2-catalog-check`, `gen2-metrics`, `gen2-debt`, `gen2-locators`, the **protected-path policy** (§3.3), the **test-integrity diff** (§3.3), secret/personal-data scan | < 3 min | yes |
| **T1 tests** | every PR update | engine tests (`gen2-test`) and the gateway suite without a DB, in parallel; JUnit XML for both | about 12 min at 2 CPU | yes |
| **T2 gateway DB** | every PR update | gateway suite against a throwaway PostgreSQL inside the container | about 4 min | yes |
| **T3 diff-scoped mutation** | every PR update | the engine and gateway mutants whose target files changed against the merge base, *plus* mutants whose killer tests are in changed test files; trigger-order check if DDL changed | scales with the diff (typically < 10 min) | yes |
| **T4 full verification** | on merge to `gen2`, and nightly | full `gen2-mutation`, full gateway mutants, `gen2-trigger-order`, absolute metrics audit (no ratchet credit), `gen2-hotspots` report | about 45 min | a failure blocks the **next** merge until fixed (the "main is red" rule) |
| **T5 hardening (nightly)** | nightly | randomized test order with a recorded seed; *N=5* repeat runs of process, timing and lease tests (supervisor, recorder, readiness, deadline); environment-drift matrix (latest 3.12.x, 3.13; latest SQLite); dependency audit (`pip-audit` on the hash-locked requirements) | about 60 min, off-peak | report-only; each finding becomes a task |

Why T3 is enough per PR: mutation measures how strong the tests are where the code changed, and the research and tooling consensus is "PR-scoped plus a full backstop". T4 catches the case where an edit in one file weakens tests for another.

### 3.3 New gen-2 gates (not covered today)

1. **Protected-path policy (T0).** Each of these paths has a declared owner:
   - the oracle: `gateway/tests/oracle/**`, `gateway/tests/test_oracle.py`;
   - the metrics state: `docs/gen2/metrics-baseline.json`, `metrics-ledger.md`, `metrics-exemptions.md`;
   - `DEBT-REGISTER.md`, `phase-status.json`;
   - `gen2/boundaries.toml`, INVARIANTS, BUILD-CHARTER;
   - the mutation-controls JSON;
   - `Jenkinsfile`, `.github/**`.

   A PR that touches one must carry an explicit declaration (a trailer such as `Protected-Change: <path> — <reason> — <review>`). CI prints the diff as **PROTECTED CHANGE**, the same way the platform prints CONTRACT CHANGE. The oracle stays **immutable** except through a separately authored oracle task.
2. **Test-integrity diff (T0).** Compared with the merge base, CI reports:
   - test methods removed or renamed;
   - new `skip`/`skipIf`/`expectedFailure`;
   - assertions removed from an existing method (AST count per method);
   - a test file deleted;
   - a mutant's killer or control list changed.

   Each of these needs a declared reason, as with protected paths. This turns "your agent will pass any test it is allowed to edit" (EvilGenie, and the reports of tests being rewritten into tautologies) into a reviewable diff instead of a silent change.
3. **Mutation kill-reason classification (T3/T4).** The mutation runners record *why* each mutant died: assertion failure, error or crash, timeout, or import failure. Only assertion failures and expected-exception tests count as kills. A crash-kill counts as a **survivor**, unless the mutant is declared `kill: error` with a reason. This fixes the 2q-a-repair-2 R4 class permanently, in the harness instead of per mutant.
4. **Network isolation (T1–T5).** Containers run with `--network none`. PostgreSQL is reached over its Unix socket inside the same container, and loopback still works. Any test that needs the network fails loudly. This replaces reliance on the Python offline guard for CI runs; the guard stays for local runs.
5. **Secret and personal-data scan (T0).** The repo is **public**. Scan the diff (gitleaks-style rules plus repo rules: operator email, home-directory names beyond the existing allow-list, tokens, `.env` content). The charter's no-personal-data rule is currently enforced only by briefs.
6. **Evidence bundle (all tiers).** `ci-results.json` (platform schema) plus `gen2-evidence.json`, with:
   - per-target exit, duration and counts;
   - test totals and the skip list;
   - mutants: total, killed by assertion, crash-kills, survivors, and which have paired controls;
   - the metrics delta and ledger entries;
   - the protected-path and test-integrity reports;
   - the finding-regression set.

   Artifacts are kept per SHA, so `/tmp` loss can't recur.

### 3.4 The architecture ratchet: one mechanism

- **gen2-metrics stays authoritative.** It is already ratcheted, ledgered, mutation-tested and reviewed. In the platform's arch-gate slot it should run as gen2's adapter, as `ARCHITECTURE.md` Layer 2 allows. Platform `archgate` either stays observe-only for gen2 with its report marked *advisory, superseded by gen2-metrics*, or is disabled for gen2 if the library supports a documented per-repo adapter. **Ask to ci-cd (C3).**
- **CI enforces whatever supported-source contract Gate D #4 rules on.** If Gate D chooses a declared subset, the refusal guard is a T0 gate. CI doesn't settle that question; it gives the ruling a gate to live in.
- The ledger's reasoned admissions appear in the PR check output as **LEDGER CHANGE**, so review attention lands on them.

### 3.5 Flakes

- **No automatic retries** (platform T7).
- When a test fails and then passes on the same SHA, that is recorded in `gen2-evidence.json`.
- Nightly T5 repeat runs score process and timing tests over time, giving a reliability number, not a yes/no flaky label (`agentic`: "how flaky, not whether").
- **Quarantine only via a PR** that moves the test to a quarantine suite. The cap is the platform default (5 tests or 14 days). Each quarantine entry becomes a DEBT-REGISTER item with its owning task, so the existing phase-close check prevents permanent quarantine.

### 3.6 Environment

- **Gate:** ENVIRONMENT.md's reference (Python 3.12.3, SQLite 3.45.1) via the digest-pinned `ci-py312-noble` image, extended with PostgreSQL 16 server binaries.
- **Drift (T5, report-only):** latest 3.12.x, 3.13, and latest SQLite. A failure becomes a task, not a red gate.
- **Immediate finding, outside CI:** the gateway client's canonical-origin and IPv4-mapped formatting depends on `ipaddress.__str__`, which changed across 3.12 patch releases. That makes the 2b acceptance specific to the patch version. It should go to a small engine task whose root fix is to canonicalize independently of `__str__`, or else ENVIRONMENT.md must pin the patch version explicitly (operator choice, D5).

### 3.7 Platform constraints and change requests to `ci-cd`

`ci-cd` is the trust root and is changed only by human merge. gen2's needs exceed the current single-call contract.

| # | Constraint today | Ask |
|---|---|---|
| C1 | One `unit` stage; no repo-defined stages; no nightly per repo yet (`.ci.yaml` is phase 2) | Allow tiered commands, e.g. `stages: [fast, tests, gateway_db, mutation_diff]`, plus a nightly command (T4/T5) through `.ci.yaml`. |
| C2 | Caps of 2 CPU / 4 GB and a 60-minute ceiling | Raise gen2's caps for T4/T5 (tower headroom is large), or allow parallel containers per tier. T4 at 2 CPU is close to the ceiling. |
| C3 | archgate always runs; it is configured only through `archgate.toml` | A documented "repo adapter" mode that runs gen2's checker in the arch-gate slot (P6). |
| C4 | Containers have network access | A `network: none` option for test stages (R8), at the Layer-0 level if the platform agrees it is a good default. |
| C5 | `ci-results.json` v0 has no place for repo evidence | A sanctioned extension point (`extensions.gen2`), or archiving `gen2-evidence.json` alongside it. |
| C6 | No support for the protected-path or test-integrity policy | Either a library stage (it is generic and useful fleet-wide) or gen2 runs it in T0. |

Until those land, a **minimum viable** version fits the current single-call contract:
- `lint`: the T0 commands, including the new protected-path, test-integrity and scan tools;
- `build`: the venv;
- `unit`: a new `make gen2-ci` that runs T1, T2 and T3 and writes JUnit;
- T4/T5: a separate scheduled job owned by the platform.

### 3.8 GitHub Actions

Two CI systems for one job is the P6 smell. `gen2-check.yml` also runs on an interpreter ENVIRONMENT.md does not declare. **Recommendation:** delete it once `ci/std` is the required check, *or* turn it into the T5 drift job (non-required, scheduled, latest 3.12/3.13), since free GitHub runners suit report-only drift. Decision D4.

### 3.9 Architecture checks in every tier (operator requirement, 2026-10-04)

The operator's requirement: CI should cover as much architectural complexity and coupling as it realistically can, with some architecture checking in **every** tier, light where speed matters and deeper where time allows. It should also produce whatever helps the architecture review (Gate D).

The scaling rule:
- **cheap, diff-scoped checks run when the change is made**, and they block (Infer's evidence: findings delivered at diff time get fixed, nightly batches don't);
- **deep, whole-system checks run on merge and nightly**, and they feed Gate D and the trend record.

| Tier | Architecture checks | Blocking? | Status today |
|---|---|---|---|
| **T0 (every push, seconds)** | (a) boundary graph (`gen2-boundaries`); (b) ratchet of import edges, fan-in/out, reach, propagation cost, cycles, smells and per-function complexity (`gen2-metrics`); (c) the supported-source guard Gate D #4 decides; (d) file-size rule; (e) **a change-impact summary** in the check output: edges added or removed, components touched, the *blast radius* (files that transitively depend on the changed files), and complexity deltas for changed functions; (f) CONTRACT, LEDGER and PROTECTED CHANGE banners | (a)–(d) and (f) yes; (e) informational | (a), (b), (d) exist; (c) pending Gate D #4; (e) and (f) new |
| **T1 (per PR, minutes)** | (g) **interface-stability diff**: each component's public surface (exported names and signatures, the JSON schemas under `gen2/schemas`, DDL tables and columns, the gateway HTTP/MCP routes) compared with the merge base, flagged as INTERFACE CHANGE; (h) **observed runtime coupling**: while the test suite runs, an import and call recorder logs the cross-component module edges that actually happen. Any runtime edge between components that the static graph lacks is a **blind-spot finding**, meaning the static analysis missed coupling. This is the backstop for the 2q-a problem, where static analysis can't see some Python forms. Research: static and dynamic graphs miss different edges, combining them gives the best recall, and dynamic traces are only as good as test coverage, so they supplement the static graph and are never treated as ground truth; (i) **test locality**: which components each test module exercises. A unit test that pulls in unrelated components is a coupling smell, and the same map gives test-impact analysis (`agentic` Branch 7: regressions cut by 70%) | (g) yes, unless declared; (h) yes for blind spots, which need an analyser fix or a declared exemption; (i) informational | all new |
| **T3 (per PR)** | (j) architecture-rule mutants: the mutation harness already includes mutants that weaken the boundary and metrics checkers, so a PR that changes those tools is mutation-tested on the changed rules | yes | exists for gen2-metrics |
| **T4 (merge and nightly, deep)** | (k) **absolute audit**: every function, file and component is held to absolute ceilings, with no ratchet credit, so baselines can't become permanent permission; (l) **change coupling and hotspots** (`gen2-hotspots`): files that change together with no static edge are *hidden coupling*, and churn × complexity gives a ranked hotspot list. Research: network centrality predicts defects better than complexity alone (Zimmermann & Nagappan, `software-architecture` F113); (m) **duplication detection**: token- and AST-based clone detection across the engine and gateway, ratcheted. Agent-written code measurably duplicates more and reuses less (GitClear 2025; *More Code, Less Reuse*, arXiv 2601.21276); (n) **dead code** (vulture-style, with a reviewed allow-list); agents leave dead code behind; (o) **cohesion**: classes or modules whose methods share no state or callers, a split candidate; (p) **type-contract coverage** at component boundaries: are the public functions crossing a boundary annotated, and do they type-check (mypy/pyright on boundary modules only, ratcheted)? Untyped boundaries are where implicit coupling hides; (q) **layering and stability**: Martin's stable-dependencies and stable-abstractions measures per component, reported as a trend | (k) yes; (l), (m), (n), (p) ratcheted once a baseline exists; (o), (q) report-only | (k), (l) partly exist (`gen2-hotspots` report-only); (m)–(q) new |
| **T5 (nightly) and the Gate D pack** | (r) **trend series**: every merge appends the T0–T4 numbers to a time series, so Gate D sees how they move, not single snapshots; (s) **traceability**: each flow-document stage and INVARIANTS entry is mapped to its code locators and tests (the locator check already parses these), giving an implemented / scheduled / missing table; (t) **a Gate D input bundle**, generated, not hand-assembled: the trend series, current smells, hotspots, hidden coupling, blind-spot findings, interface changes since the last Gate D, duplication and dead-code deltas, the traceability table, the defect-family history (REVIEW-LOG findings grouped by family) and the debt register; (u) freshly regenerated scaffolding views (CodeGraphContext, Emerge) attached as non-gating artifacts | report-only (they feed Gate D) | (u) exists manually; the rest are new |

Gate D keeps its judgment. The bundle replaces the measurement work each Gate D session has redone by hand (Gate D #1 and #2 each re-ran `measure.py`, cgc and emerge). The reviewer spends its budget on interpretation. The same bundle also makes the charter's "every regression since the last Gate D explained" requirement mechanical.

**Realism limits, stated:**
- Static and dynamic coupling measurements are both partial (soundiness; dynamic recall is bounded by test coverage).
- Duplication and dead-code detectors produce false positives, so they ratchet against a reviewed baseline rather than gate on absolute counts.
- Cohesion and stability metrics are proxies, reported as trends, never as pass/fail truths.
- Every new check starts in observe mode for a few merges before it is allowed to block (platform F2).

## 4. What we don't cover today (beyond the above)

1. **Supply chain:** no dependency vulnerability audit; no SBOM; no provenance for anything built (SLSA is out of scope until there is a deployable artifact, in 2e1/Phase 4; self-hosted runners top out near Build L2).
2. **Documentation and claim drift:** BUILD-STATE and REVIEW-LOG test counts are written by hand and can't be checked. CI could publish the counts and a doc check could compare them.
3. **Coder attribution metrics:** the platform's per-agent failure and revert metrics (`agentic` Branch 17) aren't wired for gen2. Coders changed model three times this week (Opus → Sonnet → Sol); per-agent failure profiles would show which model needs which scrutiny.
4. **Performance regression:** decode-cost numbers (Crossref, BEA) are measured by hand once per task; there is no regression budget.
5. **Migration and DDL rehearsal:** the pre-change store is refused but untested in CI. The Phase 4 migration needs a CI rehearsal on synthetic old stores.
6. **Review-loop economics:** nothing measures rounds per task or Codex/Claude spend per round. A CI-side "round counter" per task branch would make the charter's three-BLOCK Gate D trigger mechanical rather than remembered.
7. **Deployment smoke:** 2e1 brings a dedicated gen-2 gateway and runner. CI will need an integration environment (compose-based, network-isolated except for the internal network) before 2f.
8. **Code review assist:** platform T8 (advisory LLM review) could run on every gen2 PR as a non-required check. Astra stays the gate.

## 5. Rollout

1. **Phase A (no code change to gen2's process):**
   - fix the `ipaddress` portability defect (task);
   - extend the image with PostgreSQL;
   - `make gen2-ci` running T1–T3;
   - T0 gates added in observe mode;
   - deal with GitHub Actions (D4).
2. **Phase B:**
   - enable the protected-path and test-integrity gates in block mode;
   - mutation kill-reason classification;
   - `--network none` (with C4 or a gen2-side wrapper);
   - evidence bundle.
3. **Phase C:**
   - move coders to task branches, worktrees and PRs with `ci/std` required on `gen2`;
   - the orchestrator stops manual reruns after **5 consecutive landings** where CI and the orchestrator's rerun agree exactly (a measured hand-over, not assumed);
   - Astra cites CI evidence (D3).
4. **Phase D:** nightly T4/T5 via `.ci.yaml` (C1); drift matrix; flake scoring; dependency audit.

Each phase is a build-out: a branch, tests, then operator confirmation before merging into `gen2`.

## 6. Risks

- **Trusting CI as the verifier of record makes CI a single point of failure.** Mitigations: the platform's trust model (an App-pinned check; agents with no Jenkins write access); the five-run agreement hand-over; Astra keeps the right to re-run.
- **Diff-scoped mutation can miss cross-file weakening.** T4 runs on every merge, and the "main is red" rule blocks further merges.
- **Protected-path declarations can become rubber stamps.** They are only a signal; Astra and the operator still review. CI prints them prominently.
- **Parallel coders** bring merge conflicts and contention for reviews. Start at 2 concurrent tasks, at most.

## 7. Evidence used

**GraphRAG corpora:**
- `llm-performance-evidence`: test-feedback reward hacking (Conflicting-SWE-bench); intrinsic self-correction degrading without an external oracle; static-analysis feedback loops; test-oracle strength (EvalPlus).
- `codegraph-evidence`: soundiness as industry practice; PyCG recall limits on dynamic Python; Infer's diff-time versus nightly fix rates; compositional incremental analysis.
- `agentic`:
  - Branch 7 (test impact analysis cut regressions 6.08% → 1.82%);
  - Branch 14 (mutation score over coverage; scope mutation to changed code; flaky quarantine with a hard cap);
  - Branch 17 (CI with coding agents: test-health classification for agents; a cheap check per push with the expensive suite once in the queue; per-agent failure profiles and attribution).
- `software-architecture`: build/CI enforcement turns silent routing-around into a reviewable diff (F109); fitness functions for ADRs.

**Web:**
- mutants.rs and Mull incremental mutation docs (diff-scoped runs are not a substitute for full runs);
- EvilGenie (arXiv 2511.21654) and practitioner reports on agents editing tests;
- SLSA provenance notes for self-hosted runners;
- Jenkins docs and issues on docker agents and parallel stages (JENKINS-47103).

**Platform:** `trevorbyrum/ci-cd` ARCHITECTURE.md (F1–F6, Layer 0–2), docs/archgate.md, docs/agent-ci-guide.md, and the PR #1 description (environment findings).

## 8. Decisions for the operator

- **D1:** Adopt CI as the verifier of record (R1), with the five-landing agreement hand-over?
- **D2:** Move coders to task branches, worktrees and PRs into `gen2`, with `ci/std` required? Allow parallel coders on disjoint tasks (cap 2)?
- **D3:** Let Astra cite CI evidence for target runs instead of re-running them every review (re-runs optional)?
- **D4:** GitHub Actions: delete it, or repurpose it as the report-only drift job?
- **D5:** Fix `ipaddress` canonicalization at the root (recommended), or pin the Python patch version in ENVIRONMENT.md?
- **D6:** File change requests C1–C6 against `ci-cd` (human-merged trust root)?
