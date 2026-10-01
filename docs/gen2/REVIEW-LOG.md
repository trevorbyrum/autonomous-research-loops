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
