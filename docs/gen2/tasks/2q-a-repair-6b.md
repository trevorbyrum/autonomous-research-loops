# Task 2q-a-repair-6b (slice A fix): validated scope pairing and private-name mangling

**Research basis:** `docs/gen2/research/2q-a-round-cap-20261005.md`, the **Addendum** (compiler visit order, two-way validation, mangling). Implement that design.

**Source:** Astra's slice A review, `~/work/research-loops-public/private/reviews/gen2-2q-a-repair-6-astra-review-20261005.md`, findings R6-1 and R6-2 and the non-blocking list. Evidence: `private/evidence/astra-2q-a-repair-6/` (`pairing-probes.json` and the private-name probes).

**Operator direction:** fix → review → move on. **Review-throughput rules apply:** target ≤ ~500 hand-written lines; targeted tests and `--only` mutants only; the orchestrator runs the full targets at landing.

## Required
1. **R6-1, pairing.** Pair AST scopes with `symtable` tables following the compiler's visit order. In particular, a comprehension's first iterable is visited before its own scope; check the order for lambdas, default arguments, decorators and class bases too.
   - **Validate every pairing both ways.** The AST scope's identifiers, after mangling, must equal the table's identifiers, ignoring compiler-internal names such as `.0`. Any mismatch, unpaired table or unpaired scope is a refusal naming the file and line.
   - Add Astra's generator fixture (`tuple((A := object) for q in (q for q in (1,)))`) in both services, with an interpreter-backed control, a matching accepted control, and an assertion killer for the wrong-table assignment.
2. **R6-2, mangling.** Apply Python's private-name mangling (`__name` without a trailing `__` becomes `_Class__name`, with the class name's leading underscores stripped and nothing mangled when the class name is all underscores) to every read and write looked up in a class context, nested scopes and parameters included.
   - A missing symbol for an **executable** binding is a refusal, never a module or global fallback. Only genuinely unevaluated annotations take the annotation path.
   - Regressions: Astra's duplicate `__helper`, which must be `SRC-DEF-DUPLICATE`; the `__helper = None` rebinding, which must be `SRC-DEF-REBOUND`; a single private method keeping its effective member; and a private local import used as a nested class's base, which must be accepted. All with interpreter-backed controls, in both services.
3. **Mutants** with paired controls: pairing without validation; mangling skipped; a missing executable symbol falling back to global.
4. **Docs (non-blocking item):** narrow SOURCE-CONTRACT's `typing.get_type_hints` analogy to the exact annotation policy. Record the 3.12.3 reference limit: the AST and table correspondence is validated only for the reference interpreter.

Production facts and metrics must stay identical. Report any difference, and confirm 0 refusals on production. Don't start slice B, which is held for an operator decision.

## Constraints
- Same as 2q-a-repair-6, with evidence going to `~/work/research-loops-public/private/evidence/2q-a-repair-6b/`.
