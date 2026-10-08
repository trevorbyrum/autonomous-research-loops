# Task 2q-t4b: finish and qualify the replay seams for real processes (closes DEBT-023 item 1)

**Source:** 2q-t4 (`docs/gen2/tasks/2q-t4.md`) stopped after its first commit `5ef2130`, when the orchestrator session ended. That commit holds the replay seams for job identity, the child's clock and ids, and the first poll. Since then:
- the replay reports **6 unresolved** where there were 352 (2q-b10 and 2q-b11 runs);
- Astra's 2q-b10 review **validated the count but didn't accept the seam.** Its requirements (`~/work/research-loops-public/private/reviews/gen2-2q-b10-astra-review-20261008.md`, the paragraph beginning "This review does not accept 2q-t4") are this task's acceptance criteria:
  - parent and child identity **consistency and distinctness**: two children must never draw colliding ids, and the trial (2q-r1, Trial C) warned that every armed child draws the same ids;
  - **opt-out** behaviour, with production and non-replay test runs unaffected;
  - **child activation;**
  - the **poll schedule's effect** on lifecycle cases;
  - the **repeated comparison on `c02fa74` → `8bc87cc`**;
  - **end-to-end negative controls** showing that identity, fencing and result-binding faults stay visible;
  - **all five real-identity integration assertions kept** as they are.
- Use established libraries where they cover the need (`time-machine` for the in-process clock). The trial showed they don't cross process boundaries, so a reviewed seam is legitimate there. Keep it minimal.

**Also:** give an explicit disposition for each of the 6 remaining unresolved scenarios: fix them, or leave them unresolved with a named source.

**Review-throughput rules apply:** target ≤ ~500 hand-written lines; targeted runs only; the orchestrator runs the full targets at landing.

## Constraints
- Branch gen2. Production changes only if unavoidable and minimal (an injectable default with AST evidence that the default path is unchanged); prefer harness-only.
- No provider calls. Never touch the live gen-1 gateway or 127.0.0.1:8765. Don't search `/home/trevor/work` recursively.
- Don't edit BUILD-STATE.md, REVIEW-LOG.md or DEBT-REGISTER.md.
- Evidence goes to `~/work/research-loops-public/private/evidence/2q-t4b/`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Use `git commit <paths>`.
