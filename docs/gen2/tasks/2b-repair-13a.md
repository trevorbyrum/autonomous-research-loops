# Task 2b-repair-13a — gateway: complete the decoder contract (family root fix, part 2)

**Sources (read in full first):**
- Astra re-review: `~/work/research-loops-public/private/reviews/gen2-2b-repair-12-astra-review-20261002.md` (R12-1..R12-5; family verdict MITIGATION/incomplete).
- Gate D #1: `~/work/research-loops-public/private/reviews/gen2-gate-d-1-astra-review.md` (findings 1 and 2, plus the "consolidation priorities" paragraph).
- Their evidence: `~/work/research-loops-public/private/evidence/astra-2b-repair-12/` and `.../gate-d-1/` (`probes.py`, `probes.json`).
- Charter: "Root-cause fixes, not patches", including the family-level rule.

**Keep:** repair-12's design (declared schemas, eager decoding, `Rec`, `MemberList`, schema-derived corruption). The oracle files stay unedited.

## Family cause, as both reviews name it
The decoder's contract with the rest of the gateway is **incomplete**. Repair-12 made validation eager, but:
- failures can still escape through ordinary exceptions;
- declarations can be partial (`any_()`) even for fields that drive decisions;
- the raw response is still reachable before decoding.

Each of R12-1, R12-2, R12-4, R12-5 and Gate D #1 is one of these three gaps. Fix the three gaps as **properties of the decoder**, not site by site.

## Required
1. **Total failure algebra (Gate D #1, R12-4).** Every conversion or normalization failure inside decoding must surface through the decoder's declared malformed-value channel, at the **narrowest member boundary**. Coverage: `year_value`'s `isdigit()`→`int()` with Unicode digits and conversion limits, and every other scalar normalizer. Don't blanket-catch programming errors such as `UndeclaredRead`. Readable siblings must survive as a partial lower bound. Test Unicode numerics and huge numbers beside readable peers through real adapters.
2. **Declaration completeness for decisions (R12-1).** Any field whose value affects identity, selection, a request argument, an end or a continuation must have a concrete declared type. This includes BEA `DatasetName`/`ParameterName`, BLS `survey_abbreviation`/`seriesID`, FRED `id`, and every other such field. Audit all 89 `any_()` uses by downstream role. Make the rule enforceable: an `any_()` value can only flow to passive metadata (`extra`/provenance) and can never be read by decision code. Enforce that in `Rec`, not by scanning.
3. **Sealed raw payload (R12-1 doi.org; R12-5).** Adapters must not be able to reach the raw response for payload decisions. The decoder is the only consumer; provenance receives a frozen copy. Route the doi.org lookup's whole response through the decoder before any shape decision or cache write. Make Astra's `getattr(resp, "json")` bypass impossible by construction, then keep the scan only as a bounded guard.
4. **Per-operation absence/null policy (R12-3).** Where an operation's accepted contract distinguishes a field that is *missing* from one that is *present but null*, the schema must say so. The generic `_absent` rule may not erase that distinction. Restore Semantic Scholar `data:null` (with `total:0`) to **unreadable/no-count** for all four cases. Cite the Semantic Scholar spec, not another provider's null policy.
5. **XML reference shape (R12-2).** Validate cardinality over **all** stated `Ref`s and `URN`s **before** any filtering. An empty or nameless `Ref` counts as a malformed reference, never as an absent one. Validate the fixed reference attributes (`package`, `class`) before binding a structure. Keep the accepted conservative refusal for a lone nameless Ref and for URN-only references.
6. **Harness reach (R12-5).** The schema-derived corruption walk must descend into `oneof`/union object and list branches, not just the branch the fixture selected. Verify the reached paths against an independent inventory of declared paths. Add DOAJ CSV and doi.org to the derived passes.
7. **Identity-only deduplication (Gate D #2; methodology and INVARIANTS E-3).** Authoritative deduplication merges only on explicit identity equivalence. Distinct non-empty DOIs or other identities never merge. A fuzzy title/year/author match may be recorded as a **linkage suggestion**, with provenance, for a later governed assessment; it never collapses candidates. Replace `test_cache_dedup.py`'s positive fuzzy-merge test with the correct contract. Keep the raw retrieval inventory.

## Done means
- `make gen2-check` and `make gen2-gateway` exit 0, unpiped.
- Astra's R12 probes and Gate D's `decoder`/`identity` probes are rebuilt as regressions and pass.
- The oracle is unedited and passing.
- An old-vs-new differential like repair-12's, with every remaining difference listed and justified.

## Constraints
- Branch gen2 only. Gateway only; the engine side is task 2b-repair-13b.
- No provider API calls; public documentation is allowed. No personal data.
- Never touch the live gen-1 gateway (worktree, database or service).
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-13a/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Completion report: the family cause and how each of the three gaps is closed **by construction**; each finding's root cause in one sentence; net lines; a literally-true Remaining section.
