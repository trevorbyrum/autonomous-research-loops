# 2d-4b3b-repair-2: give A6-D28 a valid paired control (Astra round 2: R3)

**Source:** `private/reviews/gen2-2d-4b3b-r2-astra-review-20261011.md`, pinned 1323cf6.
- **Verdict:** A PASS, B PASS, C BLOCK.
- **R1 and R2 are closed at the root cause.**
- **This is round 3 of 3, the cap.**

## R3
- **Symptom:** the landing `gen2-check` exits 2. 3,026 of 3,027 mutants were killed; `A6-D28-old-over-restriction` is **INVALID**.
- **Cause:**
  - Its paired control, `test_store_history.EveryTableSweepTest.test_every_table_is_populated`, uses the shared `populate_every_table` fixture (`gen2/tests/store_fixtures.py:658`).
  - That fixture now inserts `canonical_bytes` with the producer as acquirer.
  - This is valid production behaviour, but the D28 counterfactual (`tools/gen2_mutants/ddl_0a.py:416`) deliberately forbids it. So the control fails during setup.
- **Reproduction:** `private/evidence/astra-2d-4b3b-r2/landing-mutant-reproduction.log`.

## Required
1. Give D28 a **separate accepted control**. Its acquisition and extraction operands must stay valid under D28's deliberate over-restriction (for example, an acquirer other than the producer).
2. Keep D28's killer, which proves that canonical reuse acquired by the producer must work.
3. Preserve the shared sweep's every-table/history assertions and the installation no-DML assertion.
4. **Don't** waive the mutant, relabel INVALID as a kill, or weaken the canonical-reuse requirement.
5. **Process rule from now on:** when you edit a shared test fixture (`store_fixtures.py` or similar), run `--only` on **every mutant family whose paired controls use that fixture**, not just the families that target the edited files.
   - Find them in `tools/gen2_mutation_controls.json`.
   - For this repair, at minimum run `--only A6-` plus every family whose controls are in `test_store_history` or use `populate_every_table`.

## Constraints
- **Coder:** GPT-6.1-Sol, branch gen2. Change tests and tools only.
- **Before committing, run:**
  - the targeted tests;
  - the full composition module;
  - the `--only` sweep described above;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Don't** refresh `.venv-gen2` while mutants are running.
- **Reading:** anything in the repo and the named private paths. Never search `/home/trevor` or `/home/trevor/work` outside them.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3b-repair-2/`.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
