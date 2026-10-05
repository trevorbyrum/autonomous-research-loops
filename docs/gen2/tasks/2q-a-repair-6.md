# Task 2q-a-repair-6 (slice A): scope from the compiler's symbol table; the three paired controls

**Research basis (charter, "Research before re-briefing"):** `docs/gen2/research/2q-a-round-cap-20261005.md`, finding 3 and its implication "Scope". Implement **that design**; don't invent a different scope resolver.

**Operator ruling 2026-10-05** (after the round cap): "make the fixes, review it to make sure it didn't cause any other issues and then we'll move on." The operator chose to continue on the researched plan, approved SOURCE-CONTRACT v2 (that's slice B, task 2q-a-repair-7) and directed fix → review → move on. The post-2q Gate D #5 still runs before 2c.

**Review-throughput rules apply:**
- target ≤ ~500 hand-written lines;
- targeted tests and `--only` mutants only; don't run `make gen2-check` or `make gen2-gateway`, because the orchestrator runs them once at landing.

**Source findings:** Astra's 2q-a-repair-5 review (`~/work/research-loops-public/private/reviews/gen2-2q-a-repair-5-astra-review-20261005.md`):
- F1's scope-declaration part: the lookup ignores `global` (and `nonlocal`) declarations on reads;
- F2: three paired controls don't reach the changed line;
- the non-blocking invalid-`nonlocal` items.

Evidence: `private/evidence/astra-2q-a-repair-5/` (`scope-probes.json`, `blockers-cli.json`).

## Required
1. **Scope comes from `symtable`.** Use the stdlib `symtable` module, the compiler's own scope analysis, as the **only** authority for which scope a name belongs to: local, explicitly or implicitly global, nonlocal, free or cell. Do this in `tools/gen2_source_index.py`, through the shared resolver (`Facts.expr` and the lookup behind it).
   - Remove the hand-written scope classification that `symtable` replaces (`holder_of`/`lexical_chain` scope decisions, `Scope.declared` handling and the like).
   - The index still records *what* a binding refers to; `symtable` decides *where* a name lives. Map symtable scopes to index scopes deterministically: match by kind, name and line, and refuse if they can't be matched.
   - A `SyntaxError` from `symtable`, such as an invalid `nonlocal`, is a source refusal naming the file and line.
2. **Regressions,** each with an interpreter-backed control:
   - Astra's nested `global A` fixture (`factory → build`, with `a.py`/`c.py` both defining `A.f`) and its loader variant, in both services;
   - the two compiler-invalid `nonlocal` forms, now refused;
   - an accepted shadowing control.

   Each fails at `3cd4716` and passes now.
3. **Alias uncertainty (F1, second half).** Where the resolver can't resolve an ordinary alias, return an explicit unresolved result, and make every consumer refuse on it, never accept it. Add Astra's case as a regression.
4. **The three paired controls (F2):** `2QB-idx-unpacking-binds-no-value`, `2QB-idx-alias-cycle-is-external` and `2QB-con-decorator-identity-is-its-spelling` each get a control that **executes the changed line** past its guard and passes under the mutant. Use MANUAL entries if needed, and verify each with the tracer.
5. **Mutants** with paired controls: the scope taken from a hand rule instead of symtable (for example, ignoring `global`); a symtable `SyntaxError` swallowed; an unresolved alias accepted.
6. **Docs:** SOURCE-CONTRACT's "Binding identity" section states that scope is the compiler's symbol table. Mark the two invalid-`nonlocal` items of the 2q-a-repair-5 review as closed in your report; the orchestrator updates the register.

Don't do slice B's work: the mechanism ban, quoted annotations, contract v2.

## Constraints
- Branch gen2. Change only tools, tests and docs; no production change; the baseline, ledger and accounting stay unchanged unless a measurement changes, which must be declared.
- No provider calls. Never touch the live gen-1 gateway or 127.0.0.1:8765. Don't search `/home/trevor/work` recursively.
- Don't edit BUILD-STATE.md, REVIEW-LOG.md or DEBT-REGISTER.md.
- Evidence goes to `~/work/research-loops-public/private/evidence/2q-a-repair-6/`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Use `git commit <paths>`.
- The completion report covers: the root cause in one sentence; each item with evidence; hand-written net lines; the targeted tests and mutants run; a literally true Remaining section.
