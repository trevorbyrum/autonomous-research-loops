# Research before re-briefing: the Router behaviour-preservation differential (2026-10-06)

**Trigger:** the differential family recurred: DEBT-020 (2) in the 2q-b2 review, then the Gate C BLOCK in the 2q-b3 review (C1 lossy normalisation, C2 unstable replays becoming successes). The charter's "Research before re-briefing" rule applies.

## Findings
1. **Control nondeterminism at the source, don't scrub output.** Deterministic simulation testing runs the system under a harness-controlled clock, RNG and id source, so a run reproduces bit for bit and any difference between versions is a real change. Scrubbing output after the fact is the weaker approach. Sources: deterministic simulation testing ([navian-dst docs](https://docs.rs/navian-dst)); deterministic test generation for refactoring ([Diffblue](https://www.diffblue.com/resources/deterministic-test-generation/)); Temporal-style replay testing ([Bitovi](https://bitovi.com/blog/replay-testing-to-avoid-non-determinism-in-temporal-workflows)); deterministic replay surveys (ACM 10.1145/2790077).
2. **Separate generating candidate findings from verifying them.** A comparator that weakens itself when it sees disagreement certifies what it didn't check. This is the agentic corpus's "separate finding-generation from verification" principle (GraphRAG `agentic`, Branch 7).
3. **Repo evidence (Astra's 2q-b3 review):** for a pure-move refactor, an **AST-equivalence check** of each moved body, modulo the declared mechanical rewrite (`self._core.X` ↔ `self.X`), was an independent and strong oracle. Astra used it to clear the production change even though the differential was lossy.

## Implications (orchestrator's inference)
- Base the Router slices' behaviour evidence on two independent oracles:
  1. **Mechanical-move equivalence.** A small reusable tool checks that every moved method body is AST-identical to its original after only the declared rewrites, and lists every other change for review.
  2. **An exact deterministic replay.** Inject a fixed clock and deterministic id and randomness sources at the Router's seams in the replay harness (`_now`, `_new_id`, and any others found), snapshot arguments before each call and results when returned (deep copies), and compare **exactly**, with no output normalisation.
- If two baseline runs still disagree, the comparison **fails closed** as unresolved and names the remaining nondeterminism source, which then has to be determinised at its seam.
- Comparator self-tests: a changed answer, a removed store observation, a changed status answer, a reordered ordered list, a changed duration and a changed id namespace must each produce failure.
