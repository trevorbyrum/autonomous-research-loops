# Gen-2 Review Log

## 2026-09-25 — Task 0a Gate review (Astra, xhigh) — BLOCK
Full report: `~/work/research-loops-public/private/reviews/gen2-0a-astra-review-20260925.md` (pinned SHA-256 manifest included).

**Verdict:** BLOCK / BLOCK pending doc correction / BLOCK — Gates A, B, C respectively. Route a bounded 0a-repair task; do not build 0b on this DDL until repaired and re-reviewed.

**Gate A (11 findings, A1–A11):** critical — REPLACE bypasses receipt/watermark immutability (A1); high — decision-authorization doesn't check disposition/subject/topic/hash match (A2), facet importance has no schema representation (A3), pre-contract discovery is FK-blocked (A4), lifecycle pins/reconciliation incomplete (A5), verification support can contradict its evidence + over-restricts legitimate canonical-byte reuse (A6), decision receipt/spec consistency gaps (A7), boundary checker has direct-capability bypasses (A8); medium — capability supersession transaction undocumented (A9), denormalized identity/evidence needs explicit binding (A10), status vocabulary excludes valid degraded states (A11).

**Gate B (research-context, B1–B8):** B1/B2/B8 CONFORM (adjudication fixes verified in place). B3–B7 DEVIATION in the *methodology synthesis itself* — routed to operator amendment path (see below, applied 2026-09-25 same session per straightforward-correction precedent from the Sep 25 adjudication round).

**Gate C (86 tests):** 78 ACCEPT, 8 REJECT/MODIFY (D06, D07, D10, D13, D24, D26, D28, D36, D45, D46, D48, D49, D50, D54, D55 — see review for exact rewrite specs per test). Independent mutation testing found 3 additional survivors beyond the coder's claimed set: byte-mismatch quarantine CHECK removal, terminal-state reopening beyond one case, sink-membership-as-any-physical-sink.

**Rulings applied:** R1 — RFC 8785 JCS for logical JSON hashing (raw provider bytes hashed separately, never canonicalized-then-called-raw). R2 — 6 store README choices: verification-alongside-research leases ACCEPT with generation/scope matching; blanket "verifier's parent ≠ producer" REJECTED as a rule (replaced with a control/reservation-parentage distinction); byte-mismatch quarantine ACCEPT; process-identity-only-while-running MODIFY (write-once once observed); draft vocabularies MODIFY (explicit transition semantics required); hash canonical form → R1. R3 — deferred-item phasing: intake briefs → 0b/1/2; surveillance liveness → spec in 0, visible by Phase 2; question registry → freeze format in 0, load in 1, live content in 3; qualification registry → spec in 0, fake-exercise in 1, real in 3.

**Doc corrections applied same session (operator-visible, not silently amended):**
- Methodology §2/§4: removed "verifies... mechanically" / "guarantee" wording on tier-0 NLI; distinguished exact-byte match, selected-context adequacy, and semantic support as three separate properties (B3).
- Methodology §2/§3: "calibrated 1–9 analog" → "proposed elicitation aid, not calibrated" (consistent with the doc's own line 45 and INVARIANTS G-2); "tests supply method-selection ground truth" → rubric admitting multiple defensible designs, consistent with §9 (B4).
- Methodology: VoI-lite "resource-rational by construction" → reworded as an inspired, proposed, uncalibrated heuristic (B5).
- Flow doc / methodology verification rule: clarified producer-*acquired* canonical bytes (authenticated, unmodified) are legitimate reuse; the prohibition is on the producer's *selected/unvalidated extraction*, not on canonical bytes per se (B6 — also an A6/A10 code-level fix required in the repair task).
- Removed stale "reviewers' verdicts were false" phrasing (adjudication upheld route-specific inability-to-verify, rejected only absence/inflation inferences) and the leftover "independent Noul family selection" instruction superseded by the coherent-template amendment (B7).
- Task-brief wording "0%-vs-50% rule" flagged as causal/rate-shorthand INVARIANTS already correctly rejects — noted for future briefs, not a doc amendment.

**Escalated to operator (Trevor):** none required immediate operator decision beyond the above — all five B3–B7 corrections are removals of overclaim/contradiction consistent with already-adjudicated positions, not new design choices. Reported in full alongside this log entry per charter.
