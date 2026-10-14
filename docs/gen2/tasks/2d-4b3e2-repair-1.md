# 2d-4b3e2-repair-1: qualified positive controls for four registry mutants (round 2 of 3)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3e2-astra-review-20261014.md`, round 1 at `1013ed6`.
- **Gate A PASS, Gate B PASS, Gate C BLOCK**, classified ROOT-CAUSE.
- **The only blocking item is C1.** There are no non-blocking items, and no production change is requested.
- **Evidence:** `~/work/research-loops-public/private/evidence/astra-2d-4b3e2/`, files `control-path-probe.py`, `control-path-probe.json` and `control-summary.json`.

## C1: four paired controls never reach the changed predicate
The positive-control rule in `tools/gen2_mutation_controls.py` requires a separate passing control that takes an accepted path through the code the mutant changes. For a module constant, that means a function must read it. The four mutants defined at `tools/gen2_mutants/extractor_registry_2d4b3e2.py` (around line 45) don't meet it:
- **`2D4B3E2-router-membership`:** its control `RegistryDDLTest.test_control` is raw SQL only and never calls `ExtractorRegistry.require_tool`.
  - **Pair it with an accepted Router extraction control** that goes through the membership guard.
- **`2D4B3E2-router-replay`:** its control `RegistryTest.test_control` never replays a registration, so `_write`'s comparison never runs.
  - **Add a separate successful identical-registration replay control** with unchanged-state readback.
- **`2D4B3E2-registry_version-classification` and `2D4B3E2-extractor_registry_version-classification`:** the raw control never runs Store's integer preparation and never reads `IDENTITY_COLUMNS`.
  - **Pair each with a passing Store write control** that actually consumes that classification.

**For each of the four:**
- show with a trace that the baseline control reaches the changed code;
- show the control still passes under its mutant;
- regenerate the four entries through the accepted generator or manual mechanism;
- rerun the affected mutants;
- **correct the evidence claim** that all 37 new mutants had qualified controls.
- **Audit the other 33 new pairings the same way** and fix any others found.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2. Tests and tooling only.
- **Before committing:**
  - targeted tests and the full composition module (`gen2.tests.test_router_composition`);
  - `--only` on the affected families;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Environment:** disposable snapshots copy `.venv-gen2` (`cp -a`) and never symlink it. Don't refresh it during mutant runs. Before any heavy run, wait until no `gen2-landing-*` systemd user unit is active.
- **Reading:** anything in the repo, the private design records named in `docs/gen2/tasks/2d-4b3e.md`, and `~/work/research-loops-public/private/evidence/`. Never search `/home/trevor` or `/home/trevor/work` outside them. No provider calls.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3e2-repair-1/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
