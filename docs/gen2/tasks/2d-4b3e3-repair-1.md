# 2d-4b3e3-repair-1: cap validated support by the independent extraction's tier (round 2 of 3)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3e3-astra-review-20261016.md`, round 1 at `ba94b99`.
- **Gate A BLOCK, Gate B PASS, Gate C BLOCK; MITIGATION while F1 remains.**
- **Already accepted, don't reopen:**
  - trigger retirement;
  - same-receipt gate binding;
  - historical registry interpretation;
  - canonical capture is unchanged.
- **Evidence:** `~/work/research-loops-public/private/evidence/astra-2d-4b3e3/probe_tier_matrix.py` and `probe-tier-matrix.json`.

## F1 (HIGH): full-text support can rest on a bibliographic-only independent extraction
**The problem.**
- SQL 34 (`gen2/store/schema/34-bound-extraction-support.sql`, around lines 7–31) resolves `validation.target_extraction_id` as the basis and compares only the **target's** `supported_tier` with the receipt.
- It never consumes `validation.validator_extraction_id`'s supported tier.
- So a successful `/2` `semantic_agreement` validation whose independent extraction is recorded as bibliographic-only can authorize a full-text claim. It also works for bibliographic→abstract and abstract→full-text: 9 incorrect promotions across the Router, raw DDL and reversed trigger order.
- SQL 17 used to hide this. Replacing it exposed it.

**Required (root cause).**
- **Cap validated receipt and support authority by all three of:**
  - the **target's** supported tier;
  - the **exact independent (validator) extraction's** supported tier;
  - the acquisition's recorded-content ceiling.
- **Enforce it at the consuming rule** (promotion, SQL 34 and the Router), so that validations and receipts already retained can't use the gap. An admission-only fix isn't enough.
- **Keep unchanged:** SQL 31's current-at-admission rule and the retained registry interpretation.
- **Keep low-tier or failed records as history.** No success label or adjudication waives the missing tier.
- **Keep the own-extraction path's existing cap.**
- **Tests:**
  - isolated Router, raw and reversed-order negatives where the target and acquisition are sufficient and **only** the independent output is insufficient, for all three insufficient pairs;
  - controls where the independent output is sufficient;
  - a paired predicate mutant for the new comparison, with a control path trace.
- **Fix `PromotionCases.test_bindings`.** Its tier case lowers *all* extractions, so it can't separate the two operands. Add asymmetric cases.
- **Docs.** V-2, V-3, V-4, BOUNDARIES and DOSSIER must state the two-operand ceiling.

## N1 (LOW): control rationale accuracy
- `tools/gen2_mutants/bound_extraction_support.py`: the two method-branch mutants' rationale strings claim the controls cover all three tiers. The actual controls (`test_history_control` and `test_own_control`) are full-text only.
- Correct the strings and regenerate the records.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2.
- **Ordered DDL.** Editing the undeployed SQL 34 is acceptable; say which you chose.
- **Never run a migration against a real database.**
- **Before committing:**
  - the full `make gen2-test`;
  - `make gen2-trigger-order`;
  - the full uncovered-trigger inventory, or the full `make gen2-mutation`, if any trigger changes;
  - the full composition module (`gen2.tests.test_router_composition`);
  - `--only` on the affected families;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`;
  - an explicit classification repin after any DDL change.
- **Environment:**
  - Disposable snapshots copy `.venv-gen2` (`cp -a`). Never symlink it.
  - Before any heavy run, wait until no `gen2-landing-*` unit is active.
- **Reading:** anything in the repo, the private design records named in `docs/gen2/tasks/2d-4b3e.md`, and `~/work/research-loops-public/private/evidence/`. Never search `/home/trevor` or `/home/trevor/work` outside them. No provider calls.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3e3-repair-1/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
