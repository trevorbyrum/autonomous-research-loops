# Gen-2 store — DDL draft

`schema.sql` is the draft DDL for the one authoritative engine store (task 0a deliverable 3). The router is its only writer: in `gen2/boundaries.toml` only the `store` module may use `sqlite3`, and only `router` may import `store`.

**Writing a store (task 0b).** `api.py` (`open_store` → `Store`) holds the read/write primitives: `insert`, `update` (exactly one row, with optional compare-and-set conditions), `advance` (compare-and-set +1), `next_in_sequence`, `select`, all inside the Store's own `transaction()` (BEGIN IMMEDIATE … COMMIT). A failure anywhere in it, a COMMIT refused by a deferred foreign key included, leaves nothing written; if ROLLBACK itself fails, the connection is closed and the Store refuses further use (Astra 0b review A1). A `Store` comes only from `open_store` (a durable store, through `db.connect`) or `adopt_in_memory` (an in-memory connection a test fixture built, through the same compatibility gate and schema-identity check); the constructor admits nothing else (A4). Before any SQL runs, every JSON column is stored as its RFC 8785 JCS serialization via `gen2/core/canonical.py`, whether the caller passed a value or text. Every identity/revision/generation/counter column goes through `canonical.identity_integer` ([0, 2^53−1] by value, RA8), and so does every value `advance`/`next_in_sequence` generates. Other integers stay within ±(2^53−1). Table and column names come only from the opened schema. The DDL's own refusals propagate unchanged, and nothing is retried or REPLACEd. Routing, `commit_outcome` and decisions are Phase 1.

**Opening a store (task 0b).** `db.py` is the only way a durable store is created or opened. It runs the SQLite compatibility gate (`compat.py`: numeric version floor 3.45.1, JSON functions answering correctly, connection pragmas read back) before the path is touched, then again on the durable connection. It refuses a missing store (no implicit creation), and it admits an existing store only if its schema is exactly this DDL. A refusal is a dated capability fact (`StoreCompatibilityError.fact`), not a fallback. `docs/gen2/ENVIRONMENT.md` describes the gate, and `make gen2-sqlite` runs it in the build.

**Connection contract.** `connection.sql` holds the per-connection settings the schema's guarantees depend on: `foreign_keys = ON` and `recursive_triggers = ON`. Every connection (the store module through `compat.apply_connection_contract`, the tests, `tools/check_gen2_schemas.py` through the same function) applies it before the DDL and reads both pragmas back. Without `recursive_triggers`, SQLite resolves a REPLACE conflict by deleting the stored row without firing its delete guard; `gen2/tests/test_store_history.py` demonstrates that bypass on a connection that skipped the contract. Supported SQLite: 3.45.1, the only version this DDL has been run on (floor and feature minimums: `docs/gen2/ENVIRONMENT.md`).

**Traceability.** Every table carries a `-- trace:` comment naming the flow-doc section, design-review section, BOUNDARIES.md entry and `docs/gen2/INVARIANTS.md` IDs it implements. `make gen2-check` enforces that the comment exists, that the DDL executes, that every table is STRICT and has an unconditional delete guard, that no constraint has an `ON CONFLICT` clause, and that every foreign key targets a real key. The `gen2/tests/test_store_*.py` suites show each constraint rejecting its violation (and, where the test says so, accepting the same write without it). `make gen2-mutation` (part of `gen2-check`) removes each guard in memory and confirms its named tests fail — the inventory is `tools/gen2_mutations.py`. `make gen2-trigger-order` (also part of `gen2-check`) re-creates every trigger in reverse order and requires the whole store suite to produce the same outcome for every test and subtest. Where several guards refuse one write, which message SQLite reports is trigger order, and no assertion may depend on it.

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
- Outbox events (one per export manifest) and per-connector delivery receipts → `outbox_events`, `export_delivery_receipts`, `connector_watermarks` (the per-connector high-water mark) — the one outbound path (operator ruling 2026-09-26; `docs/gen2/EXPORT-API.md`)
- Holds → `holds`

**Added in 1c:** how an invocation ended. `invocations.failure_class` is a closed list of the supervisor's structural findings, only on a failed row; `end_evidence_ref` names the supervisor's execution record (an artifact), only on a failed or cancelled row; `'supervisor'` may request a cancellation; the cancellation request, descendant confirmation, failure class and end evidence are write-once. `holds.cleared_by_reconciliation_id` lets an `outcome_unknown` episode's router hold (subject `invocation:<id>#unknown:<episode>`) be cleared by that episode's reconciliation record and by nothing else (`holds_reconciliation_clears_its_episode`), and such a hold clears only through a reconciliation record — no decision or operation clears it (`holds_episode_cleared_only_by_reconciliation`, task 1c-repair A7). `invocation_reconciliations.request` keeps a reconciliation's complete normalized request (its first four facts agree with the columns) and `invocation_transitions.facts` the facts a lifecycle transition recorded, so a replay is compared with every fact (A8). `artifact_topics` records which topics may reference an artifact (A6, below). Tests: `gen2/tests/test_store_supervision.py`.

**Added in 1d:** the engine's configuration and registries (`gen2/router/registries.py`, `amendments.py`, `scheduling.py`). `config_bundles` records every activated `config-bundle/1` document under its JCS hash, one active, and `invocations.config_bundle_hash` references it, so every pin resolves. `questions` is the question registry, one content per (id, version), each the entry of the bundle registering it; a DecisionSpec can be stored only with a registered question under exactly its hash. `qualifications` holds the Phase 1 fake qualification records and their revocation; a decision receipt at qualified authority needs a live one of exactly its spec. `reservations` and `reservation_draws` hold protected-exploration and auto-promotion reservations and the admissions drawn on them. `retries` holds re-queues of failed or cancelled work. `amendment_impacts` holds the G-1 impact record of each approval that supersedes a contract revision or a confirmed brief version. And a trigger joins only a review episode of its own topic. Tests: `gen2/tests/test_store_registries.py`.

**Added in 0b:** `intake_briefs` holds the durable, versioned Intake Brief rows (flow S1; INVARIANTS G-4, §13). The document is `intake-brief.schema.json`. Owner, review deadline, status, overdue marking, confirmation and cancellation belong to the row's lifecycle and are not document fields.

**Supporting tables not named in the brief:**
- `artifacts`, `dossiers`, `decision_specs`, `audit_events` exist because listed tables reference them. Completion approvals bind to a dossier revision; decision receipts bind to an immutable spec; step 4 of `commit_outcome` records an audit event; content is referenced by hash.
- `artifact_topics` (task 1c-repair, Astra 1c review A6): an `artifacts` row is the physical record of its bytes, shared by every topic that staged them; which topics may reference it is recorded here, one write-once row per (artifact, topic), inserted only by that topic's own invocation (DDL). The router records a topic's row when bytes staged in that topic's spool are recorded by its commit or evidence, and resolves a reference to already-recorded bytes only through it: content identity is not topic authorization (C-9, Q6 ruling).
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
- **Admission** (C-12, A4): every invocation pins `contract/1` (an approved revision) or `pre-contract/1` (a confirmed brief; discovery/delegate/research_pass; only before any approved contract); receipts carry exactly their invocation's pins and config; pre-contract receipts earn no ordinal. Scientific rows need the approved protocol, not just a contract foreign key (RA3): a screening assessment is recorded by a commit of contract-admitted work pinned to exactly the revision it names (and assessed by work with that pin), with that revision's framing and eligibility-protocol versions; a claim-source link is for a claim of its topic produced by work pinned to the revision whose obligation it names; a dossier is evaluated against a revision that passed approval, current or since superseded (RA3-R: its approving decision is recorded only by the draft → approved update, never on a draft alone or by draft → superseded). Scoping (observations, retrieval events, works, provisional claims) stays open to pre-contract work. Accepted support is general, not per consumer (V-10, task 1a): a claim revision reaches `accepted_support` only if contract-admitted work of its own topic produced it, and pre-contract output is adopted by a new revision that contract-admitted work produces.
- **Leases and parentage** (L-8, R2.1, R2.2): a non-delegate owns one live lease of its topic and kind's scope; one owner per lease; delegates run under a running non-delegate parent of their topic with its pins; only delegates have a controlling parent; a causal requester is of the same topic.
- **Lifecycle** (L-1–L-3):
  - invocations are inserted `admitted` and move only along the L-1 transitions
  - launch intent (with the stable job handle) is required from `launching` on
  - leaving `outcome_unknown` needs a reconciliation record of that episode supporting the target (L-4); each episode has its own identity (`unknown_episode`, the next number on every entry), and neither it nor the episode's start time can change afterwards, so a rewound timestamp or a re-entry at a reused one never reuses an earlier episode's record (RA4)
  - `running` requires job handle, host, boot identity and start fingerprint; there is no PID column
  - identity, admission/config pins, and observed process identity (host and container included) are write-once
- **Unknown is not zero; partial is not complete** (RG-4, RG-U, A11): an observed result set is `complete` or `partial` (records kept, count a lower bound, error class says why); a degraded search observed none (`unobserved`); `searched_empty` is only complete.
- **Unknown is not zero** (RG-4, RG-U):
  - result counts exist only for `searched_ok` / `searched_empty` / `metadata_only`
  - degraded coverage states need an error class
  - retrieval events come only from successful searches
- **Verification** (RG-5, V-2, V-4, V-10):
  - producer ≠ verifier
  - the verifier is a `verification` invocation of the same topic with no controlling parent (it may be *requested by* the producer — R2.2) and names the claim's real producer
  - no reliance on the producer's selected or unvalidated extraction; authenticated canonical bytes (gateway-call reference + staged artifact with the obtained hash) may be reused whoever acquired them
  - `supports` needs successful numeric/denominator/negation/qualification checks and no tier-0 alarm, or an explicit adjudication; load-bearing support verdicts cannot rest on unperformed/unavailable checks; truthful unsuccessful verdicts may report them
  - the receipt binds its exact quote check (claim revision, source artifact, match status) and never supports on a quarantined quote without an adjudicated NLI alarm; it names the verifier's own capability; every normalized column equals its receipt-JSON field
  - `supports` never exceeds the obtained tier
  - load-bearing claims reach `accepted_support` only with a supporting receipt requested for load-bearing use at the claim's *own* stored required tier, with every substantive check performed (re-read from the receipt JSON at promotion); a sampling receipt never qualifies and no adjudication waives an unperformed check (RA5)
  - a load-bearing-use receipt states its claim's own designation (the claim is load-bearing; the required tier is the claim's); a sampled receipt may audit any claim at any tier
  - every claim, load-bearing or not, reaches `accepted_support` (from provisional or contested) only if contract-admitted work of its own topic produced that revision — a condition independent of the receipt (V-10, task 1a); a scoping claim is adopted by a new revision produced by contract-admitted work, and the scoping revision stays unpromotable
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
  - contract content is immutable, never deleted, and hash-bound to its row; revisions are written as drafts; a draft moves only to approved, and superseded is reached only from approved (0a-repair-3 ruling 1: the unreachable draft → superseded edge is gone from the status machine); a parent is a strictly earlier revision of the topic, so the parent chain is proper ancestry — no self-parent, no cycle (RA2-R)
  - one approved revision per topic; approval names an approved contract/amendment/reframe decision about that exact revision and hash, recorded only by the draft → approved update itself (whose gate runs in the same statement) and never changed after — so a retained approving decision is evidence the revision passed approval (RA3-R)
  - every operator decision names a typed subject that must exist (when stored here) with that exact revision and hash
  - facet and obligation rows each equal their entry in the hash-locked document; obligations tag only facets of their revision
  - operator ratings (facet and obligation) are band-consistent and a score needs a band; a Jev proposal cites that topic's `importance_score` receipt
  - a rating is exactly what the operator rated (RA2): the `rating_approval` decision retains its payload (`{"facets": {id: {band, score}}, "obligations": {...}}`, ids drawn from the draft it rates); a rated row cites an approved one of its topic about an *ancestor* draft (parent chain, every parent strictly earlier — so neither the revision carrying it nor an unrelated draft) that defines the same subject exactly as here, with exactly the payload's band and score; unchanged ratings carry forward
  - approval needs complete facet/obligation rows, every facet operator-rated, and no critical facet untagged by an obligation (G-3)
  - topics are created at intake (revision 0); every status change is a commit (+1 revision)
  - completion names an approved completion approval of the current dossier revision and hash, under the active approved contract
  - retirement names an approved retirement decision made at the state revision being left (so it cannot be reused)
  - the authorizing-decision pointer moves only with the status transition it authorizes: a completed or retired topic keeps the decision it used — no swap (even to another valid approval) or clearing without a status change, and a revision bump alone is not one (RA1)
- **One record, one representation** (A10, RA6): wherever a stored JSON document duplicates identity or version fields of its row, each is bound to its twin — commit receipts (every identity/version field; the admission references, joined to the pinned contract hash and brief), decision receipts (every field, and the spec id its hash selects), verification receipts, manifests, DecisionSpecs, contract documents (topic, revision, parent, created_at, hash, protocol revision, framing version) and facet/obligation rows (every duplicated field of their entry). The schema-valid example documents under `gen2/schema/examples/` are stored whole as integration controls (`gen2/tests/test_store_examples.py`).
- **Intake briefs** (G-4, C-12, G-13; 0b):
  - rows are versioned (`parent_version` strictly earlier), and their content, lineage, owner and deadline are immutable (a change is a new version)
  - every version is written `awaiting_confirmation`
  - it moves to `confirmed` only by naming an approved `brief_confirmation` about exactly that topic, brief id, version and hash; the pointer is recorded only by that transition and never changes
  - `cancelled` (from awaiting) and `archived` (from confirmed) record who, when and why
  - `superseded` needs a later version of the same brief
  - terminal versions never change; one confirmed version per topic
  - `overdue_since` is marked once, only on a version awaiting confirmation, and never together with a status change (expiry marks, it never advances)
  - a `brief_confirmation` can be recorded only about a stored brief
  - pre-contract admission pins the topic's currently confirmed version and the decision that confirmed it
  - a topic leaves `awaiting_brief_confirmation` for `scoping` only with a confirmed brief (G-4, structurally)
- **Configuration and registries** (G-10, RG-9, D-1, D-4, D-5, G-5, L-6, G-1; task 1d):
  - a config bundle is recorded active with a version above every recorded one, one active; it never changes, and a superseded one is never reactivated; its document names its version; it carries no registered question version under another content
  - an invocation pins a recorded bundle (foreign key)
  - a question version has one content (primary key), is the entry of the bundle that registers it, and never changes; a DecisionSpec pins a registered version under exactly its hash
  - a qualification is created live, for exactly its spec's provider and class, and revoked once; qualified authority rests on a live qualification of exactly its spec (a non-null reference naming anything else is not qualification)
  - a reservation is opened under its topic's approved revision, sized and thresholded as its bundle declares, one open per purpose, closed once; a draw is by non-delegate work of its topic admitted under exactly the reservation's revision, while that revision is approved and the reservation open, within its units, and for auto-promotion inside a facet whose operator band meets the threshold
  - a re-queue is of a non-delegate invocation of its topic that ended failed or cancelled, one attempt past it, and is claimed once, by an invocation of the same topic and kind
  - an amendment impact is of an approved contract/amendment/reframe approval or brief confirmation of its topic, names its row, and never changes
- **Holds** (H-3): owner, deadline and clearing condition are required; capability holds cite a fact; holds are created open; operator-authority holds clear only through an approved `hold_clearance` about that hold; an `outcome_unknown` episode's router hold clears only through its episode's reconciliation record (L-4); clearing is final.
- **Export** (P-1, P-2, P-5, P-7; operator ruling 2026-09-26): the outbox approval is an approved `publication_approval` of the exact source revision and hash; the manifest JSON's source, approval, kind, ordering pair, bundle hash, connectors and superseded pair equal its columns; ordering pairs (generation, options revision) strictly increase per topic; one generation is one approved revision; a superseded pair is complete and strictly lower; manifests name at least one connector, each of a declared type, and are immutable; delivery receipts only for a connector the manifest names, with its type, and only with the receipt contract's status rules (a failure's class, a delivery's acknowledgement and tombstones, an unknown outcome's cause and reconciliation, a capability fact for every failure and unknown outcome); a delivery receipt is stored whole (the receipt document beside its row), and every column — the written count and hold id included — equals the document's field (task 1b, Astra 1b review A2); the written count keeps the receipt contract's rules (observed, partial or unknown, where unknown has no value and is never zero; a delivery observes its count, a skipped delivery or a failure that applied nothing observes zero, a partial write reports a partial count, an unknown outcome claims no observed count); a receipt's topic and ordering pair are its manifest's, and a hold it names is a recorded hold of that topic; connector ids are well-formed; a connector's watermark never regresses.

## What stays router logic (not expressible, or deliberately not in DDL)

Task 1b built this boundary in `gen2/router/` (the sole writer). Its README lists, item by item, what is enforced there now and what is deferred with its phase.

- **Replay vs conflict on operation-ID reuse.** This compares `request_fingerprint`; the DDL only guarantees the ID cannot be committed twice. *1b: `Router.commit_outcome`.*
- **The compare-and-set on `expected_state_revision`** (`UPDATE … WHERE state_revision = ?`); the DDL guarantees only +1 steps and one commit per revision. *1b.*
- **Authority from capability**, payload validation and the step-2 validation binding. *1b: authority is the router-minted capability; the kind, topic, pins and lease come from the invocation's row.*
- **Deterministic contract-approval checks the DDL cannot see:** template slot completeness, framework-link and decision-record references, coverage-matrix cell consistency. (Facet coverage by obligations, facet referential integrity and rating completeness are DDL, above.)
- **Stopping-rule evaluation and dossier assembly** (accounting); freshness-envelope computation (exporter, from receipts and watermarks).
- **Byte-level quote matching and normalization;** tier-0 invocation.
- **Operational behavior:** transition alerts on capability facts, hold deadline escalation, verification capacity reservation, retry budgets.
- **Consistency of the JSON documents beyond their bound fields** — validated against `gen2/schema/` at the router boundary (*1b: `gen2/router/schemas.py`, checked against the pinned `jsonschema` by `tools/gen2_schema_oracle.py`*).
- **Hash truth (RA6):** that a stored `content_hash`, `spec_hash`, manifest hash, `request_fingerprint` or payload digest is the hash of the stored or staged bytes is recomputed at the router boundary (Phase 1, `gen2/core/canonical.py`); the DDL binds the representations to each other, not to the truth of a hash label. **Timestamps** are validated there as real calendar instants by `gen2/core/instants.py` (the schema's `date-time` format; the pattern alone admits February 31); the DDL stores router-validated text and does not re-validate (A11).
- **Semantic comparisons the DDL cannot make (A10) — router contract, to be tested before these rows feed accounting (Phase 1/2).** *1b enforces the first two (a provider's screening receipt also under a spec whose protocol is the committing invocation's topic, admitted contract revision and hash), payload digests and sizes, and every embedded artifact reference's size and media type against the declaration staged with the commit or the recorded artifact; the rest stay deferred with the phases below and in `gen2/router/README.md`:*
  - a search observation's `result_count` against the retrieval events actually captured for it (complete / partial / unknown capture kept distinct from zero);
  - a screening receipt's selected option against the assessment's include/exclude/borderline decision, and its criterion results against the eligibility protocol version;
  - a DecisionSpec's question against the committing invocation's pinned bundle (1d; the store binds a spec to a registered question); its rubric and input-builder versions against a registry (Phase 3);
  - qualification references against the qualification records (1d fakes, also bound by the DDL; real records Phase 3); a non-null `qualification_ref` string is not qualification;
  - payload digests against staged bytes, and artifact sizes/media types against the spool;
  - verification-receipt spans against the quote check's span offsets, and the obtained tier against what the acquisition route can deliver.

## Intentionally deferred — with the phase that owns each (ruling R3)

Each deferral names its phase, per Astra's ruling R3 (INVARIANTS §13 is the normative list). "Phase 0" items not done in 0a/0a-repair remain Phase 0 work, scheduled by the orchestrator before Phase 1 starts. No deferred registry may be stood in for by treating an arbitrary non-null string as authorization.

- **Intake briefs and confirmation history.** *Phase 0 (0b, done):* `intake_briefs`, whose rules are listed above, is bound to the pre-contract admission context and to the queue's first transition. The import mapping is in the dry-run importer. *Still open, by phase:*
  - *Phase 1 (1d, done):* re-versioning, owner reassignment and deadline extension through the router (`version_brief`: a new immutable version each time), overdue marking on the router's clock (`mark_brief_overdue`), and fencing of in-flight pre-contract work when a newer confirmed version supersedes its pinned one (lineage-only: completes under its pins; content changed — at any confirmation since, even if a later version restores the content — or another brief's lineage now confirmed: fenced; `gen2/router/README.md`, G-1 impact and standing).
  - *Still open:* cancellation and archival through the router (the DDL's explicit acts; 1e's operator surface).
  - *Phase 2:* the real intake conversation and scoping workflow.
- **Surveillance feed liveness.** *Phase 0:* specify the persisted liveness record shape and how unknown history imports (0a-repair fixed the reader-facing vocabulary: `feed_issues` reasons). *Phase 2*, before the first completed topic is claimed current: due time, last successful observation, cursor/coverage, successful-empty vs failed/never-ran, owner, mandatory signal routing. *Phase 3* may only harden and extend it — it cannot be the first point at which dead feeds become visible.
- **Question registry.** *Phase 0:* freeze question IDs/content/version/hash format and the persistence contract (a DecisionSpec already pins `question_id`/`version`/`content_hash`). *Phase 1 (1d, done):* loading (with the config bundle that carries it), pinning (the store binds a spec to a registered version; a commit binds it to the pinned bundle) and restart retention (`questions`), with no provider running. *Phase 3:* live question content, shadow/advisory calls only. No live call precedes an immutable, retrievable question and input-builder version.
- **Qualification / evaluation / blind-label registry.** *Phase 0:* specify the exact binding (provider × class × DecisionSpec), revocation, and "no qualification ⇒ no automated authority" (the DDL today: no `qualification_ref` ⇒ shadow/advisory; a non-null ref is *not* proof of qualification). *Phase 1 (1d, done):* fake qualification/revocation records exercise the authority fences (`qualifications`, router and DDL). *Phase 3:* immutable evaluations, population provenance, blind-exposure history and a complete qualification-change audit, before any promotion. Phase 2 runs with the decision layer disabled. Blind initial dispositions and advised feedback are separate `operator_decisions` kinds until the blind-label store exists.
- **Config/admission pins and reservations.** Admission pins exist (0a-repair); the config-bundle registry, protected-exploration and auto-promotion budget reservations, and signal-queue budget/cooldown are *Phase 1 (1d, done)*. The promotion mechanism that draws on an auto-promotion reservation is *Phase 3*.
- **Research-state views** (branch registry, contradiction ledger, claim graph, synthesis views — methodology §5) and **trustworthy denominators** (retrieved-count vs captured-inventory reconciliation, above): *before Phase 2 stopping* evaluates anything.
- **Export and automation** (operator ruling 2026-09-26): when the router commits a manifest (an approved revision while a connector is enabled; a new options revision on a configuration change), full-snapshot vs delta export (a later manifest may currently omit supersession), connector-side fencing, qualified automation — *Phase 3*. (The whole receipt document and advancing a watermark only from a delivered receipt landed with the router's `ack_delivery` in task 1b.)
- **Import provenance columns and the import path for historical rows** — *Phase 0 (0b)* dry-run importer; reconciled import and single-writer canary — *Phase 4*. The admitted-only invocation insert, intake-only topic creation, awaiting-only brief creation, draft-only contract creation and open-only hold creation mean the importer needs its own explicit, audited path (the 0b dry-run importer reports that mapping; it writes nothing).
  - *Before any dry-run report is used as Phase 4 migration-planning evidence:* the report must list every entry under the gen-1 root that it never examined, each with a reason. Today `sources` names only the files the importer tried to read. An extra state file, a topic log that is not JSONL, or an unknown topic file is invisible (Astra's 0b-repair re-review placed all three in a synthetic root). The inventory is a no-follow metadata walk from the root descriptor, with its scope stated; it parses and imports nothing. Until it exists, a report is not evidence of whole-tree completeness, and the accepted 40-record inventory fixture covers only its own input families. (Astra 0b-repair re-review, ruling on coder question 3.)
- **Retention and pruning policy.** No row can be deleted through any write path today (every table has a delete guard, and REPLACE is aborted by it on a contract-conforming connection). A future retention policy is a separate, audited operation — not an ordinary write path — and must preserve receipts, trigger tombstones and connector watermarks (design review §5; INVARIANTS C-11).
- **Operational schema concerns:** query indexes beyond uniqueness, and a migration mechanism beyond `PRAGMA user_version`.
- **Out of scope for this store:** the gateway's budget/cache database stays the gateway's; transcripts stay in the spool, not SQL rows.

## Interpretations to confirm

These are choices this draft made where the sources leave room. Each is easy to reverse.

1. **Lease scopes — ruled (R2.1, MODIFY/ACCEPT).** Research, discovery, verification and checkpoint leases coexist, one live lease per (topic, scope). Each non-delegate owns exactly one lease of its kind's scope, live and of its topic when admitted; delegates inherit the parent's lease. A commit is fenced by *its own* lease's generation, so a newer verification lease never invalidates an unreleased research lease. "Live" in this DDL means unreleased — expiry, deadlines, station/resource accounting, conservative scheduling and amendment invalidation are Phase 1 router work, proven there with stale-result/cancel/reservation tests.
2. **Verifier independence — ruled (R2.2, blanket parent rule REJECTED).** `parent_invocation_id` is control/reservation parentage only (delegates); a verifier never has one, so a producer cannot launch or control it. `requested_by_invocation_id` is the causal link and may name the producer: supervisor-created verification requested by the producing pass is accepted.
3. **Byte-mismatch quarantine — ruled (R2.3, ACCEPT).** An exact-quote mismatch quarantines the quote, like an NLI alarm; tested directly (D32 rewrite). Re-capture and adjudication stay explicit: an adjudication can resolve an alarm, never a mismatch.
4. **Process identity — ruled (R2.4, MODIFY).** Identity is required while `running`; a never-observed job may be recovered through its authenticated stable handle (recorded with the launch intent) and retained result without one; every identity field once observed, host and container included, is write-once in all later states. Leaving `outcome_unknown` needs the durable `invocation_reconciliations` record of that episode — keyed by the episode's own identity since RA4 — (method, evidence, digest found, descendant confirmation) — a result digest alone is neither reconciliation nor descendant-cleanup evidence. Process/descendant recovery itself is the supervisor's (task 1c, `gen2/supervisor/README.md`).
5. **Draft vocabularies — ruled (R2.5, MODIFY).** They stay drafts, but each now has explicit transition/ownership semantics (below, "Draft vocabularies") enforced in the DDL where it is a state machine, plus an amendment rule. Mandatory retraction / decision-record-change signals and the pre-contract meanings are added; unknown, resource limits and pending assessment are never relabeled as scientific outcomes.
6. **Canonical form for content hashes — ruled (R1/R2.6, ACCEPT JCS).** Implemented with the canonicalization helper (task 0a-repair R1).
7. **Facet coverage (A3).** Any obligation of the revision that tags a facet covers it, exploratory ones included; approval requires every facet to carry an operator rating (flow S3: ratings are approved with the framework, set and method design); an operator rating cites a `rating_approval` whose subject is an *earlier* revision (the draft the operator rated) because the rated revision's own hash covers the rating. Since RA2 that earlier draft must be an ancestor defining the same subject, and the decision's retained payload fixes the band and score. Subject equality compares the stored entries' JSON text minus `importance`. The store module's writer stores every JSON column in its canonical (JCS) form (`api.py`, 0b), so an equal entry is equal text however the caller ordered its keys (`gen2/tests/test_writer.py` shows a carried-forward rating accepted across two differently-ordered inputs). A re-ordered entry that bypassed the writer fails closed (refused, never accepted).

## Draft vocabularies (ruling R2.5)

Each vocabulary below is a draft: it may change only by amendment (a README/INVARIANTS change reviewed at Gate A, with its transition table and owners stated, and never by reinterpreting stored rows — the importer maps old values explicitly). None may relabel an unknown, a resource limit or a pending assessment as a scientific outcome.

**Queue status** (`queue_entries.status`; transitions enforced by `queue_status_transitions`; every change is a commit that advances `state_revision`):

| From | To | Owner / condition |
|---|---|---|
| awaiting_brief_confirmation | scoping | a confirmed intake brief of the topic (G-4; DDL `queue_scoping_needs_confirmed_brief`, 0b) |
| scoping | awaiting_scope_approval | router, on the committed scoping report |
| awaiting_scope_approval | awaiting_contract_approval / scoping | operator `scope_approval` / rework |
| awaiting_contract_approval | queued / scoping | operator contract approval / rework |
| queued | active | router (lease granted) |
| active | resting / queued | router (rest; requeue) |
| resting | active / queued | router |
| scoping, queued, active, resting, capability_blocked | held | router, with a typed hold (H-3) |
| held | scoping, awaiting_scope_approval, awaiting_contract_approval, queued | the hold's clearing authority |
| scoping, queued, active | capability_blocked | router, citing a capability fact (H-2) |
| capability_blocked | scoping / queued / held | router when the capability recovers, or hold |
| active | stopped_for_resources | router: a resource limit — never saturation (G-9) |
| stopped_for_resources | queued / awaiting_judgment | budget restored / operator judgment needed |
| active, stopped_for_resources | awaiting_judgment | router: pending an operator judgment — not an outcome |
| awaiting_judgment | active / queued / stopped_for_resources | operator judgment |
| active, awaiting_judgment | completed_with_qualified_conclusions | operator `completion_approval` of the current dossier (G-8, G-13) |
| completed_with_qualified_conclusions | queued | an approved amendment, or mandatory surveillance review (G-12) |
| every non-retired state | retired | operator `retirement` decision at the state revision being left (G-13) |
| retired | — | terminal (reviving a retired topic would be a new topic or an explicit amendment path — to confirm) |

**Claim status** (`claims.status`; enforced by `claims_status_transitions`; owner: the router at commit): `provisional` (captured) → `accepted_support` (a load-bearing claim only with its verification receipt, V-4; every claim only from contract-admitted production, V-10, from `contested` too) / `contested` / `rejected` / `quarantined` / `superseded`; `accepted_support` → `contested` / `quarantined` / `superseded`; `contested` → `accepted_support` / `rejected` / `quarantined` / `superseded`; `quarantined` → `provisional` (re-capture) / `rejected` / `superseded`; `rejected` → `superseded`; `superseded` is terminal.

**Review-trigger reason codes** (`review_triggers.reason_code`): the seven method-fit codes of flow S5, the cadence floor, amendment/reframe/capability/facet-audit/calibration causes, and the mandatory `retraction` and `decision_record_change` signals (G-12), which only code policy or the operator may raise — never a model observation (CHECK). A trigger is handled once and stays handled (RG-1b(e)).

**Search coverage, completeness and error classes** (`search_observations`): coverage states keep the gateway's narrow meanings plus `unknown` for lost telemetry; `completeness` says whether a result set was observed completely, partly (records kept, count a lower bound, error class says why) or not at all (A11, RG-4). Error classes name *why* a search is degraded or partial; `credentials_not_configured` and `secrets_backend_failing` are distinct (H-2: a failed secrets read is never "no key configured").

**Holds** (`hold_class`, `recoverability`, `required_authority`): three separate dimensions (H-3); a hold is created open and cleared once, operator-authority holds only through an approved `hold_clearance` about that hold.

## Hashing contract (ruling R1; R2.6)

- **Logical hashes** (contract `content_hash`, DecisionSpec `spec_hash`, manifest hashes, `request_fingerprint`, internally produced JSON artifacts): SHA-256 over the RFC 8785 JCS serialization, via `gen2/core/canonical.py` (canonicalization contract `jcs-rfc8785/1`). JCS itself is the pinned `rfc8785` package (`gen2/requirements.txt`, hash-locked, granted to `core` only, installed only into the project build environment — `docs/gen2/ENVIRONMENT.md`), verified against the RFC's published examples, the development-portal test data and the RFC's Appendix A ECMAScript canonicalizer on V8 (`tools/gen2_jcs_cross_vectors.js`). Python's `json.dumps(sort_keys=True)` is not JCS (number forms, UTF-16 key order).
- **What is excluded:** a document's `content_hash` excludes only its own `content_hash` field; the commit `request_fingerprint` (contract `commit-fingerprint/1`) excludes only `submitted_at` — every authority-bearing envelope field, including `envelope_version` and the admission context, is inside it.
- **Refused before hashing** (`parse_json_strict` / `canonical_bytes`): duplicate keys, NaN/Infinity, lone surrogates, JSON bytes that are not UTF-8, integer-*notation* numerals beyond ±(2^53−1) and Python ints beyond it, numerals a double cannot hold exactly (they would silently round — e.g. the RFC's own `333333333.33333329` input is refused at our boundary although JCS can serialize its rounded value — and underflow to zero). Any other number is a binary64 value as JCS defines it (`1e30` and `9007199254740992.0` are legitimate), so the parser is not the identity bound.
- **Identity bounds are by value** (RA8): identity, revision and generation fields must be integers in [0, 2^53−1] however they are spelled — `9007199254740992`, `9007199254740992.0` and `9007199254740992e0` are all the same refused value — enforced by the schemas' `maximum` (`common.schema.json` `revision`, `state_revision`, `generation`) and `canonical.identity_integer`; larger identities travel as strings. The DDL's INTEGER columns do not re-check the bound: a 64-bit column accepts 2^53. The store module's writer (`api.py`, 0b) applies `identity_integer` to every identity column and every generated increment before any SQL runs. Every INTEGER column in the DDL is classified as identity, flag, score or measure, and a test fails on an unclassified one.
- **Byte digests** (raw provider responses, acquired/staged artifacts): SHA-256 over the retained bytes exactly (`bytes_digest`), never parsed or canonicalized — a canonicalized response's hash is not a digest of the response. An internally produced JSON artifact is serialized canonically once, and its staged bytes are what is hashed.
- **Freeze point (done in 0b):** `jcs-rfc8785/1` and `commit-fingerprint/1` are frozen before any store/importer writes durable identities or replay fixtures. Every commit receipt records both in `hash_contract` (`common.schema.json#/$defs/commit_hash_contract`). Every decision receipt records the canonicalization alone (`#/$defs/logical_hash_contract`): its `spec_hash` is logical, and it has no fingerprint. Verification receipts hold only byte digests, so they record neither, because recording one would claim a contract none of their hashes uses. The DDL admits only the frozen versions (`operation_receipts_hash_contract_frozen`, `decision_receipts_hash_contract_frozen`), and the store's writer refuses any other before SQL runs (`api.FROZEN_HASH_CONTRACTS`, tied to `canonical.py`'s constants). A new contract means a new version in the schema, the DDL and `canonical.py` together. It is never an edit in place.

