# Gen-2 export sinks

Operator-pluggable research export: how an approved research record leaves the
engine for somewhere the operator chose. The schemas are committed
(`gen2/schema/export-bundle.schema.json`, `export-manifest.schema.json`,
`export-delivery-receipt.schema.json`); the adapters are **Phase-3
implementation targets** and no export code exists yet.

**Trace.** Flow architecture S8 items 1–4 (immutable manifest committed with the
approved revision; idempotent generation-aware sink writes; old retries never
overwrite newer generations; supersession and tombstones acknowledged per sink;
three independent facts never conflated) and §5 (synthesis representation:
claim-graph first, synthesis as a rendered view). Design review §9 — the reason
this exists: the external GraphRAG ingest script recognized completion only when
*every* obligation was supported, parsed verification by substring membership,
missed dotted identifiers with a regex, and wrote Qdrant and Neo4j separately;
that "requires replacement with the engine's canonical export contract".
`docs/gen2/BOUNDARIES.md` *Projector / publication*, *Operator*, *Evidence
accounting*, *Verifier*. `docs/gen2/INVARIANTS.md` P-1–P-5, G-9, G-13, V-1, V-2,
RG-3, RG-4, RG-U, H-2, H-3. `docs/gen2/DEPLOYMENT-CONTRACT.md` §2 (the config and
secrets surface) and §1 (the projector container).
`docs/gen2/INVARIANTS.md` §13 places "fuller projection/automation" in Phase 3.

---

## 1. What export is, and what it is not

**Publication** puts approved material into the two physical stores gen-2's own
readers read — Neo4j and Qdrant, named as such, never "GraphRAG". That vocabulary
is closed: `common.schema.json#/$defs/sink` admits exactly those two, the DDL's
`sink_delivery_receipts` and `sink_generations` constrain the column to them, and
a publication manifest's `expected_sinks` accepts nothing else.

**Export** hands the same approved record to destinations *outside* the engine
that the operator chose: a warehouse, an archive directory, a partner's webhook.
Nothing the engine serves reads from an export sink.

They are kept separate deliberately, and the separation is the design decision in
this document:

- The publication sink vocabulary stays closed, so "which stores do readers
  read" remains a fixed, reviewed answer. Widening it to hold operator-configured
  names would make the freshness envelope's guarantees depend on config.
- Export sinks are open by name (`export_sink_id`) and closed by *type*
  (`export_sink_type`: the three shipped generic adapters, plus `bespoke` for
  reviewed code).
- Export therefore gets its own manifest and its own receipts, and the reader
  freshness envelope is unchanged: it describes what readers are served, and no
  reader is served from an export sink. **An export failure is a delivery fact of
  the same kind as a publication-delivery failure — not a fourth fact, and never
  part of completion or currency.**

Export does **not** get its own approval path. An export manifest binds to an
approved publication generation and carries that generation's
`publication_approval` decision, so P-5 ("unapproved work is never served as
accepted evidence") holds for export by inheritance rather than by a second,
divergent gate. It also inherits the generation counter: there is one generation
stream per topic, not two.

## 2. The bundle: one shape for every sink

`export-bundle.schema.json`. A sink never receives a different document because it
is a different kind of sink; adapters differ in how they *write*, never in what
they are given. The bundle carries the topic, the approved contract revision, the
completion fact with its outcome and qualifications, the obligations with their
dispositions and confidence, the claims, the claim–source links with the
verification tier each check actually reached, the rendered synthesis views, the
stopping dossier with per-rule operands, and the four candidate units.

Four properties are worth stating because they are what makes a bundle safe to
hand out:

- **Assembled by code, from committed state.** `assembler_version` records which
  code assembled it. A bundle is a pure function of (approved revision,
  `bundle_version`, export options, `assembler_version`), which is what lets a
  sink treat redelivery as idempotent rather than as a second write.
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
  scheme is declared by the contract revision.

**Licensing is enforced in the bundle, per record.** A source's commercial verdict
is a per-source registry fact; whether a particular retrieved record's *content*
may be redistributed is a per-record fact the gateway records beside each
contributing payload (`gateway.record_sources.redistributable`, plus the content
licence). The bundle honours the per-record answer: a `supporting_quote` requires
`redistributable: true` as a constant, so a quote from prohibited or
unknown-licence content cannot be represented at all. It is omitted, and the
omission is listed in `content_policy.omitted_for_licence` with a count — an
export that is thinner than the record says why it is thinner.

**Open point for review.** The obligation `disposition` vocabulary
(`supported` / `not_supported` / `mixed` / `insufficient_evidence` / `unknown`)
is **proposed**. The authoritative dossier document is Phase-2 work; if it lands a
different vocabulary, this becomes `export-bundle/2` rather than being edited in
place. The schema's `$comment` says so.

## 3. The ExportSink contract

```
deliver(manifest: export-manifest/1, bundle: export-bundle/1) -> export-delivery-receipt/1
```

One call, one sink, one attempt, one receipt. The rules are the publication
projector's, applied to an open set of destinations:

**Idempotent.** The manifest is the idempotency key. Re-delivering the same
manifest to the same sink must converge on the same sink state and must not
duplicate rows, records or events.

**Generation-aware, ordered by a pair.** Delivery order is
`(generation, options_revision)`, compared in that order. `generation` is the
publication generation the bundle came from; `options_revision` is the revision of
the mounted per-topic export options it was assembled under, so the same approved
generation re-exported after the operator changes *what* an export should contain
is newer material rather than a duplicate to ignore. A sink that already accepted a
higher pair answers `skipped_superseded` and writes nothing. **An old retry never
overwrites newer material** — the same rule as `sink_generations` for publication,
with a two-part key.

**Supersession and tombstones are acknowledged.** A manifest that supersedes an
earlier export lists what was removed or corrected, including entities removed for
licence reasons. A delivery that did not acknowledge the tombstones is not
`delivered`; the schema refuses that combination.

**Partial delivery is visible, and is not a total.** A sink that stopped part-way
reports `failed` with `error_class: partial_write` and `written` as a `partial`
count — records actually written, a lower bound, never a total. An attempt whose
result is not established is `outcome_unknown`, requires reconciliation, and may
not claim an observed count. It is not a failure and carries no error class; it is
also not a success.

**A dead sink is a dated capability incident.** Every failure and every unknown
outcome names a `capability_facts` row with its `since` time, and the projector
raises a typed hold with an owner and a deadline when one is needed. This is H-2
applied to export: the rule the 2026-09-21..24 secrets outage produced is that a
failing dependency is a dated fact that alerts on the transition, never a quiet
"nothing configured".

**The three facts rule.** A dead export sink makes *export delivery* partial. It
does not undo scientific completion, does not stop surveillance, and does not
block a topic. The receipt document has no completion field and no currency field
at all, so neither can be asserted or inferred from it.

## 4. Configuration surface

| Thing | Where it lives | Changed by |
|---|---|---|
| Which sinks exist and are enabled; each sink's type, destination (a table prefix, a directory, an endpoint URL), batch size and retry policy | **mounted config**, `GEN2_EXPORT_SINKS_CONFIG` (default `/etc/gen2/bundle/export-sinks.toml`), read-only, validated and activated as a versioned bundle | operator edit + restart |
| Per-topic export options (which views, whether quotes are included at all, redaction choices) | **mounted config**, part of the same bundle; its revision is the manifest's `options_revision` | operator edit + restart; in-flight exports keep their pinned revision |
| Credentials: a SQL DSN, a webhook bearer token | **secrets**, `GEN2_SECRET_EXPORT_SINK_<SINK_ID>` (the id upper-cased, `-` → `_`) — see `deploy/gen2.env.example` | secrets backend |
| The adapters themselves | **image-baked** | image release |

A sink whose destination carries no credential (a mounted file path) has no
secret variable at all. Nothing about a sink is agent-writable, and no sink is
introduced by anything an agent produces.

## 5. The three shipped generic adapters

These are the Phase-3 implementation targets. Anything else is a `bespoke` sink:
**reviewed code, image-baked, naming its module and its review in the manifest.**
An operator cannot create a sink type by writing a name in config, and the schema
refuses a `bespoke` entry that names no implementation.

### 5.1 `generic_sql` — the documented relational export schema

Portable SQL only: no vendor types, no stored procedures, no JSON operators in
any predicate the adapter relies on. JSON columns hold whole sub-documents the
sink is not expected to query.

| Table | Key | Holds |
|---|---|---|
| `export_bundle` | `(topic_id, generation, options_revision)` | `bundle_id`, `bundle_version`, contract revision + hash, completion status/outcome/dossier revision, `assembler_version`, `assembled_at`, `bundle_hash`, `source_content_included` |
| `export_obligation` | `(topic_id, generation, options_revision, obligation_id)` | template id/version/claim type, importance band + optional score, `disposition`, `reason`, confidence scheme id/version/label or `confidence_unknown_reason`, `exploratory` |
| `export_obligation_facet` | `(… , obligation_id, facet_id)` | the facet tags, so coverage is queryable without parsing an array |
| `export_obligation_support` | `(… , obligation_id, claim_id)` | which claims support which obligation |
| `export_claim` | `(… , claim_id, claim_revision)` | claim text, status, `load_bearing`, `required_access_tier` |
| `export_claim_source` | `(… , claim_id, claim_revision, source_id, locator)` | access tier, verification status + receipt id + tier + time, quote text and quote licence **only where redistributable** |
| `export_synthesis_view` | `(… , view_id)` | view kind, claim-graph revision, renderer version, artifact hash + media type (the artifact itself is not inlined) |
| `export_stopping_rule` | `(… , rule_id)` | status, operands JSON, thresholds JSON |
| `export_candidate_unit` | `(… , unit)` | the unit's status, value and reason — never a bare integer, so `unknown` survives the trip |
| `export_tombstone` | `(… , entity_id)` | reason |
| `export_sink_generation` | `(topic_id)` | the highest `(generation, options_revision)` this sink has accepted; it never decreases |

Delivery is one transaction per manifest: upsert `export_bundle` on its key,
replace the child rows for that key, apply tombstones, then advance
`export_sink_generation` — and refuse the whole transaction if the incoming pair
is not greater than the stored one. `export_candidate_unit` keeping status and
reason beside the value is the one place a reader of the warehouse can still tell
"nobody looked" from "nothing was there"; flattening it to an integer would
reintroduce exactly the defect the engine spent its accounting rules avoiding.

The sink's own delivery rows, if an operator wants them, are a mirror for
convenience. **The record of delivery is the engine's receipt**, not the sink's
table.

### 5.2 `jsonl_file`

One file per `(topic, generation, options_revision)`, written to a temporary name
in the destination directory and atomically renamed into place, so a reader never
sees a half-written export. Each line is one typed record with a `record_kind`
discriminator; the first line is the bundle header. A tombstone file accompanies a
superseding export. Re-delivery of the same triple rewrites the same target name
byte-identically (the bundle is a pure function of its inputs), which is what
makes the rename idempotent. The destination is mounted config; there is no
credential.

### 5.3 `webhook_http`

One POST per manifest, carrying the manifest and the bundle, with the manifest id
as an idempotency header so the receiver can dedupe. Bearer token from the
secrets surface; endpoint URL from mounted config. A non-2xx response is `failed`
with a typed class; a response that cannot be read is `unreadable_response`, and a
request that was sent but whose response never arrived is `outcome_unknown` — not
a failure, and never a success. The adapter never follows a redirect (a redirect
could re-send the bearer token elsewhere; the gateway's vault client already
refuses redirects for the same reason).

## 6. What Phase 3 still owes

1. **Store tables and their DDL.** Export manifests and receipts need rows with
   the same discipline the publication tables have: immutable manifests, a
   per-sink high-water mark that never regresses, receipts that are append-only
   with one attempt per row, and the sibling-equality checks JSON Schema cannot
   express (that a manifest's approved revision *is* its exported source
   revision, the way `outbox_events` already checks for publication). None of
   that is in `gen2/store/schema.sql` yet, and adding it is a schema change that
   goes through review.
2. **A boundary amendment, proposed not taken.** `BOUNDARIES.md`
   *Projector / publication* today says the projector publishes "to the physical
   stores (Neo4j and Qdrant, named as such)". Export adds destinations that are
   not those two. This task deliberately did **not** edit `BOUNDARIES.md`: the
   drift rule says code and that file disagree through the amendment path, not by
   a coder's edit. The proposed wording is in this task's completion report for
   Astra and the operator to rule on.
3. **The adapters, with Gate C tests** whose failure modes are named up front:
   re-delivery of the same pair, an old retry after a newer one, a tombstone the
   sink ignores, a mid-transaction abort, a response that never arrives, a
   destination whose schema version does not match.
4. **The GraphRAG ingest replacement.** The external script the design review
   examined is what this contract exists to retire. Retiring it is a Phase-3
   cutover, and until it happens nothing here changes what that script does.

Nothing in this document is evidence that any of it works. There is no export
code yet; these are the requirements the Phase-3 implementation will be reviewed
against.
