# Task 0a-repair-3 — close RA2-R and RA3-R (small, final round expected)

Read: `docs/gen2/REVIEW-LOG.md` (2026-09-25 "Third Astra review" entry) and the full review at `~/work/research-loops-public/private/reviews/gen2-0a-repair-2-astra-review-20260925.md` §"Remaining repairs, prioritized" (items 1–2) — that section has the exact SQL reproductions, table/line locations, and required-repair text. This is a small, tightly-scoped task: two findings, both with a specific fix already described by the reviewer.

## RA3-R — dossier accepts an approval pointer that never passed the approval transition
Location: `gen2/store/schema.sql` dossier guard (~line 1024), approval-pointer update guard (~line 233), contract status transitions (~line 282).
Fix: permit first assignment of `approved_by_decision_id` only in the same statement as a valid `draft→approved` transition, so the retained pointer is itself evidence that transition happened. Preserve dossiers against legitimately approved-then-superseded revisions (audit the draft→superseded path together with pointer assignment — don't just allow both statuses blindly). Tests: pointer-only draft assignment + dossier insertion (must now fail), failed structural approval followed by dossier insertion (must fail), draft→superseded alternative (must work correctly), unchanged rows after each refusal, plus your existing valid-approved and historically-approved/superseded controls (must still pass). Update C-12's wording and the completion log to match the actual resulting guarantee.

## RA2-R — self-parent contract revision defeats the ancestor requirement
Location: `gen2/store/schema.sql` contract parent relation (~line 198), facet lineage predicate (~line 353), the obligation-rating trigger's equivalent.
Fix: enforce proper ancestry on the stored relation — reviewer's suggestion: `parent_revision IS NULL OR parent_revision < revision` (revisions are ordered numbers, so this closes both self-parentage and cycles in one constraint, without special-casing the two consuming triggers). If you use a different mechanism, it must give an equivalent acyclic/strict-ancestor guarantee. Tests: self-parent (`parent_revision = revision`) rejected, a cyclic/non-earlier parent rejected, valid direct-parent still works, multi-generation carry-forward still works. Extend both the facet and obligation rating tests — keep their already-working subject/value checks, add the ancestry check on top.

## Also apply (small, explicitly non-blocking but cheap — do these too)
- Document a supported SQLite version floor (reviewer tested 3.45.1 only; note STRICT tables need ≥3.37.0, JSON enabled by default since 3.38.0 — these are feature facts, not evidence lower versions were tested against the full schema. State the floor honestly.).
- Diagnostic assertions must not rely on SQLite's trigger-firing order (reviewer's note 3) — if any test currently expects one specific error message when multiple guards could fire, loosen it to accept any of the valid rejection reasons.
- Fix the stale BUILD-STATE test-count/RA-count shorthand if any remains (orchestrator has already corrected REVIEW-LOG; sweep BUILD-STATE.md too if you find anything stale referencing "RA1-RA8 all closed" without the RA2-R/RA3-R caveat).

## Explicitly NOT in scope for this task
Ruling 5 (whether `accepted_support` should require contract-admitted production generally) is an open operator decision, not yet made — do not implement either policy speculatively. Leave current (limited-consumer) behavior exactly as-is. The 0b-deferred items (writer/importer JCS canonicalization, fingerprint versioning, durable intake) stay deferred.

## Constraints (unchanged from prior repairs)
Branch gen2 only; no engine logic; don't touch gen-1/live topics/running services/main; small commits, `Co-Authored-By: Claude Opus <noreply@anthropic.com>`; never mask `make`'s exit status; every fix independently mutation-testable.

## Completion report
Per finding (RA2-R, RA3-R): what changed, what you tested, your mutation-kill confirmation reproducing the reviewer's exact SQL probes from the review. Flag anything unclear as a numbered question.
