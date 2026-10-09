# Gen-2 build environment

The gen-2 checks (`make gen2-check`) and every future gen-2 build run in one **project-isolated environment**: a Python virtual environment at `.venv-gen2/` in the repository root (git-ignored), built from the hash-locked requirement files and nothing else. CI builds and uses the same environment through the same Make targets.

This replaces the earlier practice of installing the runtime dependency with `pip install --user --break-system-packages`, which Astra's 0a-repair re-review rejected as a build practice: `--user` still modifies the package environment every other program using that interpreter sees, and overriding an externally managed interpreter is the exceptional path the [Python packaging specification](https://packaging.python.org/en/latest/specifications/externally-managed-environments/) reserves for deliberate system administration, not project builds.

## What is installed, and how

| File | Contents | Consumer |
|---|---|---|
| `gen2/requirements.txt` | `rfc8785==0.1.4` (no dependencies) | runtime: `gen2/core/canonical.py`, the only module `gen2/boundaries.toml` grants it to |
| `gen2/requirements-dev.txt` | `jsonschema==4.10.3` and its complete Python 3.12 dependency graph: `attrs==23.2.0`, `pyrsistent==0.20.0` | `tools/check_gen2_schemas.py` only; no gen-2 module may import it |
| `gen2/requirements-dev.txt` (task 2q-r1) | `rope==1.15.0` with `pytoolconfig==1.3.1`, `packaging==26.3`, `platformdirs==4.12.4`; `hypothesis==6.168.5` with `sortedcontainers==2.4.0`; `time-machine==3.5.1` (no dependencies) | dev tooling for refactors and their verification (below); no gen-2 module and no tool of `make gen2-check` imports them |

Every entry carries its PyPI SHA-256 hashes. `make gen2-venv` runs:

```
python3 -m venv --clear .venv-gen2
.venv-gen2/bin/python -m pip install --require-hashes --no-deps -r gen2/requirements.txt -r gen2/requirements-dev.txt
.venv-gen2/bin/python -c "import rfc8785, jsonschema, rope, hypothesis, time_machine"
```

- `--require-hashes` refuses any file whose hash is not listed.
- `--no-deps` installs nothing that is not in the lock. A top-level pin alone does not lock its transitive graph, so the lock lists the reference Python 3.12 dependency closure. The five-import check catches missing top-level packages and dependencies those imports load; it does not exercise every tool submodule. For example, it can pass without `pytoolconfig` even though importing `rope.base.project` then fails. Dependency closure was verified separately using installed requirement metadata, `pip check` and tool imports in an isolated environment (Astra's 2q-b10 review, below).
- `venv --clear` starts from an empty environment every time either lock changes. The target is keyed on both files.
- A venv does not see the base interpreter's site-packages or the user site (`~/.local`), so a package installed on the host can neither satisfy nor shadow a locked one.

Every check target (`gen2-sqlite`, `gen2-boundaries`, `gen2-schemas`, `gen2-ddl`, `gen2-catalog`, `gen2-catalog-check`, `gen2-test`, `gen2-trigger-order`, `gen2-mutation`, `gen2-size`, `gen2-linecount`) depends on `gen2-venv` and runs with `PYTHON = .venv-gen2/bin/python`. The only host input is the interpreter the venv is created from: `PYTHON_BOOTSTRAP`, default `python3`. The **reference environment is CPython 3.12.3 with SQLite 3.45.1**, pinned exactly for reproducibility. The standard-library `sqlite3` comes with the interpreter; `make gen2-check` reports the linked SQLite version.

The reference pin does not establish portability. The gateway client's project-owned address serializer preserves the accepted address spelling from value and family across Python patch releases, with interpreter-independent regression tests (task 2b-repair-20; CI design D5). The planned report-only drift qualification is a **Jenkins nightly**, not GitHub Actions (operator-approved CI design D4); it remains planned until that CI work is implemented.

## Refactoring and verification tools (task 2q-r1; dev-only, operator-authorised 2026-10-08)

The trial in `docs/gen2/research/refactor-verification-trial-20261008.md` adds established tools in place of per-refactor proof tools. None of them is imported by a production module, the boundary graph grants them to no module, and the metrics tool stays stdlib-only.

| Tool | Purpose | Notes |
|---|---|---|
| `rope` | performs a mechanical refactoring (extract method and the like) programmatically, instead of by hand | needs a `source_folders` setting for a directory without `__init__.py` (the gen-2 packages are namespace packages); a known fault, with a minimal reproduction, is in the trial write-up |
| `hypothesis` | property-based `old == new` differentials of pure functions, with shrinking | ships a compiled extension (`_native`); the lock lists its CPython 3.12 wheels |
| `time-machine` | freezes or moves the wall clock of one process (`time.time`, `datetime.now`, `time.gmtime`, `clock_gettime(REALTIME)`) | does not touch `time.monotonic`, `perf_counter`, `sleep` or file times; **does not reach a child interpreter**, which must arm it itself (a `sitecustomize` through `GEN2_CHILD_ROOT`) |
| RefactoringMiner (Java; not a Python dependency) | describes the refactorings in a commit range, Python included | runs from the official image **pinned by digest**, offline, through `tools/gen2_refactoring_detect.py` |

The detector needs Docker and one pull, by hand, of the pinned image (Java is not installed on the build host). The wrapper never pulls: with the image absent it prints the command and exits 2.

```
docker pull tsantalis/refactoringminer@sha256:2d44dccea74ffcd4fa8e1fcd8cef0d29e78a52e2662d5c863b7e5e691d51e1ba
python3 tools/gen2_refactoring_detect.py START END [--expect "Extract Method=5" ...]
```

It runs `docker run --network none --pull never --read-only` with the repository mounted read-only. The image carries no tag but `latest`; the digest above is the multi-architecture index published on 2026-10-08, and a newer detector is a deliberate re-pin, not a re-pull. The actual `gen2-venv` check imports `rfc8785`, `jsonschema`, `rope`, `hypothesis` and `time_machine`, as the recipe above shows. It is a smoke check, not a dependency-closure proof. [Astra's 2q-b10 review](/home/trevor/work/research-loops-public/private/reviews/gen2-2q-b10-astra-review-20261008.md) separately verified the pinned Python 3.12 closure from installed dependency metadata and `pip check`, and recorded the `pytoolconfig` counterexample. That verification supports the reference environment, not arbitrary interpreter/platform portability.

## Upgrading the reference interpreter

The reference environment is CPython 3.12.3, and an upgrade of the interpreter (a new minor version, or a patch release the source index has not been run under) is accepted only when each of these holds, because the supported-source contract is validated for 3.12.3 alone (task 2q-t1; DEBT-017 item 4; `docs/gen2/SOURCE-CONTRACT.md`, "Binding identity"):

1. **The scope correspondence is revalidated.** `tools/gen2_source_index.py` pairs every scope of the tree with the table of the standard library's `symtable` by following the compiler's order of entering scopes, and spells private names as the compiler does. Under the new interpreter, the index runs without a pairing refusal over a corpus of real source (the standard library and the installed packages: the 2q-a-repair-6b run used 5,893 files) and over randomly generated programs with a uniquely named lambda or iteration variable in every slot the compiler reads in a different order (the 6b fuzz, 20,383 programs); each file or program the index refuses is explained (syntax the contract declares unsupported, such as the `type` statement and type parameters), and none is an unexplained mismatch.
2. **The supported syntax is revalidated.** The node classes the walker records (`FORMS` in `tools/gen2_source_index.py`) and the refused-by-design ones are checked against the new `ast`; a node class the walker has no entry for is refused, so a new one is a failure of this criterion, not a silent pass.
3. **The interpreter-backed tests pass unchanged:** the source and closure tests (`gen2/tests/test_source_*.py`), including the effective-member matrix against `dataclasses` and the data model, and the targeted tests of the metrics, without an edit to a test to make it pass. A change to what the interpreter does that a test asserts is a contract amendment, not a test edit.
4. **The metrics are unchanged on the production tree:** `make gen2-source` reports zero refusals, and the metrics reports and facts are byte-identical to those of 3.12.3 (a difference is a measurement change and is reported as one).

Until all four are shown, the new interpreter is not a reference environment for the source guard.

## SQLite version floor

**Supported floor: SQLite 3.45.1.** It is the only version the complete DDL and test suite have been executed on: the `sqlite3` module of Python 3.12.3 in the reviewed test environment, and Astra's third review, which ran the same version. It is a floor because nothing older has been run, not because 3.45.1 is known to be the oldest version that works.

Feature minimums are facts about SQLite releases, not evidence that the schema works on them:

- STRICT tables (every gen-2 table): 3.37.0 or later ([STRICT tables](https://www.sqlite.org/stricttables.html)).
- JSON functions (`json_extract`, `json_each`, `json_valid`, …, used throughout the DDL): built in by default since 3.38.0; before that, only in builds compiled with JSON1 ([JSON support](https://www.sqlite.org/json1.html)).

Advertising a lower floor needs `make gen2-check` passing on that version first. The venv locks do not pin the system SQLite library, so the floor is enforced where the library is used:

**Compatibility gate (task 0b; Astra third review ruling 4).** `gen2/store/compat.py` refuses a SQLite that cannot hold the store. It runs three checks. None of them replaces another.
1. **Version.** The linked library's `sqlite_version()` is parsed into integers and compared with 3.45.1 as a tuple. A string comparison would rank 3.9.0 above 3.45.1.
2. **JSON.** Every JSON function the DDL uses is executed on known inputs, and its answers are compared with SQLite's documented results. SQLite can be built without JSON at any version, so the version check alone cannot establish it. The DDL check fails the build if the DDL uses a JSON function the gate does not probe.
3. **Connection contract.** `connection.sql` is applied, and every pragma it sets, plus `foreign_keys` and `recursive_triggers` in any case, must read back as 1.

A refusal raises `StoreCompatibilityError`. The error carries a dated capability fact (`store.sqlite failing since …`, with what was observed). It is not a silent fallback.

The same functions run in three places:
- **The store's open path, `gen2/store/db.py`.** The library is checked on an in-memory connection before anything on disk is created or opened (`sqlite3.connect(path)` would create the file). The contract is then applied and read back on the durable connection itself. An existing store is admitted only if its schema is exactly the store DDL: the parts in `gen2/store/schema/`, joined in the order `order.txt` declares.
- **`make gen2-sqlite`.** This runs first in `gen2-check` and prints the record of what the build ran on.
- **The DDL check, `make gen2-ddl`.** It prints `DDL creates … on SQLite x.y.z (compatibility gate passed)`.
- **The importer.** The 0b dry-run importer (`gen2/importer/`) has no SQLite access at all: the boundary graph lets it import `core` only, with no `sqlite3` grant. Any importer that writes a store (Phase 4) must open it through `gen2/store/api.py` `open_store`, and so through this gate. That requires amending the importer's boundary entry, which the review path covers.

**CI's SQLite version** is the one `actions/setup-python`'s Python 3.12 links. The workflow now records it: its `make gen2-sqlite` step appends the gate's record (version, JSON probes, pragmas) to the job summary, and a refusal fails the job. It has still not been observed, because CI has not run yet (the first push is the operator's call).

## Local use

```
make gen2-check                        # builds .venv-gen2 on first use (network: PyPI), then runs every check
make gen2-venv                         # (re)build the environment only
make gen2-check PYTHON_BOOTSTRAP=python3.12   # choose the base interpreter explicitly
```

Run `make` directly, and do not pipe its output through `tail`, `grep` or `tee` unless `pipefail` is set. The exit status is the build result. The prior repair round had two masked-failure incidents from exactly that pattern.

## The gateway's checks (`make gen2-gateway`, task 2b)

The research gateway is a separate package (`gateway/`), not gen-2 code: it has its own
dependency, `psycopg`, and it is never imported by gen-2 (INVARIANTS B-2). Its checks
therefore run on the gateway's interpreter, `$(PYTHON_BOOTSTRAP)`, not in `.venv-gen2`:
that interpreter must provide `psycopg` (the gateway's image installs `psycopg[binary]`;
the build host used for task 2b has the distribution's `python3-psycopg` 3.1). The
database cases and mutants also need PostgreSQL server binaries (`initdb`, `pg_ctl`,
`createdb`, on `PATH` or under `/usr/lib/postgresql/*/bin`): `tools/gen2_gateway_check.py`
initializes a throwaway cluster in a temporary directory, on a Unix socket only, and
removes it afterwards; it never uses an existing database. Without those binaries the
check fails and says what did not run. It is not part of `gen2-check` (CI has neither);
whether the gateway should get a hash-locked environment of its own is an open question.

## CI

`.github/workflows/gen2-check.yml` installs Python 3.12 with `actions/setup-python`, then runs `make gen2-venv`, `make gen2-sqlite` (recording the SQLite version in the job summary) and `make gen2-check`. These are the same targets, the same locks and the same flags as a local build. CI no longer installs into the runner's interpreter.

## Changing a dependency

A new runtime dependency is an architecture change. It needs a `third_party` grant in `gen2/boundaries.toml`, and it goes through the charter's review path. Whether runtime or dev, a new dependency, or a version change, updates the lock with the complete transitive graph and every hash (from PyPI, for the exact release). For a platform-specific wheel, that means the CPython 3.12 wheels at least. A change to either lock rebuilds `.venv-gen2` on the next `make` run.
