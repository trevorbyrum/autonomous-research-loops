# Research before re-briefing: 2q-a at the round cap (2026-10-05)

**Trigger:** 2q-a reached the round cap: three consecutive BLOCKs since Gate D #4, with the binding and recognition family recurring in every round. This note applies the charter rule "Research before re-briefing".

## Question
What is the best-supported way to close the open 2q-a findings? They are: scope-declaration lookup (`global`/`nonlocal`), alias uncertainty, values escaping through helpers and containers and then mutating a namespace, quoted dataclass field markers, and weak paired controls. The alternative is to accept them as debt.

## Findings
1. **No realistic static analyser is fully sound; the standard is "soundy".** The usual design handles most language features soundly and *deliberately, explicitly* under-approximates a small named set of hard dynamic features: reflection, eval, runtime namespace mutation. Livshits et al., "In Defense of Soundiness" (CACM 2015), via GraphRAG `codegraph-evidence`. None of Soot, WALA or Doop builds a sound Java call graph across benchmarks, and feature support among "soundy" Java frameworks ranges from 42/122 to 102/122 test cases (Reif et al. 2019, `codegraph-evidence`).
2. **The state of the art for Python is precise but incomplete.** PyCG reaches about 99.2% precision and about 69.9% recall on real projects, and deliberately doesn't resolve dynamic constructs (Salis et al., ICSE 2021, arXiv 2103.00587). Architecture linters in production use, such as import-linter and grimp, check explicit import statements only. Dynamic imports are out of scope by design.
3. **Python exposes the compiler's own scope analysis.** The stdlib `symtable` module gives, for every name in every scope, whether it is local, explicitly or implicitly global, nonlocal, free or cell, exactly as the compiler computes it. It also raises `SyntaxError` on compiler-invalid `nonlocal`. Verified locally on 3.12: Astra's nested `global A` fixture resolves as declared-global, and both invalid-nonlocal forms from the 2q-a-repair-5 review raise "no binding for nonlocal".
4. **Combining independent analysers beats any single one.** In one JavaScript study, two independent tools together reached 98% precision and 99% recall, beating every tool alone (arXiv 2405.07206, `codegraph-evidence`).
5. **Repo fact:** production code has no quoted annotations in class bodies (grep; the only hit is a docstring).

## Implications for 2q-a (orchestrator's inference, not research fact)
- **Scope (F1, plus the invalid-nonlocal debt):** replace the hand-written scope resolution with `symtable`. The compiler becomes the authority for scope, which removes this whole sub-family rather than patching cases.
- **Escaping values, namespace mutation and unlisted loaders (slice 2):** trying to track values through helpers is exactly the problem the literature says no tool solves soundly. The supported alternative is soundiness:
  - SOURCE-CONTRACT names the excluded dynamic features explicitly.
  - It bans their *mechanisms* outright in production code wherever they appear: `setattr`/`delattr` and `__dict__`/`vars()`/`globals()` writes, `importlib`/`__import__` outside the one inventoried loader, three-argument `type`, and `exec`/`eval`.
  - There is no value tracking. The guarantee becomes "exact for supported forms; named mechanisms refused; nothing else claimed", which is achievable and checkable. This is a contract amendment (v2) for the operator.
- **Quoted dataclass field markers (slice 3):** refuse quoted annotations in class bodies, which current code doesn't use. This also narrows forms, so it's part of the same amendment.
- **Weak paired controls:** mechanical; write controls that reach the changed line.
- **Optional:** cross-check the import graph against an independent analyser (grimp) and report disagreements; advisory only.

## Addendum, 2026-10-05: slice A's adapter regressions (Astra's 2q-a-repair-6 review, R6-1 and R6-2)
The binding family recurred inside slice A's AST-to-`symtable` adapter, so the charter requires research before re-briefing.
- **Compiler scope order.** CPython's symtable pass visits a comprehension's **first iterable before** entering the comprehension's own scope (CPython 3.12.3 `Python/symtable.c`, around line 2384, cited by Astra). So `symtable` children don't come in AST pre-order when an iterable contains a nested scope. Verified locally: for `tuple((A := object) for q in (q for q in (1,)))`, the children are `genexpr` with identifiers `{.0, q}` first, then `genexpr` with `{.0, A, object, q}`. Same name, same line, different identifier sets.
- **Private name mangling.** Inside a class body, the compiler records `__name` (no trailing double underscore) as `_ClassName__name`, with the class name's leading underscores stripped, and it looks names up the same way. This is the Python language reference, "Private name mangling", and CPython `symtable.c` `_Py_Mangle`. Verified locally: `class C: def __helper` gives the identifier `_C__helper`.
- **Implication.** Two corrections, both mechanical and both grounded in the compiler's documented behaviour:
  1. Pair scopes by reproducing the compiler's visit order, **and validate every pairing both ways**: the AST scope's names, mangled, must equal the table's identifiers modulo compiler-internal names like `.0`, and any disagreement is a refusal. Pairing by header is not proof; validating it makes a wrong pairing detectable whatever order logic is used.
  2. Apply the language's mangling rule to every identifier looked up in a class context.

  A missing symbol for an executable binding is a refusal, never a module or global fallback; only genuinely unevaluated annotations take the annotation path.
