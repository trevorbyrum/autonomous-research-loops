# 2d-4b3e1-repair-2: a sound JSON-coverage inventory, plus the stale diagnostics (round 3 of 3, the cap)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3e1-r2-astra-review-20261013.md`, round 2 at `d41e42c`.
- Gate A blocked and Gate C blocked; Gate B passed.
- **Exactly two items remain:** R2-1 and R2-2. Everything else in part 1 is accepted, including SQL 23's domain on the three columns, the write-path refusal and the F2 fixture.
- **This is the last round.** If it blocks, the operator decides.

## R2-1: the static inventory misses JSON operands (Gates A and C)
**The problem.** `tools/gen2_json_member_domain.py` `operands()` scans the SQL text with hand-rolled matching. It misses:
- quoted function names, such as `"json_valid"(v)`;
- a comment between a function name and its `(`;
- a `'--'` inside a string literal, which it treats as a comment and so hides the rest of the line;
- a misleading alias: the retained-byte exclusion exempts `CAST(a.response_bytes AS TEXT)` without resolving which table `a` is.

Astra's five probe schemas all passed `check_gen2_schemas.py --part ddl` with exit 0. See `~/work/research-loops-public/private/evidence/astra-2d-4b3e1-r2/probe_static.py`, `probe_static.json` and `probe_static_cli.json`.

**Root cause:** a custom, partial SQL scanner. Under the build charter's "established tools over custom" rule, **don't patch the scanner's cases.** Replace the discovery with an approach whose correctness doesn't depend on hand-rolled tokenizing.
- **First, research and cite in DOSSIER** how SQL function and column usage is normally found. Candidates:
  - a real SQL parser with an SQLite dialect and scope and alias resolution, for example `sqlglot` and its qualify and scope modules;
  - SQLite's own tokenizer and resolver, for example `EXPLAIN` or bytecode, or the authorizer callback `sqlite3.Connection.set_authorizer`, which reports every column read with its real table during statement preparation;
  - a fail-closed classification of every stored TEXT column.
- **Choose one, and justify it.** The authorizer is in the standard library and resolves aliases authoritatively, so evaluate it seriously.
- **Fail closed.** Any statement the tool can't analyse completely is a check failure, never a silent pass.
- **Bind retained-byte exclusions** to the actual resolved table and column, never to a textual alias.
- If you add a dependency, pin it in `gen2/requirements.txt` and justify it. Prefer the standard library where it's sound.
- **Tests:**
  - an isolated regression/control pair for each of Astra's five probes;
  - an ordinary unquoted control that must fail;
  - **mutation coverage of the inventory decisions themselves**, not just removal of the checker call.
- The current classification (36 columns, 3 covered and 33 named pending owned by part 2) must come out the same, or any difference must be explained.

## R2-2: stale NUL-name diagnostic expectations (Gate C)
- `gen2/tests/test_exact_spans.py` `ExactSpanRouterTest.test_pairs_at_payload_boundary`: thirty subtests across three methods still expect `no value is allowed`.
- The amended Router boundary correctly refuses those inputs earlier, with `NUL in object member name`.
- **Update only those expectations.** Keep the refusal, the unchanged-state checks, the accepted controls and the retained-value assertions.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2. Design and re-estimate in DOSSIER first; split at about 500 lines.
- **Never run a migration against a real database.**
- **Before committing:**
  - **the full `make gen2-test`.** This is new and required whenever shared core modules (`gen2/core/canonical.py`, `gen2/router/boundary.py`, `gen2/store/api.py`) or their diagnostics are involved. It is how R2-2 would have been caught.
  - `make gen2-trigger-order`;
  - targeted tests and the full composition module (`gen2.tests.test_router_composition`);
  - `--only` on every mutant family that targets an edited file **and** on every family whose paired controls use an edited shared fixture, including transitive imports;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Environment:** don't refresh `.venv-gen2` during mutant runs. If you add a dependency, record how it was installed. Before any heavy run, wait until no `gen2-landing-*` systemd user unit is active. Don't touch those units or their clones.
- **Reading:** anything in the repo, the private design records named in `docs/gen2/tasks/2d-4b3e.md`, and `~/work/research-loops-public/private/evidence/`. Never search `/home/trevor` or `/home/trevor/work` outside them. Web documentation for SQLite or SQL parser libraries is fine. No provider API calls.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3e1-repair-2/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
