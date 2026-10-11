# 2d-4b3c-repair-1: repair the governed-quote support control under SQL 18 (round 2 of 3)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3c-astra-review-20261011.md`, round 1 at `ead2779`.
- Gates A and B passed; Gate C blocked.
- The only blocking finding is **C1**. There are no non-blocking findings.

## C1: `gen2/tests/test_governed_quotes.py`, `AdmissionTest.test_support_control`
**The problem.**
- `QuotesCase` builds a `verifier_extraction` receipt from `gen2/schema/examples/verification-receipt/valid-load-bearing-full-text.json`.
- It never admits a matching SQL 14 acquisition.
- So SQL 18 correctly rejects the receipt, and the landing `gen2-check` exits 2.

**The repair.**
- Give this positive control admitted input with matching acquisition operands. Use the existing admitted-input fixture pattern.
- Keep all of these intact:
  - `verifier_extraction`;
  - the governed-quote binding;
  - the original commit and readback assertions;
  - the literal quote-only checks;
  - `test_partial_support_blocked`.
- Do **not** remove or weaken SQL 18. Do not turn the positive control into an expected refusal.
- Astra's reviewer-only proof shows a fixture-level repair works, with 2 of 2 passing: `~/work/research-loops-public/private/evidence/astra-2d-4b3c/fixture-repair-probe.py`.

**Root cause in the process.**
- The targeted selection matched extraction-method names, but this test reaches the method through a schema example document.
- Before committing, audit every test that loads a verification-receipt schema example, or that uses `receipt_document` or `verification_receipts=`. Any that commit an extraction receipt need admitted input. Record the audit in evidence.
- Candidates include:
  - `canonical_quotes_fixtures.py`;
  - `test_capture_support.py`;
  - `test_quote_attention.py`;
  - `test_store_ddl_export.py`;
  - `test_verification_attention.py`.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2. Tests only; no production or DDL change is expected.
- **Before committing:**
  - the repaired module, the audited modules and the full `gen2.tests.test_router_composition`;
  - `--only` on every mutant family whose paired controls use an edited test file or fixture;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Environment:**
  - don't refresh `.venv-gen2` during mutant runs;
  - never run a migration against a real database;
  - no provider calls.
- **Reading:** anything in the repo and the named private paths. Never search `/home/trevor` or `/home/trevor/work` outside them.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3c-repair-1/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
