# 2d-1-repair-1: obligation-assessment binding must honour the whole approved-contract decision family (Astra 2d-1 round 1, F1 and N1)

**Source:** `private/reviews/gen2-2d-1-astra-review-20261010.md`, pinned 77200eb.
- **Verdicts:** A BLOCK, B PASS, C BLOCK.
- **Round:** round 1 of 3. The next review checks blocking findings only.
- **Already accepted, don't touch:** DOSSIER.md, including its inventory, slice map, assembly architecture and flagged decisions, and everything else in slice 1.

## F1 (High, blocking class (d); Astra flags boundary drift)
- **The defect:** `obligation_assessments_bound` in `gen2/store/schema/08-obligation-assessments.sql:41` accepts only `d.kind = 'contract_approval'`.
- **The established authority** (SQL part 01 `contract_approval_bound_to_revision` at about line 506, and `Router._apply_decision` / `_approve_contract`) accepts three kinds: **`contract_approval`, `amendment_approval` and `reframe_approval`**.
- **Effect:** valid, exactly pinned, on-scheme assessments are refused (`payload_invalid`) after an approved amendment or reframe.
- **Reproduction:** `private/evidence/astra-2d-1/approval_kind_probe.py`. Counterfactual: `approval-kind-counterfactual.log`.

## Required (root cause)
1. The binding accepts the whole approved-contract decision family. It must keep the exact topic, revision, hash and disposition checks, plus the invocation, operation, confidence and G-1 checks. Reuse the established family definition from part 01 rather than restating a second list, if the DDL mechanism allows it.
2. **Positive admission controls for all three approval kinds**, including a real reframe, and new work under its current pins. Keep the refusals for: off-scheme, forged, wrong-topic, wrong-subject, and incompatible old work.
3. **A paired mutant** that restores the erroneous single-kind restriction.
4. **N1 (fold in):** add a raw-DDL **valid categorical** positive control, plus a one-field negative matrix (label, version, attribution) next to it.
5. **Don't** relabel operator approvals, and don't weaken the reframe or G-1 rules.

## Constraints
- **Coder:** GPT-6.1-Sol, branch gen2.
- **Checks before committing:**
  - targeted tests;
  - the full composition module;
  - `--only` on every mutant family that targets an edited file;
  - the six gates.
- **Environment:** don't refresh `.venv-gen2` during mutant runs. Never run a migration against a real database.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-1-repair-1/`.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
