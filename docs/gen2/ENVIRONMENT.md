# Gen-2 build environment

The gen-2 checks (`make gen2-check`) and every future gen-2 build run in one **project-isolated environment**: a Python virtual environment at `.venv-gen2/` in the repository root (git-ignored), built from the hash-locked requirement files and nothing else. CI builds and uses the same environment through the same Make targets.

This replaces the earlier practice of installing the runtime dependency with `pip install --user --break-system-packages`, which Astra's 0a-repair re-review rejected as a build practice: `--user` still modifies the package environment every other program using that interpreter sees, and overriding an externally managed interpreter is the exceptional path the [Python packaging specification](https://packaging.python.org/en/latest/specifications/externally-managed-environments/) reserves for deliberate system administration, not project builds.

## What is installed, and how

| File | Contents | Consumer |
|---|---|---|
| `gen2/requirements.txt` | `rfc8785==0.1.4` (no dependencies) | runtime: `gen2/core/canonical.py`, the only module `gen2/boundaries.toml` grants it to |
| `gen2/requirements-dev.txt` | `jsonschema==4.10.3` and its complete Python 3.12 dependency graph: `attrs==23.2.0`, `pyrsistent==0.20.0` | `tools/check_gen2_schemas.py` only; no gen-2 module may import it |

Every entry carries its PyPI SHA-256 hashes. `make gen2-venv` runs:

```
python3 -m venv --clear .venv-gen2
.venv-gen2/bin/python -m pip install --require-hashes --no-deps -r gen2/requirements.txt -r gen2/requirements-dev.txt
.venv-gen2/bin/python -c "import rfc8785, jsonschema"
```

- `--require-hashes` refuses any file whose hash is not listed.
- `--no-deps` installs nothing that is not in the lock. A top-level pin alone does not lock its transitive graph, so the lock lists the whole graph. A missing dependency fails the import check at once instead of being resolved silently.
- `venv --clear` starts from an empty environment every time either lock changes. The target is keyed on both files.
- A venv does not see the base interpreter's site-packages or the user site (`~/.local`), so a package installed on the host can neither satisfy nor shadow a locked one.

Every check target (`gen2-sqlite`, `gen2-boundaries`, `gen2-schemas`, `gen2-ddl`, `gen2-catalog`, `gen2-catalog-check`, `gen2-test`, `gen2-trigger-order`, `gen2-mutation`, `gen2-size`, `gen2-linecount`) depends on `gen2-venv` and runs with `PYTHON = .venv-gen2/bin/python`. The only host input is the interpreter the venv is created from: `PYTHON_BOOTSTRAP`, default `python3`, Python 3.12. The standard-library `sqlite3` comes with it, so the SQLite version the DDL runs on is still the interpreter's. `make gen2-check` reports it.

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
- **The store's open path, `gen2/store/db.py`.** The library is checked on an in-memory connection before anything on disk is created or opened (`sqlite3.connect(path)` would create the file). The contract is then applied and read back on the durable connection itself. An existing store is admitted only if its schema is exactly `schema.sql`.
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

## CI

`.github/workflows/gen2-check.yml` installs Python 3.12 with `actions/setup-python`, then runs `make gen2-venv`, `make gen2-sqlite` (recording the SQLite version in the job summary) and `make gen2-check`. These are the same targets, the same locks and the same flags as a local build. CI no longer installs into the runner's interpreter.

## Changing a dependency

A new runtime dependency is an architecture change. It needs a `third_party` grant in `gen2/boundaries.toml`, and it goes through the charter's review path. Whether runtime or dev, a new dependency, or a version change, updates the lock with the complete transitive graph and every hash (from PyPI, for the exact release). For a platform-specific wheel, that means the CPython 3.12 wheels at least. A change to either lock rebuilds `.venv-gen2` on the next `make` run.
