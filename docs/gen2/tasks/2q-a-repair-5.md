# Task 2q-a-repair-5 (slice 1 of 3): one shared binding-identity resolver

**First task under the charter's "Review throughput" rules** (operator 2026-10-05):
- Target **≤ ~500 hand-written lines**, excluding the generated mutation-controls JSON.
- Only **blocking** findings are in scope.
- Run **targeted** tests and `--only` mutants while working, and **don't run `make gen2-check` or `make gen2-gateway`**. The orchestrator runs both once at landing. If the controls trace is needed for new mutants, run it on a snapshot as before.

**Source:** Astra's 2q-a-repair-4 review, `~/work/research-loops-public/private/reviews/gen2-2q-a-repair-4-astra-review-20261005.md`. Read F1, the Gate C section and the **"Follow-up 2026-10-05"** section, which classifies every finding and names this slice. Evidence: `private/evidence/astra-2q-a-repair-4/`, especially `closure-probes.py`, `closure-probes.json` and the nonlocal fixture.

**Status:** two consecutive BLOCKs since Gate D #4. A BLOCK on this slice is the third, and goes to the operator.

**The slice plan:**
- **slice 1 (this task):** F1 binding identity;
- **slice 2:** F1 call-time owner effects, meaning module or class values that escape through helpers, containers or parameters, and namespace-dictionary mutators;
- **slice 3:** the F2 quoted dataclass field markers.

The non-blocking items are DEBT-016, owned by a later 2q tooling and documentation slice. **Don't** work on slice 2, slice 3 or DEBT-016 here, and don't claim the family is closed.

## Required
1. **One resolver.** Explicit imports, aliases (including tuple-unpacked aliases), qualified module chains and explicit re-exports resolve through **one** binding-identity resolver in the shared source index. The guard, the metrics and the locators all consume it. No consumer keeps its own resolution path.
   - Re-exported or aliased loader producers must resolve to their real identity, so Astra's re-export of `import_module` is refused as a loader.
2. **`nonlocal` resolution.** A `nonlocal` write resolves to the enclosing scope that actually binds the name, skipping intervening functions that don't. Astra's `factory → middle → replace` fixture must give either the true owner or a refusal, never stale `A` with one cross-file site, in both services.
3. **Gate C, linked items:**
   - `test_refuses_nonlocal_and_global_inside_closures` gets real `nonlocal` redirection cases, including an intervening function with no binding, asserting the resulting owner or refusal.
   - In `test_accepts_stores_the_contract_does_not_restrict`, remove or rewrite the expectations that **this slice's** resolver now decides. Leave a dated note pointing at slice 2 for the call-time cases it can't yet decide; don't keep them as closure evidence.
   - The manual walrus-data control must not claim support beyond its narrow path.
4. **Regressions.**
   - Astra's alias, re-export and nonlocal probes from `closure-probes.json` that this slice covers each become a regression that fails at `01fa8ad` and passes now, with an interpreter-backed control.
   - Targeted mutants, with paired controls, for: a consumer bypassing the shared resolver; nonlocal binding to the nearest function; an alias not followed.
5. **Docs.** Make SOURCE-CONTRACT.md accurate about what slice 1 closes. Remove the false statement that an unrecognised producer "returns a new object"; slice 2 decides that case, so mark it open with a pointer, not as an exclusion. The contract version stays v1; no row is widened or narrowed.

## Constraints
- Branch gen2.
- Change only tools, tests and docs. No production change. Leave the baseline, ledger and accepted accounting unchanged unless the resolver changes a measurement; if it does, declare that as a measurement change.
- No provider calls. Never touch the live gen-1 gateway or 127.0.0.1:8765. Don't search `/home/trevor/work` recursively.
- Don't edit BUILD-STATE.md, REVIEW-LOG.md or DEBT-REGISTER.md.
- Evidence goes to `~/work/research-loops-public/private/evidence/2q-a-repair-5/`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Use `git commit <paths>`.
- The completion report covers:
  - the root cause of the slice in one sentence;
  - each item with evidence paths;
  - the hand-written net lines, against the ~500 target;
  - the targeted tests and mutants you ran;
  - a literally true Remaining section that names slices 2 and 3.
