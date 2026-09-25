# Task 0b-repair-2 — close A5-R1/A5-R2 (small, likely final 0b round)

Read: `docs/gen2/REVIEW-LOG.md` (2026-09-25 "Re-review of 0b-repair" entry) and `~/work/research-loops-public/private/reviews/gen2-0b-repair-astra-review-20260925.md` §"Finding 0B-A5-R1"/"0B-A5-R2" for exact reproductions and required corrections. A1–A4 are fully resolved and independently re-verified with extra fault injection beyond the original findings — do not touch that code.

## A5-R1 — invalid Unicode crashes the report path
Reproduction (review's exact case): a JSON queue file containing an escaped lone surrogate (`\ud800`) anywhere that ends up in report metadata — not just `mapping` values, which the first repair already guards, but `ref` fields, issue text, topic identifiers, and `sources` dict keys. Canonicalizing the final report raises uncaught, and the CLI emits zero bytes.
Fix: make invalid Unicode a reportable input defect across the *entire* report boundary (keys, references, identifiers, diagnostics — everywhere a gen-1-sourced string can end up), not just the one path already guarded. Either reject at an appropriate input boundary with a safely-escaped diagnostic, or retain the affected record with a safe provenance locator and an explicit issue — do not silently substitute a fake-valid identity, and do not disable canonical validation to make the crash go away. Add end-to-end CLI/render regressions for an invalid ID, an invalid status string, and an invalid unknown-key — with valid neighboring records still producing a usable report.

## A5-R2 — oversized numeric token crashes the report path
Reproduction: a numeric token with ~4,300+ digits (exceeds Python's own integer-conversion limit) in a queue item field, or in the middle of a `state/events.jsonl` file between otherwise-valid lines. `json.loads` raises `ValueError: Exceeds the limit...`, which the current exception handling (`UnicodeDecodeError`, `JSONDecodeError`, `RecursionError`) doesn't catch — escapes all the way to `main`, zero report bytes.
Fix: catch this failure and route it into the same input-error/reporting path as other malformed input. For JSONL: count/report the specific bad line, preserve readable neighboring lines (the review confirms a neighboring valid line with the same-length token still produces a clean `identity-out-of-range` report — so the handling pattern already exists for the *value*, just not for the *parse failure*). For a whole queue file: a clear `queue-unparseable` blocking report is acceptable; retaining the raw token text for per-record reporting is also acceptable. Do NOT raise or disable Python's process-wide integer conversion limit to make this go away — that's hiding the problem, not handling it.

## Small wording/routing items (do alongside, cheap)
- `gen2/importer/dry_run.py`'s `_gen1_float` docstring/comment says "before any float conversion" — literally inaccurate (it computes the float first, then compares round-trip representation). Correct to "before accepting or using a lossy conversion."
- Record the files-never-examined gap (Astra's ruling on question 3: the report should eventually list unexamined-but-present files with a reason — no-follow metadata traversal, no parsing required) as an explicit follow-up item in the store README or ENVIRONMENT.md, scheduled before any report is used as Phase 4 migration-planning evidence. Not required to implement this round — just record it so it isn't lost.
- If you have time: a `boundaries.toml`-adjacent clarifying comment (not a normative change — that still requires separate routing) describing the actual read model (descriptor-relative, no-follow, refuses links) more precisely than bare "read-only." Optional, non-blocking.

## Explicitly NOT in scope
Everything already resolved (A1–A4) — don't touch. The two Trevor-only factual questions (internal gen-1 symlinks, queues missing `version`) — still unanswered, still not yours to guess at. `accepted_support` policy, live-state access, C-13's normative amendment — all still pending, untouched.

## Constraints (unchanged)
Branch gen2 only; no engine logic beyond these fixes; never touch gen-1/live state (synthetic fixtures only, matching the review's own reproductions); never touch running services/main; small commits, `Co-Authored-By: Claude Opus <noreply@anthropic.com>`; never mask `make`'s exit status; every fix independently mutation-testable.

## Completion report
Per finding (A5-R1, A5-R2): what changed, what you tested, mutation-kill confirmation reproducing the review's exact scenarios (the lone-surrogate JSON snippet, the 4,300-digit token in both a queue file and mid-JSONL).
