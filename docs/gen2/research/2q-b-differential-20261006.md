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

## Addendum, 2026-10-07: the gateway drivers (Astra's 2q-b5 review, C1–C3)
The same family recurred in the gateway's whole-answer drivers, inherited from 13c through 2q-b1, 2q-b4 and 2q-b5:
- whole-URL masks;
- timestamp spelling substituted inside provider `raw` content;
- dict-to-pairs canonicalisation that erases the object/list distinction;
- downloads observed only by type;
- a comparator that accepts empty corpora (`{}` → "0 differences").

The findings above apply unchanged: determinise at the source, compare exactly with an unambiguous encoding, normalise only explicitly identified harness-owned values (here, only the loopback's allocated port), and fail closed.

One addition from the review: **completeness is part of the oracle.** Each driver declares a fixed input manifest (its case and group identities and counts). The comparator refuses empty, partial or unexplained missing coverage, and refuses incomplete or failed drivers, so a shared generator failure can't become equivalence. This mirrors the "expected inventory" practice in deterministic replay and the build's own completion-witness rule (2q-a-repair-4 F4).

**Implication:** one shared, reviewed differential core used by both services' drivers (exact encoding, manifest completeness, fail-closed verdicts, comparator self-tests), not per-slice harnesses. The earlier accepted slices that relied on the old drivers (2q-b1, 2q-b4) are re-run under it as confirmation.

## Addendum, 2026-10-07 (2): after the 2q-e1 review (C1, C2 remaining)
Two narrower lessons, both standard practice:
- **Parse, don't substitute.** Normalise a harness-owned value only at its *structural* location. Here that means parsing each URL (`urllib.parse.urlsplit`) and replacing only the netloc's port when the host is the harness loopback, using a token that can't occur in output (a typed marker in the encoded value, not marker text inside a string). Never substitute by spelling through whole strings.
- **The inventory comes first, and it comes from the inputs, not the outputs.** The expected case and group inventory is derived from a validated, completed input inventory: generator exit 0 plus a declared count and digest, with each driver declared explicitly by name. It is never inferred from whatever artifacts happen to exist, or from agreement among runs that read the same partial input. Freezing and comparison refuse an empty driver set, missing directories, empty manifests and malformed envelopes (digest format, required fields).
