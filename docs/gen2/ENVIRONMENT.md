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

Every check target (`gen2-boundaries`, `gen2-schemas`, `gen2-ddl`, `gen2-test`, `gen2-mutation`, `gen2-size`, `gen2-linecount`) depends on `gen2-venv` and runs with `PYTHON = .venv-gen2/bin/python`. The only host input is the interpreter the venv is created from: `PYTHON_BOOTSTRAP`, default `python3`, Python 3.12. The standard-library `sqlite3` comes with it, so the SQLite version the DDL runs on is still the interpreter's. `make gen2-check` reports it.

## SQLite version floor

**Supported floor: SQLite 3.45.1.** It is the only version the complete DDL and test suite have been executed on: this host's Python 3.12.3 `sqlite3` module, and Astra's third review, which ran the same version. It is a floor because nothing older has been run, not because 3.45.1 is known to be the oldest version that works.

Feature minimums are facts about SQLite releases, not evidence that the schema works on them:

- STRICT tables (every gen-2 table): 3.37.0 or later ([STRICT tables](https://www.sqlite.org/stricttables.html)).
- JSON functions (`json_extract`, `json_each`, `json_valid`, …, used throughout the DDL): built in by default since 3.38.0; before that, only in builds compiled with JSON1 ([JSON support](https://www.sqlite.org/json1.html)).

Advertising a lower floor needs `make gen2-check` passing on that version first. The DDL check prints the version it ran on (`DDL creates … on SQLite x.y.z`). CI's version is the one `actions/setup-python`'s Python 3.12 links. It has not been observed, because CI has not run yet. Neither the build nor any runtime code refuses a lower version today. Astra's third review requires the store to check the floor at startup/build before 0b opens durable stores. The venv locks do not pin the system SQLite library.

## Local use

```
make gen2-check                        # builds .venv-gen2 on first use (network: PyPI), then runs every check
make gen2-venv                         # (re)build the environment only
make gen2-check PYTHON_BOOTSTRAP=python3.12   # choose the base interpreter explicitly
```

Run `make` directly, and do not pipe its output through `tail`, `grep` or `tee` unless `pipefail` is set. The exit status is the build result. The prior repair round had two masked-failure incidents from exactly that pattern.

## CI

`.github/workflows/gen2-check.yml` installs Python 3.12 with `actions/setup-python`, then runs `make gen2-venv` and `make gen2-check`. These are the same targets, the same locks and the same flags as a local build. CI no longer installs into the runner's interpreter.

## Changing a dependency

A new runtime dependency is an architecture change. It needs a `third_party` grant in `gen2/boundaries.toml`, and it goes through the charter's review path. Whether runtime or dev, a new dependency, or a version change, updates the lock with the complete transitive graph and every hash (from PyPI, for the exact release). For a platform-specific wheel, that means the CPython 3.12 wheels at least. A change to either lock rebuilds `.venv-gen2` on the next `make` run.

## Host state left by the earlier practice

The 0a-repair round installed `rfc8785==0.1.4` into the user site (`~/.local/lib/python3.12/site-packages/`). This repair did not install, upgrade or remove any host package. That user-site copy is no longer on the build's import path, because the venv excludes the user site. Removing it is the operator's decision.
