# Adding a research source: the governance path

How a provider the gateway cannot currently call becomes a lane it can. The
document an agent produces is `gen2/schema/source-proposal.schema.json`; this
file is the pathway it enters, who owns each step, and what each step may not do.

**Trace.** Flow architecture S2 (tradition census — "which communities study
this under what names"; coverage facts per lane), S4 step 2 (discovery through
the gateway only), §2 (the decision ladder: an agent's *new option* is always
generation, never selection, and a new option is a proposal to the operator).
Design review §6 (a new executable adapter requires an image release; container
isolation means agents never introduce executables) and §9 (keep the gateway's
licensing/provenance handling and coverage vocabulary). `BOUNDARIES.md`
*Gateway*, *Operator*, *Primary agent*, *Secondary/delegate agents*.
`INVARIANTS.md` G-7 (anything scope-changing follows the amendment path), G-13 (a
decision authorizes only its exact subject), RG-U, H-2, B-2.
`DEPLOYMENT-CONTRACT.md` §2 (baked vs mounted) and §3 (the secrets surface).
`SOURCE-CATALOG.md` is the generated result.

## One naming warning, up front

"Source" is used for two different things in this project, and conflating them
would put a provider decision in the hands of a model that is qualified for
neither.

| | **This document** | **S4 step 5 source lifecycle** |
|---|---|---|
| Subject | a *provider*: an API the gateway could call | a *work*: a retrieved study or record |
| Question | should the gateway be able to call it at all | add / keep / supersede / coexist / quarantine / link-as-duplicate-report |
| Decision classes | **none.** No decision class covers this, and none should: it is an operator decision with a reviewed build task behind it | `source_lifecycle`, `source_add_battery` in `common.schema.json#/$defs/decision_class` |
| Who decides | the operator | the router's policy, on a qualified provider answer, within the approved protocol |

The `source_add_battery` class — the five-dimension battery (precision/weight,
consistency, applicability, independence, contradiction) — is about whether an
overlapping *paper* adds something. It has nothing to do with registering an API,
and a proposal under this document never routes to it.

## The path

**Step 1 — an agent proposes.** A primary or delegate invocation that hits a gap
emits a `source-proposal/1` document as a typed proposal through the ordinary
proposal route (`commit_outcome`), exactly like any other typed proposal. It is
recorded and it authorizes nothing. The document has no field for approval, for
enablement, for a verified rate limit, or for a credential value, so an agent
cannot assert any of those four things even by trying — and the schema's invalid
fixtures demonstrate each refusal.

What the proposal must carry, and why each part is required:

- **Motivation tied to the record**: the evidence gap, and the obligation ids it
  blocks. A proposal is a product of doing the research, not of surveying what
  exists. Where the proposal reports what the existing lanes did, it reports it in
  the gateway's own coverage vocabulary, so "the lane searched and found nothing"
  stays distinct from "the lane was unavailable" and neither becomes "no results".
- **Placement in the existing structure**: base lane (queried for every request
  of its kind) versus domain lane (added only for its domains), the substitution
  family it would join, and the overlap it expects. Proposing a base lane is a
  much larger claim than proposing a domain lane, and the rationale is where that
  claim gets made. The registry already holds the instructive case: OpenAIRE
  overlaps Crossref by 96–99%, so it is kept as a *fallback for DOI metadata*, not
  as a discovery lane.
- **Access**: the registry's own auth vocabulary, plus a *logical* secret name.
  The required/absent pairing between auth kind and `secret_ref` is the same rule
  `tools/gen_source_catalog.py` enforces, so an approved proposal cannot produce a
  registry row whose keys the generator would refuse.
- **API shape**: protocol, pagination, and — the field that exists because of a
  repaired gateway defect — what an error and an empty result look like, so an
  adapter can tell them apart instead of turning an unreadable payload into zero
  results.
- **Licensing**: the commercial verdict in the registry's vocabulary, the
  redistribution answer separately (it is a different question, and it decides
  whether retrieved content may travel in an export bundle at all), and at least
  one link to the terms that were actually read.
- **Unknowns**: every thing the proposal could not establish, named by field.
  An empty array is itself a claim — that nothing was left open — which a reviewer
  can check against the rest of the document.

Rate limits are either **documented with the page they were read from**, or
**stated to be undocumented**. There is no shape in which a proposal asserts a
number with no source, and none in which it claims a limit was *verified*:
verification is a live observation a person makes with the smoke run, recorded in
the registry seed.

**Step 2 — the operator decides.** Approve, reject, or defer, as an operator
decision about exactly this proposal (G-13: a decision authorizes only its exact
subject — the proposal id and its content hash). A rejection is a record, not a
deletion: a later proposal for the same provider names the one it supersedes and
says what changed. Nothing between step 1 and step 2 is automatic, and no
confidence score shortens it.

**Step 3 — the adapter lands as a reviewed build task.** An adapter is
executable engine code. It is written against the gateway's adapter contract, it
gets a fixture test, and it ships in an **image release** — never as a mounted
file and never as anything an agent produced. This is the design review's rule
(§6: "engine bugs, migrations and new executable adapters require an image
release") and it is also why `wrappers/` is not an extension point for this: a
wrapper is an operator-trusted launcher, not a place to add a research lane
(`DEPLOYMENT-CONTRACT.md` §4).

**Step 4 — the registry entry.** The row goes into the gateway's seed
(`gateway/research_gateway/registry/seed/sources.toml`) with its evidence links,
and `python -m research_gateway.registry.load` mirrors it into the gateway's
database. Two things about this step are structural, not stylistic:

- It is a **change to the gateway**, which is a separate service the gen-2 engine
  reaches over HTTP and never imports (B-2). The engine has no write path to the
  registry, and no schema in gen-2 can create a source. That is deliberate: the
  only door to external research sources should not be openable from inside the
  thing that wants to walk through it.
- A new row arrives **disabled with its rate limit unverified**. The registry's
  own rule is that an enabled source has a verified limit; enabling it is a
  separate deployment act after the live smoke has been run and its observation
  recorded in the row's `rate.evidence`.

**Step 5 — the artifacts regenerate.** `make gen2-catalog` rewrites
`docs/gen2/SOURCE-CATALOG.md` and `deploy/gen2.env.example` from the registry.
This is not a reminder; `make gen2-check` fails while they disagree with the
registry, so a new source whose key never reached the .env example cannot reach
a green build. That gate exists because the gap it closes was real:
`semantic_scholar` requires a key and was missing from gen-1's
`gateway/deploy/gateway.env.example`.

**Step 6 — the credential.** The operator obtains the key by the steps the
proposal recorded, and puts it in the secrets surface: one variable in the
mounted `.env`. A Vault path is an option only once vault mode is admissible
(`DEPLOYMENT-CONTRACT.md` §3.4; the current gateway image's vault backend is
not). Under that contract a *failed* read is a dated `secrets backend failing`
capability fact; a *successful* read that finds nothing is "no secret
configured". Those two are never collapsed (§3.3).

## What each actor may not do

| Actor | May not |
|---|---|
| Primary / delegate agent | approve a source; enable one; introduce an executable adapter or wrapper; carry a credential value; assert a verified rate limit; write the registry |
| Gateway | be bypassed by a direct API call from an agent; report a failed secrets read as "no key configured"; schedule a source with no verified rate policy |
| Engine (router, supervisor) | write the gateway's registry; treat an unavailable lane as `searched_empty`; count an unavailable lane as a zero in any denominator |
| Operator | — (this is the operator's decision; the reviewed build task is the check on the code, not on the decision) |

## For contrast: connecting a database to the export API

*Operator ruling 2026-09-26: this section replaced one that described the
operator's own corpus registry. Nothing specific to one deployment belongs in
the build; the contrast it drew is kept, in generic terms.*

A source brings material *in*. A connector sends approved research *out*
(`docs/gen2/EXPORT-API.md`). The two look alike, because each is a named
external system with a credential. They are governed differently, and should
not be managed as if they were one thing.

| | New research source | New export connector |
|---|---|---|
| What it changes | what the gateway may call | where approved research is delivered |
| Code | a new adapter, image-baked, reviewed | none for a reference type (`sql`, `jsonl_file`, `webhook`): an entry in mounted config. An `extension` for any other database: reviewed code outside the core, image-baked |
| Release | yes | no for a reference type; yes for an extension |
| Who may write it | operator, through the gateway's seed | operator, through the mounted connector config; never an agent |
| Risk being governed | an unlicensed, unmetered or unlogged call to the outside world | redistributing content the record says may not leave, or delivering to a destination that cannot keep the ordering and settlement rules |
| Reversal | a registry row edit plus an image change | disable the connector; its receipts and the engine's record are untouched |

The asymmetry is the point. A connector decides where material the operator
already approved is sent, under per-record licence rules the bundle already
enforces. A source registration decides that the engine may send a request to
somebody else's service, under somebody else's terms, spending a budget, and
under a licence that constrains what may be kept and what may be exported.
The engine never reads research back from a connector, so a connector can never
become a source. That is why the gateway is "the only door" in.

## Status

Steps 1 and 2 are implemented in the router (task 2a, Phase 2; Astra's
Phase 2 plan audit, finding 8). A research pass, checkpoint, discovery or
delegate commits `source-proposal/1` documents in its outcome's
`source_proposals` section (`gen2/router/service.py`): the router checks that
the proposal is of the committing invocation's topic and names that invocation
as its proposer, that a superseded proposal is recorded, and, for
contract-admitted work, that each blocked obligation is its revision's. The
proposal is retained whole in the store's `source_proposals`, under the JCS
hash of the whole document, which the router computes. The operator's
`source_approval` decision (approved, rejected or deferred) names exactly one
stored proposal and that hash (G-13; the store refuses a decision about any
other subject, and the router recomputes the hash first). The decision is a
record only. Nothing in the engine writes the gateway's registry, enables a
lane, holds a credential or installs anything. Steps 3 to 6 remain the
reviewed build task, the gateway seed, the regenerated catalog and the
secrets surface, as above. No real source has been proposed through the
route: the tests exercise it with the schema's example proposal
(`gen2/tests/test_router_workflow.py`, `test_store_workflow.py`). The route
existing is not evidence that any proposal was right; that stays the
operator's decision.
