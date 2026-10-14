# 2d-4b3e1-json2b: complete the store-wide JSON member-name rollout (json2 part 2)

**Plan.** This is the remaining part of the json2 split in DOSSIER §2d-4b3e1-json2, estimated at about 410 lines. Re-estimate it in DOSSIER **before** writing code. Split at about 500 lines and stop after the first part; whatever is left stays on the named pending list, owned by this task.

**Already accepted:**
- 2d-4b3e1, Astra round 3 at `b731a22`: SQL 23's shared domain and the fail-closed column classification.
- json2 part 1, Astra round 3 at `b916117`:
  - six columns covered, including the three `search_observations` columns;
  - every authenticated failed attempt retained as opaque exact bytes plus hash, for any strict-parse refusal;
  - SQL 24/25 binding;
  - the refusal-class audit.

**Operator rulings** (Trevor, 2026-10-13):
- Close the JSON member-name family store-wide.
- Stored logical JSON member names are NUL-free (C-13).
- Every attempt is recorded.

## Required
1. **Global admission.** Every Router entry point and every Store JSON column refuses NUL-containing and duplicate member names before hashing or writing, with typed refusals.
   - This includes contract confidence-scheme labels and every other admitted open map.
   - Inventory the entry points in DOSSIER.
2. **Guards on the remaining 30 pending columns.**
   - Generated SQL-23-style INSERT and UPDATE guards from the checked generator, as ordered additive DDL.
   - **Ordering rule:** no guard lands before every writer to that column has stopped producing refused names.
   - **Empty the pending list.** Any column left over after a split stays named and owned by this task's next part.
3. **SQL 21.** Once `verification_receipts.receipt` is covered, its uniqueness check becomes redundant; document that.
   - **Don't remove or weaken** its span-shape or preserved-numeral guarantees.
   - Removing the redundant uniqueness predicate is optional. If you do, it needs a paired-mutant justification.
4. **Reclassify and repin.** Re-review the classification after each DDL change and explicitly repin both hashes. Record the review in evidence.
5. **Docs.** C-13 and BOUNDARIES must describe the completed rollout exactly, or state precisely what remains if you split.
6. **Tests.**
   - Write-path refusal at the Router and the Store, for each kind of entry point.
   - Raw-DDL regression/control pairs on a representative column for each table you cover, including literal and escaped duplicates and top-level and nested NUL names, with records that read back through `Store.select`.
   - Predicate-level paired mutants for each guard.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2.
- **`service.py`:** wiring only (DEBT-036).
- **Never run a migration against a real database.**
- **Before committing:**
  - the full `make gen2-test`;
  - `make gen2-trigger-order`;
  - the full composition module (`gen2.tests.test_router_composition`);
  - `--only` on every mutant family that targets an edited file **and** on every family whose paired controls use an edited shared fixture, including transitive imports;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Environment:**
  - Disposable snapshots copy `.venv-gen2` (`cp -a`) and `touch .venv-gen2/.gen2-installed`. Never symlink it.
  - Don't refresh `.venv-gen2` during mutant runs.
  - Before any heavy run, wait until no `gen2-landing-*` systemd user unit is active. Don't touch those units or their clones.
- **Reading:** anything in the repo, the private design records named in `docs/gen2/tasks/2d-4b3e.md`, and `~/work/research-loops-public/private/evidence/`. Never search `/home/trevor` or `/home/trevor/work` outside them. No provider calls.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3e1-json2b/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.

## Continuation (2026-10-14): part 2, the remaining 22 columns
- **Part 1 was accepted** on Astra's first review at `a28c7e2`.
  - Global Router/Store admission covers all 28 entry points and all 36 columns at the Store API.
  - SQL 26 guards 8 more columns, for 14 of 36.
- **Part 2:**
  - Install generated SQL-23-style INSERT and UPDATE guards on the **22 named pending columns**, as ordered additive DDL.
  - Empty the pending list completely.
  - The ordering rule still applies. Every writer already stops refused names at the Store API, but verify this per column.
- **SQL 21.** Once `verification_receipts.receipt` is covered, document that its uniqueness predicate is redundant. Keep the span-shape and preserved-numeral guarantees.
- **Reclassify and repin** both hashes explicitly after each DDL change.
- **Docs.** C-13 and BOUNDARIES must state that the rollout is **complete**.
- **Constraints and tests:** the same as above, including the full `make gen2-test`, `make gen2-trigger-order`, composition, family `--only` sweeps, the eight static gates, and copying the venv rather than linking it.
- **Re-estimate** in DOSSIER first; split at about 500 lines.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3e1-json2b-part2/`.
