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
| `engine-mutation` | Full inventory, global integrity checks, all unmutated loading-mode baselines, killers, controls and child attestation | Mutant IDs assigned by SHA-256 modulo shard count |
| `gateway-no-db` | Existing full gateway discovery without a DSN | One execution; requires psycopg even without PostgreSQL |
| `gateway-db` | Schema/seed plus full gateway discovery on a disposable Unix-socket PostgreSQL cluster | One DB owner in this invocation |
| `gateway-mutants` | Schema/seed and every gateway mutant on a disposable cluster | One DB owner in this invocation |

Partitioning is exhaustive, not diff selection. Every index must finish before
an aggregate acceptance result is possible. Mutation partitions retain global
coverage checks (unlike legacy `--only`), and repeat the complete baselines.
`--only` and sharding cannot be combined. Empty shards fail. The inventory
reports contain the complete expected identities and the assigned identities.
Unit discovery is a multiset: existing re-exported TestCase occurrences retain
their original multiplicities, and all occurrences of a class stay together.
Comparison requires those counts exactly. Mutation IDs remain unique.
Filtering can coalesce class/module fixture transitions when intervening classes
are assigned elsewhere. Class placement does not promise identical fixture
transitions for arbitrary suites; the unsharded sequence remains unchanged.
The unit and trigger-order runners also emit test/subtest outcomes and JUnit;
the mutation runner emits per-mutant test sets, verdicts and baseline outcomes.

`make gen2-accept` runs `gen2-check` and adds trigger-order when
`git diff --name-only <GEN2_BASE>...HEAD -- gen2/store/schema` is non-empty;
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
Mutation worker overrides are capped too. One allocation slot is reserved for
killers' child interpreters when more than one slot is available.

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

At a pinned commit, run `make gen2-check gen2-trigger-order` for the exhaustive
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
identities, failed invocations, actual test failures/errors, inconsistent
baselines, and mixed source pins. Existing intentional unittest skips and
expected failures remain recorded outcomes: their identities, multiplicities
and skip reasons must match the independent reference exactly. A new or changed
skip therefore fails equality; this does not authorise any new test skip.
It compares test/subtest identity/outcome multisets, exact mutant identities and
killer/control outcomes, both trigger orders, and unmutated baselines. It does
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
| `engine-mutation` | `make gen2-ci-mutation` | 50 minutes, full inventory; split only by exhaustive partitions if needed |
| `gateway-no-db` | `make gen2-ci-gateway-no-db` | 50 minutes; blocked on gateway interpreter dependency |
| `gateway-db` | `make gen2-ci-gateway-db` | 50 minutes; disabled pending image :2 and locked interpreter selection |
| `gateway-mutants` | `make gen2-ci-gateway-mutants` | 50 minutes; disabled pending image :2 and locked interpreter selection |

For an explicitly configured repository partition, append
`GEN2_CI_SHARD=INDEX/TOTAL` to `gen2-ci-unit` or `gen2-ci-mutation`. The complete
mode includes all partitions and all baselines. Per-mode measurements, source
pins, build URLs and current limitations are recorded in private ci-2 evidence.
The platform ceiling remains 60 minutes; this consumer requests 50 to retain
headroom. Do not combine long modes under one shared timeout.
