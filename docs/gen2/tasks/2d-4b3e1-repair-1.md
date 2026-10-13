# 2d-4b3e1-repair-1: one store-wide JSON member-name domain, plus the trigger-order fixture (round 2 of 3)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3e1-astra-review-20261012.md`, round 1 at `190dabb`.
- **Gate A BLOCK** (F1), **Gate B PASS**, **Gate C BLOCK** (F1 and F2).
- There is one non-blocking finding, **N1**. Read the full report and the reviewer evidence in `~/work/research-loops-public/private/evidence/astra-2d-4b3e1/`.

## Operator ruling, 2026-10-13 (Trevor): a store-wide guard
- F1 is the **second occurrence** of one family. 2d-4b3d F1 was the first.
- **The family:** a raw-admitted JSON value whose duplicate member names, or member names containing U+0000, let SQLite's `json_extract`/path lookup select a different member from the one a conventional decoder or `Store.select` sees.
- SQL triggers read stored JSON in about 250 places across 19 schema parts.
- Trevor chose to **close the family store-wide**, not to patch fields one at a time.

## Required
1. **The shared domain.** Design it in DOSSIER **before code**, with a re-estimate. Every stored JSON value admitted to any table must have:
   - **unique decoded member names within each object**, grouped by actual parent with binary equality, following SQL 21's accepted method and RFC 7493 §2.3; and
   - **no member name containing U+0000.** NUL characters in string *values* stay allowed.

   Implement it once, as ordered additive DDL with `-- trace:` markers. If you generate per-column guards, generate them by a checked tool, with the generated output committed and verified to match.
   - Keep SQL 21's accepted span-shape and numeral guarantees. Say whether SQL 21's uniqueness check becomes redundant, and **don't weaken it**.
   - Inventory **every** JSON column, meaning every column that DDL reads with `json_*` functions or that the store serializes as JSON. Retained raw byte BLOBs are not JSON columns.
   - Confirm that the Router and Store write paths can never produce a value this domain refuses. If any open-ended JSON object (provider metadata, for example) could legitimately contain such a name, stop and report rather than refusing it silently.
2. **The static check.** Extend `tools/check_gen2_schemas.py --part ddl` (`make gen2-ddl`) so that it **fails** whenever any JSON column lacks the domain guard. This prevents a third recurrence.
   - If the work has to split, the check may carry an explicit pending list owned by this task's next part. Each entry is named and must be gone by the end of that part. Nothing may stay listed silently.
3. **The first part covers:** the mechanism; the static check; SQL 22's `source_extractions.output_ref` and `extraction_validations.comparison_evidence_ref`, closing F1; and as many other columns as fit within about 500 lines. Then stop. The remaining columns become part 2 of this repair.
4. **F2: fix the fixture** (`gen2/tests/test_store_extraction_records.py`). It must install its intended transformed schema objects without relying on their physical position in the combined DDL. Keep the mutations and the requested trigger order, and show that the cases actually run under the reversed order. Suppressing the duplicate-trigger error, falling back to the normal DDL, or dropping the cases is **not** a fix.
5. **N1: documentation only.** BOUNDARIES and DOSSIER must state that `extractor_identity` independence is an exact, case-sensitive comparison of **caller-declared** labels. It isn't execution-derived and it doesn't resolve aliases. Settling the identity trust and canonicalization policy is required **before** part 2 of 2d-4b3e, receipt consumption, can grant any authority. Say so in DOSSIER.
6. **Tests.**
   - Isolated raw regression/control pairs for each domain predicate: duplicate literal and escaped names; NUL-suffixed names at the top level and when nested. Cover them on SQL 22's two fields and on a representative column from each table you cover.
   - Valid records must stay readable through `Store.select`.
   - Add a predicate-level paired mutant for each guard.
   - Add a test proving the static check fails on an uncovered JSON column.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2. Write the design and re-estimate in DOSSIER first; split at about 500 lines.
- **Never run a migration against a real database.**
- **Before committing:**
  - targeted tests and the full composition module (`gen2.tests.test_router_composition`);
  - **`make gen2-trigger-order`.** This is new and required whenever store tests or DDL change.
  - `--only` on every mutant family that targets an edited file **and** on every family whose paired controls use an edited shared fixture, including transitive imports;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Environment:** don't refresh `.venv-gen2` during mutant runs. Before any mutant or trigger-order run, wait until no `gen2-landing-*` systemd user unit is active. Don't touch those units or their clones.
- **Reading:** anything in the repo, the private design records named in `2d-4b3e.md`, and `~/work/research-loops-public/private/evidence/`. Never search `/home/trevor` or `/home/trevor/work` outside them.
- **No provider calls.**
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER. Edits to BOUNDARIES and INVARIANTS must match the code exactly.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3e1-repair-1/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
