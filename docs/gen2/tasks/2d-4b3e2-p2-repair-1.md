# 2d-4b3e2-p2-repair-1: one coherent family comparison across registry revisions (round 2 of 3)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3e2-p2-astra-review-20261014.md`, round 1 at `0cfb573`.
- **Gate A BLOCK, Gate B PASS, Gate C BLOCK; MITIGATION.**
- **The only blocking finding is F1.** Everything else in this slice is accepted.
- **Reproduction:** `~/work/research-loops-public/private/evidence/astra-2d-4b3e2-p2/family-probes.py`, `.json` and `.log`.
- **Operator rulings** (end of `docs/gen2/tasks/2d-4b3e.md`): only independent extraction validates; independence means a **different registered family**.

## F1 (MEDIUM): cross-revision family relabelling manufactures independence
**The problem.**
- SQL 29 resolves each operand's family under its **own** pinned registry revision, then compares the labels (`ty.family = tx.family`).
- An audited registry update that **renames** a family, with no extractor change, makes the same tool, or two tools that were always in one family, compare as "different families" when the operands pin different revisions.
- Astra's reproductions pass through both normal Router commits and raw DDL, with `method_succeeded = 1`. For example:
  - revision 2 maps `tool-a` and `tool-c` to `family-a`;
  - revision 3 renames both to `family-c`;
  - a target pinned at revision 2 and a validator pinned at revision 3 then "succeed".
- `test_snapshot_control` currently **accepts** one form of this.

**Required (root cause).**
- Establish a **coherent, operator-governed family relationship across the two operands**, while keeping their historical extraction pins.
- **A family rename or reclassification alone must never make a replay independent.**
- Choose and justify one approach in DOSSIER:
  - **(a) a common comparison interpretation:** resolve both operands' families under one approved registry revision, such as the validation's own pinned revision. Both tools must be registered there, and anything ambiguous is refused; or
  - **(b) stable family lineage:** immutable family identifiers whose renames are display labels only, with reclassification as an explicit, audited operator act.
- **Don't** repair this only by requiring unequal tool identities. The two-identity reproduction still passes that condition.
- **Refuse ambiguous bases.**
- Replace the erroneous `test_snapshot_control` acceptance with isolated Router and raw-DDL refusals for **both** reproductions.
- Keep independent same-revision and cross-revision accepted controls, where the families are genuinely different and stable.
- Add predicate-level mutants with **control path traces**.
- Update the own-snapshot documentation in BOUNDARIES, V-3 and DOSSIER to state the repaired cross-revision rule exactly.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2. Write the design and re-estimate in DOSSIER first.
- **Ordered additive DDL.** Editing the undeployed SQL 29 is acceptable if it's cleaner; say which you chose.
- **Never run a migration against a real database.**
- **New JSON columns,** if any, must be classified and guarded, with both hashes repinned.
- **Before committing:**
  - the full `make gen2-test`;
  - `make gen2-trigger-order`;
  - the full composition module (`gen2.tests.test_router_composition`);
  - `--only` on every mutant family that targets an edited file **and** on every family whose paired controls use an edited shared fixture, including transitive imports;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Environment:**
  - Disposable snapshots copy `.venv-gen2` (`cp -a`). Never symlink it.
  - Don't refresh `.venv-gen2` during mutant runs.
  - Before any heavy run, wait until no `gen2-landing-*` systemd user unit is active.
- **Reading:** anything in the repo, the private design records named in `docs/gen2/tasks/2d-4b3e.md`, and `~/work/research-loops-public/private/evidence/`. Never search `/home/trevor` or `/home/trevor/work` outside them. No provider calls.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3e2-p2-repair-1/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
