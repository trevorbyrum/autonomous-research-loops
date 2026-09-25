# Gen-2 store — DDL draft

`schema.sql` is the draft DDL for the one authoritative engine store (task 0a deliverable 3). It is not wired to any code yet. The router is its only writer: in `gen2/boundaries.toml` only the `store` module may use `sqlite3`, and only `router` may import `store`.

**Connection contract.** `connection.sql` holds the per-connection settings the schema's guarantees depend on: `foreign_keys = ON` and `recursive_triggers = ON`. Every connection (the Phase 0b store module, the tests, `tools/check_gen2_schemas.py`) applies it before the DDL and reads both pragmas back. Without `recursive_triggers`, SQLite resolves a REPLACE conflict by deleting the stored row without firing its delete guard; `gen2/tests/test_store_history.py` demonstrates that bypass on a connection that skipped the contract.

**Traceability.** Every table carries a `-- trace:` comment naming the flow-doc section, design-review section, BOUNDARIES.md entry and `docs/gen2/INVARIANTS.md` IDs it implements. `make gen2-check` enforces that the comment exists, that the DDL executes, that every table is STRICT and has an unconditional delete guard, that no constraint has an `ON CONFLICT` clause, and that every foreign key targets a real key. The `gen2/tests/test_store_*.py` suites show each constraint rejecting its violation (and, where the test says so, accepting the same write without it). `make gen2-mutation` (part of `gen2-check`) removes each guard in memory and confirms its named tests fail — the inventory is `tools/gen2_mutations.py`.

## How the brief's table list maps to the DDL

- Contract revisions and obligations → `contract_revisions`, `facets` (facet importance in its own right, A3), `obligations`, and the `uncovered_critical_facets` view (G-3)
- Queue entries → `queue_entries`
- Invocations and leases → `invocations`, `invocation_transitions`, `leases`
- Review episodes and triggers → `review_episodes`, `review_triggers`
- Evidence observations and assessments, including the retrieval-event inventory with its four candidate units:
  - `search_observations`
  - unit 1 (retrieved records): `retrieval_events`
  - unit 2 (deduplicated works): `works` + `record_work_links`
  - unit 3 (assessed candidates): `screening_assessments`
  - unit 4 (accepted claims): `claims` with status `accepted_support`
  - plus `claim_source_links`, `verification_receipts`, `quote_checks`
- Operator decisions → `operator_decisions`
- Operation receipts → `operation_receipts`, `research_ordinals`
- Decision receipts → `decision_receipts`
- Outbox events and per-sink delivery receipts → `outbox_events`, `sink_delivery_receipts`, `sink_generations` (the per-sink high-water mark)
- Holds → `holds`

**Supporting tables not named in the brief:**
- `artifacts`, `dossiers`, `decision_specs`, `audit_events` exist because listed tables reference them. Completion approvals bind to a dossier revision; decision receipts bind to an immutable spec; step 4 of `commit_outcome` records an audit event; content is referenced by hash.
- `capability_facts` is a **deviation proposal**. Flow §4.2 and BOUNDARIES.md *Gateway* make dated capability facts first-class. Capability holds and failed secrets reads (`search_observations.error_class = 'secrets_backend_failing'`) reference one. Remove it, and those two checks, if the proposal is rejected.

## What the DDL enforces

- **History cannot be rewritten** (C-11): every table rejects DELETE; REPLACE (`INSERT OR REPLACE`, `REPLACE INTO`, `UPDATE OR REPLACE`) aborts on the delete guard of the row it would displace; append-only tables reject every UPDATE; the boundary lint rejects REPLACE in store code.
- **One writer's fencing** (RG-1a, RG-1b):
  - operation ID is the primary key and receipts are immutable
  - one `final_outcome` per invocation
  - one commit per produced state revision
  - `state_revision` advances by exactly one
  - a commit's lease must be the invocation's (a delegate's parent's), live, of the same topic and generation
  - one live lease per (topic, scope), generations strictly increasing per topic, release write-once
  - ordinals only for research-pass final outcomes, dense, one per invocation
  - review-trigger identities unique, never deleted, handled-is-final
- **Admission** (C-12, A4): every invocation pins `contract/1` (an approved revision) or `pre-contract/1` (a confirmed brief; discovery/delegate/research_pass; only before any approved contract); receipts carry exactly their invocation's pins and config; pre-contract receipts earn no ordinal.
- **Leases and parentage** (L-8, R2.1, R2.2): a non-delegate owns one live lease of its topic and kind's scope; one owner per lease; delegates run under a running non-delegate parent of their topic with its pins; only delegates have a controlling parent; a causal requester is of the same topic.
- **Lifecycle** (L-1–L-3):
  - invocations are inserted `admitted` and move only along the L-1 transitions
  - launch intent (with the stable job handle) is required from `launching` on
  - leaving `outcome_unknown` needs a reconciliation record of that episode supporting the target (L-4)
  - `running` requires job handle, host, boot identity and start fingerprint; there is no PID column
  - identity, admission/config pins, and observed process identity (host and container included) are write-once
- **Unknown is not zero** (RG-4, RG-U):
  - result counts exist only for `searched_ok` / `searched_empty` / `metadata_only`
  - degraded coverage states need an error class
  - retrieval events come only from successful searches
- **Verification** (RG-5, V-2, V-4):
  - producer ≠ verifier
  - the verifier is a `verification` invocation of the same topic with no controlling parent (it may be *requested by* the producer — R2.2) and names the claim's real producer
  - no reliance on the producer's selected or unvalidated extraction; authenticated canonical bytes (gateway-call reference + staged artifact with the obtained hash) may be reused whoever acquired them
  - `supports` needs successful numeric/denominator/negation/qualification checks and no tier-0 alarm, or an explicit adjudication; load-bearing support verdicts cannot rest on unperformed/unavailable checks; truthful unsuccessful verdicts may report them
  - the receipt binds its exact quote check (claim revision, source artifact, match status) and never supports on a quarantined quote without an adjudicated NLI alarm; it names the verifier's own capability; every normalized column equals its receipt-JSON field
  - `supports` never exceeds the obtained tier
  - load-bearing claims reach `accepted_support` only with a supporting receipt at the required tier
  - claims start provisional
- **Decisions** (D-3, D-5):
  - a fallback answer carries no probability, distribution or confidence
  - Choice/Score require a confidence
  - Noul has a probability and no confidence
  - no qualification means shadow or advisory
  - only qualified authority commits
  - shadow does nothing
  - bad input is never answered
  - shadow/advisory providers never write authoritative screening rows; a provider assessment is exactly its qualified screening receipt's committed action (same invocation, commit, work)
  - the action fixes the outcome shape (shadow: no effect; commit/proposal/hold fields belong to exactly their action)
  - raw response bytes are a retained artifact whenever a response exists (answered or abstained)
  - a receipt matches its spec's provider, class, primitive, action policy, options and protocol topic; spec options are keyed by id; screening/method-selection specs name their protocol
  - every normalized receipt/spec column equals its JSON field; observations and assessments bind their invocation's/operation's topic (A10)
- **Governance** (G-1, G-2, G-8, G-13):
  - contract content is immutable, never deleted, and hash-bound to its row; revisions are written as drafts
  - one approved revision per topic; approval names an approved contract/amendment/reframe decision about that exact revision and hash
  - every operator decision names a typed subject that must exist (when stored here) with that exact revision and hash
  - facet and obligation rows each equal their entry in the hash-locked document; obligations tag only facets of their revision
  - operator ratings (facet and obligation) are band-consistent, a score needs a band, and the rating cites an approved rating decision about an earlier revision of the same topic (the rated draft); a Jev proposal cites that topic's `importance_score` receipt
  - approval needs complete facet/obligation rows, every facet operator-rated, and no critical facet untagged by an obligation (G-3)
  - topics are created at intake (revision 0); every status change is a commit (+1 revision)
  - completion names an approved completion approval of the current dossier revision and hash, under the active approved contract
  - retirement names an approved retirement decision made at the state revision being left (so it cannot be reused)
- **Holds** (H-3): owner, deadline and clearing condition are required; capability holds cite a fact; holds are created open; operator-authority holds clear only through an approved `hold_clearance` about that hold; clearing is final.
- **Publication** (P-1, P-2, P-5): the outbox approval is an approved `publication_approval` of the exact source revision and hash; the manifest JSON's source, approval, kind, sinks and supersession equal its columns; generations strictly increase per topic; manifests are immutable; delivery receipts only for expected sinks; a sink's delivered generation never decreases.

## What stays router logic (not expressible, or deliberately not in DDL)

- **Replay vs conflict on operation-ID reuse.** This compares `request_fingerprint`; the DDL only guarantees the ID cannot be committed twice.
- **The compare-and-set on `expected_state_revision`** (`UPDATE … WHERE state_revision = ?`); the DDL guarantees only +1 steps and one commit per revision.
- **Authority from capability**, payload validation and the step-2 validation binding.
- **Deterministic contract-approval checks the DDL cannot see:** template slot completeness, framework-link and decision-record references, coverage-matrix cell consistency. (Facet coverage by obligations, facet referential integrity and rating completeness are DDL, above.)
- **Stopping-rule evaluation and dossier assembly** (accounting); freshness-envelope computation (projector).
- **Byte-level quote matching and normalization;** tier-0 invocation.
- **Operational behavior:** transition alerts on capability facts, hold deadline escalation, verification capacity reservation, retry budgets.
- **Consistency of the JSON documents beyond their bound fields**, and timestamp format — validated against `gen2/schema/` at the router boundary.
- **Semantic comparisons the DDL cannot make (A10) — router contract, to be tested before these rows feed accounting (Phase 1/2):**
  - a search observation's `result_count` against the retrieval events actually captured for it (complete / partial / unknown capture kept distinct from zero);
  - a screening receipt's selected option against the assessment's include/exclude/borderline decision, and its criterion results against the eligibility protocol version;
  - a DecisionSpec's question/rubric/input-builder versions against the registry (question registry: format frozen in 0, loaded in Phase 1 — ruling R3);
  - qualification references against the qualification registry (spec'd in 0, fake-exercised in Phase 1, real in Phase 3 — ruling R3); a non-null `qualification_ref` string is not qualification;
  - payload digests against staged bytes, and artifact sizes/media types against the spool;
  - verification-receipt spans against the quote check's span offsets, and the obtained tier against what the acquisition route can deliver.

## Intentionally deferred

- **Intake briefs** as durable items (flow S1: owner, `awaiting_confirmation`, deadline); for now contracts reference the confirmed brief by ID/version.
- **Research-state views:** branch registry, contradiction ledger, claim graph and synthesis views (methodology §5).
- **Surveillance feed liveness state** (flow S8: due time, last successful poll, cursor, result class, owner).
- **Decision-layer registries:** the question registry, qualification records with evaluation populations, and a dedicated blind-label store. Blind initial dispositions and advised feedback are currently separate `operator_decisions` kinds.
- **Engine policy bookkeeping:** the config-bundle registry, protected-exploration and auto-promotion budget reservations, and signal-queue budget/cooldown.
- **Import provenance columns and the import path for historical invocations** (task 0b). The `admitted`-only insert rule means the importer needs an explicit path.
- **Retention and pruning policy.** No row can be deleted through any write path today (every table has a delete guard, and REPLACE is aborted by it on a contract-conforming connection). A future retention policy is a separate, audited operation — not an ordinary write path — and must preserve receipts, trigger tombstones and sink watermarks (design review §5; INVARIANTS C-11).
- **Operational schema concerns:** query indexes beyond uniqueness, and a migration mechanism beyond `PRAGMA user_version`.
- **Out of scope for this store:** the gateway's budget/cache database stays the gateway's; transcripts stay in the spool, not SQL rows.

## Interpretations to confirm

These are choices this draft made where the sources leave room. Each is easy to reverse.

1. **Lease scopes — ruled (R2.1, MODIFY/ACCEPT).** Research, discovery, verification and checkpoint leases coexist, one live lease per (topic, scope). Each non-delegate owns exactly one lease of its kind's scope, live and of its topic when admitted; delegates inherit the parent's lease. A commit is fenced by *its own* lease's generation, so a newer verification lease never invalidates an unreleased research lease. "Live" in this DDL means unreleased — expiry, deadlines, station/resource accounting, conservative scheduling and amendment invalidation are Phase 1 router work, proven there with stale-result/cancel/reservation tests.
2. **Verifier independence — ruled (R2.2, blanket parent rule REJECTED).** `parent_invocation_id` is control/reservation parentage only (delegates); a verifier never has one, so a producer cannot launch or control it. `requested_by_invocation_id` is the causal link and may name the producer: supervisor-created verification requested by the producing pass is accepted.
3. **Byte-mismatch quarantine — ruled (R2.3, ACCEPT).** An exact-quote mismatch quarantines the quote, like an NLI alarm; tested directly (D32 rewrite). Re-capture and adjudication stay explicit: an adjudication can resolve an alarm, never a mismatch.
4. **Process identity — ruled (R2.4, MODIFY).** Identity is required while `running`; a never-observed job may be recovered through its authenticated stable handle (recorded with the launch intent) and retained result without one; every identity field once observed, host and container included, is write-once in all later states. Leaving `outcome_unknown` needs the durable `invocation_reconciliations` record of that episode (method, evidence, digest found, descendant confirmation) — a result digest alone is neither reconciliation nor descendant-cleanup evidence. Process/descendant recovery itself is Phase 1.
5. **Queue status, claim status, reason-code and error-class vocabularies are drafts.**
7. **Facet coverage (A3).** Any obligation of the revision that tags a facet covers it, exploratory ones included; approval requires every facet to carry an operator rating (flow S3: ratings are approved with the framework, set and method design); an operator rating cites a `rating_approval` whose subject is an *earlier* revision (the draft the operator rated) because the rated revision's own hash covers the rating.
6. **Canonical form for content hashes** (contract `content_hash`, `request_fingerprint`, `spec_hash`, `payload_digest`) is open: RFC 8785 JCS, or a stdlib-reproducible subset such as sorted keys, compact separators and integer-only numbers.
