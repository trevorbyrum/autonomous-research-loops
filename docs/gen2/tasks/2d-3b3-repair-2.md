# 2d-3b3-repair-2: settle the support disposition at the commit boundary (Astra 2d-3b3 part 1, round 2, F3)

**Source:** `private/reviews/gen2-2d-3b3-r2-astra-review-20261011.md`, pinned 20f209c.
- **Verdicts:** A BLOCK, B PASS, C BLOCK.
- **Root cause found:** F1 and F2 are closed at the root cause.
- **This is round 3 of 3, the cap.** If it fails, the operator decides.

**Accepted, keep:**
- the capture-identity relationship (`governed_receipt_failures`, `governed_captures_blocked`);
- receipt admission binding;
- the promotion guard `claims_accepted_support_needs_capture`;
- the Router's matching checks;
- all F1 and F2 refusals and their controls.

## F3
- **The problem.** `quote_checks_refence_capture` (DDL 12, about line 60) re-quarantines an `accepted_support` claim **per check row**. EvidenceWriter writes the checks *before* the same commit's receipts. So a valid commit that adds a matching check **plus** its bound `supports` receipt leaves an already accepted claim permanently `quarantined`, even though the final evidence is valid.
- **Reproductions:** `private/evidence/astra-2d-3b3-r2/adversarial-probes.py`:
  - `late_valid_same_commit_existing_accepted`;
  - `raw_ddl_late_valid_same_transaction`;
  - control: `late_valid_same_commit_provisional_control`.

## Required
1. **The disposition reflects the completed commit, not an intermediate state.**
   - Remove the per-row `quote_checks_refence_capture` mutation.
   - Reconcile the affected captures **once, after all of the commit's checks and receipts are written**, inside the same transaction:
     - an `accepted_support` claim whose capture is in `governed_captures_blocked` **at that point** becomes `quarantined`;
     - nothing else changes.
   - The SQL layer must still back this up.
     - **Preferred:** fire the reconciliation from a row the commit always writes **last**, for example the operation receipt, if the commit path guarantees that ordering. Verify the ordering and say so.
     - Otherwise, keep the reconciliation in the Router. Show with a raw-DDL test that the promotion guard and every consumer still refuse blocked captures.
   - SQLite has no deferred triggers. Doing cross-row consistency at the commit boundary inside the transaction is the standard substitute.
2. **Remove the install-time `UPDATE claims SET status = 'quarantined' …`** (DDL 12, lines 48–50).
   - Astra confirmed it only takes effect if someone installs the DDL over a populated store by hand.
   - The normal open path refuses old stores (exact-schema gate), so it is unnecessary.
   - It is migration-like DML, and the project never runs migrations against real databases.
3. **Tests.** Run each through the Router **and** as raw DDL, with whole-store assertions.
   - An **already accepted** claim with a later **valid** check and receipt in one commit, including **multiple checked spans**: it stays `accepted_support`, or is promotable as the design intends.
   - Later **mismatches**.
   - Later **missing or invalid receipts**.
   - The provisional control.
   - Pair the reconciliation guard with a mutant **and** a valid accepted counterpart. The old late-check pairing only covered mismatches.
   - Keep all 22 repair mutants and the F1/F2 controls.

## Constraints
- **Coder:** GPT-6.1-Sol, branch gen2.
- **Size:** about 500 lines.
- **`service.py`** (1,422 lines): wiring only.
- **Before committing, run:**
  - targeted tests;
  - the full composition module;
  - `--only` on every mutant family that targets an edited file;
  - the six gates.
- **Environment:**
  - Don't refresh `.venv-gen2` while mutants are running.
  - Ordered DDL only. Never run a migration against a real database.
- **Reading:** you may read anything in the repository and the named private paths. Never search `/home/trevor` or `/home/trevor/work` outside them.
- **No** provider calls.
- **Don't edit** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-3b3-repair-2/`.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
