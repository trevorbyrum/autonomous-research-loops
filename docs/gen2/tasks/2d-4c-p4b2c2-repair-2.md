# 2d-4c-p4b2c2-repair-2: data-bearing DDL is invisible to the zero-DML oracle (Astra Gate C, round 2; FINAL round)

**Subject:** 2d-4c part 4b2c2, repair-1 (`d954236`; diff base `88dfa04`).

**Astra round 2** (`private/reviews/gen2-2d-4c-p4b2c2-r2-astra-review-20261021.md`):
- **A PASS, B PASS, C BLOCK.**
- **NB1 is closed (ROOT-CAUSE).**
- **The lexical-DML part of C1 is repaired at its cause.** Astra confirmed the SQLite authorizer observer catches:
  - INSERT OR REPLACE, UPSERT and REPLACE INTO;
  - trigger-body writes;
  - writes on a subject-opened second connection;
  - `executescript`, attached-database INSERTs and VACUUM INTO;
  - FK cascades, and DROP followed by recreation.
- **But C1 stays open: the full application-write guarantee is MITIGATION/incomplete.**
- Landing at `d954236`: `gen2-check` green (7,563 s). Production is unchanged.
- **This is round 3 of the 3-round cap.** If this repair doesn't close C1, the orchestrator escalates to Trevor rather than starting a fourth round. **Make it complete.**

## C1 (still open): data-bearing installation DDL passes
**Where:** the `no_dml` observer in `gen2/tests/test_retained_support.py:24`, specifically its catalog/DROP exclusions and its final assertion.

**The defect:**
- Appending this to `db.schema_text()`, at the same installation seam as the existing canaries, leaves the whole retained-support module passing (15 tests, zero failures):

  ```sql
  -- trace: review populated DDL canary
  CREATE TABLE review_application_rows
  AS SELECT 1 AS id, 'written' AS value;
  ```

  Yet every fresh installation then contains that row.
- SQLite authorizes CTAS through catalog writes and a CREATE TABLE action, with **no INSERT authorization**. `total_changes` also stays zero, so a change counter alone won't close it.
- Astra also noted that **dropping a populated standalone table passes the helper**: data destruction through DDL.
- This violates the operator's schema-only installation rule. It's charter class (e) again.

**Required (ROOT-CAUSE):**
- Keep the authorizer coverage, and **add database-content observation**. Compare the complete application-data state before and after each observed operation:
  - every non-`sqlite_%` table, including tables **created** during the operation, which must be empty;
  - tables **dropped** during the operation, which must have been empty;
  - row contents, not only counts;
  - attached databases and TEMP, if the subject can reach them.
- Legitimate schema-only DDL (empty CREATE/DROP, index and trigger creation) must still pass.
- **Qualify the oracle before submitting.** Run your own broad canary set and keep it as evidence. Each case must fail by assertion, with zero unrelated errors, while a schema-only control passes. Cover:
  - the exact CTAS counterexample above;
  - `CREATE TABLE ... AS SELECT` with zero rows, which must pass;
  - DROP of a populated table, and DROP of an empty table (the latter must pass);
  - `INSERT ... SELECT` into a new table;
  - `ALTER TABLE ... ADD COLUMN ... DEFAULT` on a populated table: decide whether that's a data change, and justify the decision in DOSSIER;
  - CREATE TEMP TABLE AS SELECT;
  - VACUUM INTO;
  - every round 1 and round 2 canary (bare, commented and CTE DML; triggers; second connection; ATTACH; executescript; UPSERT and REPLACE).
- **Think adversarially before you submit.** Ask: what other SQLite operation could create, change or destroy application rows without an INSERT/UPDATE/DELETE authorization? Probe each one you find.
- Keep the existing commented/CTE, zero-row/rollback, path, snapshot and no-effects coverage. Keep NB1.

## Constraints
- **Test-only repair.** No production change, unless a probe shows a real production defect; if one does, stop and report.
- Other constraints are as in `docs/gen2/tasks/2d-4c.md`:
  - the full `gen2-test`, `gen2-trigger-order`, the composition module, the startup/station/engine suites, the 2D4C4B2C2 mutant family with paired controls, and all eight static gates;
  - copy the venv with `cp -a`;
  - wait for `gen2-landing-*` units before heavy runs.
- Look up AGENTS.md only inside the repository. No provider calls. Never touch gen-1 runtime state or `127.0.0.1:8765`.
- **Don't edit** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER. Don't push or merge.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4c-p4b2c2-repair-2/`, with PROGRESS.md, COMPLETION.md and the canary qualification records. Class every fix ROOT-CAUSE or MITIGATION.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
