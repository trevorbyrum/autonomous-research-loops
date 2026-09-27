# Gen-2 router — the sole writer (task 1b)

`service.Router` is the one implementation of the `ControlBackend` protocol (`gen2/core/control.py`). It is the only module that writes the store: only it may import `gen2.store` (`gen2/boundaries.toml`, rule 2), and only it may reach the store's write primitives (rule 9, `store_writers`). It makes no model call, spawns nothing and opens no network connection (it is granted none of those capabilities). `boundary.py` holds the checks that need no transaction. `schemas.py` validates documents against `gen2/schema/`.

Every operation follows one shape:
1. The request is normalized to its RFC 8785 form, which refuses what C-13 refuses. It is validated against its schema, including timestamps as real instants.
2. With no transaction open, the router reads staged bytes and re-hashes them. It runs the hash-truth and A10 checks.
3. One short transaction fences against current state and writes. A write the DDL refuses rolls the whole transaction back and is reported as a refusal. Nothing is retried.
4. The reply is returned after the transaction commits.

Authority is the capability the router minted at claim. The invocation's kind, topic, pins and lease are read from its row, never from the request. A request carrying a role, actor or authority field fails its schema.

## Operations

| Operation | Key (uniqueness) | Fencing | Atomicity |
|---|---|---|---|
| `claim` | `invocation_id`, the supervisor's stable job identity (L-8). The same request returns the same grant; a different request under the id is refused. | The topic exists, is not paused, and is in a claimable status. Admission is derived from state (C-12). A live lease of the same (topic, scope) refuses; an expired one is released first. A delegate needs a launching/running parent of its topic and inherits its lease, pins and config. | Releasing an expired lease, the new lease (generation above every earlier one of the topic), the invocation (admitted, with a minted capability), its first transition, the research `queued/resting → active` move and an audit event: one transaction. |
| `record_transition` | (invocation, target state). A fact already recorded replays; a conflicting fact is refused. | The capability names the invocation. L-1 only (DDL). Launch runs the final launch-admission check: a current lease, an unpaused topic, a live deadline (L-7). `result_ready` needs the result's bytes staged under its digest. | The state and its facts, the transition row, on failure the lease release (and `active → queued`), and the audit event: one transaction. |
| `record_observation` | `observation_id`. Identical content replays; different content is refused. | The capability; a running invocation; its current lease; an unpaused topic. | The observation and every retrieval event captured with it: one transaction. |
| `commit_outcome` | `operation_id`. An identical request fingerprint replays the stored receipt (also after the lease ended, RG-1b(d)); a different one is `operation_id_conflict`. One final outcome per invocation. | Capability → invocation. Envelope, outcome document and every embedded document are of the invocation's topic. The lease is the invocation's (a delegate's parent's), unreleased, of that generation and unexpired. `expected_state_revision` is current. Admission and config equal the pins. The topic is not paused, and the pinned contract (or brief) is still approved (confirmed). A final outcome commits exactly the staged result of a `result_ready` invocation; an interim transition is committed while running. Sections are permitted by kind (`boundary.SECTION_KINDS`) and admission. | Receipt, state-revision step, queue move, artifacts, ordinal, lease release, invocation → committed, evidence rows, outbox rows and the audit event: one transaction. The receipt is returned only after it commits. A rejection writes no receipt; it is logged as a `commit_rejected` audit event. |
| `apply_operator_decision` | `decision_id`. Identical content replays; different content is refused. | The DDL binds the decision to its exact subject (G-13). The router first recomputes the stored subject document's content hash (contract revision, intake brief). A transition the current state forbids refuses the decision whole. | The decision row and the transition it authorizes (brief confirmation, scope approval, contract/amendment/reframe approval with supersession, completion, retirement, hold clearance): one transaction. |
| `ack_delivery` | `export_receipt_id`. Only the identical document replays (compared whole, as its JCS bytes); a difference in any field, an optional one left out included, is `export_receipt_id_conflict`. Also one row per (manifest, connector, attempt), with attempts numbered in order. | The manifest is committed; the receipt's topic and ordering pair are its manifest's; the connector is one it names; a hold it names is a recorded hold of the manifest's topic (the router, and the DDL behind it). A delivery of a pair older than the connector's watermark is refused (P-2). | The whole receipt document with its row (every column, the written count's state and value and the hold included, bound to the document by the DDL), the capability fact a failure or unknown outcome raises (on a transition only, H-2), the watermark advance and the recovery fact: one transaction. |

The export outbox is committed through `commit_outcome` (outcome section `exports`), not a separate operation. The store requires every outbox row to name the operation receipt that committed it (`outbox_events.committed_by_operation_id`), and every receipt is fenced by a live lease. Before a manifest is written it is validated against `export-manifest/2`. Each extension connector must be admitted by the extension registry. Its bundle must be staged with the commit, in canonical form, valid `export-bundle/1`, and the one the manifest names.

## Boundary checks the store leaves to the router (store README)

Enforced now:
- **Schema validation** of every document the router accepts or emits: envelope, outcome document, verification and decision receipts, export manifests and bundles, delivery receipts, and its own receipts and responses. Commands (claim, transition, observation, operator decision) are checked against router-private schemas built on the shared vocabulary.
- **Hash truth**:
  - payload and result-ref digests against the staged bytes, sizes included;
  - raw decision responses, canonical bytes and export bundles staged under their hashes;
  - a DecisionSpec's hash recomputed from its stored document;
  - a contract revision's or intake brief's content hash recomputed before it is approved or confirmed;
  - request fingerprints and manifest hashes computed here, never taken from a caller;
  - a search observation's request identity recomputed as the hash of its request (H-5).
- **Timestamps** as real instants (schema `date-time` via `gen2/core/instants.py`), compared as instants (`utc_instant_ns`) for expiry and deadlines.
- **A10 comparisons**:
  - an observed result set's `result_count` is exactly the retrieval events captured with it. An unobserved set carries neither events nor a count. Partial stays partial, and unknown is never zero.
  - a screening assessment's criteria are its pinned protocol version's, each decided no earlier than its stage. An exclusion rests on a criterion not met; an inclusion has none not met.
  - a provider-written assessment is exactly its qualified receipt's committed answer, about that work, under a spec for that protocol version.
  - payload digests against staged bytes.
  - artifact sizes and media types against the recorded artifact.

Deferred, each with its phase:
- A DecisionSpec's question, rubric and input-builder versions against the question registry: 1d (the registry loads there).
- Qualification against the qualification registry: the router consults a `QualificationRegistry` and admits nothing without one. Fake records are 1d; real ones are Phase 3.
- Media types against the spool's own metadata: 1c (the spool). Today a media type is compared only with the recorded artifact row.
- Verification-receipt spans against the quote check's offsets, and the obtained tier against what the acquisition route can deliver: Phase 2, with quote capture and tier-0. Until then no router path records a quote check, so a receipt can name only one already stored (the store's key).
- A dossier's content hash against its document: Phase 2, where dossiers are assembled.

## Where later tasks attach

- **G-1 amendment impact** (1d): `_require_current_pins` refuses to commit work whose pinned contract revision or brief is no longer the topic's approved (confirmed) one (`amendment_pending`). `_approve_contract` is where impact identification runs. Until 1d decides which results remain compatible, none is silently reused. The result stays retained (C-10).
- **Registries, config bundles, reservations, retry budgets, scheduling** (1d). `POLICY_VERSION` becomes the mounted bundle's version. The claimable-status table and topic selection move to policy. `retry_intent` is always null today.
- **outcome_unknown, reconciliation, cancellation, the spool** (1c).
- **Operator transport and authentication** (1e).

## Structural limits

- **The capability is a bearer identifier.** It is unguessable and router-minted, but nothing yet authenticates the process presenting it. Likewise, operator decisions and delivery receipts are trusted to arrive from the operator surface and the exporter (1e).
- **Rule 9 sees static names only.** A Store handed to another module at runtime, or the router's private `_store` reached by reflection, is not visible to it. Only the composition root constructs a Router.
- **Faults are in-process.** They are exceptions at named points, plus an `os._exit` of a child process inside the transaction on a durable store. Neither simulates power loss or a crash inside SQLite's own commit.
- **The validator covers exactly the keywords `gen2/schema/` uses.** It refuses to load any other keyword. Agreement with `jsonschema` is shown on the committed fixtures and their single-point mutations, not on every possible input.
