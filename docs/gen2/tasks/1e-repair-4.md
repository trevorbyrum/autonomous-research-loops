# Task 1e-repair-4: one masking predicate, applied consistently (single finding; final 1e round)

Read: `~/work/research-loops-public/private/reviews/gen2-1e-repair-3-astra-review-20260928.md`, finding 1 — the only open item in all of 1e. Evidence: `/tmp/gen2-1e-repair-3-astra-20260928T2006/`. Everything else is closed, including all the original masking and ID cases, which must stay passing.

## The defect
The pre-dispatch ID check and the MCP serialization step scan space-separated pieces; `_answer()` then runs recursive `redact()` scanning each *complete* string, whose 256-state decoding cutoff can report a match even though every piece passed. Result, reproduced by Astra on an unmodified engine with harmless synthetic values:
- an accepted 114-char ID executes, then comes back as `id: "[credential]"` — the accepted correlation ID changed after execution;
- an already-checked nested MCP tool document is replaced whole, so the reply reports success while its tool text is no longer valid JSON.

## Required repair (per the review)
- Acceptance and every later masking pass must agree: an ID is either echoed unchanged or refused with a null ID before dispatch — never altered after execution.
- The nested document survives later passes: mask its structured values, or return an explicit error when a valid response can't be written — never report success with an unparseable tool document.
- Keep pre-nesting masking and the final written-text check.
- Astra verified a narrow repair in a disposable tree: make the later string predicate scan the same literal-space pieces (see the experiment file in the evidence directory). Prefer that unless you find a reason it's wrong — and if you do, say so.

## Tests
Astra's two reproductions as regressions (the 272-state ID; the two seeded capability-fact strings breaking the status tool document), the reduced-depth controls beside them, a mutant restoring the whole-string scan in the later pass, and updated bindings where killer lists shift. All 17 of Astra's focused tests, and both existing masking test classes, must pass.

## Constraints
Branch gen2 only. Never touch `gateway/`, gen-1, running services or main. Commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with the completion report as your final message (what changed, both reproductions now handled, mutant evidence, final unpiped `make gen2-check` result). Don't end your turn waiting on a background run.
