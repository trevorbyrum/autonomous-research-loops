# Task 2q-a-repair-7 (slice B, final 2q-a slice): SOURCE-CONTRACT v2, soundy by declaration: ban the mechanisms, stop tracking escaped values

**Research basis:** `docs/gen2/research/2q-a-round-cap-20261005.md`, findings 1, 2 and 5 and the implications "Escaping values" and "Quoted dataclass field markers". **Operator ruling 2026-10-05:** continue on the researched plan, with SOURCE-CONTRACT **v2 approved** ("make the fixes, review it ... and then we'll move on").

**Rules:** review-throughput rules apply (≤ ~500 hand-written lines; targeted tests only; the orchestrator runs the full targets once at landing). Starts after slice A (2q-a-repair-6) has landed. Build on its resolver.

## Required
1. **SOURCE-CONTRACT v2.** Bump the version and record the ruling. The guarantee becomes: *exact for the supported forms; the named dynamic mechanisms are refused wherever they appear in production code; nothing else is claimed.*
   - List the excluded dynamic features explicitly, and cite "In Defense of Soundiness" and the PyCG and import-linter precedent from the research note.
   - Remove the slice-2 value-tracking claims and the "returns a new object" open item.
   - Keep everything v1 accepted: rows, transformations, effective members, the loader fingerprint and inventory, and refusal before measurement.
2. **The mechanism ban.** In both services, refuse any **reference** to these names anywhere in production code, whether called, aliased, passed, stored or attribute-accessed, except at the single inventoried loader site for `importlib`:
   - `setattr`, `delattr`, `vars`, `globals`, `locals`;
   - any `__dict__` access;
   - `importlib` (and `import_module`) and `__import__`;
   - `exec`, `eval`, `compile`;
   - three-argument `type(...)` (refuse `type` with more than one argument, or a starred call);
   - `__setattr__`/`__delattr__`/`__getattribute__` assignment or call;
   - `sys.modules`.

   It's a reference ban, not value tracking: aliasing a banned name is itself a reference.
   - First, inventory any current production uses with file and line, and report them. If one exists and can't be removed without a production change, **stop and report**; don't edit production.
   - Once the ban is in place, delete the value-tracking and escape machinery that only served slice 2's goal (store kinds that classify escaped values, and so on). Keep what the supported forms need.
3. **Quoted annotations.** Refuse a string (quoted) annotation in any class body in production code. Current production has none; verify that.
4. **Regressions.** Every one of Astra's 40 closure probes from `private/evidence/astra-2q-a-repair-4/closure-probes.json` (and the four residuals `loader-default`, `loader-walrus`, `loader-getattr`, `type-star`) must now be refused, in both services, or be shown to be a supported form that is measured correctly against an interpreter control. Add a plain-data-processing positive control so ordinary code stays accepted.
5. **Mutants** with paired controls: each banned family not refused; an aliased banned name missed; the loader-site exception widened; a quoted annotation accepted.
6. **Docs.** Correct the gen2 metrics paragraph's claims if they changed. DEBT-016 items (1) and (5), the loader context, may close if the ban covers them; say which.

## Constraints
- Same as slice A, with evidence going to `~/work/research-loops-public/private/evidence/2q-a-repair-7/`.

## Amendment: operator ruling 2026-10-06 ("Both recommended")
The first slice B coder stopped before coding, because production uses three banned mechanisms (evidence in `private/evidence/2q-a-repair-7/production-inventory.txt`). Astra's 2q-a-repair-6b review (`private/reviews/gen2-2q-a-repair-6b-astra-review-20261005.md`) left the private-name identity family open (R6B-1, R6B-2). The operator approved both orchestrator recommendations:

A. **Named exact-statement exceptions** for the three production uses, pinned the way the loader is:
   - `gen2/supervisor/jobs.py` `_HELD.__dict__.setdefault("keys", set())` (a thread-local's own data);
   - `gateway/research_gateway/core/payload.py` `object.__setattr__(self, "_value", value)` in `Sealed.__init__`, and the same statement in `Passive.__init__` (instance-slot initialisation behind a refusing `__setattr__`).

   Each exception is recorded in SOURCE-CONTRACT v2 by file, enclosing function and **exact normalised statement**, with its reason. It matches only that statement in that function; any other use of a banned name anywhere is refused, and adding an exception requires a contract amendment. The definition `def __setattr__` in `_Unread` is a definition, not a reference, so it isn't banned. State that explicitly in the contract. **No production change.**

B. **Refuse private (name-mangled) identifiers** in production code: any `__name` without a trailing `__`, used as a name, attribute, definition, parameter, import alias or global, in any context. Production has none; verify that. This closes R6B-1 and R6B-2 by removing the form instead of modelling it. The 6b mangling code may stay as defence in depth, or be simplified; either way, nothing may produce a fact from a mangled name, because the refusal comes before measurement. Regressions: Astra's R6B-1 and R6B-2 fixtures are refused in both services, with an ordinary dunder control (`__init__`, `__eq__`) still accepted.

C. Update the positive fixtures that v1 accepted for these idioms (`source_contract_fixtures.py` lines 271 and 273): they become refusals, except at the exact excepted statements. Add a control showing that an excepted statement copied into a different function is refused.

Size: this slice may exceed ~500 hand-written lines, because it removes value-tracking code; the deletions don't count against the target. Report additions and deletions separately.
