# Task 2q-a-repair-4: complete the recognition boundary and the subprocess-validity boundary

**Source:** Astra's 2q-a-repair-3 review, `~/work/research-loops-public/private/reviews/gen2-2q-a-repair-3-astra-review-20261005.md`. Read it in full, especially F1–F4, the checklist table, the Gate C audit and the disclosure corrections. Evidence: `private/evidence/astra-2q-a-repair-3/independent-2_b30ra6/`, especially `inside-probes.json`, `new-probes.json` (**every** probe, including the class-loop target, loader assignment alias and aliased `__all__` mutation the report's table only mentions), `supplemental-probes.json`, `boundary-probes.json`, `mixed-crash-mutant.json`, `mixed-crash-children.jsonl`, `per-test-audit.md` and `per-test-audit.json`.

**Status:**
- Gate A BLOCK, Gate C BLOCK, Gate B PASS. Family: MITIGATION.
- This is the first BLOCK since Gate D #4. Two more consecutive BLOCKs trigger Gate D #5.
- No new operator permission is needed: these are defects within the ratified contract. **Don't** narrow an approved form (ordinary `__eq__`, bare `@dataclass`), drop a required refusal, or widen a row; any of those needs an operator amendment.

**Keep, already accepted by Astra:**
- checklist item 0 (ratification);
- item 4 (one transition plan, R3 ROOT-CAUSE);
- the `_no_reading` replacement and its declared measurement change;
- the six rebuilt R4 mutants;
- the 27/27 historical reproduction;
- the unchanged accounting, thresholds and directions;
- the withdrawal of `classify`.

## The design requirement: positive recognition, not a list of known bad forms
Three rounds of fixes for individual spellings show the cause. The guard refuses the forms it knows to be bad, and the index trusts everything else. **Turn that around.** Every construct that can **bind or rebind a name** in a module or class namespace, or **change an attribute or member** of a measured module or class, has to be one of a finite, enumerated set of recognised forms whose effect the index records. **Anything else is refused,** in whichever structural position it appears: statements, expressions inside function headers and annotations, defaults, decorators, class bodies, comprehensions, loop targets, `global`/`nonlocal` redirection, imports, walrus expressions, and attribute or subscript stores on imported modules or classes.

The recognised set comes from the contract's supported rows. A new form gets in only by a contract amendment, never by the tool's default. State this closure rule explicitly in SOURCE-CONTRACT.md as part of v1's enforcement (it is not a scope change), and make the tool enforce it structurally: one dispatcher over binding and store sites in which an unrecognised kind is a refusal.

## Required
1. **F1, effective members.**
   - The index must record the **implicit** members that approved forms create, and their effect on ownership: `__eq__` without `__hash__` gives `__hash__ = None`, and the dataclass `eq`/`frozen`/`unsafe_hash` combinations follow Python's documented rules.
   - Correct the dataclass transformation record.
   - Ownership and attribution use the effective member, so a masked inherited method is not attributed to the ancestor.
   - Prove it against Python for both of Astra's F1 cases in both services, and for the dataclass flag matrix you support.
   - Use primary documentation: the Python data model on `__hash__`, and the `dataclasses` docs.
2. **F2, the binding and dispatch holes, all closed by the positive-recognition rule:**
   - dataclass fields shadowing inherited methods (the generated instance write must be refused as a method override, or modelled);
   - external precedence through **ancestors**, not just direct bases (`A(UserDict)` → `C(A, B)`). Refuse a hierarchy where an external class's MRO position could supply a name that the project attribution claims, unless its absence is established;
   - attribute stores on imported modules or classes (`a.A = object`);
   - walrus and other binding expressions in function headers, annotations and defaults;
   - `global` plus import rebinding;
   - assignment of `__getattribute__`, `__getattr__` or other hooks by any form, not just `def`;
   - the class-loop target, the loader assignment alias, and mutation of an aliased `__all__`;
   - every other probe in `new-probes.json`.

   Locators: a qualified owner whose namespace has been replaced must not satisfy the locator.
3. **F3, the loader.** Pin the reviewed implementation of the adapter loader. Its function's normalised AST (or an equivalent structural fingerprint) is recorded in the contract, and any change is a refusal until the contract is amended. Also keep the fixed package, filter and discovered-file inventory. Astra's `continue`→`pass` edit must be refused.
4. **F4, subprocess validity.**
   - **Incomplete execution dominates.** Any incomplete required child in a killer makes the mutant INVALID, whatever sibling assertions do. Fix `verdict` in `tools/gen2_mutations.py` and its misleading "other setup error" message. Add a regression with mixed subtests (one assertion failure plus one incomplete child, which must be INVALID).
   - **Positive completion witness.** Exit 0 or 1 alone is not completion. The tool child must emit a completion record: for example, a final structured line or file written only on a normal return, carrying its outcome. `Repo.run` must require that record; an `os._exit(0)` child with no record, or an exit-1 child with a suppressed excepthook, is incomplete.
   - Preserve the complete child results.
   - Then rerun the whole mutant population under the stricter rule and rebuild, as behavioural counterfactuals, any kill it newly invalidates.
5. **Disclosure and test corrections.**
   - A refused `report` writes partial artifacts. Correct the diagnostic ("nothing was measured, recorded or certified") and its contradictory test so they say it is partial, incomplete and non-passing, and mark the artifacts themselves non-certified.
   - Apply the six rejected assertion-claim rewrites from `per-test-audit.md`.
   - Describe the 176-test payload selection accurately: it includes 16 new tests.
6. **Probes as permanent regressions.**
   - Every probe in Astra's `inside-probes.json`, `new-probes.json`, `supplemental-probes.json` and `boundary-probes.json` becomes a regression that fails at `dbe5dd4` and passes now, in both services where Astra ran both.
   - Each carries an interpreter-backed control showing what Python actually does.
   - Add mutants with paired controls for: the positive-recognition dispatcher (an unrecognised kind silently accepted); the effective-member model; ancestor precedence; the loader fingerprint; and completion dominance.
7. **Verify.** Run `make gen2-check`, then `make gen2-gateway`, unpiped and one after the other. Production has to stay inside the contract **without** further production edits. If the stricter rule refuses current production code, stop and report it; don't edit production.

## Constraints
- Branch gen2.
- Change only tools, tests, docs, the register and SOURCE-CONTRACT.md. No production change in this task. The oracle stays unedited.
- No provider calls. Never touch the live gen-1 gateway or 127.0.0.1:8765. Don't search `/home/trevor/work` recursively.
- Don't edit BUILD-STATE.md or REVIEW-LOG.md; the orchestrator owns them.
- Evidence goes to `~/work/research-loops-public/private/evidence/2q-a-repair-4/`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Use `git commit <paths>`.
- The completion report covers:
  - the root cause in one sentence;
  - the recognised-form set and how an unrecognised kind is refused;
  - each of F1–F4 and items 5–6 with evidence paths;
  - net lines;
  - a literally true Remaining section.
