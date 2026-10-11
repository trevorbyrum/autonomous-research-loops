# 2d-3b3-repair-1: bind support to the exact checked capture (Astra 2d-3b3 part 1, round 1: F1, F2)

**Source:** `private/reviews/gen2-2d-3b3a-astra-review-20261011.md`, pinned 4eba3c6.
- **Verdict:** A BLOCK, B PASS, C BLOCK.
- **Classification:** computation and storage are ROOT-CAUSE. The consumption and quarantine family is MITIGATION.
- **Round:** 1 of 3.

**Accepted; keep as is:**
- governed computation and authentication;
- validation outside the writer transaction, with revalidation at commit;
- lossless persistence and DDL 11 compatibility;
- quarantine scoped to the quote;
- placement.

## Root cause (one family)
**Authority is attached to a check reference the caller chooses freely, not to the exact captured evidence that a disposition consumes.**
- **F1.** A `supports` receipt that names a *matching* check can cite a different span, source version, work, obtained hash or normalization version. It still reaches load-bearing `accepted_support`.
  - The receipt trigger (`03-evidence-and-decisions.sql:581`) compares only the check ID, claim revision, declared hash, status and quarantine.
- **F2.** A receipt with `exact_quote.status = "not_applicable"` and `quote_check_id = null` skips the quarantine fence (`11-governed-quote-checks.sql:34`).
  - `claims_accepted_support_needs_receipt` (`03:353`) then promotes a load-bearing revision whose captured quote is quarantined.
  - A non-load-bearing quarantined capture promotes with no receipt at all.

## Required: fix the relationship once, across admission and consumption
1. **Receipt admission binds the receipt to the governed check actually used.**
   - The work and source version, cited spans, artifact identity and normalization identity must **equal** the governed check's.
   - Define how multiple cited spans work. **Each** cited span needs its own matching, non-quarantined governed check. A matching passage must not certify an unchecked one.
   - Enforce this in the Router collaborator **and** in DDL, the same way earlier slices doubled their guards.
2. **Quote eligibility comes from the capture, not from the caller's choice of reference.**
   - Every support or disposition consumer reads the claim revision's **governed capture** and its recorded checks. Those consumers include receipt admission, `claims_accepted_support_needs_receipt` and any other promotion path.
   - If the capture has a quote, a `not_applicable` check or a missing check reference is refused.
   - A quarantined capture can't reach `accepted_support` (or any support disposition) by any path, load-bearing or not.
   - Legitimate non-quote evidence (claims with no captured quote) keeps working.
   - The block applies to the affected capture, never to the whole source.
3. **Re-capture identity.**
   - A matching re-capture gets a new, explicit capture identity.
   - It never erases or relabels the old mismatch, which stays immutable.
   - Only the new capture's own matching check can support.
4. **Tests.** Write the expected values by hand and run them through the Router, plus raw-DDL counterparts.
   - One-field substitution refusals: span, source version, work, artifact hash, normalization version.
   - The null-reference/`not_applicable` bypass: load-bearing and non-load-bearing.
   - An existing-receipt case.
   - A matching new capture that does support.
   - Whole-store rollback assertions.
   - Paired legitimate receipts as controls.
   - **Load-bearing promotion attempts**, to prove consumers are protected.
   - A paired mutant for each guard.
5. **Out of scope:** owner notification and refusing byte-mismatch adjudication stay in part 2 (Astra NB1). Don't do them here unless they fall out naturally.

## Constraints
- **Coder:** GPT-6.1-Sol, branch gen2.
- **Size:** about 500 lines. If it won't fit, split it, but **the F2 fence and the F1 binding must land together in the first part**, because the current state allows false support.
- **`service.py`** is at 1,422 lines: wiring only.
- **Before committing, run:**
  - targeted tests;
  - the full composition module;
  - `--only` on every mutant family that targets an edited file;
  - the six gates.
- **Environment:**
  - Don't refresh `.venv-gen2` while mutants run.
  - Ordered DDL only. Never run a migration against a real database.
- **Reading:** you may read anything in the repository and the named private paths, including Astra's probes in `private/evidence/astra-2d-3b3a/`. Never search `/home/trevor` or `/home/trevor/work` outside them.
- **No** provider calls.
- **Don't edit** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-3b3-repair-1/`.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
