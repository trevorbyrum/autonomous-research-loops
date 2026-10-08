# Research: verifying behaviour-preserving refactors without custom proof tools (2026-10-08)

**Trigger:** the operator asked, on 2026-10-08, for a better way than writing custom proof tools for each refactor. Four recent BLOCKs landed on home-built evidence tools rather than on the production change: the 2q-b3 Router differential, the 2q-b5 and 2q-e1 gateway drivers and core, and the 2q-b9 inline-back checker. This is not a new problem; established practice exists.

## What established practice uses
1. **Perform the refactor with an automated refactoring engine instead of editing by hand.** For Python, `rope` (the engine behind Python language servers) and Meta's `LibCST` codemods. Engines are correct by construction for their supported refactorings, though not perfect: automated testing of the Eclipse, NetBeans and JastAdd engines found 63 behaviour-changing bugs across 153,444 transformations (Soares, Gheyi, Massoni, IEEE TSE). So keep a behaviour check as well, but stop hand-proving the mechanics.
2. **Detect and describe what changed with an off-the-shelf refactoring detector.**
   - RefactoringMiner 3.x supports Python (as well as Java, Kotlin, TypeScript and JavaScript), and produces refactoring lists and AST diffs at commit and PR level. Its published Java precision is 99.6% at 94% recall; its Python accuracy isn't verified here.
   - `PyRef` (SCAM 2021) is a Python-specific research tool.
   - Refactoring-aware review is shown to help reviewers separate behaviour-preserving changes from logic changes (the Xerox industrial case study; ReviewFactor).
   - This replaces our custom move-equivalence and inline-back checkers.
3. **Behaviour checks from standard testing tools,** not bespoke drivers:
   - **Characterisation, golden-master or approval tests** (Feathers, *Working Effectively with Legacy Code*; the `approvaltests` and `syrupy` libraries): capture current outputs once, review them, and the refactor must reproduce them exactly.
   - **Property-based differential testing** with Hypothesis: assert `new(x) == old(x)` over generated inputs. This is a documented Hypothesis pattern for refactors and optimisations.
   - **`crosshair diffbehavior`:** SMT-backed search for inputs where two function versions differ. It's useful on small pure functions; by its own documentation it is work in progress, needs deterministic code, and finding no difference doesn't prove equivalence.
   - **Determinism from standard libraries:** `time-machine` or `freezegun` for clocks, and seeded random, uuid and secrets fixtures. `hermetic` combines these, but it's new and its maturity is unknown. These replace hand-built clock and id seams.
   - The **existing test suite plus mutation testing** is the main safety net, and gen2 already has a strong one (about 2,300 tests, every mutant killed).
4. **An LLM as a triage oracle, not a proof.** On 226 real refactoring-engine bugs, a frontier model judged refactoring correctness with 93.8% accuracy zero-shot; the authors position it as a complement that flags suspicious transformations (arXiv 2605.02096). That matches Astra's role.

## Implication for gen2 (orchestrator's inference)
- **Remaining 2q-b refactors** (the `EvidenceWriter` move, `_commit_in_transaction`) and later structural work:
  - perform each refactor with `rope` or LibCST;
  - describe it with RefactoringMiner (Python) instead of custom checkers;
  - check behaviour with the existing tests plus the mutation harness, approval or snapshot tests on the outputs that matter, and Hypothesis `old == new` properties for pure functions (decoders, parsers, URL handling);
  - get determinism from `time-machine` and seeded fixtures;
  - Astra reviews.
- **Keep the tools already built and accepted** (the 2q-b3b exact replay; the 2q-e2 core if accepted), but stop hardening them round after round.
- **Needs operator approval:** dev-only dependencies (`rope`, `hypothesis`, `time-machine`, perhaps `approvaltests`) in the hash-locked environment, and a JVM for RefactoringMiner, or else PyRef or nothing. The metrics tool stays stdlib-only. **Untried on this codebase:** run a one-slice trial before adopting.
