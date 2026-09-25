# Gen-2 Behavioral Invariants

**Status:** frozen for Phase 0 (task 0a, 2026-09-25). Changes follow the charter's amendment path — a proposal, Astra review, operator decision — never an edit to make code pass. Where this file and code disagree, that is a finding; the code does not win by default.

**Sources, cited by short name:**
- **F** — `gen2-flow-architecture-20260924.md` (amended 2026-09-25): stages S1–S8, §2 ladder, §3 decision trace, §4 observability, §5 picks, §6 transition gaps.
- **DR** — `reviews/gen2-design-astra-review-20260922.md` (completed 2026-09-24): §3 gen-1 facts, §5 router/`commit_outcome`, §6 lifecycle, §7 decision layer, §8 accounting/dossier, §9 verification/gateway/publication, §10 budget/phases/release gates.
- **ADJ** — `reviews/flow-adjudication-astra-20260924.md`: (b) resolutions 1–7, (c) suggestions 1–10, (d) change table.
- **M** — `methodology-synthesis-20260924.md` (amended 2026-09-25).
- **B** — `docs/gen2/BOUNDARIES.md` (component entries by heading).

(F, DR, ADJ, M live under `~/work/research-loops-public/private/`.)

**Entry format.** `ID — statement` (written so a test can refute it). *Source*; *Enforced at* (where the rule is expected to live: schema file, DDL object in `gen2/store/schema.sql`, the module named in `gen2/boundaries.toml`, or an audit job); *Test must show* (the failure the test exists to catch — Gate C checks tests against this line). "Enforced at DDL" means the draft store rejects the violation itself; everything else is a Phase 1+ obligation.

Nothing in this file is evidence that a mechanism works. Every mechanism that runs inside the automated loop stays [proposed] in M's sense until the M §9 tests say otherwise (F §7).

---

## 1. Release gates (adjudicated)

Numbering follows DR §10's release gates; gate 1 is split into its crash half (1a) and its replay half (1b). **RG-U** is the cross-cutting unknown-is-not-zero rule.

**RG-1a — Crash at finalization.** For a crash injected at each `commit_outcome` boundary — before validation, after validation but before the transaction, inside the transaction before commit, after commit before the reply, after the reply — recovery leaves exactly one committed result for the invocation, at most one research ordinal, exactly one lease release, and at most one instance of each review-trigger identity.
*Source:* DR §10 gate 1; DR §5 steps 1–5; DR §3 (split finalization). *Enforced at:* router (single transaction); DDL `operation_receipts` (primary key; one `final_outcome` per invocation), `research_ordinals` (unique invocation), `leases` (release is write-once), `review_triggers` (unique identity). *Test must show:* counts read back from the store — not the router's return value — after each injected crash, for every invocation kind that finalizes.

**RG-1b — Stale or conflicting replays cannot change authority.** (a) Replaying a committed operation ID with the identical payload digest returns the original receipt and leaves the state revision unchanged. (b) Reusing an operation ID with a different digest is rejected and changes nothing. (c) An envelope bound to a superseded lease generation, a released lease, another topic's lease, a stale contract/config revision, or an `expected_state_revision` other than current is rejected before any mutation. (d) A receipt retained after its lease ended can be read but authorizes no new change. (e) Replaying an already-handled trigger after its episode closed opens no new episode.
*Source:* DR §5 steps 3 and 5; DR §3 (the three executed probes against gen-1 `accept_research_completion`); DR §10 gate 1. *Enforced at:* router; schema `commit-outcome.schema.json`; DDL `operation_receipts` (immutable), `review_triggers` (never deleted). *Test must show:* each of (a)–(e) as a separate case, including the gen-1 probe shapes (unminted run with generation −1; run-ID reuse with a different payload; stall-trigger replay).

**RG-2 — Every invocation kind shares lifecycle behavior.** For each kind in {research_pass, discovery, delegate, verification, checkpoint}, the same fault set — spawn/receipt uncertainty (crash between spawn and identity record), primary exit with live descendants, deadline expiry, cancellation — produces the same state-machine outcomes (L-1) and preserves or explicitly reconciles descendants and outputs.
*Source:* DR §10 gate 2; DR §6; B *Station supervisor*. *Enforced at:* supervisor (one implementation); DDL `invocations` transition trigger. *Test must show:* one parametrized suite over all five kinds with fake executors; a kind-specific lifecycle path is itself a failure.

**RG-3 — Failure paths end in bounded, visible states.** Missing counters, exhausted retries, stalled publication, and failed hold persistence each end in a typed hold or control incident with an owner and a deadline. None loops unbounded, and none is swallowed.
*Source:* DR §10 gate 3; DR §6 (every retry path consumes a declared budget; a failed hold write is a control failure). *Enforced at:* supervisor, router; DDL `holds` (owner and deadline required). *Test must show:* each of the four cases reaches a terminal visible state within its declared budget.

**RG-4 — Degraded observation never becomes negative evidence or successful stopping.** Provider outage, malformed or unparseable payload, telemetry loss, denied access, and partial pagination never produce: a `searched_empty` coverage fact, a zero in any count or denominator, a novelty or yield observation, a satisfied stopping rule, or a completion candidate. They produce `provider_unavailable` / `auth_failed` / `unknown` coverage plus a dated capability fact.
*Source:* DR §10 gate 4; F §4.3; B *Gateway*, *Evidence accounting*. *Enforced at:* gateway_client, accounting; DDL `search_observations` (a result count is only allowed on a successful search state). *Test must show:* each degraded input driven end to end to the dossier, which shows the affected rules as `unknown`.

**RG-5 — Producer capabilities cannot approve their own verification; cross-topic and stale-revision writes are rejected.** A verification receipt is refused when the verifier invocation is the producer invocation, when the verifier invocation is not of kind `verification`, or when it relied on an unvalidated extraction produced by the producer invocation.
*Source:* DR §10 gate 5; F S4 step 8; B *Verifier*. *Enforced at:* router (capability-derived authority); DDL `verification_receipts` (checks plus a role trigger that also refuses a verifier launched by the producer — an interpretation flagged in `gen2/store/README.md`). *Test must show:* each refusal, plus a write carrying another topic's ID and a write bound to a superseded claim revision.

**RG-6 — Accounting edge cases.** The known-item, novelty and dossier logic handles: zero assessed units (result `unknown`), repeated reports of one study (counted once at the study unit), a changed protocol (labels made under the old protocol do not count under the new one), and an unresolved contradiction (blocks `satisfied` wherever the profile names it).
*Source:* DR §10 gate 6; DR §8. *Enforced at:* accounting. *Test must show:* each fixture, with the expected operands written out by hand rather than computed by the code under test.

**RG-7 — Gateway restart and ownership.** Quota and breaker state survive restart and multiple owners; SIGTERM stops admission and drains within bounds; partial index delivery recovers. *Source:* DR §10 gate 7; DR §9. *Enforced at:* gateway service (Phase 2/3 repairs), projector.

**RG-8 — Migration reconciles.** Import counts and authority history reconcile against the frozen gen-1 snapshot; a complete cadence boundary and an operator amendment work in the canary. *Source:* DR §10 gate 8 and Phase 4. *Enforced at:* importer (0b onward).

**RG-9 — Restart preserves pins; status explains waiting.** Restart or replacement preserves configuration pins, auth-volume access and permissions; status answers why every waiting item waits. *Source:* DR §10 gate 9; F §4.4. *Enforced at:* app, operator.

**RG-U — Unknown is never zero, anywhere.** No count, denominator, coverage state, novelty value, usage figure, or stopping-rule operand may substitute zero, empty, or "none found" for "not observed". Unknown propagates as `unknown` through accounting, dossiers, holds and status, and nothing downstream consumes it as a value.
*Source:* F §4.3 ("silence is never success; absence is never zero"); B *Evidence accounting* (must never); DR §8 (zero assessed ⇒ unknown novelty; unknown usage shown as unknown). *Enforced at:* schemas (counts are nullable and carry an explicit status); DDL checks on `search_observations`; accounting. *Test must show:* for every numeric field that feeds a decision, a fixture where it is unobserved and the output reads `unknown`.

---

## 2. Commit protocol — `commit_outcome`

**C-1 — One writer.** Every authoritative state change is a router transaction. No other module holds store access.
*Source:* DR §5; B *Router* (must never write through another path). *Enforced at:* boundary graph (only `store` may use `sqlite3`; only `router` may import `store`).

**C-2 — Envelope identity.** Each commit request names: operation ID, invocation, payload digest, topic, contract and config revisions, lease and generation, expected state revision, and result/artifact references, within a size bound. Role and authority come from the capability; a caller-supplied role label is rejected, not ignored.
*Source:* DR §5 step 1; B *Router* (never accepts caller-supplied role labels). *Enforced at:* schema `commit-outcome.schema.json` (closed object; no role field can validate); router.

**C-3 — Expensive validation happens outside the write transaction** and is bound to exact artifact hashes plus validator and policy versions.
*Source:* DR §5 step 2.

**C-4 — One short transaction.** Replay-or-reject by operation ID; for a new operation, check lease, generation, execution kind, permissions, contract/config revisions, and pause/restart/amendment state; then atomically record the accepted result and evidence revision, eligible research accounting, the queue transition, release/rest state, holds or retry intent, unique review triggers, the audit event, and any outbox row. A missing or stale lease is detected before any queue mutation.
*Source:* DR §5 steps 3–4; DR §3 (gen-1 detects a stale lease after the queue commit). *Enforced at:* router; DDL uniqueness listed under RG-1a.

**C-5 — The receipt is returned only after commit.** A lost reply is recovered by operation ID.
*Source:* DR §5 step 5.

**C-6 — Distinct transitions.** Research-pass acceptance, scientific sufficiency, operator approval, and topic completion are separate transitions. A successful process implies none of them.
*Source:* DR §5.

**C-7 — Only research passes earn ordinals.** Review, verification, delegate, discovery and checkpoint invocations never increment the ordinary-research ordinal.
*Source:* DR §5. *Enforced at:* DDL `research_ordinals` kind trigger.

**C-8 — No write transaction spans a subprocess or network call.**
*Source:* DR §3 (gen-1 controller holds a write transaction across a subprocess that can take 60 s).

**C-9 — Artifacts are staged, immutable and content-addressed** by trusted station code into a protected spool; the router commits references. Privileged code never opens an agent-selected destination path; uploads are topic-scoped, size-bounded, and immune to symlink traversal.
*Source:* DR §5 ("Artifacts and the sole-writer promise"); B *Station supervisor*.

**C-10 — Router outage.** While the router is unavailable: no new assignments, authoritative evidence changes, or governance effects. Admitted work may finish within its existing deadline and reservation, and the supervisor retains its result. On recovery, durable invocation receipts are reconciled before capacity is reassigned. Late output may be quarantined for explicit reuse but never silently commits under a replacement lease. A full spool or failed durable result write is an infrastructure failure, never a completion.
*Source:* DR §5 ("Router outage").

**C-11 — Recorded history cannot be rewritten through the store's write paths.** No committed receipt, decision, transition, trigger tombstone, observation, verification or quote record, delivery receipt or sink high-water mark can be deleted, replaced or regressed by a statement the store accepts. Four layers: every table has an unconditional `BEFORE DELETE` guard; no constraint carries an `ON CONFLICT` clause; every connection applies `gen2/store/connection.sql` (`foreign_keys`, `recursive_triggers` — without the latter SQLite resolves a REPLACE conflict by deleting the stored row *without* firing its delete guard); and REPLACE conflict resolution is prohibited in store code. Retention/pruning, when it exists, is a separate audited operation that preserves receipts, tombstones and watermarks (DR §5).
*Source:* DR §5; Astra 0a review A1 (added by task 0a-repair). *Enforced at:* DDL delete guards; connection contract; `tools/check_gen2_schemas.py` (every table guarded, no `ON CONFLICT`, pragmas read back); boundary graph (`forbidden_sql`). *Test must show:* `DELETE`, `INSERT OR REPLACE`/`REPLACE INTO`/`UPDATE OR REPLACE` on the primary and every alternate key, and upsert, against a populated store — each attempt raises and a read-back is unchanged; and the same REPLACE succeeds on a connection that skipped the contract (the setting is load-bearing).

---

## 3. Invocation lifecycle

**L-1 — One state machine for all kinds.** States: `admitted`, `launching`, `running`, `result_ready`, `committed`, `cancelled`, `failed`, `outcome_unknown`. Allowed transitions:
- `admitted` → `launching` | `cancelled`
- `launching` → `running` | `failed` | `cancelled` | `outcome_unknown`
- `running` → `result_ready` | `failed` | `cancelled` | `outcome_unknown`
- `result_ready` → `committed` | `failed` | `outcome_unknown`
- `outcome_unknown` → `running` | `result_ready` | `committed` | `failed` | `cancelled` (only through reconciliation)
- `committed`, `cancelled`, `failed` are terminal.

`result_ready → failed` covers a result rejected by `commit_outcome`; the result stays retained (C-10). *Source:* DR §6; B *Station supervisor*. *Enforced at:* DDL `invocations` transition trigger; schema `invocation.schema.json`.

**L-2 — Launch intent is recorded before spawn.** *Source:* DR §5 ("Crash fencing"). *Enforced at:* DDL (`launching` and later states require the launch-intent timestamp).

**L-3 — Process identity is never a bare PID.** It is the invocation/job handle plus host/container identity, boot identity, and process start fingerprint. A crash between spawn and identity record is resolved by idempotent job lookup or by terminating/reconciling the owned execution group, never by PID adoption.
*Source:* DR §5; B *Station supervisor*. *Enforced at:* DDL (`running` requires job handle, host, boot identity and start fingerprint; there is no PID column).

**L-4 — `outcome_unknown` is reconciled, never assumed.** It is not synonymous with vanished, failed, safely retryable, or done. *Source:* DR §6; B *Station supervisor*.

**L-5 — Agent self-reported completion is never accepted.** The supervisor's structural checks and the commit protocol decide what happened. *Source:* F S4 step 7; B *Station supervisor*.

**L-6 — Every retry path consumes a declared attempt/time budget**, including missing-counter recovery, diagnostic repair and infrastructure refunds. Known transient faults retry within budget; suspected semantic faults are diagnosed or revised, not blindly retried. *Source:* DR §6; DR §2 row F95 (scoped to its synthetic-chain setting).

**L-7 — Pause and cancellation** require a final launch-admission check and confirmed descendant handling before capacity is released. Fencing protects commits; it does not claim to kill orphaned computation or undo a dispatched external request. *Source:* DR §5.

**L-8 — Delegates and verifiers run as supervisor-owned jobs** outside the primary harness's child lifetime; submission and reconnect use the same invocation ID. *Source:* DR §6.

**L-9 — Empty output is a structural failure recorded in the observation stream.** A zero-exit empty result is never a silent return code. *Source:* DR §6 (gen-1 delegate wrapper returns 70 and never records it in the activity stream).

---

## 4. Evidence accounting

**E-1 — Zero assessed units yields `unknown` novelty**, never zero novelty. *Source:* DR §8; F S7; B *Evidence accounting*. *Enforced at:* accounting; schema dossier rule-result shape (`unknown` carries no value).

**E-2 — Denominators are durable event-derived inventories.** The station/gateway captures retrieved candidate identities at retrieval time, before any screening; the router persists the events; accounting aggregates them. An agent-written total is never a denominator. Unknown capture means an unknown denominator.
*Source:* F S4 step 2; ADJ (a) G-A2, (b) resolution 7; B *Evidence accounting*. *Enforced at:* DDL `retrieval_events` (rows only from observations with a successful coverage state); accounting.

**E-3 — Four candidate units stay distinct:** retrieved records, deduplicated works/studies, assessed candidates, accepted claims. Overlap across lanes never multiplies evidence. Deduplication removes identity duplicates only; it does not decide semantic novelty or independent experimental origin.
*Source:* F S4 step 2; ADJ (b) resolution 7; DR §8. *Enforced at:* DDL (`retrieval_events`, `works`, `screening_assessments`, `claims`); schema `common.schema.json#/$defs/candidate_unit`.

**E-4 — Failed or partial passes never count as saturation evidence.** Repeating the same search cannot manufacture saturation. *Source:* DR §8; B *Evidence accounting*.

**E-5 — Resource-deferred candidates stay unassessed.** They never become scientific exclusions or zero-novelty observations. *Source:* F S4 step 2; ADJ (d) row 5. *Enforced at:* DDL (deferral is the absence of an assessment row; `screening_assessments` admits no "deferred" decision).

**E-6 — Stopping rules evaluate to `satisfied` / `not_satisfied` / `unknown`, with operands shown**, combined by explicit AND/OR only. No majority voting over heuristics. Conjunctive gates (challenge pass completed, coverage integrity, verification tiers on load-bearing claims) are gates, not votes.
*Source:* F S7; DR §8. *Enforced at:* schema `contract-v2.schema.json` (combination operators are `all`/`any` only; gates are a separate list); accounting.

**E-7 — Arithmetic never certifies meaning.** Novelty, independence and sufficiency are labeled assessments by models or people; the sufficiency ruling is never a model output. *Source:* F S7; DR §8; B *Evidence accounting*.

**E-8 — Legacy topics start with unknown historical denominators.** Nothing is backfilled with invented zeros or reconstructed screening histories. *Source:* DR §8.

**E-9 — Exclusions are reason-coded, framing-versioned and reversible.** A reframe reopens exclusions made under the old framing for re-screening. *Source:* F S4 step 3, §6.5; M §4. *Enforced at:* DDL `screening_assessments` (exclusion requires a reason code; framing version required).

---

## 5. Verification and capture

**V-1 — A verification receipt binds** claim revision, source version, cited spans, obtained content hash, access tier, acquisition and extraction lineage, and producer and verifier invocation identities.
*Source:* F S4 step 8; ADJ (b) resolution 5; B *Verifier*. *Enforced at:* schema `verification-receipt.schema.json`; DDL `verification_receipts`.

**V-2 — Access tiers are ordered and never inflated:** bibliographic < abstract < full_text < reproduced. A verifier never certifies above the tier it obtained; an abstract check never satisfies a full-text requirement. A claim about a table requires the table to have been accessible. Missing required content produces a hold.
*Source:* F S4 step 8; B *Verifier*. *Enforced at:* router; DDL `claims` trigger (accepted support needs a supporting receipt at or above the required tier).

**V-3 — Independence is not a URL count.** Independent re-access may reuse identical canonical transport/cache bytes; it may never reuse the producer's selected summary or unvalidated extraction.
*Source:* F S4 step 8; ADJ (a) K-A2, (b) resolution 5.

**V-4 — Provisional capture may commit before verification; accepted support may not.** A load-bearing disposition becomes accepted support only once the required verification receipt exists. Pending evidence can open a bounded investigation but cannot satisfy a completion gate.
*Source:* F S4 step 9; F §5 (hybrid placement); ADJ (b) resolution 7. *Enforced at:* DDL `claims` trigger.

**V-5 — Disagreement becomes a typed adjudication hold** (class `judgment`, owned by the primary, escalating to the operator at its deadline). It is never averaged.
*Source:* F S4 step 8, §6.6; B *Verifier*.

**V-6 — Exact quote byte-matching precedes NLI.** Quoted bytes are checked against a versioned source artifact with explicit normalization and span offsets. A failed NLI check quarantines the quote (not the source), notifies the capturing pass's owner, and blocks the quote from backing any disposition until it is re-captured or adjudicated.
*Source:* F S4 step 4, §6.7; ADJ (c) 2; B *Tier-0 checker*.

**V-7 — The tier-0 checker screens and alarms; it never promotes.** On observed regression it is re-evaluated, narrowed, or suspended — never auto-tightened. Passed claims are sampled for false passes (numeric, negation, context traps), reported with denominators.
*Source:* F §4.8; ADJ (a) G-A5; B *Tier-0 checker*.

**V-8 — Load-bearing uses get independent checks** of numeric units, denominators, negation, and surrounding qualifications. *Source:* F S4 step 4; ADJ (c) 2.

**V-9 — Three independence properties are recorded separately:** independent checking, independent evidence origins (lineage), and different analytical methods. Two analyses of one study never count as two independent studies.
*Source:* ADJ (b) resolution 5; M §3. *Enforced at:* DDL `claim_source_links` (separate lineage and method columns) and `verification_receipts` (checking).

---

## 6. Decision layer

**D-1 — Every automated decision runs under a full DecisionSpec:** class, provider, resolved model/version, primitive and output semantics, question/rubric version, input-builder version, applicable protocol, action-policy version. Its receipt links inputs, provider response, policy, authorization, action and outcome. The raw response digest and artifact are retained at the trusted station/adapter boundary, outside the interpretation path.
*Source:* F §2, §3 steps 1–2; ADJ (b) resolution 6; B *Decision layer*. *Enforced at:* schemas `decision-spec.schema.json`, `decision-receipt.schema.json`; DDL `decision_receipts`.

**D-2 — The router's policy, not the provider, chooses the action:** commit a reversible action, attach a proposal, escalate, or abstain-hold. A provider answer is never itself a state write. *Source:* F §3 step 3; B *Decision layer* ("It answers; the router's policy acts").

**D-3 — Uncertainty stays provider-specific.** An LLM-fallback label carries no probability, distribution or confidence. A missing confidence field never defaults to a pass. Jev's Noul returns a probability without a separate confidence field; Choice and Score return a distribution plus a derived confidence statistic (the vendor's interface, as recorded in DR §7 — not a calibration claim).
*Source:* F §2; DR §7; ADJ (a) G-A3; B *Decision layer*. *Enforced at:* schema `decision-receipt.schema.json` (answer shape per provider/primitive); DDL `decision_receipts` check.

**D-4 — Qualification is per provider, per class, per DecisionSpec.** It refers to a declared evaluation population and immutable results. Any behavior-affecting change retires it; old labels keep their provenance, and old decisions are never reinterpreted. There is no authority inheritance and no pooled uncertainty across Jev and the fallback. Question tuning never consumes the final held-out set.
*Source:* F §2; ADJ (a) G-A4, K-A6; (b) resolution 6.

**D-5 — Unqualified means advisory at most.** Initial rollout exercises exactly two classes on one logging/evaluation path: screening in shadow, method-selection advisory. Everything else stays with code, primary, or operator.
*Source:* F §5 (Jev rollout row); ADJ (a) K-P1; B *Decision layer*. *Enforced at:* schema and DDL (no qualification reference ⇒ authority is `shadow` or `advisory`).

**D-6 — Oversized, stale, truncated or disallowed input produces an abstention** (which routes up the ladder), never a guess. State-mutating plus low confidence produces a hold. *Source:* F §2.

**D-7 — The engine runs with the decision layer disabled.** Provider outage is a capability fact; scheduling, receipts and cancellation never depend on a model. *Source:* F §2; charter ("Jev is not a build dependency"). *Enforced at:* boundary graph (router may not import `decision`); Phase 1 tests run with it off.

**D-8 — Providers never generate options, re-fetch evidence, write state, or trust prose.** Snapshots are code-assembled typed records with extractive quotes; retrieved text is data, never instructions. A situation outside the offered options is an abstention, and any new option is a primary proposal to the operator. *Source:* B *Decision layer*; F §6.3; M §2 (state integrity).

**D-9 — Blind samples.** A recorded random subset of advisory decisions hides the recommendation; the operator's initial disposition is captured before reveal. Blind labels are stored separately from advised accept/override feedback. Overrides and a sample of accepted decisions are both audited.
*Source:* F §2, §3 step 5; ADJ (a) K-A4.

**D-10 — Deterministic replay audit.** An independent scheduled job, with its own last-success alarm, replays sampled decision receipts against retained raw responses (policy binding, response digest, permitted action, recomputed authority). Missing raw evidence is a control failure. Qualification changes get complete, not sampled, checking.
*Source:* F §3 step 6; ADJ (a) K-A1.

**D-11 — Pre-authority adversarial cases** — altered distributions, mismatched policy versions, fallback without confidence, revoked qualifications, stale question versions — end in rejection or a visible control incident.
*Source:* F §3 step 6; ADJ (b) resolution 6.

**D-12 — Calibration data (override joins, retrospective outcomes, blind labels) lives in the router's store**, never in agent workspaces. *Source:* F §6.8.

---

## 7. Contract, governance, and scope

**G-1 — Contract v2 is hash-locked with its protocol revision.** The lock covers the approved inventory and the eligibility/stopping/applicability protocol. Older revisions and operator decisions are preserved. An amendment identifies affected labels, dossiers, verification and index generations; incompatible results are never silently reused.
*Source:* F S3; DR §4. *Enforced at:* schema `contract-v2.schema.json`; DDL `contract_revisions` (approved rows immutable, no deletes).

**G-2 — Only operator-approved importance ratings authorize later actions.** A Jev score is a proposal. The GRADE-style 1–9 number is an optional elicitation aid atop a required band (critical 7–9 / important 4–6 / limited 1–3) — not a calibrated probability or a validated Jev measurement.
*Source:* F S3; M §2; ADJ (a) G-R9, K-R4. *Enforced at:* schema `contract-v2.schema.json#/$defs/importance`, used by both facets and obligations (separate `proposed` and `operator_rating` fields; band required, score optional and band-consistent); DDL `facets` and `obligations` (band/score checks; each row equals its hash-locked document entry; an operator rating cites an approved `rating_approval` about the earlier, rated revision; a Jev proposal cites a same-topic `importance_score` receipt).

**G-3 — An uncovered critical facet blocks approval** (deterministic check on the coverage matrix). Facet importance is recorded on the facet itself, never inferred from its obligations (that would make the check circular: an untagged facet would have no importance). Structural validity is not semantic adequacy: a well-typed omission remains an omission, and whether facets represent the decision stays with the operator and the fresh-context facet audit.
*Source:* F S1, S3; ADJ (c) 1; Astra 0a review A3. *Enforced at:* DDL — `uncovered_critical_facets` view; approval of a contract revision is refused unless its facet and obligation rows are complete, every facet carries an operator rating, and no critical facet is untagged by an obligation of that revision. *Test must show:* a critical facet with zero obligations is representable (schema fixture and store row) and blocks approval; tagging it lifts the block.

**G-4 — Unconfirmed briefs cannot advance.** A draft brief is a durable intake item with an operator owner, `awaiting_confirmation` state, creation time and review deadline. Expiry marks it overdue — it never advances it. Cancellation or archival is an explicit act.
*Source:* F S1; ADJ (a) G-A8.

**G-5 — Auto-promotion is narrow and revision-bound.** It is allowed only for a sub-question inside an existing facet whose operator-confirmed rating is at or above the declared threshold, bound to the exact approved contract revision and the remaining auto-budget reservation. New facets always require an amendment. Auto-promotions are suspended during a reframe migration.
*Source:* F §6.4; ADJ (a) G-A6, K-A7. *Record the check reads:* the facet's operator rating in DDL `facets` (A3); the promotion mechanism itself is Phase 3.

**G-6 — Reframe migration** versions the facet map, marks affected labels and coverage stale-under-new-framing, reopens exclusions for re-screening, and re-renders synthesis views. No silent reuse, no deletion. *Source:* F §6.5.

**G-7 — "Adjust within family" is self-serve only inside the approved operational envelope.** Any change to eligibility, estimand, required access tier, or stopping interpretation follows the amendment path. Reframes and expansion purposes always go to the operator.
*Source:* F S5; ADJ (c) 4.

**G-8 — Completion approval binds to the exact dossier revision** and goes stale after any material change. *Source:* F S7; DR §8. *Enforced at:* DDL — the completion transition names its decision (`queue_entries.status_decision_id`), which must be an approved `completion_approval` of this topic about the current dossier revision with that dossier's content hash, evaluated under the topic's active, approved contract (G-13).

**G-13 — A decision authorizes only its exact subject.** Every operator decision names a typed subject (one subject kind per decision kind) with its identifying revision and content hash; a stored subject must exist with that exact hash when the decision is recorded. A gated write (contract approval, operator rating, hold clearance, completion, retirement, publication) names the decision it relies on, and that decision must be of the permitted kind, `approved`, of the same topic, and about exactly the subject being written — revision, hash, and (for retirement) the state revision being left. A rejected or deferred decision, a decision of another kind or topic, or one about an earlier revision authorizes nothing, and a decision bound to a state revision cannot be reused. Rows that carry authority cannot be created in a decided/terminal state: topics start at intake, contracts as drafts, holds open (the importer gets its own audited path, 0b).
*Source:* B *Operator*; DR §8; F S3, S7, S8; Astra 0a review A2 (added by task 0a-repair). *Enforced at:* DDL `operator_decisions` (subject shape and existence) and the consuming triggers on `contract_revisions`, `obligations`, `holds`, `queue_entries`, `outbox_events`. *Test must show:* for each gate, near-miss decisions that differ from a valid one in exactly one dimension (kind, disposition, topic, subject revision/hash, currency, the decision named) are each refused, and the valid one is accepted; direct insertion of a decided state is refused.

**G-9 — Outcomes are distinct and recorded:** `completed_with_qualified_conclusions` (always conditional on framing F, coverage C, discovery mechanisms D), `capability_blocked`, `stopped_for_resources` (residual uncertainty stated — never relabeled as saturation), `awaiting_judgment`, `retired`. *Source:* F S7; DR §8; M §6.

**G-10 — Scientific protocol and execution policy are separate data.** Target recall or evidence thresholds belong to the contract; retry ceilings, heartbeats, timeouts, cadence and budgets belong to the mounted engine policy bundle. *Source:* DR §4.

**G-11 — The engine refuses automatic stopping rules it cannot evaluate.** There is no required count of stopping rules. Statistical target recall is enabled only for an identified finite candidate collection with a specified screening procedure (Callaghan & Müller-Hansen 2020, which bounds recall within that pool, not over undiscovered literature). Capture-recapture, VoI/EVPI, SAFE and meaning saturation stay reviewed analyses, not automatic gates.
*Source:* DR §4, §8; M §6; ADJ (a) G-R10. *Enforced at:* schema `contract-v2.schema.json` (the automatic rule set is closed; statistical target recall requires pool and procedure parameters).

**G-12 — Mandatory signals cannot be suppressed.** Retractions and decision-record changes route to mandatory review by code policy; a model score may rank discretionary alerts only. Checkpoint triage may add or prioritize attention but never suppresses a required checkpoint. The fixed-floor cadence plus one coalesced signal queue records every cause and drops none.
*Source:* F S5, S8; DR §7. *Enforced at:* schema `contract-v2.schema.json` (retraction and decision-record-change signals are mandatory and code-triaged).

---

## 8. Publication and surveillance

**P-1 — The router atomically commits the approved publishable revision and an outbox event** referencing an immutable manifest (topic, artifact kind, source revision/hash, approval revision, schema version, expected sinks, supersession identity). Publication receipts are separate, projector-owned records. *Source:* F S8 item 1; ADJ (b) resolution 2. *Enforced at:* schema `publication-manifest.schema.json`; DDL `outbox_events`.

**P-2 — Sink writes are idempotent and generation-aware.** Sinks are named physically (Neo4j, Qdrant), never "GraphRAG". Old retries never overwrite newer generations; supersession and tombstones are acknowledged per sink.
*Source:* F S8 item 2; B *Projector / publication*. *Enforced at:* DDL `sink_generations` (the delivered generation never decreases), `sink_delivery_receipts`.

**P-3 — Readers receive a freshness envelope** (source revision, projected revision, approval status, last successful delivery, pending/failed/unknown status). Every retrieval names its manifest generation; mixed-generation retrieval is detected and either pinned or reported degraded. *Source:* F S8 item 3. *Enforced at:* schema `freshness-envelope.schema.json`.

**P-4 — Three facts, never conflated:** scientific completion at dossier revision R, current publication delivery, surveillance currency as of T. A failed sink leaves publication partial and raises a capability incident; it neither undoes completion nor stops surveillance. *Source:* F S8 item 4.

**P-5 — Approved corrections and approved checkpoint publications create new outbox events.** Unapproved work is never served as accepted evidence; the envelope may disclose that newer unapproved material exists. *Source:* F S8 item 5. *Enforced at:* DDL `outbox_events` — the approval is an approved `publication_approval` of the exact source revision and content hash (G-13), and the manifest JSON's source, approval, kind, sinks and supersession equal the row's columns.

**P-6 — Surveillance liveness alarms on an overdue successful observation**, not on an absence of scientific events. Successful-empty is distinct from failed or never-ran. A dead feed makes currency unknown/degraded without rewriting historical completion. Retirement is an operator decision. *Source:* F S8; ADJ (a) K-A3.

---

## 9. Holds and observability

**H-1 — One invocation ID threads the chain** router → station → delegate → gateway lane → decision layer → commit receipt. *Source:* F §4.1.

**H-2 — Capability facts are first-class, dated, and alert on transition.** A failed secrets read is recorded as "secrets backend failing" with its since-time and affected lanes — never as "no key configured". *Source:* F §4.2; B *Gateway* (the 2026-09-21..24 vault outage is the fixture).

**H-3 — Holds are typed, owned and deadlined.** Cause class (transient / capability / scope / judgment / unknown), recoverability, and required authority are separate fields, plus what clears the hold. A failed hold write is a control failure. A model label never clears an operator hold.
*Source:* F §4.4; DR §6, §7 (separate dimensions for cause, recoverability, authority). *Enforced at:* DDL `holds` (owner, deadline and clearing condition required; created open; operator-authority holds clear only through an approved `hold_clearance` decision about that hold — G-13).

**H-4 — Status answers why every waiting item waits.** *Source:* F §4.4; DR §10 gate 9.

**H-5 — The gateway never turns an unparseable payload into zero results**, never lets two different requests share a request identity, and logs every call with its invocation ID. *Source:* DR §9; B *Gateway*.

---

## 10. Build invariants

**B-1 — The module-boundary graph is enforced in CI from the first commit.** `make gen2-check` fails on any violation (`tools/check_boundaries.py` against `gen2/boundaries.toml`). The research cited for machine-checkable boundaries (Fleet B F76) is weak and confounded (DR §2); no violation rate is promised — this is engineering discipline. *Source:* charter; DR §2, §10.

**B-2 — No gen-2 module imports gen-1 `research_loops` or the gateway's internals (`research_gateway`).** *Source:* task 0a; DR §6. *Enforced at:* boundary graph (`forbidden_imports`).

**B-3 — Size budget:** 10,000 production lines allocated, 12,000 hard ceiling before explicit scope reconsideration. Counted like-for-like with the DR §10 baseline (physical lines of tracked `.py` and `.sh`, blanks and comments included); tests, schemas, SQL, prompts and config are reported separately so functionality cannot hide in excluded file types. *Source:* charter; DR §10. *Enforced at:* `tools/gen2_linecount.py --check` in `make gen2-check`.

**B-4 — No test is accepted without its Gate C verdict.** A green suite is never evidence by itself. *Source:* charter (Gate C).

---

## 11. Gen-1 behaviors that are defects to change — not compatibility targets

Gen-2 does not reproduce these, and migration parity checks exclude them (DR §10: compare mechanical invariants under old-compatible policy; review intentional policy differences separately). Locations are in gen-1 at `7c84325` (the DR checkout; later commits add only gen-2 files, so no gen-1 file has changed since). "Verified" means re-read in this checkout for task 0a; "per DR" means taken from the design review's citations without re-reading.

1. **Split finalization.** The runner does research accounting through `accept_research_completion` (`research_loops/runner.py:1538`), while `QueueStore.finalize_run` mutates the queue inside its locked transaction (`research_loops/queue.py:1790`) and only afterwards retrieves the managed lease (`:1899-1902`), so a missing or stale lease surfaces after state already changed. DR §3's executed probes: an unminted run (station 99, generation −1) was accepted while another run held the lease; reuse of a run ID with a different payload returned the old result without conflict; a handled stall trigger replayed after its episode closed opened a new episode. *Verified* (call sites); probes *per DR*. → C-4, RG-1a, RG-1b.
2. **Silent legacy fallback.** `QueueStore.__init__` uses the managed SQLite store only if `state/control.sqlite3` happens to exist and otherwise silently runs the legacy JSON queue under `flock` (`research_loops/queue.py:171`, `:206-218`); checkpoint scheduling keeps a legacy path for unmigrated queues (`research_loops/runner.py:1309-1311`); process adoption without a fingerprint falls back to command-line matching (`research_loops/runner.py:774-800`). *Verified.* → Gen-2 has one store and one execution path. A missing store is a startup error, not a mode; import is an explicit offline operation outside the runtime path (DR §6).
3. **Filesystem STOP writes as authority.** The chassis treats any `$TOPIC_DIR/STOP` present at start as terminal (`research_loops/chassis/run-topic.sh:121`, exit 3), reads the STOP an iteration wrote (`:307`, `:362-381`), and the queue deletes stale STOPs on requeue (`research_loops/queue.py:1566`). Gen-1 commit `7c84325` ("resume_item actually clears a stale STOP file (it never did)") shows the class in action. *Verified.* → Stop and completion are router transitions over typed proposals (C-6, L-5); no file is authority.
4. **Preflight execution.** The chassis executes a topic-shipped `preflight.sh` (arbitrary topic code) and swallows its failure with `|| true` (`research_loops/chassis/run-topic.sh:67-70`). *Verified.* → Capability probes are supervisor code (B *Station supervisor*); no topic-supplied executables (B *Router*: never executes agent-supplied code; DR §10 cuts arbitrary topic hooks).
5. **Agent-written denominators.** `sources_cited` is the difference of two `semantic-state.py source-count` reads over agent-authored ledger files, and a failed count silently becomes `0` (`research_loops/chassis/run-topic.sh:136`, `:234-235`, `2>/dev/null || echo 0`). Saturation is declared after consecutive unchanged agent-state signatures (`research_loops/runner.py:1031-1035`, `:1612-1625`). *Verified.* → E-2, RG-U, E-4.

Further defects the sources record (all *per DR* unless marked):

6. Three JSON logical documents rewritten on every changed transaction, and a controller write transaction held across a subprocess of up to 60 s (DR §3: `control_store.py:235`, `controller.py:181`). → normalized rows; C-8.
7. Delegate wrapper returns code 70 for zero-exit empty stdout without recording it in the activity stream (DR §6: `chassis/managed-delegate.py:185`). → L-9.
8. A missing counter sends a checkpoint back to `retry_wait` without consuming an attempt budget (DR §6: `checkpoints/service.py:628`). → L-6, RG-3.
9. The research-activity summarizer returns an empty structure for absent/unreadable activity, ignores malformed lines, and keeps only the latest per-source state (DR §3: `chassis/research_activity.py:28`). → RG-4, E-2.
10. Gateway: invalid JSON becomes `None` at the response helper (`adapters/base.py:49`); two searches differing in kind and cursor share one request subject (`clients/mcp_stdio.py:174`); breaker sequence advances before persistence and callback errors are swallowed (`app.py:184`, `core/broker.py:139`); restart usage seeding excludes refused dispatches (`app.py:129`); SIGTERM unhandled (`api/http.py:207`); topic policy enforced only client-side (`clients/mcp_stdio.py:131`); DB source loading omits license/freshness fields (`app.py:154`); `auth_failed` covers "not configured at all" (`gateway/docs/STATION-CONTRACT.md` §2 — *verified*). (DR §9.) → H-2, H-5, RG-7.
11. External GraphRAG ingest: completion recognized only when every obligation is supported, verification parsed by substring, dotted IDs missed by regex, Qdrant and Neo4j written separately (DR §9: `~/bin/research-loops-graphrag-ingest:65`). → P-1–P-4.
12. The privileged semantic-state subprocess bridge and agent-writable authoritative files generally (DR §6). → C-1, C-9.

---

## 12. What migration must preserve

Import preserves contract and citation identity, operator decisions and holds, queue priority, accepted ordinals, handled triggers, outstanding review episodes, consumed budgets, capability blockers, artifacts, publication state, and available usage history. Unavailable or pruned history is imported as unknown, never as zero (RG-U, E-8). Host PIDs are never adopted across the cutover (L-3). After new writes, rollback means reconciliation or repair-forward, not restoring a stale database over new operator decisions. *Source:* DR §10 (Phase 4 and migration paragraph). The dry-run importer (task 0b) is the first code bound by this section.
