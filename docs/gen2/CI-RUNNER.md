# ci-2 execution modes

The October 18 amendment permits image `ci-py312-noble:1` until the operator
builds and confirms `:2` on cir. The default Jenkinsfile uses synchronous
workspace cleanup, recorded library/source/image identities, T0 and fixed
engine-unit partition 1/8. This is not a full
engine or full-acceptance verdict; the other seven unit partitions remain required.

## Commands and coverage

`make gen2-ci GEN2_CI_MODE=MODE GEN2_CI_SHARD=INDEX/TOTAL` runs one workload.
Output is fresh per invocation under `build/ci-evidence/MODE-INDEX-of-TOTAL`.
Reusing an output directory fails; retain it or remove it deliberately before a
new run. Every report records the checkout SHA/tree, interpreter, SQLite,
allocation, workload, shard, result and duration. The platform's identity remains
the authority for the executed checkout and branch head versus PR merge.

| Mode | Workload | Partition |
| --- | --- | --- |
| `push` (default) | sqlite, boundaries, size, schemas, DDL, catalog consistency, metrics, debt, locators, supported source | One execution |
| `engine-unit` | Full unittest discovery through the existing verbose runner | Classes assigned by SHA-256 modulo shard count; all class occurrences stay together in discovery-relative order |
| `engine-trigger-order` | Original and reversed store suites, with the unchanged rebuild and outcome gates | One execution |
| `engine-mutation` | Cosmic Ray changed-line campaign against the merge-base of `GEN2_BASE` (default `origin/gen2`), native git/pragma filters, shared full-suite coverage; line/module selections before full-suite escalation | One serial execution |
| `gateway-no-db` | Existing full gateway discovery without a DSN | One execution; requires psycopg even without PostgreSQL |
| `gateway-db` | Schema/seed plus full gateway discovery on a disposable Unix-socket PostgreSQL cluster | One DB owner in this invocation |
| `gateway-mutants` | Schema/seed and every gateway mutant on a disposable cluster | One DB owner in this invocation |

Unit partitioning is exhaustive: every index must finish before acceptance.
Mutation is unsharded and records every generated identity, filtered outcome,
normalized verdict, raw diagnostics and diff in `mutation-report.json` and its
native session database. Only inline `# pragma: no mutate` comments with a reason
can exclude changed-line survivors; Astra reviews them. After a passing clean
baseline, test execution errors count as `ERROR_KILL`, separately from
`ASSERTION_KILL`. Timeouts, crashes, loader/harness/internal errors and missing
or unclassified outcomes fail. Syntax-invalid variants are separate non-kills.
Unit discovery is a multiset: existing re-exported TestCase occurrences retain
their original multiplicities, and all occurrences of a class stay together.
Comparison requires those counts exactly. Mutation IDs remain unique.
Filtering can coalesce class/module fixture transitions when intervening classes
are assigned elsewhere. Class placement does not promise identical fixture
transitions for arbitrary suites; the unsharded sequence remains unchanged.
The unit and trigger-order runners also emit test/subtest outcomes and JUnit;
the mutation runner retains typed failures/errors, fresh test PIDs, baseline coverage, per-job test selections and per-stage outcomes/timings.

`make gen2-check` runs static gates and units. Under `make gen2-accept`, that
unit run also collects coverage once; acceptance then runs
trigger-order when `git diff --name-only <GEN2_BASE>...HEAD -- gen2/store/schema`
is non-empty or unavailable, followed by changed-line mutation;
`GEN2_BASE` defaults to `origin/gen2`. These targets have no shard arguments
by default. `make gen2-gateway` still runs no-DB, DB and all mutants by default,
on its existing bootstrap interpreter. Its new `GEN2_GATEWAY_MODE` only selects
an explicit invocation; the full default is unchanged.

## Allocation

`tools/gen2_workers.py` reads cgroup v2 `cpu.max` or v1 CFS quota/period,
including visible ancestors, and intersects that allocation with process CPU
affinity. Fractional quotas round down, with a minimum of one runnable process.
It does not use host-visible `os.cpu_count()`. `GEN2_CPU_BUDGET` can lower the
allocation, never increase it; malformed quotas or allocations fail visibly.
The engine mutation campaign uses Cosmic Ray's serial native executor, with
one test worker and fresh child interpreters. It has no worker override.

Each mode owns the aggregate allocation. Engine and gateway execute separately,
not concurrently within an invocation. Gateway is serial with one DB owner.
Independent jobs get the platform's individual 2-CPU container caps. Manually
starting concurrent modes in the same cgroup requires dividing the allocation
explicitly with `GEN2_CPU_BUDGET`; no independent process can infer another
process's allocation from a cgroup quota.

## What the deployed Jenkins platform can trigger

The inspected `std@v1.0.0` (`64e873b141093025b7d68edad79dacfd5f43eda9`)
provides one serial lint/build/unit execution per branch or PR job. It has no
consumer mode parameter, shard/matrix API or scheduler. Its maximum execution
budget is 60 minutes; this consumer requests 50. Replacing one long unit command
with several sequential commands would still share that timeout.

| Trigger | Current result | Required full-acceptance path |
| --- | --- | --- |
| Branch push, including `gen2` and task branches | T0 + unit partition 1/8 at the branch checkout | Separate engine shards at that same pin; trigger-order on DDL change |
| Ready PR creation/update | T0 + unit partition 1/8 at the platform's PR merge checkout | Separate engine shards at the executed merge pin, invalidated by target updates; trigger-order on DDL change |
| Draft PR | Platform does not build it | No acceptance claim |
| Integration/nightly/manual mode selection | Not exposed to consumers | Platform-owned opt-in trigger and aggregation |

The checkout token fetches branch history without a shallow depth; historical
commits needed by provenance tests must remain available. No GitHub Actions
workflow, job setting, new Jenkins stage or repo-launched sibling container is
introduced. No secret/personal-data scanner is exposed by the inspected library;
that conditional platform gate cannot be claimed here.

**Platform request (approved v1.2):** per-mode commands and a platform-owned
`CI_MODE` selection, after v1.1 identity/evidence is released. Map each command
below to a separately bounded execution, retain its raw evidence/JUnit, and bind
results to the executed source pin. Keep the integration interlock and queued
integration behavior from the approved v1.2 plan. A later push must not abort an
in-progress integration backstop. Generic platform sharding is deferred; no
library shard API or implementation is requested here. Repository partition
arguments can be explicit per-mode scalar commands if needed after measurement.
Until v1.2 is deployed, the default branch/PR result is T0 + unit partition 1/8; the
remaining engine modes cannot be measured separately in Jenkins. The planned
v1.1 source also explicitly excludes modes/schedules from its API.
No commit-footer, build-number, branch-name or temporary-Jenkinsfile scheme is
used to simulate a scheduler.

If either full engine mode exceeds its per-execution limit, proposed initial
qualification uses eight repository partitions for it, plus trigger-order. These are unqualified sizes, not measured bounds.
No partition is promised to fit until measured on cir. Increase partition count
only while retaining the complete expected inventory and all controls/gates.

## Gateway prerequisite and prepared follow-up

Gateway discovery imports `research_gateway.core.db`, which imports psycopg
unconditionally. Image `:1`'s declared package list has no psycopg. Every T0
invocation probes the actual gateway interpreter and records the import result;
this capability observation is not a gateway suite result. Missing psycopg
prevents even no-DB acceptance; no stub or additional skip is substituted.

The opt-in `make gen2-gateway-venv` prepares `.venv-gateway-ci` from
`gateway/requirements-ci.txt` using `--require-hashes --no-deps
--only-binary=:all:`, `pip check`, and driver/libpq imports. It is a separate
CPython 3.12 Linux amd64 environment. The lock pins psycopg 3.1.18,
psycopg-binary 3.1.18 and typing-extensions 4.10.0, with the exact wheel hashes
from each release's PyPI JSON metadata. `make gen2-gateway-ci
GEN2_GATEWAY_MODE=MODE` is prepared for the follow-up. Neither target is a
dependency of the default CI, engine venv, full local engine checks, or the
existing local gateway command. Image `:2` and DB modes stay off the Jenkins path.

## Equivalence evidence

At a pinned commit, run `make gen2-accept GEN2_BASE=<merge-base>` for the complete
CI qualification comparison in a disposable `git archive` snapshot with
`.venv-gen2` copied using `cp -a`. Start only when
no `gen2-landing-*` unit is active, under `systemd-run --user --collect
-p MemoryMax=20G`. Give it `GEN2_CI_EVIDENCE` and `GEN2_TEST_LOG` paths on durable
private storage; retain a `run.json` with the verified source SHA and final status.
The snapshot needs its own git metadata/history for tests reading old source.

Compare full local evidence to the exhaustive CI shard evidence with:

```
.venv-gen2/bin/python tools/gen2_ci_compare.py LOCAL CI --sha SHA --out RESULT.json
```

The comparison rejects missing or repeated shards, incomplete test or mutant
identities, failed invocations, actual test failures/errors, different mutation bases, and mixed source pins. Existing intentional unittest skips and
expected failures remain recorded outcomes: their identities, multiplicities
and skip reasons must match the independent reference exactly. A new or changed
skip therefore fails equality; this does not authorise any new test skip.
It compares test/subtest identity/outcome multisets, exact mutant identities and
normalized verdicts and the mutation base, plus both trigger orders. It does
not compare durations or machine-specific paths as a substitute for outcomes.
Any actual identity differences, including unstable subtest names, are reported
rather than normalised away. CI qualification and the shadow window remain
separate later work.

## Default result disclosure

`make gen2-ci-default` prints **PARTIAL ACCEPTANCE — NOT FULL ACCEPTANCE**
before execution and again at completion, including failure. Its fixed scope is
T0 and units 1/8. Complete trigger-order, unit partitions 2–8/8, all mutation
work and all gateway modes are omitted. A green result covers only that scope.
`default-1-of-1/scope.json` records the planned scope, actual per-mode execution
statuses and source SHA/tree; `GEN2_CI_SCOPE` retains it in the console.
`acceptance-scope.xml` publishes the banner and scope as a Jenkins-visible test
summary through `standardPipeline(junit: ...)`. This reporting case is not an
additional acceptance test. Every workload JUnit carries source SHA/tree,
dirty state, mode and shard properties from its colocated `run.json`, with
mode/shard/SHA also in the suite/class label for the Jenkins test UI.

The deployed std revision `64e873b141093025b7d68edad79dacfd5f43eda9`
has no consumer status-description interface. Request for ci-cd-2: provide an
opt-in, bounded consumer coverage/status description, visible on the completed
build and linked commit status, bound to the controller's executed source and
the consumer mode/shard scope. Preserve non-passing execution/publication
results. This branch uses the supported JUnit interface and console evidence;
it does not set Jenkins descriptions or change the platform. The drafted,
unmerged std v1.2 PRs #13–#15 do not establish deployed capability.

## v1.2 command mapping

| Mode | Command | Required execution ceiling |
| --- | --- | --- |
| `push` | `make gen2-ci GEN2_CI_MODE=push` | 50 minutes; expected a few minutes, measure in Jenkins |
| `engine-unit` | `make gen2-ci-unit` | 50 minutes, split into explicit repository partitions if measured over budget |
| `engine-trigger-order` | `make gen2-ci-trigger-order` | 50 minutes |
| `engine-mutation` | `make gen2-ci-mutation` | Changed lines only; serial, measured per change (no universal time bound) |
| `gateway-no-db` | `make gen2-ci-gateway-no-db` | 50 minutes; blocked on gateway interpreter dependency |
| `gateway-db` | `make gen2-ci-gateway-db` | 50 minutes; disabled pending image :2 and locked interpreter selection |
| `gateway-mutants` | `make gen2-ci-gateway-mutants` | 50 minutes; disabled pending image :2 and locked interpreter selection |

For an explicitly configured repository partition, append
`GEN2_CI_SHARD=INDEX/TOTAL` to `gen2-ci-unit` or `gen2-ci-mutation`. The complete
mode includes all partitions and all baselines. Per-mode measurements, source
pins, build URLs and current limitations are recorded in private ci-2 evidence.
The platform ceiling remains 60 minutes; this consumer requests 50 to retain
headroom. Do not combine long modes under one shared timeout.

`make gen2-mutation-report` runs all production Python files as report-only
evidence at phase gates and Gate S. It never participates in acceptance or blocks.
The gateway retains its existing 413-mutant PostgreSQL step pending separate adoption.
The wrapper observes the test-runner boundary: an outer assertion following a
nested child crash can still look like an assertion failure. Astra reviews intent.

The acceptance unit run records coverage.py per-test dynamic contexts through
`switch_context(test.id())`, including test setup/cleanup. `GEN2_COVERAGE` defaults
to `build/gen2-coverage.sqlite`. A successful unsharded full run publishes a
receipt bound to HEAD, tracked source bytes/differences, untracked source inputs,
Python/coverage versions and the coverage file's SHA-256. Mutation reuses only a
matching receipt; missing, stale, corrupt or incomplete maps require a fresh
full baseline. Plain `gen2-check` need not collect coverage. Set
`GEN2_TEST_COVERAGE=<path>` to collect it in a standalone unsharded `gen2-test`.

Stage 1 runs tests covering the mutated source span. If none exist, stage 1b
runs tests covering any line of that module. A survivor of either selection
runs the full suite in a fresh process (stage 2); an entirely uncovered module
goes directly to stage 2. Assertion and test-error kills retain fail-fast
semantics. Typed errors during test or fixture execution become `ERROR_KILL`;
failed discovery/imports represented by unittest's loader remain invalid.
No survivor passes on a partial suite.
`coverage.sqlite`, its receipt, `test-selection.json`, `module-selection.json`,
and each result's `stages` preserve selection, verdict and timing evidence.
Timing reports separate the shared coverage-collecting unit run from mutation.

Selected test-ID sequences must pass on clean source through the same native runner;
results are cached per sequence. Invalid line selections try module selection,
then full discovery. Stage-2 kills also need a passing matching clean full execution.
Receipts additionally bind interpreter path/options, installed and locked dependencies,
discovery arguments and hashed environment (excluding output routing, make recursion
and bytecode destinations). Nondefault interpreter options force recollection.
Clean requests/logs and report `qualifications`/`qualification_seconds` retain controls and cost.
