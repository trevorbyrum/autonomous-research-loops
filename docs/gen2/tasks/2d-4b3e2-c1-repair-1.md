# 2d-4b3e2-c1-repair-1: mutation coverage over the final installed triggers (round 2 of 3)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3e2-c1-astra-review-20261015.md`, round 1 at `dc81392`.
- **Gate A PASS, Gate B PASS, Gate C BLOCK.**
- **The only blocking finding is R1.** There is one non-blocking finding, N1.
- **Evidence:** `~/work/research-loops-public/private/evidence/astra-2d-4b3e2-c1/coverage-probe.json`.

## R1 (MEDIUM): the full landing gate fails on the retired trigger
**The problem.**
- `tools/gen2_mutations.py` `uncovered_triggers()` (around line 230) inventories every textual `CREATE TRIGGER`, including the SQL 21 `verification_receipts_span_domain` definition that SQL 32 retired.
- The span mutants were correctly retargeted to `_v2`, so the retired name shows up as uncovered.
- The landing `gen2-check` exited 2 before **any** of the 3,476 mutants ran.
- Coder `--only` runs skip this global check (line 726), which is why it wasn't caught earlier.

**Required (root cause).**
- Mutation coverage must account for the **final installed trigger definitions**, and must keep the coverage requirement for every live guard.
- Add a focused regression covering:
  - a replaced trigger, which is not reported;
  - a still-installed uncovered guard, which **must** still be reported;
  - safe handling of same-name re-creation;
  - unrelated or commented `DROP` text.
- **Don't** add a blanket exemption, a fictitious second-layer designation, or tests retargeted back to the retired definition, and don't treat `--only` as the full landing record.
- Prefer deriving "installed" the way the trigger-order tool already does, or from SQLite's catalog after applying the ordered DDL. Use one shared helper so the two tools can't disagree.

## N1 (non-blocking): trigger-count reporting
- `tools/gen2_trigger_order.py` (around line 152) counts textual CREATE statements. It reports 322, but 321 triggers are actually installed and reversed.
- Report the installed and reversed count, and correct the completion wording.

## New coder gate
- Whenever a task **adds, replaces or retires a DDL trigger**, run the full `make gen2-mutation`, without `--only`, before committing.
- At minimum, run its uncovered-trigger inventory check directly, so that the global coverage check is exercised.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2. Tooling and tests only; no production change is expected.
- **Before committing:**
  - targeted tests;
  - the uncovered-trigger inventory on the full schema, which must report nothing;
  - `make gen2-trigger-order`;
  - `--only` on the affected families;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Environment:**
  - Disposable snapshots copy `.venv-gen2` (`cp -a`). Never symlink it.
  - Before any heavy run, wait until no `gen2-landing-*` systemd user unit is active.
- **Reading:** anything in the repo, the private design records named in `docs/gen2/tasks/2d-4b3e.md`, and `~/work/research-loops-public/private/evidence/`. Never search `/home/trevor` or `/home/trevor/work` outside them. No provider calls.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3e2-c1-repair-1/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
