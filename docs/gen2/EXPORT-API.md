# Gen-2 export API

How approved research leaves the engine: one standard, versioned export API
that any database can connect to, local or cloud. The documents are committed
(`gen2/schema/export-bundle.schema.json`, `export-manifest.schema.json`,
`export-delivery-receipt.schema.json`), and so are the store tables that
record exports (`gen2/store/schema/04-registries-and-export.sql`, "Export"). The exporter and its
connectors are **Phase-3 implementation targets**; no export code exists yet.

> **Operator ruling 2026-09-26.** Gen-2 is open source. Nothing in the build
> may carry a feature, route, schema value, service or setting specific to one
> operator's infrastructure. External export is one standard API. Any
> database, the operator's own included, is connected to it after the build
> through a connector, like anyone else's. None is built in, and none gets a
> path of its own. The internal process (S1–S7, the router, the store core,
> the importer, the internal record) is unchanged; only the outbound surface
> changed. This file was `EXPORT-SINKS.md`. Every section below is amended by
> the ruling, and §1 lists what it retired.

**Trace.** Flow architecture S8 items 1–5, as amended by the operator ruling
of 2026-09-26: the router commits the approved revision and an immutable
manifest atomically; deliveries are idempotent and generation-aware; old
retries never overwrite newer material; supersession and tombstones are
acknowledged per connector; the three facts are never conflated; approved
corrections are exported too. Flow §5 (synthesis representation: claim-graph
first, synthesis as a rendered view). Design review §9 is why this exists. The
external ingest script it examined recognized completion only when *every*
obligation was supported, parsed verification by substring membership, missed
dotted identifiers with a regex, and wrote its two target stores separately.
The review said it "requires replacement with the engine's canonical export
contract". `docs/gen2/BOUNDARIES.md` *Exporter*, *Router*, *Operator*,
*Evidence accounting*, *Verifier*. `docs/gen2/INVARIANTS.md` P-1–P-7, G-9,
G-13, V-1, V-2, RG-3, RG-4, RG-U, H-2, H-3, C-11.
`docs/gen2/DEPLOYMENT-CONTRACT.md` §1 (the exporter container) and §2 (the
config and secrets surface). Astra's three 0c reviews
(`reviews/gen2-0c*-astra-review-*.md`) proved the contract carried here.

---

## 1. One outbound path

**What the ruling retired.** Before 0d there were two outbound paths.
*Publication* put approved material into two named stores that gen-2's own
readers read. The store's vocabulary was closed over their product names, and
there was a reader "freshness envelope" to say how far those stores lagged.
*Export* (task 0c) sent the same material to operator-chosen destinations as a
second path beside it, with a second manifest. Both are gone as separate
things:

| Retired | Now |
|---|---|
| `publication-manifest/1`, and `export-manifest/1` bound beside it | `export-manifest/2`, the one manifest (§3) |
| the closed `sink` enum of two product names | `connector_id` (open, operator-named) and `connector_type` (closed: `sql`, `jsonl_file`, `webhook`, `extension`) |
| `bespoke` export sinks | `extension` connectors: reviewed code outside the core (§7) |
| `sink_delivery_receipts`, `sink_generations` | `export_delivery_receipts`, `connector_watermarks` (§4) |
| `export-delivery-receipt/1` | `export-delivery-receipt/2`: `sink` → `connector`, `export_manifest_id` → `manifest_id`, every rule unchanged |
| `freshness-envelope/1` (projected revision, mixed-generation pinning, per-sink map) | `freshness-envelope/2`, re-scoped to reads of the local record (§8) |
| the projector | the exporter (BOUNDARIES.md *Exporter*) |

No `/1` manifest or receipt was ever emitted, because no export code exists.
The `/1` versions therefore retire without a migration.

**What export is.** The router commits each approved revision with an export
manifest (§3). The exporter hands that manifest and its bundle to every
connector the manifest names, through one call (§4), identically for every
connector. A connector's type decides how it writes, never what it is given or
what it must guarantee.

**What export is not: a read path.** The engine never reads research back from
any connector or any external database. Engine readers read the local record:
research retrieval, accepted evidence and operator status alike. The connector
contract has one operation, and it returns a receipt that carries no research
content. Reconciling an attempt re-sends; it does not query. No engine module
can reach a connector except through the exporter, and only the composition
root may import the exporter (`gen2/boundaries.toml`).

**One approval path.** An export is of the exact approved revision: its
approved revision *is* its source revision. The approval is the operator's
`publication_approval` decision about that exact revision and content hash,
checked by the store when the manifest is committed
(`outbox_events_only_approved`). "Publication" survives only in that decision
kind and in the artifact kinds. It names the act of releasing an approved
revision, not a destination.

**Three facts, not four.** Completion at a dossier revision, export delivery,
and surveillance currency as of a time stay independent (P-4). A failed or
unknown delivery is an *export delivery* fact, reported per connector. It never
undoes completion, never stops surveillance and never blocks a topic.

## 2. The bundle: one shape for every connector

`export-bundle/1`, unchanged by the ruling. A connector never receives a
different document because it is a different type of connector. The bundle
carries the topic, the approved contract revision, the completion fact with its
outcome and qualifications, the obligations with their dispositions and
confidence, the claims, the claim–source links with the verification tier each
check actually reached, the rendered synthesis views, the stopping dossier with
per-rule operands, and the four candidate units.

Four properties are worth stating because they are what makes a bundle safe to
hand out:

- **Assembled by code, from committed state.** `assembler_version` records which
  code assembled it. A bundle is a pure function of (approved revision,
  `bundle_version`, export options, `assembler_version`), which is what lets a
  connector treat redelivery as idempotent rather than as a second write.
- **Unknown stays unknown.** Candidate units and rule operands are
  `observed_count`s: an unobserved window travels as `unknown` with its reason, a
  truncated one as `partial` with a lower bound. A satisfied stopping rule may not
  rest on an unknown operand, and the schema refuses one.
- **Tiers are not flags.** A load-bearing claim's link must name a verification
  receipt at a recorded tier. An abstract-tier check never satisfies a full-text
  requirement, and a tier-0 entailment pass is a screen that never stands in for
  verification.
- **No invented numbers.** `confidence` is a label under a scheme pinned by id
  and version, with the invocation that assessed it — or `unknown` with a reason.
  There is no numeric field in either shape, so a probability is unrepresentable
  rather than discouraged. This schema does not adopt a certainty scale; the
  scheme is declared by the contract revision. It does not borrow GRADE's
  certainty bands either. The methodology synthesis anchors GRADE (Guyatt et
  al. 2011, GRADE guidelines 2) for question framing and outcome importance. It
  also mentions GRADE's consistency and certainty-of-evidence domains (§4, and
  §10b, where they are canonical but unanchored). Neither passage gives an
  operational or validated mapping from those domains to an obligation's
  confidence, and without one the bands would be a borrowed label.

**Licensing is enforced in the bundle, per record.** A source's commercial verdict
is a per-source registry fact; whether a particular retrieved record's *content*
may be redistributed is a per-record fact the gateway records beside each
contributing payload (`gateway.record_sources.redistributable`, plus the content
licence). The bundle honours the per-record answer: a `supporting_quote` requires
`redistributable: true` as a constant, so a quote from prohibited or
unknown-licence content cannot be represented at all. It is omitted, and the
omission is listed in `content_policy.omitted_for_licence` with a count — an
export that is thinner than the record says why it is thinner. The constant
refuses a quote whose flag is false or absent. It cannot establish that the
flag is true of the quoted bytes. Checking that the flag and licence belong to
the exact contributing payload the quote came from is the assembler's job
(Phase 3). The assembler also carries the licence and attribution obligations
with the quote. A reusable-metadata flag never licenses the full text of the
paper it describes.

**Open point for review.** The obligation `disposition` vocabulary
(`supported` / `not_supported` / `mixed` / `insufficient_evidence` / `unknown`)
is **proposed**. The authoritative dossier document is Phase-2 work; if it lands a
different vocabulary, this becomes `export-bundle/2` rather than being edited in
place. The schema's `$comment` says so. Astra's 0c review ruled that it may stand
as proposed. Phase 2 must reconcile it with the authoritative dossier and
assessment scheme.

## 3. The manifest: `export-manifest/2`

The router commits the manifest as the outbox event's manifest, in the same
transaction as the approved publishable revision (P-1). `outbox_events` holds
one row per manifest. The manifest names:

- the topic and the **artifact kind**: a completion, an approved evidence
  correction, or an approved checkpoint publication (P-5: approved corrections
  are exported too, as new manifests);
- the **ordering pair** `(generation, options_revision)`. `generation` is the
  topic's approved-generation number: each approved publishable revision is one
  generation. `options_revision` is the revision of the mounted connector and
  export-options configuration the bundle was assembled under;
- the **source** revision and content hash, and the **approval** that names
  exactly them;
- the **bundle** identity: id, version, content hash;
- the **expected connectors**, keyed by id, each with its type (and, for an
  extension, its implementation and review);
- what it **supersedes**, as a whole pair, and the **tombstones** relative to
  it.

**When a manifest is committed.** Each approved publishable revision while at
least one connector is enabled is a new generation. A change to the connector
configuration or to what a topic exports is a new options revision of the
topic's latest approved generation. That covers enabling a connector later,
which is why a topic's first manifest can be any generation and supersedes
nothing. With no connector enabled, no manifest is committed and nothing leaves
the engine. The approval and the approved revision are in the local record
either way, and that record is what readers read.

**What the store enforces** (DDL `outbox_events` and its triggers, each with
tests and bound mutants):

- the approval is an approved `publication_approval` of this topic about exactly
  this source revision and hash (G-13), and the stored manifest's approved
  revision *is* its source revision. This was a Phase-3 obligation in 0c. It
  holds now because the export manifest is the outbox row;
- the manifest JSON's id, pair, kind, source, approval, bundle hash, connectors
  and superseded pair equal the row's columns;
- ordering pairs strictly increase per topic, so an old retry cannot be
  committed as newer material;
- one generation is one approved revision: a re-export under a later options
  revision keeps its generation's approval and kind;
- a superseded pair is complete, at least `(1, 1)`, and strictly lower, so
  generation 1 supersedes only its own earlier options revisions;
- every connector the manifest names is of a declared type, and there is at
  least one;
- a manifest is never updated or deleted.

The store does not check that an extension names its implementation and review,
or that a reference connector names none. That is `export-manifest/2`'s rule,
validated before outbox admission (§5).

## 4. The connector contract

```
deliver(manifest: export-manifest/2, bundle: export-bundle/1) -> export-delivery-receipt/2
```

One call, one connector, one attempt, one receipt. The engine drives every
enabled connector through this call and no other. The rules are the same for
every connector type.

**Idempotent.** The manifest is the idempotency key. Re-delivering the same
manifest to the same connector must converge on the same destination state and
must not duplicate rows, records or events.

**Generation-aware, ordered by a pair.** Delivery order is
`(generation, options_revision)`, compared in that order. The same approved
generation re-exported after the operator changes *what* an export should
contain is newer material rather than a duplicate to ignore. A connector
compares the incoming pair with the highest pair it has applied for the topic,
and there are four answers:

- **Lower.** The destination already holds newer material: `skipped_superseded`,
  and nothing is written. **An old retry never overwrites newer material.**
- **Equal, same export.** The connector's retained evidence names this
  manifest's `manifest_id` and `bundle.content_hash`, so this export was
  already applied. The usual cause is an attempt that committed and then lost
  its receipt. Nothing is rewritten: the connector acknowledges the earlier
  application from that evidence, tombstones included, and the receipt is an
  ordinary `delivered`.
- **Equal, different content.** One ordering pair naming two different exports
  is an upstream fault, and a connector does not settle it by overwriting. The
  result is `failed` with `error_class: conflict`, nothing written, a capability
  fact and a hold.
- **Greater, or nothing stored yet.** Write it and advance the stored pair,
  atomically.

§6 names the retained evidence each reference connector compares. An extension
connector's review must name its own (§7).

**Supersession and tombstones are acknowledged.** A manifest that supersedes an
earlier one lists what was removed or corrected, including entities removed for
licence reasons. A delivery that did not acknowledge the tombstones is not
`delivered`; the schema and the store both refuse that combination.

**The status records what is known about the destination, not what the
transport did.** Three questions decide it, in order:

1. *Could any of the request have been applied?* If it was never sent (a name
   that did not resolve, a refused connection, a connect timeout), it could
   not. That is `failed`, and `written` is an observed zero.
2. *If it may have been applied, did an authoritative answer settle the
   result?* An acknowledgement is `delivered`. An authoritative refusal is
   `failed` with an observed zero. A destination that reports which part it
   applied before it stopped is `failed` with `error_class: partial_write`, and
   `written` is a `partial` count: records actually written, a lower bound,
   never a total.
3. *Otherwise* the request may have been applied and nothing establishes
   whether. The process stopped after sending, no response came, the response
   could not be read, or it was neither an acknowledgement nor a refusal. That
   is `outcome_unknown`: it requires reconciliation, may not claim an observed
   count, and carries no error class. It is neither a failure nor a success.

The transport symptom is kept, in the receipt's typed `unknown_cause` and on the
capability fact, but it never decides the status by itself. An unreadable
response is `unknown_cause: unreadable_response`, never an error class, because a
receiver may have committed the export before its response became unreadable.
The schema holds these rules. A failure's count must be known: a `partial` count
for `partial_write`, an observed zero for every other class. An unknown cause
appears only on an unknown outcome. What counts as authoritative depends on the
connector type; §6 defines it for each reference connector, and an extension's
review must define it for that connector (§7). For `webhook` it is a protocol
the receiver must implement, because the engine cannot observe the receiver's
store (§6.3).

**Reconciling an unknown outcome** is a new attempt that re-sends the same
manifest and bundle. The branch it lands in is the answer. Each re-send has its
own receipt; the unknown receipt is never edited, and its hold stays until an
attempt settles (P-7).

**A dead connector is a dated capability incident.** Every failure and every
unknown outcome names a `capability_facts` row with its `since` time, and the
exporter raises a typed hold with an owner and a deadline when one is needed.
This is H-2 applied to export: the rule the 2026-09-21..24 secrets outage
produced is that a failing dependency is a dated fact that alerts on the
transition, never a quiet "nothing configured".

**The three facts rule.** A dead connector makes *export delivery* partial. It
does not undo scientific completion, does not stop surveillance, and does not
block a topic. The receipt document has no completion field and no currency
field at all, so neither can be asserted or inferred from it.

**What the engine records.** `export_delivery_receipts` holds one row per
attempt, append-only, and refuses a receipt the contract refuses:

- a status outside the four;
- a failure without its class, or a class on anything but a failure;
- an unreadable response as a class;
- a delivery without its acknowledgement time and tombstones, or either on
  anything else;
- an unknown outcome without its cause and reconciliation, or either on a
  settled result;
- a failure or unknown outcome without its capability fact, or a delivery with
  one;
- a receipt for a connector the manifest does not name, or under another type;
- a malformed connector id.

`connector_watermarks` is the engine's per-connector high-water mark: the
highest pair a connector has a delivered receipt for. It never regresses and is
never deleted. It is the engine's own bookkeeping, not a reading of the
destination. The exporter may skip a pair lower than it without sending, as an
optimization, but the connector's retained evidence is the correctness
boundary. The written count and hold travel in the receipt document, which the
router validates against `export-delivery-receipt/2`.

## 5. Configuration surface

| Thing | Where it lives | Changed by |
|---|---|---|
| Which connectors exist and are enabled; each connector's id, type, destination (a table prefix, a directory, an endpoint URL), batch size and retry policy; for an extension, its module and review | **mounted config**, `GEN2_CONNECTORS_CONFIG` (default `/etc/gen2/bundle/connectors.toml`), read-only, validated and activated as a versioned bundle | operator edit + restart |
| Per-topic export options (which views, whether quotes are included at all, redaction choices) | **mounted config**, part of the same bundle; its revision is the manifest's `options_revision` | operator edit + restart; in-flight exports keep their pinned revision |
| Credentials: a SQL connection string, a webhook bearer token, an extension's credential | **secrets**, `GEN2_SECRET_CONNECTOR_<CONNECTOR_ID>` (the id upper-cased, `-` → `_`) — see `deploy/gen2.env.example` | secrets backend |
| The reference connectors | **image-baked**, in the core | image release |
| Extension connectors | **image-baked** from their own reviewed package, outside the core | image release |

A connector whose destination carries no credential (a mounted directory) has no
secret variable at all. Nothing about a connector is agent-writable, and no
connector is introduced by anything an agent produces. An operator cannot create
a connector type by writing a name in config: the type vocabulary is closed, and
the schema and the store both refuse an undeclared type (DDL
`outbox_events_connectors_declared`).

That an extension names its implementation (module and review), and that a
reference connector names none, is a **schema rule only**: `export-manifest/2`
holds it, and the store does not repeat it. The store binds the manifest's
connectors to their column and checks each type; the rest of a stored document's
consistency is schema validation at the router boundary (`gen2/store/README.md`,
"What stays router logic"). Validating every manifest against
`export-manifest/2` before it is admitted to the outbox is therefore a named
obligation: of the router's validation boundary, which every document it commits
must pass (Phase 1), and of the manifest commit and extension loading that §9 items
2 and 4 owe (Phase 3). Even then, a nonempty module and review name establish
neither that the module exists nor that the review accepted it. That is the
extension's admission (§7).

*Task 1b:* the router's part is in place. Before a manifest enters the outbox,
the router validates it against `export-manifest/2`. It asks an extension
registry to admit each extension connector, and the bundle must be staged with
the commit, canonical, valid `export-bundle/1`, and the one the manifest
names (`gen2/router/README.md`). No registry is loaded until Phase 3's
extension loading exists, so until then no extension connector is admitted.

## 6. The reference connectors

The core ships exactly these three. They are the Phase-3 implementation
targets. None names a database product: each speaks a standard (SQL, JSON
Lines, HTTP).

### 6.1 `sql` — portable SQL over a standard connection string

The destination is any SQL database reachable by a standard connection string,
the connector's secret. Its scheme selects the driver, and which drivers the
image carries is a Phase-3 build decision recorded as a reviewed
`third_party` grant in `gen2/boundaries.toml`. The core never names a database
product. Portable SQL only: no vendor types, no stored procedures, no JSON
operators in any predicate the connector relies on. JSON columns hold whole
sub-documents the destination is not expected to query.

| Table | Key | Holds |
|---|---|---|
| `export_bundle` | `(topic_id, generation, options_revision)` | `manifest_id`, `bundle_id`, `bundle_version`, contract revision + hash, completion status/outcome/dossier revision, `assembler_version`, `assembled_at`, `bundle_hash` (the manifest's `bundle.content_hash`), `source_content_included` |
| `export_obligation` | `(topic_id, generation, options_revision, obligation_id)` | template id/version/claim type, importance band + optional score, `disposition`, `reason`, confidence scheme id/version/label or `confidence_unknown_reason`, `exploratory` |
| `export_obligation_facet` | `(… , obligation_id, facet_id)` | the facet tags, so coverage is queryable without parsing an array |
| `export_obligation_support` | `(… , obligation_id, claim_id)` | which claims support which obligation |
| `export_claim` | `(… , claim_id, claim_revision)` | claim text, status, `load_bearing`, `required_access_tier` |
| `export_claim_source` | `(… , claim_id, claim_revision, source_id, locator)` | access tier, verification status + receipt id + tier + time, quote text and quote licence **only where redistributable** |
| `export_synthesis_view` | `(… , view_id)` | view kind, claim-graph revision, renderer version, artifact hash + media type (the artifact itself is not inlined) |
| `export_stopping_rule` | `(… , rule_id)` | status, operands JSON, thresholds JSON |
| `export_candidate_unit` | `(… , unit)` | the unit's status, value and reason — never a bare integer, so `unknown` survives the trip |
| `export_tombstone` | `(… , entity_id)` | reason; one row per tombstone in the manifest, written in the transaction that advanced the watermark |
| `export_watermark` | `(topic_id)` | the highest `(generation, options_revision)` this database has applied, which never decreases, plus the identity of the delivery that set it: `manifest_id`, `bundle_hash`, `tombstone_count`, `tombstone_digest`, `applied_at` |

**Delivery is one transaction per manifest.** Its first step reads this topic's
`export_watermark` row inside that transaction and compares the incoming pair
with it (§4):

- **Lower:** roll back, write nothing, answer `skipped_superseded` with an
  observed zero.
- **Equal, with the stored `manifest_id` and `bundle_hash` equal to the
  incoming manifest's, and the stored `tombstone_count` and `tombstone_digest`
  equal to its tombstone list's:** the export was already applied. A lost
  receipt looks exactly like this: the transaction committed, then the exporter
  died before recording the result. Roll back without writing and answer
  `delivered`, with tombstones acknowledged, `written` the observed row count
  stored under the key (read in the same transaction), and `acked_at` the time
  of that read.
- **Equal, with anything above differing:** roll back, write nothing, answer
  `failed` with `error_class: conflict`, and raise a capability fact and a hold.
- **Greater, or no row yet:** upsert `export_bundle` on its key, replace that
  key's child rows, write the manifest's tombstones as `export_tombstone` rows,
  and advance `export_watermark` to the incoming pair with this delivery's
  identity, all in the one transaction. The advance is a conditional update
  (`WHERE` the stored pair is lower, or an insert when there is no row), and its
  row count is checked before commit. If a concurrent delivery got there first,
  the transaction rolls back and the comparison is made again against what that
  delivery stored. It never overwrites.

**The destination-side evidence the comparison reads** is that watermark row and
the rows under its key. `manifest_id` and `bundle_hash` tell an equal pair apart
from a conflicting one. `tombstone_count` and `tombstone_digest` (SHA-256 over
the RFC 8785 canonical form of the manifest's `tombstones` array, as applied)
let the equal-pair branch report `tombstones_acknowledged: true` from what the
database recorded, not by assumption. The `export_tombstone` rows are the
per-entity record, written in the same transaction as the watermark. Reconciling
an `outcome_unknown` SQL attempt is the same comparison: re-deliver the manifest,
and the branch it lands in is the answer.

`export_candidate_unit` keeping status and reason beside the value is the one
place a reader of the database can still tell "nobody looked" from "nothing was
there"; flattening it to an integer would reintroduce exactly the defect the
engine spent its accounting rules avoiding.

The watermark row is evidence the connector reads to decide a replay; it is not
the record of delivery. Nor are the database's own delivery rows, if an operator
wants them: those are a mirror for convenience. **The record of delivery is the
engine's receipt**, not the destination's table.

### 6.2 `jsonl_file`

One file per `(topic, generation, options_revision)`, written to a temporary name
in the destination directory and atomically renamed into place, so a reader never
sees a half-written export. Each line is one typed record with a `record_kind`
discriminator; the first line is the bundle header, which carries the manifest
id and the bundle content hash. A tombstone file accompanies a superseding
export. The files are the retained evidence, and the §4 comparison reads them.
The highest triple already present for the topic is the stored pair, and a lower
incoming pair is skipped. The same triple whose header names this manifest id
and bundle hash, with its tombstone file present when the manifest has
tombstones, is acknowledged without rewriting. The same triple with a different
header is a `conflict`, and nothing is renamed. A higher pair is written. The
destination is mounted config; there is no credential.

### 6.3 `webhook`

One POST per manifest, carrying the manifest and the bundle. The manifest id
also travels as an `Idempotency-Key` header, for the receiver's logs; the
receiver's dedupe is the atomic step below, not a key lookup. Bearer token from
the secrets surface; endpoint URL from mounted config. The connector never
follows a redirect (a redirect could re-send the bearer token elsewhere; the
gateway's vault client already refuses redirects for the same reason).

An HTTP status by itself establishes nothing about what a receiver did. A
`202 Accepted` can precede processing that later fails (RFC 9110 §15.3.3), a
generic endpoint may answer 2xx to anything, and a 4xx can follow a partly
applied request. The engine cannot see the receiver's store, so the §4
ordering rule and the settlement rule must both be kept by the receiver.
**A `webhook` connector is admissible only if its endpoint implements the
receiver protocol below.** Admission needs evidence for the whole protocol
before the connector is enabled; the acceptance cases at the end of this
section say what is run live and what needs the receiver's own tests. Phase 3
builds the runner with the connector. Anything the operator puts in front of
the receiver (a proxy, an auth gateway) is part of the endpoint for this
purpose. An endpoint that cannot meet the protocol is not an admissible webhook
connector, whatever it answers. That includes one that only queues work,
cannot keep the per-topic evidence, or cannot apply a manifest all at once.
The no-stale-overwrite rule is not relaxed for it.

**The receiver protocol, `export-webhook/1`.** Its payload is the export API's
current manifest and bundle, `export-manifest/2` with `export-bundle/1`. The
protocol itself is unchanged by the operator ruling; no receiver of the earlier
manifest version exists.

1. *Retained evidence.* The receiver durably keeps, per topic, what §6.1's
   `export_watermark` row keeps. That is the highest
   `(generation, options_revision)` it has applied, which never decreases,
   and the identity of the delivery that set it: `manifest_id`, the
   bundle `content_hash`, `tombstone_count` and `tombstone_digest` (defined
   as in §6.1). The records and tombstones it applied are kept beside it.
2. *One atomic step per request.* The receiver reads that evidence, compares
   the request's pair and identity with it, and takes exactly one of the §4
   branches, in one atomic, durable step. The step is serialized per topic
   against every other request for that topic; §6.1's transaction with its
   checked conditional advance is one way to do it.
   - **Lower:** nothing is applied.
   - **Equal, all four identity members equal:** nothing is rewritten; the
     earlier application stands.
   - **Equal, any member different:** nothing is applied.
   - **Greater, or nothing stored:** every record and every tombstone in the
     manifest is applied, and the stored pair and identity advance, together.
     Otherwise none of it happens.

   Because the step is serialized, two requests for one topic never both
   read the same stored pair and both advance: the second compares against
   what the first stored. The result does not depend on the order requests
   were dispatched or arrived in, or on any check the engine made before
   sending.
3. *Answers name the branch, and are sent only once its outcome is durable.*

   | Receiver's branch | Response | Receipt |
   |---|---|---|
   | Greater, or nothing stored: applied now | `200`, header `Export-Webhook-Result: applied` | `delivered`; `written` is observed, the number of records the bundle carries; tombstones acknowledged |
   | Equal, same identity: applied earlier | `200`, `Export-Webhook-Result: already_applied` | `delivered`, the same count, tombstones acknowledged. The stored identity is this manifest's, bundle hash and tombstone digest included, so what the receiver holds is this bundle, whole |
   | Equal, different identity | `409`, `Export-Webhook-Result: conflict` | `failed`, `conflict`, observed 0, with a capability fact and a hold |
   | Lower | `409`, `Export-Webhook-Result: superseded` | `skipped_superseded`, observed 0 |

4. *A refusal means nothing of this request was applied.* The receiver
   refuses only before the atomic step starts, or after that step rolled
   back. The refusals are exactly these: `401` or `403` (the credential),
   `429` (rate or quota), and `400`, `404`, `405`, `413`, `415` or `422`
   (the request cannot be routed or read, or does not validate as
   `export-manifest/2` with `export-bundle/1`, the latter including a bundle
   whose last record fails after earlier ones were read). They need no
   result header, because they claim nothing about the store beyond "none of
   this".

**What the connector concludes.** The status line and the result header, read in
full from the configured endpoint on the connection that carried this request,
are all it reads. A body is not needed, and one it cannot parse changes
nothing.

| What the connector observed | Receipt |
|---|---|
| Nothing was sent: the name did not resolve, the connection was refused, or TLS setup or the connect failed or timed out before any byte of the request was written | `failed`, `unreachable` or `timeout`, observed 0 |
| `200` with `Export-Webhook-Result: applied` or `already_applied` | `delivered`, as in the protocol table |
| `409` with `Export-Webhook-Result: conflict` | `failed`, `conflict`, observed 0 |
| `409` with `Export-Webhook-Result: superseded` | `skipped_superseded`, observed 0 |
| `401` or `403` | `failed`, `auth_failed`, observed 0 |
| `429` | `failed`, `quota`, observed 0 |
| `400`, `404`, `405`, `413`, `415` or `422` | `failed`, `refused`, observed 0 |
| Anything else that was read: `202` or any other 2xx; a `200` or `409` whose result header is missing, unrecognised or does not match its status; any other 4xx; a 3xx (never followed); a 5xx | `outcome_unknown`, `unauthoritative_response` |
| A response whose status line could not be read | `outcome_unknown`, `unreadable_response` |
| No response after the request was sent (closed, reset, timed out) | `outcome_unknown`, `no_response_after_send` |
| The exporter stopped after sending and before reading | `outcome_unknown`, `terminated_after_send` |

**Durable enqueueing is not delivery.** A receiver that has queued a request
has not applied it, and `export-delivery-receipt/2` has no status that says
"queued" (the store refuses one too). An answer given once the request is
queued but before the atomic step has committed is a `202`, or a response
without a branch result. Either way the attempt is `outcome_unknown` with
`unauthoritative_response`: `written` unknown, tombstones not acknowledged, a
capability fact and a hold. A receiver may queue internally, but it may not
answer `200` until the step has committed. Counting a durable enqueue as
delivery would need its own status and count semantics in a new receipt
version; this contract defines neither.

**Ordering, crashes and reconciliation.** The receiver's step is the
correctness boundary for §4. The exporter may still skip a pair lower than
one this connector has a `delivered` receipt for, recording
`skipped_superseded` without sending. That is sound, because the receiver's
stored pair never decreases, but it is only an optimization: it cannot fence a
request already dispatched, and every equal or higher pair is sent for the
receiver to decide. If the receiver crashes inside the step, nothing was
applied; if it crashes after the commit and before answering, the application
stands. The connector cannot tell these apart, so both are `outcome_unknown`.
Reconciling one is a new attempt that re-sends the same manifest and bundle,
and the branch it lands in is the answer, as for SQL. `already_applied` means
an earlier attempt of this manifest was applied, and `applied` means none was
until now. `superseded` means newer material is held. `conflict` means this
pair already names another export. Each re-send has its own receipt. The
unknown receipt is never edited, and its hold stays until an attempt settles.

**Webhook acceptance cases (Phase 3).** These run in full against the connector
with a test receiver whose store the test can read and whose step it can
crash. Against a real endpoint, as its admission check, what can be driven
from outside runs live: every answer in the two tables, both ordering traces
(the older request is held by withholding the rest of its body until the
newer one is answered), and re-sends answering `already_applied`. The rest,
the store's contents and a crash inside the step, needs the receiver's own
reviewed tests. The first case's receiver is deliberately non-conforming.

- **Queued-then-rejected.** The receiver answers `202 Accepted` once it has
  queued the request, applies nothing, and later rejects the queued work.
  This is the 0c re-review's counterexample. The receipt is `outcome_unknown`,
  `unauthoritative_response`, `written` unknown, tombstones not acknowledged,
  with a capability fact and a hold. It is never `delivered`, and the later
  rejection edits nothing. A `200` with no result header, from a generic
  endpoint, gives the same receipt. Either endpoint fails admission.
- **Whole-request acknowledgement.** After `200 applied`, the receiver's
  store holds every record and every tombstone of the manifest and the
  advanced pair and identity, and the receipt's count equals the records the
  bundle carries. A crash injected inside the step, after some records were
  staged, leaves none of them, no tombstone and no advance; the receipt is
  `outcome_unknown`, and a re-send answers `applied`. A crash after the
  commit and before the answer is `outcome_unknown` too, and the re-send
  answers `already_applied` without rewriting anything.
- **Atomic refusal.** For each refusal the protocol lists, and for both `409`
  results, the receiver's store is the same before and after. That includes
  a bundle whose last record fails validation after the earlier ones were
  read. The receipt is the mapped `failed` or `skipped_superseded`, observed 0.
- **Equal pair, different manifest.** This is the re-review's first ordering
  trace. M1 at `(3,2)` is applied with content A. M2 at `(3,2)`, with a
  different manifest id, content B and a fresh key, is sent, since the
  exporter sends equal pairs. The receiver answers `409 conflict` and still
  holds M1's content A; the receipt is `failed`, `conflict`, observed 0, with
  a capability fact and a hold. The same manifest id and pair with a
  different bundle hash, and a different tombstone digest alone, are
  conflicts too.
- **Older in-flight request lands after a newer one.** This is the
  re-review's second trace. A request for `(3,1)` is dispatched and held
  before the receiver's step. `(4,1)` is then applied and acknowledged, and
  `(3,1)` is released. The receiver answers `409 superseded` and its state
  stays at `(4,1)`; the receipt is `skipped_superseded`, observed 0. A second
  run releases both requests into the step together, many times over, and
  the final state is `(4,1)` every time.

## 7. Extension connectors: every other database

A database the reference connectors do not cover, for example a graph
database or a vector index, is reached by an **extension** connector. That
includes any database the operator runs. It is:

- **reviewed code outside the core**: its own package, not under `gen2/`, never
  named in the core's vocabulary, schemas, store or configuration defaults;
- **image-baked** by a release, never operator config alone. Every manifest
  that names it carries its `implementation`: the module and the review that
  accepted it. The schema refuses an extension without one, and refuses one on
  a reference connector;
- **bound by §4 exactly.** It gets the same manifest and the same bundle, and
  returns the same receipt. It decides the same four branches from retained
  evidence it keeps in its own destination, as §6.1's `export_watermark` row
  does. It has the same status rules and tombstone acknowledgement, and it
  reconciles by re-send. Its review defines what counts as an authoritative
  acknowledgement or refusal for it, as §6.3 does for `webhook`.

**Admission.** Its review must show the connector conformance cases passing
against a real instance of its database. They are §9's Gate C list: re-delivery
of the same pair; an old retry after a newer one; equal-pair replay after a lost
receipt, acknowledged without a rewrite, tombstones included; an equal pair with
different content, refused as a conflict; a tombstone it must apply and
acknowledge; a partial write reported as a partial count; a crash inside and
after its atomic step, each reconciled by re-send; two concurrent deliveries
racing for its watermark. A connector that cannot keep per-topic evidence or
apply a manifest atomically is not admissible, as for `webhook`.

**Must never:** feed anything back into the engine as research; answer with
anything but a receipt; add a type to the closed vocabulary; call the router.

**Loading.** The core grants no dynamic import (`gen2/boundaries.toml`
restricts `importlib`). How the image registers an extension with the exporter
is a boundary amendment, reviewed with the first extension (§9).

## 8. What engine readers get: the freshness envelope, re-scoped

**Why S8 item 3 had an envelope.** Readers were served from two projected
stores that could lag the canonical record. The adjudicated S8 contract was
written after two committee reviewers were handed a 20-day-old projection. The
envelope said which projected revision a reader got, whether retrieval had
mixed generations across stores, and how delivery to each store stood.

**What the ruling changes.** Engine readers read only the local record, in one
transaction. No projection is read, so there is no second copy to lag and no
way for one read to mix generations. `freshness-envelope/2` therefore retires
`projected_revision` and `mixed_generation`. Its per-store map becomes the
per-connector export delivery fact. Keeping those fields would describe
something that cannot happen.

**What still has meaning, and is kept** (so the envelope is re-scoped, not
removed):

- which approved revision the read served (`approved_revision_served`; P-3:
  every read names what it served), and nothing is served when nothing is
  approved;
- whether newer unapproved material exists, disclosed and never served (P-5);
- the three facts (P-4): completion at a dossier revision; export delivery,
  per connector, from receipts and watermarks (`no_connectors` when none is
  enabled); and surveillance currency with its per-feed reasons (P-6).

This follows the 0c review's ruling on the envelope: it describes engine reads;
export status is reported independently, per destination; and currentness is
never inferred from an exported snapshot or its receipt. The envelope's export
delivery fact says what receipts establish about a connector and nothing about
what a destination currently holds.

**Consumers of an export** read their own database. They get a pinned snapshot:
the manifest's pair and the bundle's completion and `assembled_at`. Nothing in
a bundle or a receipt claims currency, and they do not inherit a claim of
currentness from the engine.

## 9. What Phase 3 still owes

1. **The exporter and the reference connectors, with Gate C tests** whose
   failure modes are named up front: re-delivery of the same pair, an old retry
   after a newer one, a tombstone the destination ignores, a mid-transaction
   abort, a response that never arrives, a response that cannot be read, a 3xx
   or 5xx that settles nothing, a partial write reported as a total, equal-pair
   replay after a lost receipt (acknowledged without a rewrite, tombstones
   included), an equal pair with different content (refused as a conflict),
   two concurrent deliveries racing for the watermark, and a destination whose
   schema version does not match. For `webhook`, the five named receiver cases
   at the end of §6.3, which are also the admission check run against each
   endpoint before it is enabled. The same list is an extension's admission
   (§7).
2. **The router's manifest rules:** committing a manifest with each approved
   revision while a connector is enabled, and a new options revision when the
   connector configuration or a topic's export options change (§3); assembling
   the bundle from committed state before the commit transaction, so the
   transaction stays short (C-8); validating each manifest against
   `export-manifest/2` before it is admitted to the outbox, because the
   extension implementation/review rule is the schema's, not the store's (§5).
3. **Receipt storage in full — landed in task 1b.** The store holds every
   status rule of the receipt (§4), and the router's `ack_delivery` persists the
   whole receipt document beside its row, with every column (the written count
   and hold id included) bound to it the way the manifest is. A connector
   watermark advances only from a delivered receipt. An export receipt id
   replays only the identical document. What Phase 3 still owes here is the
   exporter that produces receipts, and deciding what the optional
   `invocation_id` must name; the router keeps it and does not yet check it.
4. **Extension loading:** the boundary amendment that lets the image register a
   reviewed extension with the exporter (§7). Registration must match the module
   a manifest names to one the image actually carries; the schema only requires
   that a module and a review are named (§5).
5. **Retiring the external ingest script** the design review examined. That is
   a cutover outside this build: once the exporter exists, whatever consumed the
   script's output connects through a connector instead. Until then nothing
   here changes what the script does.

**Closed by task 0d:** the approved-revision binding and approval check for
exports, which 0c left to Phase 3, is now enforced by the store, because the
export manifest is the outbox row (§3).

Nothing in this document is evidence that any of it works. There is no export
code yet; these are the requirements the Phase-3 implementation will be reviewed
against.
