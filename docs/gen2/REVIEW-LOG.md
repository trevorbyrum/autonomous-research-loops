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

**Escalated to operator (the user):** none required immediate operator decision beyond the above — all five B3–B7 corrections are removals of overclaim/contradiction consistent with already-adjudicated positions, not new design choices. Reported in full alongside this log entry per charter.

**Correction to this entry (2026-09-25, from the 0a-repair re-review below):** the "78 ACCEPT / 8 REJECT" test-accounting figure above was wrong — the original review's actual split was **70 ACCEPT / 16 REJECT**. Sourced from Astra's own re-count against the original report; propagated here in error by the orchestrator. Also: this entry's B3–B7 "applied" claim was incomplete — two of the six corrections (B3's small-window/context-adequacy inference, B4's method-selection ground-truth wording) had NOT actually landed in the doc text as of this entry's writing, despite being described as fixed. Both are now corrected (see 2026-09-25 0a-repair re-review entry below) — this class of error (describing a fix as applied without re-verifying the actual file text) is itself worth carrying forward as a process lesson: always grep the target line after editing, not just after drafting the edit.

## 2026-09-25 — Task 0a-repair review (Astra, xhigh) — BLOCK, narrower
Full report: `~/work/research-loops-public/private/reviews/gen2-0a-repair-astra-review-20260925.md` (pinned SHA-256 manifest included). Orchestrator independently confirmed `make gen2-check` green (345/345 mutants, 177 tests) before dispatching this re-review.

**Verdict:** BLOCK / BLOCK pending narrow doc correction / BLOCK — Gates A, B, C. Narrower than the original: 3 of 11 original findings (A1, A9, A11) fully RESOLVED and independently re-confirmed via the reviewer's own original probes; 7 of 11 (A2–A8, A10) PARTIALLY RESOLVED with 8 new findings (RA1–RA8).

**RA1–RA8 (all reproduced by direct probe, not inferred):** RA1 (high) — a rejected other-topic decision can still overwrite the authorizing-decision pointer on an already-completed or already-retired topic without changing status/revision. RA2 (high) — a rating decision about one draft (even one with zero facets/obligations) can authorize invented or changed ratings on a later, unrelated revision; only `subject_revision < contract_revision` is checked, not what was actually rated. RA3 (high, boundary-drift) — pre-contract work can record scientific exclusion decisions against an unapproved draft contract; the FK fix didn't also require approved-protocol admission for scientific writes. RA4 (high) — an `outcome_unknown` episode's reconciliation timestamp can be rewound and replayed to exit to running without new reconciliation evidence — episode identity isn't protected. RA5 (high, boundary-drift) — a verification receipt marked `use=sampled` with all four substantive checks `not_checked` can still promote a load-bearing claim to `accepted_support`; the gate trusts the declared use, not the claim's actual required checks. RA6 (high) — three separate probes showed schema-valid JSON can disagree with its own normalized SQL row (operation-receipt identity, decision-spec ID vs. hash-selected spec, obligation protocol fields) — no comparison catches this class. RA7 (high) — the boundary checker misses ordinary static Python bypasses: function type-annotation capabilities (`def f(x: eval('1')): pass`), nonlocal import rebinding, and direct `posix` module access. RA8 (medium, required before persistent identities) — integer identity/revision bounds are bypassable by notation (`9007199254740992.0` and `...e0` both parse where the bare integer is correctly rejected).

**Gate B:** 4 of 8 original checks RESOLVED clean (B1, B2, B5, B6, B8); B3 and B4 PARTIALLY RESOLVED (two sentences survived edits that were described as applied — now actually fixed, see correction note above); B7 SUBSTANTIALLY RESOLVED (one non-blocking historical task-brief phrase remains, explicitly flagged as never-reuse rather than corrected).

**Gate C:** 70 ACCEPT / 16 REJECT was the *original* review's actual split (REVIEW-LOG's prior "78/8" entry was wrong — corrected above). Of the 16 requested rewrites: 12 fully ACCEPT, 4 (D07, D54, D55, B20) MODIFY — same invariant direction, missing a specific attack case each (episode-reuse regression for D07; RA1's post-terminal decision-pointer substitution for D54/D55; the type-annotation/nonlocal/posix bypasses for B20). All 91 newly added tests individually reviewed; most ACCEPT, several MODIFY for the same reason (composition coverage: individually-valid rows assumed to imply a stronger relationship that isn't actually checked — this is the same shape of gap as RA1/RA2/RA6). 8 additional Python mutants found surviving beyond the coder's own inventory (float underflow-to-zero, raw-byte whitespace stripping, ASCII-vs-UTF8 decoding, decimal-point-with-no-fraction, pre-1970 date rejection, and three distinct scope-resolution gaps in the boundary checker — class scope, walrus/comprehension binding, `global` resolution).

**Environment/process rulings:** REJECT `pip install --user --break-system-packages` as a repeatable build practice — modifies a shared interpreter's user-visible package environment outside project isolation; the hash-pinned `rfc8785==0.1.4` dependency itself is accepted, but Phase 1 requires a documented venv/isolated build image before this recurs. CONFIRMED (via git reflog) both self-reported masked-failure incidents were genuinely amended/fixed in the retained history — no bad commit landed on the reviewed branch tip. No evidence of a force-push found, though a local reflog can't prove remote history (moot — nothing has been pushed).

**R1–R3 and the coder's 6 proposals — rulings:** R1 substantially implemented (RA8 remains). R3 phase assignments ACCEPTED as encoded. Proposal 1 (research_pass in pre-contract admission) ACCEPTED conditional on RA3's fix making the "no scientific writes" restriction actually true. Proposal 2 (retirement is terminal, no revival without new topic or explicit amendment) — confirmed implemented as described; **explicitly left as the operator's decision, not inferred by the review, whether a revival route should exist**. Proposal 3 (every status change advances revision) ruled sound-but-insufficient-alone. Proposal 4 (earlier-draft rating hash) — accepted the anti-self-hash-cycle need, REJECTED arbitrary-earlier-draft binding (this is RA2). Proposal 5 (retries need new lease) ACCEPTED. Proposal 6 (remaining items deferred to 0b/1/2/3) confirmed correctly scoped.

**Escalated to operator (the user):** (1) the dependency-installation ruling above is a clear engineering call already made by Astra (venv/isolated build before Phase 1) — not asking you to decide the technical approach, just noting it as a Phase 0→1 transition requirement. (2) Proposal 2's revival policy remains explicitly your call per the review's own text — current behavior (no revival, new topic or amendment only) stands unless you say otherwise.

## 2026-09-25 — Task 0a-repair-2 landed (11 commits), routed for third Astra review
**Correction (added after the third review below): "closed all 8" was premature.** Coder's fixes for RA1, RA4, RA5, RA6, RA7, RA8 held up fully under Astra's third-round independent re-probing; RA2 and RA3 turned out only partially resolved (see RA2-R/RA3-R, third review entry below) — the underlying mechanisms were right but each had one more composition the coder's own tests didn't reach. Coder closed all 8 RA findings *as originally described*, plus every named test extension, the 8 independently-found Python mutant survivors, and the environment fix (hash-locked project venv, `make gen2-venv`, `docs/gen2/ENVIRONMENT.md` — replaces the rejected host-level `pip --break-system-packages` practice). Orchestrator independently re-ran `make gen2-check`: confirmed green, all 11 commits present. Mutation count grew from 345→427 (all killed), tests 177→194.

**The coder's own framing of the fix (largely right, per Astra's third review — but "applied uniformly" overstated it; see below):** every RA finding was a case of a record claiming something about a *different* record without that claim being checked against the other record's own stored state. promotion checks read the claim's own designation (RA5, RESOLVED); scientific rows require the producing work's actual approved-protocol pin, not just a contract FK (RA3, later found partial — the dossier guard didn't check that the pin was itself produced by an approval transition); ratings are checked against an ancestor-chain payload of what was actually rated (RA2, later found partial — the ancestor check didn't reject a contract naming itself as its own parent); duplicated JSON/column pairs are now bound field-by-field (RA6, RESOLVED); `outcome_unknown` episodes get their own persistent identity instead of a mutable timestamp key (RA4, RESOLVED); the terminal decision pointer can only move in the same statement as its status transition (RA1, RESOLVED).

**Coder flagged 7 items needing a ruling before/alongside the next review** (its own numbering): (1) RA7 test placement (fixture graph vs. real-graph test) — minor, self-resolving; (2) RA5 test placement — minor; (3) RA2's subject-comparison assumes canonical JCS storage and is verified only on SQLite 3.45.1 — needs Astra's read; (4) RA3's claim-source-link interpretation adds framing/eligibility-version pins slightly beyond the review's literal text — needs Astra's read; (5) **open design question**: should promotion to `accepted_support` also require contract-admitted production generally, not just the specific C-12-listed consumers? Left unchanged pending a ruling; (6) RA8's bound is enforced at schema/helper layer, not by a DDL CHECK — same trust model as timestamps, but worth Astra confirming that's consistent; (7) **operator item**: the earlier coder's stray `rfc8785` install in `~/.local` (from before the venv fix) is still present on the host — cleanup is the user's call, not touched by this task.

Routed to Astra for third Gate A+B+C review: task file `research-loops-public/private/reviews/gen2-0a-repair-2-review-task-20260925.md`.

## 2026-09-25 — Task 0a-repair-3 landed (6 commits), routed for fourth (possibly final) Astra review
Coder closed both RA2-R and RA3-R: `contract_parent_is_earlier` is a single named CHECK constraint (`parent_revision IS NULL OR parent_revision < revision`) that closes self-parentage, cycles, and later-parent cases in one rule — neither rating trigger needed a special case, confirming the coder's generalization claim actually holds here. `contract_approval_pointer_set_by_approval` is a new trigger requiring the approving-decision pointer to be set in the same statement as a genuine draft→approved transition, which also correctly closed the draft→superseded loophole the review's own probe exploited. Both fixes independently re-derive the reviewer's exact read-back on the pre-fix schema, then show it refused at HEAD. Coder also: reran the full suite with all 119 triggers created in reverse order (no accept/refuse outcome changed — confirms the earlier trigger-order concern wasn't masking anything), documented the SQLite floor honestly (3.45.1 tested; 3.37/3.38 cited as release facts only, not tested support), and self-corrected BUILD-STATE's stale 78/86 figure (redundant with the orchestrator's own fix, harmless).

Coder deferred 4 items rather than deciding unilaterally: (1) whether to remove the now-unreachable `draft→superseded` transition from `contract_status_forward_only`'s enum; (2) correctly left REVIEW-LOG.md alone as the orchestrator's file — the "closed all 8"/"applied uniformly" overclaim above is now fixed; (3) a proposal (not implemented, out of brief) to make the reversed-trigger-order test a permanent CI check; (4) whether the SQLite version floor should get a runtime refusal now or wait for 0b's store module. All four routed to Astra's fourth review rather than decided by the orchestrator.

Independently re-ran `make gen2-check` in background; not confirmed complete before dispatching the fourth review (Astra's own independent run supersedes this regardless). Routed: task file `research-loops-public/private/reviews/gen2-0a-repair-3-review-task-20260925.md`. This review was explicitly asked to say plainly if 0a is ready to accept, rather than searching for a new residual to keep the cycle going.

## 2026-09-25 — Fourth Astra review (0a-repair-3) — **PASS WITH FOLLOW-UPS. 0a ACCEPTED.**
Full report: `~/work/research-loops-public/private/reviews/gen2-0a-repair-3-astra-review-20260925.md`. **Gates A/B/C: PASS/PASS/PASS.** Astra reconstructed both RA2-R and RA3-R attacks fresh (not re-running the coder's tests) — full example contract, recomputed content hash, actual JCS serialization — against both the pre-fix commit and HEAD, confirmed each attack succeeds on the old schema and fails on the new one, with unchanged database state on every rejection. Also independently: 5 fresh SQL mutations (all killed, zero test errors), reversed all 119 trigger creation orders (all 135 store tests still pass), and confirmed the coder's "shared fix" claim by diffing the two rating triggers byte-for-byte between commits — unchanged, confirming the ancestry fix required no per-consumer special-casing.

**4 rulings, all decided:**
1. Remove the now-dead `draft→superseded` transition edge from `contract_status_forward_only`'s `OLD.status='draft'` arm — nonblocking cleanup, not a condition of acceptance.
2. Coder was correct to leave REVIEW-LOG.md alone; charter explicitly assigns it to the orchestrator. Confirmed the orchestrator's own corrections (the "closed all 8" / "applied uniformly" overclaim fix, above) are sufficient — no further edit needed.
3. Add the reversed-trigger-order run as a permanent CI check — worth doing now while context is fresh, can land alongside 0b's first work.
4. **SQLite version-floor enforcement is a hard 0b requirement, not deferrable**: "There is no permission to postpone compatibility enforcement until after durable stores exist." Must be checked numerically (not just version string) plus JSON-capability verified (SQLite can be built without JSON support even post-3.38.0) plus the connection pragmas applied/read-back, in 0b's *common store initialization path* — before any durable store is created or admitted, covering both runtime and importer use paths.

**Carried forward into 0b, explicit, not silently decided:** writer/importer must actually perform JCS canonicalization on write (schema validation alone doesn't enforce it — flagged back in round 3); identity/revision bounds must be applied by every writer, not just the schema; fingerprint-version recording on receipts; durable intake brief rows/import mapping. **The `accepted_support` general-admission question (ruling 5 from round 3) remains explicitly unresolved and is the user's call** — current limited-consumer behavior stands, this review does not choose a policy for him.

**Historical-accuracy note Astra flagged approvingly:** the orchestrator's mid-cycle correction (that round 3 found RA2/RA3 only *partially* resolved, not fully) should stand as the accurate record — "preserve the corrected third-round history rather than retroactively describing that earlier review as accepting."

## 2026-09-25 — Third Astra review (0a-repair-2) — BLOCK, substantially narrower
Full report: `~/work/research-loops-public/private/reviews/gen2-0a-repair-2-astra-review-20260925.md`. **Gate B: PASS.** Gate A/C: BLOCK, down to 2 findings from 8, both medium severity.

**All 8 RA findings re-verified by direct probe:** RA1, RA4, RA5, RA6, RA7, RA8 fully RESOLVED. RA2 and RA3 PARTIALLY RESOLVED — the coder's fixes work for every case the second repair task described, but Astra found one more composition each by probing the underlying mechanism rather than just the named attack:
- **RA2-R:** `parent_revision` has no constraint against self-reference. A contract revision can name itself as its own parent, which makes the ancestry check (designed to require a *strictly earlier* revision) accept ratings against the revision that IS the subject — defeating the "ancestor, never the revision itself" rule the fix was supposed to enforce. Reproduced with a fully valid, canonically-serialized document — not a constructed edge case.
- **RA3-R:** the dossier guard only checks that an `approved_by_decision_id` pointer is non-null — it doesn't check that the pointer was actually set *by* a successful draft→approved transition. A valid decision can be attached to a still-draft contract (one that has separately and correctly failed the real approval check) and a dossier against that draft still gets accepted.

Astra explicitly noted the coder's "one unifying mechanism" framing was real but **not uniform** — these two are exactly the cases where a stored field was trusted as proof of a relationship its own write path doesn't actually guarantee.

**Gate C:** all 4 previously-MODIFY'd tests (D07/D54/D55/B20) and all 8 independently-found Python mutants now ACCEPT with genuine killing tests, independently re-confirmed by direct mutant recreation (not just re-running the coder's harness).

**Rulings 1–6 (the coder's flagged items):** 1 (RA7 placement) ACCEPT. 2 (RA5 placement) ACCEPT. 3 (RA2 JCS-storage assumption) conditionally sound — fails closed on reordering, but flagged as needing the 0b writer to actually canonicalize on write, and a documented SQLite version floor before 0b. 4 (RA3 claim-link interpretation) ACCEPT, not scope creep. 6 (RA8 enforcement layer) ACCEPT for 0a, with a note that every future writer/importer must apply the same bound.

**Ruling 5 — genuine open design question, explicitly not decided by the review:** should promotion to `accepted_support` require contract-admitted production generally, or only for the specific consumers currently listed (today's behavior)? Astra's recommendation: require it generally if `accepted_support` is meant to be a globally reusable evidence status — but states plainly this is "a semantics/authority choice for the user under the charter, not an undisclosed additional 0a blocker."

**Non-blocking:** stale BUILD-STATE test-count shorthand (fixed above), diagnostic assertions shouldn't rely on SQLite trigger-firing order, document the bootstrap-rebuild process.

## 2026-09-25 — Task 0b landed (9 commits), routed for first Gate A+B+C review of the new scope
Coder shipped: the hard SQLite-compat gate (numeric version check, per-function JSON capability verification, pragma apply-and-read-back, dated capability-fact refusal — landed first as required); both small cleanups (dead `draft→superseded` edge removed, reversed-trigger-order check made permanent via `make gen2-trigger-order`); the store write layer (`gen2/store/api.py` — single-transaction all-or-nothing writes, JCS canonicalization and identity bounds enforced at the write primitive, not just schema validation — directly addressing the exact class of gap RA2/RA8 exposed in 0a); hashing-contract version recorded on commit/decision receipts; durable intake brief rows (new table + schema, versioned, owner/deadline, `awaiting_confirmation` state machine); and a dry-run importer that maps gen-1 records to the gen-2 scheme, read-only, core-only boundary grant, refuses to write outside its report path or into the gen-1 root, and correctly detects+reports a live `state/control.sqlite3` as blocking rather than silently treating the stale JSON queue as current.

Orchestrator independently re-ran `make gen2-check`: confirmed 262 tests pass, boundary/schema/DDL checks pass, reversed-trigger-order check passes (1,043 store tests/subtests identical in both orders) — mutation count (coder claims 515/515, up from 433) still verifying at review dispatch time.

**8 proposals + 5 questions, all routed to Astra rather than decided unilaterally.** Two of the five questions are explicitly flagged as **operator-escalation items, not Astra's or the orchestrator's to decide**: whether the importer should ever run against live gen-1 state, and whether it should get a read-only `sqlite3` grant to handle the (likely-live) managed-deployment case where the JSON queue is stale — both squarely inside the charter's strictest boundary ("never touch gen-1 runtime state, live topics, or running services"). The review brief explicitly instructs Astra to confirm the coder was right to leave both undecided, not to pick a policy itself.

Coder self-reported one process catch worth preserving: while building the mutation-harness's own baseline, it found a gap where a mutant could "die" from an import crash rather than a genuine assertion failure — caught before commit, harness now checks for it directly (matches the discipline from the 0a rounds: a green suite is only as good as its own harness's honesty).

Routed: task file `research-loops-public/private/reviews/gen2-0b-review-task-20260925.md`.

## 2026-09-25 — First 0b review (Astra, xhigh) — BLOCK (Gate A + C); Gate B PASS
Full report: `~/work/research-loops-public/private/reviews/gen2-0b-astra-review-20260925.md`. Astra independently confirmed all coder-claimed counts (262 tests, 33 tables, 515/515 mutants, 1,043 trigger-order tests) then found real defects the green suite didn't catch.

**5 Gate A findings, all independently reproduced (not inferred):**
- **A1 (HIGH):** `Store.transaction`'s COMMIT sits *outside* the rollback-protected try/except. Reproduced with a real deferred-FK write that fails at COMMIT time: the connection is left with an active transaction, one connection sees a partial write, a second connection sees the original state, and the "failed" batch can later be silently completed by supplying the missing piece — directly violating the write layer's own documented all-or-nothing contract.
- **A2 (HIGH, boundary deviation):** importer path-checks and the later file-open are two separate operations (check-then-open race). Demonstrated two synthetic exploits: swapping the output directory for a symlink into the gen-1 root *after* validation but *before* the report is written (writes into gen-1); and swapping a source file for an outside symlink after containment checks pass (reads outside gen-1). Both are TOCTOU races, not stable-symlink cases (those were already correctly refused).
- **A3 (HIGH):** the "is this a live managed gen-1 deployment" detector requires the marker file to be *contained* in the scanned root; an external symlink to a real managed-store marker makes it invisible, so the importer proceeds as if there's no managed store and treats the stale JSON queue as authoritative — directly contradicting how gen-1's own queue.py decides managed-vs-legacy mode.
- **A4 (MEDIUM):** `Store`'s public constructor accepts a raw connection + caller-supplied compatibility dict with no verification, bypassing the SQLite compatibility gate entirely — reproduced by constructing a Store against pragmas that were never actually applied and writing to it successfully. (Ironically: the new receipt tests themselves use this unchecked constructor.)
- **A5 (MEDIUM):** the importer crashes uncaught (TypeError) on malformed input shapes instead of reporting them as issues, silently accepts duplicate target IDs without flagging the collision, and — the carried-forward-requirement-relevant one — parses out-of-range/fractional numeric identity tokens through lossy float conversion before bounds-checking, so a non-integer token can silently become a valid-looking integer.

**Gate B: PASS**, with wording corrections needed (C-12/G-4/C-13 "Enforced at" lines need the exact qualifications Astra listed; C-13's rule text itself changed, not just its locator — route through the normal amendment process, not silently).

**Gate C:** one test **REJECTED outright** — the importer's "every record is classified" completeness test is tautological: it only checks records the importer itself emitted, so a wholly *omitted* input record passes undetected. Several EXTEND items (existing tests are useful but don't cover the newly-found attack classes).

**All 8 coder proposals ruled** — 7 straightforward ACCEPTs; proposal 1 (importer module) is a split ruling: the narrow import-graph restriction is accepted, but its *sufficiency as a read-only boundary claim* is explicitly rejected — that's exactly A2/A3.

**Both operator-escalation questions independently confirmed correct to leave open** — Astra: "The coder was right to leave this undecided... This review gives no authorization for a live run. I also performed none." Explicitly declined to pick between the two live-access options itself, offering only the technical tradeoffs. **Both remain open for the user.** Question 3 (brief cancel/archive authorization) got a non-binding recommendation, not a requirement. Question 5 (accepted_support) restated as still open.

**Explicit closing instruction, worth preserving:** "Do not soften this to PASS WITH FOLLOW-UPS because the suite is green."

## 2026-09-25 — Task 0b-repair landed (5 commits), routed for re-review
Coder closed all five findings: A1's COMMIT now runs inside the rollback path (with a documented, if untested-without-a-mock, fallback for rollback-itself-failing — connection closed, further use refused); A4's Store now has exactly two construction routes, both gated (`open_store` for durable stores, a clearly-separate `adopt_in_memory` for test fixtures that still runs the full compatibility check); A2/A3 fixed via descriptor-bound, no-follow file operations rather than a snapshot approach (coder's stated reasoning: a snapshot still needs safe reads to build, and true immutable snapshotting needs infrastructure outside this module — Astra asked to assess whether that reasoning holds); A5's numeric-token exactness check now runs before any lossy conversion, malformed/colliding/unsupported input is reported not silently dropped, and the coder found two *additional* crash paths on its own initiative (a NUL character in an ID, deeply nested JSON) beyond what the review asked for. The previously-REJECTED completeness test is rewritten against a hand-enumerated 40-record inventory. Orchestrator independently confirmed 275 tests pass and all boundary/schema/DDL/trigger-order checks match the coder's claims.

**5 questions, routed by type rather than treated uniformly** — this is the point of the exercise: two (symlink-following change could break on gen-1 structures the coder can't see; a queue.json missing `version` — coder doesn't know if older gen-1 queues omit it) are flagged as **needing the user's actual knowledge of the gen-1 deployment**, not Astra's technical judgment or a guess. The other three (a narrow residual report-directory race the coder proposes documenting rather than fixing further; whether never-read files should be listed in the report; a boundaries.toml wording precision question) are routed to Astra as ordinary technical rulings.

**C-13's rule-text amendment correctly left pending, not silently applied** — the coder recorded it as needing the user's decision rather than treating "I wrote the correction" as the same thing as "it's approved."

Routed: task file `research-loops-public/private/reviews/gen2-0b-repair-review-task-20260925.md`.

## 2026-09-25 — Re-review of 0b-repair — BLOCK, narrower still (A1–A4 RESOLVED; A5 incomplete)
Full report: `~/work/research-loops-public/private/reviews/gen2-0b-repair-astra-review-20260925.md`. **A1–A4 fully RESOLVED**, independently re-verified with fault injection beyond what was asked (a real SQLite authorizer that denies only ROLLBACK; a deliberate cross-thread connection-ownership violation to trigger the one previously-untestable close-failure path; a novel race — swapping the *final report filename itself* for a symlink to an existing gen-1 file right before exclusive-create, which correctly failed with the victim file unchanged). A2/A3 explicitly accepted "within the stated offline/stable-filesystem operating contract" — Astra's own phrase, not a rubber stamp: it confirmed the coder's snapshot-vs-descriptor reasoning holds, but was precise that this bounds what's actually proven (no cross-file-consistency guarantee, not a substitute for the frozen/reconciled snapshot the real Phase 4 migration will need).

**A5: two new narrow findings, both "crashes instead of reports" — the same class as the original bug, just two cases the first repair missed:**
- **A5-R1:** invalid Unicode (a lone surrogate) reaching report metadata through several paths the original fix didn't cover (references, issue text, topic IDs, source-map keys) crashes the importer with zero report output — a small, deliberately-crafted JSON snippet, no real filesystem needed.
- **A5-R2:** a ~4KB numeric token that exceeds Python's own integer-conversion digit limit isn't caught by the existing exception handling and also produces zero report output.

Both are continuations of A5's actual requirement (report don't crash), not new scope.

**Gate B: PASS**, one precision fix needed (a docstring literally says "before any float conversion" — the code actually computes the float first, then compares the round-trip; wording should say "before accepting or using a lossy conversion" instead).

**Coder's 5 questions, all ruled correctly per the routing the brief specified:**
1. **Internal gen-1 symlinks — reconfirmed user-only, unanswered by design.** "I did not inspect it and do not infer the answer from source code or fixtures."
2. Output-directory-moved-after-final-check residual — ACCEPTED as a documented operating restriction for this offline skeleton; no further race-closing required for 0b.
3. **Files-never-examined should be listed in the report** — real ruling, not deferred: Astra independently placed extra unread files in a synthetic tree and confirmed they're currently invisible in the report. Not a 0b blocker, but flagged as required before the report can be trusted as migration-planning evidence.
4. **Missing-`version` queues — reconfirmed user-only, unanswered by design.**
5. `boundaries.toml`'s "read-only" wording — correct to leave the normative entry unchanged (it's still true as policy; the import graph never claimed filesystem-level enforcement); a clarifying wording pass is recommended, not required.

**Mutation-count accounting, worth carrying forward as a general discipline:** Astra explicitly diffed 515→560 rather than accepting the delta at face value — "46 added, one removed, not 45 newly independent guarantees" (one old mutant was replaced by a more specific set, not simply supplemented).

**Explicit note on the bookkeeping:** "Its bookkeeping statement that A1–A5 are 'all closed' is a coder claim superseded by this verdict" — same discipline as every round: a coder's own completion report is a claim, not a verified fact, until independently re-probed.

## 2026-09-25 — Task 0b-repair-2 landed (3 commits), routed for likely-final review
Coder's session ended without sending a final prose report this time (a stall of the "work landed, no closing message" kind seen once before with Astra) — the orchestrator worked from the commit messages directly rather than waiting, since the actual deliverable (working, tested code) doesn't depend on the coder narrating it. A5-R1 and A5-R2 both closed: the integer-conversion-limit failure is now converted to a reportable parse error without raising or lifting the interpreter's own limit (the review's explicit prohibition); invalid Unicode is now caught in all four paths the review named (refs, issue text, topic IDs, sources keys), not just the one path the first repair covered.

**Coder found and fixed one more related bug on its own initiative, not asked for:** a `Decimal` exponent past Python's representable range (e.g. `1e-9999999999999999999`) was causing an uncaught `InvalidOperation` in the same exactness-check code path — same failure class as A5-R2, just a different trigger. Flagged to Astra to independently verify and to assess as a signal about the coder's own testing discipline, not just accept as another line item.

Orchestrator independently re-ran `make gen2-check`: confirmed 279 tests pass (up from 275), boundary/schema/DDL checks pass, trigger-order check passes.

Routed: task file `research-loops-public/private/reviews/gen2-0b-repair-2-review-task-20260925.md`. Explicitly asked to state plainly whether 0b is now accepted, matching the same discipline used for 0a's final round.

## 2026-09-25 — Final 0b review (Astra, xhigh) — **PASS all gates. 0b ACCEPTED.**
Full report: `~/work/research-loops-public/private/reviews/gen2-0b-repair-2-astra-review-20260925.md`. A5-R1/R2 confirmed resolved by direct reconstruction of the exact prior-failing inputs (both now produce usable reports, not zero bytes). A1–A4 confirmed unchanged via AST comparison against the last-verified version (not re-run from scratch — Astra explicitly declined to repeat the earlier fault-injection campaign since nothing in that code changed).

**The unprompted Decimal-overflow fix: independently verified as real and correctly fixed**, and explicitly called a positive signal: "Finding this additional exception source while repairing the integer conversion path is a specific positive sign... evidence of improved local testing discipline, not proof of exhaustive malformed-input coverage" (the qualifier matters — noted, not overclaimed).

**Original 0b task scope (`docs/gen2/tasks/0b.md`) confirmed fully satisfied**, item by item — not just the specific review findings, the actual original requirements list.

**The coder's missing final prose message explicitly ruled a non-issue:** "a process omission... does not leave an implementation requirement unfinished or justify another repair cycle." Confirms the orchestrator's handling (working from commits, not waiting on narration) was correct.

**Phase 1 authorization — explicitly NOT granted by this report, and explicitly why:** "0b no longer blocks it... It is not authorized to begin now solely by this report: BUILD-STATE still lists 0c as queued, and this review neither completes that task nor supplies the operator's approval." This is Astra correctly declining to overstep — accepting 0b doesn't imply anything about 0c or the Phase 0→1 operator gate.

**All open operator items reconfirmed, none decided:** internal gen-1 symlinks (unanswered), queues missing `version` (unanswered), files-never-examined (recorded in store README, not implemented — confirmed present), live-state authorization / SQLite-vs-export / `accepted_support` general policy / C-13's normative amendment (all still pending, none touched this round).

## 2026-09-26 — 0c review (Astra, xhigh) — BLOCK (Gates A + C), Gate B PASS
Full report: `~/work/research-loops-public/private/reviews/gen2-0c-astra-review-20260925.md`. The first dispatch (2026-09-25) died on a one-off Codex 401 (cause unknown; auth is OAuth). The redispatch ran clean.

**Independently verified:** `make gen2-check` exit 0 unpiped; 307 tests, 589/589 declared mutants, 14 schemas / 51 valid + 150 invalid fixtures, 1,845 production lines; no gen-1, gateway or engine paths changed. Four catalog mutants were rebuilt by hand and all were killed, including the replacement "env not checked" mutant, which does isolate the check path.

**Findings:** A1 (HIGH): the deployment contract requires the unmodified gateway, but that gateway still falls back to `~/.vault-token` and reports a failed secret read the same way as a missing one, so the contract can't be met. A2 (HIGH): an unreadable webhook response validates as a settled failure with no reconciliation. A3: a `mixed` disposition validates with an empty hold list. A4: a `partial_write` receipt can claim an observed total. A5: the spec has no path for replaying an SQL export at an equal ordering pair after a lost receipt. A6: `GEN2_OPERATOR_LISTEN` binds container loopback, which the Compose topology can't reach. C1 (HIGH, Gate C): the mixed-disposition fixture still passes after its rule is removed, because two missing properties collapse into one declared signature. Astra demonstrated this with a counterfactual whole-tree run.

**Accepted:** export kept separate from publication (the design); generating from the registry seed; the credential-posture pricing; the service-key table; 28 catalog tests plus 12 positive and 44 negative fixtures, within their stated bounds.

**Coder questions ruled:** (2) the disposition vocabulary may stand as proposed; (3) no `cost_tier` field is needed to accept 0c; (5) the reader freshness envelope stays unextended; (4) port availability is for the user to confirm at deploy time, but A6 gets fixed now; (1) the boundary amendment is escalated to the user with a recommendation to adopt it with refinements. It only needs deciding before a phase implements export (Phase 3), so it does not block 0c.

**Routed:** task `docs/gen2/tasks/0c-repair.md` to an Opus 5.5 coder (agent 9eb1ac80). A1's owner is the gateway repair work already in the phase plan (Phases 2 and 3), so it isn't sent to the user. The repair is a spec fix only; `gateway/` is untouched.

## 2026-09-26 — 0c-repair re-review (Astra, xhigh): BLOCK, narrow (A + C); Gate B PASS
Full report: `~/work/research-loops-public/private/reviews/gen2-0c-repair-astra-review-20260926.md`. Independently observed `make gen2-check` exit 0: 321 tests, 605/605 mutants, 54 valid + 158 invalid fixtures, 1,845 production lines unchanged.

**CLOSED:** A1 (vault mode inadmissible until the reviewed gateway release; ownership is Phase 2/3; no separate approval question), A3, A4, A5's SQL contract, A6, A2 at the schema level, and C1. Astra rebuilt every original reproduction: each validated at ad3e2ec and is refused at HEAD. A broken schema mutation is correctly classified INVALID. 0a changes verified: only the fixtures' `tests` and `errors` fields changed, and every 0a schema is byte-identical. Count-based kills are ACCEPTED as bounded redundant-guard checks.

**Remaining:** BLOCK 1 (HIGH): the webhook table treats any 2xx as full application; Astra demonstrated a 202 receiver that applied nothing. BLOCK 2 (HIGH): engine-side watermarks plus per-key dedup don't implement the four ordering branches; Astra demonstrated both a same-pair conflicting manifest being applied and an in-flight older request regressing state. BLOCK 3 (MEDIUM, Gate C): a compensated two-edit mutant swaps which identity members are required without changing the error count; it needs three isolated negatives.

**Coder questions ruled:** declared counts are acceptable for the redundant-guard 0a fixtures; an echoed idempotency key is not required, but status class alone is not sufficient; the projector sharing the engine listener with a projector-only token is CLOSED under A6.

**The user at the Phase 0→1 gate (Astra's list):** C-13 ratification; opening Phase 1; the BOUNDARIES amendment, which can stay pending until the phase that implements export. Nothing else is escalated. Astra explicitly declined to re-escalate `accepted_support`, symlinks, queue versions, gateway repair authorization and importer live access.

**Routed:** `docs/gen2/tasks/0c-repair-2.md` to an Opus 5.5 coder (agent 1bdfa4b8).

## 2026-09-26: 0c-repair-2 re-review (Astra, xhigh): **ACCEPT. 0c ACCEPTED. Phase 0 (0a, 0b, 0c) fully ACCEPTED.**
Full report: `~/work/research-loops-public/private/reviews/gen2-0c-repair-2-astra-review-20260926.md`. Gates A/B/C all PASS. Independently observed `make gen2-check` exit 0: 324 tests, 608/608 mutants, 55 valid + 161 invalid fixtures, 1,845 production lines unchanged. This matches the orchestrator's own run.

**BLOCK 1 closed:** a webhook "delivered" now requires the admitted `export-webhook/1` protocol. Astra's 202-then-discard receiver maps to unknown. 17 unauthoritative status/header combinations map to unknown. All nine listed refusals map to observed zero. A dishonest receiver answering `200 applied` without applying anything is ruled the inherent trust boundary of any receiver assertion, now an explicit admission condition, not a spec gap. **BLOCK 2 closed:** Astra built an SQLite-backed receiver and ran every trace: same pair with a different manifest or content gives 409 conflict with no rewrite; exact replay gives already_applied; a held older request gives superseded with no regression (20/20 concurrent runs); crash before commit and crash after commit both recover correctly. **BLOCK 3 closed:** the exact compensated mutant and both rotations are detected, and the counterfactual docstring's bounded claim is accepted.

**The user at the Phase 0→1 gate (final list):** (1) ratify C-13; (2) approve opening Phase 1; (3) adopt the BOUNDARIES export/projector amendment, or leave it pending until the phase that implements export. **`accepted_support` generalization:** settled by the design, can land early in Phase 1, before downstream paths rely on it and before Phase 1 acceptance. It is not an operator question. Merge to main and a first push remain the user's actions.

## 2026-09-26: OPERATOR RULING (the user): one standard export API, nothing setup-specific
"Nothing in this build should have a caveat or specific feature for my setup. This is going to be open source." External export must be **one standard API that any database can connect to, local or cloud**. The operator's Neo4j/Qdrant GraphRAG connects to it after the build, like any other database, with no special path of its own. "Don't change the internal process." This overrides flow doc S8's hardwired Neo4j/Qdrant publication sinks, and it overrides 0c's design of a second, generic export path alongside them. The orchestrator should have flagged the parallel-path design when export was first requested. It is also the operator's decision on the BOUNDARIES amendment: fold export into one generic role.

Phase 0 is reopened for task **0d** (`docs/gen2/tasks/0d.md`): collapse publication and export into one versioned export API with generic reference connectors only (SQL connection string, JSONL/file, webhook). Remove every Neo4j/Qdrant/GraphRAG reference from schemas, DDL, fixtures, tests, deployment and governing text. Keep every guarantee that export already proved. The engine never reads research back from an external database. The internal process is unchanged. Routed to an Opus 5.5 coder (agent 5985c8ba). Astra reviews it next.

## 2026-09-26: 0d review (Astra, xhigh): BLOCK, narrow (Gates A + C); Gate B PASS
Full report: `~/work/research-loops-public/private/reviews/gen2-0d-astra-review-20260926.md`. Astra's independent run of `make gen2-check` exited 0, matching the orchestrator's: 351 tests, 674/674 mutants, 57 valid + 165 invalid fixtures.

**CONFORMS:** there is now one export path; the internal process is unchanged; every guarantee export had already proved is preserved; no `neo4j|qdrant|graphrag` remains in the build outside history.

**Findings:**
1. **P1:** host-specific deployment material remains:
   - DEPLOYMENT-CONTRACT's gen-1 service and occupied-port inventory;
   - the generator and env example's "on this host" gen-1 notes;
   - a personal cleanup note in ENVIRONMENT;
   - hardcoded `~/work/...` locators in CHARTER and INVARIANTS.

   Astra: the ruling covers the whole build surface. Don't ask the user about any of this.
2. **P2 (Gate C):** four replacement-rule mutations survive every fixture and all 36 counterfactual tests:
   - extension missing only `module`;
   - extension missing only `review_ref`;
   - `mixed_generation` re-added;
   - delivered pair missing only `options_revision`.
3. **P2:** EXPORT-API §~326 claims the store refuses an extension with no implementation, but the DDL checks only the connector type. Astra showed this with direct inserts.

**Gate list (Astra):** the C-13 ratification and opening Phase 1 remain. The export design and the BOUNDARIES amendment are decided by the ruling. There are no port or coexistence questions. `accepted_support` goes early in Phase 1.

**Routed:** `docs/gen2/tasks/0d-repair.md` to an Opus 5.5 coder (agent 43851429).

## 2026-09-26: 0d-repair: host note moved here from ENVIRONMENT.md (review finding 1)
The build-environment document no longer carries this machine's maintenance state; it keeps the generic rule that the isolated venv excludes user-site packages. The note, as it stood in `docs/gen2/ENVIRONMENT.md` ("Host state left by the earlier practice"): the 0a-repair round installed `rfc8785==0.1.4` into the build host's user site (`~/.local/lib/python3.12/site-packages/`). The 0a-repair-2 venv fix installed, upgraded and removed no host package, and that copy is no longer on the build's import path. Removing it is the operator's decision (first recorded above, 0a-repair-2 coder item 7). Nothing was installed or removed by 0d-repair.

## 2026-09-26: 0d-repair re-review (Astra, xhigh). **ACCEPT. 0d ACCEPTED. Phase 0 (0a, 0b, 0c, 0d) fully ACCEPTED.**
Full report: `~/work/research-loops-public/private/reviews/gen2-0d-repair-astra-review-20260926.md`. Gates A/B/C all PASS.

**Independent check:** Astra ran `make gen2-check` and it exited 0 (356 tests, 680/680 mutants, 57 valid + 171 invalid fixtures). The orchestrator's own run gave the same result.

**Finding 1 closed:** Astra's own sweep covered 287 active files, looking for private products, paths, hosts, addresses, services, identities and endpoints. It found no remaining setup-specific material. Astra accepted leaving the following in place:
- The user as the named operator in governance text;
- the synthetic operator-ID test-fixture values (renamed to `'user'` 2026-09-27);
- the `jev=typesafe-jev` alias example.

**Finding 2 closed:** Astra rebuilt all four survivors, and each is now killed by its own isolated negative. Both mirrors are sound, and the positive controls still hold.

**Finding 3 closed:** extension admission is now accurately documented as a schema rule, with router validation named as a Phase 1/3 obligation.

**The user at the Phase 0→1 gate (final):** (1) ratify C-13; (2) approve opening Phase 1. Nothing else. `accepted_support` goes early in Phase 1. Merge and push remain the user's actions and are not prerequisites for the gate.

## 2026-09-27: OPERATOR DECISIONS at the Phase 0→1 gate
1. **Operator name removed.** Every mention of the operator's personal name in the build now reads "user" / "the user". That covers governance, deployment, task and history docs, and the synthetic test operator IDs, which now read `'user'`. A grep finds neither the name nor any home-directory path anywhere in `gen2 tools docs/gen2 deploy Makefile .github`. The orchestrator's independent `make gen2-check` exited 0: 356 tests, 680/680 mutants.
2. **C-13 ratified.** The sentence fixing the hash-contract versions recorded on commit and decision receipts is now part of the frozen rule. INVARIANTS C-13 is updated.
3. **Phase 1 APPROVED**, conditional on item 1, which is now done. The first task is 1a: the `accepted_support` generalization.

## 2026-09-27 — 1a review (Astra, xhigh) — **PASS all gates. 1a ACCEPTED (first round).**
Full report: `~/work/research-loops-public/private/reviews/gen2-1a-astra-review-20260927.md`.

**Independent verification:** `make gen2-check` exits 0, with 363 tests and 691/691 mutants. All 9 V10 mutants and both importer mutants were reconstructed independently, and all were killed. 70 reviewer-authored probes ran against real SQLite, covering admission, promotion, isolation, supersession, delegate inheritance, the consumers and the importer.

**What it establishes:** "admission already checked approval" holds under the supported store contract. After supersession, the historical producer still passes. That is consistent with C-12's retained pins and with V-10's limit on amendment impact.

**Carried into Phase 1:**
- the router must bind actual production and adoption to authenticated, atomic commits and their receipts (task 1b);
- amendment handling must apply G-1's impact and stale-work rules before Phase 1 is accepted (task 1d).

## 2026-09-27: 1b review (Astra, xhigh). BLOCK (Gates A + C); Gate B PASS
Full report: `~/work/research-loops-public/private/reviews/gen2-1b-astra-review-20260927.md`.

**Independent verification:** `make gen2-check` exit 0 (485 tests, 822/822 mutants). The schema differential compared 244 fixtures and 26,780 instances with zero disagreements. Astra rebuilt 9 declared mutants independently; all 9 were killed.

**Findings:**
- **A1 (HIGH):** claim, launch and observation sample the clock before acquiring the write lock, so a lease or deadline that expires during a lock wait is accepted.
- **A2 (HIGH):** delivery receipts discard content, and conflicting receipts replay.
- **A3 (HIGH):** a qualified screening spec can name a different contract than the admitted one.
- **A4 (MEDIUM):** nested artifact references skip the metadata binding, and there is no in-transaction recheck.
- **A5 (MEDIUM):** transition replay fails once the target is no longer current.
- **C1:** an exact-expiry `>=`→`>` mutant survives all 31 relevant tests.
- **C2:** the payload-digest negative is not isolated.
- **C3:** the provider-screening fixtures are invalid as positive controls.

**Proposals:** 9 ACCEPTED; #8 (screening consistency) MODIFY, which is A3.

**Scope rulings:**
- Rule 9 is architectural lint, not runtime isolation. Acceptable, but the README must list the re-export/alias gaps.
- Bearer capabilities are acceptable for trusted in-process use only until 1e authenticates principals.
- **Bootstrap:** creating topics, contract drafts and works can stay in Phase 2. Seeded fixtures suffice for Phase 1. **1d must add minimal router-owned brief/amendment version commands**, which 1e then exposes.
- Intermediate non-green commits are non-blocking; the charter imposes no per-commit bisectability.

No operator decision is needed.

**Routed:** `docs/gen2/tasks/1b-repair.md` → Opus 5.5 coder.

## 2026-09-27: 1b-repair re-review (Astra, xhigh): BLOCK, narrow (one path)
Full report: `~/work/research-loops-public/private/reviews/gen2-1b-repair-astra-review-20260927.md`.

**Closed:** A1–A4 and C1–C3. Astra rebuilt every reproduction.

**Rulings:** both probe adjustments were legitimate. The coder's added hold rule (a named hold must exist and belong to the manifest's topic) is ACCEPTED. Leaving `invocation_id` unchecked is ACCEPTED for this phase; the exporter relationship is Phase 3. The 31 DDL mutants are sound.

**Remaining:** A5-R (MEDIUM). `record_transition` requires staged bytes before it looks up the recorded transition. As a result, a historical `result_ready` replay after commit and restart, with the bytes gone, is refused as `payload_missing` when it should be `replayed`. A changed unstaged digest also returns `payload_missing` instead of `transition_conflict`. Astra reproduced this on a durable store in a fresh process; the store rows were unchanged.

No operator decision is needed. **Routed:** `docs/gen2/tasks/1b-repair-2.md` to an Opus 5.5 coder.

## 2026-09-27 — 1b-repair-2 re-review (Astra, xhigh) — **1b ACCEPTED** (3 review rounds)
Full report: `~/work/research-loops-public/private/reviews/gen2-1b-repair-2-astra-review-20260927.md`.

**A5-R closed.** Astra reran its original probe unchanged: 2/2 pass. Each case commits, restarts in a fresh process past expiry, and replays. An identical request returns `replayed`, a changed digest returns `transition_conflict`, and every row stays unchanged.

**New race probe:** 8/8 schedules pass, using separate connections and event-synchronized with no timing sleeps. Astra also reconstructed 5 mutations on disk; all are killed and keep their meaning.

**Non-blocking, carried into 1c:** the mutation runner only swaps modules in the current interpreter, so kills that happen inside a fresh child process are invisible to it. The inventory audit found no named kill that depends only on such a child. 1c relies heavily on subprocesses, so 1c must add disk mutation first.

**Routed:** task 1c (supervisor, spool, fake executors, lifecycle fault set) to an Opus 5.5 coder.

## 2026-09-27: 1c review (Astra, xhigh). BLOCK on all gates (A, B-claims, C)
Full report: `~/work/research-loops-public/private/reviews/gen2-1c-astra-review-20260927.md`. The first review session was killed by OpenAI's cybersecurity content filter because of offensive-sounding task wording. That was a provider stop, not a finding. The task was reworded and re-dispatched fresh.

**Independent checks:**
- `make gen2-check` exit 0: 756 tests, 990/990 mutants. The mutation step took 35 minutes.
- Five full-suite runs under load, all green.
- Rerun matrices, all passing: 90 lifecycle cases and 50 crash cases.
- 8 independent mutants, all killed.
- `--no-disk` audit: exactly 8 mutants depend on the new child-tree propagation.

**Findings (all reproduced):**
- A1 (HIGH): recovery starts executors after a pause or lease expiry. Reproduced 10/10.
- A3 (HIGH): the parent lease is released while an owned delegate is still running. Reproduced 8/8.
- A6 (HIGH): a recorded hash bypasses topic authorization. Inherited from 1b; this is Q6, rejected.
- A9 (HIGH): losing the launcher during a router outage defeats the local deadline.
- A2 (HIGH): cancellation after an uncertain spawn can never reconcile, because of a `failure_class` contract mismatch.
- A4 (HIGH): failed evidence and journal writes escape without an incident.
- A5 (HIGH): unrelated successful reads refill a failing write's retry budget.
- A7 (HIGH): generic hold clearance clears an `outcome_unknown` episode hold without reconciliation.
- A8 (MEDIUM): conflicting lifecycle facts are reported as a replay.
- A10 (MEDIUM): changes to a scratch file made after it was opened go undetected.
- A11 (MEDIUM): exhausted spawn and commit retries leave no owned, deadlined incident.
- C1: the mutation preflight doesn't attest the executing child, and `children.py` `setdefault(cwd)` can import unmutated code.
- C2: the unidentified intermittent failure is still unresolved.
- C3: two guards have no bound mutants.
- B1: README claims are overstated.

**Rulings on the coder's questions:**
- Q1 ACCEPT.
- Q2: no blanket hold, but exhausted, pending and persistence failures need an owned, deadlined incident.
- Q3 ACCEPT in principle.
- Q4 ACCEPT as interim, with an incident on exhaustion.
- Q5: accept cancellation only after factual confirmation that the group is empty.
- Q6 REJECT.

Mutation-runtime recommendations have been recorded. No operator decision is needed.

**Routed:** `docs/gen2/tasks/1c-repair.md` to an Opus 5.5 coder.

## 2026-09-27: 1c-repair re-review (Astra, xhigh): BLOCK, narrow
Full report: `~/work/research-loops-public/private/reviews/gen2-1c-repair-astra-review-20260927.md`.

**Independent verification:** `make gen2-check` exit 0: 894 tests, 1040/1040 mutants, mutation step 737 s under load. All 637 tracked-file hashes were unchanged.

**CLOSED:**
- A1–A4 and A6–A11, each rebuilt against the original reproductions.
- C1: child attestation holds, and the rebuilt probe that goes around it is refused.
- C2: two concrete races were diagnosed with deterministic regressions. The original failure is not retrospectively identified, but the investigation meets the standard.
- C3.
- Most of B1.

**Remaining:**
- A5-R (MEDIUM): parent cleanup of a stalled delegate bypasses the delegate's outage budget and pushes its incident deadline later. Reproduced 8/8.
- C4: mutation selection omits paired positive controls.
- C5: the "replaced lease" skip excludes reachable delegate cases (discovery, verification and checkpoint parents).
- B: the bounded-retry and positive-control claims are overstated, and the 7-minute runtime is one recorded run, not a dependable figure. Observed runs: 434, 737 and 1,219 s.

No operator decision needed. **Routed:** `docs/gen2/tasks/1c-repair-2.md`.

## 2026-09-27: 1c-repair-2 re-review (Astra, xhigh). BLOCK, narrow
Full report: `~/work/research-loops-public/private/reviews/gen2-1c-repair-2-astra-review-20260927.md`.

**Independent verification:** `make gen2-check` exit 0, 970 tests, 1054/1054 mutants.

**CLOSED:**
- A5-R: original 8/8 regression passes, plus an extended delegate-deadline regression 8/8.
- C5.
- Both new budgets: 13 policy probes across all kinds and all six immediate-stop reasons.

**ACCEPTED:** the collected-end cleanup gap (descendants never confirmed gone). It stalls with a visible incident that needs an operator, which is acceptable under L-7/RG-3.

**Remaining:**
- BLOCK 1 (L-6/RG-3): a recursive `_grant()` re-claims a parent stalled on an incident. That is a third call path bypassing the stall gate, after A5 and A5-R. Reproduced 4/4 with 12 extra calls each; the deadline gets renewed.
- BLOCK 2 (C4): the tracer credits enclosing branch conditions, so controls can pass without executing the changed guard (3 examples). Astra also built passing controls for 3 of the 9 "no control possible" mutants.

**Orchestrator routing decision:** this is the third path of the same kind, so 1c-repair-3 closes the class structurally. The gate goes at the router-call chokepoint, and an open incident's deadline becomes write-once. No per-site patch.

No operator decision needed.

## 2026-09-28: 1c-repair-3 re-review (Astra, xhigh). BLOCK, narrow
Full report: `~/work/research-loops-public/private/reviews/gen2-1c-repair-3-astra-review-20260928.md`.

**What closed:**
- The sequential retry bypasses are repaired. Static inspection found no backend call that goes around `_call()`.
- The tightened control rule fixes the earlier enclosing-branch examples.

**What remains:**
- **BLOCK 1:** overlapping advances on the same job are not serialized. `_spend()`/`_save()` writes the caller's stale journal snapshot back, which erases an open incident and resets the exhausted counter. That produced 12 calls instead of 6, and the deadline moved. Reproduced 8/8: 4 kinds × {shared instance, shared jobs directory}. A temporary whole-advance lock fixes it.
- **BLOCK 2:** a relevant passing control exists for `no-abandon-handshake`.

**Routed:** `docs/gen2/tasks/1c-repair-4.md`, a cross-process per-job lock with parent↔delegate lock ordering.

## 2026-09-28 — 1c-repair-4 re-review (Astra, xhigh) — **1c ACCEPTED** (5 review rounds)
Full report: `~/work/research-loops-public/private/reviews/gen2-1c-repair-4-astra-review-20260928.md`.

**BLOCK 1 closed.** Astra rebuilt the overlap regression as a genuinely concurrent probe rather than reusing its old script: 4 kinds × 2 pause points × {shared supervisor, shared directory, separate processes} = 24/24 pass, with kernel lock contention actually observed, exactly six failing calls, the incident and its original deadline preserved, and no executor started. Also 12/12 separate-process recovery schedules, 16/16 parent/delegate schedules in both lock orders, and lock-resource checks (no descriptor leaks; one lock inode per job). Astra confirmed the coder's criticism of its own earlier script was correct: that script's pass rested on barrier timeouts, not a real race.

**BLOCK 2 closed:** the abandonment control is paired; the `for`-header rule and the remaining single unpaired mutant are accepted.

**Stated limits (documented, accepted):** the serialization guarantee is per job, across cooperating threads and processes on one Linux host — not cross-host; the journal revision check is a backstop, not independent mutual exclusion; `busy` is transient, creates no incident and spends no budget.

**1c totals:** 5 review rounds (BLOCK 15 findings → 3 → 2 → 2 → ACCEPT). Every finding was reproduced before repair and independently re-verified after. Production 5,771/10,000 lines; 1,065 tests; 1,071/1,071 mutants killed, 1,058 with paired controls.

## 2026-09-28 — Scope audit (Astra, xhigh, operator-requested): production CONFORMS; two doc slips fixed
Full report: `~/work/research-loops-public/private/reviews/gen2-scope-audit-astra-20260928.md`. Requested by the operator: "make sure the agents are not over-engineering or going outside of the architectural doc other than what's been approved."

**Verdict:** no production mechanism lacks an architectural or recorded-ruling basis; no banned construct (event bus, DSL, orchestration framework) exists in any form; nothing needs removal. The "beyond the brief" repair additions are each the minimal closure of a real defect, not accumulated untracked scope.

**Must-fix (documentation only, both fixed by the orchestrator same session):** BUILD-STATE still headed the state as Phase 0 with a stale operator-gate line (now: Phase 0 complete, Phase 1 open); one REVIEW-LOG entry repeated the removed personal identifier while claiming none remained (now generic). A full grep confirms the identifier appears nowhere in the build.

**Taste (recorded, no action now):** stop growing the control-selection tracer — prefer explicit reviewed pairings when next touched (folded into the 1d brief); keep the router's bounded schema validator bounded — if the vocabulary grows materially, seek a reviewed dependency grant instead; label the root README as describing gen-1 (queued for 1e's doc pass).

## 2026-09-28 — Task 1d dispatched (registries, config bundles, reservations, brief/amendment versioning, G-1 impact)
Brief: `docs/gen2/tasks/1d.md`, scoped to INVARIANTS §13's Phase 1 column and the store README deferrals, carrying the 1a-review G-1 obligation, the 1b bootstrap ruling, the 1b proposal-3 interim (`amendment_pending` → real impact handling), and the 1c policy-bundle/scheduling deferrals. Coder: Opus 5.5 agent 7a61b979.

## 2026-09-28 — 1d review (Astra, xhigh) — BLOCK (Gates A + C); Gate B PASS
Full report: `~/work/research-loops-public/private/reviews/gen2-1d-astra-review-20260928.md`. Independent build matched: exit 0, 1,167 tests, 1245/1245 mutants, production 6,560.

**Findings:** (1) HIGH — G-1/G-6 compatibility trusts the framing version label: changed framing content passes as compatible, and cycling 1→2→1 silently revives a claim recorded stale, which then promotes without adoption. (2) HIGH — restart without the `config_bundle` argument runs old jobs under default `Policy()`, bypassing their pinned budgets. (3) HIGH — `WorkOrder` can't carry `retry_of`/`reservation`, so the accepted lane gate can't actually be exercised through the supervisor. (4) MEDIUM — fractional `hold_window_s` truncates to a zero window. (5) MEDIUM — after a refused bundle, restoring the valid one leaves the capability fact falsely `failing`, and the station test requires the stale state. (6) MEDIUM/Gate C — the brief wrong-parent negative is masked by hash validation; a parent-only mutant survives all 26 amendment tests.

**All seven open questions ruled ACCEPT** (lane gate, proactive cancellation, fail-closed missing policy values, admission-unit reservations, question-entry format, `policy_version`, claimable table in code), with finding 3 as required integration. **The four INVARIANTS locator updates are authorized** as repair work (V-10 wording only after finding 1).

**Routed:** `docs/gen2/tasks/1d-repair.md` to an Opus 5.5 coder.

## 2026-09-28 — 1d-repair re-review (Astra, xhigh) — BLOCK, narrow (2 areas)
Full report: `~/work/research-loops-public/private/reviews/gen2-1d-repair-astra-review-20260928.md`.

**CLOSED:** the framing-content and stale-revival repairs hold under Astra's rebuilt probes (version-label cycling, restored obligations/briefs); pinned policy on every start; retry/reservation through work orders (real failed subprocess re-queued and committed for all four kinds); exact hold arithmetic (500,000,000 ns on the probe); lineage isolation (the parent-only survivor is killed).

**Remaining:** (1) HIGH — obligation removal/replacement bypasses impact classification: the classifier compares only shared IDs and the framing projection omits coverage cells, so removing `O-2` (cell → `deliberately_out`) or re-issuing the same substantive change under a fresh ID gets blanket `compatible`, and the old claim promotes without adoption. G-1 locks the approved inventory; G-5 authorizes bounded additions, not removals. Conservative revision-wide fencing suffices at Phase 1 scope. (2) MEDIUM — the unmounted-restoration path never records capability recovery (`failing` forever), while explicit remount does.

**Routed:** `docs/gen2/tasks/1d-repair-2.md` to an Opus 5.5 coder.

## 2026-09-28 — 1d-repair-2 re-review (Astra, xhigh) — **1d ACCEPTED** (3 review rounds)
Full report: `~/work/research-loops-public/private/reviews/gen2-1d-repair-2-astra-review-20260928.md`. Gates A/B/C all PASS.

**Both findings close.** The original removal and replacement probes now classify `protocol_changed`, fence the running pass, refuse its commit as `amendment_pending`, list the observation/claim stale, and only adoption promotes. **Every fresh bypass attempt fenced:** splitting an obligation (with or without keeping one ID), merging, moving between facets (obligation or cell alone), nominally-equal coverage with a redefined rationale, and a comparator change under unchanged coverage. Pure JSON reordering stays compatible, as it should. Restoring an earlier inventory revives nothing. The two conservative extras are accepted for this scope, and the gap-fill control remains a genuine G-5 addition. Both probe adaptations were ruled faithful. The unmounted-restart recovery sequence gives failing → healthy with history retained.

**1d totals:** 3 rounds (BLOCK 6 findings → BLOCK narrow 2 → ACCEPT). **Carried:** 1e owns authenticated transport and the operator surface (including authenticated brief closure and exposing the trusted versioning/config operations); Phase 2 owns real intake/contract construction and the outcome operation for writing claim source links (still fixture-seeded).

## 2026-09-28 — 1e review (Astra, xhigh) — BLOCK (Gates A + C); Gate B PASS. **Phase 1 NOT complete.**
Full report: `~/work/research-loops-public/private/reviews/gen2-1e-astra-review-20260928.md`. Independent build matched (1,291 tests, 1377/1377).

**Findings:** (1) HIGH — DEPLOYMENT-CONTRACT §4 says "Before Phase 1 is accepted" the deployment must demonstrate, with the pinned runner: credential refresh without rebuild; container replacement preserving auth-volume access; simultaneous use of one auth home without corruption; revoked/expired credentials → dated capability fact + typed hold. No demonstration exists and no amendment moved it. **Operator fork: supply the demonstration, or explicitly amend the contract's phasing. Escalated to the operator.** (2) HIGH — the collected-end incident has no usable authenticated recovery route (the carried 1c ruling requires fresh termination evidence → episode reconciliation → recovery; deferring to Phase 2 rejected). (3) credential reflection in raw-path logging/exception replies. (4) MCP envelope looser than HTTP. (5) open incidents lose topic attribution after the lane advances. (6) CLI IncompleteRead misclassified. (7) startup secrecy assertions can assert against nothing. (8) the connection-reset fix survives its own removal (66/66 pass without it).

**Accepted:** the four bounded architecture choices (close_brief + read-only status; app's http grant; capabilities off the listener; auth-persistence-as-reread) and the invariant locator repairs. **§13 accounting:** everything Phase 1 owes is judged satisfied at mechanical scope except the operator-surface findings and finding 1.

**Routed:** findings 2–8 → `docs/gen2/tasks/1e-repair.md` (Opus 5.5). Finding 1 → the operator.

## 2026-09-28 — 1e-repair re-review (Astra, xhigh, fresh session after a second content-filter stop) — BLOCK, narrow
Full report: `~/work/research-loops-public/private/reviews/gen2-1e-repair-astra-review-20260928.md`. The first session was cut off by the provider's cyber filter mid-review; its one open lead was preserved in the retry's task file, and the fresh session **confirmed it as the HIGH finding**: `recover_incident` saves `incident: null`/`outcome: null` before advancing, so a crash before reconciliation leaves retries returning `replayed` with nothing done — episode `outcome_unknown`, open hold, unreleased lease, incident invisible. Reproduced with a real engine process, `os._exit(71)` fault injection, and a replacement engine.

**Closed:** original findings 4 (MCP strictness), 5 (incident attribution), 6 (CLI exit classes), 8 (unread-body regression, with the 2 s bound accepted). **Remaining:** the recovery-replay defect above; MCP serialization/numeric-ID credential escape; startup secrecy tests discarding the first stdout line.

**Routed:** `docs/gen2/tasks/1e-repair-2.md` to an Opus 5.5 coder. Finding 1 of the original review (auth-volume demonstration) remains with the operator, recommendation already presented: amend the phasing to "before any live provider execution."

## 2026-09-28 — OPERATOR DECISION: the §4 auth-volume demonstrations run UP FRONT (no phasing amendment)
The operator chose to satisfy DEPLOYMENT-CONTRACT §4 as written rather than amend its phasing: "Doesn't it make more sense to do up front?" Confirmed. Task 1f (docs/gen2/tasks/1f.md) builds the minimal compose slice and runs all four demonstrations with a pinned public runner CLI, using the supervisor's already-declared capability-probe responsibility for demonstration (d). Isolation rules: own compose project/ports/volumes, throwaway credentials only, gen-1 untouched. 1f dispatches after 1e-repair-2 lands (one coder on the tree). This resolves the 1e review's finding 1 by the demonstration route.

## 2026-09-28 — 1e-repair-2 re-review (Astra, xhigh) — BLOCK, narrow (one finding)
Full report: `~/work/research-loops-public/private/reviews/gen2-1e-repair-2-astra-review-20260928.md`.

**CLOSED:** recovery resumption (the original `os._exit(71)` reproduction now ends `resumed`/outcome `failed`, then `replayed`; one reconciliation, hold cleared, lease released, one allowance spent) and startup-log coverage. Findings 4/5/6/8 stay closed.

**Remaining (MEDIUM):** redaction runs before final serialization, so JSON escaping can reconstruct a configured token at the output boundary (backslash+quote reassembly; a token completed by the serializer's own opening quote; percent-encoded JSON escapes inside IDs decoded in layers). Required: the credential check must cover the actual serialized representation; unsafe IDs refused with a null ID before dispatch; emitted JSON stays valid.

**Routed:** `docs/gen2/tasks/1e-repair-3.md` (single finding) to an Opus 5.5 coder.

## 2026-09-28 — 1e-repair-3 re-review (Astra, xhigh, fresh session after a third filter stop) — BLOCK, one finding
Full report: `~/work/research-loops-public/private/reviews/gen2-1e-repair-3-astra-review-20260928.md`. All previous reproductions repaired; configuration rules verified to exclude whitespace from secrets (74 parser cases), so piece-wise scanning is sound.

**Remaining (MEDIUM, new):** the pre-dispatch piece-wise check and the later recursive whole-string check disagree at the 256-state decoding cap. A harmless ID with 272 combined states passes acceptance, executes, then returns `id: "[credential]"` — an accepted correlation ID changed after execution; two harmless seeded capability-fact strings likewise get an already-checked MCP tool document replaced whole, producing a success reply whose tool text isn't valid JSON. Not a secret disclosure — a correctness defect of the masking itself. Astra verified a one-line repair in a disposable tree (the later predicate scans the same pieces).

**Routed:** `docs/gen2/tasks/1e-repair-4.md` to an Opus 5.5 coder.

## 2026-09-28 — 1e-repair-4 re-review (Astra, xhigh) — **1e ACCEPTED, conditional only on task 1f** (5 review rounds)
Full report: `~/work/research-loops-public/private/reviews/gen2-1e-repair-4-astra-review-20260928.md`. Gates A/B/C all PASS.

**All four reproductions verified at HEAD in unmodified engine processes:** the 272-state ID echoed exactly with the cancellation recorded; the deeply-encoded status document intact over REST and MCP; the trailing-backslash ID refused up front with the store unchanged; the reply-matching secret answered by the exact fixed 500. Astra also **independently confirmed the coder's counter-evidence**: it rebuilt disposable trees with its own earlier one-line `auth.py` proposal (hash-matched) and reproduced both additional failures against it — the coder was right that it was insufficient, and both added guards are REQUIRED and ACCEPTED.

**1e totals:** 5 rounds (BLOCK 8 findings → 3 → narrow → narrow → ACCEPT). **The Phase 1→2 operator gate now contains exactly:** (1) task 1f's four pinned-runner deployment demonstrations; (2) the operator's Phase 1 acceptance and Phase 2 authorization (decision layer stays disabled/unqualified); (3) merge to main as a separate operator decision. The H-4 locator cleanup stays nonblocking.

## 2026-09-29 — 1f review (Astra, xhigh) — BLOCK on evidence repairs; the (d) decision stays with the operator, now on corrected facts
Full report: `~/work/research-loops-public/private/reviews/gen2-1f-astra-review-20260929.md`. Astra ran the demonstrations itself three times (two consecutive subset runs exit 0; the full run fails only at d2) on its own containers.

**Finding 1 (HIGH):** F1's premise overstated. The pinned CLIs' status commands really don't reject expired tokens (reproduced offline), **but locally declared expiry IS readable** — the fixtures' JWT `exp` claims decode to their declared expiries, and the other CLI exposes `expiresAt` directly. What remains truly offline-invisible is provider-side revocation and actual acceptance (reading a claim is not authentication; expired access tokens can coexist with usable refresh credentials; opaque credentials expose nothing). The evidence brief must present these distinctions before the operator decides (d). **Finding 2 (MEDIUM, Gate C):** demo (c)'s overlap oracle measures whole-probe windows and admits fully serial runner executions — REJECTED; needs process-level overlap evidence plus a serializing negative control. **Finding 3 (LOW):** the SIGKILL shutdown note is wrong (`init: true` → SIGTERM, exit 143, ~0.12 s); the exit-code shorthand (driver 1 vs make 2) corrected.

**Accepted:** (a), (b), (d1), the characterization, authority wiring, hygiene (no gen-1 contact, no token in kept files).

**Routed:** `docs/gen2/tasks/1f-repair.md` — fix the brief, extend the probe to read declared expiry offline (fact + hold, labeled as declared expiry), split (d2) into the now-demonstrable declared-expiry case and the honestly-residual revocation case, fix the oracle and doc claims. The §4(d) disposition remains the operator's.

## 2026-09-29: 1f-repair re-review (Astra, xhigh). **1f TECHNICALLY COMPLETE. All Phase 1 tasks (1a–1f) done.** (2 rounds)
Full report: `~/work/research-loops-public/private/reviews/gen2-1f-repair-astra-review-20260929.md`. Gates A/B/C all PASS.

**Findings 1–3 closed on Astra's own execution:** it decoded the fixtures independently (d2a declares expiry 2001-09-09; controls 2100-01-01; `alg: none` synthetic), ran the production probe with the baked runner under `--network none` (verdict `declared_expired`; empty-or-any API key takes precedence, matching the runner), audited the store by SQL (one dated `degraded` fact retaining `last_success_at`; a `capability` hold with operator authority, one-hour deadline, explicit remedy; recovery does not clear it; all 12 clearances across three runs bound to approved operator decisions; every copied DB passes integrity_check), and confirmed the concurrency oracle rejects serial schedules while `c-control` keeps failing the overlap assertion. `degraded` is ruled technically reasonable, with the mapping confirmed as part of the operator's (d) decision. F2–F4 stay disclosed, operator-routed.

**Final build accounting at 7d11b22:** 1,424 tests; 1,487/1,487 mutants (1,470 with paired controls); 16 schemas, 67 valid + 198 invalid fixtures; 41 STRICT tables; production 8,677/10,000 lines.

**The exact Phase 1→2 operator gate (Astra's words):** (1) decide §4(d) — how the demonstrated local rejection and declared-expiry fact/hold count, the `degraded` mapping, the refresh-presence policy, and the disposition of the unseen revocation/undeclared-expiry residual; (2) then accept Phase 1 and authorize Phase 2 (the complete single-topic workflow with the gateway observation/policy repairs; no model qualification or unattended authority); (3) merge to main as a separate operator decision.

**LOOP STOPPED AT THE PHASE 1→2 OPERATOR GATE.**

## 2026-09-29 — OPERATOR DECISIONS at the Phase 1→2 gate: §4(d) settled, Phase 1 ACCEPTED, Phase 2 AUTHORIZED
The operator accepted the orchestrator's recommendation ("That's fine. I accept. And go with phase 2").
1. **§4(d) amended** (DEPLOYMENT-CONTRACT §4, normative operator amendment): the offline scope — a runner-rejected credential and a credential whose declared expiry has passed — satisfies (d) for the Phase 1 gate; declared expiry is a `degraded` fact; refresh-token presence is recorded, never taken as proof of refreshability. The revoked/undeclared-expiry residual becomes a **binding requirement gating the first live provider execution** — which is Phase 2's live run, not Phase 3 (the orchestrator's recommendation had mislabeled it "Phase 3"; corrected same day to match the approved substance, 'before any live call', and flagged to the operator): a real invocation's authentication failure must record a dated `failing` fact + typed hold and end as a failure with evidence, never a zero-result pass — tested with the pinned runner against a genuinely rejected credential before any live call is admissible. An optional provider liveness check stays a later deployment choice.
2. **Phase 1 ACCEPTED** (1a–1f; 1e's condition on 1f now met).
3. **Phase 2 AUTHORIZED**: the complete single-topic workflow. The Phase 2 row begins "repair the gateway observations and policy boundary", and DEPLOYMENT-CONTRACT §3.4 says gateway code changes need the user's authorization — the orchestrator reads this Phase 2 authorization as covering gateway code changes **on the gen2 branch only**. The live gen-1 gateway runs from a separate clone (`~/work/staging/research-gateway-wt`, verified) and stays untouched; accepting any gateway release into live service remains the user's. The decision layer stays disabled/unqualified throughout Phase 2.

## 2026-09-29 — Phase 2 plan audit (Astra, xhigh, read-only) — PLAN NEEDS CHANGES; all 10 findings folded into the revised plan
Full report: `~/work/research-loops-public/private/reviews/gen2-phase2-plan-audit-astra-20260929.md`. Commissioned because the Phase 1 plan had missed DEPLOYMENT-CONTRACT §4's pre-Phase-1 prerequisite.

**No out-of-scope task found; the gaps were omissions and ambiguous breadth.** Six HIGH: (F1) live-execution isolation must precede real agents — now 2e1's preflight, with the §4(d) acceptance tightened so the invocation *ends failed with evidence*; (F2) 2b's full gateway repair set enumerated (attempt identity, full request identity, response-shape validation, server-side policy, licence/provenance, all eight §3.4 fixtures); (F3) S4–S7 research work unassigned — semantic assessments to 2c; checkpoints, facet audit, protected capacity, probes, the counterevidence challenge and fresh sufficiency review to 2e2; challenge evidence required by 2d's completion gates; (F4) 2a's bootstrap chain skipped scoping approval and the rating/successor cycle G-2 needs; (F5) the spend ceiling had no enforcement mechanism — now an explicit run-admission policy in 2e1; (F6) no phase-wide line budget. Four MEDIUM: bounded JSONL export (F7), the source-proposal route (F8), disposition/confidence reconciliation (F9), surveillance/scheduler/observability integration (F10).

**Budget forecast:** Astra estimates Phase 2 adds 2,450–4,100 engine lines → 11,127–12,777 against the 10,000 target / 12,000 hard ceiling (gateway-service changes count separately against the gateway baseline). Plan response: keep both figures, simplify first per Astra's list, per-task allocations with a net-growth check at each boundary, and the operator decides before any task that would breach 10,000 dispatches.

## 2026-09-29 — OPERATOR REQUEST: per-run usage metrics sufficient to estimate cadence cost (API and subscription share)
"I'd like to get to a point with usage where users could estimate usage both api and subscription (how much of their weekly plan) a specific cadence brings." Verified current state: the gateway records per-call latency and credits; the engine records invocations and attempts but **no model usage** (no tokens, model or cost). The plan had only a vague "usage including failures."

**Added to 2e1 (capture):** per-invocation-and-attempt usage records (provider/model/runner version, runner-reported tokens in/out/cached, provider-reported cost when available, wall time, correlated gateway calls and credits, kind/topic/cadence context). Before/after snapshots of each provider's subscription usage window through a generic per-provider reader, stored as account-wide context and never as per-run attribution. Unreported values are `unknown`, never zero. **Carried to Phase 3 (estimator):** cadence → API cost and plan-share ranges, calibrated from accumulated records; one Phase 2 run cannot calibrate it.

## 2026-09-29 — 2a review (Astra, xhigh) — BLOCK (Gates A + C); Gate B PASS
Full report: `~/work/research-loops-public/private/reviews/gen2-2a-astra-review-20260929.md`. Independent build matched (1,495 tests, 1587/1587); Astra rebuilt the whole chain with its own script (no coder test reused) and seven mutants by hand — all killed. Budget independently confirmed: 8,677 → 9,060 (+383).

**Findings (all reproduced):** F1 HIGH — a materially superseded brief still authorizes the scoping and contract hand-offs; F2 HIGH — checkpoint closure is fenced by timestamps, not bound to the episode it was admitted to review; F3 MEDIUM — method-design provenance joins two unrelated facts (the artifact's first stager); F4 MEDIUM — the "newest report" is inferred from wall time and per-report version.

**Rulings on the seven choices:** 1–5 ACCEPT (template registry in the bundle; router-only referential checks; rejected scope → rework; fixture scaffolding; in-place `/1` outcome sections for the undeployed baseline only); 6 — checkpoint-closure fence REJECTED (F2), the rest ACCEPT; 7 — INVARIANTS locator updates AUTHORIZED (G-4, G-12, C-12, G-13, E-3), locator-only. The 2e operator-surface command list ruled complete. **Routed:** `docs/gen2/tasks/2a-repair.md`.

## 2026-09-29 — 2a-repair re-review (Astra, xhigh) — BLOCK, narrow (F1-R)
Full report: `~/work/research-loops-public/private/reviews/gen2-2a-repair-astra-review-20260929.md`. F1's bootstrap reproductions and F2–F4 pass. **Remaining F1-R (HIGH):** the post-approval blanket exemption lets an amendment keep a materially replaced brief as its basis — reproduced in both timings through the router, approved as `compatible` while r2-pinned work kept committing; 1d's impact machinery does not cover it. **Rulings:** the first-approval-only exemption REJECTED as a blanket rule (its archive-then-amend motivation ACCEPTED); the automatic return to scoping ACCEPTED; both stated limits (F2 unbound episode; F3 crash-not-kill mutant) ACCEPTED. **Routed:** `docs/gen2/tasks/2a-repair-2.md`.

**Resource alert:** the Codex weekly window (which Astra's reviews consume) went from 16% (2026-09-28 17:32) to 80% (2026-09-29 18:35), resets in ~4 days. Escalated to the operator before the next Astra dispatch.

**2026-09-29 correction:** the Codex resource alert above was wrong. The orchestrator attributed the whole account-wide window movement to Astra, but the operator runs parallel work loops on the same account, reads more than 40% remaining, and has 3 resets available. The hold was lifted, and the loop resumed with the 2a-repair-2 re-review.

## 2026-09-29 — OPERATOR RULING: size rules replaced
"Idk where the 10K total lines of code came from. I know I stipulated a 1.5K lines per file rule." Traced: the 10,000/12,000 figures came from the Sep-22 design review's §10, which offers them as a *proposed* planning allocation ("not effort estimates or proof of feasibility"). The orchestrator copied them into the build charter as a binding rule without asking. The user's per-file rule was not recorded in any gen-2 document. **Ruling:** (1) no hand-written file over 1,500 lines, enforced, with the existing oversized files refactored while preserving boundaries and behavior; (2) 15,000 total production lines becomes a growth-review trigger ("at that point we'll want to look at what made it grow"). Charter updated. The earlier budget alert is withdrawn. Oversized files today: `tools/gen2_mutations.py` (5,093), `gen2/store/schema.sql` (3,274), `gen2/tests/test_store_ddl.py` (2,891), plus the generated `tools/gen2_mutation_controls.json` (10,514; exempted by reasoned allowlist, pending objection). Queued as task 2r, before 2b.

## 2026-09-29 — 2a-repair-2 re-review (Astra, xhigh) — BLOCK, narrow (F1-R continued)
Full report: `~/work/research-loops-public/private/reviews/gen2-2a-repair-2-astra-review-20260929.md`. The two earlier F1-R timings now refuse. **Remaining:** archiving a confirmed replacement brief that has a *different* brief ID restores permission to amend under the obsolete original, because the supersession check reconstructs history filtered by brief ID. Six failing cases in a 26-case matrix, with a minimal router-only regression (four tests fail by assertion). The locator-only update at C-12/G-4 is AUTHORIZED.

**Orchestrator routing decision:** this is the third round of the same defect family, so 2a-repair-3 replaces the history reconstruction with a durable, monotonic supersession fact written at brief-confirmation time and cleared only by incorporation through reframe approval (the lesson from 1c's retry chokepoint). 2r follows it.

## 2026-09-30 — 2a-repair-3 re-review (Astra, xhigh) — **2a ACCEPTED** (5 review rounds)
Full report: `~/work/research-loops-public/private/reviews/gen2-2a-repair-3-astra-review-20260929.md`. Gates A/B/C all PASS. Scope corrected mid-review to include the coder's fourth commit `ed69e70`, which the orchestrator had left out of the scope list; Astra asked rather than assume.

**The F1 family is closed structurally.** Replacements are recorded in the same transaction as the confirming decision, across every brief ID, and are never overwritten. The post-approval check reads that record at proposal and at approval, and neither archival nor later confirmations can remove it. Incorporation through a reframe changes the contract's basis without erasing the old record. Astra's scripts, byte-identical: 26/26 expected outcomes (the six previously failing cross-ID cases now refuse, and all 20 reframe controls pass), cross-brief regression 4/4, history controls pass. Fresh sequences (reversions, chains, concurrent approval) found no counterexample.

**2a totals:** 5 rounds (BLOCK F1–F4 → F1-R → F1-R continued → structural fix → ACCEPT). Production 9,111 lines.

## 2026-09-30 — Investigation: why gen-1's fleet is idle (operator-requested, read-only)
Traced via topic-folder mtimes and the host journal. **Every gen-1 topic's files stopped updating within minutes of 2026-09-12 20:43:49 UTC.** The journal shows the operator ran `sudo systemctl stop research-loops-station@1..5` at that exact timestamp — a deliberate, explicit shutdown, not a crash, OOM or hang. The controller service is still active and would resume dispatching the moment the station units restart; nothing was lost. Two in-flight attempt logs (agent-run-businesses #25, in verification) end in back-to-back `Terminated` lines consistent with the station stop tearing down their process groups mid-step. The queue's `revision: 10042` has been static since at least 2026-09-26, consistent with an idle fleet.

## 2026-09-30 — OPERATOR RULING: the Phase 2 live-run topic is a fresh intake, not gen-1's queue
The operator rejected using gen-1's existing (stale) queue for gen-2's Phase 2f live run: "We need to pick ONE topic and go through the initial process and everything to make sure it works properly with a fucking queue." Confirmed: Phase 2f uses one fresh topic through the real gen-2 S1 intake conversation, once task 2e lands — not an import of gen-1 state. This does not change the Phase 4 migration plan (gen-1's history is still imported then, under the reconciled-import design), only 2f's proving run.

**Draft topic prepared:** `docs/gen2/PHASE2-TOPIC-DRAFT.md` — research frameworks/methodologies for translating research findings into product/system design decisions (survey/dossier only, no playbook; product/system design broadly, not software-only — operator's explicit choices). Marked DRAFT: it is input for the real S1 conversation at 2f, not an actual intake, since real executors (2e) don't exist yet. No router operation was invoked; nothing is committed to any store.

## 2026-09-30 — 2r review (Astra, xhigh) — **ACCEPTED, first round**
Full report: `~/work/research-loops-public/private/reviews/gen2-2r-astra-review-20260930.md`. Gates A/B/C all PASS.

**DDL split independently proven equivalent:** the four parts concatenate to the exact original bytes (194,578 bytes, matching SHA-256), and the resulting database is structurally identical across five construction paths (original SQL, the four parts run separately, their concatenation, and the real `db.connect` path) — same 44 tables, 77 indexes, 172 triggers, 1 view, 294 rows, `user_version=1`, compared on all five `sqlite_master` columns including exact SQL text, not just counts. The `order.txt` loader was independently attacked (reversed order, missing part, unlisted file) and behaves correctly in each case.

**Boundary conformance confirmed** (same module edges before/after; only the router touches store-write primitives; router/supervisor/importer byte-identical) and **no stale reader of the old single-file path remains** anywhere in the repo. Astra went beyond the task and built the actual scoped Docker image (disabled networking, declared UID): it loads the split parts and produces the identical database inside the real deployment container.

**2r totals:** 1 review round. Gen-2's size rule (1,500 lines/file, 15,000-line growth trigger) is now enforced by `make gen2-check`, not just documented. Production 9,125/15,000.

## 2026-09-30 — 2b landed (coder 286eff36), orchestrator independent verification — GREEN, sent to Astra
13 commits (`gen2 2b:` prefix) since the 2r tip. Coder's self-report: all six acceptance items done, gateway `core/request_identity.py` added, server-side signed/expiring policy grants, licence/freshness/provenance split into four distinct facts, all eight DEPLOYMENT-CONTRACT §3.4 fixtures executable against a fake Vault, engine-side `gen2/gateway_client` built and tested.

**Orchestrator independently re-ran, not trusted from the coder's log:** `git status --short` clean on the working tree; `make gen2-check` unpiped exit 0, 1,582 tests OK (2 skipped), 1,651/1,651 mutants killed, 9,521 production lines in 31 files. **Live gen-1 gateway boundary re-fingerprinted separately:** `~/work/staging/research-gateway-wt/gateway` clean, HEAD still `f4a7a5c6108d90fd4afd2fa2e1b8164381e0c279` (unchanged), `research-gateway.service` still active — the live deployment was not touched.

Astra dispatched for Gate A/B/C review, task file `~/work/research-loops-public/private/reviews/gen2-2b-review-task-20260930.md`. Explicitly asked to independently re-verify the gen-1-boundary claim itself rather than trust the coder's or orchestrator's fingerprint, and to rebuild several of the eight §3.4 fixtures and the request-identity collision fix from scratch.

## 2026-09-30 — 2b review (Astra, xhigh) — **BLOCK** (Gate A + C; Gate B PASS)
Full report: `~/work/research-loops-public/private/reviews/gen2-2b-astra-review-20260930.md`. **The live gen-1 gateway boundary held**, independently re-fingerprinted (HEAD `f4a7a5c6` unchanged, clean tree, SHA-256 tree hash, service PID unchanged and uninterrupted since 2026-09-26, no lifecycle events in the journal across the whole task window, rechecked again at review end). `make gen2-check` exit 0 (1,582 tests, 1,651/1,651 mutants), `make gen2-gateway` exit 0 (57/57 gateway mutants) both independently re-run by Astra, unpiped.

**8 findings, all real defects, not test-only or process nitpicks — 5 HIGH, 3 MEDIUM:**
- **A1 (HIGH):** degraded/uncaptured gateway answers (empty lanes with no records field, `metadata_only`, `capture_loss`) become complete zero-result observations instead of a distinct degraded state — violates RG-4.
- **A2 (HIGH):** engine request identity is built from the gateway's *echo*, so a timeout/refusal with no echo collapses two genuinely different requests into one observation (H-1/H-5 violation), while `delivery` mode changes (cache vs. dispatched) wrongly split one identical request into two recorded observations. Pagination loses the actual failed cursor per page.
- **A3 (HIGH):** a persisted restrictive redistribution fact (`prohibited`) reverts to `permitted` on reload/reannotate; a metadata licence override can override a content licence; link-only responses are mislabeled as delivered content.
- **A4 (HIGH):** malformed individual members (not just malformed containers) produce fabricated identities (`url:None`) or discard valid sibling records entirely instead of a partial lower bound.
- **A5 (HIGH):** both correlation headers absent is still accepted (contradicts the two-required-headers claim); job polling doesn't bind to the caller's own invocation, letting one invocation read another's job under the creator's identity; the station HTTP client drops the download attribution header.
- **A6 (MEDIUM):** fixture 5's engine half is test-only SQL insertion, not a real router ingestion path.
- **A7 (MEDIUM):** Vault reads don't require HTTP 200 — a 201 with a valid body is accepted as a successful read.
- **A8 (MEDIUM, boundary-drift):** the size checker's `SURFACE_PREFIXES` excludes `gateway/` entirely, so per-file enforcement doesn't actually cover gateway code (no file is currently oversized — pure enforcement gap).

Line accounting, mutation counts, and the Phase 3 scope boundary (breaker/budget/SIGTERM untouched) were all independently confirmed correct. Gate B passes outright — no research-effectiveness claim introduced.

**Orchestrator routing decision:** dispatched to a fresh Opus 5.5 coder as task 2b-repair (`docs/gen2/tasks/2b-repair.md`), covering A1–A8 with Astra's required repairs verbatim.

## 2026-09-30 — 2b-repair landed (coder fa1a0b3b), orchestrator independent verification GREEN, sent to Astra
9 commits since the BLOCK verdict. Coder's self-report: all eight findings closed (see task file for per-item detail); notably A2's fix replaces the merged multi-page observation with one observation per page (revises 4 previously-accepted tests: 106, 107, 127, 128), and A5 enforces the correlation pair with **no maintenance-door exemption**, since none was granted — the coder flagged this explicitly as a decision worth Astra's attention, not something it decided quietly.

**Orchestrator independently re-ran, not trusted from the coder's log:** 9 commits confirmed (`e7856a9..HEAD`), clean working tree. `make gen2-check` unpiped exit 0: 1,601 tests OK, 1,674/1,674 mutants killed. `make gen2-gateway` unpiped exit 0: 385 tests OK (with and without database), 74/74 gateway mutants killed — matches the coder's claims exactly. **Live gen-1 gateway boundary re-fingerprinted again:** HEAD still `f4a7a5c6`, PID 1456514 unchanged, 0 restarts, active since 2026-09-26 — untouched through this repair too.

Astra dispatched for re-review, task file `~/work/research-loops-public/private/reviews/gen2-2b-repair-review-task-20260930.md`. Asked to re-run its original reproductions against each of A1–A8, give an explicit opinion on whether A5's no-exemption default should instead be an operator decision, and re-confirm the gen-1 boundary itself rather than trust either report.

## 2026-09-30 — 2b-repair re-review (Astra, xhigh) — **BLOCK, narrow** (A1/A2/A4/A5/A7/A8 CLOSED)
Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-astra-review-20260930.md`. Live gen-1 gateway boundary re-confirmed untouched a third time (same HEAD, PID, 0 restarts). `make gen2-check` and `make gen2-gateway` both independently re-run, exit 0, matching the orchestrator's own numbers exactly. Gate B PASS.

**6 of 8 original findings are now genuinely closed: A1, A2, A4, A5, A7, A8.** Astra also explicitly ruled on the operational question the coder flagged: enforcing correlation with no maintenance exemption (A5) is "the literal, defensible reading" of the repair brief and **needs no blocking operator decision** — settled, not escalated.

**2 new findings, both narrower than the original 8:**
- **R1 (HIGH):** the A3 persistence fix only repairs legacy rows written *without* provenance — it misses the rows task 2b's own (pre-repair) writer actually produced, which have provenance summaries but are missing the input flags needed to reconstruct restrictions. A real pre-repair Crossref `prohibited` record still reloads as `permitted`; a real pre-repair FRED third-party-restricted record still reloads as `commercial_use`. The restrictive data is still in the stored summary — the reader just isn't looking at it correctly for this exact case.
- **R2 (MEDIUM):** a single ongoing Vault outage that legitimately widens (a second lane starts failing under the same onset/episode) gets refused as `fact_conflict` by the new `record_gateway_facts` command, because the fact ID doesn't distinguish "same outage, updated snapshot" from "a genuinely different fact." A caller can end up persisting an observation against a stale, pre-widening snapshot.

**Orchestrator routing decision:** dispatched to a fresh Opus 5.5 coder as task 2b-repair-2 (`docs/gen2/tasks/2b-repair-2.md`), covering only R1 and R2.

## 2026-09-30 — 2b-repair-2 landed (coder 8f0c3df4), orchestrator independent verification GREEN, sent to Astra
3 commits closing R1 and R2. R1: a marker column distinguishes rows the current writer stored from older rows; old rows have restrictions reconstructed per-member from their own stored facts. Coder flags one conservative tradeoff worth Astra's judgment: an old row's stored `personal_use` is always treated as third-party-restricted, which never widens permission but can occasionally over-restrict if the original cause wasn't third-party terms. R2: each gateway fact is now a snapshot of an outage (capability+state+start time identifies the outage; detail/lanes/last-success are the mutable snapshot), with every snapshot retained and the start time preserved. Coder discloses a known residual: snapshots carry no timestamp, so out-of-order recording could briefly show a stale snapshot as current — flagged explicitly, not hidden.

**Orchestrator independently re-ran:** 3 commits confirmed (`ce97fa5..HEAD`), clean tree. `make gen2-check` unpiped exit 0: 1,604 tests OK, 1,677/1,677 mutants. `make gen2-gateway` unpiped exit 0: 391 tests OK (with/without database), 79/79 gateway mutants — matches the coder's claims exactly. **Live gen-1 gateway boundary re-fingerprinted a fourth time:** unchanged.

Astra dispatched for re-review, task file `~/work/research-loops-public/private/reviews/gen2-2b-repair-2-review-task-20260930.md`. Asked to judge both disclosed tradeoffs on their merits (not just confirm the reproductions pass), spot-check A3/A6 for regression, and re-confirm the gen-1 boundary. If this closes, 2b as a whole is accepted.

## 2026-09-30 — 2b-repair-2 re-review (Astra, xhigh) — **BLOCK, narrower still** (R1 CLOSED)
Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-2-astra-review-20260930.md`. Live gen-1 gateway boundary re-confirmed untouched a fifth time. `make gen2-check`/`make gen2-gateway` both independently re-run, exit 0, matching the orchestrator's numbers exactly. Gate B PASS.

**R1 is CLOSED** — Astra independently reproduced the actual pre-repair writer's output across 5 cases (prohibited/third-party/lead/non-lead/unrestricted) and confirmed restrictions survive the upgrade correctly. Astra also explicitly evaluated the disclosed conservative-labeling tradeoff (an old Semantic-Scholar-only `personal_use` member can acquire an inferred `third_party_restricted` flag it may not have literally earned) and ruled it acceptable: the repair brief expressly permits conservative reconstruction, direction is never permission-widening, and it needs no separate finding.

**R2 turned out to be a real, persistent defect, not the "brief" residual the coder disclosed.** Astra's independent reproduction shows the engine's *current* status fact — not just history, which is fine — can get stuck stale **indefinitely**: (1) a genuine two-process race where a delayed narrower snapshot overwrites a correctly-recorded wider one and never self-corrects even after reconfirmation, and (2) a fully sequential, no-race case where a failure detail *returns* to a value seen earlier in the same outage — the router treats that recurrence as a pure replay (by content hash) and leaves stale, older content as current, even though the new read is objectively the most recent information. Every affected historical observation still links correctly and stays non-evidentiary (no false zero-results, no permission widening) — only the status surface's "current" notion is wrong.

**Orchestrator routing decision:** dispatched to a fresh Opus 5.5 coder as task 2b-repair-3 (`docs/gen2/tasks/2b-repair-3.md`), covering only R2's remaining current-snapshot staleness, using Astra's two exact reproductions as the required regression tests.

## 2026-09-30 — OPERATOR RULING: Gate D, architecture metrics, and no patches
The operator asked whether the build checks architecture against the requirements and the architecture document, and asked for an architectural complexity check alongside boundaries plus a rule against patches. **Orchestrator's answer: only partly.** Gate A reviews each task's diff against the flow doc and BOUNDARIES.md, and the boundary checker enforces the declared module graph. But nothing has ever reviewed the whole built system against the flow doc, and nothing measures complexity beyond the file-size rules. A scan of gen-2 production code found no self-admitted patch markers. The real risk is patches that don't label themselves, and 2b has already had two: 2b-repair-2's disclosed "known limit" (a real defect written down as documentation), and 2b-repair-3's relaxation of an accepted 0a store rule.

**Rulings (charter updated):** (1) **Gate D**, a whole-system architecture/traceability/complexity review, runs when a task is fully accepted and at each phase end; (2) **architecture metrics** in `make gen2-check`, stdlib-only and ratcheted; (3) **root-cause fixes only**: every correction is classified ROOT-CAUSE or MITIGATION, a mitigation always blocks and escalates, only the operator can accept one, and accepted ones go to `DEBT-REGISTER.md` with an owning phase; (4) sequencing: the tooling is built as task 2q after 2b is accepted, then the first Gate D covers everything built so far, and 2c waits for it. The pending 2b-repair-3 review brief now requires the root-cause/mitigation classification across all four 2b rounds.

**2b-repair-3 landed (coder ddfb039d), orchestrator verification GREEN.** 2 commits. The gateway numbers each change to its secrets-outage snapshot (a revision); the router orders an episode's snapshots by revision, not arrival. A late lower-revision snapshot is kept behind the current one for its own observation, a recurrence of earlier contents gets a new revision and becomes current, and an unchanged repeat replays. This relaxes 0a's A9 store rule so a late snapshot can be inserted behind the current fact; the coder flagged it as the main thing to review. Orchestrator reran both targets unpiped: `make gen2-check` exit 0 (1,609 tests, 1,687/1,687 mutants), `make gen2-gateway` exit 0 (395 tests with and without a database, 82/82 mutants). Gen-1 boundary unchanged. Sent to a fresh Astra with three specific checks (the A9 relaxation, whether revision numbering survives a gateway restart, and the coder's overwrite of Astra's prior `probes.json`) plus the root-cause/mitigation classification of every 2b fix.

**2b-repair-3 re-review (Astra, xhigh) — BLOCK on two MITIGATIONS; escalated to the operator.** Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-3-astra-review-20260930.md`. Gen-1 boundary held (sixth independent check). Both suites exit 0. Gate B PASS. R2's two current-status reproductions are fixed within one gateway lifetime. First root-cause classification of every 2b correction: 15 ROOT-CAUSE and 2 MITIGATION.
- **F1 (MEDIUM, MITIGATION):** the relaxed A9 store rule is enforced in the DDL only for graph shape, not meaning. Direct SQL can store a fact behind the current one from another episode, with a different state, a higher or equal revision, or no revision; the router's normal path blocks these, but the database contract no longer does. Required: enforce the exact late-snapshot relation in DDL, with negative tests.
- **F2 (MEDIUM, MITIGATION):** R1's legacy-row handling reinterprets old rows at read time and never converts them, with no completion check or removal condition. Required: a bounded, idempotent migration with verifiable completion and a removal condition for the legacy read path, or operator acceptance.
- **Revision lifetime (Phase 3, not a 2b blocker):** the revision counter lives in gateway process memory, so a restart within the same second, or two gateway processes, can reproduce stale current status. Astra assigned it to Phase 3's gateway lifecycle work, a named owner. The coder's "Remaining: NONE" did not disclose this limit.
- **Gate C:** 14 ACCEPT, 1 REJECT (the new DDL test never isolates the late-snapshot eligibility conditions).

**Orchestrator routing:** under the charter's root-cause rule only the operator can accept a mitigation. Both are escalated with a recommendation to repair.

**OPERATOR RULING:** fix both properly; neither is accepted as debt. F1: the DDL enforces the exact late-snapshot relation, or the design changes so late snapshots never enter the supersession graph (fourth correction in this family, so the third-round redesign rule applies). F2: a bounded, idempotent migration with a zero-unconverted-rows completion check, then the legacy read path is deleted and the gateway refuses to serve unconverted rows; inferred restrictions are labelled as inferred. The migration runs only on disposable databases until a release the operator approves. Dispatched as 2b-repair-4.

**2b-repair-4 landed (coder a94bac98), orchestrator verification GREEN.** `bd13e76` (F2): an idempotent migration with a zero-unconverted completion check, the read-time rebuild deleted, the gateway refuses to start on unconverted rows, and unknown-cause personal use stored as `inferred_personal_use`. `9621690` (F1): the DDL admits a late snapshot only as the same gateway capability, episode and state at a strictly lower revision, with one snapshot per revision. The coder declined the optional redesign and gave its reasons. **New finding by the coder:** the live gen-1 writer's (`f4a7a5c`) rows would have been widened by the pre-fix reader (lead prohibition read as permitted, FRED third-party terms as commercial use); the migration now covers them. The coder read that writer from git history, not the live checkout. Remaining items are disclosed with proposed owners: the real-data migration run and stopping older gateways before it (Phase 4), and gen-1's unrecorded non-lead member restrictions (Phase 4, needs operator confirmation). Orchestrator reran both targets unpiped: `make gen2-check` exit 0 (1,610 tests, 1,692/1,692 mutants), `make gen2-gateway` exit 0 (401+401 tests, 92/92 mutants). Gen-1 boundary unchanged. Sent to a fresh Astra, which is also to reproduce the `f4a7a5c` finding and classify each remaining item.

**2b-repair-4 re-review (Astra, xhigh) — BLOCK.** Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-4-astra-review-20260930.md`. Gen-1 boundary held (seventh independent check). Both suites exit 0. Gate B PASS. Gate C: 13 ACCEPT, 1 REJECT.
- **F1:** the late-insert predicate is ROOT-CAUSE and closes the earlier REJECT. But an ordinary supersession transaction (point current C at a not-yet-inserted N, then insert N) can make an older revision current, and also accepts a NULL revision, a different state at the same onset, and an older episode. F1 as a whole stays MITIGATION.
- **F2:** the migration, the inferred-restriction input and the startup refusal are ROOT-CAUSE. The migration was independently exercised across interruption, batching and concurrent arrival. But the local-index adapter reads `gateway.records` directly, so an unconverted row written after startup is served as a complete result through HTTP, HTTP MCP, stdio and queued jobs, with widened permissions when the row is restricted. F2 as a whole stays MITIGATION.
- **The coder's `f4a7a5c` finding is independently reproduced:** the pre-fix reader widened that writer's lead restrictions, and the migration preserves them.
- **Remaining-item classification:** (a) the real-data migration run and (b) stopping and fencing all old writers at cutover are legitimate Phase 4 release steps. (c) Gen-1's lost non-lead restrictions are an inherited gen-1 gap, not a 2b mitigation. The root-cause option is to purge regenerable affected cache rows and refetch; carrying them forward as if preserved would be a mitigation needing operator acceptance.

**Orchestrator routing:** the operator's standing ruling (fix both properly) covers the incomplete fixes, so repair goes straight to 2b-repair-5 without a new escalation. Round six, with the same "rule on one path" shape twice, so the brief requires enforcement at the single chokepoint: F1 validates every supersession edge; F2 routes every serving read through one servable-records gate, with a check against bypass. The three Phase 4 release decisions go to the operator.

**OPERATOR RULINGS on the Phase 4 release items:** (a) the real-data migration is Phase 4, run only on the operator's approval; (b) the procedure for stopping every old writer will be decided when Phase 4 arrives ("Can we address this when we're there"), and it is recorded as a Phase 4 item so it can't be dropped; (c) gen-1's lost non-lead restrictions: purge and refetch. Recorded in BUILD-STATE.md under "Phase 4 release items".

**2b-repair-5 landed (coder b72fcc42).** `09cd02d` (F1): every gateway supersession edge records its successor's since/state/revision; a named CHECK holds each edge to one relation (the same episode at a strictly higher revision, or a later episode), and a deferred foreign key confirms at COMMIT that the recorded details match the actual successor. Gateway facts now require a revision and an orderable timestamp form. `b3ea91a` (F2): a `gateway.servable_records` view is the single read gate (unconverted rows expose identity only); the cache, the local index's results and counts, and the startup count all read through it. A withheld match makes the lane partial, or unavailable if nothing servable matched. `tests/test_record_gate.py` fails on any production read of `gateway.records` outside six named non-serving uses. An assembled regression covers HTTP, HTTP MCP, queued jobs and stdio MCP. Coder-disclosed items for Astra: the gate test reads SQL text, so dynamically built table names would escape it (a view-only database role would be stronger; unowned); and, from reading the code, the local-index lane never returns a continuation, so results beyond `limit` are reported as exhausted. Orchestrator reran both targets unpiped: `make gen2-check` exit 0 (1,614 tests, 1,701/1,701 mutants), `make gen2-gateway` exit 0 (407+407 tests, 95/95 mutants). Gen-1 boundary unchanged. Sent to a fresh Astra, which is also asked to reproduce or refute the exhaustion defect and to judge the gate test's dynamic-SQL gap.

**2b-repair-5 re-review (Astra, xhigh) — BLOCK on one new defect; F1 and F2 ACCEPTED.** Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-5-astra-review-20260930.md`. Gen-1 boundary held (eighth independent check). Both suites exit 0. Gate B PASS. Gate C: all 12 new or changed tests ACCEPT.
- **F1 ROOT-CAUSE, closed:** ordering is a property of the edge; one CHECK plus a composite deferred FK resisted every tested SQL form.
- **F2 ROOT-CAUSE, closed:** every current serving read and count goes through the view. The source-level check is adequate for the audited code but is not runtime access control. Database privilege separation is assigned to Phase 4 deployment qualification and recorded under BUILD-STATE's Phase 4 release items.
- **F3 (MEDIUM, BLOCK):** the coder-noticed local-index defect is real. A bounded result is reported `complete`/`exhausted`, the continuation skips the remaining matches, and this reproduces on HTTP, HTTP MCP, queued jobs and stdio, while the engine client stops after one page. Root cause: a missing cursor is treated as proof of exhaustion. This violates STATION-CONTRACT §2 and RG-4, and is 2b's responsibility. Deferring it would be a mitigation needing operator acceptance.

**Orchestrator routing:** no operator decision is needed; repair dispatched as 2b-repair-6. The brief requires exhaustion to be asserted only on an adapter's positive report, never inferred from a missing cursor, so no adapter can produce it.

**2b-repair-6 landed (coder 31e6d85f).** 3 commits. Exhaustion is decided in one place, only on an adapter's own end report; a page without one becomes `partial`/`partial_pagination`, uncached and without the skip sentinel. All 13 find adapters are under the rule. The local index pages by offset. Crossref now requests a cursor from page 1: the coder found it had the same false-exhaustion bug on its first page. Remaining limitations disclosed with proposed owners, sent to Astra to classify: offset paging under index churn (Phase 3, unassigned), unverified provider end signals (Phase 4 canary), withheld rows halting paging (ends at the Phase 4 migration), and provider result caps reported as lower bounds (no owner). The completion block's "Remaining: NONE" contradicts that list. **Process slip, disclosed by the coder:** three read-only live Crossref requests carried the operator's email in Crossref's `mailto` contact field. The orchestrator confirmed the email is in no tracked file. Future briefs forbid personal data in any live call.

**2b-repair-6 re-review (Astra, xhigh) — BLOCK.** Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-6-astra-review-20261001.md`. Gen-1 boundary held (ninth independent check). Both suites exit 0. Gate B PASS. No committed fixture or test holds the operator's email or needs live access.
- **F3's shared router decision is ROOT-CAUSE**, and the stationary reproduction is fixed on all four doors.
- **F3-R1 (MEDIUM, BLOCK):** the coder's limitation #1 reproduced. Removing an already-read row between pages skips a still-matching row, and the lane is still declared exhausted. A Phase 3 deferral would be a mitigation.
- **F3-R2 (MEDIUM, BLOCK):** the Hugging Face adapter invents numeric offsets and ignores the official client's `Link: rel="next"` protocol, so it falsely exhausts a short page that has a next link.
- **Adapter audit:** most end rules rest on assumed provider behaviour, not primary evidence. 2b must ground them now; Phase 4 owns live canary qualification (recorded).
- **Pre-existing defect:** a Socrata malformed-member case loses the whole page (identical on `d7cd61b`, not a regression).
- **Limitation rulings:** #3 owned by Phase 4; #4 provider caps reported as lower bounds is ROOT-CAUSE. The completion block's "Remaining: NONE" is rejected.

**Orchestrator routing:** dispatched as 2b-repair-7 under the standing fix-properly ruling, with the Socrata defect folded in so it isn't left unowned.

**2026-10-01 — host reboot mid-task (operator doubled the disk).** The 2b-repair-7 Opus coder had committed `ef39cd6`..`cadd62e` and was on its final checks when the operator paused it; the reboot then closed its session and wiped `/tmp`, losing its raw provider captures and the prior Astra review's probe files. `PROVIDER-PAGINATION.md`, with its quoted sources, is committed and intact. **The reboot restarted the live gen-1 gateway:** new PID 1040, active since 2026-10-01 04:26:25 UTC, journal stop/start entries 04:23–04:26 lining up with the shutdown and boot. HEAD `f4a7a5c` and the clean tree are unchanged. The build did not cause the restart, and the next boundary check rebaselines on the new PID. The previous coder's log names three unowned findings: OpenCitations enrich loses a whole answer on one malformed row (A4-class, the second adapter after Socrata); the OpenAIRE adapter uses a deprecated endpoint version slated for removal; Kaggle's official client no longer uses the adapter's listing endpoint. **Routing:** coding moves to Sonnet 5.5 (operator, 2026-10-01). 2b-repair-7b restores the evidence under a durable directory, fixes the OpenCitations defect at the shared member-decoding chokepoint, runs the final checks and writes the report; the OpenAIRE and Kaggle items go to Astra for classification. New charter rule: evidence lives under `private/evidence/`, never only in `/tmp`.

**2b-repair-7b landed (Sonnet 5.5 coder e6c24611).** 6 commits. Provider evidence re-captured to `private/evidence/2b-repair-7/`: 45 captures with a manifest, and all 48 excerpts in `PROVIDER-PAGINATION.md` checked against them. **Malformed-member defect fixed once, at the chokepoint:** every provider list becomes records only through `base.members()` or `first_member()`, and a test fails on any adapter building records in its own loop. Before the change a probe found nine record-producing paths that lost a whole answer on one non-object member; all are changed. The report gives root causes for all 13 2b-repair-7 commits. **Remaining, with proposed owners (operator to accept or reassign):** (1) OpenAIRE adapter on an endpoint version marked deprecated and slated for removal; (2) Kaggle's official client has moved to a different listing API than the adapter uses; (3) catalogue answers (bls/fred/census/bea, ECB envelope) lost whole on one non-object entry, failing closed. The coder asks whether fetching five specification documents from provider API hosts counts as live calls. Sent to Astra with the reboot boundary rebaseline.

**2b-repair-7 re-review (Astra, xhigh) — BLOCK.** Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-7-astra-review-20261001.md`; evidence in `private/evidence/astra-2b-repair-7/`. Boundary rebaselined to PID 1040: the reboot-driven restart was independently confirmed from `/proc/stat` and the journal, and nothing since. Gate B PASS. Gate C: 77 ACCEPT; the structural bypass test is REJECTed.
- **ROOT-CAUSE, closed:** F3-R1 (the continuation carries a population digest; a changed population yields unavailable with no end); the provider evidence (all 45 hashes and 48 excerpts re-verified); the individual adapter decoder conversions. The five spec documents fetched from provider API hosts were within the documentation allowance.
- **R7-1 (MEDIUM, BLOCK):** the `Link` parser splits inside quoted parameters, so the HF relation is lost and the lane claims exhaustion.
- **R7-2 (MEDIUM, BLOCK):** one-decoder not established. HF siblings and ECB datasets still lose readable records; OpenCitations metadata reads `rows[0]`; the AST name scan misses filter comprehensions, `while`, aliases, `rows[0]` and helpers outside `adapters/`.
- **Unowned items, not blocking 2b:** OpenAIRE deprecation and Kaggle endpoint drift → proposed Phase 3 adapter-compatibility task before Phase 4 qualification; catalogue partial results → proposed Phase 3 enhancement if commissioned. The ECB data envelope is not a catalogue and is folded into R7-2.

**Orchestrator routing:** this is the third round of the malformed-member family (Socrata → OpenCitations/8 paths → HF/ECB), so 2b-repair-8 requires a structural redesign: raw provider lists can't be iterated except through isolation. Dispatched to Sonnet 5.5. Owner decisions sent to the operator. **OPERATOR RULINGS:** OpenAIRE deprecation and Kaggle endpoint drift → a Phase 3 gateway adapter-compatibility task, finished before Phase 4 qualification; catalogue partial results → commissioned for Phase 3. Recorded in BUILD-STATE under "Phase 3 items".

**2b-repair-8 landed (Sonnet 5.5 coder 130b5b23), orchestrator verify GREEN** (gen2-check exit 0, 1,615 tests, 1,701/1,701 mutants; gen2-gateway exit 0, 525+525 tests, 164/164 mutants).

**2b-repair-8 re-review (Astra, xhigh) — BLOCK, narrower.** Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-8-astra-review-20261001.md`; evidence in `private/evidence/astra-2b-repair-8/`. Boundary PASS at PID 1040. Gate B PASS.
- **ROOT-CAUSE, accepted:** the runtime view redesign (provider lists can't be iterated, only decoded per member), every original R7 reproduction, all 68 escape uses at 36 locations audited as honest, and every disclosed behaviour change and scope limit (SDMX-ML confirmed inside A4 and correct; the OpenAlex snapshot loader is offline ingestion outside the lane contract).
- **R8-1 (BLOCK):** decoded `rel` values aren't validated, so `rel="\"next\""`, `rel=""`, `rel="next, prev"` and control characters read as known absence, and HF claims exhaustion.
- **R8-2 (BLOCK):** truthiness checks skip type validation. ECB `series=false`/`0`/`""` and HF `siblings={}`/`false` become complete-empty, and a falsy wrong-type holder beside a good one loses its drop accounting.
- **R8-3 (BLOCK):** `from .base import *` and a re-exported `json` parser bypass the escape inventory. Two full adapter mutations pass all 20 structural tests while losing records.

**Orchestrator routing:** fourth round of the same family (malformed input read as a definite answer). Fixing reported instances keeps leaving neighbours, so 2b-repair-9 also requires a seeded generative harness asserting the invariant across every adapter: no complete, empty or exhausted result from unreadable input, and readable peers kept as a partial lower bound. Dispatched to Sonnet 5.5.

**Follow-up ruling, same day:** "I want a fresh Astra on the architecture review every time. I don't want other gates tainting it." Gate D is always a new Astra session that has run no other gate and is never reused for one. Clarified by the operator: "it should and can look at the review log. I just don't want tainted context" — the isolation is of session context, not files; Gate D reads the normal repository, review log included.

## 2026-10-01 — 2b-repair-9 landed (Sonnet 5.5 coder fac04fcb)
7 commits `47357b0..cb3caae`. R8-1: `rel` values are validated as RFC 8288 relation-type lists before anything concludes absence. R8-2: `base.optional()` and its siblings are the single typed reading of optional provider containers. R8-3: `adapters.base` has an explicit `__all__`, binds no parser, and the inventory check refuses import forms it can't analyse. **The invariant harness** corrupts every position (and co-dependent pairs) of every adapter's valid answers and runs them through the real router against four invariants. It **failed 117 of 261 tests with 3,401 violations on the unfixed tree** and passes now. Beyond the named findings it surfaced:
- a wrong-kind member field crashing the whole request in 21 operations;
- falsy bypasses across many holders;
- ~1,800 silent wrong-kind reads inside kept records;
- totals and cursors producing false ends;
- fabricated identities;
- a Socrata year read from epoch seconds.

All are fixed, and 24 new mutants are bound to the fixes and invariants. Limits are disclosed with proposed owners: Phase 4 canary for live type and semantic drift; Astra Gate C for hand-parsing and oracle authorship. The completion block's "Remaining: NONE" is sent to Astra for a ruling.

## 2026-10-01 — 2b-repair-9 re-review (Astra, xhigh) — BLOCK; oracle authorship split
Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-9-astra-review-20261001.md`; evidence in `private/evidence/astra-2b-repair-9/`. Boundary PASS at PID 1040. Gate B PASS. The harness's before/after claim was independently confirmed: at `7a90b37`, 117 of 261 tests fail with 3,401 violations; at `cb3caae`, 0. Most behaviour changes are ROOT-CAUSE and accepted, including the Socrata epoch-year fix and DOAJ `ref`. The limits are accepted as owned scope statements.

**Blocks:**
- **R9-1:** URI-form `rel` values are validated by a forbidden-character rule, not the URI grammar, so `%GG`, a trailing `%`, `https://[broken` and non-ASCII still mean known absence (false exhaustion). The "independent" reader shares the same rule.
- **R9-2:** OpenML `licence or license` erases a present wrong-kind value. The fixture never populated that field, so the harness never corrupted it.
- **R9-3:** `from ..core import cache` then `.json.loads` bypasses the import closure; all 27 structural tests pass while records are lost.
- **R9-4:** the canonical-field oracle uses `run(op, valid)` as its baseline. A title-erasing mutant passes all 261 harness tests.
- **R9-5:** coverage credits `bis.catalog`, which never executes. A BIS fabrication mutant survives.

**Orchestrator routing:** R9-1 and R9-4 share one root cause: code and oracle written by the same author, so they share blind spots. The fix is to split authorship. **2b-repair-10a**, an oracle author on Sonnet 5.5, writes RFC 3986/8288 conformance vectors, hand-specified expected canonical fields, populated optional-field variants and an execution-derived coverage registry, from specifications and fixtures only and never reading the implementation; these tests are expected to fail on current code. **2b-repair-10b**, a separate coder, then fixes R9-1..R9-5 against them.

**2b-repair-10a landed (oracle author fb7bc4cf, Sonnet 5.5, spec-only).** Commits `e4b7eac` (pre-registration), then `206afe4`. Production code untouched. It adds 637 hand-labelled RFC Link/URI vectors with a reference grammar, hand-specified expected canonical fields tagged by source, 61 populated optional-field variants, an execution-derived coverage registry with the BIS and ECB catalogue cases, and router-output mutants. On current code `make gen2-gateway` exits 2 with 189 failures, as intended:
- 144 Link/URI conformance (R9-1, including invalid targets, URI rels, cursors and the empty reference);
- 10 OpenML licence (R9-2, the find path only);
- 2 multi-structure catalogue dimension merges;
- 18 missing `publisher`;
- 10 harness mixed-member failures for `openml.fetch` at other seeds;
- 5 populated-variant harness failures (DOAJ `ref`, Europe PMC `isOpenAccess`, OpenML licence).

R9-4 confirmed: the old harness passes 6 of 7 router-output mutants, and the new expectations catch all 10.

**Disclosed weakness:** the RFC grammars were written from memory, because the orchestrator's brief wrongly forbade all network calls; fetching public documentation is allowed. Sent back to fetch the RFC text and verify every vector, logging any correction as RFC-text or post-observation.

**"Needs a ruling" items, settled by the orchestrator from existing contracts and principles; none needs the operator:**
- openml.fetch url members: decided from OpenML's documented payload in 10b.
- `publisher`: mapped wherever the canonical contract defines it and the provider supplies it.
- A self-referential next link: not followed (no progress) and not an end, so unknown/partial.
**2b-repair-10a, RFC-text verification:** the RFC 3986, 8288 and 9110 texts are fetched into evidence with a manifest. The hand grammar was checked mechanically against an RFC 3986 Appendix A regex compiled from the text: 0 disagreements over 240,267 strings. Corrections: 169 citations fixed and 13 labels or grades changed, all traced to RFC lines. One post-observation tightening (the empty reference) was disclosed and reverted. 191 oracle failures on current code (`650ac23`). Dispatched **2b-repair-10b** (Sonnet 5.5 coder) to make the gateway pass the oracle without editing it; disputed expectations go to Astra with their evidence.

**2b-repair-10b landed (Sonnet 5.5 coder be3b8d97).** 5 commits. All 191 independent-oracle cases pass; no expectation disputed; the oracle files are byte-identical to `650ac23`, which the orchestrator confirmed. Root causes addressed:
- R9-1: a real RFC 3986 grammar in `core/uri.py`, with relative resolution and self or foreign-anchor next links treated as unknown;
- R9-2: a present value is typed before any fallback chooses, across 190 scanned sites, including doi.org `RA`;
- R9-3: import closure through module attributes;
- R9-5: the per-flow browse.

`publisher` is now mapped. The `openml.fetch` mixed-member failure was the harness generator's error, per OpenML's `Api_data.php`, and the generator was fixed. Sent to a fresh Astra, which is also asked to judge the oracle's independence in substance.

## 2026-10-01 — 2b-repair-10 re-review (Astra, xhigh) — BLOCK, narrower
Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-10-astra-review-20261001.md`; evidence in `private/evidence/astra-2b-repair-10/`. Boundary PASS at PID 1040. Gate B PASS.

**ROOT-CAUSE, accepted:**
- R9-1: the RFC 3986 grammar. 330,513-string differential reproduced; all 41 §5.4 examples pass.
- R9-3: the import closure. The `core.cache.json` mutant is refused.
- R9-4: the oracle's field expectations. The title-erasing mutant now produces 170 violations, and all 10 router mutants are caught.
- Typed reading at the corrected sites, publisher mapping, the per-structure dimension reader, and execution-registry accounting.
- The oracle is judged substantively independent and source-based but not a flawless clean room: it saw the old URI regex and changed some expectations after observation, each documented. 30 vectors and 17 fields were spot-checked as supported.

**Blocks:**
- **R10-1:** `text(a) or text(b)` short-circuits validation of a present malformed fallback. DataCite `rights` and BEA `Description` are reproduced, and the contract text wrongly exempts the pattern.
- **R10-2:** the BIS and ECB browse takes the structure reference from `flows[0]` and labels it with the requested flow, fabricating templates for non-first and absent flows (6 failures). The oracle always browsed `flows[0]`.
- **R10-3:** the original BIS `identified(...)` deletion mutant survives all 501 harness and 30 oracle tests.

**Evidence corrections required:** 63 populated variants, not 61; independence claims to carry their qualifications; the OpenML documentary explanation to be narrowed.

**Orchestrator routing:** the R10-2 and R10-3 gaps are oracle gaps, so the authorship split is kept. 11a: the independent oracle author adds fallback-pair, flow-binding and unnamed-flow cases from the specifications. 11b: a separate coder fixes against them.
**2b-repair-11a landed (oracle author fb7bc4cf).** `caf4b13` (new cases, committed before any comparison) and `99e3f2c`. No production code touched. 68 new oracle cases fail on current code, each for Astra's stated reason:
- 30 R10-1 fallback-beside-valid-preferred cases (DataCite rights find/resolve, BEA `Desc`/`Description`);
- 32 R10-2 flow-binding cases (24 non-first-flow, 8 fail-closed for absent, missing-structure or ambiguous flows);
- 6 R10-3 failure-mode accounting gaps.

Unnamed-flow cases pass on current code and kill a boundary-level reproduction of the deleted-validation mutant. Failure-mode accounting is now separate from execution accounting. Disclosed qualification: one black-box probe chose which 2 of 40 documented fallback pairs the gateway reads. Evidence corrections made (63 variants; qualified independence; narrowed OpenML explanation). Dispatching the 11b fix coder.
**2b-repair-11b landed (coder 05f61d77).**
- 2 commits, `33e2c2d` and `c1b9351`. All 68 oracle cases pass, none disputed, oracle unchanged since `99e3f2c`.
- **R10-1:** every alternative is read before selection, through `base.preferred`/`identity_from`. The contract exemption is removed. Full site inventory is in `fallback-sites.md` (83 sites, 12 changed, 71 with reasons; plus 17 further changes), with a scan test against new lazy choices.
- **R10-2:** the browse is bound to the requested flow's own structure; absent or ambiguous flows produce no template.
- **R10-3:** the BIS/ECB validation mutants are now killed by the oracle.
- **Coder decisions sent to Astra:** Unpaywall `best_oa_location`; Kaggle whole-number sizes; URN structure references.
- **OpenAlex snapshot defaults:** left as is. Astra's 2b-repair-8 ruling (offline ingestion outside the A4 lane contract) already covers this, so no operator question; Astra is asked to confirm.

Sent to a fresh Astra once the orchestrator's verification completes.

## 2026-10-02 — 2b-repair-11 re-review (Astra, xhigh) — BLOCK, narrow; dispatch HELD for operator
Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-11-astra-review-20261001.md`. Boundary PASS at PID 1040. Gate B PASS.

**Accepted:**
- The original 68 oracle assertions pass.
- The BIS/ECB fabrication mutants are killed.
- The scalar fallback repair (`preferred` / `identity_from`) is ROOT-CAUSE.
- Requested-flow selection works.
- The OpenAlex snapshot tolerance is confirmed under the repair-8 scope ruling.

**Blocking:**
- **R11-1:** a correctly typed outer container is checked, but its supported nested contents are decoded only after selection. Examples: Unpaywall `best_oa_location.url`, ECB alternate `structures`/`data.structure`, the Crossref journals loader `ISSN` beside `issn-type`. 20 corruption cases fail; alternate-only controls pass. Effect: malformed fallback data is ignored and records are kept (no false empty or end).
- **R11-2:** contradictory structure references inside the requested flow (two `Ref`s, or a `Ref` plus a conflicting `URN`) silently resolve to the first. The SDMX 2.1 schema forbids such input. Effect: a possibly wrong template from schema-invalid XML.

The structural scan also has an ordinary-spelling bypass; Astra asks that its claim be narrowed.

**Orchestrator:** this is the twelfth 2b review round. The operator asked why the process feels like circling. The orchestrator's diagnosis: an open-ended acceptance bar, instance-level fixing until round 8, and routing without stepping back. It proposed freezing a finite acceptance contract, with later findings triaged into either blocking (false end, false empty, permission widening) or debt-register items. **No new repair is dispatched until the operator decides.**
**OPERATOR RULING:** "or why don't we try to address the bugs" — fix R11-1 and R11-2 now. Dispatched 2b-repair-12 (Sonnet 5.5) with Astra's reproductions as the required tests. The acceptance-process change is not adopted; the existing process continues.
**OPERATOR (same exchange):** "at their root — which is a constraint I know I applied." Correct: the charter's root-cause rule and third-round redesign rule cover this. The orchestrator had applied them per finding, not per defect family. **Family root cause:** adapters read provider payloads field by field, ad hoc, with no declared shape, so each round patched one access pattern. **2b-repair-12 is redirected to the root fix:**
- per-operation declared schemas for supported payloads (types, nesting, cardinality, alternatives and their consistency, member lists);
- one shared decoder that validates whole payloads before adapter logic;
- adapters choose only between already-validated values;
- harness corruption derived from the schemas.

All accepted contracts, the unedited oracle and Astra's R11 reproductions must still pass.
**OPERATOR:** "last night I literally had you add a review pass that specifically was meant to catch patches." **Why it didn't:** the orchestrator scoped the root-cause/mitigation classification per finding. Each fix was honestly ROOT-CAUSE for its own finding, and no brief asked whether the findings shared a cause across rounds. Gate D, the one cross-cutting review, only triggers on task acceptance, which 2b never reached. **Charter amended:** (1) every re-review classifies at family level too, and a series of local fixes for one shared cause counts as a MITIGATION of that cause; (2) a task's third consecutive BLOCK triggers a fresh-session Gate D before the next repair. Memory updated.

## 2026-10-02 — 2b-repair-12 landed: the family root fix
Sonnet 5.5 coder `ee76b68e`, 5 commits `278ab7e..a06ea5e`.
- **What changed:** every provider operation declares a schema, and `core/schema.py` validates whole payloads before any adapter logic runs: alternatives, nested contents, consistency rules, per-member isolation. Harness corruption positions are derived from the schemas, and reading an undeclared field fails. The old views and helpers (`need`, `optional`, `nested`, `listed`, `preferred`) and the lazy-choice scan were removed as dead.
- **Results:** Astra's R11 probes went from 24 failures to 0; the oracle is unedited and passing. The coder ran an old-vs-new differential over 67,021 single and 6,666 pair corruptions: it found 3 unintended changes (fixed and pinned) and 120 deliberate ones (documented).
- **Disclosed limits:** SDMX-ML positions are not schema-derived; an `any_()` under-declaration can't be caught by the derived harness; a stale oracle citation remains. The engine supervisor mutant `1C-sup-no-start-grace` failed once in a full run and passed 3 of 3 alone (timing-dependent).

**Dispatch:** a fresh Astra re-review, with the charter's family-level question made explicit, and **Gate D #1** (whole-system, fresh session), in parallel on the same commit, per the third-consecutive-BLOCK rule.

## 2026-10-02 — 2b-repair-12 re-review (Astra, xhigh) — BLOCK; family verdict MITIGATION/incomplete
Full report: `~/work/research-loops-public/private/reviews/gen2-2b-repair-12-astra-review-20261002.md`; evidence in `private/evidence/astra-2b-repair-12/`. Boundary PASS at PID 1040. Gate B PASS. The orchestrator's verification: `make gen2-check` exit 0 (1,615 tests, 1,701/1,701 mutants; the supervisor mutant passed this time); `make gen2-gateway` result logged in `orch-2b-repair-12/`.

**Family-level verdict (the first under the amended charter): MITIGATION / incomplete structural correction.** Schemas and eager decoding remove the lazy-read mechanism for correctly declared fields. The family cause survives on concrete paths:
- `any_()` declarations still admit decision fields;
- doi.org bypasses the decoder;
- XML shape constraints are partly ad hoc;
- raw responses remain reachable before decoding.

The R11 reproductions are closed (ROOT-CAUSE at their sites).

**Findings:**
- **R12-1:** decision fields under-declared as `any_()`. BEA `DatasetName`/`ParameterName`, BLS `survey_abbreviation`/`seriesID` and FRED `id` accept `true`/list/object as identifiers and selectors. The doi.org lookup still bypasses the decoder.
- **R12-2:** the SDMX reference reader filters `Ref`s by a truthy `id` before counting, so a valid Ref beside `<Ref/>` or `<Ref id=""/>` still binds. Fixed `package`/`class` attributes are not checked. Same family as R11-2.
- **R12-3, regression:** Semantic Scholar `data:null` + `total:0` is newly promoted to complete-empty (false empty). The generic decoder's absent rule erased an operation-specific distinction.
- **R12-4, regression:** `year_value` uses `isdigit()` then `int()`, so Unicode digits or a 4,301-digit string raise a `ValueError` that escapes the member boundary and aborts the whole answer.
- **R12-5:** the derived harness doesn't descend into `oneof` unions (50 positions, 0 descendants), and DOAJ CSV and doi.org are absent from the derived passes. Raw-response access via `getattr(resp,"json")` bypasses the structural checks.

**Routing:** held until Gate D #1 (running in parallel) reports, so that one repair brief addresses both, per the charter's rule that Gate D runs before the next repair.

## 2026-10-02 — Gate D #1 (fresh Astra, whole system, pinned a06ea5e) — BLOCK
Full report: `~/work/research-loops-public/private/reviews/gen2-gate-d-1-astra-review.md`; evidence in `private/evidence/gate-d-1/`. The first whole-system review.

**Blocking (HIGH):**
1. The schema decoder's member-failure boundary is not total: a Unicode digit or a huge year raises a `ValueError` that loses the whole lane (same as R12-4).
2. The gateway's fuzzy dedup merges records with distinct DOIs into one canonical record. That violates the methodology and INVARIANTS E-3 (identity duplicates only); it is inherited gen-1 behaviour.
3. The engine drops pagination and exhaustion at the durable handoff. A page that has another cursor and an exhausted page produce identical client outputs and router commands, so 2c could never recover the distinction.

**Non-blocking:**
4. MEDIUM: the poll deadline counts only sleep time, not network time (bounded-liveness defect; must be fixed before 2e1).
5. MEDIUM: import-only checks understate coupling. The Router's six mixins make 132 cross-file self-calls, and the gateway's adapters/core/registry packages form a cycle (→2q).
6. LOW: stale locators (→2q).

**Measurements:** propagation cost 13.6% (engine), 11.3% (gateway); 43 functions over CC 20; top hotspots are `_decode`, `Router._write_evidence` and `_commit_in_transaction`. Size rules pass. Mechanical crash/replay/fencing coverage is judged substantial, and most unfinished workflow features have owners. **Directive: don't build or accept accounting/stopping behaviour on the current 2b handoff.**

**Orchestrator routing:** the Astra repair-12 and Gate D findings are combined.
- **2b-repair-13a (gateway)** closes the decoder contract's three gaps by construction (total failure algebra, declaration completeness for decision fields enforced in `Rec`, a sealed raw payload), plus per-operation null policy, XML reference shape, union-branch harness reach and identity-only dedup.
- **2b-repair-13b (engine)** then carries a typed page outcome through client, router and store, adds an absolute poll deadline, and makes the 1c supervisor mutant test deterministic. Astra ruled the rerun a MITIGATION; the owner is engine test maintenance.
- 2q's scope absorbs Gate D findings 5 and 6.

## 2026-10-02 — 2b-repair-13a landed (gateway decoder contract) — Astra re-review dispatched
**Coder (Sonnet 5.5, `c8ceb127`):** `42a155d`..`2d62753`. It claims the three gaps in the decoder contract are closed by construction:
- every conversion and consistency rule goes through one failure channel to a member-level `PayloadError`;
- `any_()` values are `Passive`, so storage via `plain()` is the only use and anything else raises `PassiveRead`; 26 of the 89 audited uses are now typed and 63 stay passive under a table test;
- `Response` is sealed: only `decode` opens the bytes, and doi.org and DOAJ CSV are decoded.

It also covers per-operation `never_null` (Semantic Scholar restored), reference cardinality before filtering, union-branch harness reach, and identity-only dedup with optional `linkage_suggestions`. Gateway production grows by 399 lines. The differential against `a06ea5e` has 0 unexplained rows. The coder reports both targets exiting 0.

**The coder's own limits, which the review judges as findings:**
- `is None` on a `Passive` always reads as present;
- some string operations raise `TypeError` rather than `PassiveRead`;
- `plain()`/`download()` are guarded only by the scan;
- totality rests on a finite corpus;
- a new 64-level nesting limit;
- `linkage_suggestions` has no consumer yet.

**Orchestrator:** clean tree; the oracle and `gen2/` are unchanged; gen-1 is unchanged (user unit, PID 1040). Independent reruns are in progress. Astra's task: `private/reviews/gen2-2b-repair-13a-review-task-20261002.md`.

## 2026-10-02 — Astra re-review of 2b-repair-13a (`180914e7`, pinned 2d62753) — BLOCK (A, C); PASS (B)
Full report: `private/reviews/gen2-2b-repair-13a-astra-review-20261002.md`.

**ROOT-CAUSE at their sites:**
- R12-1: the typed BEA/BLS/FRED fields (30 wrong-kind and 8 malformed-label cases refuse), and doi.org decoding;
- R12-2: SDMX references;
- R12-3: Semantic Scholar null (all four pairs restored);
- R12-4 and Gate D #1: the scalar failure channel;
- R12-5: union reach, 40 union-descendant positions, every declared path reached;
- Gate D #2: identity-only dedup (120 distinct-identity pairs, no merges; raw inventory preserved).

Both targets pass independently: gateway 1,334+1,334 tests, 295/295 mutants; engine 1,615 tests, 1,701/1,701. Astra rebuilt 4 mutants and all were killed.

**Family verdict: MITIGATION / incomplete, but narrowed.** Two places remain where the decoder contract stops short:
- **R13A-1 (MEDIUM, boundary drift):** `decode_csv` uses Python's permissive CSV default. An unterminated quoted header gives a DOAJ load of **0 journals that reports success**. Unterminated fields collapse rows; duplicate headers silently pick one. This is inherited (the same result on `a06ea5e`). Cause: the lexical opener layer below the decoder resolves malformed bytes into structure.
- **R13A-2 (MEDIUM, deviation):** `make_record` returns `plain(rec)`, so adapter code can read `raw`/`extra` and let a passive field decide selection. Shown with a reviewer source mutant (OpenCitations omits a citation, the lane still reports complete, and no scan fires); no shipped code does this. The "by construction" claim is therefore not met.

**Gate C:** 90 of the 100 new test claims are bounded; 10 overbroad claims need rewriting.

**Disclosed limits:** all judged MITIGATION of the universal claim, with no current misuse found. TypeError paths fail closed. The 64-level JSON depth limit is an explicit operational limit.

**Orchestrator routing:**
- **13b (engine) first**, since it is independent of these findings.
- **Then 2b-repair-13c (gateway):**
  - inventory every byte opener and make each strict against its format spec: CSV quoting and duplicate headers, JSON duplicate keys and NaN, XML as checked;
  - keep provenance opaque through `make_record` until the router's serialization boundary;
  - rewrite the 10 test claims;
  - narrow the "only decode opens bytes" wording.
- Language-level residuals (`is None` on `Passive`, reachable private names, a finite corpus) can never be closed by construction in Python. **Escalated to the operator for a ruling** on accepting them as permanent, scan-guarded limits.

## 2026-10-02 — 2b-repair-13b landed (engine hand-off) — Astra re-review dispatched
**Coder (Sonnet 5.5, `d6988b45`):** `1178e97`..`a5a2afb`.
- **Gate D #3:** each page observation now carries `page_outcome` (exhausted / continuation / end_unknown / limit_reached / failed) and a typed `continuation`, end to end, with store CHECKs. Only a whole page reporting `exhausted` establishes exhaustion.
- **Gate D #4:** one monotonic deadline; each exchange's timeout is clamped to the time left; sleeps are bounded.
- **Supervisor test:** the start-grace test is synchronized by a gate file and has a normal-start control.
- **13a condition:** `linkage_suggestions` is shown to be inert in the engine.
- **Results:** 1,641 tests; 1,739/1,739 mutants; engine production +94 lines.

**Coder's disclosed limits, judged as findings:**
- The clamp is per socket operation, so a reply that trickles in can outlast the deadline.
- `end_unknown` also covers requests that don't page.
- One unexplained intermittent failure in a multi-process store test (`test_a_report_recorded_after_a_newer_one_never_displaces_it`), not investigated.

**Orchestrator:** clean tree; `gateway/` and the oracle untouched; gen-1 unchanged (PID 1040). Independent reruns in progress. Astra's task: `private/reviews/gen2-2b-repair-13b-review-task-20261002.md`.

## 2026-10-02 — Astra re-review of 2b-repair-13b (`5539a8d8`, pinned a5a2afb) — BLOCK (A, C); PASS (B)
Full report: `private/reviews/gen2-2b-repair-13b-astra-review-20261002.md`.

**ROOT-CAUSE:**
- Gate D #3's information loss: "more remains" and "finished" now differ in client output, command and row;
- the supervisor start-grace test (killed in all four schedules, control passes);
- `linkage_suggestions` inert in the engine.

Both targets pass independently (1,641 tests and 1,739/1,739; gateway 1,334+1,334 and 295/295). Astra rebuilt 3 mutants and all were killed. New corruption families (cursor repeat, cursor cycle, cap equal to total) produced no false exhaustion. Pre-change stores are refused by the opener, which is safe; Phase 4 owns reconciliation.

**Family verdict: MITIGATION / incomplete at the engine hand-off.**
- **R13B-1 (MEDIUM):** the deadline is a per-socket-operation timeout, so a 6-chunk trickle took 0.5 s under a 0.2 s budget, and a late `done` was accepted and persisted as `searched_empty/complete/exhausted`.
- **R13B-2 (MEDIUM):** the boundary checks compare assertions with each other but never with evidence. Admitted today:
  - complete/exhausted with `gateway_call_ref=null`;
  - a missing or invented request type;
  - the `exhausted` sentinel as a cursor;
  - router and DDL disagreeing on the cursor domain;
  - a first-write relabel of `limit_reached` as `exhausted` with a valid capability.
- **R13B-3 (MEDIUM, test reliability):** the recorder-startup failure is unexplained. Readiness has no bound and the child's exit/stderr aren't kept.

**Gate C:** 1 of 27 test claims is rejected (the after-deadline test receives its reply before the deadline).

**Orchestrator routing → 2b-repair-13d (engine, after 13c):**
- a whole-exchange deadline over connect, headers and body, where a late terminal reply counts as a timeout;
- the admission contract enforced in both router and DDL: capture acknowledgement, a closed request discriminator, per-type `end_unknown`, no exhausted unobserved lane, one cursor domain;
- the startup failure instrumented and diagnosed.

**Trust model:** taken from the source of truth, not adjudicated as a mitigation. Trusted station/gateway code is the capture boundary (flow §S2, BOUNDARIES' station supervisor, D-1), and relabelling by trusted code is detected by the state-integrity audit's re-derivation from the raw ledgers (BOUNDARIES "checked by", flow §state integrity). 13d documents it, and the next review judges that reading. **Reported to the operator for override.**

## 2026-10-02 — 2b-repair-13c landed (gateway: strict openers, opaque provenance) — Astra re-review dispatched
**Coder (Sonnet 5.5, `6dcd87e1`):** `dd61431`..`37a655c`. Claims and results:
- **Openers:** all JSON/XML/CSV lexing goes through `core/wire.py`, each opener strict to its specification (RFC 8259, XML 1.0, RFC 4180). `Retry-After` follows the header grammar; it was `float()`, so `inf` held a breaker open. `test_openers.py` inventories every parse call.
- **Provenance:** `make_record` keeps `raw` Sealed and `extra` Passive. Materialization happens only at the router, the harvest index and the cache.
- **Byte reads:** the "only decode opens bytes" claim is scoped to payload decisions, with an exact inventory of the four other reads.
- **Tests:** 10 claims rewritten. Astra's 13a probes fail on `2d62753` and pass now.
- **Differential:** zero unexplained differences.
- **Size and results:** gateway production +289 lines; 1,398+1,398 tests, 327/327 mutants.

**Residuals left for review:**
- The Python-language residuals are pending the operator's ruling.
- Snapshot-loader lines that aren't JSON now fail the load instead of being skipped.
- Live-provider compatibility of the strict refusals is unverified (Phase 4).
- SDMX namespace URIs are unchecked.
- A CSV truncated at a record boundary reads as complete; the review is asked whether the transport detects truncation.
- `Rec.empty` exposes one bit; decoder-issued `Sealed` values can be compared; lone surrogates are accepted.

**Orchestrator:**
- clean tree; `gen2/` and the oracle untouched; gen-1 unchanged (PID 1040);
- independent reruns in progress.

Astra's task (`private/reviews/gen2-2b-repair-13c-review-task-20261002.md`) asks explicitly whether anything other than the language-level limits stands between the gateway and structural closure.

## 2026-10-02 — Astra re-review of 2b-repair-13c (`f3e1f1c2`, pinned 37a655c) — BLOCK (A, C); PASS (B)
Full report: `private/reviews/gen2-2b-repair-13c-astra-review-20261002.md`.

**ROOT-CAUSE:**
- the R13A-1 lexical defects (CSV quoting and headers, JSON duplicate names and non-finite numbers, malformed UTF-8);
- the R13A-2 direct-copy escape, sealed downloads, and materialization at router, index and cache;
- the earlier R12 and Gate D fixes, retained.

Both targets pass independently.

**Family verdict: MITIGATION; not structurally closed**, and the gaps go beyond the language-level residuals:
- **R13C-1 (MEDIUM, boundary drift):** `resp.read(n)` returns a short body without `IncompleteRead`. A DOAJ CSV cut short of its declared Content-Length loads 0 or 1 journals and reports success (status 200 / `ok`). Chunked truncation is detected. The contract docs claim short bodies are detected.
- **R13C-2 (MEDIUM):** provenance escapes through public constructors:
  - `make_record` seals an adapter literal with decoder (`_issued`) authority, so `copied == guessed` decides selection;
  - a decoded `Rec` passed as `identifiers` is materialized by `plain()`.

  Both are shown with OpenCitations mutants that drop a citation and still report complete. Neither uses private names.
- **R13C-3 (MEDIUM):**
  - XML scalar text inside a child element is silently dropped (BIS label `Policy <b>rates</b>` becomes `Policy `, still complete);
  - SDMX matching is namespace-blind, so a foreign namespace is accepted as SDMX.
- **R13C-4 (MEDIUM):** the snapshot loader now aborts the whole file on one malformed line. That regresses the per-line isolation accepted in repair-8.
- **R13C-5 (LOW):** the `Retry-After` date path still uses the permissive email parser, contradicting the "strict grammar" claim.

**Gate C:** 85 of the 96 new or changed tests are bounded; 9 overclaims and 2 rejected contract changes. The "no number beyond a double" claim is false (`10**400` is accepted). The tools line count (+613) doesn't reproduce; Astra counts +205.

**Asked for operator confirmation, separately from the language residuals:**
- sanctioned exceptions for `Rec.empty` and for equality between `Sealed` values the decoder issued;
- the supported-format and depth limits.

**Orchestrator routing:**
- **Charter trigger:** this is the third consecutive BLOCK since Gate D #1 (13a, 13b, 13c). A fresh **Gate D #2** (`8d74ce90`) is dispatched before any further gateway repair. Its task (`private/reviews/gen2-gate-d-2-task.md`) asks:
  - whether the family definition is stable or the review standard is drifting;
  - which threat model the source of truth requires for first-party adapter code: by-construction confinement, or a provider-input contract plus guards;
  - the finite acceptance list for 2b;
  - whether the repair sequence has built accidental complexity.
- 13d (engine, already dispatched) continues.

## 2026-10-02 — Gate D #2 (fresh Astra `8d74ce90`, pinned 2c400a8) — BLOCK, with a finite finish line for 2b
Full report: `private/reviews/gen2-gate-d-2-astra-review.md`; evidence in `private/evidence/gate-d-2/`.

**Diagnosis:**
- The provider-input validation work **is converging**.
- The **proof obligation expanded**. The 13a/13c briefs (the orchestrator's) adopted "by-construction" confinement of first-party adapter code against deliberate misuse of public APIs. Reviewers rightly found counterexamples to that, and each one was treated as another instance of the decoder family. That was the process error behind the circling.
- The family groups at least four mechanisms: wire completion, lexical/structural interpretation, adapter discipline, and policy preservation. They share an objective, not one root cause.

**Findings:**
- **F1 HIGH:** Content-Length truncation (R13C-1).
- **F2 HIGH:** XML child-text loss and namespace-blind matching (R13C-3).
- **F3 HIGH, architectural:** no stable trust boundary.
- **F4 MEDIUM:** the two constructor compositions (R13C-2).
- **F5 MEDIUM:** snapshot isolation regressed (R13C-4).
- **F6 MEDIUM:** 13d's audit sentence is overstated:
  - `gateway_call_ref` acknowledges a call row, not a response artifact;
  - D-1 covers decision receipts, not retrieval;
  - the cited flow section is S4, not S2.

  Fix: correct the wording, and give 2e2's retrieval audit an evidence requirement.
- **F7 LOW:** Retry-After and number claims, plus the 9 overclaimed tests and the 2 snapshot tests.

**Trust model:** the source of truth supports **B**: a complete contract for supported provider input, with first-party adapter discipline enforced by guards, inventories, mutation tests and review. **A** (by-construction confinement) isn't established in same-process Python and would be a different architecture project. Adopting B is an operator amendment.

**Finite acceptance checklist:**
- **0:** amend to B (operator).
- **1:** transport framing completion.
- **2:** lossless scalar XML and SDMX expanded names.
- **3:** close the two constructor compositions.
- **4:** restore snapshot per-line isolation.
- **5:** freeze the supported-format/resource policy and the sanctioned predicates (`Rec.empty`; `Sealed` equality only for decoded objects) (operator).
- **6:** one consolidated inventory and guards; reconcile the rejected test claims.
- **7:** 13d.
- **8:** final assembled validation with a family-level account.

New counterexamples *within the frozen contract* still block. Restating the same evidence limits does not.

**Complexity:**
- gateway production +688 lines since Gate D #1 (+6.2%), 84.7% of it in schema/payload/wire/base;
- propagation cost 11.25% → 11.92%;
- `_decode` cyclomatic complexity 57 → 64;
- still no file-import cycles.

Consolidate: canonical typed construction must not materialize raw data; one raw-materialization operation at the sinks; replace `_issued` with a narrowly specified comparison; one owned inventory. The package cycle, router collaboration and decomposition stay with 2q.

**Orchestrator:** the next gateway repair is **held for the operator's rulings on items 0 and 5**. 13d continues; F6's wording fix joins the final package.

## 2026-10-02 — Operator rulings on Gate D #2
1. **Trust model B is adopted.** The gateway guarantees a complete contract for supported provider input. First-party adapters are trusted, reviewed code, with their discipline enforced by inventories, guards, mutation tests and review. This is a design boundary, not by-construction confinement. Python identity checks, private-field access, importable helpers and finite testing are documented boundaries under B, not debt. This also answers the language-residual question pending since the 13a review.
2. **The supported-format and resource policy is frozen as listed in Gate D #2 item 5.** It covers UTF-8, JSON duplicates and non-finite numbers, finite floats versus exact integers, depth 64 for JSON and XML, no DOCTYPE, the CSV extensions, the 131,072-character CSV cell and the 256 MiB body limit. There are two sanctioned predicates: `Rec.empty` at the reviewed shape predicates, and equality between decoded provider objects for the intended comparisons only.

**Routing:** 2b-repair-14 (gateway) implements Gate D #2 checklist items 0–6 and 8 in one pass, after 13d. The next reviews judge against the frozen contract: new counterexamples *within* it block; restating the same evidence limits doesn't.

## 2026-10-02 — 2b-repair-13d landed (engine: deadline, admission, startup failure)
**Coder (Sonnet 5.5, `63cce017`):** `34ed64b`..`fd414d4`.
- **R13B-1 (deadline):** one absolute deadline, taken when the transport is called, arms every blocking socket call: connect, send, status and headers, body, and TLS. `_exchange` also discards a reply that completes after its budget. On Astra's probe, a 0.2 s deadline that previously took 0.508 s now takes 0.20 s, and the late `done` is now `unknown/unobserved/timeout/failed`.
- **R13B-2 (admission):** the router and the DDL enforce the same contract: capture acknowledgement, a closed request discriminator, per-type ends, no exhausted unobserved lane, and one cursor domain (see `gen2/core/pagination.py`).
- **R13B-3 (startup failure):** diagnosed as SQLite's `busy_timeout` not covering the switch from rollback journal to WAL on first open beside a writer, and fixed in `store/db.py`.
- **Test claim:** the after-deadline test was renamed and a real late-reply test added.

**Disclosed:**
- DNS resolution (`getaddrinfo`) can overrun the deadline by the resolver's own timeout. A late reply is still never admitted.
- The relabel case awaits the 2e2 retrieval audit.
- The TLS tests need `openssl`, which is present on this host.
- The real-socket tests use wall-clock margins.
- Two socket mutants have no paired control.

**Orchestrator:**
- clean tree; `gateway/` untouched; gen-1 unchanged (PID 1040);
- independent reruns in progress;
- **review held for a combined 13d + 14 review**, to conserve the Codex window (90% of 7 days used, resets in about 5 days).

## 2026-10-02 — 2b-repair-14 landed (gateway finish line); combined final 2b review dispatched
**Coder (Sonnet 5.5, `39fc2492`):** `071eb9a`..`373c3dc`. Gate D #2 checklist:
- **0:** B amendment.
- **1:** `Transport.request` owns message completeness: framing validated, an unmet Content-Length raises `IncompleteRead`, 256 MiB bound.
- **2:** lossless XML scalars; matching by expanded name.
- **3:** no `Sealed` comparison; `Rec.same_as` is the one comparison; typed fields unwrap nothing; `plain` at three sinks only.
- **4:** snapshot per-line isolation restored, with a report of refused lines.
- **5:** STATION-CONTRACT §5 freezes the format policy.
- **6:** one owned inventory (65 sites); the 9 overclaims and 2 snapshot failures resolved; Retry-After documented (zone-less dates are now GMT, previously host-local); the number claim corrected.
- **F6:** INVARIANTS E-2 and the router README corrected, and the 2e2 requirement recorded.
- **8:** the family account under B.

**Results:** gateway 1,491+1,491 tests, 366/366 mutants; engine 1,700 tests, 1,781/1,781 mutants. All ten open reproductions fail on `37a655c` and pass now. Gateway production +168 lines. The coder flagged stale "detected by the audit" wording in two engine files that its brief kept it from touching; **the orchestrator fixed both, comment-only, in `c0d963d`**.

**Judgement calls sent to the review:**
- **SDMX-ML 2.1 only.** The BIS adapter uses `stats.bis.org/api/v2` with `Accept: application/xml`, and its default response version isn't confirmed from public docs, which are rendered by JavaScript.
- repeated Content-Length is refused;
- a cut inside the chunked trailer is accepted;
- record identity must be text.

**Review:** one combined Astra Gate A+B+C review of 13d + 14 (`ef030fc5`, pinned `c0d963d`; task `private/reviews/gen2-2b-final-review-task-20261002.md`), judged against the operator rulings and Gate D #2's acceptance rule. Combining them conserves the Codex window. Orchestrator reruns at `c0d963d` are in progress.

## 2026-10-02 — Astra final 2b review (13d + 14; `ef030fc5`, pinned c0d963d) — BLOCK (A, C); PASS (B)
Full report: `private/reviews/gen2-2b-final-astra-review-20261002.md`.

**ROOT-CAUSE:**
- **13d:** R13B-1 deadline renewal and late-result admission; R13B-2 admission under B; R13B-3 the WAL cause (100/100 stress runs in each journal mode); the late-reply test.
- **14:** items 0, 2, 3, 4, 5, 6 and F6.
- **Judgement calls:** SDMX-ML 2.1 only (BIS's published OpenAPI document gives SDMX 2.1 for data queries, and the adapter requests `format=sdmx-2.1` for structures); duplicate Content-Length refused; text identity; the snapshot report; Retry-After policy; 2e2 audit ownership; the wall-clock margins.
- **Two missing socket-mutant controls:** supplied by Astra.

Both targets pass independently.

**Open, as a finite list:**
- **F1 HIGH:** chunked framing is delegated to `http.client`, which parses sizes with permissive `int(x, 16)`, skips the CRLF check after data, and treats EOF as the end of trailers. So `\r\n0` + EOF, `+0`, `0x0`, signed sizes, `XX` in place of the CRLF, and a cut trailer all produce a successful count (0, 1 or 3). This shares the transport-completion cause with R13C-1.
- **F2 MEDIUM:** `getaddrinfo` sits outside the deadline. A slow resolver turned a 0.05 s exchange into 0.42 s; no late answer was admitted.
- **F3 MEDIUM:** the readiness helper uses an unbounded `readline` after `select`.
- **F4 LOW:** 8 test claims and 1 contract test (the cut-trailer test).

**Gateway family:** MITIGATION, open only at transport chunk framing. **Engine hand-off:** MITIGATION, open only at DNS.

**Routing:** a single **2b-repair-15** covers F1–F4 plus Astra's two mutant controls. DNS is fixed at the root: no exchange resolves names, and resolution happens outside any exchange deadline through an owned path. Any residual is reported to the operator, not claimed closed. Codex has reset to 6% of its 7-day window, so the earlier combined-review economy no longer applies.

## 2026-10-02 — 2b-repair-15 landed — Astra re-review dispatched
**Coder (Sonnet 5.5, `af1bd4de`):** `a5e3cd2..0d53bfc`.
- **F1:** `Transport` parses chunked bodies itself per RFC 9112 §7.1. Astra's ten wire captures are byte-identical regressions.
- **F2:** no exchange resolves a name; it connects to an IP literal or a pre-resolved map entry. The Host header, SNI and certificate check still use the name, and `endpoint_stale` marks a failed connection.
- **F3:** readiness is read under one deadline until the newline arrives.
- **F4:** the 9 test items are fixed, and Astra's socket controls are paired.

The coder reports both targets exiting 0 at `0d53bfc`.

**Residual, honestly reported:** the lookup itself, at client construction or in `resolve()`, is unbounded in-process, and no gen-2 code constructs the client yet. The options are:
- **(a)** build the client only inside supervised job children, so the job deadline bounds it;
- **(b)** a resolver child owned by the supervisor;
- **(c)** a bounded resolver written for the client;
- **(d)** accept the unbounded wait at start-up, with an owner and a removal condition.

**Operator ruling needed.**

**Orchestrator:** the oracle is unchanged and gen-1 is unchanged (PID 1040). Astra's re-review is `7efecde2`; its task is `private/reviews/gen2-2b-repair-15-review-task-20261002.md`.

## 2026-10-02 — Operator ruling: the DNS residual (2b-repair-15 F2)
**Option (a) is chosen.** A `GatewayClient` (and its `resolve()`) is constructed only inside a supervised job child. The supervisor's job `deadline_at` termination (SIGTERM then SIGKILL; `gen2/supervisor/supervisor.py`) bounds the lookup. No new code is needed now. 2e1 owns this as a wiring rule, and its review must verify there is no other construction site. This is recorded in BUILD-STATE's 2e1 entry. Astra's 2b-repair-15 review will be told of the ruling when it reports.

## 2026-10-02 — Operator ruling: Gate D sequencing after 2b (one-time)
2b's acceptance won't trigger its own Gate D. Gate D #2 reviewed the whole system that day, and 2q builds the ratcheted metrics Gate D relies on. **Gate D #3 runs at 2q's acceptance, before 2c starts.** The charter's cadence is otherwise unchanged.

## 2026-10-02 — Astra re-review of 2b-repair-15 (`7efecde2`, pinned 0d53bfc) — BLOCK (A, C); PASS (B)
Full report: `private/reviews/gen2-2b-repair-15-astra-review-20261002.md`.

**Gateway input contract: ROOT-CAUSE, closed under trust model B.**
- **F1:** `Transport` owns chunked completion per RFC 9112 §7.1.
- No new counterexample within the frozen contract.
- Normalization, member isolation, XML, snapshot and identity behaviour all stand.

**Engine:**
- **F2:** exchange-time resolution is removed. 0 resolver calls per exchange; a 0.05 s budget now holds at 0.02 s. TLS SNI and certificate checks stay correct.
- **F3:** readiness is closed.
- **F4:** all 9 items are closed.
- Six rebuilt mutants are killed. Both targets pass.

**Blocking:**
- **R15-1 (HIGH, engine hand-off):** `resolve()` keeps the old addresses when a re-lookup finds nothing, and `_exchange()` ignores `endpoint_stale`. An unrelated listener at the old address received the bearer token and returned an observation recorded as `searched_empty/complete/0/exhausted`. A test currently *requires* this fallback.
- **R15-2 (LOW):** one constructor-mutant control never reaches the constructor. Astra verified a replacement.

**DNS time residual:** Astra judged (a) the smallest mechanism if the placement fits. The operator ruled (a) earlier the same day, and 2e1 owns it.

**Routing:** **2b-repair-16** (engine only): a failed re-resolution or connection makes the endpoint unusable until the owner's `resolve()` succeeds; no connection and no token while stale; the test and mutant reversed; the control re-paired. This is the second consecutive BLOCK since Gate D #2; a third triggers Gate D.

## 2026-10-02 — 2b-repair-16 landed — Astra re-review dispatched
**Coder (Sonnet 5.5, `40675310`):** `a22496a`, `6b44bb2`.
- **Root cause:** the endpoint's addresses and an unread stale flag were two records of one fact. `GatewayClient._withdraw` now changes them together. A stale endpoint has no addresses until the owner's `resolve()` succeeds, so no connection is made and no token is sent; the result is `unknown/unobserved/null/failed`.
- **Tests:** Astra's probe has been rebuilt; zero requests reach the unrelated listener, and the move to a new address still works.
- **Mutants:** the mutants were reversed, all 8 `2B15-*` are killed, and the constructor control is re-paired.
- **Size:** +125 lines.
- **For 2e1:** after a connection failure, a gateway reached by name needs `resolve()`. Timeouts don't withdraw the endpoint, and an IP literal never goes stale.

**Orchestrator:**
- clean tree, `gateway/` unchanged, gen-1 unchanged (PID 1040);
- independent reruns in progress;
- Astra re-review `c8dd6ba4`, task `private/reviews/gen2-2b-repair-16-review-task-20261002.md`.

## 2026-10-02 — Astra re-review of 2b-repair-16 (`c8dd6ba4`, pinned 6b44bb2) — BLOCK (A, C); PASS (B)
Full report: `private/reviews/gen2-2b-repair-16-astra-review-20261002.md`.

**ROOT-CAUSE:**
- **The sequential R15-1 case:** the original probe, run unmodified, shows zero requests to the stale listener; the move to a new address works.
- **R15-2:** the constructor control was verified by trace.

**Blocking:**
- **R16-1 (HIGH):** `_withdraw()` doesn't coordinate with an exchange already running. `_connect()`'s iterator over the withdrawn list survives, so an exchange that started before withdrawal still connects, sends the token, and accepts `searched_empty/complete/0/exhausted`.
- **R16-2 (HIGH):** `_opener()` keeps urllib's automatic `ProxyHandler`. With `http_proxy` set, the connection goes to the proxy's literal address, so withdrawal is bypassed and the token goes through the proxy to an unrelated listener.

Both are client-output reproductions using ordinary APIs.

**Routing (charter):** this is the **third consecutive BLOCK since Gate D #2**: the final review, 15, and 16. A fresh-session **Gate D #3** (`e5989aa9`, task `private/reviews/gen2-gate-d-3-task.md`) runs before the next repair. It is to:
- name the engine hand-off guarantee and its family cause (endpoint authority is not a single owned fact);
- inventory every route by which a request can leave the client;
- set the client's threat model: concurrency, and the ambient environment;
- give a finite checklist.

The post-2q Gate D is renumbered #4.

## 2026-10-02 — Gate D #3 (fresh Astra `e5989aa9`, pinned 6b44bb2) — BLOCK, converging, with a finite engine finish line
Full report: `private/reviews/gen2-gate-d-3-astra-review.md`; evidence in `private/evidence/gate-d-3/`.

**Family cause:** endpoint authority is not one enforced fact across operation ownership and transport routing. This is behind R15-1, R16-1 (an overlapping exchange keeps its iterator over the withdrawn addresses) and R16-2 (ambient `ProxyHandler`).

The §3 inventory covers every route by which a request can leave `gen2/gateway_client`:
- public operations, URL construction, DNS, address fallback, IP literals;
- proxy and CONNECT, redirects, auth, cookies and global opener, other urllib handlers (FTP/file/data);
- environment variables;
- keep-alive, retries, polls, TLS, injected hooks.

**Checklist 0–7:**
- 0: one client contract;
- 1: one authority owner over all operations and the connect/send lifetime;
- 2: direct HTTP/HTTPS only (no proxies, no redirects, no non-HTTP handlers);
- 3: bounded lifetimes;
- 4: keep the timing contracts;
- 5: keep the hand-off and gateway contract;
- 6: validation, with mutants and controls;
- 7: a family account against the inventory.

**Threat model:** it recommends an enforced serial client per job, which is compatible with the source of truth: the design supports concurrent invocations, not shared client instances. Ignoring ambient proxies needs no ruling (DEPLOYMENT-CONTRACT §1).

**Reviewer boundary disclosure:** an initial AGENTS.md search ran recursively under `/home/trevor/work` and may have walked the live gen-1 tree's directory metadata. No file there was opened or operated on. Future task files will restrict discovery to ancestor directories.

## 2026-10-03 — Operator ruling: the client model
A `GatewayClient` **instance is serial**: an overlapping or re-entrant call on the same instance is refused before I/O. **Separate instances (one per station or job) must run fully concurrently**, proven by test. Operator: *"That's fine then as long as concurrent connections can run."*

**Routing:** 2b-repair-17 implements Gate D #3 checklist 0–7.

## 2026-10-03 — 2b-repair-17 landed (engine endpoint authority, Gate D #3 checklist 0–7) — Astra review dispatched
**Coder (Sonnet 5.5, `9c21fece`):** `46edc5e`..`4c360d0`.

**Root cause:** whether the client could do I/O was decided by four facts that could disagree:
- the cached address mapping;
- the stale flag;
- the live connect iterator;
- urllib's proxy choice.

**Fix:** one `_Endpoint` now holds the origin, the addresses (stale is derived from them) and the operation lease.
- `search` (across pages and polls), `grant` and `resolve` run under the lease. An overlap on the same instance raises `ClientBusy` before any I/O.
- Endpoint forms are http/https only.
- The opener has 4 HTTP handlers: no proxy, no redirect, no auth, no cookies, no FTP/file/data.
- All 17 routes in §3 are mapped to tests and mutants in `family-account.md`.

**Concurrency across instances is proven.** The loopback server sees N in flight for N = 2/8/32/64. The `2B17-instances-share-a-lock` mutant collapses that to 1 in flight.

**Results (coder):**
- 23 new mutants and 7 re-expressed ones;
- gen2-check 1,752 tests, 1,811/1,811 mutants;
- gen2-gateway 1,500+1,500 tests, 377 mutants;
- `gateway/` and the oracle unchanged;
- +1,357 lines (production +63).

**Orchestrator:** clean tree; gen-1 unchanged (PID 1040). Independent reruns are in progress. Astra review `5df3cb04`; task file `private/reviews/gen2-2b-repair-17-review-task-20261003.md`. If it closes, this is the 2b acceptance review.

## 2026-10-03 — Astra review of 2b-repair-17 (`5df3cb04`, pinned 4c360d0) — BLOCK (A, C); PASS (B)
Full report: `private/reviews/gen2-2b-repair-17-astra-review-20261003.md`.

**Removed structurally:** the operation-ownership race and the ambient-handler and proxy routes. The gateway input contract is still closed under B. Earlier ROOT-CAUSE items stand.

**R17-1 (HIGH):** connection authority still has two interpretations. `_Endpoint` classifies `urlsplit`'s raw host, so `127.0.0.%31` is a name. urllib then unquotes it to `127.0.0.1`, and `_connect` tries `_literal()` on the decoded host before consulting the owner's mapping. As a result, a withdrawn and NXDOMAIN'd endpoint sent a search and a grant, with the bearer token, to a replacement listener. The search was recorded as `searched_empty/complete/0/exhausted`. Ordinary name and literal controls behave correctly.

**Family verdict:** MITIGATION. Withdrawn owner state is not yet the sole prerequisite for network I/O.

**Routing:** **2b-repair-18**:
- one canonical origin, validated at construction: LDH names or `ipaddress` literals; percent-encoding, alternate numeric spellings and userinfo refused;
- `_connect` takes targets only from the owner's admitted addresses;
- Astra's probe rebuilt as a regression, plus a refused-spelling table and a mutant.

No operator ruling is needed. This is the first BLOCK since Gate D #3.

## 2026-10-03 — 2b-repair-18 landed — Astra re-review dispatched
**Coder (Sonnet 5.5, `e249eca5`):** commits `a831511`..`0d34df8`.

**Root cause:** the same URL string had two readings: the owner's, and urllib's decoded form tried as a literal at connect time.

**Fix:**
- A strict `_origin` parser runs at construction. It accepts http/https with an LDH name or an `ipaddress` literal, an optional port and an optional trailing `/`. It refuses percent-encoding, alternate numeric spellings, userinfo, zones, paths, queries, whitespace and non-ASCII.
- The canonical origin is the only text request URLs are built from.
- `_connect` takes targets only from the owner's admitted addresses.

**Tests:**
- Astra's probe is rebuilt to cover search, grant and poll. It fails on `4c360d0` and passes now.
- Controls: a plain name withdraws, a literal connects, and moving to address B works.
- 11 new `2B18-*` mutants.

**Results:** gen2-check 1,760 tests, 1,822/1,822 mutants; gen2-gateway 1,500+1,500 tests. `gateway/` is unchanged. Production code is +31 lines.

**Orchestrator:**
- clean tree; gen-1 unchanged (PID 1040);
- independent reruns in progress;
- Astra re-review is agent `f8ba3f2f`, task file `private/reviews/gen2-2b-repair-18-review-task-20261003.md`. If it closes, this is the 2b acceptance review.

## 2026-10-03 — Astra re-review of 2b-repair-18 (`f8ba3f2f`, pinned 0d34df8) — BLOCK (A); PASS (B, C)
Full report: `private/reviews/gen2-2b-repair-18-astra-review-20261003.md`.

**R17-1 is ROOT-CAUSE.** The endpoint owner is the sole source of connection targets. No remaining client path lets urllib, http.client or ssl override them; Host, SNI, IPv6 brackets, default port, A-labels and case folding were all checked. The lease, cross-instance concurrency and closed handlers stand.

**R18-1 (MEDIUM):** the port regex `[0-9]{1,5}` refuses zero-padded decimal ports of six or more digits (`:000080`, `:065535`), although H-6 defines a port by value (1–65535) and `:08765` is already accepted. This is unapproved input narrowing: compatibility, not a token leak.

**Routing:** **2b-repair-19** validates the port by value, with a documented cap on digit count, and adds Astra's five cases and the wire case as regressions plus a mutant.

Orchestrator reruns of 18 match.

## 2026-10-03 — 2b-repair-19 landed — Astra re-review dispatched
**Coder (Sonnet 5.5, `f06b02fb`):** commit `28a2e83`.
- **Root cause:** a five-digit text-width rule that H-6 never specified.
- **Fix:** the port is accepted as a run of 1–32 ASCII digits and range-checked by value; H-6 and DEPLOYMENT-CONTRACT state the rule.
- **Tests:** Astra's five cases and the wire case are now regressions. The new acceptance tests failed on the old client (9 failures). A `2B19` mutant was added.
- **Results:** both targets exit 0; 1,823/1,823 mutants killed; `gateway/` unchanged.

Astra's re-review is `6fac8e6c`. If it passes, this is the review that accepts 2b.

## 2026-10-03 — Astra re-review of 2b-repair-19 (`6fac8e6c`, pinned 28a2e83) — PASS (A, B, C). **TASK 2b ACCEPTED.**
Full report: `private/reviews/gen2-2b-repair-19-astra-review-20261003.md`.

**R18-1: ROOT-CAUSE, closed.**
- The port is validated by value, on a run of at most 32 digits, and H-6 states the rule.
- Independent domain check:
  - all 1,846,086 valid (value, width) constructions are accepted;
  - 65,535 33-digit paddings are refused before resolution;
  - 5,016 mixed forms are accepted and 2,337 invalid ones refused.
- Real-server matrix: 18 exchanges, with exact Host values and SNI, across HTTP and HTTPS, DNS, IPv4 and IPv6.
- R17-1 and the 17 acceptances are intact.

**Family verdicts:**
- **Gateway input contract:** ROOT-CAUSE, closed under B.
- **Engine hand-off:** ROOT-CAUSE, closed. The endpoint owner is the sole connection authority; the lease, concurrency across instances, closed routes, deadlines, admission and page outcomes all stand.

**Operator confirmation:** none newly required.

**Still the operator's (later phases):**
- merges and phase transitions;
- the real-data migration release;
- old-writer fencing before cutover.

**Owners:**
- 2e1: construction placement, runner isolation, env/credential allowlist.
- 2e2: retrieval-audit evidence.
- Phase 3 and Phase 4 items as recorded.

**Next:** 2q (2q-a: metrics, ratchet, debt register, locators; then 2q-b: structural consolidation). Gate D #4 runs after 2q, before 2c, per the operator's 2026-10-02 sequencing ruling.

## 2026-10-03 — 2q-a landed (metrics, ratchet, debt register, locators) — Astra review dispatched
**Coder:** Sonnet 5.5 `f5ac8d3c`, commits `0306df4`..`1e8dc9f`.

**Metrics:**
- `tools/gen2_metrics.py` (stdlib) runs in `gen2-check` and measures the engine and the gateway separately.
- It reproduces all nine Gate D tables byte for byte at the #1, #2 and #3 pins.

**Baseline:**
- **Engine:** 32 files, 60 edges, 14.16% propagation, no cycles, 132 mixin self-calls, 22 offenders.
- **Gateway:** 68 files, 216 edges, 11.92% propagation, an `adapters`/`core`/`registry` component cycle, 30 offenders, and three smells (hub `base.py`, unstable `schema→wire`, god component `core`).

**Ratchet and exemptions:**
- The baseline is digested.
- Rebaselining only tightens.
- Exemptions need a review, a removal condition and a limit. There are none.

**Debt register:**
- `docs/gen2/DEBT-REGISTER.md`, with `phase-status.json` and `gen2-debt`: a closed phase or task that still owns an open entry fails the build.
- No mitigations have been accepted.
- 13 owned obligations, DEBT-001..013, covering 2e1, 2e2, Phase 3 and Phase 4. The coder added DEBT-004 (the §4(d) ruling) and DEBT-011..013 (the Phase 3 items) beyond the brief. The orchestrator judges these consistent with the recorded operator rulings; no new decision is needed.

**Locators and mutants:**
- `gen2-locators` checks locators.
- Stale locators are reconciled: H-5, RG-9, §11, AUTH-DEMO and BUILD-STATE 1f.
- 157 mutants.

**Results:** no production change. gen2-check: 1,931 tests, 1,980/1,980 mutants. gen2-gateway: 1,500+1,500 tests, 377 mutants.

**Disclosed:**
- The smell thresholds are operating points.
- The locator check only sees backticked locators in INVARIANTS and the register.
- Three tests failed in the coder's traced snapshot run but pass in the real tree; they were not investigated. *(Corrected 2026-10-03 by Astra's 2q-a review F7 and task 2q-a-repair: they were not three failed behaviours. One, `test_the_helper_runs_children_from_the_named_tree`, depended on its environment: it assumed `GEN2_CHILD_ROOT` was unset, so in a run that names a tree it saw that tree instead of the repository's. The other two, `test_recovery_starts_nothing_once_the_lease_is_replaced` of `DelegateCrashTest` and `ResearchPassCrashTest`, are intentional skips in every run, ordinary or snapshot, with the reason in their skip message. The first is fixed and both facts are tested in `gen2/tests/test_child_root_environment.py`.)*

**Review:** Astra `8e5c3480`, task file `private/reviews/gen2-2q-a-review-task-20261003.md`.

## 2026-10-03 — Astra review of 2q-a (`8e5c3480`, pinned 1e8dc9f) — BLOCK (A, C); PASS (B)
Full report: `private/reviews/gen2-2q-a-astra-review-20261003.md`.

**Accepted:**
- **Historical reproduction is exact.** 27/27 tables match the tool's output and 27/27 match the archive at the Gate D #1, #2 and #3 pins. An independent graph computation agrees.
- **Phase-close mechanism.** Closing 2e1, 2e2, Phase 3 or Phase 4 correctly fails on their open entries.
- **The 13 register entries,** including the coder's four additions.
- **Locator reconciliation.**
- **Production identity is unchanged.**

**Findings (all ROOT-CAUSE repairs required):**
- **F1 HIGH:** `project_bases` doesn't resolve fully qualified bases. Rewriting the Router's bases in qualified form erased all 132 self-calls and 19 pairs, and the check and rebaseline both passed. Family order uses depth-first search rather than C3, so a diamond is misattributed, and overlapping families count the same site twice.
- **F2 HIGH:** the ratchet compares only functions currently above a threshold. A baselined function that went from CC 21/cog 0 to CC 8/cog 28 vanished from the comparison and was reported as an improvement.
- **F3 MEDIUM:** two carried obligations are missing from the register: the importer's unexamined-file inventory (Phase 4, needed before migration planning) and the Phase 3 usage estimator (operator request, 2026-09-29).
- **F4 MEDIUM:** a dotted locator is recognised only when its prefix resolves. Deleting the module turns the citation into unchecked prose, and a full `gen2...` path is never counted.
- **F5 MEDIUM:** per-module fan-in/out and instability are reported but not ratcheted, which narrows the charter without an amendment. A new real-tree edge (60→61) passed, and so did a probe where growth was hidden by a larger denominator.
- **F6 LOW:** a wrong statement in the threshold rationale.
- **F7 LOW:** the three "snapshot failures" were one test that depends on the environment plus two intentional skips.

**Routing:** **2q-a-repair** fixes F1–F7. F5 is enforced as the charter states, with no amendment. No operator ruling is needed.

## 2026-10-03 — 2q-a-repair landed — Astra re-review dispatched
**Coder (Sonnet 5.5 `9fc444b6`):** commits `1b5b81c`..`c87821e`.

**Fixes:**
- **F1:** the tool resolves the base-class surface and orders methods by C3. It counts each call site once, and an unresolved base fails the build. The qualified-name Router keeps 132/19.
- **F2:** offenders are compared on both dimensions.
- **F3:** DEBT-014 (importer inventory, which must exist before use) and DEBT-015 (usage estimator).
- **F4:** locators are recognised by grammar only.
- **F5:** gates added for unresolved bases, per-file fan-out, fan-in to stable files, and gained reach. Astra's edge probe now fails.
- **F6/F7:** fixed.

**Baseline:** v2, with new fields only.

**Results:**
- 51 new mutants.
- gen2-check: 2,005 tests, 2,027/2,027 mutants.
- gen2-gateway: 1,500+1,500 tests.
- 65 new tests fail on `1e8dc9f` and pass now.
- The 27/27 reproduction is intact, and there is no production change.

**Policy readings sent to review:**
- new and renamed files are held only by the aggregate measures until rebaseline;
- the fan-in rule counts only existing dependents of files that were stable at baseline;
- instability is judged by direction, not as a gate;
- `code:` and `history:` markers are unchecked author choices.

**Review:** Astra `98a9d2a6`, task `private/reviews/gen2-2q-a-repair-review-task-20261003.md`.

## 2026-10-03 — Astra re-review of 2q-a-repair (`98a9d2a6`, pinned c87821e) — BLOCK (A, C); PASS (B)
Full report: `private/reviews/gen2-2q-a-repair-astra-review-20261003.md`.

**Still holding:**
- the 27/27 reproduction;
- both targets pass independently;
- the policy readings on instability direction and on the code/history markers are sound.

**Family verdict: MITIGATION.** The tool derives its obligations from a lossy representation, and lost identity reads as removal or improvement. Findings:
- **R1:** a conditional, same-name `Router` takes the measured coupling from 132/19 to 0/0, while the runtime MRO is unchanged. Star re-export order also misattributes.
- **R2:** renaming or moving a function resets its threshold obligation.
- **R3:** new or renamed files are unmeasured until rebaseline. A real two-import `normalized.py` raises fan-in on stable `canonical.py` and `instants.py` and still passes.
- **R4:** a qualified locator resolves through the flattened short-name index.
- **R5:** two tests encode the exemption that should have been rejected, and two mutants are policy-sensitive.

**Routing:** **2q-a-repair-2** is a redesign at the family level:
- explicit identities, each in exactly one state (present, mapped or retired), with anything missing failing;
- every new budget admitted through a committed ledger with reasons, reviewed at Gate A (`make gen2-metrics-admit` drafts the entries, and a TODO reason fails);
- ambiguous bindings fail closed;
- locator lookup preserves scope.

This is the first coder on **GPT-6.1-Sol** (operator, 2026-10-03). It is the second consecutive BLOCK on 2q-a, so a third triggers Gate D.

## 2026-10-03 — 2q-a-repair-2 landed (identity ledger redesign; first GPT-6.1-Sol coder) — Astra re-review dispatched
**Coder:** GPT-6.1-Sol `e34b5045`, commits `35ffdd1`..`4f1ae96`.

**Root cause:** lossy indexes erased obligations and scope.

**Fix:**
- Baseline v3 tracks 1,051 persistent IDs. Each must be exactly one of present, mapped (budgets carried over) or retired; a missing ID fails.
- New budgets are admitted only through a committed, reasoned ledger entry. A `TODO` fails. `make gen2-metrics-admit` drafts entries, and `rebaseline` folds them in without inferring identity.
- Ambiguous bindings fail closed.
- Qualified locators keep their scope.
- The ledger is empty at this pin.

**Results:**
- All seven R1–R4 reproductions fail on `c87821e` and pass now.
- 216/216 tool mutants killed.
- gen2-check: 2,040 tests, 2,039/2,039 mutants.
- gen2-gateway: 1,500+1,500 tests.
- 27/27 reproduction holds; production unchanged.

**Review:** Astra `0da948d1` (third round on 2q-a; a BLOCK triggers Gate D). The task also asks for a proportionality judgement on how usable the admission step is for later tasks.

## 2026-10-03 — Astra re-review of 2q-a-repair-2 (`0da948d1`, pinned 4f1ae96) — BLOCK (A, C); PASS (B). Third consecutive BLOCK on 2q-a → Gate D #4
Full report: `private/reviews/gen2-2q-a-repair-2-astra-review-20261003.md`.

**What the ledger achieves.** It is a substantive improvement. Whole missing identities fail, mappings carry their budgets, and admissions need reasons. All seven R1–R4 reproductions are fixed, and the 27/27 reproduction holds. Both targets pass independently.

**Family verdict: MITIGATION.** The keys and their values are still derived from a lossy reading of the code:
- **R1:** a duplicate same-name function shifts the obligation by position, so 8/28 escapes as `f#2`.
- **R2:** with `Router._now` placed under `if True:`, measured coupling falls from 132 to 127 sites while all 19 pairs survive, so nothing fires. Aliases, class decorators that rebind, `__all__.append`, and the order of star imports versus explicit imports are all misread.
- **R3:** the admit draft conflicts with existing mappings.
- **R4:** six mutants are "killed" by a `KeyError` crash, not by the behaviour under test.

**Routing (charter):** a fresh **Gate D #4** (`f657c1c2`, task `private/reviews/gen2-gate-d-4-task.md`) decides:
- (A) full Python support, or (B) a declared supported-source subset, with forms outside it refused by gen2-check (the same approach as trust model B);
- a finite checklist;
- proportionality for later tasks;
- consolidation of the 2,000+-line tool.

The post-2q Gate D is renumbered #5.

## 2026-10-04/05 — CI design: Astra review, revision, re-review; operator rulings
- **Design:** `docs/gen2/CI-DESIGN.md`. It builds on the existing `trevorbyrum/ci-cd` platform (two Jenkins VMs, the `std` library, archgate) and the gen2 Jenkinsfile from PR #1.
- **Astra review 1** (`private/reviews/gen2-ci-design-astra-review-20261004.md`): **SOUND-WITH-CHANGES**, 10 findings. The four HIGH ones:
  - the diff-mutation selector and the full backstop were in the wrong order;
  - crash-kills happen at the subprocess boundary;
  - verifier qualification needs identity, cleanliness and evidence, and "five landings" is not enough;
  - the network-isolation claim was broader than the design could support.

  Revision 2 adopts all ten, plus Astra's implementation order.
- **Astra re-review** (`gen2-ci-design-rev2-astra-review-20261004.md`): **SOUND-WITH-CHANGES**. Remaining items:
  - RR1: a charter transition table;
  - RR2: event-bound freshness for the Gate D pack;
  - RR3: full source keys;
  - first-slice additions.

  All are applied in revision 2.1 (`73b9ed0`).
- **Operator rulings, 2026-10-05:**
  - **D1–D3 and D5–D11 approved as recommended.**
  - **D4 changed:** no GitHub Actions at all, because there are no paid minutes. Drift checks move to the Jenkins nightly mode.
  - **D2 charter amendment** recorded in BUILD-CHARTER: task branches and worktrees, PRs into `gen2`, operator merges, still one coder.
  - **D9 values:** accepted-review evidence is kept permanently, routine runs for 90 days, and nightly findings become tasks within 2 working days.
- **Confirmed defect, routed:** the gateway client's canonical origin depends on `ipaddress.__str__` (3.12.14 changed it). Root fix: project-owned canonical serialisation, plus pinning the reference environment (D5).

## 2026-10-05: Gate D #4 (rerun): the 2q-a architecture-metrics finish line
- **Rerun** in a fresh Astra session (`6544e498`), pinned 4f1ae96. The first session, `f657c1c2`, closed without producing a report. Report: `private/reviews/gen2-gate-d-4-astra-review.md`; evidence: `private/evidence/gate-d-4-rerun/`.
- **Verdict: BLOCK.** Astra chooses option **B**: exact computation of the declared metrics over a declared, guarded source subset, with one shared recognition boundary across both services.
- **Findings:**
  - **F1 HIGH:** source recognition can still change an obligation or lose part of a measurement while the checks pass (R1 and R2 open). Family: MITIGATION.
  - **F2 HIGH:** the acceptance boundary is implicit, and classified uncertainty can still pass.
  - **F3 MEDIUM:** admission drafting contradicts existing mappings (R3).
  - **F4 MEDIUM:** the six disputed mutants still crash rather than producing the wrong behaviour they are meant to show (R4).
  - **F5 MEDIUM:** duplicated source models have accumulated repair complexity.
- **Repair:** one family-level repair against checklist 0–8 (ratify, recognition boundary, production compatibility, R1/R2, R3, locators, R4, assembled pin, family closure). A shared source boundary plus an effective transition plan would be ROOT-CAUSE; more per-example exceptions would stay MITIGATION.
- **Production syntax inventory:** 100 files are almost wholly inside the proposed contract. The one exception is `_no_reading` in `gateway/research_gateway/core/payload.py`, which installs methods dynamically. Astra recommends replacing it with explicit methods while keeping the behaviour unchanged.
- **Operator rulings required:**
  1. adopt B and the supported-source contract, including an unwaivable refusal stage and amendments to repair-2's unresolved-classification claims;
  2. authorize the minimal production change (`_no_reading`) before 2q-a acceptance;
  3. approve its sequencing (inside the 2q-a repair, or as a 2q-b preparation slice ahead of acceptance).
- Not rerun by Astra: the full engine and gateway suites and their mutation campaigns. The earlier reruns at 4f1ae96 stand as prior evidence.
- **Operator rulings 2026-10-05** ("I agree"):
  - all three adopted: B and the supported-source contract, with repair-2's unresolved-classification permission withdrawn;
  - the `_no_reading` explicit-method replacement is authorized before 2q-a acceptance;
  - it is sequenced inside the 2q-a repair, so the family history continues.

  Routed to **2q-a-repair-3** (checklist 0–8). Coders return to Sonnet 5.5.

## 2026-10-05: 2b-repair-20 (project-owned canonical address serialization)
- **Astra** (`62ccbbd1`, pinned 5354346; `private/reviews/gen2-2b-repair-20-astra-review-20261005.md`): **PASS on A, B and C. ROOT-CAUSE. "2b-repair-20 is ACCEPTED."**
  - The serializer matches RFC 5952 §§4.1–4.3. The mapped hex spelling is the accepted contract (28a2e83), not drift.
  - Probes: 256 zero-run layouts plus 30,000 value-preserving samples. A real-wire probe on 3.12.3 and 3.12.14 found no other spelling producer.
  - R17-1, R18-1 and the 2b acceptance are intact.
  - No new operator confirmation is needed.
- **Orchestrator reruns at 5354346** (isolated clone): gen2-check exit 0 (2,044 tests, 2,040/2,040 mutants, 1,752 s); gen2-gateway exit 0 (1,500+1,500 tests, gateway mutants passed, 971 s). The coder's results are confirmed. **2b-repair-20 CLOSED.**

## 2026-10-05: 2q-a-repair-3 (the supported-source contract; family repair against the Gate D #4 checklist)
- **Astra** (`78dde6c8`, pinned dbe5dd4; `private/reviews/gen2-2q-a-repair-3-astra-review-20261005.md`; the first session `d1d4e515` stopped on a model-capacity error): **BLOCK on A and C, PASS on B, family MITIGATION.**
- **Accepted:**
  - checklist item 0;
  - item 4, the one transition plan (R3 ROOT-CAUSE);
  - the `_no_reading` replacement (734+800 differential comparisons, zero differences; the measurement change is honestly declared);
  - the six rebuilt R4 mutants;
  - the 27/27 historical reproduction;
  - Astra's own reruns: gen2-check exit 0 (2,178 tests, 2,151/2,151) and gen2-gateway exit 0 (1,516+1,516, 394/394).
- **Open:**
  - **F1 HIGH:** effective members aren't modelled. `__eq__`, or a bare `@dataclass`, sets `__hash__ = None` and masks an inherited method, which is still attributed to the ancestor.
  - **F2 HIGH:** prohibited binding and dispatch changes pass the guard: dataclass fields shadowing methods, external precedence through ancestors, module-attribute stores, walrus in annotations, `global` plus import, assigned hooks, and more. A stale qualified owner also passes the locator check.
  - **F3 HIGH:** the loader inventory checks text, not behaviour (`continue`→`pass` passes).
  - **F4 HIGH:** a killer that both fails an assertion and has an incomplete child still earns a kill, and exit 0/1 is taken as completion without a witness.
  - Disclosure corrections: a refused `report` does write partial artifacts; six test claims were rejected.
- **Routed** to **2q-a-repair-4** (Sonnet 5.5), which turns the guard into positive recognition (refuse every unrecognised binding or store kind) instead of a list of known bad forms. This is the first BLOCK since Gate D #4. No operator ruling is needed: the defects are within the ratified contract.
- The orchestrator corrected CI-DESIGN's T0 list so it names `gen2-source`.

## 2026-10-05: operator ruling, review throughput
- The operator adopted four rules after a research pass on speeding up the build (repair-loop returns, review size, gate-only full suites): blocking findings defined; re-reviews raise only blocking findings; a round cap at 3 consecutive BLOCKs, after which the operator decides; small slices; one full test run per round. All are recorded in BUILD-CHARTER "Review throughput".
- They apply from the next dispatch. 2q-a-repair-4's review (`ca0161ae`) already running is unchanged.
- Deferring 2q-b was offered and not adopted.

## 2026-10-05: 2q-a-repair-4 (positive recognition)
- **Astra** (`ca0161ae`, pinned 01fa8ad; `private/reviews/gen2-2q-a-repair-4-astra-review-20261005.md`), dispatched before the review-throughput rules: **BLOCK on A and C, PASS on B, family MITIGATION.**
- **ROOT-CAUSE within their scope:**
  - the effective-member (`__hash__`) correction: 144 hash cases agree with Python;
  - completion dominance: the mixed-crash mutant is now INVALID, and `os._exit`, suppressed excepthook, SIGTERM and timeout are all rejected. Under model B the record need not be unforgeable; the claim must be stated as detecting accidental incomplete execution.
  - all 16 rebuilt kills are valid.
- **Open:**
  - **F1 HIGH:** the recognition boundary still admits namespace mutation and unlisted producers (e.g. `namespace().A = object`). 40 closure probes produce zero refusals and a wrong attribution.
  - **F2 HIGH:** transformation recognition uses spelling where Python uses identity and composition (e.g. a string annotation ending in `ClassVar`).
  - **F3 HIGH:** the loader fingerprint omits the other definitions in the loader module, which execute at import.
  - Gate C: unsound positive expectations and unsupported claims.
- Astra's own reruns: gen2-check exit 0 (2,237 tests, 2,244/2,244); gen2-gateway exit 0 (1,516+1,516, 394/394). Orchestrator reruns match.
- **This is the second consecutive BLOCK since Gate D #4.** Under the review-throughput rules, a third goes to the operator (round cap). Before the next brief, the orchestrator asked Astra to classify F1–F3 under the new blocking definition, and whether an interpreter cross-check would close the family.

## 2026-10-05: 2q-a-repair-5 (slice 1: the binding-identity resolver), the first round under the review-throughput rules
- **Astra** (`9796d360`, pinned 3cd4716; `private/reviews/gen2-2q-a-repair-5-astra-review-20261005.md`): **BLOCK on A and C, PASS on B. The slice correction is MITIGATION.**
- **Repaired:** the four original cases (re-exported and unpacked loader, unpacked module, nonlocal). The landing run is green: gen2-check exit 0 (2,248 tests, 2,256/2,256); gen2-gateway exit 0.
- **Open, blocking:**
  - **F1 (d, e):** the shared lookup ignores `global` declarations when reading a name, giving a wrong class owner or a missed loader under nested-scope shadowing; an unresolved alias becomes an accepted call.
  - **F2 (e):** three new paired controls (`2QB-idx-unpacking-binds-no-value`, `2QB-idx-alias-cycle-is-external`, `2QB-con-decorator-identity-is-its-spelling`) don't reach the changed line or guard.
- **Non-blocking:**
  - two compiler-invalid `nonlocal` forms are accepted;
  - the four producer-call residuals (`loader-default`, `loader-walrus`, `loader-getattr`, `type-star`) need a named owner.
- **This is the third consecutive BLOCK since Gate D #4, so the round cap applies.** The orchestrator stopped dispatching, and the decision is the operator's: accept the remainder as debt, or continue, with a fresh Gate D first.
- **Operator ruling 2026-10-05 at the round cap.** After the research pass (`docs/gen2/research/2q-a-round-cap-20261005.md`, now required by the charter's "Research before re-briefing"), the operator ruled: "make the fixes, review it to make sure it didn't cause any other issues and then we'll move on."
  - The operator continues on the researched plan: scope from `symtable` (slice A, 2q-a-repair-6), then SOURCE-CONTRACT v2, soundy by declaration (slice B, 2q-a-repair-7): the mechanism ban plus a refusal of quoted class-body annotations, replacing value tracking. v2 is approved.
  - The pre-repair Gate D is skipped by operator direction. Gate D #5 after 2q still runs.

## 2026-10-05: 2q-a-repair-6 (slice A: scope from symtable)
- **Astra** (`471df716`, pinned 59b0536; `private/reviews/gen2-2q-a-repair-6-astra-review-20261005.md`): **BLOCK on A and C, PASS on B, family MITIGATION.**
- **ROOT-CAUSE for their findings:** the global/nonlocal repair, the compiler-invalid refusal, alias uncertainty, and the three controls. The landing run is green, and production measurements and the accepted items are intact.
- **New regressions from the adapter:**
  - **R6-1:** same-header generator scopes can be paired with the wrong `symtable` table, because the compiler visits the first iterable first.
  - **R6-2:** private names are looked up unmangled, so duplicate and rebound private methods are accepted.
- **Non-blocking:** the `get_type_hints` analogy wording; interpreter-version portability.
- The research addendum covers compiler visit order, two-way validation and mangling. Routed to **2q-a-repair-6b**.
- **Slice B (2q-a-repair-7) BLOCKED before coding** on three production uses of banned names; it's held for an operator decision.

## 2026-10-05: 2q-a-repair-6b (slice A fix: validated pairing, mangling)
- **Astra** (`752b23d2`, pinned a4deb99; `private/reviews/gen2-2q-a-repair-6b-astra-review-20261005.md`): **BLOCK on A and C, PASS on B, MITIGATION.**
- **Repaired:** R6-1's mispairing (ROOT-CAUSE) and R6-2's named examples. The landing run is green (gen2-check 2,271 tests, 2,282/2,282; gen2-gateway exit 0), and production is unchanged.
- **Open, blocking (one identity family):**
  - **R6B-1:** restored private members give a false cross-file self-call attribution, because member and attribute identity use the raw spelling.
  - **R6B-2:** mixed spellings (`__h` and `_C__h`) split one binding and hide a rebinding.
- A safe false refusal of valid annotation syntax is non-blocking.
- This is the second consecutive BLOCK since the operator's continue ruling.
- **Repo fact:** production contains **no** private (mangled) names.
- **Operator ruling 2026-10-06 ("Both recommended"):**
  - (A) the three production uses of banned mechanisms (`jobs.py` thread-local `__dict__`; `payload.py` `object.__setattr__` in `Sealed`/`Passive.__init__`) become named exact-statement exceptions in SOURCE-CONTRACT v2, with no production change;
  - (B) private name-mangled identifiers are refused in production code, which uses none. This closes R6B-1 and R6B-2 by removing the form.

  Both are folded into **2q-a-repair-7**, the final 2q-a slice. The non-blocking items from the 6 and 6b reviews are DEBT-017.

## 2026-10-06: 2q-a-repair-7 (the final 2q-a slice: SOURCE-CONTRACT v2)
- **Astra** (`2f7dce26`, pinned 5d87a8e; `private/reviews/gen2-2q-a-repair-7-astra-review-20261006.md`): **BLOCK on A and C, PASS on B, family MITIGATION.**
- **Retained:** production measurements and the accepted work (hash/effective members, scope, completion, the plan, the historical reproduction). The landing run is green (gen2-check 2,310 tests, 2,302/2,302; gen2-gateway exit 0). The approved v2 exclusions are not reasons for the verdict.
- **Open, blocking:**
  - **R7-1:** an ordinary alias or re-export of `builtins` (`bi = builtins; bi.setattr(A, ...)`) bypasses the mechanism ban, because the ban doesn't use the shared identity resolver.
  - **R7-2:** an exact payload exception statement can write through a different parameter, or from a static method, because the exception doesn't validate that the target is the method's receiver.
- **Non-blocking:** a file-wide builtin-alias set causes a false refusal (`import re as b` in another function).
- **Repo fact:** production never references `builtins`.
- **This is the third consecutive BLOCK since the operator's continue ruling, so the round cap applies.** Held for the operator.
- **Operator ruling 2026-10-06 ("Close and move on"): task 2q-a CLOSED at the round cap.** R7-1, R7-2 and the non-blocking builtin-alias false refusal are an **operator-accepted mitigation, DEBT-018** (owner: task 2q). They are fixed in a 2q tooling slice with DEBT-016 and DEBT-017 before 2q closes and before Gate D #5. **2q-b proceeds in slices; 2q-b1 (break the gateway component cycle) is dispatched.**

## 2026-10-06: 2q-b1 (break the gateway component cycle)
- **Astra** (`7f06aa53`, pinned aa49b06; `private/reviews/gen2-2q-b1-astra-review-20261006.md`): **PASS on A, B and C. ROOT-CAUSE, including at family level. "2q-b1 is ACCEPTED."** No blocking findings.
- **Confirmed:** contracts now live in their owning layer, with no hidden imports. An independent AST graph reproduced the metrics: the component cycle is gone, reach 49→43 and 551→547. 0 refusals under v2.
- The landing run is green: 2,310 tests; 2,302/2,302 engine and 396/396 gateway mutants.
- **Non-blocking:** NB-1 (the interface test hard-codes `correlation`), NB-2 (exception `__module__` pickling bound), NB-3 (ledger prose) are registered as DEBT-019, owned by task 2q.

## 2026-10-06: 2q-b2 (the Router explicit-collaborator pattern on Status and Capabilities)
- **Astra** (`22aaf34e`, pinned 193ee7b; `private/reviews/gen2-2q-b2-astra-review-20261006.md`): **PASS on A, B and C. ROOT-CAUSE. "2q-b2 is ACCEPTED."** No blocking findings.
- **On the pattern:**
  - It's sound to replicate, and the consumer-owned protocols are legitimate dependency inversion. The local `Rows` and `Schemas` protocols are legitimate interface segregation, not measurement-dodging.
  - Visibility is at the protocol-declaration level; the import graph doesn't certify a complete runtime dependency graph.
  - `_snapshot()` isn't an enforced read-only transaction. The transaction semantics (`BEGIN IMMEDIATE`, the post-lock clock read) are preserved.
- **Non-blocking:** stale evidence summaries; the differential masks can erase semantic differences; don't widen the pattern's enforcement claims. Registered as DEBT-020.

## 2026-10-06: 2q-t1 (the 2q tooling slice: DEBT-016, DEBT-017, DEBT-018)
- **Astra** (`07183765`, pinned 32489d9; `private/reviews/gen2-2q-t1-astra-review-20261006.md`): **PASS on A, B and C. ROOT-CAUSE within the v2 subset. "2q-t1 is ACCEPTED; DEBT-016, DEBT-017 and DEBT-018 are closable."**
  - R7-1 is closed by refusing the `builtins` module reference at its source.
  - R7-2 is closed by whole-function pins plus a required method context.
  - Every DEBT-016 and DEBT-017 item is confirmed.
- The landing run is green: 2,326 tests, 2,319/2,319; gateway 1,518+1,518.
- **The orchestrator closed DEBT-016, DEBT-017 and DEBT-018**, including the operator-accepted mitigation, which is now removed. One non-blocking stale doc example is DEBT-021.

## 2026-10-06: 2q-b3 (the Registries collaborator; a field-aware differential)
- **Astra** (`432cc7c7`, pinned 8e73b42; `private/reviews/gen2-2q-b3-astra-review-20261006.md`): **PASS on A and B, BLOCK on C.**
  - **The Registries conversion is ROOT-CAUSE**: 34 public signatures are unchanged and all 15 bodies are AST-identical modulo two rewrites. No production regression.
  - **Both deviations are ACCEPTED:**
    - the `_transaction()` exceptions preserve behaviour and sole-writer semantics;
    - the per-pair budget transfers are exactly accounted. A falling total can't pay for unrelated growth.
  - **Rulings for later Router slices:** keep the `_guarded` paths, with no new raw transactions without a concrete existing path and a semantics review; `_snapshot` stays limited; exact transfer accounting.
- **Blocking (Gate C):**
  - **C1:** the differential normalisation is still lossy: field names everywhere, global substring replacement, ranks erase durations, sorted ordered lists, mutable capture aliasing.
  - **C2:** unstable baselines silently fall back to outcome-only success. Astra altered an answer and removed a store observation, and the comparator still returned 0 differences.
- **Non-blocking:** NB1 (snapshot test wording), NB2 (no per-write store observation for the registry routes).
- **The family recurs** (DEBT-020 (2) → C1/C2), so the research step ran: `docs/gen2/research/2q-b-differential-20261006.md` (control nondeterminism at the seams; exact comparison; fail closed; mechanical-move AST equivalence as a second oracle). Routed to **2q-b3b**, which is queued behind the running 2q-b5 coder. The remaining Router slices wait for it.

## 2026-10-07: 2q-b4 (decompose the gateway's `_decode`)
- **Astra** (`ea8e980f`, pinned 8a59308; `private/reviews/gen2-2q-b4-astra-review-20261006.md`): **PASS on A, B and C. ROOT-CAUSE within the supported-input contract. "2q-b4 is ACCEPTED."** No blocking findings.
- **Confirmed:** the extracted bodies match the old branches, the modifier semantics are preserved, and normalizer liveness is kept.
- **Non-blocking:** NB-1 (a hypothetical `token` normalizer's precedence; not used in production), NB-2 (re-anchor count 50, not 51), NB-3 (a control name overstates its assertion). Registered as DEBT-022.

## 2026-10-07: 2q-b5 (split `adapters/base.py`)
- **Astra** (`f7609fc9`, pinned f33c18f; `private/reviews/gen2-2q-b5-astra-review-20261006.md`): **PASS on A and B, BLOCK on C.**
  - **The production split is ROOT-CAUSE.** 49 of 50 old definitions are AST-unchanged, `parse_links` is decomposed faithfully, and there is no behaviour regression.
  - **Costs accepted:** the `base.py → _transport.py` smell is a coherent composition edge, and the graph growth is justified by parser simplification plus 31 files losing their reach to `core/uri.py`.
- **Blocking (evidence only):**
  - **C1:** the drivers' normalisation erases semantics: whole-URL masks, timestamp substitution inside provider `raw`, object/list loss, downloads unobserved.
  - **C2:** the comparator accepts empty corpora as 0 differences.
  - **C3:** two scanner-mutant controls never call their scanners.
- **The differential family recurs** (2q-b2, 2q-b3, now 2q-b5, in drivers inherited since 13c), so the research addendum was written: one shared exact core with manifest completeness and fail-closed verdicts. Routed to **2q-e1**, which re-certifies 2q-b5 and, as confirmation, 2q-b4 and 2q-b1.

## 2026-10-07: 2q-b3b (the Router behaviour-preservation oracle, rebuilt)
- **Astra** (`c0bd81d1`, pinned 504372f; `private/reviews/gen2-2q-b3b-astra-review-20261007.md`): **Gate C PASS, with A and B standing. ROOT-CAUSE. "2q-b3b is ACCEPTED and 2q-b3 is ACCEPTED."**
  - C1 (no scrubbing; deep capture), C2 (fail closed), NB1 and NB2 are all RESOLVED.
  - The combined evidence (move AST identity plus exact replay plus an honest unresolved list) is sufficient for pure-move Router slices.
- **Rulings for Lifecycle, Scheduling and Amendments:**
  - an exhaustive move mapping and AST identity, with constructors, delegates, imports and bases inspected by hand;
  - exact replay with immediate store observations for write routes;
  - `_guarded` semantics preserved, with no new raw transactions;
  - independent targeted evidence outside stable replay coverage;
  - multi-row fixtures before relying on ordering.
- **Non-blocking:** 352 unresolved scenarios (process identity, concurrency), two ordering negative controls undetected, observation accounting. Registered as DEBT-023.

## 2026-10-07: 2q-t2 (DEBT-019, DEBT-021, DEBT-022)
- **Astra** (`f4d7e932`, pinned 642a0ef; `private/reviews/gen2-2q-t2-astra-review-20261007.md`): **PASS. "2q-t2 is ACCEPTED; DEBT-019, DEBT-021 and DEBT-022 are closable."**
- The documented extension policy for DEBT-022 NB-1 is accepted: the precedence before the split was mixed, so a swap would have changed six kinds.
- The landing run is green: 2,343 tests, 2,322/2,322; gateway 1,538+1,538, 413/413.
- **The orchestrator closed DEBT-019, DEBT-021 and DEBT-022.**

## 2026-10-07: 2q-e1 (the shared gateway differential core)
- **Astra** (`720d74ce`, pinned f1868f3; `private/reviews/gen2-2q-e1-astra-review-20261007.md`): **Gate C BLOCK; 2q-b5 still not accepted.** The production split stays ROOT-CAUSE, and no production regression was found.
- **Resolved:** C3. The timestamp, container and download cases from C1 are fixed at their cause.
- **Open:**
  - **C1:** `loopback()` still substitutes by spelling through whole strings, so loopback-looking data in a path, query or fragment, or literal `<port>` text, collapses. Astra showed a real-driver reproduction where an invalid next link came out EQUIVALENT.
  - **C2:**
    - zero drivers or missing directories certify EQUIVALENT;
    - a failed shared generator's partial output becomes the frozen inventory;
    - erased observation envelopes pass schema checks.
- This is the second consecutive BLOCK on the evidence family (2q-b5, 2q-e1). Research addendum (2) was added: parse, don't substitute; the inventory comes from validated inputs. Routed to **2q-e2**. A third BLOCK goes to the operator.

## 2026-10-07: 2q-b6 (the Router Lifecycle collaborator)
- **Astra** (`b8b0bc6a`, pinned 8bc87cc; `private/reviews/gen2-2q-b6-astra-review-20261007.md`): **PASS on A, B and C. ROOT-CAUSE. "2q-b6 is ACCEPTED."**
  - All five 2q-b3b rulings conform: 13 of 13 bodies identical; 29 dispositions reviewed; replay reproduced at 658/0/352; `_guarded` preserved.
- **Non-blocking:** serial mutation-harness module contamination; the `Rows` docstring overstates transaction scope. Registered as DEBT-025. The carried replay coverage and ordering items are already DEBT-023.

## 2026-10-07: 2q-b7 (the Router Scheduling collaborator)
- **Astra** (`d85ec3e7`, pinned 528c58e; `private/reviews/gen2-2q-b7-astra-review-20261007.md`): **PASS on A, B and C. ROOT-CAUSE. "2q-b7 is ACCEPTED."**
  - The five rulings are satisfied: 14 of 14 bodies identical; 20 dispositions; replay 658/0/352 recomputed; 7,428 readable immediate rows.
- **Non-blocking:** serial mutation-harness contamination, the same as DEBT-025 NB1 and addressed in 2q-t3 (in review); the carried replay and ordering coverage is DEBT-023.

## 2026-10-07: 2q-b8 (the Router Amendments collaborator, the last mixin)
- **Astra** (`bbf7d409`, pinned 8f59e6f; `private/reviews/gen2-2q-b8-astra-review-20261007.md`): **PASS on A and B, BLOCK on C.**
  - The production conversion is ROOT-CAUSE: 20 of 20 bodies identical; 24 dispositions accepted; replay 658/0/352.
  - **C1 (MEDIUM, class d):** two metrics regression tests depend on a mixin-composed production Router and break at `class Router:`. The orchestrator's landing run caught this, as designed.
- Routed to **2q-b8b**, which retargets the tests to a frozen fixture, keeping `RouterInMiniatureTest`. Skipping or weakening the tests would be a MITIGATION.

## 2026-10-07: 2q-b9 (decompose `Router._write_evidence`)
- **Astra** (`8a9fd4a0`, pinned d649d51; `private/reviews/gen2-2q-b9-astra-review-20261007.md`): **PASS on A and B, BLOCK on C.**
  - The production decomposition is ROOT-CAUSE: 55/96 → 14/14, with the helpers under the thresholds.
  - **C1 (MEDIUM):** the inline-back checker certifies behaviour-changing plumbing as IDENTICAL (scalar versus tuple returns and targets, `@staticmethod`, `async def`).
  - **L1:** inherits the 2q-b8 test failures.
- **Non-blocking:**
  - NB1: `service.py` headroom. Astra advises moving the evidence-writing unit into an `EvidenceWriter` collaborator before `_commit_in_transaction`.
  - NB2: wording.
  - NB3: the replay limit (DEBT-023).
- Routed to **2q-b9b** (the checker grammar plus NB2). L1 goes with 2q-b8b. NB1 shapes the next Router structure slice.

## 2026-10-08: operator ruling, established refactoring and verification tools
- **The operator asked why we write custom proof tools, and for research on established practice.** Research note: `docs/gen2/research/refactor-verification-20261008.md`:
  - refactoring engines (`rope`, LibCST);
  - refactoring detection (RefactoringMiner 3.x for Python, PyRef);
  - characterisation and approval tests;
  - Hypothesis old-versus-new differential properties;
  - `time-machine` and seeded determinism;
  - an LLM as a triage oracle, not a proof.
- **Ruling 2026-10-08:** "Okay, then do that. You have my authorization."
  - It approves the dev-only dependencies (`rope`, `hypothesis`, `time-machine`, and RefactoringMiner or PyRef) and a one-slice trial: **2q-r1**, queued behind the small 2q-b8b test fix.
  - 2q-b9b (the custom stitch-back checker fix) is **held** pending the trial. 2q-t4 (hand-built replay seams; commit `5ef2130` of 3, after the coder session ended) is **paused**; the trial tests whether `time-machine` and seeded fixtures replace it.
- **Session recovery note:** the previous orchestrator session ended mid-flight.
  - The 2q-e2 landing run and Astra review (`ab6b6af6`) didn't complete, with no report, so they'll be redone.
  - Astra's 2q-t3 review (`a3e11f6a`) completed: **no blocking finding**, and DEBT-024, DEBT-025, DEBT-023 items 2–3 and DEBT-020 are closable. Final acceptance is pending a landing record, which also inherits the two 2q-b8 test failures.

## 2026-10-08: 2q-r1 (trial of established tools)
- **Coder report** (`ac72fe8`; `docs/gen2/research/refactor-verification-trial-20261008.md`):
  - **Hypothesis `old == new`: worked.** On the 2q-b4 decoder: 150k cases with 0 differences, 100% line coverage, and 17 of 17 behaviour-changing mutants caught within 5.6 s.
  - **rope plus RefactoringMiner: partly worked.**
    - rope reproduced the 2q-b9 split in 1.2 s, but with one spurious parameter, a rope fault that the existing tests caught in 19 s.
    - RefactoringMiner reported exactly the five Extract Methods. It describes changes and doesn't prove behaviour.
  - **time-machine and seeded ids: partly worked.** They cover the test process only, not child processes or the real job-process identity; a 9-line fingerprint mock fixed one scenario.
  - **Dependencies:** `rope`, `hypothesis` and `time-machine` are hash-locked as dev-only; the RefactoringMiner image is pinned by digest.
- **Adopted under the operator's 2026-10-08 authorisation:** the charter's new "Refactor evidence standard" rule. **2q-b9b is dropped.** 2q-b9's evidence is re-judged under the new standard. 2q-t4's process-identity seam stays needed, in reduced form.

## 2026-10-08: 2q-t3, landing confirmation
- **Astra** (`f1339f58`): the combined run at `623576e` covers the reviewed pin. **"2q-t3 is ACCEPTED."**
- **DEBT-020, DEBT-024 and DEBT-025 are CLOSED.** DEBT-023 items 2–3 are done; item 1 (352 unresolved scenarios) stays open. The partial 2q-t4 work is not accepted.

## 2026-10-08: 2q-b8 and 2q-b9 re-review (under the "Refactor evidence standard")
- **Astra** (`47e85d9b`; `private/reviews/gen2-2q-b8-b9-astra-rereview-20261008.md`): **PASS on A, B and C for both. "2q-b8 is ACCEPTED." "2q-b9 is ACCEPTED."**
- **2q-b8 C1:** resolved as ROOT-CAUSE by 2q-b8b's frozen fixture (15 files byte-identical to `f216133`; 132/19 reproduced).
- **2q-b9:** C1 is resolved as a blocker under the amended standard. The checker is advisory with no gate credit. L1 is resolved by the green combined run.
- **Non-blocking:** documentation that still credits the inline-back checker, plus the remaining documentation closeout. Registered as DEBT-026.

## 2026-10-08: 2q-e2 (the gateway differential core, completed)
- **Astra** (`095a9dbb`, pinned 15bac9a, fresh session; `private/reviews/gen2-2q-e2-astra-review-20261007.md`): **Gate C PASS, with A and B retained. "2q-e2 is ACCEPTED; 2q-e1 and 2q-b5 are ACCEPTED."**
  - C1 (a structural `LoopbackURL`) and C2 (the inventory comes first; validated envelopes) are RESOLVED as ROOT-CAUSE, and **the evidence family is now ROOT-CAUSE.** Astra reproduced on the real driver that the repaired core gives DIFFERENT where the old one gave EQUIVALENT.
  - The round cap was not triggered.
- **Non-blocking:** nothing new. The DEBT-024 prose it mentions was already corrected in 2q-t3 (`a3d1b34`, after this pin) and is closed.

## 2026-10-08: 2q-b10 (the `EvidenceWriter` collaborator) and the 2q-r1 tooling
- **Astra** (`adbb7b7e`, pinned 93e8338; `private/reviews/gen2-2q-b10-astra-review-20261008.md`): **PASS on A, B and C. ROOT-CAUSE. "2q-b10 is ACCEPTED; the 2q-r1 tooling is ACCEPTED."** This is the first slice under the "Refactor evidence standard". Astra reran the rope driver and the outputs matched.
- **Detector and deps:** RefactoringMiner (digest-pinned, `--network none`, `--pull never`) is accepted as descriptive tooling, not a behaviour gate. The dev deps are accepted.
- **Replay:** the 352 → 6 count is validated, but **2q-t4's seam isn't accepted**. Its own review must cover:
  - parent and child identity consistency and distinctness;
  - opting out;
  - child activation;
  - the poll schedule;
  - a repeated comparison on `c02fa74` → `8bc87cc`;
  - negative controls for identity, fencing and result binding;
  - the five real-identity assertions kept intact.
- **Non-blocking:** NB2 (flaky mutation-verdict diagnostics), NB3 (ENVIRONMENT and BOUNDARIES wording), NB4 (the detector's exit code). Registered as DEBT-027.

## 2026-10-08: 2q-b11 (decompose `_commit_in_transaction`)
- **Astra** (`91e077f9`, pinned 7e59054; `private/reviews/gen2-2q-b11-astra-review-20261008.md`): **PASS on A and B, BLOCK on C on L1 only.** The landing run failed on one test, `test_children` readiness: a flake under load that passes 10 of 10 alone, with no related change, and is registered as DEBT-028. **The production extraction is supported** and all three new tests are accepted.
- The orchestrator is repeating the landing run on an idle machine (`private/evidence/2q-b11/orchestrator/`; attempt 1 is in `orchestrator-attempt1/`).
- **Session recovery:** the orchestrator session ended again around 16:46 UTC. The 2q-t4b coder (`157195fc`, commits `e9d090e` and `5de8d7f`) was interrupted before its replays ran; it has been resumed.

## 2026-10-09: PAUSED by the operator ("Pause the work")
- **Cause of the repeated "session cut-offs":** the `agent-hub` VM (16 GB, 6 vCPUs) ran out of memory three times (10-07 09:10, 10-08 16:46 and 17:54). Each time, the OOM killer took down the whole paseo.service with every agent and orchestrator job, because overlapping landing runs, replays and agent tests exhausted memory. The tower has about 1 TB of RAM and 128 cores; the orchestrator has recommended raising `agent-hub` to 64 GB and 16–24 vCPUs (the operator's action).
- **2q-b11's repeated landing run** (on a mostly idle machine, as a systemd unit) **failed the same test again**: `test_children` readiness ("database is locked", the child classified as still running at 5.0 s). It passes alone 10 of 10 times, and it passed in 2q-b10's landing run. **The earlier "flake under load" reading (DEBT-028) is therefore doubtful.** This could be a test-isolation or lock interaction that appears in the full suite at 2q-b11; the cause is unknown and needs investigating before 2q-b11 is accepted.
- **2q-t4b:** commits `e9d090e` and `5de8d7f`; the replay pair 1 finished (before-1, after-1), and pair 2 was stopped by the pause. The coder (`157195fc`) is stopped.
- **Nothing is running.** Resume from: investigate the 2q-b11 landing failure; finish the 2q-t4b replays and review; the 2q debt slice (DEBT-026, DEBT-027, DEBT-028); Gate D #5.

## 2026-10-09: RESUMED (the operator raised `agent-hub` to 24 vCPUs and 62 GB)
- **2q-b11 landing investigation:** the readiness failure is a race in the **test helper** `gen2/tests/children.py::started`, not in 2q-b11's change. `poll()` runs immediately after EOF, while an exiting child can still be unreaped.
  - Evidence: full `gen2-test` runs at 2q-b11 (twice) and 2q-b10 (once) all pass on the new VM (`private/evidence/2q-b11/investigation/`).
  - DEBT-028 is updated with the cause and fix.
  - Landing attempt 3 at `7e59054` is running.
- 2q-t4b has resumed: rebuild `/tmp`, then replay pairs 2 and 3.

## 2026-10-09: 2q-b11, L1 confirmation
- **Astra** (`0354cd4e`): L1 is resolved by landing attempt 3 at `7e59054` (2,430 tests; 2,382/2,382 engine and 413/413 gateway mutants). The helper-race attribution is credible; DEBT-028 stays non-blocking until 2q-t5's fix. **"2q-b11 is ACCEPTED."**
- **2q-b's planned structural items are all accepted:** the gateway cycle; all six Router mixins as collaborators; `_decode`; `adapters/base.py`; `_write_evidence`; `EvidenceWriter`; `_commit_in_transaction`.

## 2026-10-09: 2q-t4b (the replay seams for real processes)
- **Astra** (`f1467d28`, pinned 5de8d7f; `private/reviews/gen2-2q-t4b-astra-review-20261009.md`): **PASS on A, B and C. "2q-t4b is ACCEPTED. DEBT-023 item 1 is closable."**
  - Identity is consistent and distinct, with 0 real or fixed leakage and 0 duplicates.
  - The opt-out is ROOT-CAUSE.
  - Child activation and the poll wait are qualified as a bounded mitigation.
  - The 7 unresolved scenarios are accepted with bounded contract evidence.
  - The landing run at f356814 is green.
- **DEBT-023 is CLOSED.** **Non-blocking:** NB1 evidence wording and NB2 test titles, registered as DEBT-029, owned by phase 2.

## 2026-10-09: 2q-t5 (DEBT-026, DEBT-027, DEBT-028), and task 2q closed
- **Astra** (`9cf2cbfe`, pinned 96d9541): **PASS on A, B and C. "2q-t5 is ACCEPTED; DEBT-026, DEBT-027 and DEBT-028 are closable."** The readiness race is fixed with a forced regression; the verdict diagnostics, environment and replay wording, and the detector exit code are corrected; the inline-back claims are superseded.
- **The orchestrator closed DEBT-026, DEBT-027 and DEBT-028, and set task 2q to `closed` in phase-status.json.** No 2q-owned entry is open.
- **Gate D #5 dispatched** in a fresh session; it must pass before 2c.

## 2026-10-09: GATE D #5 (whole system after 2q): PASS
- **Astra, fresh session** (`c4ecca2b`, pinned 03b9b16; `private/reviews/gen2-gate-d-5-astra-review.md`): **PASS. "Task 2c may start. No prerequisite repair is required."** There is no realistic blocking-class defect.
  - **2q-b both reduced and moved coupling:** the gateway cycle is gone and the Router collaboration is explicit, but coordination is still concentrated in the Router.
  - **The evidence tooling is proportionate** under the accepted limits; the inline-back checker stays advisory.
- **F1 (Medium):** Router headroom. Keep 2c arithmetic in `gen2/accounting` (DEBT-030, owner 2c).
- **F2 (Low):** stale summaries and the 2q-b11 NB1 and NB2 dispositions (DEBT-031, owner phase 2).
- **Readiness for 2c:** the structure is fit. 2c's deliverables are as planned:
  - denominators from durable inventories, keeping the four units and unknown distinct;
  - attributable semantic assessments and lineage;
  - only the implemented evaluators;
  - lossless disposition and confidence reconciliation;
  - the four fixture cases.

## 2026-10-09: 2c-1 (the accounting component and the four candidate units): round 1 BLOCK
- **Astra** (`351f8d18`, pinned bd0a989; `private/reviews/gen2-2c-1-astra-review-20261009.md`): **BLOCK on A, PASS on B, BLOCK on C.**
- **What conforms:**
  - E-1, E-2, E-3, E-5, E-7 and E-8;
  - the four units and unknown handling;
  - accounting is pure, and the Router reads in one snapshot;
  - DEBT-030 placement (`service.py` +11);
  - 13 tests and 12 mutants accepted.
- **Blocking (one family, a lossy window projection; E-4 is a MITIGATION):**
  - **F1:** the exact request hash lets equivalent searches earn extra windows.
  - **F2:** dropped ancestry hides failed or partial delegates from the parent's window.
  - **F3:** an exhausted tail page is accepted without its captured prefix.
- **Non-blocking, folded into the repair:**
  - **N1:** complete multi-page searches are rejected.
  - **N2:** non-paging work erases a valid find window.
- **Landing run at bd0a989: green.**
  - `gen2-check`: 2,454 tests; 2,394 of 2,394 mutants killed.
  - `gen2-gateway`: 1,540 tests twice; 413 of 413 mutants killed.
- **Routed:** to `docs/gen2/tasks/2c-1-repair-1.md` (round 1 of 3), Sol coder.

## 2026-10-09: 2c-1 round 2 (2c-1-repair-1): PASS, and 2c-1 accepted
- **Astra** (`06337c12`, pinned 2339991; `private/reviews/gen2-2c-1-r2-astra-review-20261009.md`): **A, B and C all PASS, ROOT-CAUSE. "2c-1 is ACCEPTED."**
- **F1 closed:** search identity is separate from capture identity, and it mirrors the gateway's normalised find form. A comparison against the gateway's own function pins the mirror; the reviewer checked another 40 forms against it.
- **F2 closed:** delegate trees are traversed, and the scope stays per window. The reviewer added a three-level tree as a probe.
- **F3 closed:** a search needs the full linked page chain, from page 1 to an exhausted last page.
- **N1 and N2** were confirmed as positive controls.
- **Landing run at 2339991: green.**
  - `gen2-check`: 2,470 tests; 2,406 of 2,406 mutants killed, including 24 accounting mutants.
  - `gen2-gateway`: 1,540 tests twice; 413 of 413 mutants killed.
- **No new non-blocking items.** 2c-2 dispatched (`docs/gen2/tasks/2c-2.md`).

## 2026-10-09: 2c-2a (attributable semantic assessments and source lineage): round 1 BLOCK, on the landing gate only
- **Context:** 2c-2 was split at the design stage (~900 lines estimated). 2c-2a was coded by Sol `647d8de0` and landed at `bfe0975`.
- **Astra review** `07b3a13b` (`private/reviews/gen2-2c-2a-astra-review-20261009.md`): **A PASS, B PASS, C BLOCK, all ROOT-CAUSE.**
- **What passed:**
  - **Admission:** limited to authorized actors, with attribution set by the Router.
  - **Storage:** immutable DDL with foreign keys and a binding trigger; replay-safe.
  - **Accounting:** stays pure; label conversion only.
  - **Lineage:** shared origin keeps the works distinct.
  - **The 2a/2b split** is coherent.
  - **The coder's pre-commit snapshot method** is sound.
- **F1 (blocking):** `Router.evidence_inventory` is missing from the composition test's `PUBLIC_API`.
  - The landing `gen2-check` exited 2: 2,490 tests, 3 failures, all from this one cause. The trigger-order and full-mutation stages didn't run.
  - `gen2-gateway` was green: 1,540 tests twice, 413 of 413 mutants killed.
- **NB1:** the assessment collaborator is missing from `COLLABORATORS`.
- **Routed:** `docs/gen2/tasks/2c-2a-repair-1.md`, round 1 of 3, to Sol.

## 2026-10-09: 2c-2a round 2 (2c-2a-repair-1): F1 closed, new BLOCK on F2 (a landing-gate failure)
- **Astra** (`bac4c4c6`, pinned `c984af9`; `private/reviews/gen2-2c-2a-r2-astra-review-20261009.md`): **Gate C BLOCK.**
- **Closed:** F1 (`PUBLIC_API`) and NB1 (`COLLABORATORS`).
- **F2 (new):** the landing `gen2-check` exited 2 with 2,428 of 2,430 mutants killed. Two mutants are INVALID:
  - **The mutants:** `2QB10-router-delegate-drops-the-outbox` and `-drops-the-triggers`.
  - **Cause:** both still anchor on the `return self._evidence_writer._write_evidence(...)` delegate that 2c-2a rewrote.
  - **When it started:** the defect has existed since `bfe0975`. Round 1's run stopped before reaching the mutation stage.
- **What passed:** 2,490 tests and the trigger-order check.
- **Routed:** `docs/gen2/tasks/2c-2a-repair-2.md`, round 3 of 3 (the cap). It also adds a standing rule: a slice that edits a file runs `--only` on every mutant family targeting that file.

## 2026-10-09: 2c-2a round 3 (2c-2a-repair-2): PASS, and 2c-2a is accepted
- **Astra** (`fe7a5a70`, pinned 62d6c52; `private/reviews/gen2-2c-2a-r3-astra-review-20261009.md`): **Gate C PASS, ROOT-CAUSE. "2c-2a is ACCEPTED."**
- **F2 closed:** the DELEGATE anchor was re-pointed. 2QB10 5/5 killed with controls.
- **Independent audit:** all 47 families targeting changed files apply; 1,501 of 1,501 killed.
- **Landing run at 62d6c52:** `gen2-check` green: 2,490 tests, 2,430 of 2,430 mutants killed. `gen2-gateway` is carried forward from bfe0975 (413 of 413 killed; no gateway or production changes since).
- **Standing rule (2c-2a lesson):** a slice that edits a file runs `--only` on every mutant family that targets that file, and runs the full composition module if it touches a public Router member or collaborator.
- **2c-2b dispatched** (`docs/gen2/tasks/2c-2b.md`).

## 2026-10-09: 2c-2b1 (reversible source lifecycle chains and dated views): PASS, first review
- **Astra** (`1eeeb412`, pinned `6524e58`; review at `private/reviews/gen2-2c-2b1-astra-review-20261009.md`): **PASS on A, B and C. ROOT-CAUSE. "2c-2b1 is ACCEPTED."** No blocking or non-blocking findings.
- **Admission:** primary-only, with versions pinned and attribution supplied by the Router.
- **Storage:** the DDL has foreign keys, a binding trigger and immutability guards. Time order is enforced by the Router at nanosecond precision under the commit lock, not by the DDL; the design documents this.
- **Dated view:** filters by `as_of` first, then removes only predecessors that are explicitly named. Competing records stay visible.
- **Landing at 6524e58: green on the first run.**
  - `gen2-check` exited 0.
  - `gen2-gateway` exited 0: 1,540 tests twice, 413 of 413 mutants killed.
- **Next:** 2c-2b2 dispatched (`docs/gen2/tasks/2c-2b2.md`).

## 2026-10-09: 2c-2b2a (attributed contradiction and branch disposition histories): PASS on first review
- **Astra** (`7354526c`, pinned `c1ffb16`; `private/reviews/gen2-2c-2b2a-astra-review-20261009.md`): **A, B and C all PASS, ROOT-CAUSE. "2c-2b2a is ACCEPTED."** No blocking or non-blocking findings, and **no boundary drift or research misuse.**
- **The new registry table is in scope.** Plan-audit F3 assigns these histories to 2c, and the store README deferred the tables to Phase 2.
- **One table with topic-local identity is sound.**
- **A promote records only a proposal.**
- **The narrowed lifecycle anchor still removes the same guard.**
- **Landing at `c1ffb16`: green on the first run.**
  - `gen2-check`: 2,521 tests; 2,500 of 2,500 mutants killed.
  - `gen2-gateway`: 1,540 tests twice; 413 of 413 mutants killed.
- **Next:** 2c-2b2b dispatched (`docs/gen2/tasks/2c-2b2b.md`).

## 2026-10-09: 2c-2b2b (accrual operands, G-1 label selection, E-9 re-screening views): PASS on first review; 2c-2 complete
- **Astra** (`cbb1d9c5`, pinned 7941ea3; `private/reviews/gen2-2c-2b2b-astra-review-20261009.md`): **A, B and C all PASS, ROOT-CAUSE. "2c-2b2b is ACCEPTED; 2c-2 is complete."**
  - No blocking or non-blocking findings.
  - No boundary drift or research misuse.
- **G-1 label selection:** uses revision identity plus recorded standing only. Invalidation is checked first, and a label stays stale however it is cycled. Astra probed all 364 sequences of length 0 to 5. Unknown is kept separate from stale.
- **`as_of`:** limits the histories, not the approval authority.
- **E-9:** consumes recorded reopenings only.
- **Landing at 7941ea3: `gen2-check` green on the first run.** The `gen2-gateway` record was carried forward from c1ffb16, since nothing in the gateway has changed.
- **Next:** 2c-3 dispatched (`docs/gen2/tasks/2c-3.md`).

## 2026-10-09: 2c-3a (typed stopping results and evaluators): round 1 BLOCK
- **Astra** (`bc8e462c`, pinned df1dffd; `private/reviews/gen2-2c-3a-astra-review-20261009.md`): **A BLOCK, B PASS, C BLOCK.** One blocking finding.
- **What conforms:**
  - strong-Kleene `all`/`any`, and gates conjoined separately;
  - pinned and versioned results;
  - the descriptive and known-item evaluators;
  - purity, the ledger and DEBT-030.
- **F1 (HIGH, MITIGATION; Astra flags it as boundary drift against the Evidence-accounting unknown rule):** `coverage()` counts only the E-4 eligibility list, so windows that were attempted but only partly observed give `not_satisfied` instead of `unknown`. Four probe cases reproduce this.
- **Landing at df1dffd:** `gen2-check` green; gateway carried forward.
- **Recurring family** (with 2c-1 F1–F3: lossy window projection), so the research came first: `docs/gen2/research/2c-coverage-unknown-20261009.md`. It uses certain-answer semantics (Libkin 2015) and PRISMA-style separate accounting of unknowns.
- **Routed:** `docs/gen2/tasks/2c-3a-repair-1.md`, round 1 of 3.

## 2026-10-09: 2c-3a round 2 (2c-3a-repair-1): BLOCK, F1 continues as a MITIGATION
- **Astra** (`69bb1f26`, pinned 4f5a91e; `private/reviews/gen2-2c-3a-r2-astra-review-20261009.md`): **A BLOCK, B PASS, C BLOCK.**
- **Now fixed:** the four original cases and delegates.
- **Accepted:** G-1 stale = known-ineligible, and per-rule scope.
- **F1 continues on two counts:**
  - **Earlier uncertain windows.** An earlier indeterminate root can take the distinctness credit of later eligible roots. The eligible count is therefore not a lower bound: `satisfied` flips to `not_satisfied`, including across the scope boundary.
  - **Recoverable chains.** A chain with a missing page 1 is called known-invalid, when it is only recoverable.
- **Test gap:** the Hypothesis monotonicity test excluded overlap and earlier-uncertain cases.
- **Landing at 4f5a91e is green:** `gen2-check` 2,575 tests; 2,579 of 2,579 mutants killed.
- **Research addendum** written before the re-brief (charter rule): `docs/gen2/research/2c-coverage-unknown-20261009.md` Addendum 1.
  - Sound approximation of certain answers (Libkin ICDT 2015; Console, Guagliardo, Libkin, PODS 2020).
  - Dependency-aware bounds.
  - Chain classes.
  - A reference-model test that enumerates the completions.
- **Routed:** `docs/gen2/tasks/2c-3a-repair-2.md`, **round 3 of 3 (the cap)**.
- **Operator informed:** Astra flags this as a blocking mitigation to escalate. It is not accepted as debt.

## 2026-10-09: 2c-3a round 3 (2c-3a-repair-2): PASS, and 2c-3a is accepted
- **Astra** (`634edab2`, pinned e9c0a47; `private/reviews/gen2-2c-3a-r3-astra-review-20261009.md`): **A, B and C all PASS, ROOT-CAUSE. "2c-3a is ACCEPTED."** No operator decision is needed at the round cap.
- **The fix:**
  - Coverage resolves global credit dependencies before it applies scope.
  - Recoverable chain gaps are treated as indeterminate.
  - Bounds are sound under the Addendum 1 completion semantics.
- **Astra's checks:**
  - All three round-2 probes now give `unknown`, with their controls holding.
  - The 1,250 bound cases and 5,000 refinements are preserved.
- **Coder's reference model:** 2,754 completions, 0 disagreements, 27 conservative unknowns.
- **Landing at e9c0a47:** `gen2-check` green (2,585 tests). Gateway carried forward.
- **Lesson:** the window-projection family took three rounds. Doing the research addendum before round 3 is what closed it.
- **Next:** 2c-3b dispatched (`docs/gen2/tasks/2c-3b.md`).

## 2026-10-09: 2c-3b1 (G-11 refusal at both Router boundaries; known-item binding): PASS on first review
- **Astra** (`d701706a`, pinned 869d576 + ledger 1b691c3; `private/reviews/gen2-2c-3b1-astra-review-20261009.md`): **A, B and C all PASS, ROOT-CAUSE. "2c-3b1 is ACCEPTED."** No blocking findings.
- **Support check:** one support binder, enforced independently at admission or amendment (`stopping_defect`) and at approval of the stored revision (`_approve_contract`). Astra's probes confirmed:
  - legacy re-approval is refused;
  - replay is inert;
  - reframe dispatch is covered.
- **Known-item binding:** exact over hash, bytes and media type.
- **Part-2 schema ruling:** a narrow additive descriptive/coverage vocabulary is **in scope, with no operator ruling needed**, under these constraints: closed shapes; no reinterpretation; hash-locked protocol plus G-1 impact; coverage is a prerequisite, not sufficiency.
- **Non-blocking:**
  - **N1:** isolated wrong-hash test. Folded into the 2c-3b2 brief.
  - **N2:** G-11 locator. **Done:** INVARIANTS G-11 now names the support binder and both Router boundaries.
- **Landing at 869d576:** `gen2-check` green: 2,597 tests, 2,600 of 2,600 mutants killed. Gateway carried forward.
- **Next:** 2c-3b2 dispatched (`docs/gen2/tasks/2c-3b2.md`).

## 2026-10-09: 2c-3b2 (descriptive/coverage contract vocabulary and bindings; changed-protocol fixture): PASS on first review; 2c-3 complete
- **Astra** (`3cd49d5e`, pinned `549a351`; `private/reviews/gen2-2c-3b2-astra-review-20261009.md`): **A, B and C all PASS, ROOT-CAUSE. "2c-3b2 is ACCEPTED; 2c-3 is complete."** No blocking or non-blocking findings.
- **Schema extension:** strictly additive. All 20 earlier contract fixtures are byte-identical.
- **Coverage:** still a prerequisite only. Profiles have no sufficiency authority.
- **G-1 reuse:** consumes recorded standing only, and a later compatibility record never revives an earlier invalidation.
- **Gate inputs:** still require the exact current context.
- **Landing at `549a351`: green.**
  - `gen2-check` exit 0.
  - `gen2-gateway` exit 0: 413 of 413 mutants killed.
- **Next:** 2c-4 dispatched (`docs/gen2/tasks/2c-4.md`).

## 2026-10-09: 2c-4 BLOCKED at design, waiting on an operator decision (F9 vocabulary and confidence scheme)
- **Sol** (`e0f049d3`, `cb1b67e`, design only; `docs/gen2/ACCOUNTING.md` §2c-4): reports BLOCKED, as the brief's "escalate rather than decide" clause allows.
- **Why it is blocked:**
  - EXPORT-API still marks the disposition vocabulary as *proposed*.
  - EXPORT-API §2 says the confidence scheme "is declared by the contract revision". But Contract v2 has no field to pin a scheme, and no label set or rubric.
  - No source defines a scale. The 0c rulings reject borrowing GRADE bands.
- **Orchestrator check:** EXPORT-API lines 115–125, flow S7 and S8, and the methodology synthesis all leave the scheme undefined. This is a real operator choice, not a gap the coder could fill.
- **Also found:** `export-bundle/1` can't carry the reconciliation losslessly, so an additive `/2` is needed. The estimate is about 820 lines, split as 4a (490) and 4b (330).
- **Escalated to the operator.**
- **Operator rulings (Trevor, 2026-10-09):**
  - **Vocabulary A:** the four named dispositions plus an open state.
  - **Confidence A:** a per-plan categorical scale, declared and hash-locked in the contract, approved with the plan. No built-in scale; labels are never probabilities.
  - **Order:** views first (2c-4b), then reconciliation and `export-bundle/2` (2c-4a).
  - Recorded in `docs/gen2/tasks/2c-4.md`. 2c-4b dispatched.

## 2026-10-09: 2c-4b (research-state views): PASS on first review
- **Astra** (`280d59b0`, pinned 70a851d; `private/reviews/gen2-2c-4b-astra-review-20261009.md`): **A, B and C all PASS, ROOT-CAUSE. "2c-4b is ACCEPTED."** No blocking findings. No boundary drift.
- **Probes:**
  - Views stay unknown without links, and prose never counts as a link.
  - Eligible capture and stale G-1 standing are kept separate.
  - Contradiction histories survive across 24 permutations at 3 cutoffs.
- **N1 (non-blocking, scheduled obligation):** dossier assembly needs a durable branch/window association, because a pure caller can supply invented links. Registered as **DEBT-032**, owned by task 2d, with 2e2 producing the records.
- **Landing at 70a851d:** `gen2-check` green, 2,624 tests and 2,649 of 2,649 mutants killed. The gateway result is carried forward from 549a351.
- **Next:** 2c-4a dispatched, under the operator rulings in `docs/gen2/tasks/2c-4.md`.

## 2026-10-10: 2c-4a part 1 (contract confidence-scheme declaration and G-1): PASS on first review
- **Astra** (`5db3cd30`, pinned 346c83d; `private/reviews/gen2-2c-4a1-astra-review-20261009.md`): **A, B and C all PASS. ROOT-CAUSE. "2c-4a part 1 is ACCEPTED."** No drift from the operator rulings.
- **The declaration:** closed, with categorical labels and textual rubrics. It has no numeric or probability field and no built-in scale. Legacy contracts are unchanged.
- **G-1:** the whole scheme counts as protocol content. That includes rubric-text-only changes: Astra confirmed these are correctly incompatible.
- **Re-anchored 1D mutants:** they still pin their sections.
- **N1:** the obligation-assessment production obligation is now registered as two debts:
  - **DEBT-033:** admission and assembly, owned by 2d.
  - **DEBT-034:** production, owned by 2e2.
- **Landing at 346c83d:** `gen2-check` and `gen2-gateway` both green.
- **Next:** part 2 dispatched (`docs/gen2/tasks/2c-4a2.md`).

## 2026-10-10: 2c-4a part 2 slice 1 (reconciliation operands and confidence-consistency check): PASS on first review
- **Astra** (`f684ee80`, pinned 86132e7; `private/reviews/gen2-2c-4a2a-astra-review-20261010.md`): **A, B and C all PASS. ROOT-CAUSE. "2c-4a part 2 slice 1 is ACCEPTED."** No new findings.
- **What was confirmed:**
  - The four dispositions and the separate open type are in place, with no open→unresolved transition.
  - `check_confidence` checks all five pins, plus the scheme id, version and label.
  - Unknown confidence is kept exactly as supplied.
  - The limit "fixture operands only, not provenance" is stated honestly. That is safe while DEBT-033 is open.
- **Landing at 86132e7:** `gen2-check` green. The gateway result is carried forward.
- **Next:** slice 2 dispatched (`docs/gen2/tasks/2c-4a3.md`).

## 2026-10-10: 2c-4a3 (lossless mapper and inverse, `export-bundle/2`, end-to-end unresolved-contradiction fixture): PASS on first review. TASK 2c CLOSED
- **Astra** (`5d57a84c`, pinned c4a3574; `private/reviews/gen2-2c-4a3-astra-review-20261010.md`): **PASS on A, B and C, all ROOT-CAUSE. "2c-4a3 is ACCEPTED; task 2c is complete. DEBT-030 is closable."**
- **Losslessness:** 100 expanded adversarial cases (permutations, repetitions, subsets, competing records, two historical schemes). Order and both directions of the round trip held.
- **Disposition distinctions:** the five stay distinct.
- **G-9 outcomes:** survive under both completion states.
- **`/1`:** unchanged.
- **Landing at c4a3574 (green):**
  - `gen2-check`: 2,658 tests; 2,712 of 2,712 mutants killed.
  - `gen2-gateway`: 1,540 tests run twice; 413 of 413 mutants killed.
- **N1 (stale BOUNDARIES progress text):** fixed by the orchestrator in this commit.
- **Orchestrator:**
  - **DEBT-030 CLOSED.**
  - **Task 2c set to `closed` in phase-status.json.**
  - Open follow-ons, correctly owned: DEBT-032 and DEBT-033 (2d), DEBT-034 (2e2).
- **Next:** Gate D #6 (fresh session) must pass before 2d starts.

## 2026-10-10: Gate D #6 (whole system after 2c): PASS
- **Astra, fresh session** (`2444ac7a`, pinned 6a5b712; `private/reviews/gen2-gate-d-6-astra-review.md`): **PASS. "Task 2d may start. No prerequisite repair is required before it starts."** No new defect in any blocking class.
- **DEBT-030 closure confirmed.**
- **Fresh checks:**
  - metrics, hotspots, boundaries, debt, locators and size;
  - 214 targeted accounting tests and 108 transaction tests;
  - the coverage oracle reproduced.
- **F1 (Medium):** the rich stopping result still needs a durable and export representation. Registered as **DEBT-035**, owned by 2d.
- **F2 (Medium):** Router headroom (89 lines) and inventory reads held under the `BEGIN IMMEDIATE` writer lock. Registered as **DEBT-036**, owned by 2d.
- **F3 (Low):** stale progress text. Folded into **DEBT-031**; 2d handles the EXPORT-API split.
- **Readiness for 2d:** a finite follow-through list (DEBT-032 and DEBT-033, dossier/verification, one export path, feed state). These are prerequisites for *enabling* the authoritative paths, not for starting.
- **Next:** task 2d opened. Brief at `docs/gen2/tasks/2d.md`. 2d-1 (design note `DOSSIER.md` plus the first slice) dispatched to Sol.

## 2026-10-10: operator ruling on tier-0 (decision flagged in DOSSIER.md)
- **Trevor:** "Keep it off for now, but I don't want to get it up and running and months later come back and say it was left off."
- **Ruling:** tier-0 stays disabled in Phase 2.
- **Recorded as DEBT-037** (owner phase 3). While it is disabled, the engine must show an explicit `tier-0 disabled` capability fact, and the item can't close silently.
- **Still open:** the quote-normalization decision. The operator asked about matching at 98% similarity or better; the orchestrator is clarifying the trade-off before slice 3.
- **Operator ruling on quote matching:** layered.
  - An exact match passes.
  - A named, versioned normalization followed by an exact match passes.
  - A match that is ≥98% similar but still differs is held for review as a "near match" and never auto-passes.
  - Any difference in a number, a negation word or a unit always fails.
  - Recorded in `docs/gen2/tasks/2d.md` for slice 3.

## 2026-10-10: 2d-1 (DOSSIER design note; durable obligation-assessment admission): round 1 BLOCK
- **Astra** (`4173407b`, pinned 77200eb; `private/reviews/gen2-2d-1-astra-review-20261010.md`): **A BLOCK, B PASS, C BLOCK.** DOSSIER.md is accepted, including its flagged decisions; no additional operator decision is missing.
- **F1 (High, class d; flagged as boundary drift):** the DDL binding allows only `contract_approval`, so valid assessments are refused after an approved amendment or reframe. The fix restores conformance with the established decision family. No operator amendment is needed.
- **N1:** raw-DDL categorical controls. Folded into the repair.
- **Landing at 77200eb: green.**
  - `gen2-check` passed.
  - `gen2-gateway` passed.
- **Routed:** `docs/gen2/tasks/2d-1-repair-1.md`, round 1 of 3.
- **2d-1-repair-1 landed** at `68849b8`, from Sol `6a02b780`. Astra round 2 is dispatched.
- **Coder deviation, disclosed:** while looking for AGENTS.md files, the coder ran a filename search under `/home/trevor`. That breaks the no-recursive-search rule. The search was read-only and stopped at once. Coder prompts now limit discovery to the repo's AGENTS.md and the paths they name.

## 2026-10-10: 2d-1 round 2 (2d-1-repair-1): PASS, and 2d-1 is accepted
- **Astra** (`cc788619`, pinned 68849b8; `private/reviews/gen2-2d-1-r2-astra-review-20261010.md`): **A, B and C all PASS, ROOT-CAUSE. "2d-1 is ACCEPTED."**
- **F1 closed.** The binding now uses the contract's own approving-decision pointer, which part 01 binds for all three approval kinds; this replaces the duplicate, narrower list.
- **The round-1 probe** now commits under all three approval kinds, including a real reframe.
- **N1 closed.**
- **Landing at 68849b8:** `gen2-check` green. The gateway result is carried forward.
- **Next:** 2d-2, DEBT-032 (branch/window association), dispatched as `docs/gen2/tasks/2d-2.md`.

## 2026-10-10: 2d-2 (durable branch/window association; provenance-derived window pins): PASS on first review; DEBT-032 closed
- **Astra** (`f1bff563`, pinned de1ced0 plus ledger 09efd32; `private/reviews/gen2-2d-2-astra-review-20261010.md`): **A, B and C all PASS, ROOT-CAUSE. "2d-2 is ACCEPTED. DEBT-032 is closable."**
- **Probes:** nine reviewer probes, covering cross-topic links, delegate/checkpoint/pre-contract windows, forged revisions and attribution, duplicates, missing provenance, fencing and transaction boundaries.
- **N1:** DEBT-036 carries forward to slices 6 and 8. Coverage-view evaluation runs outside the writer lock, but selecting and joining the inputs still happens inside it. `service.py` is at 1,420 lines, leaving 80.
- **Landing at de1ced0, all green:**
  - `gen2-check`: 2,694 tests; 2,753 of 2,753 mutants killed.
  - `gen2-gateway`: 413 of 413 mutants killed.
- **Orchestrator:** DEBT-032 is closed.
- **Next:** 2d-3 is dispatched (`docs/gen2/tasks/2d-3.md`, quote verification under the layered-matching ruling).
  - **Mapping to V-6:** a near match counts as a mismatch. It is quarantined and comes with a diagnostic to help re-capture. It is never passed and never adjudicated.

## 2026-10-10: 2d-3a (pure layered quote matcher): round 1 BLOCK
- **Astra** (`84267797`, pinned 0a8238e; `private/reviews/gen2-2d-3a-astra-review-20261010.md`): **A BLOCK, B PASS, C BLOCK. ROOT-CAUSE repair required.**
- **A1:** NFKC auto-passes `10²`→`102` and `m²`→`m2`.
- **A2:** the dehyphenation fold deletes the minus sign (U+2212), and a hard line-break hyphen merges `re-sign` into `resign`.
- **A3:** the lexical guards miss negation prefixes (`non-`, `un-`), grouped numbers (`1;000`), compound-unit operators and time units. These get forbidden near-match diagnostics.
- **A4:** protection depends on alignment, so a relocated negation still gets a diagnostic.
- **C1:** the idempotence law is false (Hangul composition after dehyphenation).
- **Accepted:** input checks, the difflib diagnostic and its 0.98 boundary, citations, the split and placement.
- **Landing at 0a8238e:** `gen2-check` green (2,776 of 2,776 mutants). The probes still fail.
- **Routed:** `docs/gen2/tasks/2d-3a-repair-1.md`, round 1 of 3.
  - NFC plus a safe whitelist (W3C charmod-norm), not NFKC.
  - Soft-hyphen-only dehyphenation, failing closed.
  - Ordered protected-token comparison on the original text, independent of alignment.

## 2026-10-10: 2d-3a round 2 (2d-3a-repair-1): BLOCK; A1, A2 and C1 closed
- **Astra** (`c1bc907d`, pinned 040373d; review at `private/reviews/gen2-2d-3a-r2-astra-review-20261010.md`): **A BLOCK, B PASS, C BLOCK.**
  - A1, A2 and C1 are closed at the root cause.
  - A3 and A4 remain open and are classed as MITIGATION.
- **R2-1:** these all still earn diagnostics: hyphenated negations (`not-yet`), spaced signs (`- 5` vs `+ 5`), and the overreaching negative prefix (`discuss` vs `cuss`).
- **R2-2:** the lexical-slot fingerprint loses positions inside a word, so a number moved inside one lexeme (`abc1def` vs `abcde1f`) earns a diagnostic.
- **Landing at 040373d:** green, 2,793 of 2,793 mutants killed.
- **Recurring family**, so research came before the re-brief: `docs/gen2/research/2d-quote-protection-20261010.md`.
  - **The approach:** use sound, conservative approximation, as in 2c-3a, and classify the edit regions rather than the tokens (Myers 1986 / difflib opcodes).
  - **The rule:** a diagnostic is allowed only if the protected-character skeletons are equal, the edit regions are safe, there is no relocation, and no negative prefix was edited.
  - **Brief amendment:** over-protecting the lookalikes is accepted by design.
- **Routed to** `docs/gen2/tasks/2d-3a-repair-2.md`, **round 3 of 3 (the cap)**.

## 2026-10-11: 2d-3a round 3 (2d-3a-repair-2): BLOCK at the round cap, waiting for an operator decision
- **Astra** (`4d873899`, pinned ce6dfaa; `private/reviews/gen2-2d-3a-r3-astra-review-20261010.md`): **Gate A BLOCK, Gate B PASS, Gate C BLOCK. The round cap is reached.**
- **Closed at the root cause:**
  - R2-2 (numbers moved within a lexeme);
  - the original R2-1 cases;
  - all 66 regression literals;
  - the utility controls.
- **R3-1 is the only remaining defect.** Apostrophe-joined sequences are grouped as a single lexeme, so negations and units inside them are missed.
  - Failing cases: `say'not'now` vs `say'now`, and a move of `mg` within `alpha'mg'omega'delta`. Both still get a near-match diagnostic instead of a plain mismatch.
  - The quote is still quarantined in every case, so only the diagnostic is wrong.
  - Astra found 30 failures out of 120 in a boundary matrix. All 30 involve straight or curly apostrophes.
- **Landing at ce6dfaa:** green, 2,797 of 2,797 mutants killed.
- **Under the charter's round-cap rule, the orchestrator has stopped dispatching.** Recommendation to the operator: accept R3-1 as tracked debt, owned by 2d-3b and fixed before the matcher is wired into the governed path. The alternative is a 4th round, which needs a fresh Gate D first.
- **Operator decision (Trevor, 2026-10-11): "Your rec is fine."**
  - R3-1 is accepted as tracked debt, **DEBT-038**, owned by task 2d. 2d-3b must fix it first, before the matcher is wired into the governed path.
  - **2d-3a is closed**, with the pure matcher at `ce6dfaa`.
  - 2d-3b is dispatched (`docs/gen2/tasks/2d-3b.md`).

## 2026-10-11: 2d-3b part 1 (DEBT-038, apostrophe boundaries): round 1 BLOCK
- **Astra** (`9e9a429e`, pinned f722a39; `private/reviews/gen2-2d-3b1-astra-review-20261011.md`): **A BLOCK, B PASS, C PASS.**
- **What passed:** the apostrophe repair. All 14 literals and the 120-case matrix pass, and no earlier finding has regressed.
- **B1-1:** Sol added a relaxation for whitespace at word endpoints, to avoid over-protecting a possessive such as `trial's`. Deleting that whitespace erases a protected word's boundary (`alpha'not early` vs `alpha'notearly`), and the case still gets a diagnostic. Astra's probes fail on 480 of 480 cases.
- **Landing at f722a39:** green, with 2,799 of 2,799 mutants killed.
- **Routed:** `docs/gen2/tasks/2d-3b1-repair-1.md`, round 1 of 3. The fix **removes** the relaxation, which is the conservative choice under the adopted research principle. The `trial's` utility case becomes a plain mismatch, by design; this is an orchestrator amendment.

## 2026-10-11: 2d-3b part 1 round 2 (2d-3b1-repair-1): PASS. DEBT-038 closed
- **Astra** (`59191d74`, pinned dba8f35; `private/reviews/gen2-2d-3b1-r2-astra-review-20261011.md`): **A, B and C all PASS, ROOT-CAUSE. "2d-3b part 1 is ACCEPTED; DEBT-038 is closable."**
- **B1-1 closed:** the endpoint exception is removed, so inclusive protection now applies to both operands. The conservative `trial's` result is accepted.
- **Probes:**
  - endpoint: 480 of 480 cases;
  - boundary: 120 of 120 cases;
  - regression literals: all 66 intact.
- **The mutant** restores the defect and gets 128 assertion kills.
- **Landing at dba8f35:** `gen2-check` green.
- **Orchestrator:** DEBT-038 closed. 2d-3b part 2 (governed V-6) dispatched; see `docs/gen2/tasks/2d-3b2.md`.

## 2026-10-11: 2d-3b2 slice 1 (immutable source-artifact identity bindings): PASS on first review
- **Astra** (`245fa7a8`, pinned 53e7e47; review at `private/reviews/gen2-2d-3b2a-astra-review-20261011.md`): **A, B and C all PASS. ROOT-CAUSE. "2d-3b2 slice 1 is ACCEPTED."** No blocking or non-blocking findings.
- **Admission:** Router admission is enforced at the existing commit boundary.
- **DDL immutability:** these attempts were all refused: a changed-hash INSERT, an UPDATE, an UPSERT, and both REPLACE forms.
- **Rollback and replay:** both were probed under faults.
- **`service.py`:** now 1,421 lines.
- **Landing at 53e7e47:** green, for both `gen2-check` and `gen2-gateway`.
- **Next:** slice 2 (governed V-6 matching and enforcement) is dispatched, per `docs/gen2/tasks/2d-3b3.md`.

## 2026-10-11: 2d-3b3 part 1 (governed quote computation and persistence): round 1 BLOCK
- **Astra** (`637cb598`, pinned 4eba3c6, design d859c29; `private/reviews/gen2-2d-3b3a-astra-review-20261011.md`): **A BLOCK, B PASS, C BLOCK.**
- **Accepted:** computation, authentication, validation outside the writer transaction (no time-of-check/time-of-use gap), lossless persistence and DDL 11 compatibility.
- **F1 (HIGH, false-support class (a)):** a receipt naming a matching check can cite a different span, source version, work, hash or normalization. Reproduced through to load-bearing `accepted_support`.
- **F2 (HIGH):** a receipt marked `not_applicable` with a null check reference skips the quarantine fence, so a quarantined load-bearing capture is promoted. A non-load-bearing quarantined capture is promoted without any receipt.
- **Family cause:** authority is attached to a freely chosen check reference, not to the captured evidence that is actually consumed.
- **Non-blocking:**
  - **NB1:** adjudication and notification. Already scoped to part 2.
  - **NB2:** SQL checks selected fields only. Clarify the split between the Router and SQL at the 2d storage closeout.
- **Landing at 4eba3c6:** green. The probes still reproduce.
- **Routed:** `docs/gen2/tasks/2d-3b3-repair-1.md` (round 1 of 3). The F1 binding and the F2 capture-eligibility fence land together.

## 2026-10-11: 2d-3b3 part 1 round 2 (2d-3b3-repair-1): BLOCK; F1/F2 closed, F3 new
- **Astra** (`a2749534`, pinned 20f209c; `private/reviews/gen2-2d-3b3-r2-astra-review-20261011.md`): **A BLOCK, B PASS, C BLOCK.**
- **F1 and F2 closed at root cause:**
  - substitution refusals;
  - the null-reference bypass is closed;
  - re-capture is sound.
- **F3 (new):** the per-row trigger `quote_checks_refence_capture` re-quarantines accepted claims *before* the same commit's valid receipt is written. A valid verification commit therefore leaves the claim permanently `quarantined`.
- **DDL 12 install-time DML:** this is migration-like if applied by hand to a populated store. It is unreachable on normal open, because the exact-schema gate refuses old stores. It is not a separate blocker.
- **Landing at 20f209c:** green.
- **Routed:** `docs/gen2/tasks/2d-3b3-repair-2.md`, **round 3 of 3 (the cap)**.
  - Reconcile at the commit boundary, after all writes.
  - Remove the install-time DML.

## 2026-10-11: 2d-3b3 part 1, round 3 (2d-3b3-repair-2): PASS. Governed V-6 computation and capture-bound support accepted
- **Astra** (`6f926638`, pinned 7766759; `private/reviews/gen2-2d-3b3-r3-astra-review-20261011.md`): **A, B and C all PASS, ROOT-CAUSE. "2d-3b3 part 1 is ACCEPTED."**
- **F3 closed:** reconciliation now runs on the final `commit_outcome` audit row, after all evidence is written. The install-time DML has been removed. F1 and F2 still pass.
- **Documented limit:** arbitrary raw SQL that skips the final audit can bypass reconciliation. The view and the promotion guard still detect and refuse it. Acceptance rests on the single Router writer protocol, which goes into the docs in 2d-3b4.
- **Landing at 7766759, all green:**
  - `gen2-check`: 2,868 tests; 2,855 of 2,855 mutants killed.
  - `gen2-gateway`: 413 of 413 mutants killed.
- **Next:** 2d-3b4 dispatched (`docs/gen2/tasks/2d-3b4.md`): owner notification, refusal to adjudicate byte mismatches, NB2, and the raw-path documentation.

## 2026-10-11: 2d-3b4 (capture-owner notification; byte-mismatch adjudication refused): PASS on first review. DOSSIER slice 3 (V-6) complete
- **Astra** (`a011a8d3`, pinned 129d202; `private/reviews/gen2-2d-3b4-astra-review-20261011.md`): **A, B and C all PASS. ROOT-CAUSE. "2d-3b4 is ACCEPTED; DOSSIER slice 3 (V-6) is complete."** No findings.
- **Quote holds:** owned by the capture's producer station and its deadline, and scoped to the quote rather than the whole source.
- **Byte-mismatch protection holds even past the deadline:** an operator clearance of a byte-mismatch hold is refused, and the Router and DDL 13 both refuse adjudication of byte mismatches.
- **Still allowed:** NLI holds remain distinguishable and can be adjudicated.
- **Closed:** NB1, NB2 and the raw-path documentation.
- **Still with 2e2:** automatic deadline escalation.
- **Landing at 129d202:** green on both `gen2-check` and `gen2-gateway`.
- **Next:** 2d-4 dispatched (`docs/gen2/tasks/2d-4.md`), DOSSIER slice 4, covering V-2, V-3, V-5 and V-8.

## 2026-10-11: 2d-4 part 1 (adverse verification verdicts → owned holds): round 1 BLOCK on C1 only
- **Astra** (`7864934f`, pinned d16613d; review at `private/reviews/gen2-2d-4a-astra-review-20261011.md`): **A PASS (ROOT-CAUSE), B PASS, C BLOCK.**
- **What passed:** the runtime change is accepted. Verdicts map to judgment holds; `cannot_assess` maps to a judgment hold with a missing-content cause, owned by the producer.
- **C1:** the new open-creation negative test is masked by a table CHECK. The existing test still detects removal of the guard, but the new test claims to be independent and isn't.
- **Non-blocking:**
  - **NB1:** documentation wording. Folded into the repair.
  - **NB2:** retained-disagreement consumption. Recorded as a slice-6 follow-through in `tasks/2d.md`.
  - **NB3:** Router headroom of 72 lines. Continues under DEBT-036.
- **Landing at d16613d:** green, with 2,885 of 2,885 mutants killed.
- **Routed:** `docs/gen2/tasks/2d-4a-repair-1.md`, a test-only fix (round 1 of 3).

## 2026-10-11: 2d-4 part 1, round 2 (2d-4a-repair-1): PASS. 2d-4 part 1 accepted
- **Astra** (`95b2b6c6`, pinned b2a69b9; `private/reviews/gen2-2d-4a-r2-astra-review-20261011.md`): **A, B and C all PASS. "2d-4 part 1 is ACCEPTED."**
- **C1 closed:** the open-creation test now fails on its own when the guard is removed. Its counterfactual fails with the trigger removed, and the control still passes. The test is paired with `A2-holds-created-open`.
- **NB1 confirmed.**
- **Landing at b2a69b9:** `gen2-check` green.
- **Next:** 2d-4 part 2 (V-2 tier/route, V-3 re-access/extraction) dispatched as `docs/gen2/tasks/2d-4b.md`.

## 2026-10-11: 2d-4b part 1 (pure acquisition-lineage validator): PASS on first review
- **Astra** (`fafbbe58`, pinned 73c4e1b; `private/reviews/gen2-2d-4b1-astra-review-20261011.md`): **A, B and C all PASS, ROOT-CAUSE. "2d-4b part 1 is ACCEPTED."** No findings.
- **What was confirmed:**
  - It applies V-3 canonical-byte reuse correctly: bytes from the producer and from other acquirers are both allowed.
  - It stays honest about partial retrieval.
- **Disclosed limit:** it checks that the request is internally consistent, but it doesn't authenticate the gateway exchange. The next part has to bind the result to the trusted capture before admitting it.
- **Landing at 73c4e1b:** `gen2-check` green.
- **Next:** 2d-4b part 2 dispatched (`docs/gen2/tasks/2d-4b2.md`).

## 2026-10-11: 2d-4b2 slice 1 (trusted acquisition admission): round 1 BLOCK
- **Astra** (`6aa75bd1`, pinned 708b528; `private/reviews/gen2-2d-4b2a-astra-review-20261011.md`): **A BLOCK, B PASS, C BLOCK.** The family is ROOT-CAUSE; there is no boundary drift.
- **What Astra confirmed:**
  - The `CaptureReader` protocol is injected by trusted construction code. There is no direct read of station storage, and the import graph is unchanged.
  - The rehash gap is closed against a trusted capture. The trust limit (a counterfeit trusted reader) is documented and owned by 2e2.
- **F1:** the landing `gen2-check` failed in 14 seconds, because DDL 14 is missing its `-- trace:` marker. The coder's six pre-commit gates don't include `gen2-ddl`.
- **F2:** three SQL predicates have no paired coverage: artifact hash, work, and verifier topic. Each survives an individual mutant.
- **Orchestrator lesson:**
  - Check the landing exit code before dispatching a review. I dispatched in parallel and missed a 14-second failure.
  - Add `gen2-ddl` and `gen2-schemas` to the coder's pre-commit gates.
- **Landing at 708b528:**
  - `gen2-check` exit 2 (DDL trace);
  - `gen2-gateway` green.
- **Routed:** `docs/gen2/tasks/2d-4b2a-repair-1.md`, round 1 of 3.

## 2026-10-11: 2d-4b2 slice 1, round 2 (2d-4b2a-repair-1): PASS, and 2d-4b2 slice 1 is accepted
- **Astra** (`eba152d2`, pinned 3e826f3; `private/reviews/gen2-2d-4b2a-r2-astra-review-20261011.md`): **A, B and C all PASS. "2d-4b2 slice 1 is ACCEPTED."**
- **F1 closed:** the DDL trace marker is in place.
- **F2 closed:** 17 SQL mutants and 5 admission-conjunct mutants are each killed in isolation, and the three original counterexamples are now caught.
- **Landing at 3e826f3, all green:**
  - `gen2-check`: 3,044 tests; 2,969 of 2,969 mutants killed.
  - `gen2-gateway`: 413 of 413 mutants killed.
- **Next:** 2d-4b3 dispatched (`docs/gen2/tasks/2d-4b3.md`): receipt consumption, V-2 tiers and tables, and V-3 extraction validation.

## 2026-10-11: 2d-4b3 slice 1 (canonical-byte receipts consume admitted acquisitions): PASS on first review
- **Astra** (`ea3c1645`, pinned 7106c36; review at `private/reviews/gen2-2d-4b3a-astra-review-20261011.md`): **A, B and C all PASS. ROOT-CAUSE. "2d-4b3 slice 1 is ACCEPTED."**
- **What was accepted:**
  - DDL 15 binds all eight operands.
  - Topic equality follows soundly from the verifier identity.
  - There is no migration-like DML.
  - The non-canonical methods keep their gaps, but those gaps are explicitly scheduled.
- **N1 (documentation lag):** fixed by the orchestrator in this commit. The BOUNDARIES text and the INVARIANTS V-3 locator now name SQL 14/15.
- **Landing at 7106c36:** green on both `gen2-check` and `gen2-gateway`.
- **Next:** 2d-4b3 slice 2 (V-2 content/table tiers) is dispatched (`docs/gen2/tasks/2d-4b3b.md`).

## 2026-10-11: 2d-4b3 slice 2 part 1 (canonical tier ceilings): round 1 BLOCK
- **Astra** (`e4bb4a2e`, pinned b5de4c8; `private/reviews/gen2-2d-4b3b-astra-review-20261011.md`): **A BLOCK, B PASS, C BLOCK.** Classified as a MITIGATION at the V-2 family level.
- **What passed:** the canonical ceiling derivation. Astra checked it against the gateway source: `searched_ok` means records were returned, not that a paper was delivered, and links and `has_full_text` are correctly ignored.
- **R1 (HIGH):** whitespace-only bodies (form feed, NBSP, em space, line separator) count as content, and one was promoted to load-bearing `accepted_support`. The gateway CORE path can reach this.
- **R2 (HIGH):** switching to the `verifier_extraction` or `validated_extraction` method bypasses the ceiling. An abstract-only acquisition still promoted claims at full_text or reproduced.
- **Landing at b5de4c8:** green.
- **Routed:** `docs/gen2/tasks/2d-4b3b-repair-1.md`, round 1 of 3.
  - R1 fix: a named, versioned nonblank rule, cited (Unicode `White_Space`).
  - R2 fix: every tier-bearing method consumes a recorded basis, and unbound methods don't authorize support.

## 2026-10-11: 2d-4b3b repair part 1, round 2: R1 and R2 closed; BLOCK on R3 (landing gate)
- **Astra** (`7c7d1d20`, pinned 1323cf6; `private/reviews/gen2-2d-4b3b-r2-astra-review-20261011.md`): **A PASS, B PASS, C BLOCK.**
- **R1 closed at root cause:** the nonblank rule is UCD 17 White_Space plus Default_Ignorable_Code_Point. Astra verified all 4,245 code-point checks against the cited UCD files, and the rule doesn't over-block non-Latin scripts.
- **R2 closed for this split:**
  - Pending extraction methods can't qualify support. Their inflated declarations raise missing-content holds instead.
  - The declaration-admission gap stays in part 2, as disclosed.
- **R3 (new, MEDIUM):** the landing `gen2-check` exited 2 with `A6-D28-old-over-restriction` INVALID.
  - **Cause:** a shared-fixture change broke that mutant's paired control. The coder's targeted `--only` sweep didn't include A6.
- **Landing at 1323cf6:**
  - `gen2-check` exit 2, one mutant INVALID;
  - `gen2-gateway` green.
- **Routed:** `docs/gen2/tasks/2d-4b3b-repair-2.md`, round 3 of 3 (the cap).
- **New process rule:** when a shared test fixture is edited, the coder runs every mutant family whose paired controls use it.

## 2026-10-11: 2d-4b3b repair part 1, round 3 (2d-4b3b-repair-2): PASS. Repair part 1 accepted
- **Astra** (`8a8db486`, pinned 23b39a6; `private/reviews/gen2-2d-4b3b-r3-astra-review-20261011.md`): **A, B and C all PASS. "2d-4b3b repair part 1 is ACCEPTED."**
- **R3 closed (root cause):** D28 now has an independent accepted control, and its producer-reuse killer is intact. The shared fixture and the history assertions are byte-identical.
- **Coverage:** the sweep audit confirms all 521 affected pairings.
- **Landing at 23b39a6:** `gen2-check` green. Gateway result carried forward from 1323cf6.
- **What this part closed:**
  - R1: nonblank rule `recorded-nonblank/1+ucd17.0.0`.
  - R2: non-authority fence for pending extraction, SQL 17.
- **Next:** 2d-4b3c dispatched (`docs/gen2/tasks/2d-4b3c.md`). It binds both extraction methods to their admitted acquisition and recorded-content ceiling.

## 2026-10-11: 2d-4b3c part 1 (extraction receipts bound to acquisitions): round 1 BLOCK on C1 (landing gate)
- **Astra** (`b344ab9b`, pinned ead2779; `private/reviews/gen2-2d-4b3c-astra-review-20261011.md`): **A PASS, B PASS, C BLOCK. ROOT-CAUSE binding.**
- **Gate A:** SQL 18 requires one admitted SQL 14 row matching all seven operands, for both methods and every verdict. It is additive, AFTER INSERT, with its trace marker and no DML. 84/84 bypass probes were refused.
- **The topic implication holds.** It follows from the SQL 14 and SQL 03 verifier-topic bindings.
- **The producer-acquired, verifier-extracted case is correct** and isn't a loophole.
- **Split coherence:** bound but inflated declarations stay non-authoritative under SQL 17 and SQL 12, and `_require_quote_support`.
- **C1 (MEDIUM):** `test_governed_quotes.py` `AdmissionTest.test_support_control` builds a `verifier_extraction` receipt from the schema example, with no admitted acquisition.
  - The new guard correctly rejects it, so the landing `gen2-check` exits 2 (3,129 tests, 1 failure).
  - The coder's targeted selection matched method names; this test reaches the method through the schema example file, so it was missed.
- **Coverage:** 287 targeted tests and 29/29 targeted mutants independently re-run. The sweep accounting (40 families, 2,439 mutants) reproduces exactly.
- **Landing at ead2779:** `gen2-check` exit 2 (C1). `gen2-gateway` was still running at routing time.
- **Report note:** the session was archived before it wrote its final file, because the landing failure meant review after repair. The report is Astra's draft, copied verbatim apart from the landing paragraph.
- **Routed:** `docs/gen2/tasks/2d-4b3c-repair-1.md`, round 2 of 3.
- **New process rule:** the coder's targeted test selection also includes every test that loads a schema example document whose content the change constrains.

## 2026-10-11: 2d-4b3c part 1, round 2 (2d-4b3c-repair-1): PASS. Part 1 accepted
- **Astra** (`ed7558de`, pinned 7b5aaae; `private/reviews/gen2-2d-4b3c-r2-astra-review-20261011.md`): **A, B and C all PASS. "2d-4b3c part 1 is ACCEPTED."** There are no blocking or non-blocking findings.
- **C1 closed (root cause).** The support control now commits through admitted input that matches all seven SQL 18 operands. Its original assertions are intact, and every other method in the file is unchanged (AST-verified). SQL 18 is untouched.
- **The receipt audit was independently corroborated:** no other positive control lacks admitted input.
- **Landing at 7b5aaae:** `gen2-check` green.
  - 3,129 tests;
  - 215 triggers in reverse order;
  - 3,037/3,037 mutants killed, 3,020 with paired controls; 17 keep their disclosed classifications.
  - `gen2-gateway` carried forward from ead2779 (exit 0).
- **Next:** 2d-4b3c part 2 (`docs/gen2/tasks/2d-4b3c2.md`), which applies SQL 16's recorded-content ceiling to extraction declarations.

## 2026-10-12: 2d-4b3c2 (extraction declarations capped at recorded content): PASS on the first review. Accepted
- **Astra** (`e9e08dab`, pinned 0988139; `private/reviews/gen2-2d-4b3c2-astra-review-20261011.md`): **A, B and C all PASS, ROOT-CAUSE. "2d-4b3c2 is ACCEPTED."** There are no blocking or non-blocking findings.
- **The SQL 16 refactor conforms.** The shared view `source_acquisition_content_tiers` is the old inline rule, and canonical behaviour is unchanged. Editing the earlier ordered part is acceptable because the schema is undeployed.
- **SQL 19** caps both extraction methods through SQL 18's seven operands. Astra probed multiple matching acquisitions, short text, abstract-only records, malformed JSON and unselected records; all held.
- **The BOUNDARIES and INVARIANTS edits match the code.**
- **Landing at 0988139:**
  - `gen2-check` green: 3,167 tests; 216 triggers in reverse order; 3,070/3,070 mutants killed.
  - `gen2-gateway` green: 413 mutants killed.
- **With this, 2d-4b3c is complete:** binding (SQL 18) plus ceilings (SQL 19).
- **Next:** 2d-4b3d (`docs/gen2/tasks/2d-4b3d.md`), table citations require recorded table availability (V-2).

## 2026-10-12: 2d-4b3d (table citations require recorded full text): round 1 BLOCK on F1
- **Astra** (`f124568c`, pinned 9cece22; `private/reviews/gen2-2d-4b3d-astra-review-20261012.md`): **A BLOCK (MITIGATION at the family level); B PASS; C PASS.**
- **What passed:**
  - "Recorded full text as the minimum for a table citation" is sound as a conservative necessary condition.
  - Refusing structured BEA and Census rows without full text is the right call, and the limitation is disclosed.
  - Borrowing, metadata-only, Unicode-blank and the verdict exceptions all hold. The diagnostics are preserved.
- **F1 (MEDIUM, DEVIATION):** SQL 20 reads `$.locator.kind`, but nothing at the storage layer enforces the span or locator shape.
  - Raw inserts with duplicate keys (`{"kind":"page","kind":"table"}`, or a duplicated `locator`), a missing locator, or the kind `"TABLE"` are admitted as `supports` at `bibliographic`, for all three methods.
  - The Router's schema boundary refuses these, so it is not an agent-facing exploit; the raw guarantee is still in scope.
  - **Root cause:** the guard relies on an unenforced input domain.
- **NB1 (low, BOUNDARY-DRIFT):** INVARIANTS V-2 and BOUNDARIES Router still describe table admission as future work. This understates what is implemented and grants no false authority. It is folded into the repair.
- **Landing at 9cece22:**
  - `gen2-check` green: 3,210 tests; 217 triggers in reverse order; 3,090/3,090 mutants killed.
  - `gen2-gateway` green: 413 mutants killed.
- **Routed:** `docs/gen2/tasks/2d-4b3d-repair-1.md`, round 2 of 3. It applies I-JSON's unique-names rule (RFC 7493) plus an exact schema-shape domain at raw admission, and the NB1 doc fix.

## 2026-10-12: 2d-4b3d repair-1, round 2: BLOCK. F1 narrowed but still open
- **Astra** (`9dfe734b`, pinned 9fa4748; `private/reviews/gen2-2d-4b3d-r2-astra-review-20261012.md`): **A BLOCK; B PASS; C PASS.**
- **How the session ended:** the Codex cybersecurity filter ended it after the verdict draft was complete. The report is Astra's own draft, copied verbatim apart from the landing paragraph.
- **What was closed:**
  - the duplicate-name uniqueness check, which is sound, including escaped and nested names, and correctly treats Unicode-normalized names as distinct;
  - the exact shape for ordinary members;
  - the `compat.py` probe, which is a probe only and fails closed;
  - the fixtures;
  - NB1's future-tense wording.
- **Still open, F1(a):** on SQLite 3.45.1, path lookup treats a decoded NUL as the end of a member name. A `"cited_spans\u0000suffix"` member placed before the real `cited_spans` splits the column from the receipt, and every method admits a table citation as `supports` at `bibliographic`.
- **Still open, F1(b):** `1.00000000000000001` and `-1e-999` are converted to REAL before the integrality and minimum checks, so they pass.
- **Common cause:** both families come from validating through SQLite's lossy interpretation of the text, not through the store's actual canonical representation (store API JCS, C-13). They remain raw-store-only; the Router refuses them.
- **Landing at 9fa4748:** `gen2-check` green; `gen2-gateway` green.
- **Routed:** `docs/gen2/tasks/2d-4b3d-repair-2.md`, **round 3 of 3 (the cap)**. Raw admission requires the stored canonical representation, checked against the exact text and decoded names.

## 2026-10-12: 2d-4b3d repair-2, round 3 (the cap): PASS. 2d-4b3d accepted
- **Astra** (`d730e646`, pinned 9436a34; `private/reviews/gen2-2d-4b3d-r3-astra-review-20261012.md`): **A, B and C all PASS. "2d-4b3d is ACCEPTED."**
- **F1(a) closed (root cause).** Complete decoded-name member sets now cover every receipt object that SQL 03, 20 and 21 read. 318 independent NUL-alias cases across all three methods were refused. Valid NUL characters in locator values still pass.
- **F1(b) closed (root cause).** Offsets are judged from the preserved numeral text with exact decimal reasoning. 1,260 combinations were checked against Fraction/Decimal expectations with no disagreement. Integral spellings and large integers stay valid.
- **Design note:** Sol rejected canonical-only enforcement because JCS writes `1e+30` and long digit strings, which would have refused store-writable offsets. It used an exact lexical check instead. DOSSIER records the reasoning.
- **Docs:** BOUNDARIES and V-2 claim exactly the resulting guarantee. The compat probes fail closed.
- **Landing at 9436a34:** `gen2-check` green; `gen2-gateway` green.
- **Process note:** the coder read the repair-1 evidence directory, which wasn't among its named inputs, and disclosed it. Briefs now list the coder's own and prior evidence directories as allowed reads.
- **Next:** 2d-4b3e (`docs/gen2/tasks/2d-4b3e.md`): durable extraction and validation records replace the SQL 17 fence (V-3).

## 2026-10-13: 2d-4b3e1 (durable extraction and validation records): round 1 BLOCK on F1 and F2
- **Astra** (`882a46cd`, pinned 190dabb; `private/reviews/gen2-2d-4b3e1-astra-review-20261012.md`): **A BLOCK, B PASS, C BLOCK; MITIGATION.**
- **What passed:**
  - The records architecture, immutability, the five-column acquisition key and validator role separation are sound.
  - Authentication happens outside the writer lock, with no new time-of-check/time-of-use gap.
  - Nothing reads the new tables yet.
  - The metrics changes are 18→19 and 10→11 plus ten admissions, all attributable to the collaborator.
  - Gate B: the policy is faithful to the operator ruling, and semantic agreement isn't overclaimed.
- **F1 (MEDIUM): SQL 22 artifact references accept ambiguous JSON.**
  - Duplicate `content_hash`/`size_bytes`/`media_type` keys, or `key\u0000suffix` names, in `output_ref` or `comparison_evidence_ref` commit with method success.
  - The records then fail `Store.select` readback.
  - This is a raw-admission defect; the Router and Store normalize normal writes. It is the **second occurrence** of the 2d-4b3d F1 family.
- **F2 (MEDIUM): the new raw fixture breaks `gen2-trigger-order`.** It cuts the DDL text at `CREATE TABLE source_extractions`, and under reversed order that tail includes unrelated triggers, giving 51 differences. The landing `gen2-check` exited 2.
- **N1 (non-blocking):** extractor independence compares caller-declared labels exactly, so `TOOL-A`, ` tool-a ` and aliases count as distinct. It must be documented, and settled before receipt consumption grants authority.
- **Landing at 190dabb:** `gen2-check` exit 2 (trigger-order). `gen2-gateway` green.
- **Operator ruling 2026-10-13 (Trevor): close the JSON member-name family store-wide.** One shared domain (unique decoded names, no NUL in names) covers every JSON column, and a static `gen2-ddl` check fails on any uncovered column. It may split into two parts.
- **Routed:** `docs/gen2/tasks/2d-4b3e1-repair-1.md`, round 2 of 3. The coder's pre-commit gates now include `make gen2-trigger-order`.

## 2026-10-13: 2d-4b3e1-repair-1 design stop and operator ruling
- Sol (`ddcf72d4`, `8e1b0dc`) stopped after the design, as the brief requires.
- **The inventory:** 36 JSON columns across 29 tables.
- **The compatibility finding:** Router and Store paths currently admit NUL member names in open JSON. These are attempted-request records, which keep the request even on failure; contract confidence-scheme labels; and direct Store writes.
- **N1 is documented:** extractor identity is an exact comparison of caller-declared labels, and must be settled before receipt consumption.
- **Operator ruling (Trevor):** stored logical JSON member names are NUL-free. Router and Store refuse them, through a C-13 amendment. A failed attempt whose request contains one keeps that request as exact raw bytes plus its hash.
- **Re-dispatched** under the same brief; still round 2, because no review was consumed.

## 2026-10-13: 2d-4b3e1-repair-1 part 1, round 2: BLOCK on R2-1 and R2-2
- **Astra** (`54094fc5`, pinned d41e42c; `private/reviews/gen2-2d-4b3e1-r2-astra-review-20261013.md`): **A BLOCK, B PASS (carried), C BLOCK.**
- **Accepted:**
  - SQL 23's domain on the three covered columns: 96 independent raw cases (84 refusals, 12 readable controls);
  - the Router and Store NUL-name refusal and the C-13 amendment;
  - the F2 fixture;
  - generator drift checks;
  - the 33 named pending columns owned by part 2.
- **R2-1 (MEDIUM):** the static inventory scanner misses quoted function names, a comment before the `(`, a `'--'` inside a string literal, and an alias-borrowed retained-BLOB exclusion. Astra's five probe schemas pass `gen2-ddl` with exit 0, which defeats the requirement to prevent recurrence. The root cause is a custom partial SQL scanner.
- **R2-2 (MEDIUM):** the landing `gen2-check` exited 2. Thirty `test_exact_spans` subtests expect the old schema diagnostic, but the inputs are now refused earlier, as NUL member names. The refusal is still correct.
- **Landing at d41e42c:** `gen2-check` exit 2. `gen2-gateway` green, with 413 mutants killed.
- **Routed:** `docs/gen2/tasks/2d-4b3e1-repair-2.md`, **round 3 of 3 (the cap)**. Replace the hand-rolled discovery with an established, fail-closed approach (a SQL parser or SQLite's authorizer). New coder gate: the full `make gen2-test` whenever shared core modules change.

## 2026-10-14: 2d-4b3e1-repair-2, round 3 (the cap): PASS. 2d-4b3e1 accepted
- **Astra** (`d6ddbdcb`, pinned b731a22; `private/reviews/gen2-2d-4b3e1-r3-astra-review-20261014.md`): **A, B and C all PASS. "2d-4b3e1 is ACCEPTED (the JSON-domain rollout part 2 remains, owned by this task)."**
- **R2-1 closed (root cause).** The custom scanner was replaced by an exhaustive SQLite-catalog classification: 524 TEXT columns, of which 36 are JSON and 488 named scalar.
  - It is pinned to the installed-schema and ordered-DDL hashes, with no automatic refresh.
  - 26 independent checks cover views, triggers, CHECKs, expression indexes, defaults, generated columns, namespaces and preparation failure.
  - Retained-byte exclusions bind to catalog identity.
- **The authorizer evaluation was reproduced.** It doesn't report CHECK operands during DML preparation, so rejecting it was justified.
- **R2-2 closed.** Only the two expected diagnostics changed.
- **Landing at b731a22:** `gen2-check` green. `gen2-gateway` carried forward from d41e42c, green.
- **Operational note:** every future DDL slice must re-review the classification and update both hashes, by design.
- **Next:** 2d-4b3e1-json2 (`docs/gen2/tasks/2d-4b3e1-json2.md`): attempted-request raw-byte retention, the domain on every write path, and the 33 pending columns.

## 2026-10-14: 2d-4b3e1-json2 part 1 (retained refused requests; observation JSON domain): round 1 BLOCK
- **Astra** (`57c70235`, pinned 0c1c8fb; `private/reviews/gen2-2d-4b3e1-json2-astra-review-20261014.md`): **A BLOCK, B PASS, C BLOCK; MITIGATION.**
- **What passed:**
  - the six generated member guards;
  - the classification repin, independently reproduced;
  - C-11 coverage;
  - the 30-column ownership;
  - writer ordering for ordinary logical writes;
  - control-file churn: all 3,189 old entries are kept, the restored R2.5 control is legitimate, and the module re-anchors are legitimate.
- **F1 (HIGH):** SQL 24 binds the retained-request descriptor only when `request_bytes` is non-NULL. A copied descriptor with no bytes is accepted by the Router, even as observed or exhausted with a capture acknowledgement. A retrieval event then crashes `accounting.read_page` (`KeyError: 'page'`).
- **F2 (HIGH):** retention depends on normalizing and decoding a discriminator. Refused requests with a NUL-named or duplicated `request_type`, and object-form NUL filters, leave **zero observation rows**, which violates the operator's every-attempt-recorded ruling. The docs' claims of unconditional retention are therefore not yet true; this is boundary drift, fixed as part of F1 and F2.
- **F3 (MEDIUM):** the `2B13-cursor-beyond-the-bound` mutant was re-paired to a control that never reaches the integer predicate.
- **Landing at 0c1c8fb:**
  - `gen2-check` green: 3,543 tests; 3,214/3,214 mutants killed.
  - `gen2-gateway` green.
- **Routed:** `docs/gen2/tasks/2d-4b3e1-json2-repair-1.md`, round 2 of 3.

## 2026-10-14: json2-repair-1, both parts landed; process incident
- **Part 1** `bc6fffa` closes F1 and F3. **Part 2** `db85860` closes F2: unconditional failed-attempt retention and an explicit opaque failed representation.
- Both parts are reviewed together as round 2. Landing at db85860 is running.
- **Process incident (disclosed by the coder):** a disposable snapshot that symlinked `.venv-gen2` caused `make` to run `venv --clear` against the shared environment.
  - It was restored from cached hash-locked wheels. The orchestrator verified the installed package set is identical to the 10-14 00:15 clone's (11 packages, the same dist-info).
  - All credited validation came after the restore.
  - **Rule:** disposable snapshots copy `.venv-gen2` (`cp -a`) and touch `.gen2-installed`. They never symlink it.

## 2026-10-14: json2-repair-1 (both parts), round 2: BLOCK on the remaining part of F2
- **Astra** (`a33674f2`, pinned db85860; `private/reviews/gen2-2d-4b3e1-json2-r2-astra-review-20261014.md`): **A BLOCK, B PASS, C BLOCK.**
- **F1 closed (root cause).** Descriptors are bound both ways by SQL 24/25, ordinary requests can't impersonate one, and accounting validates the whole representation.
- **F3 closed.** The numeric control reaches the predicate; a reject-all-integers counterfactual makes it fail six times.
- **Also accepted:** SQL/classification/C-11; control audit (3,228 entries, only F3's entry changed); producer chain; last-value-wins removed; the venv incident does not compromise the evidence.
- **F2 remaining (HIGH):** retention happens only when strict parsing raises `MemberNameError`. An earlier numeric error (an integer above 2^53−1, or a precision-losing float) returns `request_invalid` with **zero rows**, so the same refused document is retained or lost depending on member order.
- **Landing at db85860:**
  - `gen2-check` green: 3,571 tests; 3,228/3,228 mutants killed.
  - `gen2-gateway` green.
- **Routed:** `docs/gen2/tasks/2d-4b3e1-json2-repair-2.md`, **round 3 of 3 (the cap)**. Any authenticated failed attempt whose request is not admissible as logical JSON for **any** strict-parse reason is retained as opaque exact bytes plus hash. This follows the operator's every-attempt-recorded ruling. Ordinary validation is unchanged.

## 2026-10-14: json2-repair-2, round 3 (the cap): PASS. json2 part 1 accepted
- **Astra** (`59fc121d`, pinned b916117; `private/reviews/gen2-2d-4b3e1-json2-r3-astra-review-20261014.md`): **A, B and C all PASS. "2d-4b3e1-json2 part 1 is ACCEPTED."** There are no blocking findings.
- **F2 closed (root cause).** Retention catches every strict-parse refusal (`ValueError`, `RecursionError`) for a valid failed/unobserved envelope.
  - All nine edge probes record exact bytes and replay.
  - Further probes also pass: empty text, whitespace, non-JSON, a literal NUL, a BOM, trailing garbage, an escaped lone surrogate, 5,000-digit integers, 2,000-level nesting and extreme exponents.
  - Ordinary validation is intact.
  - The refusal-class audit is bound, immutable and written in the same transaction.
- **Landing at b916117:**
  - `gen2-check` green: 3,233/3,233 mutants killed.
  - `gen2-gateway` carried forward from db85860, green.
- **Next:** 2d-4b3e1-json2b (`docs/gen2/tasks/2d-4b3e1-json2b.md`): global admission and the 30 remaining pending columns.

## 2026-10-14: 2d-4b3e1-json2b part 1 (global JSON admission; SQL 26): PASS on the first review. Accepted
- **Astra** (`67d4ef2f`, pinned a28c7e2; `private/reviews/gen2-2d-4b3e1-json2b-astra-review-20261014.md`): **A, B and C all PASS, ROOT-CAUSE for the slice.** There are no blocking or non-blocking findings.
- **Coverage:**
  - All 28 Router document entry points reach `boundary.normalize`, which now enforces the member domain by default.
  - Store INSERT and UPDATE enforce it on all 36 columns, independently of the triggers.
  - All 8 newly guarded columns' writers are covered before SQL runs.
  - No bypass was found.
- **Unchanged:** the failed-attempt path, SQL 21/23–25 and `service.py`, byte for byte.
- **Landing at a28c7e2:** `gen2-check` green; `gen2-gateway` green.
- **Next:** json2b part 2, raw-DDL guards on the 22 remaining columns (see the brief's continuation).

## 2026-10-14: 2d-4b3e1-json2b part 2 (SQL 27, the final 22 columns): PASS on the first review. The JSON member-name family is closed store-wide
- **Astra** (`318a9e28`, pinned b66298f; `private/reviews/gen2-2d-4b3e1-json2b-p2-astra-review-20261014.md`): **A, B and C all PASS, ROOT-CAUSE.** "2d-4b3e1-json2b part 2 is ACCEPTED; the JSON member-name family is closed store-wide."
- **Coverage:**
  - 36 of 36 JSON columns guarded, with 72 INSERT/UPDATE triggers and zero pending.
  - The scalar spot-checks found no hidden JSON.
  - All 28 production writers go through Store admission.
  - SQL 21's uniqueness predicate is accurately documented as redundant, and the rest of SQL 21 is unchanged.
  - 135 tests got individual ACCEPT verdicts.
- **Landing at b66298f:**
  - `gen2-check` green: 3,781 tests; 302 triggers in reverse order; 3,357/3,357 mutants killed.
  - `gen2-gateway` green.
- **Operator ruling 2026-10-14 (Trevor), settling N1:** extractor identity comes from an operator-maintained tool **registry** with families. Independent validation needs a different family; unknown or aliased tools are refused.
- **Next:** 2d-4b3e2 (`docs/gen2/tasks/2d-4b3e2.md`): the registry, then receipts consume the durable extraction and validation records. SQL 17 stays in force.

## 2026-10-14: 2d-4b3e2 part 1 (extractor tool registry, SQL 28): round 1 BLOCK on C1 (evidence only)
- **Astra** (`1eadbfa1`, pinned 1013ed6; `private/reviews/gen2-2d-4b3e2-astra-review-20261014.md`): **A PASS, B PASS, C BLOCK; ROOT-CAUSE.**
- **What passed:**
  - registry admission, versioned provenance and the operator-only authority route;
  - immutable storage;
  - the registry binds approved declarations without claiming to certify execution or semantics.
- **C1 (MEDIUM):** four new mutants (`router-membership`, `router-replay` and two classification mutants) are paired with controls that never reach the changed code; a line trace shows zero lines in the target. The killers are valid; the pairings break the positive-control rule.
- **Landing at 1013ed6:** `gen2-check` green; `gen2-gateway` green.
- **Routed:** `docs/gen2/tasks/2d-4b3e2-repair-1.md`, round 2 of 3, tests and tooling only.

## 2026-10-14: 2d-4b3e2-repair-1, round 2: PASS. 2d-4b3e2 part 1 (registry) accepted
- **Astra** (`6724bdcb`, pinned 23440ec; `private/reviews/gen2-2d-4b3e2-r2-astra-review-20261014.md`): **A, B and C all PASS. "2d-4b3e2 part 1 is ACCEPTED."**
- **C1 closed.** Each of the four repaired pairings reaches its changed line, as the trace shows. The audit of all 37 pairings was independently reproduced. Exactly four of 3,394 control entries changed.
- **Landing at 23440ec:**
  - `gen2-check` green: 3,852 tests; 310 triggers in reverse order; 3,394/3,394 mutants killed.
  - `gen2-gateway` carried forward from 1013ed6, green.
- **New brief rule:** new mutant pairings need trace evidence that the control reaches the changed code.
- **Next:** 2d-4b3e2 part 2: `/2` validation records and both receipt consumers. SQL 17 stays.

## 2026-10-14: landing at 0cfb573 (2d-4b3e2 part 2, slice 1): mutation baseline timing flake, rerun queued
- The `gen2-check` unit suite was green (3,947 tests) and trigger order was green (318 triggers).
- The mutation harness's child-tree baseline then failed on one timing-dependent gateway-routes test, which uses a 0.2-second client deadline. `gen2-check` exited 2 before any mutant ran.
- Five standalone reruns pass, and the commit doesn't touch the gateway client.
- Recorded as **DEBT-039** (owner: task 2d): make deadline-based client and route tests independent of load, at the root.
- The run 1 record is kept as `gen2-check-run1-baseline-flake.*`. `gen2-check` is being rerun after `gen2-gateway` finishes, so the two don't overlap.

## 2026-10-15: 2d-4b3e2 part 2 slice 1 (SQL 29, `extraction-validation/2` records): round 1 BLOCK on F1
- **Astra** (`75df59cf`, pinned 0cfb573; `private/reviews/gen2-2d-4b3e2-p2-astra-review-20261014.md`): **A BLOCK, B PASS, C BLOCK; MITIGATION.**
- **What passed:**
  - non-NULL registered pins, with no `/1` or NULL-pin operands;
  - a version-only change can't create independence;
  - validator/producer separation;
  - exact acquisition bindings;
  - no authority consumer reads `/2`, and SQL 17 still fences;
  - SQL 29/30 additive, with all 384 prior objects unchanged;
  - C-11;
  - 41 control traces qualify.
- **F1 (MEDIUM):** each operand's family is resolved under its own registry revision and the labels are compared. An audited family **rename** between revisions makes a same-tool or same-family replay succeed as "independent", through both the Router and raw DDL. `test_snapshot_control` accepts one form of it.
- **Landing at 0cfb573:**
  - `gen2-gateway` green.
  - `gen2-check` run 1 exited 2 because of the mutation-baseline timing flake (DEBT-039).
  - The rerun at the same commit was **green** (3,786 s).
- **Routed:** `docs/gen2/tasks/2d-4b3e2-p2-repair-1.md`, round 2 of 3. The fix is a coherent operator-governed family relationship across operands: a common comparison revision, or stable family lineage.

## 2026-10-15: 2d-4b3e2-p2-repair-1, round 2: PASS. 2d-4b3e2 part 2 slice 1 accepted
- **Astra** (`ab47b808`, pinned 50cff2e; `private/reviews/gen2-2d-4b3e2-p2-r2-astra-review-20261015.md`): **A, B and C all PASS, ROOT-CAUSE within the registry boundary.**
- **F1 closed.** Both rename reproductions are refused through the Router and raw DDL. 12 original and 16 extended probes behave correctly, and complete stable cross-revision controls are accepted.
- **Trust boundary noted:** the validator extraction's declared revision can be selected, so an older approved revision can still classify tools as separate after a later merge. This is acceptable under the repair as briefed, and it was raised to the operator.
- **Operator ruling 2026-10-15 (Trevor): the latest registry revision governs new validations.** Retained validations keep their recorded interpretation. This is folded into slice 2.
- **Landing at 50cff2e:** `gen2-check` green; `gen2-gateway` green.
- **Next:** slice 2: the latest-revision rule, then both receipt consumers. SQL 17 stays.

## 2026-10-15: 2d-4b3e2 slice 2 part 1 (latest registry revision for new validations; SQL 31): PASS on the first review. Accepted
- **Astra** (`c6a06d31`, pinned ad1cc4a; `private/reviews/gen2-2d-4b3e2-s2a-astra-review-20261015.md`): **A, B and C all PASS, ROOT-CAUSE.**
- **What it does:**
  - The Router and SQL 31 independently require the validator pin to equal the highest admitted registry revision. That value is monotonic, and an empty registry fails closed.
  - The check runs inside `BEGIN IMMEDIATE`, so a merge committed before the transaction takes effect.
  - Retained validations are unchanged.
- **Older target pins** stay valid as provenance, and both identities are compared under the current revision.
- **Landing at ad1cc4a:** `gen2-check` green; `gen2-gateway` green.
- **Next:** slice 2 part 2, both receipt consumers. SQL 17 stays.

## 2026-10-15: 2d-4b3e2 consumers part 1 (`verifier_extraction` durable basis; SQL 32): round 1 BLOCK on R1 (landing gate)
- **Astra** (`ecba52cc`, pinned dc81392; `private/reviews/gen2-2d-4b3e2-c1-astra-review-20261015.md`): **A PASS, B PASS (ROOT-CAUSE); C BLOCK.**
- **What passed:**
  - the receipt consumer binds a durable, pinned own extraction;
  - the SQL 21 trigger was replaced by a successor that differs only in its name and the optional member;
  - the trigger-order tool reverses all 321 installed triggers and is not weakened;
  - SQL 17 is intact.
- **R1 (MEDIUM):**
  - `gen2_mutations.uncovered_triggers()` inventories textual CREATEs, including the retired SQL 21 trigger.
  - The landing `gen2-check` exited 2 before **any** mutant ran.
  - `--only` runs skip that global check.
- **N1 (non-blocking):** the trigger-order tool prints 322; the installed count is 321.
- **Landing at dc81392:** `gen2-check` exit 2 (R1); `gen2-gateway` green.
- **Routed:** `docs/gen2/tasks/2d-4b3e2-c1-repair-1.md`, round 2 of 3, tooling only.
- **New coder gate:** run the full mutation inventory whenever a trigger is added, replaced or retired.

## 2026-10-16: 2d-4b3e2-c1-repair-1, round 2: PASS. Consumers part 1 (`verifier_extraction`) accepted
- **Astra** (`9dde41fe`, pinned 0364453; `private/reviews/gen2-2d-4b3e2-c1-r2-astra-review-20261015.md`): **A, B and C all PASS.**
- **R1 closed (root cause).** `tools/gen2_ddl_triggers.py` builds the final installed-trigger inventory from a fresh in-memory apply, and coverage and reversal share it.
  - Independent probes match all 321 installed triggers.
  - An uncovered live guard is still reported, even next to misleading commented `DROP` text.
  - Stripping the mutations reports all 321 guards.
- **N1 closed.** The installed count is now reported.
- **Landing at 0364453:**
  - `gen2-check` green: 4,039 tests; 321 triggers in reverse order; the full mutation run **without `--only`** killed 3,476/3,476.
  - `gen2-gateway` carried forward from dc81392, green.
- **Next:** consumers part 2, the `validated_extraction` consumer. SQL 17 stays.

## 2026-10-16: 2d-4b3e2 consumers part 2 (`validated_extraction` durable `/2` basis; SQL 33): PASS on the first review. Accepted
- **Astra** (`c6be3338`, pinned 25141bc; `private/reviews/gen2-2d-4b3e2-c2-astra-review-20261016.md`): **A, B and C all PASS, ROOT-CAUSE.** There are no blocking or non-blocking findings.
- **Binding:**
  - The receipt consumes the validation's **target** extraction, which must be the declared extractor and tool.
  - The validator must be the receipt's verifier, from an independent family.
  - This is the correct V-3 separation.
  - The Router and SQL predicates agree.
  - A validation admitted while its revision was current stays consumable after a later merge, which is the retained-history rule. A stale validation admitted *new* is refused.
- **SQL 17 is unchanged.**
- **Landing at 25141bc:** `gen2-check` green; `gen2-gateway` green.
- **2d-4b3e2 is complete.** It delivered the registry, the `/2` validations, the latest-revision rule and both receipt consumers.
- **Next:** 2d-4b3e3 (`docs/gen2/tasks/2d-4b3e3.md`), which replaces SQL 17 with bound-basis consumption. This is the step that lets extraction-based support become authoritative.

## 2026-10-16: 2d-4b3e3 part 1 (SQL 34 replaces SQL 17): round 1 BLOCK on F1
- **Astra** (`ed3418c1`, pinned ba94b99; `private/reviews/gen2-2d-4b3e3-astra-review-20261016.md`): **A BLOCK, B PASS, C BLOCK; MITIGATION while F1 remains.**
- **What passed:**
  - trigger retirement;
  - same-receipt gate binding, confirmed by 20 mixed-set probes that refused;
  - the target and acquisition ceilings;
  - `reproduced` is unreachable;
  - SQL 12 and the canonical `EvidenceWriter` capture are unchanged;
  - historical registry interpretation.
- **F1 (HIGH):** validated support is capped only by the **target** extraction's tier, never by the independent extraction's. A successful `/2` with a bibliographic-only independent output promotes a full-text claim. All 9 insufficient pairs promote, through the Router, raw DDL and reversed order. SQL 17 had hidden this.
- **N1 (LOW):** the mutant control rationale strings overstate tier breadth.
- **Landing at ba94b99:** `gen2-check` green; `gen2-gateway` green.
- **Routed:** `docs/gen2/tasks/2d-4b3e3-repair-1.md`, round 2 of 3. The fix caps validated support by the target, the independent extraction and the acquisition ceilings, at the consuming rule.

## 2026-10-16: 2d-4b3e3-repair-1, round 2: PASS. 2d-4b3e3 part 1 (SQL 17 replaced by bound-basis consumption) accepted
- **Astra** (`055c092b`, pinned 727dcda; `private/reviews/gen2-2d-4b3e3-r2-astra-review-20261016.md`): **A, B and C all PASS. F1 closed (root cause), N1 closed.**
- **The ceilings:**
  - Validated support is capped by the minimum of the target extraction, the exact independent extraction and the acquisition content, applied at promotion to retained and new receipts alike.
  - A sufficient distractor extraction can't stand in for the named operand.
  - The Router refuses new over-tier validated receipts.
- **Independent reproduction:** for each of the Router, raw DDL and reversed triggers, 3/3 insufficient cases are refused and 6/6 sufficient controls promote.
- **Landing at 727dcda:** `gen2-check` green; `gen2-gateway` green.
- **This is the first point where extraction-based support can become accepted support,** and only through a bound, tier-capped durable basis.
- **Next:** 2d-4b3e3 part 2, the pending-extraction attention holds.

## 2026-10-16: 2d-4b3e3 part 2 (pending-extraction attention): PASS on the first review. 2d-4b3e complete
- **Astra** (`9d6551ab`, pinned 0e903ee; `private/reviews/gen2-2d-4b3e3-p2-astra-review-20261016.md`): **A, B and C all PASS, ROOT-CAUSE.** Quote: "2d-4b3e3 part 2 is ACCEPTED; 2d-4b3e is complete."
- **The hold reads SQL 34's own view.** Attention consumes `bound_extraction_receipts` through a narrow Store read, so it inherits the same ceilings and lineage that promotion uses, with no second definition. A bound distractor can't exempt another receipt.
- **What the change doesn't do:**
  - The exemption is from the unbound-extraction hold only. It doesn't grant promotion.
  - Missing content and disagreement attention are kept, and no path clears a hold.
- **`service.py`:** one changed argument, now 1,443 of 1,500 lines.
- **Process note:** the coder disclosed one out-of-scope filename lookup in `~/.agents`. It had no matches and read nothing.
- **Landing at 0e903ee:** `gen2-check` green; `gen2-gateway` green.
- **2d-4b3e is complete.** It delivered durable extraction and validation records, the operator tool registry, the latest-revision rule, both receipt consumers, bound-basis promotion with tier ceilings, and the aligned attention holds.
- **Next:** 2d-4c (`docs/gen2/tasks/2d-4c.md`), attributed detailed V-8 check receipts (2d-4 part 3).

## 2026-10-17: 2d-4c design stop and operator ruling
- **Sol** (`868fed66`, `5009d9b`) stopped after the design, as the brief requires. The open question was what evidence makes each of the four V-8 checks performed, and whether `not_applicable` needs a reason.
- **Re-estimate:** about 1,900 lines, split into four parts. Part 1 is record admission, part 2 the successor receipt references, part 3 the fixture conversion, and part 4 mandatory consumption at promotion.
- **Operator ruling (Trevor): an attributed assessment with retained evidence.**
  - Every performed outcome needs a hash-authenticated evidence artifact recording the assessment, the method version and the examined context.
  - `not_applicable` needs an explicit reason.
  - Quote-matcher tokens count only as supplementary evidence.
- **Process note:** the coder disclosed an out-of-scope AGENTS.md lookup in an ancestor directory. It is the second such disclosure, so the brief now limits AGENTS.md lookup to the repository.
- **Dispatched:** part 1, record admission.

## 2026-10-17: 2d-4c part 1 (attributed durable V-8 check records; SQL 35/36): PASS on the first review. Accepted
- **Astra** (`bd0ba616`, pinned 89401a7; `private/reviews/gen2-2d-4c-p1-astra-review-20261017.md`): **A, B and C all PASS, ROOT-CAUSE for the admission slice.**
- **Operator-ruling fidelity:**
  - every performed outcome needs evidence and nonblank assessment and context;
  - `not_applicable` also needs a reason;
  - default-ignorable-only text is refused;
  - the evidence report must equal the recorded assessment;
  - quote-matcher methods are rejected.
- **Attribution:**
  - The performer comes from the committing invocation and is never declared.
  - The performer must be an independent, contract-admitted verifier.
  - Self-performance by the claim producer or the source producer is refused.
- **NB1 (coverage):** add regressions for corrupt recorded bytes, evidence left out of `result_refs`, and an ID collision under a new operation. Reviewer probes passed all three, and no defect was found. This is owned by part 2.
- **Landing at 89401a7:** `gen2-check` green; `gen2-gateway` green.
- **Next:** 2d-4c part 2, successor receipt references, optional and not yet mandatory.

## 2026-10-17: 2d-4c part 2 (verification-receipt/2, optional detailed-check refs; SQL 37): round 1 BLOCK (Gate C)
- **Astra** (`29714aac`, pinned 6c145ae; `private/reviews/gen2-2d-4c-p2-astra-review-20261017.md`):
  - **A PASS.** Exact relational binding; the explicit `succeeded→checked_ok` / `failed→checked_problem` projection gave 400 verdicts with zero divergence across schema, Router validator, collaborator and raw DDL; span guard v3 is text-identical apart from rename and root allowance; `service.py` is wiring only (1,448).
  - **B PASS.**
  - **C BLOCK.**
- **Production is ROOT-CAUSE at its optional-binding scope.**
- **Blocking findings (both experiment construction, charter class (e)):**
  - **C1:** `ReferenceCases.setUp` reseeds from normal DDL and reinstalls three guards in a fixed order. The reversed run had the same 334-trigger order, so the raw receipt cases had no reversed-order credit.
  - **C2:** the validated-extraction fixture uses equal canonical, target and validator hashes. A target→validator selector swap passed all 21 Router and all 20 raw receipt tests.
- **Astra's catalog-asserting probes:** the unmodified code passes in both orders, and the distinct-output cases kill both selector swaps (5 assertion failures each). **No production escape was shown.**
- **Non-blocking:** none.
- **Landing at 6c145ae:** `gen2-check` green; `gen2-gateway` green.
- **Next:** 2d-4c-p2-repair-1 (Sol), with an audit of the same reseed pattern in 7 other modules.

## 2026-10-17: 2d-4c-p2-repair-1 (receipt-reference test experiments): round 2 PASS. 2d-4c part 2 is ACCEPTED
- **Astra** (`a5243b02`, pinned 927b32d; `private/reviews/gen2-2d-4c-p2-r2-astra-review-20261017.md`):
  - **C PASS. A and B retained.**
  - **ROOT-CAUSE test repairs**; production unchanged.
- **C1 closed.**
  - `restore_triggers` rebuilds the complete requested catalog in requested order and asserts it.
  - With restoration made a no-op, the reset regression fails by assertion.
  - Astra independently reproduced all **14 modules / 25 classes:** 2 of 25 kept exact reversal before the repair, 25 of 25 after.
  - The nine defeated reseed owners are confirmed and repaired.
- **Earlier acceptances.** **421 focused raw-DDL tests** pass in both real normal order and real reversed order, covering the extraction, JSON rollout/member/completion, observation, detailed-record and receipt families.
  - **No previously accepted claim exposed an order-sensitive failure.**
  - Their earlier reversal-coverage gap is now closed.
- **C2 closed.** Distinct canonical, target and validator bytes in both matrices; Router and SQL selector mutants die by assertion; separate validated controls survive, with traces.
- **Landing at 927b32d:**
  - `gen2-check` green: 4,200 tests; 334 triggers / 3,967 reversal outcomes; 3,604/3,604 mutants.
  - `gen2-gateway` green: 413 mutants.
- **Next:** 2d-4c part 3, positive-fixture conversion.

## 2026-10-17: 2d-4c part 3a (extraction receipt fixtures converted to attributed `/2`): PASS on the first review. Accepted
- **Astra** (`22db54b3`, pinned 9416fd6, audit 4d98d83; `private/reviews/gen2-2d-4c-p3a-astra-review-20261017.md`): **A, B and C all PASS, ROOT-CAUSE within the authorized slice.**
- **The 3a/3b split is truthful.** Pending conversions are assigned to 3b, not hidden behind "historical" labels.
- **Fixture records come only through Router authentication.** There is no raw insert or bypass, and no IDs are manufactured at submission.
- **Each record binds the receipt's actual operands,** including the validated **target** output. Distinct canonical, target, validator and comparison bytes are kept separate from the byte-equal controls.
- **No production, DDL, pin or control-record change.**
- **NB1 (audit precision):** `AuthorityTest.test_a_producer_cannot_verify_its_own_work` ends in an accepted load-bearing receipt, so it is a real pending positive. It belongs to part 3b's checklist.
- **Process note (disclosed by Astra):** its first AGENTS filename search covered `/home/trevor/work`, outside scope. No files were opened. Reviewer task prompts now limit AGENTS lookup to the repository.
- **Landing at 9416fd6:** `gen2-check` green (4,206 tests; 334 triggers / 4,011 reversal outcomes; 3,604/3,604 mutants). `gen2-gateway` is carried forward from 927b32d, since no production change was made.
- **Next:** 2d-4c part 3b.

## 2026-10-17: 2d-4c part 3b (canonical, acquisition and content receipt fixtures, plus the NB1 authority control): PASS on the first review. Accepted
- **Astra** (`29bcfbe6`, pinned 1bfb9a9, audit 58608e6; `private/reviews/gen2-2d-4c-p3b-astra-review-20261017.md`): **A, B and C all PASS, ROOT-CAUSE.** No findings, blocking or non-blocking.
- **The opt-in conversion is scoped.** The optional-reference, legacy and byte-equal experiments keep their original fixtures.
- **Fixture correctness.**
  - The shared sender now uses the actual verifier invocation, which fixes the replacement-verifier path.
  - The readback oracle no longer depends on JSON member order.
- **NB1.** All four producer and verifier refusal cases are preserved, and the accepted control is converted.
- **The 3c pending list is truthful,** including the two amendment callers. Astra's own inspection of receipt builders found no omitted pending positive.
- **Landing at 1bfb9a9:** `gen2-check` green (4,211 tests; 334 triggers / 4,034 reversal outcomes; 3,604/3,604 mutants). `gen2-gateway` is carried forward from 927b32d, since no production change was made.
- **Next:** 2d-4c part 3c.

## 2026-10-17: 2d-4c part 3c (Router pending-bound, table, span and exact-span receipt fixtures): PASS on the first review. Accepted
- **Astra** (`f166f7bc`, pinned d140c23, audit 3fe2059; `private/reviews/gen2-2d-4c-p3c-astra-review-20261017.md`): **A, B and C all PASS, ROOT-CAUSE.** No findings.
- **Span discrimination.** PAGE, TABLE, mixed spans and the decoded exponent each get a distinct admitted record. Table refusal controls reattach records after the change to PAGE. The `start=1e30` exponent control survives.
- **Equal-byte controls get no selector credit.** The unchanged four-distinct-artifact experiment supplies that evidence.
- **Clarification:** valid bound support avoids a new missing-basis hold. It never clears an existing one. `ExtractionAttentionTest` owns the fenced matrix.
- **The 3d pending list is honest,** with no omitted positive owner.
- **Landing at d140c23:** `gen2-check` green (5,502 s). `gen2-gateway` is carried forward from 927b32d.
- **Next:** 2d-4c part 3d.

## 2026-10-17: 2d-4c part 3d (raw table receipt fixtures): PASS on the first review. Accepted, with an operator decision raised
- **Astra** (`95f9c5f5`, pinned 1faacfb, audit 2f192d3; `private/reviews/gen2-2d-4c-p3d-astra-review-20261017.md`): **A, B and C all PASS, ROOT-CAUSE.** No blocking findings.
- **Raw records are real.** `RawAssessmentFixture` admits 48 real records per owner through Router commits under unmutated DDL. The raw tests still exercise SQL admission, with further Router commits prohibited.
- **The four regressions:**
  - span/tier matrix;
  - foreign-span refusal and matching promotion;
  - no invented references for unperformed outcomes;
  - exact catalog restoration.
- **Counterfactuals all fail by assertion:** `/1` downgrade (9), collapsed spans (9), removed binding trigger (3), reset catalog (3).
- **NB1, NEEDS A DESIGN DECISION (escalated to the operator).** **The store accepts spans for which the Router cannot admit an exact matching detailed record.**
  - Astra probed the production Router with literal bytes:
    - 9007199254740991 commits;
    - 9007199254740993 and 9223372036854775809 are refused as `payload_invalid` under C-13.
  - Unmutated DDL accepts and promotes both values across all three methods.
  - **The cause is two accepted contracts meeting:** the 2d-4b3d exact integral span domain (no maximum) and C-13 canonical JSON.
  - **The operator decides:**
    - any amendment to the span domain or the canonical representation;
    - how it treats retained data.
  - **Until then:** do not close the raw-span conversion and do not activate part 4.
- **Landing at 1faacfb:** `gen2-check` green (4,220 tests; 334 triggers / 4,084 reversal outcomes; 3,604/3,604 mutants). `gen2-gateway` is carried forward from 927b32d.
- **Next:** 2d-4c part 3e, the non-span groups.

## 2026-10-18: 2d-4c part 3e (Router quote/capture/verdict receipt fixtures): PASS on the first review. Accepted
- **Astra** (`ad4b81ca`, pinned 2bf8bbe, audit 2165cfa; `private/reviews/gen2-2d-4c-p3e-astra-review-20261018.md`): **A, B and C all PASS, ROOT-CAUSE at slice and family level.**
- **Gate B, against the 2026-10-17 ruling:** attributed assessments supply every detailed outcome. Lexical quote protection never substitutes for them.
- **Coverage:**
  - six consumer classes converted;
  - all 132 original assertion-call ASTs unchanged;
  - both reseeding owners use `restore_triggers`;
  - the six raw-span owners are untouched and still pending, awaiting the 2^53−1 cap implementation.
- **NB1 (bookkeeping):** the active pending-status summaries should say "cap implementation pending", not "open operator decision". Owned by the next 2d-4c continuation.
- **Landing at 2bf8bbe:** `gen2-check` green locally (5,619 s). `gen2-gateway` is carried forward.
- **Jenkins:** branch build #6 on 2bf8bbe was **aborted at the 50-minute limit**, as expected. The fix is task ci-2.
- **Next (operator, 2026-10-18):** **ci-2**. Then the span-cap production slice, the remaining part 3 conversions, and part 4.

## 2026-10-18: ci-2 (Jenkins routine runner, first slice; branch sol/ci-2 51f8b01): round 1 BLOCK (Gates A and C)
- **Astra** (`d0f5f52a`; `private/reviews/gen2-ci-2-astra-review-20261018.md`).
- **These PASS:**
  - the independent same-pin comparison of every CI-executed mode at 3fc5acf;
  - unit and mutation partition conservation;
  - scope (no `gen2/` production, workflow or infrastructure change; no private content).
- **Classification:**
  - the quota-based worker budget is ROOT-CAUSE;
  - **the partial default CI execution is a MITIGATION** until std v1.2 and image `:2`, **pending operator acceptance.**
- **Blocking findings:**
  - **B1:** a skipped subtest fabricates a parent `fail` and a JUnit `<failure>`. Reporting semantics only; no real failure is masked.
  - **B2:** a green build doesn't declare PARTIAL ACCEPTANCE or the omitted work in its executed output and evidence.
  - **B3:** `test_ci_runner.py` misses skips and the loss of repeated identities under nontrivial sharding. An injected dedup-at-`total>1` defect passed all 12 tests while dropping 25 repeats.
- **Non-blocking:**
  - **NB1:** JUnit lacks SHA and shard properties.
  - **NB2:** the fixture-preservation wording overstates; classes can coalesce.
  - **NB3:** the remaining CI coverage is explicitly unfinished.
- **Next:** ci-2-repair-1, queued behind ci-cd-2 (one coder at a time).

## 2026-10-18: ci-cd-2 std v1.2 (ci-cd draft PRs #13–#15, stacked on #12): round 1 BLOCK (#15, Gates A and C)
- **Astra** (`6ad71c48`; `private/reviews/gen2-ci-cd-2-astra-review-20261018.md`).
- **Per PR:**
  - **#13 modes** (`0276dcc`): PASS as the scoped first layer.
  - **#14** (`4908993`): S1, an empty second-execution JUnit marked complete. Fixed in #15.
  - **#15** (`34db1c9`): **BLOCK.**
- **Scalar backward compatibility PASS** across ten normalized lifecycle/evidence snapshots versus v1.1, including sub-agent-router and ci-cd's own Jenkinsfile.
- **Blocking (both HIGH, ROOT-CAUSE):**
  - **B1:** the interlock doesn't revalidate target freshness after its evidence lookup. A target move during the final observation still yields SUCCESS with a stale `target_sha`.
  - **B2:** nightly evidence substitutes for integration on the mode label alone. A genuine nightly `smoke` record passed a PR whose integration workload never ran.
- **Non-blocking:**
  - **N1 (MITIGATION):** live qualification is outstanding.
  - **N2:** a consumer-aware release/rollback checklist is needed.
  - **N3:** the library is pinned to tag `v1.0.0` (PR #11), so a merge alone doesn't activate it. A release tag plus JCasC repoint is an operator step.
- **Next:** ci-cd-2-repair-1, queued behind ci-2-repair-1.

## 2026-10-18: ci-2-repair-1 (sol/ci-2 9b98090): round 2 PASS. ci-2 accepted for merge (operator merges)
- **Astra** (`ad10d982`; `private/reviews/gen2-ci-2-r2-astra-review-20261018.md`): **Gates A and C PASS.** B1, B2 and B3 closed; NB1 and NB2 handled; no weakening.
- **B1:** with the old methods restored, the committed suite fails by assertion (4 failures, 0 errors).
- **B2:**
  - Jenkins #6 (SUCCESS, 36 min 50 s) prints **PARTIAL ACCEPTANCE — NOT FULL ACCEPTANCE** before and after execution.
  - The structured record carries `acceptance: partial` / `full_acceptance: false` with SHA, tree, mode and shard.
  - The disclosure is published in the Jenkins test report.
- **B3:** the committed sharding and skip regressions catch the injected dedup defect.
- **The partial default stays a MITIGATION pending operator acceptance.** The quota worker budget is ROOT-CAUSE.
- **Next:** a PR from `sol/ci-2` into gen2 for the operator to merge.

## 2026-10-18: ci-cd-2-repair-1 (std v1.2, ci-cd #13 c4753df / #14 d154fe9 / #15 70f782a): round 2 PASS. Ready for operator merge
- **Astra** (`5e2266d3`; `private/reviews/gen2-ci-cd-2-r2-astra-review-20261018.md`): **the complete stack PASSES. B1 and B2 are closed at their root; S1 is preserved.**
- **B1:** the interlock re-fetches target HEAD and rereads the queue and evidence around the lookup.
  - The round-1 race (a move inside the final observation) now fails closed with "target HEAD changed during integration lookup".
  - An unavailable target and a throwing SCM read also fail closed.
- **B2:** only completed integration-mode evidence qualifies. The smaller-nightly, omitted-fallback and same-name/different-work substitutions are all refused.
- **Scalar compatibility is unchanged.** #14 isn't a standalone release, because S1 is fixed only in #15.
- **Operator activation steps** (report, "Operator activation and post-merge qualification steps"):
  1. Record the current state.
  2. Merge #12 → #13 → #14 → #15.
  3. Create a new immutable tag, `v1.2.0`.
  4. Repoint JCasC to the tag.
  5. Run the qualification checklist.
  6. Run a first gen2 consumer branch.
  7. Use the rollback plan if any drill fails.

## 2026-10-19: 2d-4c span-offset cap (f19725a, SQL 38): round 1 BLOCK (Gates A and C)
- **Astra** (`3f8529fc`; `private/reviews/gen2-2d-4c-cap-astra-review-20261019.md`): **A BLOCK, B PASS, C BLOCK. Family: MITIGATION, incomplete domain closure.**
- **Established:**
  - the exact `start`/`end` cap (a 38-numeral independent matrix shows no mismatch);
  - both 3d values refused (112 refusals, 56 exact-limit acceptances);
  - no rounding;
  - guards text-identical apart from the magnitude test;
  - 336 triggers, zero uncovered;
  - C-11 intact.
- **Blocking:**
  - **B1:** raw `claim_source_links` locator values may be over-cap **numbers**. The schema requires strings and the Router refuses them.
  - **B2:** `0e±999999999999999999999` (exact zero) is admitted by raw DDL but rejected by C-13 parsing. The cause is `Decimal` exponent capacity in `canonical._exact_float`. The defect predates the cap.
- **Orchestrator classification:** B2 is an implementation defect against C-13's existing text (exactly representable numerals are admitted). It needs **no operator C-13 amendment.**
- **Landing at f19725a:** `gen2-check` green (5,703 s); `gen2-gateway` green.
- **Next:** span-offset cap repair-1.

## 2026-10-19: span-offset cap repair-1 (04c7af7, SQL 39 + canonical exact-zero): round 2 PASS. Span-offset cap accepted
- **Astra** (`6650db33`; `private/reviews/gen2-2d-4c-cap-r2-astra-review-20261019.md`): **A, B and C all PASS. Family ROOT-CAUSE, domain closure complete.** No remaining findings.
- **B1 closed:** SQL 39 requires the raw link locator value to be JSON text.
  - 20 numeric-locator refusals and 10 accepted string labels across both orders.
  - Staged Router attempts agree.
- **B2 closed:** `canonical._exact_float` compares sign, significant digits and adjusted exponent instead of using Decimal.
  - An all-zero significand is exact zero.
  - The comparison is algebraically equivalent wherever Decimal could parse.
  - Previously accepted numerals keep identical floats and hashes.
  - The matrix shows zero numeric-domain and zero parser-domain mismatches; the 58 round-1 counterexamples are gone.
- **Landing at 04c7af7:**
  - `gen2-check` attempt 1 hit the DEBT-039 timing flake in the mutation baseline, after a green `gen2-test` (4,256) and trigger-order.
  - **Attempt 2 is green** (5,697 s, all checks).
  - `gen2-gateway` green.
- **Unblocked:** the six raw span and exact-span owners can now be converted.
- **Next:** the DEBT-039 root fix (the flake cost two landing cycles), then the remaining part 3 conversion.

## 2026-10-19: debt-039 (deterministic gateway-client deadline tests, b9ec00d): PASS on the first review. Accepted; DEBT-039 closed
- **Astra** (`75de015c`; `private/reviews/gen2-debt-039-astra-review-20261019.md`): **Gates A and C PASS, ROOT-CAUSE.**
- **Mechanism:** an injected monotonic clock and advancing sleep replace the scheduler-dependent oracle.
  - The production client still computes and enforces its own budgets.
  - The deadline stays at 0.2.
  - The redirect matrix asserts exactly one POST plus one GET.
- **No production change:** all 119 production files match their base bytes.
- **No test was removed.** Of the 259 methods in the six affected modules, 44 bodies changed; per-test review is in Astra's evidence.
- **Loaded landing:** `gen2-check` (including the previously flaky mutation baseline) and `gen2-gateway` are both green, run while a coder worked concurrently.

## 2026-10-19: 2d-4c part 3f (the six raw span and exact-span owners, b75bcb4): PASS on the first review. Accepted
- **Astra** (`df1a3f11`; `private/reviews/gen2-2d-4c-p3f-astra-review-20261019.md`): **A, B and C all PASS, ROOT-CAUSE.** No blocking findings.
- **Records:** the six owners use real Router-admitted records under unmutated DDL, followed by `restore_triggers`. Astra checked the unmutated catalog at seeding in both trigger orders.
- **Accepted literals keep their SQL experiments**, plus a rolled-back `/1` compatibility probe. Over-cap operands stay refusals.
- **All 31 existing assertion calls are unchanged.**
- **NB1 (naming):** `test_store_span_cap.AuxiliaryCapTest` calls `populate_every_table` but isn't named in the pending list. It falls in the pending population category; carry it into 3g.
- **Landing at b75bcb4:** `gen2-check` green (6,426 s). `gen2-gateway` is carried forward from b9ec00d.

## 2026-10-19: 2d-4c part 3g (remaining Router group: ImpactTest amendment positives and the cap Router matrix, 50d8b14): PASS on the first review. Accepted
- **Astra** (`6c69d49a`; `private/reviews/gen2-2d-4c-p3g-astra-review-20261019.md`): **A, B and C all PASS, ROOT-CAUSE.** No findings, blocking or non-blocking.
- **Records:** `ContractWorld.verify` admits real retained assessments through `Router.commit_outcome`, then restores the requested triggers before submitting the receipt.
- **Behaviour preserved:** compatible-amendment completion and promotion, and protocol-change fencing across all five job kinds.
- **Assertions unchanged:** 179 amendment assertion calls, 11 plain assertions and 18 cap assertion calls.
- **The pending raw/global group is listed honestly**, including 3f NB1 `AuxiliaryCapTest`.
- **Landing at 50d8b14:** `gen2-check` green (6,496 s; 337 triggers / 4,721 reversal outcomes; 3,618/3,618 mutants). `gen2-gateway` is carried forward.

## 2026-10-19: 2d-4c part 3h (raw content family, 7681a22): PASS on the first review. Accepted
- **Astra** (`24bfe096`; `private/reviews/gen2-2d-4c-p3h-astra-review-20261019.md`): **A, B and C all PASS, ROOT-CAUSE.** No findings.
- **Records:** `ContentDDLTest`, `ExtractionContentDDLTest` and `ValidatedContentDDLTest` take their references from real admitted records.
- **Fixture isolation:** full requested view and trigger restoration removes a fixture-isolation cause that had been masking content-view mutations.
- **The 2-line `PendingDDLTest` edit** (`ATTRIBUTED = False`) only keeps the pending path. Its SQLite dumps are identical to the base for six controls.
- **The pending list is complete,** confirmed by an independent population audit: 12 direct calls, plus 8 RolloutPairs and 22 CompletionPairs owners.
- **Landing at 7681a22:** `gen2-check` green (6,586 s). `gen2-gateway` is carried forward.

## 2026-10-20: 2d-4c part 3i (raw canonical and acquisition family, e8706a1): PASS on the first review. Accepted
- **Astra** (`dbb66c3b`; `private/reviews/gen2-2d-4c-p3i-astra-review-20261019.md`): **A, B and C all PASS, ROOT-CAUSE.** No findings.
- **All 25 original positive writes are converted:** 9 canonical, 16 extraction.
  - Each requires `/2`, the actual source-artifact identity and the method-selected examined bytes, with performer attribution.
  - Receipt insertion changes no other table.
- **The 18 original assertion expressions are preserved.**
- **Negative operands keep their relationships:** work, version, verifier, obtained hash, gateway call, retrieval, route and acquirer.
- **Fixture changes:**
  - fresh disposable stores replace the outer savepoints, because Router admission can't nest;
  - the alternate verifier's lease suffix was lengthened for schema validity, with its role unchanged.
- **Landing at e8706a1:** `gen2-check` green (7,047 s). `gen2-gateway` is carried forward.

## 2026-10-20: 2d-4c part 3j (PendingDDLTest family, 7419be4): PASS on the first review. Accepted
- **Astra** (`a611a7d2`; `private/reviews/gen2-2d-4c-p3j-astra-review-20261020.md`): **A, B and C all PASS, ROOT-CAUSE.** No findings.
- **The opt-out is gone:** `PendingDDLTest.ATTRIBUTED = False` is removed.
- **Assertions preserved:** all 23 original assertion-call expressions, and the 3 local plus 12 inherited methods.
- **Records:** `prepare_pending` restores unmutated views and triggers, then admits records through `Router.commit_outcome`.
  - Distinct claim/revision operands have disjoint record sets.
  - The existing `historical=True` negative keeps its role.
  - Matching canonical support still promotes; all four distractors still can't authorize.
- **Landing at 7419be4:** `gen2-check` green (7,050 s). `gen2-gateway` is carried forward.

## 2026-10-20: 2d-4c part 3k (global population root + raw quote/capture/adjudication, a7e01f5): PASS on the first review. Accepted; part 3 complete
- **Astra** (`5b37db2a`; `private/reviews/gen2-2d-4c-p3k-astra-review-20261020.md`): **A, B and C all PASS, ROOT-CAUSE.**
- **Completeness:** Astra's own inventory of all 201 test files (226 receipt literals, 225 builder/population candidates, wrappers and inheritance followed) finds no pending ordinary/current positive owner. Part 3 is complete within its fixture-conversion scope.
- **Converted together:** `StoreTestCase.verify` / `populate_every_table` and all forty consumers (including `QuoteTest`, `AuxiliaryCapTest`, eight RolloutPairs and twenty-two CompletionPairs), plus raw quote, capture and adjudication.
- **Mirror fixture:** admission runs on a disposable mirror under complete unmutated DDL with `(foreign_keys, recursive_triggers, ignore_check_constraints) = (1,1,0)`; copy-back is a privileged test-setup bridge (guards off during transfer, then flags and the exact trigger catalog restored). It builds no receipts or promotions. Astra probed all eight flag combinations; the full mutation inventory still kills through the owner.
- **Scope qualifications, not blockers:** copied rows include fixture preparation as well as admission effects; the rebound bridge is used for readback only by convention. Explicit optional/legacy admission experiments still describe pre-activation behavior, and **part 4 must deliberately change their disposition.**
- **Non-blocking NB-1:** stale "consumers pending" comments at `test_canonical_receipt_admission.py:54`, `test_canonical_content_tiers.py:30`, `test_store_content_tiers.py:30`. Fold into part 4.
- **Landing at a7e01f5:** `gen2-check` green (8,384 s). `gen2-gateway` is carried forward from `b9ec00d`.

## 2026-10-20: 2d-4c part 4a (mandatory detailed-record receipt admission, a0f976e): BLOCK, round 1
- **Astra** (`dd6ab23e`; `private/reviews/gen2-2d-4c-p4a-astra-review-20261020.md`): **A BLOCK, B PASS, C BLOCK.** 4a is classed **MITIGATION**: activation is incomplete over the raw admission domain. The warm mutation-loader repair (boundary-reload routes reload every Router collaborator that captures `Refusal`) is **ROOT-CAUSE**.
- **B1 (blocking):** SQL 40 requires references only for the summary values `checked_ok`/`checked_problem`/`not_applicable`. SQL 37 closes the domain for `/2` only, and SQL 03 excludes only `not_checked`/`unavailable`/missing. So raw `/1` load-bearing positives with out-of-domain summaries (`succeeded`, `invented`, JSON `1`/`true`/`{}`) **commit with zero records**.
  - Reproduced for canonical, own and validated extraction, in both trigger orders, under the full 338-trigger catalog.
  - The Router refuses the same operands (`payload_invalid`), so the layers disagree.
  - An adjudicated `supports` row then allowed a raw claim update to `accepted_support`.
- **NB1:** `test_bound_extraction_support.py:22` restores triggers by appending, losing order (SQL 40 moves from index 0 to 335 when reversed). Fold into the repair, before 4b relies on it.
- **Confirmed sound:** exact binding (SQL 37 and Router) intact; `historical_admission` is test-only, restores the exact catalog and order (nested and exceptional exits probed), and is used only at explicit historical/refusal sites; the legacy experiments assert substantive refusals; 3,618 prior control records and verdicts unchanged; `service.py` untouched; split honest.
- **Reviewer procedural deviation:** the initial AGENTS.md filename lookup extended to `/home/trevor/work`. Paths were listed but no file was opened. Disclosed by Astra.
- **Landing at a0f976e:** `gen2-check` green (8,482 s), `gen2-gateway` green (1,018 s). Green gates don't cover B1.
- **Routed:** `docs/gen2/tasks/2d-4c-p4a-repair-1.md` (B1 ROOT-CAUSE fail-closed repair via additive SQL 41, with a family audit; NB1 folded in).

## 2026-10-20: 2d-4c part 4a repair-1 (SQL 41 summary domain, c5bce59): PASS on round 2. Part 4a accepted
- **Astra** (`934916b8`; `private/reviews/gen2-2d-4c-p4a-r2-astra-review-20261020.md`): **A, B and C all PASS, ROOT-CAUSE.** Blocking list: none.
- **B1 closed at the root:** SQL 41 (BEFORE INSERT) allow-lists the four summary fields as JSON text in the five-label legacy vocabulary for every new load-bearing `supports`/`partially_supports` receipt, whatever its version or method. SQL 40 (AFTER INSERT) then requires the records, and SQL 03 still refuses `not_checked`/`unavailable`.
  - Astra reran the round 1 reproduction and its operand table: 192 refusals, with Router and raw layers agreeing.
  - An independent matrix added 5,664 refusals, covering case, whitespace, look-alike, fullwidth, zero-width and NUL variants, plus empty, numeric, boolean, array and null values.
  - Sampled and truthful-unsuccessful receipts and historical readback still work.
- **NB1 ROOT-CAUSE:** the extraction-history helper restores and asserts the ordered catalog. The old-helper counterfactual gives 2 assertion failures.
- **Gate C:** `2D4C4AR1-summary-domain` is assertion-killed by `test_b1`, and its separate control passes. All 3,632 prior control records are unchanged.
- **4b remainder (confirmed as promotion consumption, not current admission):**
  - SQL 03/SQL 34 promotion from a sole historical adjudicated `/1` receipt, for each basis;
  - SQL 12 governed-capture promotion and the final `commit_outcome` refence;
  - independent Router consumption;
  - durable checks and the basis on the same receipt, with no pooling and no adjudication waiver;
  - all existing tier/use/ceiling/tier-0/contract/canonical-capture gates preserved.
- **Landing at c5bce59:** `gen2-check` green (8,636 s), `gen2-gateway` green (1,020 s).

## 2026-10-21: 2d-4c part 4b1 (SQL promotion consumers, c5b2bec..b07a68f): PASS on the first review. Accepted
- **Astra** (`c4617aeb`; `private/reviews/gen2-2d-4c-p4b1-astra-review-20261021.md`): **A, B and C all PASS, ROOT-CAUSE** within the SQL-consumer scope. Blocking: none.
- **SQL 42** enumerates the four kinds independently of receipt contents. It requires a `/2` receipt with exactly four entries and an actual record for each, with a performed outcome. The outcome must match the referenced record and the summary projection exactly.
  - Joins bind topic, verifier, kind, claim/revision, full ordered spans, work/version, source hash, and the basis-selected examined bytes (canonical hash, own output, or the validation's **target** output).
  - Empty, partial, extra, historical `/1` and invented-summary receipts can't satisfy it.
- **Consumers:**
  - SQL 03/34 trigger bodies are mechanically unchanged apart from the added conjunct.
  - SQL 34 requires the **same receipt ID** in both the detailed and bound-extraction relations, so there's no pooling.
  - SQL 12 promotion and final audit consume the replacement relation.
  - Adjudication gives no escape from the actual-record requirement.
  - SQL 01–41 and production Python unchanged; no installation DML.
- **Provenance:** the orchestrator's `9788093` (`git commit -am`) captured Sol's in-progress implementation and was pushed. Astra judged the final tree, and the capture doesn't change the verdict. Lesson recorded: stage explicit paths only.
- **Non-blocking:**
  - NB1 size: 674 hand-written lines against a ~470 estimate and the ~500 guide. Not blocked (production SQL is 111 lines); keep 4b2 separate and re-estimate it.
  - NB2: the history-catalog test should request `unchecked=True` and assert `ignore_check_constraints` restoration. Astra's 8-case probe found no defect; fold into 4b2.
- **Landing at b07a68f:** `gen2-check` green (7,195 s), `gen2-gateway` green (1,013 s).

## 2026-10-21: 2d-4c part 4b2a (Router detailed-record consumption at promotion, d737331..0464983): PASS on the first review. Accepted
- **Astra** (`c8651983`; `private/reviews/gen2-2d-4c-p4b2a-astra-review-20261021.md`): **A, B and C all PASS, ROOT-CAUSE** within the slice. Blocking: none.
- **What it does:** `DetailedChecks.require_support` reads the stored claim's load-bearing designation and tier, plus the actual receipt columns. Detached JSON labels can't redirect it.
  - A `/2` receipt must carry exactly four performed kinds, each bound through the independent `require_receipt`, all on one candidate receipt.
  - It never queries SQL 42. It runs inside the existing writer transaction.
  - `service.py` gains only a 3-line delegate (1,451 of 1,500).
- **Survivor fix ROOT-CAUSE:** `1B-store-refusal-swallowed` survived because the new Router gate pre-empted the Store-refusal test.
  - The test now suspends only that Router instance's predicate (`patch.object`, restored on every exit) and asserts the Store-origin diagnostic.
  - The suspension is test-only, with no production bypass.
- **Carry-forward:**
  - (1) Remaining 4b2: same-receipt acquisition/bound-extraction qualification (extend the **same candidate selection**, not a separate existential check), capture promotion and final refence, and the retained-state guard.
  - (2) The reconciliation proposal is reserved for Trevor before any implementation. To settle: authenticated operator identity (never a caller label), manifest/request hash and stale-preview checks, topic vs whole-store scope, and authorized quarantine transitions. A preview or manifest can't confer support.
- **Landing at 0464983:** `gen2-check` green (7,313 s), `gen2-gateway` green (1,014 s).

## 2026-10-21: 2d-4c part 4b2b (same-receipt basis qualification in the Router, 380de3a..43772c5): PASS on the first review. Accepted
- **Astra** (`bd741a59`; `private/reviews/gen2-2d-4c-p4b2b-astra-review-20261021.md`): **A, B and C all PASS, ROOT-CAUSE.** Blocking: none.
- **Candidate loop:** `require_support` runs detailed qualification and `_has_basis(row, rank)` in the same candidate loop, and both must pass before that candidate returns. There's no pooling; a later complete candidate is still allowed.
- **Acquisition and content:**
  - acquisition uses the actual topic/work/version/verifier and the obtained hash, gateway call, retrieval and route;
  - canonical support binds the acquiring invocation;
  - content is selected by the retained record identity, and nonblank parity with SQL 16 was checked over 1,112,064 scalar values.
- **Extraction:**
  - own extraction needs the non-NULL pin, declared tool, invocation, verifier ownership, output tier and lineage;
  - validated extraction needs the exact `/2` `independent_extraction` result (policy 2, succeeded) and both output ceilings;
  - tier-0 alarms stay non-authorizing.
- **SQL comparison:** Astra compared against SQL 15/16/32/33/34/42 and found nothing weaker.
- **Corrections:**
  - the decoder now reuses `canonical.parse_json_strict` (NaN and duplicate-member gaps closed), with a paired mutant;
  - the `_has_basis` suspension is scoped to the older 4b2a test only, restored, and test-only.
- **Carry-forward:**
  - (1) capture/final refence, ~220 lines;
  - (2) the retained-state guard, ~200 lines; reconciliation decisions are still reserved for Trevor;
  - (3) evidence hygiene: the preliminary `control-preservation.json` count says 23 where the final is 24.
- **Landing at 43772c5:** `gen2-check` green (7,458 s), `gen2-gateway` green (1,014 s).

## 2026-10-21: 2d-4c part 4b2c1 (Router governed-capture promotion and final refence, 11828ff..b4b30e1): PASS on the first review. Accepted
- **Astra** (`87853626`; `private/reviews/gen2-2d-4c-p4b2c1-astra-review-20261021.md`): **A, B and C all PASS, ROOT-CAUSE.** No blocking or new non-blocking findings.
- **One candidate:** `require_support` carries a single candidate through verdict/use, claim tier, detailed records, basis/content and capture.
  - `quote_check_id` comes from the stored column. Canonical bytes are required when governed captures exist.
  - The former existential receipt search is removed, so there's no pooling; a later complete candidate is still accepted.
  - It matches SQL 12, and no SQL view supplies the Python decision.
- **`refence_captures`:**
  - selects only quote checks recorded by the committing operation, deduped by claim and revision;
  - leaves every status except `accepted_support` alone, and quarantines only revisions that fail qualification;
  - never sweeps the whole store, a whole topic, or the latest revision.
- **Placement:** it runs after all evidence and receipts, immediately before the final audit, inside the existing writer transaction, for both commit kinds. Replay, conflict and rollback are intact.
- **Landing at b4b30e1:** `gen2-check` green (7,560 s), `gen2-gateway` green (1,000 s).

## 2026-10-21: 2d-4c part 4b2c2 (retained-state guard + read-only history viewer, cf52bd1..5b01b6e): BLOCK, round 1
- **Astra** (`c7fcf7b5`; `private/reviews/gen2-2d-4c-p4b2c2-astra-review-20261021.md`): **A PASS, B PASS, C BLOCK.**
  - The guarded admission (both constructors and station startup, store-wide snapshot, `ReconciliationRequired` with topic/claim/revision/deficiency) is **ROOT-CAUSE** and conforms to the 2026-10-20/21 rulings.
  - So is the detached `HistoryReader` (closed data interface) and the temporal-fixture correction.
  - No production DML was found.
- **C1 (blocking):** `test_snapshot_and_no_dml` detects DML with the first-keyword regex `\s*(INSERT|UPDATE|DELETE|REPLACE)\b`.
  - Astra reproduced comment-prefixed and CTE-led opening `UPDATE`s and a `-- trace:`-style installation `INSERT` that change rows yet **pass** the test. A bare `UPDATE` correctly fails it.
  - Charter class (e): the test claims an operator-ratified property it doesn't enforce.
- **NB1:** the original-code comparison has 4 mock-induced errors in the startup subcases; fold into the repair.
- **Size:** 591 hand-written lines against the ~500 guide. Not required to split further.
- **Completeness:** Astra found no further missing production V-8 consumption step in 2d-4c. **2d-4c is complete once C1 is repaired and accepted.**
- **Landing at 5b01b6e:** `gen2-check` green (7,532 s), `gen2-gateway` green (1,018 s).
- **Routed:** `docs/gen2/tasks/2d-4c-p4b2c2-repair-1.md`: a ROOT-CAUSE, database-aware application-write oracle qualified by bare, commented and CTE canaries; NB1 folded in; test-only.

## 2026-10-21: 2d-4c part 4b2c2 repair-1 (d954236): BLOCK, round 2
- **Astra** (`5cddd8e6`; `private/reviews/gen2-2d-4c-p4b2c2-r2-astra-review-20261021.md`): **A PASS, B PASS, C BLOCK.**
- **NB1 closed (ROOT-CAUSE).** The lexical part of C1 is repaired at its cause: the SQLite authorizer observer catches comment/CTE DML, UPSERT/REPLACE, trigger bodies, a second connection, executescript, ATTACH, VACUUM INTO and FK cascades.
- **C1 still open:** a data-bearing installation `CREATE TABLE ... AS SELECT` writes an application row with no INSERT authorization and zero `total_changes`. The whole module still passes (15 tests). Dropping a populated table also passes.
  - This still violates schema-only installation (class e). The full guarantee is classed MITIGATION/incomplete.
- **Landing at d954236:** `gen2-check` green (7,563 s). Production unchanged.
- **Routed:** `docs/gen2/tasks/2d-4c-p4b2c2-repair-2.md`, the **final** round (3 of 3). It adds database-content observation (created tables must be empty, dropped tables must have been empty) plus a broad self-qualified canary set. If round 3 fails, escalate to Trevor.

## 2026-10-22: 2d-4c part 4b2c2 repair-2 (fca05ef): BLOCK, round 3 (cap reached; escalated to Trevor)
- **Astra** (`9f136232`; `private/reviews/gen2-2d-4c-p4b2c2-r3-astra-review-20261022.md`):
  - A PASS and B PASS; prior ROOT-CAUSE acceptance preserved; production unchanged; no new defect.
  - Maintainability PASS.
  - **C BLOCK:** C1 is MITIGATION/incomplete at the family level.
- **Repaired:** data-bearing DDL. Populated CTAS and DROP now fail by contents assertion. All 73 fixtures behave as expected.
- **Still open:** native SQLite row changes that are **written then restored** between observation points pass the test. The examples are `blobopen().write` and `Connection.backup`, which bypass the authorizer and trace callbacks.
  - Reproduced at the real opening seam via a test wrapper.
- **Orchestrator check:** production gen2 code makes **no** use of `blobopen`, `backup`, `serialize` or `deserialize` (grep). The gap is in what the test claims to cover, not in production behavior.
- **Round cap reached:** escalated to Trevor for disposition, with no fourth round.

## 2026-10-22: 2d-4c-p4b2c2-closure (native-API gate + narrowed claim, 323a18d..9ff9e54): PASS. 2d-4c part 4b2c2 accepted; **2d-4c COMPLETE**
- **Astra** (`13e93bf3`; `private/reviews/gen2-2d-4c-p4b2c2-closure-astra-review-20261022.md`): **A, B, C, maintainability and independent full verification all PASS; ROOT-CAUSE** under the operator-amended contract (2026-10-22). Blocking: none. **C1 closed.**
- **The gate:** `tools/check_gen2_sqlite_native.py` forbids `blobopen`, `backup`, `deserialize`, `enable_load_extension` and `load_extension` across the B-3 Python surface (tests exempt). It covers attribute access on any receiver, plus literal and attribute-qualified `getattr`, and fails closed on read or parse errors. It's wired into `gen2-check`.
- **The narrowed claim:** the `no_dml` docstring and DOSSIER now state the scope as SQL application-row writes plus SQL-boundary state, and cite the gate. The test module differs only in that docstring; all 17 methods are AST-identical, and all 73 fixtures behave as expected (56 failures, 17 controls).
- **First independent-verifier round:** Sonnet verifier `ed4b5338` ran `gen2-check` on a clean clone of `9ff9e54`: **exit 0, 7,644 s**. Gateway was carried forward from `5b01b6e`. The coder ran targeted checks only.

## 2026-10-22: 2d slice 5 (tier-0 disabled capability fact, d6376ad, PR #4): BLOCK, round 1
- **Astra** (`25dca0bd`; `private/reviews/gen2-2d-5-astra-review-20261022.md`): **A PASS, B PASS, C BLOCK.**
  - The implementation is ROOT-CAUSE: the existing `_fact` writer records `tier-0`/`unknown`/"tier-0 disabled" on both activation and restoration.
  - Status passes stored facts through, and absence never reads as a pass.
  - Opening and history stay read-only. No consumer reads the fact. The existing tier-0 *alarm* receipt guards are preserved (contract clarification).
- **B1:** the verifier's full `gen2-check` failed (1 of 4,403). `test_router_ops.AckDeliveryTest.test_failures_raise_capability_facts_on_transitions` expects only the connector fact. This is an overlooked consumer of the new row, found by the independent verifier rather than the coder's targeted checks. `gen2-gateway` passed.
- **NB1:** stale restoration descriptions in `registries.py` and `test_router_registries.py`.
- **Process finding:** PR #4 auto-merged (06:40Z, `54ce832`) before the verifier and Astra finished, because the Jenkins PR check runs only T0 static gates. gen2 therefore carries the B1 failure until the repair lands. Escalated: **Trevor ruled 2026-10-23** that auto-merge is enabled only after the verifier is green and Astra accepts (charter, PR-only gen2).
- **Routed:** `docs/gen2/tasks/2d-5-repair-1.md`, a family-level fix to the capability-fact consumers, on a new branch with auto-merge held.

## 2026-10-23: 2d slice 5 repair-1 (a891329, PR #6): ACCEPTED, round 2
- **Astra** (`a0c49495`; `private/reviews/gen2-2d-5-r2-astra-review-20261023.md`): **A PASS, B PASS, C PASS, ROOT-CAUSE.**
  - **B1 resolved at family level:** connector selection by capability identity, an exact tier-0 startup assertion, and full-row preservation of unrelated facts. Astra independently re-ran the consumer audit (38-module inventory matches) plus ten fault probes, all of which fail by assertion.
  - **NB1 resolved:** docstring-only; the AST is otherwise identical.
- **Verifier** (Sonnet `71bc2783`): gen2-check exit 0 (7,670 s; 4,403 tests OK, trigger-order OK, mutants killed); gen2-gateway exit 0 (1,013 s).
- **Auto-merge** enabled by the orchestrator after both passed; merged as `72c4ac1`. **2d slice 5 is complete.**

## 2026-10-23: 2d slice 6a redesign: design review (Astra `1e949316`)
- **Recommends D** for Phase 2: a store-wide generation in one WAL read snapshot, compared under BEGIN IMMEDIATE, with bounded recapture.
  - B is sound but disproportionate for one-topic operation. C has more proof obligations and no measured advantage. A leaves the writer-fenced reread unresolved.
  - DEBT-036 doesn't require topic-minimal invalidation. That cost came from the slice's own contract.
  - Revised remaining 6a estimate: about 1,800 lines (B would be about 2,320).
  - R2 and R3 approved in principle, with precision on zero-row DML and rollback.
- **Operator ruled D plus up to two automatic recaptures** (2026-10-23).
- **Disclosed deviation:** at the start of the review, Astra ran one AGENTS.md filename search across `/home/trevor/work`, before reading the path limit. Outside filenames were returned, but no files were opened. No action needed beyond the record.

## 2026-10-23: 2d slice 6a part 1 (WAL-read capture, 73a676f, PR #8): ACCEPTED, first review
- **Astra** (`f99c2961`; `private/reviews/gen2-2d-6a-p1-astra-review-20261023.md`): **A, B and C PASS, ROOT-CAUSE.**
  - Capture moved to a checked Store-owned `mode=ro` WAL reader (BEGIN DEFERRED, query-only, schema identity, device/inode checks), so the writer reservation is gone.
  - The concurrency regression is deterministic. In-memory fixtures don't reopen an empty `:memory:` database. 27 direct and 10 shared groups, with exact bytes and pins. Router and `service.py` unchanged.
  - D1 capture: no writer reservation; memory within budget; the measured sources match the committed bytes.
- **Verifier** (Sonnet `a855e9e0`): gen2-check exit 0 (7,740 s; 4,429 tests; mutants 3,755/3,755); gen2-gateway exit 0 (1,005 s; 413/413 killed).
- **Non-blocking items:**
  - NB1: the ML-0172–0181 ledger rationales describe the earlier Router-owned capture (folded into part 2);
  - NB2: full-read p95 is about 1 s and readers delay checkpoints, so measure live operands and reader effects later (folded into part 2);
  - NB3: device/inode checks are not the lifecycle or freshness proof (parts 3–4 and 6b1).
- Auto-merge enabled after both passed; merged.

## 2026-10-23: 2d slice 6a part 2 (fe03b1b, PR #11): BLOCK, round 1
- **Astra** (`431f883f`; `private/reviews/gen2-2d-6a-p2-astra-review-20261023.md`): **A PASS, B PASS, C BLOCK.**
  - The production change is ROOT-CAUSE: the readers no longer convert under the writer transaction.
  - 2a's behaviour preservation is confirmed, and the memory reading (149.5 MiB against ≤192 MiB) is honest.
- **C1:** the `boundary.py` mutation reload tuple omitted `gen2.router.accounting`, the new `Refusal` importer. This was the verifier's sole failure (1 of 4,441). Astra reproduced the stale-alias effect.
- **Verifier** (Sonnet `77b0c329`): gen2-check exit 2 (stopped at gen2-test); gen2-gateway exit 0.
- **Repair** `768364a` was dispatched as soon as the verifier flagged the failure, before Astra finished: reload order fixed, 45-entry audit, stronger guards.
  - Re-verification is gen2-check only; the gateway is carried forward from `fe03b1b`, since no gateway input changed.
  - **Round 2** dispatched (Astra `a61b039c`).
- **Non-blocking items:** full-route read p95 is about 2.7 s and reader lifetime about 0.9 s (allowed by R3; keep measuring); freshness and authority remain with parts 3–4 and 6b1.

## 2026-10-24: 2d slice 6a part 2 repair (768364a, PR #11): ACCEPTED, round 2
- **Astra** (`a61b039c`; `private/reviews/gen2-2d-6a-p2-r2-astra-review-20261024.md`): **A, B and C PASS, ROOT-CAUSE.**
  - C1 is closed at the family level. Astra's independent 45-entry reload audit passed 14 of 14 ordering checks.
  - Round 1's reload probe now passes.
  - Five in-memory counterfactuals each fail the strengthened guard by assertion, and no assertion was weakened.
- **Verifier** (Sonnet `f9743b5f`): gen2-check exit 0 (7,777 s; 4,441 tests; trigger-order and mutants passed). The gateway carry-forward from `fe03b1b` is valid, since no gateway input changed.
- Auto-merge enabled after both passed; merged. Part 3 dispatched.

## 2026-10-24: 2d slice 6a part 3 (store-wide generation, 6333f0b, PR #14): BLOCK, round 1
- **Verifier** (Sonnet `998135cb`): gen2-check exit 2, **382 failures of 4,460**; gen2-gateway exit 0 (413/413).
  - The coder's targeted selection followed new files and direct Store consumers only. It missed durable-opener, no-DML, full-state, crash/restart, lock-wait, replay and supervisor consumers.
- **Astra** (`0dbca75a`; `private/reviews/gen2-2d-6a-p3-astra-review-20261024.md`): **A PASS, B PASS, C BLOCK.**
  - R1: incomplete migration of the metadata-sensitive oracle family (MITIGATION at family level).
  - R2: the random epoch breaks exact replay stability.
- **Disagreement on the open-time epoch write.**
  - Astra treated it as a legitimate lifecycle write.
  - Sol's diagnosis found that it violates no-write-at-open and startup-before-effects. The orchestrator confirmed that `HistoryReader.open` reaches the writable open, so the read-only viewer writes.
  - Escalated as a boundary question. **Trevor ruled 2026-10-24: no writes on open**; restore detection goes through an explicit maintenance operation.
- **Repair** in progress on the same branch:
  - shared oracle fixes, deterministic replay epochs, reference-schema seed omission and conflict-policy regressions, as local commits up to `20f0b03`;
  - then the no-write-open redesign.
- **Process lesson (semantic-impact selection):** changes to `db.connect`, schema bootstrap or shared state fixtures require targeted checks over every durable-opener consumer, startup/history/no-DML, complete-state or allowed-effects, crash/restart, lock-wait, replay/recorder and supervisor test, including child processes.

## 2026-10-24: Gate S #1, whole-system simplification (first run)
- **Prompted by** the operator's concern that the build grows by stacking per-finding fixes. Measured at the time: about 20k lines of engine code (Python plus SQL) against about 56k lines of tests and 24k lines of tooling, 29 days in. Slice 6 had grown from 490 to about 3,200 lines.
- **Two independent reviews:**
  - Fable (`c7606dcc`, owner; `private/reviews/gen2-simplification-review-fable-20261024.md`);
  - fresh Astra (`00882e5f`; `private/reviews/gen2-simplification-review-astra-20261024.md`).
- **Where they agree:**
  - one enforcement layer per rule (semantic rules are currently duplicated in Router code and DDL, with twin tests and mutants);
  - the checking machinery is the largest deletion opportunity (metrics and source-contract ratchet, hand-written mutant inventory with traced controls, reload bookkeeping, replay and differential tools);
  - re-plan the rest of Phase 2 around 2f;
  - collapse the records.
- **Where they disagree** (sent to a Fable reconciliation, `06e72bb1`, before ruling):
  - A: which layer owns semantic rules (Fable says the Router, Astra says SQL);
  - B: whether 6a part 3's 111 DDL triggers should become a Router-maintained counter. That depends on a trace confirming the Router is the only production writer.
- **Operator rulings (Trevor, 2026-10-24):**
  - **Charter Gate S** adopted (PR #16): Fable, fresh session each run, with triggers and always-on simplicity rules.
  - **Cut the checking machinery back:**
    - tiered checks (quick per PR; the full gen2-check once at acceptance; trigger-order only on DDL changes);
    - standard automatic mutation on changed code instead of the hand-written inventory and traced controls;
    - retire the custom metrics and source-contract ratchet in favour of standard complexity tools.
    - The boundary graph, the 1,500-line file rule and the debt gate stay. Fable designs the replacement as one batch.
  - **Reorder Phase 2 around 2f:** finish 6a, then 6b1 (persist the rich dossier), slice 7 (completion approval binding), 2e1, a minimum 2e2, then 2f.
    - Slices 8–11 (approved-revision `/2` bundle assembly, JSONL connector, feed facts, freshness envelope) move after 2f.
    - Slice 12 is dropped, since 2f is the integration.
    - Until feeds exist, currency is reported as unknown.
  - **Collapse the records:**
    - INVARIANTS back to normative rules plus "enforced at" pointers, with the locator narrative moved to a generated table;
    - DOSSIER to the slice map, the decisions and the current contract, with history moved to private evidence;
    - BUILD-STATE to the current state.
    - No rule changes.
- **Held pending A/B:** the 6a part 3 merge (PR #14; its round 2 verifier and review are running) and part 4.

## 2026-10-24: Gate S reconciliation and operator rulings A/B
- **Fable reconciliation** (`06e72bb1`; `private/reviews/gen2-simplification-reconcile-fable-20261024.md`):
  - **A:** the Router should own every support/consumption rule; every production consumer of eligibility is already Python. Three insertion checks (SQL 15/16/19/20) need Router versions first.
  - **B:** a full writer trace found **101 production Store writes, all in `gen2/router/`**. The only other writers are `Store.maintain` (offline) and `connect(create=True)` (schema creation). `store_writers` is statically enforced.
- **Operator rulings (Trevor, 2026-10-24):**
  - **A: the Router owns semantic rules,** and the DDL keeps integrity only.
  - **B: 6a part 3 becomes a Store-level counter,** bumped once per committed transaction that writes a covered table. This amends R1:D's mechanism from "every covered row event" to "every committed covered write transaction, once". The no-writes-on-open and maintenance rulings stand.
- The part 3 round 2 review (`401825cd`) and verifier (`9dbd8910`) of the trigger design `25f4ab9` were **stopped**. Before stopping, its gen2-test had passed 4,475 tests.
- The counter redo was dispatched to Sol on PR #14. A Gate S plan for the remaining simplification batches was dispatched to Fable (`932fcdc2`).

## 2026-10-24: Gate S #1 plan approved (operator)
- **Fable plan** (`932fcdc2`; `private/reviews/gen2-simplification-plan-fable-20261024.md`): eight batches, one coder at a time.
  - R1: records collapse I.
  - S1: tiered checks and retirement of the replay, differential and move tools.
  - S2: automatic mutation in place of the hand-written inventory and controls.
  - S3: retirement of the metrics ratchet, ledger and source contract, in favour of radon ceilings.
  - 6a part 4 (about 250 lines).
  - S4: Router versions of the SQL 15/16/19/20 insertion rules.
  - S5: deletion of the semantic DDL and its raw matrices.
  - R2: INVARIANTS normative plus a generated traceability table.
  - S6: deletion of the JSON member-domain DDL guards.
  - Then 6b1 (about 350), 6b2 with 6b3 merged (about 450) and slice 7 (about 200).
- **Expected size:** engine side about 180k lines down to about 102k (tooling about 51k down to about 4k; tests about 65k down to about 47k; production flat). To 2f: about 4,750 lines planned, about 9,500 when adjusted for observed growth, with a risk band of about 14,000.
- **Operator approved all twelve decisions D1–D12 (Trevor, 2026-10-24):**
  - D1: deletion batches are counted by file.
  - D2: the replay, differential and move/inline tools are retired (charter refactor standard amended).
  - D3: the span cap and link locator go to S5.
  - D4: the JSON member-domain DDL guards go in S6, with `Store._prepare` as the single enforcement point.
  - D5: blocking radon ceilings.
  - D6: checks before 6a part 4.
  - D7: new task **2g** after 2f owns slices 8–11 (DEBT-040–043); the export legs of DEBT-033 and DEBT-035 move to DEBT-040.
  - D8: the `/2` rich member is deferred to slice 8.
  - D9: Gate S #1 stands as the 15,000-line growth review.
  - D10: the importer moves under `tools/` in S3.
  - D11: 6b2 and 6b3 merge.
  - D12: the CI-DESIGN amendment is drafted in R2.
- 2f reports scientific completion at revision and hash; export delivery as `not_attempted`; currency as `unknown` (`never_ran`). It is not claimed current.

## 2026-10-24: 2d slice 6a part 3, Store-level counter (45d9da1, PR #14): BLOCK, round 2 of 3
- **Astra** (`db31d8b4`; `private/reviews/gen2-2d-6a-p3-r2b-astra-review-20261024.md`):
  - **A BLOCK, B PASS, C BLOCK.** Gate S proportionality PASS: one Store counter is proportionate.
  - The counter design and the R1/R2 oracle and replay repair are ROOT-CAUSE.
- **R3:** the literal-DML lint recognized only three spellings. `INSERT OR ABORT`, `UPDATE OR ABORT` and commented `DELETE` passed it, and a reviewer-injected write committed without a bump. This is not a production bypass.
- **R4:** two mutants (`2B13-ddl-cursor-*`) went INVALID, because SQL 43 added a second occurrence of their anchor text.
- **Verifier** (Sonnet `aba0892d`): gen2-check exit 2 (unit suite 4,476 OK; trigger reversal OK; mutants 3,782/3,784 with 2 INVALID); gen2-gateway exit 0.
- **Cleanup observations:** a vacuous delete-all in `raw_population_fixtures`, and the now-unneeded replay `randomblob` wrapper.
- **Routed as one round 3 repair:**
  - a broad keyword-based literal-DML gate (complete for literals);
  - scoped cursor mutants;
  - both cleanups;
  - a selection-rule addition: run `--only` on every mutant whose anchor text occurs in a changed file.

## 2026-10-24: 2d slice 6a part 3, Store-level counter (4cd6f6c, PR #14): ACCEPTED, round 3 of 3
- **Astra** (`09946fe6`; `private/reviews/gen2-2d-6a-p3-r3-astra-review-20261024.md`): **A, B, C and S PASS, ROOT-CAUSE.**
  - R3 is resolved at the family level: a broad keyword literal-DML gate; 31 probes behaved as expected with no false passes.
  - R4 is resolved: the cursor mutants are scoped to `search_observations`, and the uniqueness check is unchanged.
  - Both cleanups (the raw-population delete-all and the replay `randomblob` wrapper) are removed.
- **Verifier** (Sonnet `5c103e24`): gen2-check exit 0 (7,902 s; mutants 3,786/3,786, zero INVALID). gen2-gateway was carried forward from `45d9da1` (exit 0), since no gateway input changed.
- Auto-merge was enabled after both passed; merged as `dbbdced`. **6a parts 1–3 are complete.** Next: S1 (tiered checks), then S2, S3, 6a part 4.
- **Part 3 history:** trigger design `6333f0b` (382 verifier failures) → no-write-open repair `25f4ab9` (superseded) → Store counter `45d9da1` (round 2 BLOCK on R3/R4) → `4cd6f6c` accepted. Against the trigger design, the counter removed about 1,900 lines.

## 2026-10-24: BUILD-STATE history moved (records batch R1)

By records batch R1 (Gate S plan §4 R1; operator ruling 5) the following sections of `docs/gen2/BUILD-STATE.md` at origin/gen2 `dbbdced` were replaced by a short "Current" and a rewritten "Phase 2 plan". Their text is preserved here verbatim so no narrative sentence is lost. Many facts also appear in the dated sections above.

### Moved: old "Current" (BUILD-STATE lines 5-87)

- **Operator rulings 2026-10-22: build efficiency** (Astra process review `private/reviews/gen2-process-efficiency-astra-review-20261022.md` plus five research reports; plan in `private/reviews/gen2-efficiency-plan-20261022.md`).
  - **Three roles.** The coder runs targeted checks only. An **independent verifier** runs the full set once per round: a fresh Sonnet 5.5 agent per `docs/gen2/VERIFIER.md` until CI qualifies, then CI. Astra judges. The orchestrator only routes.
  - **Mechanical batches** of up to about 800–1,200 lines.
  - **Acceptance contracts** agreed before coding.
  - Recorded in BUILD-CHARTER.
  - **Not adopted:** pipelining successors, the shared rule table, generated evidence.
  - **CI:** Trevor is doing the activation steps:
    1. merge ci-cd #12→#15;
    2. tag v1.2.0 and repoint JCasC;
    3. build image `:2`;
    4. merge gen2 PR #2.

    The coder's CI completion task and §4 qualification follow.
  - The in-flight p4b2c2 repair-2 landing stays orchestrator-run, as it started before the ruling. The new roles apply from the next round.
  - **PR-only gen2 (2026-10-22):** gen2 is being locked for auto-merge on Jenkins green (the ci-cd session applies the protection). Every change goes through a PR from a task or `orch/records-*` branch. main (gen-1) isn't touched. Charter "PR-only gen2".
- **OPEN ITEM, CI rollout stalled (raised to the operator 2026-10-17).**
  - **Where it stands:**
    - CI-DESIGN was approved 2026-10-05, and ci-cd PRs #5–#11 merged.
    - The rollout stopped after 2026-10-06: `ci/gen2-jenkinsfile-v2` waits on image `ci-py312-noble:2` on cir (an operator step; current status unverified).
    - The gateway suite needs a psycopg lock and the worker-budget fix.
    - The full `gen2-check` (~80–90 min locally) now exceeds the 50-minute Jenkins limit, so the §3.3 tiers are required.
    - `origin/gen2` was last pushed 2026-10-09 (`03b9b16`, Jenkins branch status success). The local gen2 head is 238+ commits ahead.
    - Coders still commit directly to gen2, because the PR workflow isn't live.
    - ci-cd PR #12 (std v1.1) has been open since 2026-10-05.
  - **Proposed:**
    1. Push gen2, then push on every accepted task.
    2. A coder CI task on a branch: Jenkinsfile v2, the gateway fixes and §3.3 tiers. Confirm with the operator before merging.
    3. The operator builds image :2.
    4. §4 qualification (drills plus a shadow window), then task-branch PRs that the operator merges.
  - **Operator 2026-10-18: push + queue the CI task.** gen2 pushed to `2bf8bbe` (was 03b9b16); pushing after every accepted task from now on. CI task `ci-2` is the next coder job after the part 3e review. **First Jenkins build on the pushed head (#6, 2bf8bbe) aborted at the 50-min limit** — expected; ci-2 fixes it. **ci-2 DISPATCHED 2026-10-18.** Image `ci-py312-noble:2` confirmed **not deployed on cir** (probe build sol/ci-2 #1, 8.6 s, pull access denied) — **operator step: build it on cir** per the ci-cd runbook. ci-2 amended to proceed on `:1` for T0 + engine modes meanwhile; gateway DB mode follows once `:2` exists. **ci-2 landed on `sol/ci-2` `51f8b01`** (Jenkins #4 SUCCESS 34m28s: T0 + trigger-order + units 1/8; CI modes identity-matched local at 3fc5acf; local full 3,604/3,604) — **Astra round 1 BLOCK** (B1 skipped-subtest false failure, B2 no PARTIAL banner, B3 runner tests too weak; comparison/partitions/scope PASS; partial default = MITIGATION pending operator acceptance); **ci-2-repair-1** `9b98090` (Jenkins #6 SUCCESS 36m50s with PARTIAL banner; comparison PASS) — **Astra round 2 PASS: ci-2 ACCEPTED for merge; PR sol/ci-2 → gen2 opened for the operator to merge** (partial default = MITIGATION pending operator acceptance); operator merges after PASS. Second blocker: deployed std has no per-mode executions → **operator 2026-10-18: Trevor reviews/merges ci-cd #12 (std v1.1); Sol drafts std v1.2 modes PR (task ci-cd-2).** **ci-cd-2 done:** stacked draft PRs ci-cd #13 (modes) → #14 (executions/evidence) → #15 (schedules/interlock), on #12; offline Groovy/archgate tests pass; live qualification only possible post-merge. **Astra round 1: #13 PASS; #15 BLOCK** (B1 interlock target-freshness race, B2 nightly substitutes for integration); **ci-cd-2-repair-1 done** (#13 `c4753df`, #14 `d154fe9`, #15 `70f782a`; offline suites + scalar compatibility pass) — **Astra round 2 PASS: std v1.2 ready for operator merge** (order #12→#13→#14→#15, tag v1.2.0, JCasC repoint, qualification checklist — see REVIEW-LOG). **Span-offset cap slice**: Sol `ec150f94` implemented it (uncommitted) then hit repeated "model at capacity" errors; a resume prompt then succeeded and **Sol is running again** (it fixed a stale SQL-21 test oracle; gateway gate reported green). A Sonnet 5.5 handoff (`5c132fa1`) was dispatched in error while Sol ran; Sonnet detected it, made no edits and stood down (archived). Sol finishes. **Landed `f19725a`** (SQL 38 + schema + Router cap; coder gates all green incl. gateway and 2,565 affected mutants; 614 lines vs 495 est., disclosed) — landing green; **Astra round 1 BLOCK** (B1 numeric link locators bypass raw cap; B2 exact-zero extreme-exponent spellings break raw/C-13 parity — a canonical.py exactness bug, not a C-13 change); **cap repair-1 landed `04c7af7`** (canonical.py exact-zero fix with identical prior hashes; SQL 39 string-only link locators; coder: 4,256 tests, 3,618 + 413 mutants) — landing green (gen2-check rerun after DEBT-039 flake; gateway green); **SPAN-OFFSET CAP ACCEPTED** (Astra round 2, ROOT-CAUSE). **DEBT-039 fix landed `b9ec00d`** (controlled time in gateway deadline tests; tests only; loaded sweeps + paired mutants) — **ACCEPTED, DEBT-039 CLOSED** (Astra first review, ROOT-CAUSE; loaded landing green). **Part 3f** `b75bcb4` (6 raw span/exact owners; tests only; 4,260 tests, 68/68 mutants) — landing green; **ACCEPTED** (Astra first review; NB1 → 3g). **Part 3g** `50d8b14` (split: Router group only — 2 amendment positives + cap Router matrix; tests only) — landing green; **ACCEPTED** (Astra first review, no findings). **Part 3h** `7681a22` (raw content family; tests only; 4,267 tests, 3,618/3,618 mutants) — landing green; **ACCEPTED** (Astra first review, no findings). **Part 3i** `e8706a1` (raw CanonicalDDLTest + ExtractionDDLTest; tests only; 4,271 tests, 68/68 mutants) — landing green; **ACCEPTED** (Astra first review, no findings). **Part 3j** `7419be4` (PendingDDLTest family; tests only; 4,275 tests, 195/195 mutants) — landing green; **ACCEPTED** (Astra first review, no findings). **Part 3k** `a7e01f5` (global root + all forty consumers, raw quote/capture/adjudication; tests only; 4,281 tests, 3,618/3,618 mutants; coder reports part 3 complete) — landing green; **ACCEPTED** (Astra first review; NB-1 stale comments only). **Part 3 COMPLETE.** **Part 4** re-estimated at ~820 lines and split (`db03684`). **Part 4a** `a0f976e` (SQL 40 + DetailedChecks: mandatory records for performed checks on new load-bearing receipts; first production change since part 2; 4,300 tests, 3,632/3,632 mutants, gateway 413/413) — landing green (check + gateway); **Astra round 1 BLOCK** (B1: SQL 40 fails open for out-of-domain `/1` summaries; raw load-bearing positives commit with zero records). **Repair-1** `c5bce59` (SQL 41 closes the load-bearing summary type/vocabulary; NB1 ordered restore; both ROOT-CAUSE; 4,313 tests, 3,633/3,633 mutants, gateway 413/413; historical promotion gaps recorded for 4b) — landing green (check + gateway); **Part 4a ACCEPTED** (Astra round 2, no findings; pushed `bd15baa`). **Part 4b** designed (`2aeef44`, ~880 lines → 4b1 ~470 SQL consumers / 4b2 ~410 Router consumers + retained-state policy). **Operator ruling 2026-10-20: refuse until reconciled** (retained accepted claims without qualifying records block active use with a reconciliation diagnostic; no installation DML, no silent grandfathering or demotion; the reconciliation procedure's scope goes back to Trevor before it is built). 4b2 follows 4b1. **Part 4b1** `b07a68f` (SQL 42 durable-binding relation; SQL 03/34 successors; SQL 12 capture/refence; 4,330 tests, 3,661/3,661 mutants, gateway 413/413) — landing green (check + gateway); **ACCEPTED** (Astra first review; NB size + CHECK-policy assertion). **Part 4b2** re-estimated ~900 lines and split (`0f3d9cd`). **Part 4b2a** `0464983` (DetailedChecks.require_support: independent Router detailed-record consumption at claim promotion; NB2; reconciliation design proposal in DOSSIER, for Trevor; 4,340 tests, 3,675/3,675 mutants, gateway 413/413) — landing green; **ACCEPTED** (Astra first review, no findings; reconciliation decisions reserved for Trevor before any procedure is built). **Part 4b2b** `43772c5` (same-receipt acquisition/bound-extraction qualification inside `require_support`; strict decoder; 4,347 tests, 3,699/3,699 mutants, gateway 413/413) — landing green; **ACCEPTED** (Astra first review, no findings). **Part 4b2c** designed (`117573a`, ~610 lines: capture/refence ~250 + guard/history interface ~360). **Operator ruling 2026-10-21: guarded start + read-only history viewer** (store-wide check at both Router construction paths and station startup; `reconciliation_required` diagnostic; separate closed read-only history reader). **Part 4b2c1** `b4b30e1` (same-candidate capture promotion + operation-scoped final refence; 4,355 tests, 3,708/3,708 mutants, gateway 413/413) — landing green; **ACCEPTED** (Astra first review, no findings). **Part 4b2c2** `5b01b6e` (guarded Router admission on both constructors + station startup; `ReconciliationRequired`; detached read-only `HistoryReader`; 591 hand-written lines; 4,368 tests, 3,720/3,720 mutants, 175 startup tests, gateway 413/413) — landing green; **Astra round 1 BLOCK** (C1: the zero-DML test misses commented/CTE DML; production clean). **Repair-1** `d954236` (test-only: SQLite authorizer-based application-write oracle qualified by bare/comment/CTE canaries; NB1 mocks; both ROOT-CAUSE; 4,370 tests) — landing green; **Astra round 2 BLOCK** (C1 open: CTAS installation DDL writes rows invisibly; NB1 closed). **Repair-2** `fca05ef` (test-only: authorizer + typed application-row multiset comparison across main/TEMP/attached schemas; 73 validation fixtures; ROOT-CAUSE; 4,372 tests) — Astra round 3 BLOCK (cap reached; C1 is open only for native SQLite write-then-restore APIs, which production never calls). **Operator ruling 2026-10-22: ban the APIs and narrow the claim.** Closure `9ff9e54` **ACCEPTED** (Astra `13e93bf3`; verifier `ed4b5338` gen2-check green 7,644 s). **2d-4c COMPLETE 2026-10-22.** **2d slice 5 ACCEPTED** (`d6376ad` + repair `a891329`; Astra round 2 PASS on A, B and C; verifier gen2-check and gateway exit 0; merged `72c4ac1`). Round 1 blocked on an overlooked capability-fact consumer that only the verifier's full run caught. PR #4 had auto-merged before review, so **operator ruling 2026-10-23:** code PRs open without auto-merge, and the orchestrator enables it after the verifier is green and Astra accepts. CI uses image `:2` (PR #5). **2d slice 6 IN PROGRESS** (PR #8, `task/2d-6`): design `d7ad2f6` re-estimates about 1,890 lines, split 6a/6b1/6b2/6b3. The 6a contract is confirmed, and the operator ruled D1/D2/D3 = A (2026-10-23). 6a re-estimated at 1,180 lines (size stop), so it is split 6a1/6a2/6a3 (440/390/350); slice 6 now totals about 2,590. **6a1 STOPPED at D1** (`fea623b`): capture p95 682.8 ms against a budget of ≤250 ms (memory 109 MiB, within the 128 MiB budget). The capture reads 64 MiB of selected data under BEGIN IMMEDIATE. Per the D1 ruling it is redesign, not tuning; Redesign: Astra recommended **D** (a store-wide generation), and **Trevor ruled D plus up to two automatic recaptures** (2026-10-23).
  - The remaining 6a is about 1,800 lines in four parts, so slice 6 totals about 3,210.
  - **Part 1 ACCEPTED and merged** (`73a676f`, PR #8; Astra A/B/C PASS; verifier green). **Part 2** (PR #11; 2a `d5319cb` relocation and 2b `fe03b1b` route, 444 lines; memory 149.5 MiB against ≤192 MiB): **Astra BLOCK round 1 on C1** (a mutation-harness reload gap, the verifier's sole failure). Repair `768364a`; **ACCEPTED in round 2 and merged** (verifier green). **Part 3** (`6333f0b`, PR #14; 111 triggers on 37 tables): verifier 382 failures; **Astra BLOCK round 1** (R1 oracle family, R2 replay randomness). The open-time epoch write was escalated, and **Trevor ruled no writes on open** (2026-10-24); restore detection goes through an explicit maintenance operation. Repair `25f4ab9` (no writes on open) is under verifier and Astra round 2. **Gate S #1 (2026-10-24):** the operator adopted Gate S, cutting back the checking machinery, the Phase 2 reorder around 2f (slices 8–11 after 2f, slice 12 dropped) and collapsing the records. **Operator ruled A: the Router owns semantic rules; B: Store-level counter replaces the 111 triggers.** Part 3 counter `45d9da1`: **Astra round 2 BLOCK** (R3 lint gap, R4 two INVALID mutants; the design itself is ROOT-CAUSE and proportionate). The round 3 repair (the cap) is dispatched. **The Gate S #1 plan was approved by the operator, all of D1–D12:** order PR #14, R1, S1–S3 (checks cut-back), 6a part 4, S4–S5, R2, S6, 6b1, 6b2, slice 7, then 2e1, 2e2-minimum and 2f. New task 2g owns DEBT-040–043. Expected engine side about 180k down to about 102k; about 9,500 lines to 2f, adjusted for observed growth. Last Gate S SHA: `65fb30e`.
- **Phase:** Phase 0 complete (0a–0d). **Phase 1 ACCEPTED 2026-09-29** (1a–1f). **Phase 2 OPEN** (operator, 2026-09-29): one complete single-topic research workflow. Decision layer disabled/unqualified throughout.
- **Branch:** `gen2` (dev workspace)
- **0a review verdict: BLOCK (all 3 gates).** Full report: research-loops-public/private/reviews/gen2-0a-astra-review-20260925.md (pinned SHA-256 manifest). Astra ran independent DB probes, not just re-review: found history-rewrite paths (REPLACE bypasses receipt immutability), decision-authorization not bound to subject/topic/hash, facet importance unrepresentable in schema, pre-contract discovery FK-blocked, and 16 of 86 tests need rewrite (3 mutations independently survived beyond the coder's claimed set). 70/86 tests and all 8 coder deviations ACCEPTED. (Test split corrected from an earlier 78/8 shorthand; see REVIEW-LOG.) Full findings + rulings logged: docs/gen2/REVIEW-LOG.md.
- **Doc corrections applied same session** (Gate B found 6 overclaims in the methodology synthesis beyond the 3 already-fixed citations): tier-0 NLI "verifies mechanically"/"guarantee" wording removed; Jev importance score "calibrated" language corrected to proposed/operator-authoritative; VoI-lite "resource-rational by construction" reworded as proposed heuristic; method-selection Noul battery now scores coherent templates, not independent per-family answers; stale "reviewers' verdicts were false" phrasing corrected to match the adjudication's actual ruling. All in methodology-synthesis-20260924.md.
- **Landed:** 0a-repair (17 commits, 5d59476..885f805) — all A1–A11 fixed, all 16 named tests (D06–D55, B20) rewritten, R1–R3 rulings implemented. `make gen2-check` green (orchestrator-independently-verified): 345/345 mutants killed, 177 unit tests, first production code in (193 lines, gen2/core helpers). Coder self-reported 2 process slips (make|tail hid a failing check twice) — both caught and amended before final commit.
- **0a-repair re-review: BLOCK, narrower — full report landed (381 lines).** A1/A9/A11 RESOLVED clean; A2–A8/A10 PARTIALLY RESOLVED with 8 findings RA1–RA8 (ranked: RA5 sampled-verification-promotes-load-bearing-claim highest, then RA1 decision-pointer substitution, RA3 pre-contract scientific writes, RA6 JSON/row contradictions, RA4 stale reconciliation, RA2 rating binding, RA7 checker gaps, RA8 integer-notation bounds). Gate B: 3 doc corrections completed same session (methodology lines 95/111, flow line 15 — REVIEW-LOG had wrongly described 2 of these as already applied; now actually fixed and grep-verified). Gate C: accounting corrected to 70 ACCEPT/16 REJECT (was misreported as 78/8); 12/16 rewrites clean, 4 need extension; 8 more Python mutants found surviving. **New engineering ruling: reject `pip --user --break-system-packages` as build practice — venv/isolated build image required before Phase 1.** Masked-build-failure incidents confirmed genuinely repaired (git reflog), no bad commit on branch tip. Full report + REVIEW-LOG entry: research-loops-public/private/reviews/gen2-0a-repair-astra-review-20260925.md.
- **Landed:** 0a-repair-2 (11 commits) — RA1–RA8 addressed (the third review found RA2 and RA3 only partially resolved: RA2-R, RA3-R below), 4 named tests extended, 8 independently-found Python mutants each given a killing test, environment fixed (hash-locked venv via `make gen2-venv`, `docs/gen2/ENVIRONMENT.md`, replaces rejected host-level pip install). Orchestrator independently re-ran `make gen2-check`: green, 194 tests (was 177), 427/427 mutants killed (was 345). 6 items flagged by the coder need Astra's ruling (RA2 storage-format assumption, RA3 interpretation scope, an open accepted_support design question, RA8 enforcement-layer consistency — see REVIEW-LOG).
- **Third re-review: BLOCK, substantially narrower — Gate B PASSED.** 6 of 8 RA findings (RA1,RA4,RA5,RA6,RA7,RA8) fully RESOLVED and independently re-confirmed by direct mutant recreation. 2 remain: RA2-R (contract self-parentage defeats the ancestor-only rating rule — no constraint stops `parent_revision = revision`) and RA3-R (a dossier's approval pointer isn't checked as proof an actual draft→approved transition happened). Both medium severity, both with the reviewer's specific fix already written out. Full report: research-loops-public/private/reviews/gen2-0a-repair-2-astra-review-20260925.md.
- **Landed:** 0a-repair-3 (6 commits) — RA2-R closed via one named CHECK constraint (`contract_parent_is_earlier`); RA3-R closed via a trigger requiring the approval pointer to be set only by a genuine draft→approved transition. Coder confirmed both fixes against the reviewer's exact pre-fix reproductions. Trigger-creation-order tested reversed (no change). Coder-reported `make gen2-check`: 198 tests (was 194), 433/433 mutants killed (was 427); orchestrator's independent re-run was still in progress at dispatch time.
- **0a ACCEPTED.** Fourth review: Gates A/B/C all PASS. Astra independently reconstructed both remaining attacks fresh (recomputed content hash, actual JCS serialization) against pre-fix and HEAD, confirmed both fail cleanly at HEAD with unchanged DB state; 5 fresh SQL mutations killed; reversed all 119 trigger orders, no change; confirmed the two rating triggers are byte-identical pre/post-fix (the ancestry fix genuinely needed no per-consumer special-casing). Full report: research-loops-public/private/reviews/gen2-0a-repair-3-astra-review-20260925.md.
- **Landed:** 0b (9 commits) — SQLite compat gate (hard requirement, landed first), both cleanups (dead transition edge, permanent reversed-trigger-order check), store write layer (single-transaction, JCS+identity-bounds enforced at write time not just schema), fingerprint-version on receipts, durable intake briefs, dry-run gen-1 importer (read-only, core-only boundary grant). Orchestrator independently confirmed: 262 tests pass, boundary/schema/DDL checks pass, reversed-trigger-order check passes; mutation count (515/515 claimed) still verifying.
- **First 0b review: BLOCK (Gate A + C), Gate B PASS.** 5 real findings, all independently reproduced by Astra: A1 (HIGH) — `Store.transaction`'s COMMIT sits outside the rollback path, so a COMMIT-time failure (e.g. a deferred-FK violation) leaves a live active transaction and can later be silently completed; A4 (MEDIUM) — `Store`'s public constructor bypasses the SQLite compatibility gate entirely (the new receipt tests themselves use this unchecked path); A2 (HIGH, boundary) — importer has two TOCTOU races (check-then-open on both the output report path and source file paths) demonstrated with synthetic symlink swaps; A3 (HIGH) — managed-store detection can be fooled by an external symlink, making a stale gen-1 queue appear authoritative; A5 (MEDIUM) — importer crashes uncaught on malformed input instead of reporting it, misses duplicate-ID collisions, and rounds fractional numeric tokens into valid-looking integers via lossy float parsing before bounds-checking. Gate C: one test outright REJECTED as tautological (importer "completeness" test only compares against its own output). All 8 coder proposals ruled (7 ACCEPT, 1 split). Full report: research-loops-public/private/reviews/gen2-0b-astra-review-20260925.md.
- **Landed:** 0b-repair (5 commits) — A1–A5 all closed, Gate C completeness test rewritten against a genuine hand-enumerated inventory, Gate B wording corrected. Orchestrator independently confirmed: 275 tests pass, boundary/schema/DDL/trigger-order checks all match (mutation count 560/560 claimed, still verifying). No live gen-1 state touched, importer access not widened.
- **Re-review: BLOCK narrower — A1–A4 fully RESOLVED (independently re-verified with extra fault injection: authorizer-denied ROLLBACK, deliberate cross-thread close-failure trigger, a novel filename-swap race — all correctly handled).** Only A5 remains, and only two narrow cases: A5-R1 (invalid Unicode reaching report metadata through paths the first fix missed — crashes with zero report output) and A5-R2 (an oversized numeric token exceeding Python's own integer-conversion limit isn't caught by existing exception handling — same zero-report-output failure mode). Both are the same underlying requirement (report malformed input, don't crash) with two more trigger cases. Full report: research-loops-public/private/reviews/gen2-0b-repair-astra-review-20260925.md.
- **Landed:** 0b-repair-2 (3 commits) — A5-R1/A5-R2 closed; coder also found+fixed an unprompted related bug (Decimal exponent overflow in the same numeral-exactness code path). Orchestrator independently confirmed 279 tests pass, all checks green.
- **0b ACCEPTED.** Final review: Gates A/B/C all PASS. A5-R1 (Unicode) and A5-R2 (integer-limit) both independently reconstructed against the review's exact reproductions and confirmed RESOLVED, including exact boundary behavior (4,300 digits maps normally, 4,301 correctly blocks; the interpreter's own conversion limit confirmed neither raised nor disabled). The coder's unprompted Decimal-exponent-overflow fix independently verified as real and correctly fixed — "positive evidence of testing discipline." A1–A4 reconfirmed unchanged via AST diffing (not re-run, per the task brief). Original `docs/gen2/tasks/0b.md` scope confirmed fully satisfied, item by item, not just the repair-round findings. The coder's missing final prose message ruled a process omission, not an unfinished requirement. Full report: research-loops-public/private/reviews/gen2-0b-repair-2-astra-review-20260925.md.
- **2026-09-26 — open questions resolved (orchestrator checked directly, per the user: "you can go see"; and "are these not covered in the architecture doc?" — most were):**
  - *gen-1 symlinks:* CLOSED. None in any gen-1 state the importer would read (`~/work/loops/loop-queue/state`, both Sep-9 cutover snapshots). gen-1 itself refuses a symlinked state dir (`research_loops/access.py:151`). Only symlinks found are 3 `auth.env` credential links in old per-project loops, outside any gen-1 root. The user's standing rule is no symlinks (fragile on this build). No-follow policy stands as built.
  - *queue `version`:* CLOSED. All 3 gen-1 queue files carry `version: 1`. Blocking on a missing version stays.
  - *importer live access:* SETTLED BY DESIGN, deferred to Phase 4. Sep-22 design review §Phase 4 already specifies it: shadow from captured observations or read-only live snapshots before the freeze, then freeze → consistent final snapshot → import/reconcile. The mechanism (e.g. SQLite backup of the managed store) is a Phase-4 build detail, not an operator question now. Note: the live managed deployment (STATUS.md queue revision 10042, updated 2026-09-26) keeps root-owned state the orchestrator's user can't read.
  - *`accepted_support` scope:* SETTLED BY DESIGN. Flow doc S3 step 9 (support is accepted only once its verification receipt exists) and §4 rule 5 ("unapproved work is never silently promoted") make it general, not per-consumer. Queued as a small repair task after 0c's review.
  - *Still the user's:* C-13 sign-off (the charter requires operator approval for any change to a frozen rule; Astra already approved the content) and the Phase 0→1 gate.
- *(superseded 2026-09-26, kept for history)* **TWO OPERATOR QUESTIONS reconfirmed, still open (factual, about your actual gen-1 deployment):** (1) the importer now refuses to follow symlinks even inside the gen-1 root — if your real deployment uses internal symlinks (e.g. topic directories), those would report as "not found." (2) a `queue.json` with no `version` field now blocks — do older gen-1 queues in your deployment omit that field? Astra's exact words on both: "I did not inspect it and do not infer the answer... This factual question remains open for the user."
- **New non-blocking follow-up (Astra's ruling on the coder's question 3):** the importer's report should eventually list files it never examined (not just unmapped fields within files it did read) — required before any report is trusted as Phase 4 migration-planning evidence, not required for 0b acceptance itself.
- **Both operator-escalation questions reconfirmed correct to leave open** — Astra explicitly declined to pick between the importer live-access options itself; both remain pending for the user (see above).
- **TWO OPERATOR-ESCALATION QUESTIONS from the coder, explicitly not decided by anyone in the build loop:** (1) should the dry-run importer ever run against live gen-1 state? (2) since the real deployment is likely managed/live, the importer will always report the JSON queue as a blocking stale snapshot when `state/control.sqlite3` exists — should it instead get a read-only `sqlite3` grant, or should gen-1 export its control store for the importer to read? Both touch the charter's strictest boundary (never touch gen-1 runtime/live state) and are flagged for the user, not for Astra or the orchestrator to pick.
- **OPERATOR DECISION NEEDED (not blocking the current repair, but should be settled before 0b's status semantics freeze):** should promotion to `accepted_support` require contract-admitted production generally, or stay limited to today's specific consumers? Astra's recommendation: require it generally if the status is meant to be globally reusable evidence — but this is explicitly the user's call under the charter, not a technical question. Current (limited) behavior stands until the user decides.
- **Operator item pending (explicitly not the review's or orchestrator's call):** retired topics cannot currently be revived without a new topic or an explicit amendment — Astra confirmed this is implemented as designed and declined to rule on whether a revival route should exist. Current behavior stands unless the user says otherwise.
- **Landed:** 0c (7 commits, 4a45d4f..ad3e2ec) — deployment contract, generated key catalog/.env.example with a registry-drift gate, export-sink schemas (bundle/manifest/receipt, structurally separate from the closed publication-sink vocabulary — coder's own design call, flagged for review), source-proposal schema + governance doc. Coder reports (not yet independently verified by orchestrator): `make gen2-check` green unpiped, 307 tests (was 279), 589/589 mutants (was 575), no gen-1 file touched, no engine logic added. Coder deliberately did NOT edit BOUNDARIES.md (widening the projector's entry is a normative amendment, not a coder's edit) — left proposed replacement text for review. 5 open questions carried to review (BOUNDARIES.md amendment text, obligation-disposition vocabulary timing, a gateway-touching cost_tier field proposal, port defaults needing deploy-time confirmation, freshness-envelope scope for export delivery).
- **0c review: BLOCK (A + C), Gate B PASS.** The design direction is accepted and every coder count was independently confirmed. Six spec/schema gaps (A1–A6) and one fixture that doesn't test its rule (C1). Full report: research-loops-public/private/reviews/gen2-0c-astra-review-20260925.md.
- **Landed:** 0c-repair (8 commits, cfd0c2b..234bce8). A1–A6 and C1 are closed, and the review's A2, A3 and A4 reproductions are now refused. The orchestrator independently observed the coder's final `make gen2-check`: exit 0, 321 tests, 605/605 mutants, 54 valid + 158 invalid fixtures. Notable: the C1 audit changed the shared schema checker to compare error counts instead of a set. It found 4 accepted 0a negatives each hiding a second rule failure: at ad3e2ec, 7 mutants survived while the whole check still passed. Only those fixtures' declared errors changed, and no 0a rule was touched.
- **0c-repair re-review: BLOCK, narrow (3 left, down from 7).** Webhook ack semantics, webhook ordering, and isolated identity negatives. Everything else is closed. Full report: research-loops-public/private/reviews/gen2-0c-repair-astra-review-20260926.md.
- **Landed:** 0c-repair-2 (3 commits, d129ae8..c4017c0). The webhook receiver protocol `export-webhook/1` defines explicit applied/already-applied acknowledgement and a closed list of atomic refusals; a 202 or anything unlisted is recorded as unknown. The receiver enforces the four ordering branches itself, one request per topic at a time. Three isolated identity negatives were added, and the compensated mutant plus its rotations are killed. Orchestrator ran `make gen2-check` independently: exit 0, 324 tests, 608/608 mutants, 55 valid + 161 invalid fixtures.
- **0c ACCEPTED 2026-09-26** (3 review rounds: BLOCK 7 findings → BLOCK 3 → ACCEPT). **PHASE 0 FULLY ACCEPTED (0a, 0b, 0c).** Full report: research-loops-public/private/reviews/gen2-0c-repair-2-astra-review-20260926.md.
- (History) **PHASE 0 REOPENED 2026-09-26 by operator ruling: task 0d.** Neo4j/Qdrant were hardwired as publication sinks, with a second generic export path built alongside. The ruling: one standard export API any database connects to, nothing specific to the operator's setup (open source), internal process unchanged. Coder agent 5985c8ba, brief docs/gen2/tasks/0d.md. Once 0d passes Astra, the Phase 0→1 gate returns with: C-13 ratification and opening Phase 1. The BOUNDARIES export amendment is now decided by the ruling.
- **Landed:** 0d (4 commits, e9be7a5..ce801d9). There is now one versioned export API (`export-manifest/2`, connector types sql/jsonl_file/webhook/extension), with no Neo4j/Qdrant/GraphRAG anywhere in the build. Store outbound tables were renamed and generalized. BOUNDARIES "Exporter"; INVARIANTS P-1…P-7; flow doc S8 was edited in place (it is gitignored). Orchestrator ran `make gen2-check` independently: exit 0, 351 tests, 674/674 mutants, 57 valid + 165 invalid fixtures. Known leftovers for review: DEPLOYMENT-CONTRACT and generator notes about this host's ports and gen-1 coexistence.
- **0d review: BLOCK, narrow.** The export design conforms. Remaining: host-specific deployment notes, four untested replacement rules, and one enforcement claim in the docs that overstates the DDL. Full report: research-loops-public/private/reviews/gen2-0d-astra-review-20260926.md.
- **Landed:** 0d-repair (4 commits, 5ab7248..a4c1c06). Host-specific deployment material removed and locators made portable. Six isolated negatives added; Astra's four survivors are now killed. The extension-admission claim is corrected (it is a schema rule, with router validation as a Phase 1/3 obligation). Orchestrator ran `make gen2-check` independently: exit 0, 356 tests, 680/680 mutants, 57 valid + 171 invalid fixtures.
- **0d ACCEPTED 2026-09-26** (2 review rounds). **PHASE 0 FULLY ACCEPTED (0a, 0b, 0c, 0d).** Full report: research-loops-public/private/reviews/gen2-0d-repair-astra-review-20260926.md.
- **PHASE 1 OPENED 2026-09-27 by the operator.** C-13 is ratified, and the operator's name is replaced with "user" throughout the build.
- **Phase 1 plan** (scope: design review §Phase 1 row plus the INVARIANTS §13 / store README Phase-1 deferrals). One coder at a time; Astra gates each task.
  - **1a**: `accepted_support` requires contract-admitted production, enforced everywhere. [**ACCEPTED 2026-09-27**, first round]
  - **1b** [**ACCEPTED 2026-09-27**, 3 review rounds]: Router core. A command service with a sole writer (claim / record_observation / commit_outcome / apply_operator_decision / ack_delivery), lease and generation fencing, and receipts that are idempotent by operation ID. Checks at the boundary: schema validation, recomputing hashes to confirm they are true, timestamps, the A10 semantic comparisons due in Phase 1, and export-manifest validation plus extension admission before a manifest enters the outbox.
  - **1c** [**ACCEPTED 2026-09-28**, 5 review rounds]: Supervisor, fake executors, and a protected artifact/result spool. Run the research, discovery, delegate, verifier and checkpoint envelopes through one lifecycle, and prove the crash, replay, cancel and stale-result cases.
  - **1d** [**ACCEPTED 2026-09-28**, 3 review rounds]: Registries and config. Question registry loading, pinning and restart retention. Fake qualification and revocation records exercise the authority fences. A config-bundle registry, plus reservations and signal-queue budget and cooldown. Intake confirmation/amendment fencing, and owner reassignment and deadline extension. G-1 amendment impact and stale-work handling (carried from the 1a review). Minimal router-owned brief/amendment version commands (Astra's 1b bootstrap ruling).
  - **1e** [**ACCEPTED 2026-09-28**, 5 review rounds, conditional only on 1f]: auth service, HTTP+MCP+CLI, status, health; 2 self-found bugs fixed). Orchestrator's independent check: exit 0, 1,291 tests, 1377/1377 mutants (1,363 paired), production 7,718/10,000. first review BLOCK: 8 findings; 1e-repair LANDED 49ddd1c..cf0c88a (recover_incident, redaction, MCP strictness, attribution, CLI exit classes, test fixes; orchestrator's independent check: exit 0, 1,340 tests, 1419/1419 mutants). re-review BLOCK narrow (recovery falsely replayed after crash — the killed session's lead confirmed; MCP serialization credential escape; startup stdout gap); 1e-repair-2 LANDED cc6bff7..0d5bb3c (unfinished-recovery resumption, redaction forms, startup-log coverage; orchestrator's independent check: exit 0, 1,372 tests, 1436/1436 mutants). re-review: recovery + startup CLOSED; one redaction finding remains (serialized-representation check); 1e-repair-3 LANDED fc3a338+6bc7ce3 (credential check on the written text; whole-value replacement; pre-dispatch ID refusal). Orchestrator's independent check: exit 0, 1,378 tests, 1445/1445 mutants. re-review: all prior cases repaired; one new consistency defect at the decoding cap (accepted ID changed after execution / nested JSON destroyed); 1e-repair-4 LANDED 016dd96+e503242 — the coder proved Astra's one-line fix insufficient (fuzz: 1,805/6,686 accepted IDs still altered) and built the full repair (0/4,881). Orchestrator's independent check: exit 0, 1,385 tests, 1448/1448 mutants. IN ASTRA RE-REVIEW (final 1e round); finding 1 resolved by OPERATOR DECISION 2026-09-28: demonstrate up front — task 1f (compose slice + 4 auth-volume demos, brief docs/gen2/tasks/1f.md) QUEUED behind 1e-repair-2]: The operator command/status surface, as one command service behind the CLI and API, with auth and config persistence.
  - **1f** [**ACCEPTED 2026-09-29** with Phase 1: the operator's §4(d) decision (REVIEW-LOG "OPERATOR DECISIONS at the Phase 1→2 gate") amended §4(d) so the offline scope satisfies it, and the revoked or undeclared-expiry residual (d2b) is task 2e1's binding requirement (`DEBT-REGISTER.md`, DEBT-004). Earlier status, kept for history: TECHNICALLY COMPLETE 2026-09-29, 2 review rounds; only the operator's §4(d) disposition remained]: compose slice + capability probe + demos. (a)(b)(c)(d1) PASS as worded, independently rerun by the orchestrator (exit 0); (d2) expired/revoked is offline-undetectable — OPERATOR DECISION taken 2026-09-29: narrow (d), with a real-invocation requirement that gates the first live execution (it landed on 2e1, not Phase 3); the options were (AUTH-DEMO.md F1) an online non-billing check / narrow (d) with a real-invocation requirement / both. review BLOCK on evidence repairs (F1 premise corrected by Astra: declared expiry IS readable offline; only revocation/acceptance is not; concurrency oracle rejected; 2 doc claims). 1f-repair LANDED 14a5d4f..7d11b22 (F1 rewritten on the four distinctions; probe reads declared expiry offline → degraded fact + hold; (d2) split d2a PASS / d2b honestly failing; process-level concurrency oracle with failing serial control). Orchestrator's independent check + demo subset both exit 0. IN ASTRA RE-REVIEW (final 1f round). The §4(d) disposition stays with the operator]: minimal compose slice + the four DEPLOYMENT-CONTRACT §4 auth-volume demonstrations (operator decision 2026-09-28: up front, no phasing amendment).
  - **Phase 1→2 operator gate** after all of these are accepted.
- **Queued after 0c:** `accepted_support` generalization (settled by the flow doc, see 2026-09-26 resolutions below).
- **Operator items:** first push to GitHub (activates CI workflow) is the operator's call. Orchestrator model switched Fable→Sonnet mid-build via operator's own /model command (matches CLAUDE.md: orchestration is Sonnet/Fable, never Opus) — coder (Opus 5.5) and reviewer (Astra) assignments unchanged throughout.

### Moved: old "Phase 2 plan" (BUILD-STATE lines 89-161)

#### Phase 2 plan (REVISED 2026-09-29 per Astra's plan audit, gen2-phase2-plan-audit-astra-20260929.md: 10 findings, all folded in)
**Size rules (the user, 2026-09-29):** no hand-written file over 1,500 lines (enforced by `make gen2-check`; generated files exempt by reasoned allowlist); 15,000 total production lines is a growth-review trigger. This replaces the 10,000/12,000 cap, which the orchestrator had copied from the design review's *proposed* allocation without operator approval. The per-task allocations below are now guidance only. The earlier budget alert is withdrawn.

  - **2a** [**ACCEPTED 2026-09-30**, 5 review rounds; production 9,111]: the full router bootstrap chain, `topic → brief → confirmation → pre-contract scoping report → scope approval → unrated draft → rating decision → rated successor → contract approval → admitted research → claim/link → review closure`. Router operations throughout, each with its decision binding. Draft revisioning before any approved contract. Deterministic referential checks: template slots, framework/decision links, coverage matrix, method design. Claim–source link operation. Code-policy signals. **Source-proposal route (F8):** a typed proposal plus an exact-subject approve/reject/defer by the operator, with no registry write and no enablement; correct SOURCE-GOVERNANCE's stale status. Name the commands the operator surface must expose by 2e.
  - **2r** [**ACCEPTED 2026-09-30**, 1 review round; production 9,125/15,000]: enforce the per-file rule and the 15K trigger in `make gen2-check`; split `tools/gen2_mutations.py`, `gen2/store/schema.sql` and `gen2/tests/test_store_ddl.py`, behavior-preserving with equivalence proofs.
  - **2b** [**ACCEPTED 2026-10-03.** Astra (`6fac8e6c`, pinned 28a2e83): PASS on A, B and C, ROOT-CAUSE. Its words: "2b-repair-19 is ACCEPTED and task 2b as a whole is ACCEPTED." The gateway input contract is closed under B and the engine hand-off is closed. No new operator confirmation is needed. Per the 2026-10-02 operator ruling, no Gate D is run on 2b's acceptance: **2q is next**, then Gate D #4, which must pass before 2c. History: 2b-repair-19 LANDED 2026-10-03 (`28a2e83`, Sonnet 5.5 `f06b02fb`): the port is validated by its integer value (1–65535) on a digit run of at most 32 characters, and H-6 states the cap. The coder reports both targets exit 0, with 1,823/1,823 mutants killed. **Astra re-review DISPATCHED** (`6fac8e6c`); orchestrator reruns in progress. Astra on 18 (`f8ba3f2f`): BLOCK A only, PASS B and C. R17-1 is ROOT-CAUSE (the owner is the only connection source; no urllib/http.client/ssl override found); the 17 acceptances stand. Open: **R18-1 MEDIUM**, the port regex `[0-9]{1,5}` refuses valid zero-padded ports (`:000080`), contract drift against H-6. Orchestrator reruns of 18 match (gen2-check exit 0, 1,760 tests, 1,822/1,822; gen2-gateway exit 0, 1,500+1,500). **2b-repair-18 LANDED 2026-10-03** (`a831511`..`0d34df8`): a strict `_origin` parser runs at construction, and the connection target comes only from the owner's admitted addresses. The coder reports gen2-check 1,760 tests, 1,822/1,822 mutants; gen2-gateway 1,500+1,500 tests, 377 mutants. **Astra re-review DISPATCHED** (`f8ba3f2f`, pinned 0d34df8); orchestrator reruns in progress. Previously: 2b-repair-18 dispatched (Sonnet 5.5 `e249eca5`; brief docs/gen2/tasks/2b-repair-18.md). Orchestrator reruns of 17 match (gen2-check exit 0, 1,752 tests, 1,811/1,811; gen2-gateway exit 0, 1,500+1,500). Astra on 17 (`5df3cb04`): BLOCK A/C, PASS B. Ownership race and ambient routes are structurally removed; the gateway contract is still closed. Open: **R17-1 HIGH**: urllib unquotes `127.0.0.%31` to a literal and `_connect` tries `_literal` before the owner's mapping, so a withdrawn endpoint still connects and sends the token. Fix: one canonical origin validated at construction; the owner is the only source of a connection target. This is the first BLOCK since Gate D #3. **2b-repair-17 LANDED 2026-10-03** (`46edc5e`..`4c360d0`, Sonnet 5.5 `9c21fece`): one `_Endpoint` owner (origin, addresses, operation lease); serial instance (`ClientBusy` before I/O); direct HTTP/HTTPS only (4 handlers, no proxies, no redirects); concurrency across instances proven (N up to 64 in flight). Coder reports gen2-check 1,752 tests, 1,811/1,811; gen2-gateway 1,500+1,500, 377. **Astra review DISPATCHED** (`5df3cb04`, pinned 4c360d0); orchestrator reruns in progress. Earlier: 2b-repair-17 DISPATCHED 2026-10-03 (brief docs/gen2/tasks/2b-repair-17.md: Gate D #3 checklist 0–7). **Operator ruling 2026-10-03:** a `GatewayClient` instance is serial (overlap on the same instance is refused before I/O); separate instances (one per station or job) must run fully concurrently, proven by test ("as long as concurrent connections can run"). Ambient proxies are ignored per DEPLOYMENT-CONTRACT. Gate D #3 (`e5989aa9`): BLOCK, converging; endpoint authority is not yet one enforced fact; finite route inventory and checklist given. Earlier: **HELD FOR GATE D #3** (fresh session `e5989aa9`, pinned 6b44bb2, focused on the engine hand-off's finish line). This is the third consecutive BLOCK since Gate D #2. Astra on 16 (`c8dd6ba4`): BLOCK A/C, PASS B. The sequential R15-1 fix and R15-2 are ROOT-CAUSE. Open: R16-1 HIGH, an exchange already in progress keeps its iterator over the withdrawn addresses (connects, sends the token, accepts an empty/exhausted answer); R16-2 HIGH, urllib's ambient `ProxyHandler` (`http_proxy`) bypasses a withdrawn origin. The post-2q Gate D is renumbered #4. **2b-repair-16 LANDED 2026-10-02** (`a22496a`, `6b44bb2`, Sonnet 5.5 `40675310`): `_withdraw` changes the addresses and the stale flag together, so a stale endpoint has no addresses (no connection, no token) until the owner's `resolve()` succeeds; constructor control re-paired. The coder reports both targets exit 0; orchestrator reruns match (gen2-check exit 0, 1,719 tests, 1,789/1,789; gen2-gateway exit 0, 1,500+1,500). **Astra re-review DISPATCHED** (`c8dd6ba4`, pinned 6b44bb2). Brief: docs/gen2/tasks/2b-repair-16.md. Astra on 15 (`7efecde2`): BLOCK A/C, PASS B. **Gateway input contract: ROOT-CAUSE, CLOSED under B.** Engine: F1/F3/F4 closed; F2 exchange-time resolution ROOT-CAUSE. Open: **R15-1 HIGH**, a failed re-resolution leaves the stale address usable, so an unrelated listener receives the bearer token and supplies a `searched_empty/complete/exhausted` observation; R15-2 LOW, one vacuous constructor-mutant control. The DNS time residual is already ruled (a). Note: this is the second consecutive BLOCK since Gate D #2; a third triggers Gate D. **2b-repair-15 LANDED 2026-10-02** (`a5e3cd2..0d53bfc`, Sonnet 5.5 `af1bd4de`): the transport parses chunked framing itself; no exchange resolves names; bounded readiness through end of line; F4 claims fixed. Both targets exit 0 (coder). Orchestrator reruns match (gen2-check exit 0, 1,717 tests, 1,788/1,788; gen2-gateway exit 0, 1,500+1,500). **Astra re-review DISPATCHED** (`7efecde2`, pinned 0d53bfc). **F2 residual RULED (operator 2026-10-02, option a):** the client is constructed only inside supervised job children, so the job deadline bounds the lookup; 2e1 owns and verifies this. Previously: F2 residual awaited an operator ruling: the lookup at client construction / `resolve()` is unbounded (options a–d in private/evidence/2b-repair-15/f2-residual.md). Brief: docs/gen2/tasks/2b-repair-15.md. Final review (Astra `ef030fc5`, pinned c0d963d): BLOCK A/C, PASS B. Everything else in 13d and 14 was ruled ROOT-CAUSE. Open: F1 HIGH, chunked framing (http.client's permissive decoder: `+0`/`0x0`/signed sizes, unchecked CRLF, EOF in place of the trailer end) still yields a successful 0 or short load; F2 DNS `getaddrinfo` outside the deadline; F3 readiness helper's unbounded `readline`; F4 8 test claims + 1 contract test. BIS api/v2 is documented as SDMX 2.1 for data, so the 2.1-only decoding is ROOT-CAUSE. Final review dispatched against c0d963d, covering 13d + 14. **2b-repair-14 LANDED 2026-10-02** (`071eb9a`..`373c3dc`, Sonnet 5.5 `39fc2492`): Gate D #2 checklist items 0–6, 8 and F6. The coder reports gen2-gateway 1,491+1,491 tests and 366/366 mutants, gen2-check 1,700 tests and 1,781/1,781. The orchestrator corrected two stale trust-model comments in engine files, comment-only (`c0d963d`). Orchestrator reruns at c0d963d match (gen2-check exit 0, 1,700 tests, 1,781/1,781; gen2-gateway exit 0, 1,491+1,491). Open question for the review: SDMX-ML 2.1-only versus BIS `api/v2` (version of the default response not confirmed). **2b-repair-13d LANDED 2026-10-02** (`34ed64b`..`fd414d4`, Sonnet 5.5 `63cce017`): one absolute deadline arms every blocking socket call and late replies are discarded; the admission contract is enforced in router and DDL; the startup failure is diagnosed (SQLite busy_timeout doesn't cover the rollback→WAL switch) and fixed. Disclosed: DNS resolution can overrun the deadline (late replies still refused); the retrieval audit is unbuilt (2e2). Orchestrator reruns match (gen2-check exit 0, 1,700 tests, 1,781/1,781; gen2-gateway exit 0, 1,398+1,398). **2b-repair-14 DISPATCHED** (Sonnet 5.5 `39fc2492`). **Review plan (Codex at 90% of its 7-day window):** one combined Astra review of 13d + 14 once 14 lands. **OPERATOR RULINGS 2026-10-02: trust model B adopted; supported-format/resource policy and sanctioned predicates confirmed.** Queue: 13d (engine, in flight) → **2b-repair-14** (gateway, brief docs/gen2/tasks/2b-repair-14.md: Gate D #2 checklist items 0–6 and 8). Earlier: **Gate D #2 BLOCK, with a finite finish line** (report `private/reviews/gen2-gate-d-2-astra-review.md`). Gate D recommends trust model **B**: trusted, reviewed first-party adapters under a complete contract for supported provider input, with guards and review rather than by-construction Python confinement. Adopting it is an operator amendment. Item 5 (the supported-format/resource policy and sanctioned predicates) also needs operator confirmation. The next gateway repair (2b-repair-14) is held for these rulings and then implements checklist items 0–6 and 8 in one pass; 13d (engine, in flight) is item 7. Gate D #2 dispatch: `8d74ce90`, fresh session, pinned 2c400a8. This is the third consecutive BLOCK since Gate D #1 (13a, 13b, 13c), so no gateway repair is dispatched until it reports; 13d (engine, already in flight) continues. Astra on 13c (`f3e1f1c2`): BLOCK A/C, PASS B; family MITIGATION. ROOT-CAUSE: the R13A-1 lexical cases and the R13A-2 direct copy. Open: R13C-1 Content-Length truncation becomes a successful short/empty load; R13C-2 public constructor compositions (make_record sealing adapter literals with decoder authority; a Rec passed as typed identifiers) let provenance decide selection; R13C-3 XML child text is silently dropped and foreign namespaces are accepted as SDMX; R13C-4 snapshot whole-file abort regresses the accepted per-line isolation; R13C-5 Retry-After date tolerance contradicts its claim. Gate C: 9 overclaims and 2 rejected contract changes. 2b-repair-13c LANDED 2026-10-02 (`dd61431`..`37a655c`, Sonnet 5.5 `6dcd87e1`): strict openers in core/wire.py (JSON/XML/CSV/Retry-After) with an executable inventory of parse calls; opaque provenance through make_record, materialized at router/index/cache storage; 10 test claims rewritten. **Astra re-review DISPATCHED** (`f3e1f1c2`, pinned 37a655c). Orchestrator reruns match (gen2-check exit 0, 1,641 tests, 1,739/1,739; gen2-gateway exit 0, 1,398+1,398). **2b-repair-13d DISPATCHED** (Sonnet 5.5 `63cce017`). **Queue: → 13d (engine; brief docs/gen2/tasks/2b-repair-13d.md).** Astra on 13b (`5539a8d8`): BLOCK A/C, PASS B. ROOT-CAUSE: Gate D #3 info-loss, supervisor test, linkage inert. Open: R13B-1 deadline is per-socket-op, so a late `done` persists as searched_empty/complete/exhausted; R13B-2 admission contract (complete/exhausted with null gateway_call_ref admitted, request type optional, cursor domain differs router vs DDL, `exhausted` sentinel accepted as cursor, first-write relabel by trusted code); R13B-3 recorder-startup failure unexplained. 2b-repair-13b LANDED 2026-10-02 (`1178e97`..`a5a2afb`, Sonnet 5.5 `d6988b45`): typed `page_outcome` + typed `continuation` through client→observe→router command→store, absolute poll deadline, deterministic supervisor test. **Astra re-review DISPATCHED** (`5539a8d8`, pinned a5a2afb). Orchestrator reruns match (gen2-check exit 0, 1,641 tests, 1,739/1,739; gen2-gateway exit 0, 1,334+1,334). **2b-repair-13c DISPATCHED** (Sonnet 5.5 `6dcd87e1`). **Order: 13b (engine) → 13c (gateway: strict byte openers + sealed provenance through make_record; brief docs/gen2/tasks/2b-repair-13c.md).** Astra on 13a (`180914e7`): BLOCK A/C, PASS B. The family is still MITIGATION but narrowed. R12-1..5, Gate D #1 and Gate D #2 each ROOT-CAUSE at their sites. Open: R13A-1 malformed CSV framing → successful zero-journal load (inherited); R13A-2 make_record's plain copy lets passive provenance decide selection (reviewer source mutant, not shipped). Python-level residuals (`is None` on Passive, private names, finite corpus) need an operator ruling. 2b-repair-13a LANDED 2026-10-02 (`42a155d`..`2d62753`; Sonnet 5.5 `c8ceb127`) (gateway: decoder contract; brief docs/gen2/tasks/2b-repair-13a.md), then **2b-repair-13b** (engine: typed page outcome, poll deadline, deterministic supervisor test). Astra on repair-12: BLOCK, family MITIGATION/incomplete (R12-1..5). **Gate D #1: BLOCK.** HIGH: decoder failure boundary not total; fuzzy dedup merges distinct identities (violates E-3); the engine drops pagination/exhaustion at the durable handoff. MEDIUM: poll deadline excludes network time; import-only checks hide Router mixin coupling (→2q). LOW: stale locators (→2q). Gate D: don't build accounting/stopping on the current 2b handoff. Earlier: 2b-repair-12 LANDED 2026-10-02 (Sonnet 5.5 coder ee76b68e, 278ab7e..a06ea5e): ROOT-FIX redesign, schema-first provider decoding (core/schema.py, one decoder, schema-derived harness corruption), with the old view/helper/scan mechanisms removed. R11 probes 24→0 failures; oracle unedited and passing; old-vs-new differential over 67,021+6,666 corruptions, 3 unintended changes fixed, 120 deliberate. IN ASTRA RE-REVIEW (family-level classification) **and Gate D #1 (whole-system) running in parallel**, per the charter's third-consecutive-BLOCK rule. Earlier: **2b-repair-12 DISPATCHED 2026-10-02** (operator: "why don't we try to address the bugs"; brief docs/gen2/tasks/2b-repair-12.md). Was HELD FOR OPERATOR: Astra `gen2-2b-repair-11-astra-review-20261001.md` BLOCK on R11-1 (nested fallback contents decoded after selection: Unpaywall, ECB, Crossref loader) and R11-2 (contradictory SDMX structure references resolve to the first). Neither produces a false end, false empty or permission widening. Operator asked to choose: fix these two then freeze a finite acceptance contract, accept them as debt and close 2b, or continue as-is. Earlier: 2b-repair-11 IN ASTRA RE-REVIEW 2026-10-01 (agent 44e80983; brief `gen2-2b-repair-11-review-task-20261001.md`). 11b LANDED (coder 05f61d77, 33e2c2d/c1b9351; all 68 oracle cases pass, oracle untouched); orchestrator verify GREEN (gen2-check exit 0, 1,615 tests, 1,701/1,701; gen2-gateway exit 0, 1,206+1,206 tests, 257/257). Earlier: **2b-repair-11b DISPATCHED 2026-10-01** (11a LANDED caf4b13/99e3f2c: 68 new failing oracle cases) (brief docs/gen2/tasks/2b-repair-11.md): 11a oracle additions by the independent author (fb7bc4cf), then an 11b fix coder. Astra `gen2-2b-repair-10-astra-review-20261001.md` BLOCK on R10-1 (a valid preferred field short-circuits validation of a malformed fallback), R10-2 (the BIS/ECB browse binds to flows[0], fabricating a template for non-first or absent flows), R10-3 (the BIS fabrication mutant survives harness and oracle). Accepted as ROOT-CAUSE: R9-1 grammar, R9-3 import closure, typed sites, publisher, per-structure reader, execution accounting, and the oracle (qualified independence). Earlier: 2b-repair-10b LANDED 2026-10-01, Sonnet 5.5 coder be3b8d97, 5 commits 5ac065c..04166da: all 191 oracle cases pass, none disputed, oracle byte-identical since 650ac23. New `core/uri.py` (RFC 3986 Appendix A); typed reading before fallbacks at 190 scanned sites; import closure through module attributes; per-flow structure browse; publisher mapped; openml.fetch harness generator corrected. Orchestrator verify GREEN (gen2-check exit 0, 1,615 tests, 1,701/1,701 mutants; gen2-gateway exit 0, 1,156+1,156 tests, 218/218 mutants). IN ASTRA RE-REVIEW, brief `gen2-2b-repair-10-review-task-20261001.md`. Earlier: **2b-repair-10b DISPATCHED 2026-10-01** (Sonnet 5.5 coder; brief docs/gen2/tasks/2b-repair-10b.md): make the gateway pass the independent oracle (191 failing cases) without editing it. 10a LANDED: oracle author fb7bc4cf, commits e4b7eac, 206afe4, 650ac23; vectors verified against fetched RFC 3986/8288/9110 text. Earlier: **2b-repair-10a DISPATCHED 2026-10-01** (Sonnet 5.5, oracle author; brief docs/gen2/tasks/2b-repair-10a.md), then 2b-repair-10b (coder). Astra `gen2-2b-repair-9-astra-review-20261001.md` BLOCK: R9-1 malformed URI relations still mean known absence; R9-2 OpenML licence truthiness fallback; R9-3 package-module import bypass; R9-4 part of the harness oracle derived from the implementation; R9-5 coverage credits unexecuted BIS catalogue. Root cause of R9-1/R9-4: shared authorship of code and oracle, so oracle authorship is split from implementation. Earlier: 2b-repair-9 LANDED 2026-10-01, Sonnet 5.5 coder fac04fcb, 7 commits 47357b0..cb3caae: R8-1..R8-3 fixed, plus a generative invariant harness over every adapter (fails 117/261 tests, 3,401 violations, on the unfixed tree; passes after). The harness found a whole-request crash in 21 operations, ~1,800 silent wrong-kind reads, false end signals from bad totals/cursors, and fabricated identities, all fixed. Orchestrator verify GREEN (gen2-check exit 0, 1,615 tests, 1,701/1,701 mutants; gen2-gateway exit 0, 836+836 tests, 188/188 mutants). IN ASTRA RE-REVIEW, brief `gen2-2b-repair-9-review-task-20261001.md`. Earlier: **2b-repair-9 DISPATCHED 2026-10-01** (Sonnet 5.5), brief docs/gen2/tasks/2b-repair-9.md: Astra `gen2-2b-repair-8-astra-review-20261001.md` BLOCK. The structural view redesign and all 68 escape uses are ROOT-CAUSE; remaining are R8-1 (invalid rel values read as known absence), R8-2 (falsy wrong-type holders read as empty), R8-3 (star import / re-exported parser bypass the inventory). Fourth round of the malformed-input-as-definite-answer family, so the brief adds a generative invariant harness across all adapters. Earlier: 2b-repair-8 LANDED 2026-10-01, Sonnet 5.5 coder 130b5b23, 4 commits eef2f1a..e19064c: RFC 8288 Link reader with known/unknown (an unparseable header is never an end); provider payloads are views (`core/payload.py`) where lists can't be iterated, only decoded per member; escape hatches allow-listed with reasons. Orchestrator verify GREEN (gen2-check exit 0, 1,615 tests, 1,701/1,701 mutants; gen2-gateway exit 0, 525+525 tests, 164/164 mutants). IN ASTRA RE-REVIEW, brief `gen2-2b-repair-8-review-task-20261001.md`. Earlier: **2b-repair-8 DISPATCHED 2026-10-01** (Sonnet 5.5), brief docs/gen2/tasks/2b-repair-8.md: Astra `gen2-2b-repair-7-astra-review-20261001.md` BLOCK. F3-R1, the provider evidence and the individual decoder conversions are ROOT-CAUSE; R7-1 (Link parser loses quoted-comma relations, so a parse failure becomes exhaustion) and R7-2 (one-decoder property not enforced: HF siblings, ECB datasets, OpenCitations metadata; name-scan check bypassable) remain. Third round of the malformed-member family, so a structural redesign is required. Three owner decisions with the operator (OpenAIRE deprecation, Kaggle endpoint drift, catalogue partial results). Earlier: 2b-repair-7b LANDED 2026-10-01, Sonnet 5.5 coder e6c24611, 6 commits 12d7df0..4e1ea4c: provider evidence restored durably (45 captures, 48 excerpts verified); one-decoder chokepoint `base.members()`/`first_member()` with a bypass test, 9 whole-answer-loss paths fixed incl. OpenCitations. Three unowned items for Astra to classify and the operator to assign (OpenAIRE deprecated endpoint, Kaggle listing endpoint drift, catalogue answers lost whole on one bad entry). Orchestrator verify GREEN (gen2-check exit 0, 1,615 tests, 1,701/1,701 mutants; gen2-gateway exit 0, 483+483 tests, 143/143 mutants). IN ASTRA RE-REVIEW, brief `gen2-2b-repair-7-review-task-20261001.md`. Earlier: **2b-repair-7b DISPATCHED 2026-10-01** (Sonnet 5.5), brief docs/gen2/tasks/2b-repair-7b.md: finishes 2b-repair-7 after a host reboot (operator doubled the disk) closed the Opus coder's session and wiped /tmp evidence. 7 commits ef39cd6..cadd62e already in. Adds the OpenCitations malformed-member defect, fixed at the shared member-decoding chokepoint (second adapter with the same defect). The reboot restarted the live gen-1 gateway (new PID 1040, start 2026-10-01 04:26:25 UTC); code unchanged at f4a7a5c, clean. Not caused by the build. Earlier: **2b-repair-7 DISPATCHED 2026-10-01**, brief docs/gen2/tasks/2b-repair-7.md: Astra `gen2-2b-repair-6-astra-review-20261001.md` BLOCK. F3's shared router decision is ROOT-CAUSE, but F3-R1 (local offsets skip rows when the index changes, still reported exhausted) and F3-R2 (Hugging Face ignores its next-link protocol) remain, and most adapters' end rules lack primary provider evidence. A pre-existing Socrata malformed-member defect is folded in. Earlier: 2b-repair-6 LANDED 2026-10-01, coder 31e6d85f, 3 commits (9f8e006, 02f3723, d498d85): exhaustion only on an adapter's own end report; all 13 find adapters under the rule; Crossref page-1 false exhaustion also fixed. Orchestrator verify GREEN (gen2-check exit 0, 1,615 tests, 1,701/1,701 mutants; gen2-gateway exit 0, 425+425 tests, 102/102 mutants). IN ASTRA RE-REVIEW, brief `gen2-2b-repair-6-review-task-20261001.md`. Earlier: **2b-repair-6 DISPATCHED 2026-10-01**, brief docs/gen2/tasks/2b-repair-6.md: Astra `gen2-2b-repair-5-astra-review-20260930.md` accepted F1 and F2 as ROOT-CAUSE; one blocker remains, F3, local-index false exhaustion (truncated results marked exhausted on all four doors, so the engine client stops after one page). Earlier: **2b-repair-5 DISPATCHED 2026-09-30**, brief docs/gen2/tasks/2b-repair-5.md: Astra `gen2-2b-repair-4-astra-review-20260930.md` BLOCK. F1 and F2 are each partly ROOT-CAUSE, but each rule sits on one path (F1: ordinary successor edges can install an older revision as current; F2: the local-index reader serves unconverted rows after startup, widening permissions through all four doors). Redesign rule applied: enforce at the single chokepoint. Three Phase 4 release decisions sent to the operator. Earlier: 2b-repair-4 LANDED 2026-09-30, coder a94bac98, 2 commits (bd13e76 F2 migration + deleted read-time rebuild; 9621690 F1 exact late-snapshot DDL relation). Coder found the live gen-1 writer's (f4a7a5c) rows were being widened by the pre-fix reader; migration now covers them. Remaining items proposed for Phase 3/4, pending Astra classification and operator confirmation. Orchestrator verify GREEN (gen2-check exit 0, 1,610 tests, 1,692/1,692 mutants; gen2-gateway exit 0, 401+401 tests, 92/92 mutants; gen-1 boundary unchanged). IN ASTRA RE-REVIEW, brief `gen2-2b-repair-4-review-task-20260930.md`. Earlier: **2b-repair-4 DISPATCHED 2026-09-30** — operator ruled both mitigations get a proper fix (no debt accepted); brief docs/gen2/tasks/2b-repair-4.md. Was: BLOCK — AWAITING OPERATOR: Astra `gen2-2b-repair-3-astra-review-20260930.md` classes 2 corrections as MITIGATION (F1: relaxed A9 DDL rule enforces graph shape but not episode/revision meaning; F2: R1 legacy rows reinterpreted at read time with no migration or removal condition). Only the operator can accept a mitigation; repair recommended. R2 fixed within one gateway lifetime; cross-lifetime revision ordering assigned to Phase 3. Prior: 2b-repair-3 LANDED 2026-09-30, coder ddfb039d, 2 commits (22f9375, ee71260): gateway revision orders an outage's snapshots; relaxes 0a's A9 store rule (late snapshot may sit behind the current one). Orchestrator independent verify GREEN (exit 0, 1,609 tests, 1,687/1,687 engine mutants; gateway exit 0, 395 tests, 82/82 mutants; gen-1 boundary unchanged). IN ASTRA RE-REVIEW, brief `gen2-2b-repair-3-review-task-20260930.md`, including the new root-cause/mitigation classification across all four 2b rounds. Prior: **BLOCK, narrower still, 2026-09-30**, Astra re-review `gen2-2b-repair-2-astra-review-20260930.md`: **R1 CLOSED** (conservative tradeoff ruled acceptable); **R2's current-snapshot staleness is a real persistent defect**, not the disclosed brief residual — 2 independent reproductions (reordering race, sequential recurrence). Live gen-1 gateway boundary re-confirmed untouched a fifth time. 2b-repair-3 dispatched, brief docs/gen2/tasks/2b-repair-3.md, covers only R2's remaining current-status bug. History: 2b-repair-2 (coder 8f0c3df4, 3 commits) → 2b-repair (coder fa1a0b3b, 9 commits) → original 2b (coder 286eff36, 13 commits, brief docs/gen2/tasks/2b.md) — first task touching `gateway/` code; branch gen2 only]: gateway observation and policy-boundary repair (F2). Invocation+attempt identity through both API doors, queued jobs, lane calls and receipts. Complete effective request identity, durable acknowledged capture, explicit telemetry loss. Response-shape validation at adapter boundaries, with partial candidate identities kept as lower bounds. Authenticated **server-side** station/topic policy on every door. Licence, freshness and provenance preserved end to end, with the four permissions kept distinct. All eight DEPLOYMENT-CONTRACT §3.4 fixtures. Plus the engine `gateway_client`. Breaker, shared budget and SIGTERM stay Phase 3.
  - **2q** [**TASK 2q CLOSED 2026-10-09:** 2q-a and every 2q-b slice are accepted, and every 2q-owned debt entry is closed. **GATE D #5 PASS 2026-10-09** (fresh Astra `c4ecca2b`; no blocking checklist; F1 is DEBT-030 (2c) and F2 is DEBT-031 (phase 2)). **2c may start.** **2q-a CLOSED 2026-10-06 by operator acceptance at the round cap** ("Close and move on"). R7-1 and R7-2 are DEBT-018, an accepted mitigation owned by task 2q. **2q-b slice plan:**
    - b1: the gateway component cycle. **LANDED** (`7246e4d`, `aa49b06`): the cycle is gone, component propagation 49→43, 0 differences over 223,582 runs. **ACCEPTED 2026-10-06** (Astra `7f06aa53`: PASS on A, B and C, ROOT-CAUSE; non-blocking NB-1 to NB-3 are DEBT-019). Landing run at aa49b06: gen2-check exit 0 (2,310 tests, 2,302/2,302); gen2-gateway exit 0 (1,518+1,518).
    - b2: the Router collaborator pattern on Status and Capabilities. **LANDED** (`bb0f7bc`, `193ee7b`): self-calls 132→109; 0 differences over 1,010 replayed tests. **ACCEPTED 2026-10-06** (Astra `22aaf34e`: PASS on A, B and C, ROOT-CAUSE; the pattern is sound, the local protocols are legitimate interface segregation, and the visibility claim is scoped to protocol declarations; non-blocking items are DEBT-020). Landing run at 193ee7b: gen2-check exit 0 (2,315 tests, 2,308/2,308); gen2-gateway exit 0 (1,518+1,518). Next: b3 = Registries plus a field-aware differential (DEBT-020 item 2), then b4 Lifecycle, b5 Scheduling, b6 Amendments, queued behind the running 2q-t1 coder (one coder at a time).
    - **CI:** gen2 is pushed (`f1ee0a0`), and Jenkins passed it (2,315 tests, 2,308/2,308, 45 min of the 50-min limit). The first CI run caught an unmarked locator in DEBT-019, now fixed. Branch `ci/gen2-jenkinsfile-v2` (image :2, clean workspace, identity) fails because `ci-py312-noble:2` isn't built on cir yet. The gateway suite needs a hash-locked psycopg install and the worker-budget fix before it fits in CI.
    - The 2q tooling slice **2q-t1** (DEBT-016, DEBT-017, DEBT-018) **LANDED** (`32489d9`): the `builtins` module is banned; exceptions are pinned by whole-function fingerprint; the DEBT-016 and DEBT-017 items are fixed or documented; net 324 lines. **ACCEPTED 2026-10-06** (Astra `07183765`: PASS on A, B and C, ROOT-CAUSE); **DEBT-016, DEBT-017 and DEBT-018 CLOSED**; DEBT-021 is a doc nit. Landing run at 32489d9: gen2-check exit 0 (2,326 tests, 2,319/2,319); gen2-gateway exit 0 (1,518+1,518).
    - **2q-b3 LANDED** (`6c4302b`, `8e73b42`): the Registries collaborator; self-calls 109→89 and pairs 13→8; a field-aware differential with 0 differences and its negative control detected. Two deviations go to Astra: two writes keep their own transaction via `_transaction()` instead of `_guarded`, and three per-pair budgets rise. **Astra:** PASS on A and B, **BLOCK on C** (`432cc7c7`). The conversion is sound and both deviations are accepted, but the differential is lossy (C1) and unstable baselines pass silently (C2). Researched fix: **2q-b3b** (an exact deterministic replay plus mechanical-move AST equivalence), queued behind the 2q-b5 coder. Landing run at 8e73b42: gen2-check exit 0 (2,327 tests, 2,322/2,322); gen2-gateway exit 0 (1,518+1,518).
    - **2q-b4 LANDED** (`23a43c3`, `8a59308`): `_decode` 64/105 → 5/4 as one decoder per kind; 0 differences over 242,967 runs; 5 of 5 negative controls detected. **ACCEPTED 2026-10-07** (Astra `ea8e980f`: PASS on A, B and C, ROOT-CAUSE; non-blocking items are DEBT-022). Landing run at 8a59308: gen2-check exit 0 (2,327 tests, 2,322/2,322); gen2-gateway exit 0 (1,530+1,530).
    - **2q-b5 LANDED** (`cc0c84a`, `f33c18f`): `base.py` is split into `_response.py`, `_transport.py` and `_links.py`; `parse_links` 22/57 → 7/9; propagation 11.83% → 11.72%. But reach pairs, edges and fan-outs rose and a new unstable-dependency smell appeared, all admitted. 0 differences over 4.2M runs; 14 of 14 negative controls detected. **Astra:** PASS on A and B, **BLOCK on C** (`f7609fc9`). The production split is ROOT-CAUSE and its costs are accepted; the evidence fails (C1 lossy drivers, C2 empty corpus passes, C3 two controls). Researched fix: **2q-e1 LANDED** (`4031259`, `f1868f3`): a shared exact, manifest-complete, fail-closed differential core; 9 drivers ported; C3 controls repaired; 2q-b5, 2q-b4 and 2q-b1 re-certify EQUIVALENT. **Astra (`720d74ce`): Gate C BLOCK**, the second on this evidence family. C3 is resolved; C1 (spelling-based port substitution) and C2 (zero drivers, partial-generator inventory, erased envelopes) remain. **2q-e2 LANDED** (`15bac9a`; structural `LoopbackURL`; the inventory comes first; 2q-b5, 2q-b4 and 2q-b1 re-certify EQUIVALENT). **Astra re-review DISPATCHED** (`ab6b6af6`); the landing run is serialised after 2q-b9's. **2q-t3 LANDED** (`a3d1b34`..`8f8e8d2`: the DEBT-024 prose; the DEBT-025 harness serial-restore fix plus docstring; DEBT-023 items 2–3, ordering fixtures and the readable/marker split; DEBT-020 items 1 and 3 confirmed). **Astra review DISPATCHED**; the landing run is serialised after 2q-e2's. (structural URL port handling; inventory from validated inputs). A third BLOCK goes to the operator. Landing run at f1868f3: gen2-check exit 0 (2,356 tests, 2,322/2,322); gen2-gateway exit 0 (1,540+1,540). Landing run at f33c18f: gen2-check exit 0 (2,327 tests, 2,322/2,322); gen2-gateway exit 0 (1,533+1,533).
    - **2q-b6 LANDED** (`09a221c`, `de55340`, `8bc87cc`): the Lifecycle collaborator. Move equivalence: 13 of 13 identical, every one of the 29 added functions given a disposition. Replay UNRESOLVED (658 same / 0 different / 352 unresolved, the known list); 5 of 5 negative controls detected; targeted evidence for the low-coverage routes. **ACCEPTED 2026-10-07** (Astra `b8b0bc6a`: PASS on A, B and C, ROOT-CAUSE; all 5 rulings conform; non-blocking items are DEBT-025). Landing run at 8bc87cc: gen2-check exit 0 (2,361 tests, 2,328/2,328); gen2-gateway exit 0 (1,540+1,540).
    - **2q-b7 LANDED** (`02d9fdc`, `b4c6825`, `528c58e`): the Scheduling collaborator; 14 of 14 bodies AST-identical; replay UNRESOLVED (658/0/352, the known list); wiring tests for 8 delegates and 5 write routes. **ACCEPTED 2026-10-07** (Astra `d85ec3e7`: PASS on A, B and C, ROOT-CAUSE; the non-blocking items are already DEBT-025 NB1, fixed in 2q-t3, and DEBT-023). Landing run at 528c58e: gen2-check exit 0 (2,365 tests, 2,335/2,335); gen2-gateway exit 0 (1,540+1,540).
    - **2q-b8 LANDED** (`1dd411b`, `718b78d`, `8f59e6f`): the Amendments collaborator. **`Router` now inherits no mixins; engine self-call sites went from 132 across 19 pairs to 0.** 20 of 20 bodies AST-identical; replay UNRESOLVED (658/0/352). **Astra (`bbf7d409`): PASS on A and B, BLOCK on C (C1)**, the first BLOCK on 2q-b8. **The landing run at 8f59e6f FAILED gen2-check:** 2 tests whose premise (a mixin-composed production Router) 2q-b8 removed. The gateway run is green. Fix **2q-b8b** (retarget them to a frozen historical fixture) is queued behind the 2q-t4 coder. Later pins (b9, e2, t3) inherit the 2 failures; notes are left in their orchestrator evidence directories.
    - **2026-10-08 operator authorisation:** established tools replace custom proof tools; **2q-b8b LANDED** (`623576e`): the two tests now run on a frozen six-mixin Router fixture (`f216133`); 67 tests OK; 21 of 21 mutants killed. **The combined landing run at 623576e is GREEN:** gen2-check exit 0 (2,419 tests, 2,362/2,362) and gen2-gateway exit 0 (1,540+1,540). **2q-b8 and 2q-b9 ACCEPTED** (Astra `47e85d9b`, re-review under the new standard; the inline-back checker is advisory only; follow-through is DEBT-026); **2q-e2, 2q-e1 and 2q-b5 ACCEPTED** (Astra `095a9dbb`: Gate C PASS, ROOT-CAUSE; the evidence family is closed); **2q-t3 ACCEPTED** (Astra `f1339f58`, landing confirmation): DEBT-020, DEBT-024 and DEBT-025 CLOSED; DEBT-023 items 2–3 done, item 1 open. **2q-b10 DISPATCHED** (the `EvidenceWriter` move, the first slice under the new standard). **Trial 2q-r1 LANDED** (`ac72fe8`): Hypothesis worked; rope and RefactoringMiner partly worked (rope output is untrusted, and the tests caught its fault); time-machine covers the test process only. **Adopted** as the charter's "Refactor evidence standard". **2q-b9b DROPPED**, and 2q-b9 will be re-judged under the new standard. 2q-b9b is held; 2q-t4 is paused at `5ef2130`. The 2q-e2 landing run and review didn't complete (session ended) and will be redone. The 2q-t3 review has no blocking findings, pending a landing record.
    - **2026-10-09:** **2q-b11's landing attempt 3 is GREEN** (2,430 tests; 2,382/2,382), and **2q-b11 ACCEPTED** (Astra `0354cd4e`). **Every planned 2q-b structural item is now accepted.** **2q-t4b LANDED** (`e9d090e`, `5de8d7f`): replay 1,003 / 0 / 7; Astra's 7 requirements are evidenced. **ACCEPTED** (Astra `f1467d28`: PASS on A, B and C; 7 named unresolved scenarios bounded by contract evidence); **DEBT-023 CLOSED**; non-blocking items are DEBT-029 (phase 2). Landing run at f356814: gen2-check exit 0 (2,438 tests; 2,382/2,382); gen2-gateway exit 0. **2q-t5 LANDED** (`96d9541`, Sol `0a8880a8`): the readiness race fixed with a forced-race regression, plus the DEBT-027 and DEBT-026 corrections. **ACCEPTED** (Astra `9cf2cbfe`); DEBT-026, DEBT-027 and DEBT-028 CLOSED.
    - **2q-b10 LANDED** (`ab53b7c`..`93e8338`): the `EvidenceWriter` collaborator, moved by rope then normalised; `service.py` 1,498 → 1,349; the detector reports 5 Move Method + Extract Class + Extract And Move; 78 of 78 mutants. **Replay: 1,004 same / 0 different / 6 unresolved** (346 of the 352 resolved, attributed to 2q-t4's partial `5ef2130`, unconfirmed). **ACCEPTED, with the 2q-r1 tooling also ACCEPTED** (Astra `adbb7b7e`: PASS on A, B and C, ROOT-CAUSE). The 352 → 6 count is validated, but 2q-t4's seam needs its own gate review before DEBT-023 item 1 closes. Non-blocking items are DEBT-027. Landing run at 93e8338: gen2-check exit 0 (2,427 tests, 2,367/2,367); gen2-gateway exit 0 (1,540+1,540).
    - **2q-b11 LANDED** (`50b6061`..`7e59054`): `_commit_in_transaction` 52/60 → 4/3 as nine rope-extracted helpers; two rope faults were removed (one invisible to the tests); detector `Extract Method=9`; 303 + 1,800 tests; 15 new mutants; replay 1,003 / 0 / 7. **Astra (`91e077f9`): PASS on A and B, BLOCK on C on L1 only** (the landing run hit the DEBT-028 readiness flake). The repeated landing run **failed the same readiness test again**; the cause is unknown (see REVIEW-LOG 2026-10-09). **PAUSED by the operator 2026-10-09.**
    - **2q-t4b DISPATCHED:** finish and qualify the replay seams against Astra's 2q-b10 requirements, to close DEBT-023 item 1.
    - **2q-b9 LANDED** (`ad7d4c9`, `fa4e2b2`, `d649d51`): `_write_evidence` 55/96 → 14/14 via 5 verbatim helpers; the inline-back check is AST IDENTICAL; replay 658/0/352. `service.py` is at 1,498 of the 1,500-line cap, so `_commit_in_transaction` needs a structural move first. **Astra (`8a9fd4a0`): PASS on A and B, BLOCK on C** (C1: the inline-back checker grammar; L1: inherited from 2q-b8), the first BLOCK on 2q-b9. Fix **2q-b9b** is queued. Next structure slice: an `EvidenceWriter` collaborator, then `_commit_in_transaction`. Landing run at d649d51: gen2-check exit 2, **failing only the 2 inherited 2q-b8 tests**, and it stopped at gen2-test, so the mutation, trigger-order and size steps **did not run**; gen2-gateway exit 0 (1,540+1,540). A full landing run on the 2q-b8b fix tip will supply the missing steps.
    - **2q-t2 LANDED** (`f6e2e7a`, `be38f15`, `642a0ef`): DEBT-019, DEBT-021 and DEBT-022 addressed. DEBT-022 NB-1 is resolved by a documented extension policy, because the original order was mixed and a swap would change behaviour; that's for Astra to rule on. **ACCEPTED 2026-10-07** (Astra `f4d7e932`: PASS; the extension-policy route for DEBT-022 NB-1 is accepted). **DEBT-019, DEBT-021 and DEBT-022 CLOSED.** Landing run at 642a0ef (restarted after the queue hit the background time limit): gen2-check exit 0 (2,343 tests, 2,322/2,322); gen2-gateway exit 0 (1,538+1,538).
    - **2q-b3b LANDED** (`504372f`): move equivalence (15 of 15 and 11 of 11 bodies identical) plus an exact, fail-closed replay. Per change: 658 the same, 0 different, **352 UNRESOLVED** (the real job-process fingerprint, plus 3 races). **ACCEPTED 2026-10-07: 2q-b3b and 2q-b3 both ACCEPTED** (Astra `c0bd81d1`: Gate C PASS, ROOT-CAUSE; C1, C2, NB1 and NB2 resolved). The evidence is sufficient for pure moves. Rulings for Lifecycle, Scheduling and Amendments: an exhaustive move mapping plus AST identity; exact replay with an unresolved list; `_guarded` preserved; targeted evidence outside replay coverage. Non-blocking items are DEBT-023. Landing run at 504372f: gen2-check exit 0 (2,341 tests, 2,322/2,322); gen2-gateway exit 0 (1,533+1,533).
    - then decompose `_decode`, `adapters/base.py` and the Router hotspots;
    - a 2q tooling slice for DEBT-016, DEBT-017 and DEBT-018;
    - then Gate D #5.

    Earlier: **OPERATOR 2026-10-05 at the round cap: continue on the researched plan** (`docs/gen2/research/2q-a-round-cap-20261005.md`): "make the fixes, review it to make sure it didn't cause any other issues and then we'll move on". SOURCE-CONTRACT v2 (soundy by declaration) is approved, and the pre-repair Gate D is skipped by operator direction; the post-2q Gate D #5 still runs before 2c. **2q-a-repair-6 (slice A) LANDED** (`59b0536`, Sonnet 5.5 `d5339e45`): scope comes from `symtable`; unresolved aliases refuse; three controls reach their changed lines; net 307 hand-written lines; production facts and metrics byte-identical. It closes the two invalid-`nonlocal` items of the repair-5 review. **Astra on slice A** (`471df716`): BLOCK on A and C, MITIGATION. The adapter introduced R6-1 (generator scopes paired with the wrong table) and R6-2 (unmangled private names). **2q-a-repair-6b LANDED** (`a4deb99`, Sonnet 5.5 `1abc6c0f`): compiler-order pairing validated both ways, plus mangling; production byte-identical; 0 mismatches over a corpus of about 6,700 files and 20,383 random programs. **Astra on 6b** (`752b23d2`): BLOCK on A and C, MITIGATION. R6-1 is closed; R6B-1 and R6B-2 (private-name identity is inconsistent between binding keys and member lookup) are open. This is the 2nd consecutive BLOCK since the continue ruling. **Operator 2026-10-06 ("Both recommended"):** exact-statement exceptions for the 3 production uses, plus a refusal of private (mangled) names. Folded into **2q-a-repair-7 (final 2q-a slice), LANDED** (`5d87a8e`, Sonnet 5.5 `b9bf57d5`): v2 ban; five exact-statement exceptions; private-name and quoted-annotation refusal; value tracking removed. 32 of 40 closure-probe executions refused; 8 (escaped-value stores through a call, container or parameter) are declared v2 exclusions. Production has 0 refusals and unchanged numbers. **Astra final review** (`2f7dce26`): BLOCK on A and C, MITIGATION. R7-1 is a builtins alias bypassing the ban; R7-2 is an exception statement that doesn't validate its receiver. **ROUND CAP AGAIN (third consecutive BLOCK since the continue ruling): held for the operator.** Landing run at 5d87a8e: gen2-check exit 0 (2,310 tests, 2,302/2,302, 2,270 s); gen2-gateway exit 0 (1,516+1,516, 956 s). Non-blocking items are DEBT-017. Landing run at a4deb99: gen2-check exit 0 (2,271 tests, 2,282/2,282, 2,365 s); gen2-gateway exit 0 (1,516+1,516, 966 s). Landing run at 59b0536: gen2-check exit 0 (2,262 tests, 2,270/2,270, 1,994 s); gen2-gateway exit 0 (1,516+1,516, 968 s). **2q-a-repair-7 (slice B) BLOCKED before coding** (Sonnet 5.5 `6a7213a4`): three production uses of banned names (`gen2/supervisor/jobs.py:164`, a thread-local `__dict__`; `gateway/research_gateway/core/payload.py:251` and `:280`, `object.__setattr__` in the sealed classes' `__init__`). Awaiting the operator: the orchestrator recommends exact-statement exceptions, like the loader. Earlier: **ROUND CAP REACHED** (third consecutive BLOCK since Gate D #4: 2q-a-repair-5 slice 1, Astra `9796d360`, BLOCK on A and C, MITIGATION; F1 scope declarations and alias uncertainty; F2 three weak paired controls). The operator chooses between accepting the remainder as debt (closing 2q-a) and continuing (a fresh Gate D first). **Review-throughput rules adopted 2026-10-05** (BUILD-CHARTER "Review throughput"), applying from the next dispatch. 2q-a has **2 consecutive BLOCKs since Gate D #4**; a third goes to the operator. **2q-a-repair-4: Astra BLOCK on A and C, PASS on B, MITIGATION** (`ca0161ae`): F1 namespace mutation and unlisted producers; F2 transformation spelling against identity; F3 loader-module context. Hash correction and completion dominance are ROOT-CAUSE. Astra's follow-up (new rules) classifies F1 and F2's quoted field markers, plus the linked Gate C items, as **BLOCKING**; F3 and the remaining Gate C wording are **NON-BLOCKING** and registered as DEBT-016 (task 2q). On the proposed interpreter cross-check, Astra says it would not close the family alone and would need a contract amendment to certify; not pursued. **Slice plan:** 1 = binding identity (2q-a-repair-5 **LANDED** `3cd4716`, Sonnet 5.5 `ff719273`: one resolver (`Facts.expr`), nonlocal resolution, net 309 hand-written lines, no measurement change; **Astra re-review DISPATCHED** `9796d360`. Landing run at 3cd4716: gen2-check exit 0 (2,248 tests, 2,256/2,256, 2,090 s); gen2-gateway exit 0 (1,516+1,516, gateway mutants passed, 971 s)), 2 = call-time owner effects, 3 = F2 field markers. **2q-a-repair-3: Astra BLOCK on A and C, PASS on B, MITIGATION** (`78dde6c8`): F1 effective members, F2 binding and dispatch holes, F3 loader behaviour, F4 subprocess-completion validity. Item 0, the plan (R3 ROOT-CAUSE), `_no_reading` and the six R4 mutants are accepted. **2q-a-repair-4 LANDED 2026-10-05** (`a235bf0`..`01fa8ad`). The coder reports: positive recognition through four dispatchers (`SRC-FORM-UNRECOGNISED`, 28 categories, still v1); effective members; a loader fingerprint; a completion witness, with any errored test now INVALID. gen2-check exit 0 (2,237 tests, 2,244/2,244); gen2-gateway exit 0 (1,516+1,516, 394/394). No production change. **Astra re-review DISPATCHED** (`ca0161ae`). Orchestrator reruns at 01fa8ad match: gen2-check exit 0 (2,237 tests, 2,244/2,244, 2,204 s); gen2-gateway exit 0 (1,516+1,516, gateway mutants passed, 963 s). Dispatched as Sonnet 5.5 `33ee6c78` ( brief docs/gen2/tasks/2q-a-repair-4.md: positive recognition, effective members, a loader fingerprint, completion dominance). This is the first BLOCK since Gate D #4. Earlier: **OPERATOR RULINGS 2026-10-05 ("I agree"): B adopted; `_no_reading` replacement authorized; it goes inside this repair.** **2q-a-repair-3 LANDED 2026-10-05** (`b12c312`..`dbe5dd4`). The coder reports: SOURCE-CONTRACT v1 with 27 refusal categories; one source index; one transition plan; `_no_reading` replaced by `_Unread`; the crash-kills rebuilt as behavioural mutants. gen2-check exit 0 (2,178 tests, 2,151/2,151); gen2-gateway exit 0 (1,516+1,516, 394/394). **Astra review DISPATCHED** (`78dde6c8`; the first session `d1d4e515` stopped on a model-capacity error). Orchestrator reruns at dbe5dd4 match: gen2-check exit 0 (2,178 tests, 2,151/2,151, 1,903 s); gen2-gateway exit 0 (1,516+1,516, gateway mutants passed, 961 s). Dispatched 2026-10-05 (Sonnet 5.5 `96722a4d`; brief docs/gen2/tasks/2q-a-repair-3.md: Gate D #4 checklist 0–8). **2b-repair-20 LANDED** (`5354346`, GPT-6.1-Sol `96aaf466`): a project-owned address serializer keeps `::ffff:7f00:1`; the endpoint tests pass on 3.12.3 and 3.12.14; the coder reports both targets exit 0 (2,040/2,040; 1,500+1,500, 377/377). **2b-repair-20 ACCEPTED** (Astra `62ccbbd1`: PASS on A, B and C, ROOT-CAUSE). Orchestrator reruns at 5354346 match (gen2-check exit 0, 2,044 tests, 2,040/2,040; gen2-gateway exit 0, 1,500+1,500). Coders are back on Sonnet 5.5 (operator 2026-10-05). Earlier: **Gate D #4 BLOCK, choose B.** Report: `private/reviews/gen2-gate-d-4-astra-review.md`. The operator must rule on (1) adopting B, the supported-source contract; (2) authorizing the `_no_reading` production change before 2q-a acceptance; (3) its sequencing. After that, one family repair against checklist 0–8. Earlier: **RERUN DISPATCHED 2026-10-05** (fresh Astra session `6544e498`, pinned 4f1ae96, same task file `gen2-gate-d-4-task.md`). The first session `f657c1c2` closed after about 12 minutes with no report; the cause is unknown. **Operator 2026-10-05 ("All 3"): the CI design is approved, and three things are in flight.** (1) **2b-repair-20 DISPATCHED** (GPT-6.1-Sol `96aaf466`, brief docs/gen2/tasks/2b-repair-20.md): a project-owned canonical address serialization (CI design §8, D5) and an exact reference-interpreter pin. (2) **ci-cd-1 LANDED as PRs 2026-10-05, awaiting the operator's merge:** trevorbyrum/ci-cd #5 (image v2), #6 (opt-in clean workspace and identity), #7 (C4 design note only: `.inside()` uses `--volumes-from`, so the execution container inherits the worker's Docker socket and `--network none` would not seal it), #8 (C5 evidence, stacked on #6). Auto-merge is off and the ci-cd Jenkins checks are green, but those checks run only archgate's tests: the new library behaviour is verified offline only. **ci-cd-1 was dispatched** (GPT-6.1-Sol `8a77743f`, in the separate clone `~/work/ci-cd-gen2`, brief docs/gen2/tasks/ci-cd-1.md): the first platform PRs (image v2, identity/clean workspace, C4 sealed container, C5 evidence), opt-in and PR-only, for the operator to merge. (3) This Gate D #4 rerun. Superseded: the first Gate D #4 dispatch (fresh session `f657c1c2`). Orchestrator reruns at 4f1ae96 match: gen2-check exit 0 (2,040 tests, 2,039/2,039); gen2-gateway exit 0 (1,500+1,500). **Operator 2026-10-03: pause the loop once Gate D #4 reports.** Next, Jenkins CI for this build. this is the **third consecutive BLOCK on 2q-a**. Astra on 2q-a-repair-2 (`0da948d1`): BLOCK on A and C, PASS on B, family verdict MITIGATION. The ledger fixes the accounting of absent keys, but the keys themselves still come from a lossy reading of the code:
    - R1: same-name functions take each other's old obligation.
    - R2: a method under `if True:` drops the Router count from 132 to 127 sites while all 19 pairs survive. Aliases, class decorators and dynamic `__all__` are also misread.
    - R3: drafting an admission collides with an existing mapping.
    - R4: six mutants are 'killed' by a KeyError crash, not by a failed check.

    Gate D #4 decides between full Python support and a declared supported-source subset that gen2-check refuses anything outside, and sets a finite checklist. (The post-2q Gate D becomes #5.) **2q-a-repair-2 LANDED 2026-10-03** (`35ffdd1`..`4f1ae96`, GPT-6.1-Sol `e34b5045`):
    - baseline v3 with 1,051 persistent IDs, each present, mapped or retired, through a ledger that is empty at this pin;
    - admission requires a reasoned ledger entry;
    - ambiguity fails closed;
    - scoped locators.

    Coder's results: gen2-check 2,040 tests, 2,039/2,039 mutants; gen2-gateway 1,500+1,500, 377; production delta 0. **Astra re-review DISPATCHED** (`0da948d1`; third round on 2q-a). Orchestrator reruns are in progress. Brief: 2q-a-repair-2 (GPT-6.1-Sol; brief docs/gen2/tasks/2q-a-repair-2.md: explicit identity, a ledger of maps, retirements and admissions, ambiguity fails closed, scoped locators). Astra on 2q-a-repair (`98a9d2a6`): BLOCK on A/C, PASS on B. Family verdict MITIGATION. Root cause: a lossy representation lets lost identity read as improvement.
    - R1: conditional same-name Router → 0/0.
    - R2: rename or move resets the threshold obligation.
    - R3: new or renamed files escape the dependency ratchet (real `normalized.py` patch).
    - R4: a qualified locator resolves through the flattened short-name index.
    - R5: 2 rejected tests.

    This is the second consecutive BLOCK on 2q-a; a third triggers Gate D. **2q-a-repair LANDED 2026-10-03** (`1b5b81c`..`c87821e`, Sonnet 5.5 `9fc444b6`). F1–F7 are fixed:
    - C3 family resolution;
    - both-dimension offender comparison;
    - DEBT-014 and DEBT-015;
    - locators recognised by grammar;
    - fan-out, stable fan-in and reach ratcheted;
    - baseline v2.

    The coder reports gen2-check at 2,005 tests and 2,027/2,027 mutants, and gen2-gateway at 1,500+1,500. **Astra re-review DISPATCHED** (`98a9d2a6`). Orchestrator reruns match: gen2-check exit 0 (2,005 tests, 2,027/2,027 mutants), gen2-gateway exit 0 (1,500+1,500). Previous step: 2q-a-repair DISPATCHED (brief docs/gen2/tasks/2q-a-repair.md). Astra on 2q-a (`8e5c3480`): BLOCK on A and C, PASS on B. Reproduction is exact (27/27 tables). The phase-close mechanism, the 13 register entries and the locator reconciliation are accepted. Open:
    - F1 HIGH: qualified base syntax erases the 132 Router self-calls; the tool uses depth-first order instead of C3.
    - F2 HIGH: an offender that drops below a threshold escapes a growth in the other metric.
    - F3: two register entries are missing (importer unexamined-file inventory, Phase 3 usage estimator).
    - F4: a locator whose prefix is deleted becomes unchecked.
    - F5: fan-in/out and instability are reported but not ratcheted, against the charter.
    - F6/F7: low; documentation and test environment.

    **2q-a LANDED 2026-10-03** (`0306df4`..`1e8dc9f`, Sonnet 5.5 `f5ac8d3c`). It adds `tools/gen2_metrics.py` (reproduces Gate D #1/#2/#3 byte for byte), a digested baseline with ratchet, exemptions (none), `gen2-hotspots`, the DEBT-REGISTER (13 owned obligations, no mitigations) with `phase-status.json` and `gen2-debt`, `gen2-locators` with stale locators reconciled, and 157 mutants. No production code changed. The coder reports gen2-check 1,931 tests and 1,980/1,980 mutants, and gen2-gateway 1,500+1,500. **Astra review DISPATCHED** (`8e5c3480`). Orchestrator reruns match: gen2-check exit 0 with 1,931 tests and 1,980/1,980 mutants killed, and metrics, debt and locators all passing; gen2-gateway exit 0 with 1,500+1,500. When recording an acceptance, set the task to `closed` in `docs/gen2/phase-status.json` in the same commit. Earlier: 2q-a DISPATCHED 2026-10-03 (Sonnet 5.5 `f5ac8d3c`; brief docs/gen2/tasks/2q.md, part a: metrics, ratchet, debt register, locators). Orchestrator reruns at 28a2e83 for the 2b acceptance match: gen2-check exit 0, 1,762 tests, 1,823/1,823; gen2-gateway exit 0, 1,500+1,500. Earlier: QUEUED; **operator ruling 2026-10-02: one-time Gate D sequencing.** When 2b is accepted, skip the Gate D that acceptance would normally trigger: Gate D #2 measured the whole system the same day, and 2q builds the metrics Gate D uses. **The post-2q Gate D (now #5; #3 and #4 were charter-triggered) runs when 2q is accepted, before 2c starts.** scope adds Gate D #1 findings 5–6: Router mixin collaboration metrics (132 cross-file self-calls, 19 file pairs), the gateway package cycle adapters↔core↔registry, a debt register with baselines, and reconciliation of stale INVARIANTS/BUILD-STATE locators, including the Phase 3 revision-lifetime item — operator ruling 2026-09-30; runs after 2b is accepted, before 2c]: build the charter's architecture metrics into `make gen2-check` (stdlib only; dependency structure, architecture smells, function complexity, ratcheted baseline; git change-coupling/hotspot report), and `docs/gen2/DEBT-REGISTER.md` with its phase-close check. Then the **first Gate D whole-system review** over Phases 0–1 and 2a/2r/2b/2q. 2c does not start until Gate D passes.
  - **2c** [**CLOSED 2026-10-10** (Astra 2c-4a3: task complete; DEBT-030 closed). Slices: 2c-1 `2339991`; 2c-2a `62d6c52`, 2c-2b1 `6524e58`, 2c-2b2a `c1ffb16`, 2c-2b2b `7941ea3`; 2c-3a `e9c0a47`, 2c-3b1 `869d576`, 2c-3b2 `549a351`; 2c-4b `70a851d`, 2c-4a part 1 `346c83d`, 2c-4a2 `86132e7`, 2c-4a3 `c4a3574`. Operator rulings 2026-10-09 (vocabulary A, per-plan confidence scale). Follow-ons DEBT-032/033 (2d), DEBT-034 (2e2). **Gate D #6 PASS** (fresh Astra `2444ac7a`: 2d may start; F1→DEBT-035, F2→DEBT-036, F3→DEBT-031)]: evidence instrumentation and accounting. E-1…E-9 denominators from durable inventories. Research-state views. **Durable, attributable semantic assessments (F3):** lineage, dated source lifecycle dispositions, contradiction/branch dispositions, semantic accrual; arithmetic consumes judgments and never produces them. Stopping profiles limited to implemented descriptive, coverage and known-item evaluators; G-11 refuses the rest at admission and approval. Accounting consumes G-1 impact dispositions. **Disposition/confidence reconciliation (F9):** lossless mapping into the bundle, `export-bundle/2` if incompatible, unknown stays unknown.
  - **2d** [**OPEN 2026-10-10**; brief docs/gen2/tasks/2d.md; owns DEBT-032/033/035/036; **2d-1 ACCEPTED** (Astra round 2, pinned `68849b8`; landing green): DOSSIER.md (12-slice map) + durable obligation-assessment admission (all three approval kinds); **2d-2 ACCEPTED** (Astra first review, pinned `de1ced0`; landing green; DEBT-032 closed); **DOSSIER slice 3 (V-6) COMPLETE** (2d-3a matcher `ce6dfaa`→quote-protection/5 `dba8f35`; 2d-3b artifacts `53e7e47`, governed computation/capture-bound support `7766759`, notification/adjudication refusal `129d202`; DEBT-038 closed); **2d-4 SPLIT** (~1,050 lines): **part 1 ACCEPTED** (Astra round 2, pinned `b2a69b9`): adverse verdicts → owned judgment holds; **part 2 SPLIT** (~850 lines): **2d-4b part 1 ACCEPTED** (`73c4e1b`, pure acquisition-lineage validator); **2d-4b2 slice 1 ACCEPTED** (Astra round 2, pinned `3e826f3`): trusted acquisition admission, DDL 14; **2d-4b3 SPLIT** (~1,050 lines: receipts 350 / tiers 300 / extraction 400): **slice 1 ACCEPTED** (`7106c36`, canonical receipts consume admitted acquisitions, DDL 15); **slice 2 SPLIT** (~850): **part 1** `b5de4c8`: landing green; **Astra round 1 BLOCK** (R1 Unicode-blank bodies count as content; R2 extraction methods bypass the ceiling and promote); **2d-4b3b-repair-1 part 1** `1323cf6`: R1/R2 closed; **Astra round 2 BLOCK on R3** (A6-D28 paired control invalidated by shared fixture; landing exit 2); **repair part 1 ACCEPTED** (Astra round 3, `23b39a6`); **2d-4b3c SPLIT** (~750 lines): **part 1 ACCEPTED** (Astra round 2, pinned `7b5aaae`; DDL 18, both extraction methods consume a matching admitted acquisition; landing green); **part 2 ACCEPTED** (Astra first review, pinned `0988139`; DDL 19 caps both extraction methods via SQL 16's shared content view; landing green); **2d-4b3d ACCEPTED** (Astra round 3 of 3, pinned `9436a34`; DDL 20 table citations need recorded full text; DDL 21 exact receipt/span domain: complete decoded names, exact numeral offsets; landing green); **2d-4b3e** design `54d75d9` (re-estimated ~1,250 lines, split 480/460/310); **operator ruling 2026-10-12: only independent extraction validates** (different extractor tool/method, separate validator, compared; same-tool replay = integrity only); **2d-4b3e1 ACCEPTED** (Astra round 3 of 3, pinned `b731a22`; DDL 22 immutable extraction/validation records under `extraction-validation/1`; DDL 23 shared JSON member-name domain on 3 columns; Router/Store NUL-name refusal (C-13); fail-closed SQLite-catalog column classification 36 JSON / 488 scalar pinned to dual hashes; landing green); **2d-4b3e1-json2 part 1 ACCEPTED** (Astra round 3 of 3, pinned `b916117`; every authenticated failed attempt retained as opaque exact bytes + SHA-256 for any strict-parse refusal; SQL 24/25 bind descriptors both ways; refusal-class audit; 6 of 36 JSON columns guarded; landing green); **2d-4b3e1-json2b** re-estimated ~810, split 2 parts: **part 1** `a28c7e2` (global Router/Store member-domain admission incl. confidence labels and open maps; SQL 26 guards 8 more columns, 14 of 36 covered, 22 named pending for part 2): **ACCEPTED** (Astra first review; landing green); **part 2 ACCEPTED** (Astra first review, pinned `b66298f`; SQL 27; 36/36 JSON columns guarded; **JSON member-name family closed store-wide**; landing green); **operator ruling 2026-10-14: extractor identity via tool registry with families (settles N1)**; **2d-4b3e2** re-estimated ~495+475: **part 1** `1013ed6` (SQL 28 operator-maintained extractor registry with families; new extractions pin a registered tool + revision; ExtractorRegistry collaborator via authenticated operator surface): landing green; **Astra round 1 BLOCK on C1** (A/B PASS; four mutant controls never reach their changed code); **repair-1** `23440ec` (all 37 pairings qualified, tests only): landing green; **part 1 ACCEPTED** (Astra round 2); **part 2** re-estimated ~930, split 490/440: **slice 1** `0cfb573` (SQL 29 `extraction_validations_v2` under `extraction-validation/2`: different registered family required, same-family replay integrity only, NULL pins refused; no authority yet): landing green (gen2-check rerun after DEBT-039 flake); **Astra round 1 BLOCK on F1** (family rename across registry revisions manufactures independence); **p2-repair-1** `50cff2e` (families compared under the validator extraction's one approved registry revision; both pins retained; missing membership refused): landing green; **slice 1 ACCEPTED** (Astra round 2); **operator ruling 2026-10-15: latest registry revision governs new validations**; **slice 2** re-estimated ~900, split: **part 1** `ad1cc4a` (SQL 31 + Router: new `/2` validations must pin the highest admitted registry revision, checked inside the writer transaction): **ACCEPTED** (Astra first review; landing green); **part 2** split by receipt method: **consumers part 1** `dc81392` (SQL 32: `verifier_extraction` receipts need the verifier's own pinned durable extraction via `extraction.extraction_id`; SQL 21 span trigger replaced by an identical-plus-member successor; trigger-order tool reverses installed triggers only): landing gen2-check exit 2 (retired trigger counted as uncovered; no mutant ran), gateway green; **Astra round 1 BLOCK on R1** (A/B PASS); **c1-repair-1** `0364453` (shared installed-trigger helper `tools/gen2_ddl_triggers.py`; coverage over the final installed triggers; installed count reported): landing green; **consumers part 1 ACCEPTED** (Astra round 2); **consumers part 2** `25141bc` (SQL 33 + EvidenceWriter: `validated_extraction` receipts need an exact successful `/2` validation bound to the receipt's acquisition, lineage, tool, pin and tier): **ACCEPTED** (Astra first review; landing green); **2d-4b3e2 COMPLETE**; **2d-4b3e3** split: **part 1** `ba94b99` (SQL 34 retires SQL 17: load-bearing support from an extraction method needs a bound durable basis via `bound_extraction_receipts`, rechecked at promotion; the same receipt must carry tier/use/V-8/tier-0 gates; historical, `/1`, failed and integrity-only bases stay fenced): landing green; **Astra round 1 BLOCK on F1 (HIGH)** (validated support not capped by the independent extraction's tier); **repair-1** `727dcda` (validated support capped by target, exact independent extraction and acquisition ceilings at promotion; Router refuses over-tier validated receipts): landing green; **part 1 ACCEPTED** (Astra round 2; extraction support now authoritative only via bound, tier-capped durable basis); **part 2** `0e903ee` (bound-basis receipts no longer raise the obsolete unbound-extraction hold; fenced receipts and truthful missing content still do; coder disclosed one out-of-scope filename lookup in ~/.agents, no matches, nothing read): **ACCEPTED** (Astra first review; landing green); **2d-4b3e COMPLETE**; **2d-4c** design `5009d9b` (~1,900 lines, 4 parts: records / successor receipt refs / fixture conversion / mandatory consumption); **operator ruling 2026-10-17: attributed assessment + retained evidence artifact per performed check, `not_applicable` needs a reason, quote tokens supplementary only**; **part 1** `89401a7` (+ `7fbeb0d` design/metrics; SQL 35/36 immutable `attributed-assessment/1` check records with retained evidence and reasons; DetailedChecks collaborator; ~605 lines vs ~495 estimate; no authority yet): **ACCEPTED** (Astra first review; landing green); **part 2** `6c145ae` (re-estimate `f149947`; `verification-receipt/2`, optional per-kind record refs, SQL 37; 464+85 lines vs 500+85 est.) — landing green; **Astra round 1 BLOCK (Gate C only: C1 fixture defeats trigger reversal, C2 target/validator bytes indistinguishable)**; A/B PASS, production ROOT-CAUSE; **2d-4c-p2-repair-1** `927b32d` (tests only; shared `ddl_fixtures` order restore — audit found **9 modules whose "reversed" runs were not reversed**, all repaired; distinct target/validator bytes + selector mutants) — landing green; **Astra round 2 PASS — part 2 ACCEPTED** (no earlier acceptance exposed: 421 raw-DDL tests pass in real reversed order); **part 3** audit `4d98d83` (41 modules, ~1,050 lines → split 3a/3b); **part 3a** `9416fd6` (extraction consumer fixtures; tests only, 263 lines) — landing green (gateway carried forward from 927b32d); **ACCEPTED** (Astra first review; NB1 → 3b); **part 3b** re-audit `58608e6` (remaining ~970 lines → split 3b/3c) + `1bfb9a9` (canonical/acquisition/content Router consumers + NB1 authority control; tests only, 442 lines) — landing green (gateway carried forward); **ACCEPTED** (Astra first review, no findings); **part 3c** re-audit `3fe2059` (remaining ~1,140 lines → split again) + `d140c23` (Router pending-bound/table/span/exact-span consumers; tests only, 465 lines) — gen2-check landing green (5,502 s); **ACCEPTED** (Astra first review, no findings); **part 3d** re-audit `2f192d3` (split again) + `1faacfb` (3 raw table owners; tests only, 428 lines) — landing green; **ACCEPTED** (Astra first review). **3d NB1 RULED (operator 2026-10-18): cap span offsets at 2^53−1** (task file ruling) — implementation queued as a production slice before the raw-span conversion and part 4. **Part 3e** audit `2165cfa` (split again) + `2bf8bbe` (Router quote/capture/verdict; tests only, 453 lines) — **ACCEPTED** (Astra first review; NB1 bookkeeping). **Next coder job: ci-2** (operator 2026-10-18); then span-cap production slice, remaining part 3 (raw quote/capture/adjudication, global raw/history/JSON, amendment positives, 6 raw-span owners — cap implementation pending), then part 4 (raw owners, quote/capture/verdict, global raw/history/JSON, 2 amendment positives; must end with a no-pending inventory) and part 4 next. Part 3 total now ~2,050 lines vs DOSSIER's original ~460; parts 3–4 next. Operator rulings 2026-10-10: tier-0 off (DEBT-037, phase 3); layered quote matching (exact → named normalization → ≥98% near-match held for review; number/negation/unit changes always fail)]: verification, dossier and publication. V-1…V-9, byte-exact quote before NLI, tier-0 optional (screens and alarms, never promotes), quote-span and tier-vs-route checks, dossier assembly with hash truth. **Completion gates require real challenge evidence, coverage integrity and required verification (F3).** Completion approval bound to the exact dossier (G-8) and distinct from publication approval. **One JSONL/file export path (F7)** with full guarantees: ordering, equal-pair replay/conflict, tombstones, unknown reconciliation, truthful counts, per-record licence checks. The export-doc Phase 2/3 split gets updated. **Durable feed state and freshness computation (F10, part 1).**
  - **2e1 — live-execution preflight (F1, F5, §4(d))**: **Gateway-client construction rule (operator ruling 2026-10-02, 2b-repair-15 F2):** a `GatewayClient` (and any call to its `resolve()`) is constructed only inside a supervised job child, so the supervisor's job `deadline_at` termination bounds the otherwise unbounded name lookup. The 2e1 review must verify that no other construction site exists (engine process, router, operator tools). Per-job isolation, covering scratch, read-only inputs, protection of control state/spool/other topics/unrelated auth homes, no operator or broad gateway credentials in files or environments, and research only through the governed gateway, demonstrated with the actual runner. Dedicated gen-2 gateway/database/network deployment. Explicit resolution of AUTH-DEMO F2/F4. **§4(d): a genuinely rejected credential → dated failing fact + typed hold + the invocation ENDS FAILED with retained evidence**, run against the pinned runner before any productive call. **Run-admission spend policy (F5):** operator ceiling plus resource limits, one accounting owner, failed/retried usage counted, conservative next-dispatch authorization, hold on uncertain usage, single dedicated gateway owner, no automatic resumption after uncertain dispatch. **Usage capture (operator request 2026-09-29), built so it can later drive a cadence estimator:** for every invocation *and* attempt (failures and retries included), record: provider, model, runner version; input/output/cached tokens *as reported by the runner*; provider-reported cost when available (API billing); wall time; the gateway calls and credits correlated by invocation+attempt id; and the run's kind, topic, cadence context. For subscription plans, record snapshots of each provider's own usage-window readings (e.g. % of a 5-hour/weekly window) before and after each run, taken through a generic per-provider reader. Nothing operator-specific. These readings are account-wide, so other use of the same account contaminates them; store them as context, never as per-run attribution. Anything not reported is recorded as `unknown`, never as zero.
  - **2e2 — real executors and the S4–S7 workflow (F3, F10)**: one pinned runner family. Pending-first selection. Fixed-floor scope/method-fit/facet checkpoints plus the signal queue. A fresh-context non-author facet audit. Protected exploration and verification capacity. Bounded deepening/bridge/reframing probes. Typed disagreement holds with deadline escalation. **A counterevidence challenge, including a competing-explanation test per open contradiction, then a fresh-context sufficiency review, then the operator's exact-dossier decision.** A scheduler loop with bounded feed polling, due-time checks, mandatory reopening, last-tick health, the transition notifications §3.4 needs, and operational measurements (attempt correlation, usage including failures, rework, drift, false exclusions, operator effort, time in holds). Bounded audits: source-to-claim sampling, sampled state re-derivation, tier-0 false-pass/false-alarm records. **Retrieval-audit evidence requirement (Gate D #2 F6; recorded by 2b-repair-14): before real workflow acceptance, 2e2 must give the sampled state-integrity audit an independently checkable evidence requirement for retrieval** — what the trusted capture retains of each retrieval so that a sample can be re-derived without trusting the claim, and a missing required item is itself an audit failure. Today `gateway_call_ref` acknowledges a durable call row of the gateway (the request, its correlation and telemetry), not a response artifact; D-1's raw-response retention is for decision receipts, not retrieval. No new router writer and no duplicated provider parser in the router.
  - **Phase 2f topic drafted** (operator, 2026-09-30): fresh intake, not gen-1's queue. Draft brief at `docs/gen2/PHASE2-TOPIC-DRAFT.md`; confirmed through the real S1 conversation once 2e lands.
  - **2f**: the supervised live single-topic run. **Operator inputs needed:** a test question and intended deliverable (plus the in-workflow approvals); the spend ceiling and its scope, with time/attempt/concurrency limits; the provider/runner configuration and credentials via the secrets surface, including a safe one for the rejection demonstration; allowed research lanes; one JSONL export destination plus publication approval; the decision/hold owner, review deadlines and surveillance expectations.
  - **Carried to Phase 3 — usage estimator (operator request 2026-09-29):** given a topic profile and a cadence, estimate API cost and subscription-plan share (for example, the percent of a weekly window). Calibrated from the Phase 2+ usage records by fitting tokens per percent-of-window from quiet-account windows, and reported as ranges with the calibration's uncertainty. Deferred because it needs data from many runs, and one Phase 2 run can't calibrate it.
  - **Phase 2→3 operator gate** once all of these are accepted.

## 2026-10-25: batch S1, tiered checks and retired replay tools (a68ad7e, PR #20): BLOCK, round 1
- **Astra** (`d491861a`; `private/reviews/gen2-s1-astra-review-20261025.md`):
  - A BLOCK on **S1-R1** only. B, C, deletion closure and S proportionality PASS.
  - The S1 simplification is ROOT-CAUSE.
- **S1-R1:** `gen2-accept` aborts, rather than running trigger-order, when the DDL comparison is unavailable (missing `origin/gen2` or an invalid base). The contract requires running trigger-order when unsure.
- **Verifier** (Sonnet `404aba25`): **gen2-accept exit 0 in 6,091 s.** Trigger-order was correctly skipped (no DDL diff against `dbbdced`). That is about 30 min faster than the recent roughly 7,900 s gen2-check runs.
- **Repair** (a Makefile recipe change plus controls) dispatched on the same branch. The full gen2-accept at `a68ad7e` is carried forward, since the repair changes only the fallback branch of the `gen2-accept` recipe. Round 2 re-runs Astra's five fallback probes on the repaired Makefile.

## 2026-10-25: batch S1 (66f34d9, PR #20): ACCEPTED, round 2
- **Astra** (`188d3fda`; `private/reviews/gen2-s1-r2-astra-review-20261025.md`): PASS, ROOT-CAUSE.
  - S1-R1 is closed: empty comparisons skip trigger-order, while non-empty and unavailable comparisons run it, with the reason printed and failure propagated. 11 of 11 fallback probes passed.
  - The full gen2-accept carried forward from `a68ad7e` (exit 0, 6,091 s) was judged valid.
- Merged as `b7747e1`. Retired: the exact replay oracle, the differential tool and the move/inline equivalence tools (D2). Trigger-order now runs only on a DDL change.

## 2026-10-25: batch S3 (10679ec, PR #22): ACCEPTED, first review
- **Astra** (`864fe4ea`; `private/reviews/gen2-s3-astra-review-20261025.md`): every gate PASS, ROOT-CAUSE, no blocking items.
  - The custom metrics ratchet, identity ledger and supported-source contract were retired (net −22,845 lines).
  - The boundary graph, 1,500-line rule, 15,000-line trigger and debt gate were confirmed byte-unchanged and still enforced.
  - The locator gate uses a stdlib AST index.
  - **`gen2-complexity`**: radon, per-function ceiling 48 and mean ceiling 10 (D5; current worst `gateway/research_gateway/clients/mcp_stdio.py:225::record_activity`). 48 catches regressions but is permissive as a quality bar.
  - The importer moved to `tools/` (D10), bringing engine production to 12,995.
- **Orchestrator ruling during S3:** four `test_locators` cases asserting the retired source contract's refusals (SRC-DEF-DUPLICATE/REBOUND, SRC-CLASS-CONDITIONAL, SRC-DECORATOR-UNKNOWN) were retired with that contract (ruling 3). Astra confirmed the ruling was applied narrowly.
- **Verifier** (Sonnet `92f902ad`): gen2-accept exit 0, **5,356 s** (3,971 tests; mutants 3,372/3,372). Trigger-order was skipped (no DDL change).
  - **Landing time trend:** about 7,900 s before S1, then 6,091 s after S1, then 5,356 s after S3.
- **Non-blocking items:** narrow the wording at `test_importer.py:611` and `check_gen2_sqlite_native.py:8`.
  - Records edits needed: the charter "Architecture metrics" text (done in this PR), CI-DESIGN §3.3/§3.4 and lines 192/196 (with R2, operator D12), and DEBT-017 reconciliation.

## 2026-10-25: S2 tool spike and operator ruling on mutation scope
- **Spike** (Sol `e95cecdc`; `private/evidence/s2-spike/REPORT.md`): recommends **Cosmic Ray 8.7.0 + pytest 9.1.1** with outcome normalization.
  - mutmut 3.8.0 skips decorated functions, so `Store.transaction()` (a `@contextmanager`) gets no mutants. Cosmic Ray mutates it.
  - Cosmic Ray on `gen2/store/api.py`: 318 mutants, 81 survivors, 23 min. Its native "kills" mix assertion failures, errors and syntax-invalid variants, so verdicts must be normalized.
  - The changed-line filter (`cr-filter-git`) on each file's last real change kept 3 of 723 and 1 of 318 mutants.
  - The dependency closure is 31 runtime packages.
- **Operator ruling (Trevor, 2026-10-25): the acceptance gate mutates changed lines only.**
  - Any survivor in changed lines fails acceptance, unless accepted with an inline `# pragma: no mutate` plus a reason, which Astra reviews.
  - Full-file campaigns are report-only, run at phase gates and Gate S.
  - This narrows plan §4 S2's "changed files".
- S2 dispatched to Sol, branching after S3 (PR #22) merges.

## 2026-10-25: batch S2, Cosmic Ray changed-line mutation (39d9cfd, PR #25): BLOCK, round 1
- **Size:** 112 files, +480/−34,700. Retired the hand-written mutant inventory, controls JSON and harness. The gateway keeps its 413-mutant step (an authorized later second step).
- **Verifier** (Sonnet `88c078d4`): gen2-accept hit 8 failures in S1's `test_acceptance`, so the orchestrator stopped the run after reproducing them.
- **Astra** (`3abdb762`; `private/reviews/gen2-s2-astra-review-20261025.md`): BLOCK on one family, otherwise passing.
  - **S2-C1:** a missed consumer. The `test_acceptance` fixture lacks the new build lock and a mutation stub.
  - **S2-C2:** mutation ran before S1's conservative trigger-order. The required order is check → conditional trigger-order → mutation → success.
  - **Keep** `gen2-mutation: gen2-venv`. Removing it would be a MITIGATION.
  - **NB1:** remove the unused `mutation_workers()`.
- **Selection-rule addition:** a change to a Makefile recipe requires running every test that executes that recipe (`test_acceptance`).
- **Repair dispatched** as one combined pass. A fresh gen2-accept and gen2-gateway will run at the repaired head.
- **Noted for the operator, no action taken:** `.github/workflows/gen2-check.yml` has been tracked since task 0a (2026-09-25). PR checks show only Jenkins. It is a deletion candidate under the "no GitHub Actions" rule.

## 2026-10-25: batch S2 (14c31e1, PR #25): ACCEPTED, round 2
- **Astra** (`8d7e46f0`; `private/reviews/gen2-s2-r2-astra-review-20261025.md`): PASS, ROOT-CAUSE.
  - S2-C1 and S2-C2 are closed: the order is check → conditional trigger-order → mutation → success, and the `test_acceptance` fixture models the full graph.
  - NB1 is done.
- **Verifier** (Sonnet `7be8a57c`): **gen2-accept exit 0 in 3,263 s** (3,910 tests; changed-line mutation had legitimately no applicable files); gen2-gateway exit 0 in 1,012 s (413/413).
- **The checks cut-back S1–S3 is complete.** Landing time went from about 7,900 s to 6,091, then 5,356, then 3,263 s.
  - Retired: the replay, differential and move tools; the metrics ratchet, ledger and source contract; the hand-written mutant inventory and controls.
  - Adopted: tiered trigger-order, radon ceilings, and Cosmic Ray changed-line mutation (gate) plus full-file campaigns (report-only).
- **Next:** 6a part 4 (freshness binding), contract plan §6.1, dispatched to Sol (branching after PR #25 merges).

## 2026-10-25: S2 cost defect found on first real use; S2b dispatched
- 6a part 4 (`5eb31d0`, PR #28): the verifier's gen2-check passed (3,922 tests).
- The changed-line Cosmic Ray step had **79 executable mutants**, and **each ran the entire suite** (about 52 min serially, fail-fast).
  - After about 71 min, only the baseline and **2 mutants** (both killed) were done. The projection was about 6 more hours.
  - The orchestrator stopped the run; the partial session is saved in the part 4 evidence.
- **Root cause:** S2 had no per-mutant test selection.
- **S2b** (Sol `01b7dbdf`): two-stage selection.
  - Stage 1 runs the tests covering the mutated line (coverage.py contexts preferred).
  - Stage 2 runs the full suite for stage-1 survivors only.
  - There is no loss of rigor: a survivor is always judged against the full suite. The target is under about 20 min for a part-4-sized slice.
- Astra's part 4 review continues statically. The mutation gate stays pending until a re-run with S2b.

## 2026-10-25: 2d slice 6a part 4, freshness binding (5eb31d0, PR #28): BLOCK, round 1
- **Astra** (`100fb0d6`; `private/reviews/gen2-2d-6a-p4-astra-review-20261025.md`):
  - A BLOCK, B PASS, C BLOCK, Gate S proportionality PASS.
  - The freshness fence is ROOT-CAUSE and sound: coherent capture, pre-effect writer fence, typed differences, a correct three-attempt bound, and the audit is respected.
  - Size: production +63 net, tests +241, matching the estimate.
- **R1:** recapture is not bound to the caller's finite deadline, as the 2026-10-23 ruling requires. It must reuse the existing deadline authority, with no new framework. Tests needed: expiry after a mismatch, expiry while awaiting the fence, and a live-deadline success case.
- **C1:** the exhaustion test needs an in-callback attempt-ceiling assertion, so that removing the bound fails by assertion.
- **N1** (non-blocking): consider tool-level skipping of annotation-only mutations instead of per-line pragmas. All six pragmas were accepted.
- **Mutation gate:** pending S2b.
- **Repair queued** behind S2b (one coder at a time on the shared tree).

## 2026-10-25: S2b (c334e03, PR #30): BLOCK, round 1; 6a part 4 (82befcb, PR #28): ACCEPTED pending the mutation gate, round 2
- **S2b, Astra** (`55f5459a`; `private/reviews/gen2-s2b-astra-review-20261025.md`): BLOCK on **S2b-C1** (MITIGATION as delivered).
  - Kills were awarded from selected test executions that had not been qualified on clean source. Astra reproduced a selected subset failing on unmutated code, so a survivor was counted as a kill.
  - A cached baseline was not bound to the execution configuration.
  - Everything else PASSED: shared coverage, staged selection, `ERROR_KILL` policy, the +18% overhead, and the 25-min mutation budget as reasonable.
  - Verifier gen2-accept exit 0 (3,955 s).
  - **Repair dispatched** (fresh Sol `80558bbb`): qualify each distinct selection on clean source, fall back conservatively, and bind the baseline to the configuration.
- **6a part 4, Astra round 2** (`f1e99957`): **A, B, C and S PASS, ROOT-CAUSE.**
  - R1 is closed: recapture is bound to the invocation's existing `deadline_at`, checked before capture, before preparation and inside the writer fence.
  - C1 is closed: an in-callback ceiling assertion.
  - **ACCEPTED pending the independent mutation gate**, which runs after S2b merges into the part 4 branch.

## 2026-10-26: S2b-C1 repair: eager controls too costly; lazy controls ACCEPTED (1d54e1d, PR #30), round 2
- **First repair** (`9f08939`, Sol `80558bbb`) qualified every distinct selection whole on clean source. Correct, but one 2,747-test control took 3,059 s to authorise a mutant run that stopped at position 471 (423 s). The projected mutation step was about 4 h, against 24.96 min. The orchestrator stopped the measurement at 18/79 results and kept the partial evidence (`private/evidence/s2b-c1/STATE.md`).
- **Astra cost consult** (`55f5459a`; `private/reviews/gen2-s2b-c1-cost-consult-astra-20261026.md`): lazy, kill-only controls are SOUND WITH CHANGES, under four conditions: construct the full ordered selection and stop at the boundary; fixture and unknown boundaries fall back to the whole selection; keep the source and execution-identity binding; exact cache only. Reusing the acceptance run as the stage-2 control is unsound without aligning the runners.
- **Round 2** (`1d54e1d`, brief `private/reviews/gen2-s2b-c1-lazy-control-brief-20261026.md`): replaces the eager controls. Net 0 lines against `9f08939`, +120 against `c334e03`. All five fault removals fail by assertion.
- **Measurement** on the part 4 changes: mutation 2,010.8 s (33.5 min) including 510.8 s of controls (18 controls over 12 sequences, all clean). Unit run 4,492 s.
- **Astra round 2** (`private/reviews/gen2-s2b-r2-astra-review-20261026.md`): A, B, C and proportionality PASS, ROOT-CAUSE. **ACCEPTED pending the verifier.** NB1: no executed fault receipt for "survivors take no control"; a passing assertion covers it.
- **Verifier:** gen2-accept at `1d54e1d` dispatched (Sonnet `9e8fda2f`).
- **Lesson (Gate S always-on):** a correctness repair needs its cost measured before review, not after. The eager design was the per-finding answer; the lazy one keeps the same guarantee with 8.5 min of controls instead of a projected 3 h or more.

## 2026-10-26: S2b merged; 6a part 4 ACCEPTED, so 6a is complete; S2c found
- **S2b** (PR #30, `1d54e1d`): verifier gen2-accept exit 0 in 4,129 s (tools-only diff, so the changed-line scope was empty). Merged.
- **6a part 4** (PR #28): merged origin/gen2 at `4fdfe4d` with no conflicts.
  - Verifier (Sonnet `5514f2a8`): gen2-accept exit 0 in 11,090 s; 3,927 tests OK.
  - Changed-line mutation: 3,793 candidates. FILTERED_GIT 3,632, PRAGMA 66, ASSERTION_KILL 60, ERROR_KILL 5, SYNTAX_INVALID 30, **SURVIVED 0**. 23 clean controls (940 s).
- **Astra mutation-gate confirmation** (`f1e99957`; `private/reviews/gen2-2d-6a-p4-mutation-gate-astra-20261026.md`): **6a part 4 is ACCEPTED.**
  - The four pragma lines pass for the exact excluded spans: keyword-only `*` and annotation `|` only. This is not blanket approval for future executable changes on those lines.
  - The 30 SYNTAX_INVALID variants are all keyword-marker replacements.
  - All five ERROR_KILLs have matching clean controls.
  - The merge leaves the part 4 files unchanged from `82befcb`.
  - Merged. **2d slice 6a is complete.**
- **S2c (cost defect, orchestrator diagnosis):** the mutation step re-ran the full suite as its baseline (4,370 s) instead of reusing the acceptance coverage.
  - Cause, reproduced with a throwaway Makefile: the recursive `$(MAKE) gen2-mutation GEN2_COVERAGE=…` exports `GEN2_COVERAGE` into the mutation process's environment, but not into the unit run's. `source_state()` hashes the environment, so reuse is refused.
  - The S2b measurement invoked the tools directly and missed it.
  - Fix dispatched (Sol `80558bbb`, brief `private/reviews/gen2-s2c-coverage-reuse-brief-20261026.md`).

## 2026-10-26: S2c merged; S4 rounds 1–3 (PR #35)
- **S2c** (PR #33, `6cfd65d`): removed the redundant command-line overrides on the recursive `$(MAKE) gen2-mutation`.
  - Astra (`55f5459a`): A and C PASS, ROOT-CAUSE, no findings. Six invocation forms were probed, including CI.
  - Verifier: gen2-accept exit 0 in 4,142 s. Merged.
  - Confirmed live: the S4 run at `01defff` reused the unit coverage, and mutation started seconds after the unit run.
- **S4 round 1** (`6325c90`, Sol `3290d2e7`, +113): Astra (`b0d34e37`) BLOCK.
  - **B1:** `write_holds` reused the promotion predicate `_has_basis`, which is alarm-aware. A bound, adjudicated extraction with a tier-0 alarm got a false unbound hold, and the commit receipt diverged from the written holds.
  - **B2:** no text-type check on the extraction reference, so a retained numeric reference lost its hold.
  - One cause; the three insertion rules themselves passed.
- **S4 round 2** (`5b1c4c7`, +153): `_basis_member` (SQL 34 membership plus the text type) is factored out of `_has_basis` (membership plus alarm). Astra: PASS, ROOT-CAUSE, accepted pending the verifier.
- **Verifier at `01defff`** (round 2 merged with gen2): the changed-line campaign found a full-suite **SURVIVED** mutant, `evidence_writer.py:358` `==` changed to `>=` on the acquisition `retrieved_at`. The orchestrator stopped the run at 10/158 when round 3 superseded the filter; the evidence is in `private/evidence/s4/verifier-01defff-stopped/`.
- **S4 round 3** (`af81ff9`, +185 against +140 planned): The time match is necessary: with it weakened, a different-time, higher-tier acquisition would authorize a table receipt. Astra round 3 confirmed that the parent code already matched time exactly, so the gap was the missing regression test, not a live path. Changes: exact call and time lookup; literal both-direction cases for all three methods; the route and acquirer filters and the table tier guard removed as redundant; equivalent variants documented, with no pragmas.
- **Astra round 3** (`private/reviews/gen2-s4-r3-astra-review-20261026.md`): A, B and C PASS, ROOT-CAUSE. **Accepted pending the verifier.** The removed route, acquirer and table-tier conditions are enforced by `_basis_member`, `_require_own_extraction` and `_require_validated_extraction`; no newly admitted operand class.
- **Lesson:** the changed-line mutation gate found an untested false-certification guard (weakening it changes admissibility) that two review rounds and 1,631 targeted tests missed. That is what S2 was adopted for.

## 2026-10-26: S4 rounds 4 and acceptance (90d5070, PR #35); S5 dispatched
- **Verifier at `af81ff9`:** stopped at 18/105.
  - Survivor `detailed_checks.py:65` `!=` changed to `>=`: a canonical alarm-bearing receipt was unpinned.
  - The next mutant in stage 2 (`NotEq_Gt`) was equivalent, because `"canonical_bytes"` sorts before both extraction methods.
  - Evidence: `private/evidence/s4/verifier-af81ff9-stopped/`.
- **Round 4** (`90d5070`, brief `gen2-s4-r4-brief-20261026.md`):
  - an 8-line literal test (an adjudicated canonical alarm is admitted and promotes, at SQL parity);
  - closed-domain string comparisons on changed lines rewritten as explicit membership tests;
  - a new optional annotation quoted.
  - Sol's own changed-line pre-check was clean. Net +194.
- **Astra round 4** (`private/reviews/gen2-s4-r4-astra-review-20261026.md`): A, B and C PASS, ROOT-CAUSE.
  - The original implementation already had the intended canonical-alarm behaviour. The test repairs a coverage gap.
  - The rewrites are equivalent over the supported domains.
- **Verifier** (`c1245d1d`): gen2-accept exit 0 in 4,729 s. 34 executable mutants, all killed in stage 1. Baseline reused. Mutation step 457 s. **S4 merged.**
- **Process changes (orchestrator):**
  - Coders run the changed-line gate through `make gen2-accept` on a disposable copy before pushing mutation-sensitive repairs.
  - Survivors are batched into one push.
  - A superseded campaign is stopped and archived.
  - Gate S watch: stage-1 survivors cost a serial full suite (about 70 min) each.
- **S5** dispatched (fresh Sol `2ab2c299`).

## 2026-10-27: Gate S #2 (Fable, fresh, `fe31c24a`) at S5 head `b3ffd23`
- **Report:** `private/reviews/gen2-gate-s2-fable-20261027.md`. Trigger: before 6b1 is designed.
- **Size:** engine side 177,868 at `65fb30e`, now 109,026 (−68,842 in 2.3 days, 10 landings). Production is 13,100.
- **Do now (no operator decision per the report):**
  1. the S5 repair;
  2. S6 widened to all value-domain DDL, adding SQL 22 `source_extractions_tier`, SQL 35 `detailed_check_records_domain`/`_spans` and their helper views, plus an approximately 8-line Router twin (about −2,760);
  3. delete the hand-written gateway mutants after S2d (about −2,470);
  4. R2 plus moving `docs/gen2/tasks/` history to evidence;
  5. delete the unused `.github/workflows/gen2-check.yml`;
  6. use the design-brief form of §7.1 for 6b1 and 6b2.
- **Operator decisions requested (S2-1 to S2-7):**
  - slice 7 absorbed into 6b1′/6b2′;
  - retire trigger-order after S6's final baseline;
  - shrink stage 2 once data from 10 or more sharded campaigns shows no verdict flip;
  - defer 2e1's subscription-window reader;
  - the 2e2-minimum scope;
  - INVARIANTS §13: the live S1–S3 intake moves out of Phase 2 (recommended option A);
  - charter rules on harness changes and on measuring cost before review.
- **Observed growth factors:** 1.3× for contracted engine slices, 2× for new mechanisms or runners, 3× for checking-pipeline changes.
- **Timeline to 2f:** about 22–30 working days single-threaded, about 17–22 with two coders. Live run around 2026-11-20 to 11-28, with a risk band into mid-December.

## 2026-10-27: S5 merged; S2d merged (parallel test shards); S6 BLOCK B1, round 1; Batch B in flight
- **S5** (PR #40, `2085e10`): verifier exit 0 in 3,443 s. Trigger-order: 323 triggers, 2,562 outcomes identical. Merged.
  - A 40-failure verifier run at `3a579af` came from a strengthened shared base (`RecordMatrix.test_domain`) inherited by the RAW class. The `RAW` flag now guards the typed-reason assertion.
  - Lesson: targeted selection must include every subclassing module.
- **S2d** (PR #39, `d873982`, Sol `2907f611`, +246). Measured quiet at fixed SHAs:
  - unit suite 2,949.5 s serial against about 800 s with 8 shards;
  - stage-2 survivor 3,529.6 s against 789.8 s, verdict unchanged;
  - peak memory 1.3 GiB.
  - **Astra** (`55f5459a`, `private/reviews/gen2-s2d-astra-review-20261027.md`): A and C PASS, ROOT-CAUSE. The S2b and S2c conditions are preserved. NB1: the stage-2 survivor summary copies first-shard metadata (reporting only; no change under S2-7).
  - **Verifier:** gen2-accept exit 0 in **874 s** (8 shards, 3,939 tests, union equal to discovery). Merged. **Acceptance went from about 4,100 s to about 900 s.**
- **S6** (PR #46, `9e97ed1`, −2,878). **Astra BLOCK B1:**
  - SQL 35's nonblank rule was not fully transferred. GLOB treats NUL as a terminator; the schema patterns treat NUL as content.
  - So NUL-only `assessment`/`context_examined`/`applicability_reason` committed. Reproduced through `Router.commit_outcome`.
  - The rule table was otherwise exact (83 objects).
  - **Repair** (Sol `eaec591c`): reuse `DetailedChecks._nonblank` at admission, add literal witnesses, and audit every S5 and S6 rule-table row for GLOB/trim/length semantic differences against its new owner.
- **Batch B** (Sonnet `3468c51e`, worktree `gen2-wt-3`). Pure moves out of `service.py`, plus `core.instants.utc_now`.
  - The orchestrator caught a behaviour change: compat timestamps gained a microsecond fraction.
  - Fixed with `utc_now(timespec=...)`, consumer formats byte-identical and pinned by `test_instants`. Acceptance rerunning.
- **Process:**
  - coder model mixing (charter, PR #45);
  - separation practices (PR #43);
  - coordination rule: coders wait while an S2d benchmark unit is active.

