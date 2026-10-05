# Task 2q-a-repair-3: the supported-source contract (Gate D #4, option B). One family repair against checklist 0–8

**Source:** Gate D #4, the rerun at 4f1ae96 (`~/work/research-loops-public/private/reviews/gen2-gate-d-4-astra-review.md`). Read it **in full**, especially §1 (F1–F5), §3 (the contract table and checklist 0–8), §4 (proportionality and `_no_reading`) and §7. Evidence: `private/evidence/gate-d-4-rerun/`, including `production-source-inventory.json` and `admission-workflows.json`. Also read the three 2q-a reviews it cites.

**Operator rulings 2026-10-05** ("I agree", on all three Gate D #4 recommendations):
1. **Option B is adopted.** The architecture metrics are computed exactly over a declared, guarded supported-source subset. An unwaivable source-refusal stage runs before measurement. Repair-2's permission to pass analysis by classifying unresolved source in the ledger is **withdrawn**; amend the claims and tests that relied on it.
2. **The minimal production change is authorized before 2q-a acceptance.** Replace `_no_reading` (`gateway/research_gateway/core/payload.py`) and its two uses (`Sealed`, `Passive`) with explicit, statically represented methods, sharing the refusal implementation where behaviour allows. Behaviour stays unchanged: every existing payload refusal and materialization oracle must still pass unedited. Add no method aliases that would fall outside the contract.
3. **Sequencing:** that production change is part of **this** repair, not a separate 2q-b slice. The 2q-a family review history continues: this is still the 2q-a family, under Gate D #4's checklist.

The repair is one ordered family repair, not a series of fixes for individual spellings.

## Required: Gate D #4 checklist 0–8, in order
0. **Ratify.** Write `docs/gen2/SOURCE-CONTRACT.md` as **version 1**: Gate D #4's §3 table (every row: supported forms and refusal categories), the transform/external-terminal records (resolved identity, allowed argument shape, effect), the dynamic-loader inventory (`adapters/__init__.py:18`, with a fixed package, filter and discovered-file inventory) and the explicit non-graph exclusions. Cite these operator rulings. Amend repair-2's claims and tests about unresolved classification.
1. **One recognition boundary.** Parse and inventory once into one shared source-fact index (definitions, scopes, binding roles, class bases, method ownership, diagnostics) covering **both services**. Validate the structural forms before measurement.
   - The metrics, `report`, `admit`, bootstrap, `rebaseline` and the locator commands all consume the index, including when they are run directly.
   - On refusal: diagnostics name the file, line, construct and remediation; `report` shows the input as incomplete and non-passing; and no baseline or ledger is written.
   - The boundary checker keeps its own authority policy.
   - Fixtures: positive and refusal fixtures for every contract row in both services, including unused or isolated unsupported declarations.
2. **Bring production inside the boundary.** Make the `_no_reading` replacement (ruling 2) and audit the approved decorator and loader entries against the inventory (14 dataclass decorators, property/static/class methods, context managers, `_serial`/`wraps`, the four nested classes, the three conditionally defined helpers). If recognition changes a measurement, report it as a **measurement change**, not as an architectural improvement.
3. **Close R1/R2 at the shared representation.**
   - Keep unique lexical function identities and both complexity scores.
   - Use C3 over admitted source, and count each `(site, defining file)` once across overlapping families.
   - Never drop an unknown method from a surviving pair and call the result an improvement.
   - Probes: refuse the duplicate-function crossover and the conditional Router/alias/decorator/export probes; measure correctly the qualified bases, explicit re-exports, diamonds, same-file intermediates and capturing closures.
   - Back the hand-calculated counts with interpreter-based binding and dispatch controls.
4. **Ledger and drafting (R3).** Check, draft and fold all use one effective transition plan: existing maps and retirements first, then remaining admissions and budgets derived from that plan. Preserve the old ceilings and MI IDs. Gate D #4's acceptance cases include:
   - a rename plus a new file/import;
   - no drafted retirement of a mapped ID;
   - idempotent drafting, before and after reasons are filled;
   - a destination below both thresholds;
   - collisions, stale maps, and package and file moves.

   Provide deterministic expansion and grouped presentation for explicit moves, with no wildcards and no inferred correspondence.
5. **Locators.** Separate declaration-in-file queries from module/class-attribute queries over the same source facts, keeping grammar-first recognition and the `code:`/`history:` markers. Gate D #4's cases:
   - a valid class method passes;
   - a closure local is not a module attribute;
   - a replaced or unsupported owner can't satisfy a qualified locator;
   - deleted prefixes and malformed forms fail.

   The 15 debt entries and phase-close checks keep their meaning.
6. **R4 evidence.** Replace the six crash mutants with executable wrong-behaviour counterfactuals.
   - Validate a tool subprocess's completion independently of the parent unittest's assertion or failure category: no traceback, timeout, signal, load failure or missing child result counts as a behavioural kill.
   - Preserve each child's return code, stdout and stderr.
   - Each unmodified killer and its control must pass.
   - Rename the baseline-recording test whose title still says the graph is absent.
7. **Verify the assembled pin.**
   - Keep the accepted accounting, direction policy, thresholds and historical definitions.
   - Run `make gen2-check` and `make gen2-gateway` **unpiped and one after the other, not concurrently**, plus every refusal and positive fixture.
   - Show the baseline, ledger and contract diffs. Compare against history on a common analyser version; the 27-table historical reproduction obligation stands.
   - No unknown source classification may remain as a passing hole.
8. **Close the family explicitly.** The completion report explains how supported syntax yields complete facts, how unsupported syntax is refused, and how those facts carry obligations through accounting and locators.

## Constraints
- Branch `gen2`; the PR workflow isn't live yet.
- Change only tools, tests, docs and the register, plus the **one** authorized production change in `gateway/research_gateway/core/payload.py` and any test of its behaviour. The oracle stays unedited.
- No provider calls. Never touch the live gen-1 gateway, its database or service, or 127.0.0.1:8765. Don't search `/home/trevor/work` recursively.
- Evidence goes to `~/work/research-loops-public/private/evidence/2q-a-repair-3/`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Use `git commit <paths>` so you never commit files you didn't change.
- The completion report covers:
  - the root cause in one sentence;
  - the contract's version and refusal categories;
  - the checklist items 0–8 with evidence paths;
  - net lines;
  - a literally true Remaining section.
