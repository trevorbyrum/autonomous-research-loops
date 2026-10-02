# Task 2b-repair-14 — gateway: the finite 2b finish line (Gate D #2 checklist, items 0–6 and 8)

**Source:** Gate D #2, `~/work/research-loops-public/private/reviews/gen2-gate-d-2-astra-review.md`, with evidence in `private/evidence/gate-d-2/`. Also Astra's 13c review, `gen2-2b-repair-13c-astra-review-20261002.md`, with evidence in `private/evidence/astra-2b-repair-13c/`, including `per-test-audit.md`. Read both in full.

**Runs after 2b-repair-13d** (engine; checklist item 7). Gateway only. The oracle stays unedited. Keep every accepted behaviour:
- the R12 and Gate D #1 fixes;
- identity-only merging;
- the strict lexical openers;
- the sealed downloads;
- materialization at the router, index and cache.

## Operator rulings (2026-10-02). These settle the questions below; don't reopen them.
1. **Trust model B is adopted.** The gateway guarantees a complete contract for *supported provider input*. First-party adapters are trusted, reviewed code. Their discipline is enforced by declared-read inventories, import and parser guards, mutation tests with positive controls, and review, as a documented design boundary. It is **not** by-construction confinement against deliberate misuse. Python identity checks, reachable private fields, importable privileged helpers and finite testing are documented boundaries under B, not debt.
2. **The supported-format and resource policy is frozen as follows:**
   - UTF-8 only;
   - JSON: no duplicate names, no NaN or Infinity; finite floats, with exact integers accepted;
   - JSON and XML nesting depth ≤ 64;
   - no XML DOCTYPE;
   - CSV extensions: LF-only lines, no final newline, blank lines, short rows and extra cells are accepted; a bare CR is refused *outside quoted fields*;
   - CSV cells ≤ 131,072 characters;
   - transport body ≤ 256 MiB.

   Inputs outside the policy fail visibly (the lane is unavailable), never silently. **Two sanctioned information-bearing predicates:**
   - `Rec.empty`, used only at the reviewed provider-shape predicates;
   - equality between decoded provider objects, only for the intended comparisons (for example Unpaywall's best-location check) and never for adapter-minted values.

## Required (Gate D #2 checklist)
- **0. Amend to B, consistently.** Update INVARIANTS (B-1 and the relevant gateway entries), `gateway/docs/STATION-CONTRACT.md`, the docstrings and the completion claims to state the B guarantee exactly, citing the operator ruling of 2026-10-02. Remove every absolute Python secrecy or confinement promise. Don't just append "known limitation".
- **1. Transport framing completion (F1 / R13C-1).** Before a response can count as successful, the shared transport establishes that the message is complete under HTTP: declared Content-Length met, chunked framing terminated, the 256 MiB bound kept. Handle invalid or conflicting framing deliberately. Use established HTTP semantics (RFC 9112 §6, §8), not a second ad hoc protocol parser. Test on loopback:
  - complete;
  - truncated after the header;
  - truncated mid-record;
  - truncated at a record boundary;
  - chunked complete and chunked truncated;
  - over the size bound;
  - with positive controls.

  Disclose the close-delimited ambiguity accurately.
- **2. XML interpretation (F2 / R13C-3).** A scalar field has lossless meaning: reject child-bearing scalar elements unless the declared field explicitly supports them. Cover child text, tails and nesting. Validate expanded names (namespace URI plus local name) for SDMX:
  - a foreign URI fails;
  - an equivalent prefix bound to an approved URI passes;
  - legitimate SDMX versions pass;
  - intentionally supported unqualified forms are kept, explicitly.

  No XSD engine.
- **3. Constructor compositions (F4 / R13C-2).**
  - A literal passed as `raw` must not gain decoded-provenance comparison authority. Replace the generic `_issued` issuance with the narrowly specified comparison operation from ruling 2.
  - Typed canonical fields accept only their typed domain and can never unwrap a `Rec` into original provenance.
  - Canonical typed construction must not materialize raw data. Keep **one** explicit raw-materialization operation, used only at the reviewed sinks.
  - The original R13A-2 mutant and both R13C-2 mutants fail safely. Valid adapters, raw-storage fidelity, downloads and the sanctioned comparison still pass.
- **4. Snapshot per-line isolation (F5 / R13C-4).** Restore repair-8's accepted per-line isolation. A malformed or ambiguous line is refused and reported (count it and record which lines), and its readable neighbours are kept. A file that can't be read, decompressed or framed fails the load. Test valid–bad–valid with malformed JSON, a duplicate name and a wrong-shaped record. Revert the two tests that endorsed whole-file abort.
- **5. Freeze the format policy** from ruling 2 in STATION-CONTRACT, as the supported contract with its compatibility limits stated. Don't claim every provider uses this subset; Phase 4 qualifies the live providers.
- **6. One owned inventory, and accurate claims.**
  - Consolidate the overlapping opener, read and materializer inventories into one owned inventory with reviewed classifications. Close the known gap: a parser-object spelling such as `json.JSONDecoder().decode(...)`. Don't claim it analyses arbitrary Python.
  - Resolve all 9 overclaims and the 2 snapshot-test failures in the 13c `per-test-audit.md`.
  - **Retry-After:** document the date parser's actual tolerance; don't add another parser just to rescue the wording.
  - **Number claim:** state finite floats versus exact integers accurately.
  - Recount line sizes with one consistent scope.
- **8. Gateway part of the final validation.**
  - Run `make gen2-check` and `make gen2-gateway` unpiped and keep their exit status, skips, and mutation and control results.
  - Rebuild every open reproduction from 13c and Gate D #2; each fails on `37a655c` and passes now.
  - Write a **family-level structural account under B:** which boundary owns each of transport completion, lexical validity, supported interpretation, adapter discipline and storage exits, and how every supported path is shown to pass through them.

## Not required (Gate D #2, explicit)
- another sealing layer;
- proof over arbitrary future adapter programs;
- validating unused provider fields;
- universal XML support;
- live canaries.

The package cycle, the router-collaboration metrics and the decomposition of schema/base stay with **2q**.

## Constraints
- Branch gen2, gateway only.
- No provider API calls (public documentation is fine). No personal data.
- Never touch the live gen-1 gateway.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-14/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- **Completion report:**
  - each checklist item with its evidence;
  - each root cause in one sentence;
  - net lines;
  - the family account;
  - a literally-true Remaining section.

  Any concrete defect you leave unfixed is a MITIGATION and needs the operator's acceptance.
