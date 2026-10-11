# 2d-4a-repair-1: isolate the open-creation negative test (Astra 2d-4 part 1, round 1, C1)

**Source:** `private/reviews/gen2-2d-4a-astra-review-20261011.md`, pinned d16613d.
- **Gates:** A PASS, B PASS, C BLOCK.
- **Round:** 1 of 3.
- **Scope:** a test-only repair. The runtime change is accepted.

## C1
- **Where:** `gen2/tests/test_verification_attention.py:175–177`, the `{"cleared_at": T}` case.
- **The problem:** this case violates the table CHECK as well as the trigger. The CHECK requires a clearance reference whenever `cleared_at` is set. So the test still passes when `holds_created_open` is removed, which means it isn't really testing that trigger.
- **The counterfactual:** `private/evidence/astra-2d-4a/ddl-counterfactual.json`.

## Required
1. Rewrite the case so that every unrelated CHECK and foreign key is satisfied. Use a **real** clearance operation reference, and assert the specific refusal ("created open"), not a generic `IntegrityError`.
2. Keep an ordinary open-row control.
3. Show that deleting `holds_created_open` makes the new negative fail while the control still passes. Bind the case to the existing `A2-holds-created-open` mutation, or add an equivalent paired mutant.
4. The owner, deadline and class shape cases can stay as they are.
5. **NB1, documentation only:** in DOSSIER §2d-4, describe the behaviour as a "missing-content cause on a judgment hold". Describe ownership as "owner from producer lease, deadline from producer invocation".

## Constraints
- **Coder:** GPT-6.1-Sol, branch gen2. Don't change production code.
- **Before committing, run:**
  - the targeted tests;
  - the full composition module;
  - `--only` on the affected mutant families (`2D4-`, `A2-`);
  - the six gates.
- **Don't** refresh `.venv-gen2` while mutants are running.
- **Reading:** anything in the repo and the named private paths. Never search `/home/trevor` or `/home/trevor/work` outside them.
- **No** provider calls.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4a-repair-1/`.
- **Commits:** end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
