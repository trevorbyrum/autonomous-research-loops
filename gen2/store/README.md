# Gen-2 store — DDL draft

`schema.sql` is the draft DDL for the one authoritative engine store (task 0a deliverable 3). It is not wired to any code yet. The router is its only writer: in `gen2/boundaries.toml` only the `store` module may use `sqlite3`, and only `router` may import `store`.

**Connection contract.** `connection.sql` holds the per-connection settings the schema's guarantees depend on: `foreign_keys = ON` and `recursive_triggers = ON`. Every connection (the Phase 0b store module, the tests, `tools/check_gen2_schemas.py`) applies it before the DDL and reads both pragmas back. Without `recursive_triggers`, SQLite resolves a REPLACE conflict by deleting the stored row without firing its delete guard; `gen2/tests/test_store_history.py` demonstrates that bypass on a connection that skipped the contract.

**Traceability.** Every table carries a `-- trace:` comment naming the flow-doc section, design-review section, BOUNDARIES.md entry and `docs/gen2/INVARIANTS.md` IDs it implements. `make gen2-check` enforces that the comment exists, that the DDL executes, that every table is STRICT and has an unconditional delete guard, that no constraint has an `ON CONFLICT` clause, and that every foreign key targets a real key. The `gen2/tests/test_store_*.py` suites show each constraint rejecting its violation (and, where the test says so, accepting the same write without it). `make gen2-mutation` (part of `gen2-check`) removes each guard in memory and confirms its named tests fail — the inventory is `tools/gen2_mutations.py`.

## How the brief's table list maps to the DDL

- Contract revisions and obligations → `contract_revisions`, `obligations`
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
- **Lifecycle** (L-1–L-3):
  - invocations are inserted `admitted` and move only along the L-1 transitions
  - launch intent is required from `launching` on
  - `running` requires job handle, host, boot identity and start fingerprint; there is no PID column
  - identity fields are write-once
- **Unknown is not zero** (RG-4, RG-U):
  - result counts exist only for `searched_ok` / `searched_empty` / `metadata_only`
  - degraded coverage states need an error class
  - retrieval events come only from successful searches
- **Verification** (RG-5, V-2, V-4):
  - producer ≠ verifier
  - the verifier is a `verification` invocation of the same topic, not launched by the producer, and names the claim's real producer
  - no reliance on the producer's unvalidated extraction
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
  - shadow/advisory providers never write authoritative screening rows
- **Governance** (G-1, G-2, G-8):
  - contract content is immutable, never deleted, and hash-bound to its row
  - one approved revision per topic
  - operator ratings are band-consistent, and a score needs a band
  - completion requires approval of the current dossier revision
  - retirement requires an operator decision
- **Holds** (H-3): owner, deadline and clearing condition are required; capability holds cite a fact; operator-authority holds clear only through an operator decision; clearing is final.
- **Publication** (P-1, P-2, P-5): only approved work gets an outbox event; generations strictly increase per topic; manifests are immutable; delivery receipts only for expected sinks; a sink's delivered generation never decreases.

## What stays router logic (not expressible, or deliberately not in DDL)

- **Replay vs conflict on operation-ID reuse.** This compares `request_fingerprint`; the DDL only guarantees the ID cannot be committed twice.
- **The compare-and-set on `expected_state_revision`** (`UPDATE … WHERE state_revision = ?`); the DDL guarantees only +1 steps and one commit per revision.
- **Authority from capability**, payload validation and the step-2 validation binding.
- **Deterministic contract-approval checks:** referential consistency, template slot completeness, no uncovered critical facet.
- **Stopping-rule evaluation and dossier assembly** (accounting); freshness-envelope computation (projector).
- **Byte-level quote matching and normalization;** tier-0 invocation.
- **Operational behavior:** transition alerts on capability facts, hold deadline escalation, verification capacity reservation, retry budgets.
- **Consistency of the JSON documents beyond their key fields**, and timestamp format — validated against `gen2/schema/` at the router boundary.

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

1. **Lease scopes.** Research, discovery, verification and checkpoint leases are separate, with one live lease per (topic, scope), so verification can run beside research. The sources say "fenced lease" per pass but do not settle concurrency across kinds.
2. **A verification invocation launched by the producer is refused.** This is a stricter reading of "never the producer's invocation" (BOUNDARIES.md *Verifier*).
3. **An exact-quote mismatch quarantines the quote.** The sources state quarantine for NLI alarms; this draft applies it to byte mismatches too.
4. **Process identity is required only while `running`.** A job reconciled from `outcome_unknown` may already have exited; later states require the retained result.
5. **Queue status, claim status, reason-code and error-class vocabularies are drafts.**
6. **Canonical form for content hashes** (contract `content_hash`, `request_fingerprint`, `spec_hash`, `payload_digest`) is open: RFC 8785 JCS, or a stdlib-reproducible subset such as sorted keys, compact separators and integer-only numbers.
