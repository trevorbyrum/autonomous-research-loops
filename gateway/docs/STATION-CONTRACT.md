# Station contract — topic policy and research coverage across the gateway/chassis seam

Phase 8·0 (plan: research-loops `private/phase8-plan-draft.md` v3). One page, two
definitions. The gateway track (8a/8b) and the chassis track (8c/8d) both implement
against this file; a change here is a change to both.

## 1. Topic policy fields

| Field             | Type | Owner (single writer)             | Enforcement |
|-------------------|------|-----------------------------------|-------------|
| `topic_id`        | str  | queue item identity (`items[].id`) | injected; conflicting argument rejected |
| `commercial`      | bool | queue item `research_policy`       | injected; conflicting argument rejected |
| `accept_per_item` | bool | queue item `research_policy`       | injected; conflicting argument rejected |
| `domain`          | str  | queue item `research_policy`       | injected when absent; agent MAY override (routing hint, not policy) |

- The queue item is the only writer: policy is operator-controlled execution state.
  `SEMANTIC-STATE.json` and everything else agent-writable is never an enforcement
  source.
- Flow: queue item → runner child environment (`RESEARCH_TOPIC_ID`,
  `RESEARCH_TOPIC_COMMERCIAL`, `RESEARCH_TOPIC_ACCEPT_PER_ITEM`,
  `RESEARCH_TOPIC_DOMAIN`; booleans as `"0"`/`"1"`) → station MCP launcher (passes its
  environment through) → the stdio dispatcher (`research_gateway.clients.mcp_stdio`),
  which applies the enforcement column above to every `tools/call`, batch members
  included.
- Rejection is in-band: the dispatcher returns a tool error naming the bound field —
  an agent under a commercial-bound topic that passes `commercial: false` gets
  `policy-bound: commercial is set by the topic, not the agent`, never a silent
  override in either direction.
- Absent environment = unbound session (operator CLI, ad-hoc use): the tools behave
  exactly as before this contract.
- **Server-side enforcement (task 2b).** The dispatcher's injection is a convenience, not
  the boundary: an agent holding a client token could call the HTTP API directly. A
  station is therefore given a GRANT, not a client token: the grantor mints it for one
  invocation of one topic (`POST /v1/grants`, docs/OPERATIONS.md), carrying `topic_id`,
  `commercial`, `accept_per_item`, the advisory `domain` and the invocation id. The server
  applies the enforcement column above to every request under that grant on every door
  (`/v1` sync and async, the MCP endpoint's tool calls, batch entries and downloads, job
  polls): bound fields injected, a conflicting value refused (403 / an in-band tool error
  naming the field), jobs visible only to the same topic under the posture in force, and
  requests carrying the grant's invocation (another one named is refused).
- Items without a `research_policy` field inject only `topic_id`: the gateway's
  personal-baseline default applies, which is also the pre-approval discovery posture.

## 2. Coverage state

One vocabulary for lane reporting and failure records — "searched and found nothing"
is never conflated with "not searched" or "unavailable":

| State                 | Meaning |
|-----------------------|---------|
| `searched_ok`         | lane dispatched and returned ≥ 1 record |
| `searched_empty`      | THIS successful query returned 0 records — never that the provider was down, refused, unreadable or skipped; and never proof the literature is silent beyond this query |
| `not_searched`        | lane exists but the OPERATOR'S POLICY excluded it (commercial verdict) — never a capacity refusal |
| `provider_unavailable`| outage, timeout, quota, an unreadable answer, or a budget/breaker refusal — required research that COULD NOT run |
| `auth_failed`         | credentials rejected — or not configured at all (a keyless required tier is an auth problem, not an empty search) |
| `metadata_only`       | the record was found but the requested full text / file is not retrievable |
| `exhausted`           | a continuation: this lane already returned everything it has (its `next` sentinel skips it) — said only when the lane's adapter REPORTS, from its source's own evidence, that nothing remains; never inferred from a missing continuation (task 2b-repair-6) |

- Gateway → client: every `lanes[]` entry in a find/resolve/enrich answer carries
  `coverage` (one of the states above) next to its existing `source`;
  prose `facts` remain for humans and never become the machine channel. Each entry
  also says what was OBSERVED (task 2b; INVARIANTS H-5, RG-4, RG-U):
  - `completeness`: `complete` (the answer was read whole), `partial` (it was read, but
    some of it was unreadable, or — `partial_pagination` — it holds records but neither a
    continuation nor its source's reported end, so more may remain that cannot be asked
    for: `count` is then a LOWER BOUND, never the total) or
    `unobserved` (no result set was read: every degraded state, `not_searched`,
    `exhausted`);
  - `count` exists only for an observed result set — a lane that could not run, or
    whose answer was unreadable, has no count, never a zero — and `retrieved` lists the
    identities it counts, in the lane's own rank order, before any merge;
  - `error_class` names why a lane is degraded or partial, in the engine store's
    vocabulary (`payload_invalid`, `timeout`, `rate_limited`, `breaker_open`,
    `budget_refused`, `provider_outage`, `credentials_rejected`,
    `credentials_not_configured`, `secrets_backend_failing`, `transport_failure`,
    `partial_pagination`);
  - a find answer's `records` are deduplicated by IDENTITY only (task 2b-repair-13a; INVARIANTS E-3): records whose normalised identities are equal merge, and nothing
    else does — distinct DOIs never merge, whatever their titles say. Candidates that merely look alike (same kind, year and first-author surname, a similar title) are
    reported in an optional top-level `linkage_suggestions` list — each `{type: possible_same_work, identities, basis, differing_identifiers, provenance, disposition:
    unassessed}` — for a later governed assessment; it is present only when there is something to say, and it changes no record, no `retrieved` identity and no `count`;
  - find lanes echo the `cursor` they were asked with, so a failed continuation page
    is retried from where it failed; a failed page gets no `next` and is never
    `exhausted`. A find lane's adapter answers a continuation (`next`: more may remain),
    `exhausted: true` (nothing remains), or neither (`partial_pagination` above); a
    continuation outranks a reported end. A complete page is not a complete search: only
    the page that says `exhausted` ends the lane. A continuation its source can no longer
    honour — the local index's names the population it was counted in, and that population
    has since changed — reads nothing and ends nothing: `provider_unavailable`,
    `unobserved`, `partial_pagination`, no `next` (task 2b-repair-7). Each find adapter's end
    rule rests on its provider's own evidence, recorded in `PROVIDER-PAGINATION.md`.

  **A provider's answer is read through a schema the operation declares, and nothing else (task 2b-repair-12), under trust model B (task 2b-repair-14).**

  *The guarantee, exactly.* For SUPPORTED provider input — bytes within the supported provider-input contract (section 5) — the gateway guarantees a complete contract at four
  boundaries: the response is a complete HTTP message (the transport), its bytes are valid in their format (the byte openers), the document is in the supported vocabulary and its
  fields mean what the schema says (the decoder), and what a lane reports is what was read through them (adapters and storage exits). Input that fails any of them is an
  unreadable lane — `provider_unavailable`, with `payload_invalid` or `transport_failure`, `unobserved`, no count — and never a shorter, emptier or different answer. First-party
  adapters are TRUSTED, REVIEWED CODE. Their discipline — whatever identifies, selects, ends or continues anything is read through a declared kind; a provider's raw object and
  metadata are stored and not read; materialization happens at the reviewed sinks — is enforced by declared-read inventories (`gateway/tests/inventory.py`, held by
  `tests/test_inventory.py`), import and parser guards, mutation tests with positive controls (`make gen2-gateway`) and review, as a documented design boundary. It is **not**
  by-construction confinement of Python code against deliberate misuse: Python identity checks (`x is None` on an `any_()` value), reachable private fields, importable privileged
  helpers (`plain`, `Sealed`) and finite testing are documented boundaries of the model, not debts. Who may supply adapter code, runner isolation and credential and network
  separation are not claimed here (the supervisor's, 2e1). The operator adopted this model on 2026-10-02 (Gate D #2; INVARIANTS B-1).

  *Transport completion (task 2b-repair-14; Astra F1).* The shared transport (`adapters/base.py` `_read_body`; RFC 9112 §6.3, §7.1) returns a success only for a complete message.
  It validates the framing headers (Transfer-Encoding with Content-Length, a coding other than exactly `chunked`, and a Content-Length that repeats, is a list or is not digits
  are refused as invalid or conflicting framing, not guessed at), checks that `http.client` settled on the framing the headers state, bounds the body at 256 MiB (a declared
  length past it is refused unread), and raises `IncompleteRead` when a Content-Length is not met or chunked framing is not terminated. An error status keeps its status whatever
  happens to its body. **Disclosed ambiguity:** a response with neither Content-Length nor chunked framing is close-delimited, its only end is the connection closing (RFC 9112
  §6.3), and EOF cannot tell a deliberately shorter body from an interrupted one — so a close-delimited body cut at a record boundary is a well-formed shorter document and loads
  as one. Whether a live provider's responses are close-delimited is Phase 4's to qualify.

  *The decoder.* ONE decoder (`schema.decode`) checks the whole declared payload before any adapter logic runs and hands back values read through these public operations: an
  object is a `Rec` holding exactly its declared fields (reading another raises `UndeclaredRead`, which is not a member's loss: the public way to read a field the schema does not
  declare fails visibly), a provider's list of candidates is a `MemberList` (every member decoded alone; it cannot be iterated, indexed, sliced or filtered, only read through
  `base.members()`, `base.first_member()`, `take()` and `expand()`), a record's own list is an ordinary list. Choosing between alternatives therefore happens on decoded values:
  every declared field of an object is decoded, nested contents included, whether or not the adapter will use it, so `a or b` cannot skip reading `b`. What a failure costs is
  decided by where it is: a field missing or null is the empty value of its kind (None, false, an empty list, an object of nothing) unless the schema requires it; one that is
  there and is not its kind is unreadable, `false`, `0`, `""`, `[]` and `{}` included, and costs the nearest boundary around it. A member of a list that cannot be read costs that
  member only (it is dropped and counted, so the lane is `partial` with a lower-bound `count`; a member that is readable and names nothing to report, a reference with no DOI, is
  omitted, not counted); a lookup's first result that cannot be read is an unreadable answer, never "not found", and never answered by the result after it; a member that holds
  members of its own and cannot be unfolded (an SDMX data set) is one dropped member in place of what it held; a field declared `isolated` costs only itself (Unpaywall's
  `best_oa_location`, which the listed locations may not hold: the lane is `partial`, the listed locations stay); a field declared `soft` (a total, a cursor, a count of pages)
  says nothing when it cannot be read and never ends or continues anything (`base.total`: a whole number no smaller than what was read; `base.offset_after`: a number past the
  page); anywhere else the answer is unreadable (`provider_unavailable`, `payload_invalid`, `unobserved`, no count). A list a provider may leave out only when it counts nothing
  (`results` beside `numFound: 0`) is empty only when that count is the whole number zero. `make_record` checks the canonical fields, so one member whose title is a number is
  dropped and counted, not raised out of the router. Where a list is one record's own data (a record's authors, tags or licences; a series' observations; the rows of one table
  record, which FRED, Census and BEA keep whole) or a catalogue's entries (BLS, FRED, Census, BEA: one that cannot be read makes the whole catalogue unreadable, never a shorter
  one) the schema says `own(...)`, not `members(...)`; whether a list is one or the other is the schema author's declaration, and the inventory (`gateway/tests/inventory.py`)
  lists every place an answer or a list leaves the decoder (`.raw`, `each`, `at`, `without`, `empty`, `same_as`, the `MemberList`, `Sealed`, `Passive` and `Rec` constructors,
  `download()`) with why it is not a pass over independent members; a use that is not listed fails — a finite syntax guard for review behind the construction, not what makes it
  so.

  *Totality, declarations, sealed provenance (task 2b-repair-13a, -13c, -14).* (1) The decoder's failure channel is TOTAL — every scalar conversion (a year: `str.isdigit()` takes
  `"²"`, `"①"` and a 4,301-digit string, `int()` does not) and every consistency rule runs inside the decoder's own wrapper, so whatever a provider's value makes it do is a
  `PayloadError` at the nearest boundary (a member's loss, with its readable peers kept as a partial lower bound), the opening of the answer's bytes (empty, not the document its
  format requires, nested deeper than the gateway's limit of 64 levels) is inside the same channel, and only a programming error (`UndeclaredRead`, `PassiveRead`, `SealedRead`)
  passes. (2) Declarations are complete for what DECIDES — a field declared `any_()` is handed over `Passive`, carried as sent for a record's `extra` and nothing else (every
  public way of reading it raises), so a field that identifies a candidate, selects one, ends or continues a listing, goes into a request or is shown to the caller as a label is
  declared a kind (`maybe_key`, `text`, `key`, `flag`, ...) and a wrong one is unreadable, never a returned identifier. (3) The raw answer is SEALED: the client's `Response`
  exposes no payload (no `json`, `text` or `body`: `decode(...)` opens a payload's bytes — see "scope" below — and `download()` hands back the bytes of a file a caller asked to
  download, sealed), a member's `raw` is sealed and leaves only as a copy, and so is every record an adapter builds: a record's `raw`, its `extra` values built from an `any_()`
  field and a download's bytes stay opaque from `make_record` until the router serializes the answer (`router.execute`, after every lane has run and every selection, coverage and
  licence decision is made), the cache persists a record (`Cache.put_record`) or the index stores a loaded record (`harvest/index.upsert`) — the three sinks that call `plain`,
  the one materialization. The public operations on a Sealed or a Passive do not read: **nothing compares a Sealed with another** (a literal passed as `raw` has no comparison
  with a decoded object), a decoded object compares with nothing but another decoded object through `Rec.same_as`, and a typed field of a record (title, venue, licence,
  attribution, authors, links, identifiers, year, identity) takes its own typed domain and unwraps nothing the decoder issued. Two information-bearing predicates are sanctioned
  by name (the operator's ruling of 2026-10-02) and listed, each with its reason: `Rec.empty`, used only at the reviewed provider-shape predicates (BEA's error object,
  Unpaywall's best location, an SDMX structure that says nothing), and `Rec.same_as`, used only for the intended comparison of decoded provider objects (Unpaywall's best-location
  check) and never for a value an adapter wrote. doi.org's registration-agency answer and DOAJ's CSV dump cross the decoder like any other, so an answer that is not a list is an
  unreadable lookup (nothing cached) and not an `unknown` agency remembered for a prefix. **Scope of "only the decoder opens a payload's bytes":** it covers every payload
  decision — what a provider's answer says, which can produce a record, a count, an end or an empty answer. The client also reads a `Response`'s bytes in named places for its own
  purposes (`check()`'s look at the first bytes to refuse an HTML page wearing a success status, which can only make a lane unavailable; `_text_of`'s read of a 401/403 body to
  classify the failure of the call; `_count_of`'s count for the call log, through the decoder's own opener; `download()`'s sealed bytes): the inventory lists each read of `_body`
  with what it is for, and a new one fails it.

  *The byte openers (task 2b-repair-13c; Astra R13A-1; frozen in 2b-repair-14).* The decoder validated the values a lexer handed it, and the lexer, each library at its default,
  had already resolved malformed input — a DOAJ dump with an unterminated quote loaded as zero journals. `core/wire.py` holds the openers and its docstring is the ruling for
  each; the supported provider-input contract (section 5) is their policy. Malformed input, and input outside the policy, is a `PayloadError` (the answer is unreadable), never a
  successful shorter or empty one. The OpenAlex snapshot reader opens its JSON lines through the same opener, per line: a line that cannot be read is refused, counted and named
  (file, line, reason) and the lines around it are loaded, and a file that cannot be read, decompressed or framed fails the load. The HTTP headers the gateway decides from are
  openers too: `Link` is strict (RFC 8288), and `Retry-After` is `delay-seconds` (ASCII digits) or a date the library's email-date parser reads (its tolerance is stated in
  `Response.retry_after_seconds` and held by a test; a date with no zone is GMT). `tests/inventory.py` lists every parser entry point in the package — a call or not, a parser
  object included — and fails on one that is not classified. A truncation that ends exactly at a record's end is a well-formed shorter CSV: nothing in the format marks the end,
  and the transport's framing check (above) is what detects a short body. A schema may say a field is `never_null` where an operation's contract tells a field LEFT OUT from one
  sent null (Semantic Scholar's `data`: omitted beside `total: 0` is a search that matched nothing; null is unreadable). A Dataflow's structure reference is validated over every
  `Ref` and `URN` it states before any is filtered (an empty or nameless `Ref` is a malformed one), with `package` and `class` only as SDMX 2.1 fixes them.

  *Alternatives, specifically* (tasks 2b-repair-10b/11b R10-1, 2b-repair-12 R11-1): DataCite's `rights` beside `rightsIdentifier`, BEA's `Description` beside `Desc` and every
  spelling of a value's key, a DOI among a record's identifiers beside its own id, Unpaywall's `best_oa_location` beside `oa_locations`, a Crossref work's issue date beside its
  creation date and its authors' `given`/`family` beside `name`, the Crossref journals loader's typed `issn-type` beside its plain `ISSN`, SDMX-JSON's `structure`, `structures`
  (its first element is the one a lookup reads, and it is decoded) and the same two under `data`: each is a declared field, so a malformed one, nested contents included, beside a
  valid preferred value makes what holds it unreadable by the scope's rule above. SDMX-ML is decoded by the same decoder (an element's attributes, text and children are fields of
  the schema; `"**Name"` is every descendant of that name): an element is its namespace URI and its local name, a scalar element that holds a child element has no scalar text
  (unreadable, never its first chunk), and a message outside SDMX-ML 2.1 is an unreadable answer (section 5).

  *The evidence, in the order of independence:* the oracle (`tests/test_oracle.py`, `tests/oracle/`: the canonical fields every valid answer must produce, hand-written from the
  providers' documentation and the fixtures, the RFC 3986 / 8288 `Link` vectors written from the RFC text, the BIS and ECB catalogue cases, the registry loaders' records, and a
  coverage record computed from what actually ran; written by an author who had not read the gateway); `tests/test_schema_corruption.py`, which DERIVES its corruption positions
  from the declared schemas (every declared field with a wrong kind, left out where required, every alternative beside a valid other and alone, what each must cost read from
  where the schema puts it) and fails an adapter that reads what it does not declare; `tests/test_schema.py`, the decoder's own rules; `tests/test_transport_framing.py`,
  `tests/test_xml_interpretation.py` and `tests/test_snapshot_lines.py`, which drive the transport, the XML rules and the snapshot loader from independently written bytes; and
  `tests/test_invariants.py`, four invariants over every operation corrupted at every position of a valid answer (an end or a continuation only from fields it read; an unreadable
  container never an empty one; readable peers survive; nothing escapes unhandled). That harness is metamorphic (it holds a corrupted answer to how it may differ from the
  gateway's own answer to the valid one), so it is supplementary coverage, not an independent oracle (task 2b-repair-10b, R9-4); schema-derived cases show consistency with the
  declarations, and declarations cannot certify their own completeness. A schema that under-declares a field is invisible to a harness derived from it, which is why `any_()` is
  Passive: a decision cannot read an untyped value, so the first answer that reaches it fails (tests/test_declarations.py audits the 65 that remain by what the adapter does with
  each). The derived pass goes into every `oneof` branch and `by` variant (with a valid sample put in for the one the answer does not hold) and is checked against an inventory of
  the declared paths written apart from it; DOAJ's CSV and the doi.org lookup are derived passes too. The lazy-choice SOURCE SCAN that used to stand here (no `or`, `and` or
  conditional expression over two provider reads) is retired: it was a guard with an ordinary-spelling bypass (Astra, 2b-repair-11: a value held in a variable first), never a
  proof, and with the decoder there is no lazy provider read for it to watch. Sites reviewed and left: a filter on a catalogue row's identifier (`if row["id"]`: the accepted rule
  that a row naming nothing is skipped, and a listing in which none names anything is not a catalogue, `base.identified`); credentials and token lifetimes (`expires_in or 3600`:
  no candidate data); Socrata's portal-vouching predicate (fails closed: a member that cannot be read vouches for nothing); the OpenAlex snapshot loader's per-line reading of a
  local file; and pass-through `extra` fields (`cited_by_count`, `type`, `version`, ...), declared `any_`, which are carried as the provider sent them and are not decisions.
  A dataflow browse is about the flow asked for (task 2b-repair-11b, R10-2). BIS and ECB select the Dataflow whose id was
  asked (`sdmx.dataflow_named`: the flow its agency maintains), then the DataStructure that flow's own `Structure` reference
  names (id, agency and version as stated), and the label, the dimensions and the request template all come from that one
  selection. The references a flow states are decoded and checked together (task 2b-repair-12, R11-2): SDMX 2.1 gives a Dataflow ONE
  structure reference, a `Ref` with an optional `URN`, or a `URN` alone (DataflowType, ReferenceType), so two `Ref`s, two `URN`s, two
  `Structure` children, or a `URN` that names a different structure than the `Ref` beside it, are a flow that does not say which structure
  it has: an unreadable answer (`payload_invalid`), never the first of them. A `Ref` with the `URN` that names it is one reference; a
  `URN` alone is a legitimate representation this reader does not follow, so the flow yields no template (a capability fact). A flow the
  message does not hold, one that names no structure, and a structure the message does not hold give no entry and no template
  (a capability fact: unobserved); a flow or structure the message defines twice differently is an unreadable answer, never the first of
  them; the structure is never guessed from the flow's own id; a flow nobody asked for is not asked for its references.
  A flow listing in which no dataflow names itself is unreadable, not a catalogue (`base.identified`).
  The canonical record carries `publisher` (the sample the engine's contract fixtures ship has it beside `venue`)
  wherever the provider states one for a work, a dataset or a venue (Crossref, DataCite, DOAJ journals, CORE,
  OpenAIRE, the Dataverse family), read as text; `venue` keeps what it said.
  An unreadable successful answer (unparseable, empty, or without the container its
  results live in) and a search endpoint's 404 are `provider_unavailable` with
  `payload_invalid` / `provider_outage` — never `searched_empty`. An answer with any
  degraded or partial lane is never served again from the search cache; an answer that
  IS served from it repeats the lanes of the dispatch that produced it, marked
  `cache_hit` / `served_from`, and the caller's own observation says `served: cache`
  (§4) — a replayed `searched_ok` is that earlier dispatch's, not a new one.
- Client → chassis: when `RESEARCH_LOOP_RESEARCH_ACTIVITY` names a writable file, the
  stdio dispatcher appends JSON lines
  `{"at": iso8601, "source": id, "request_type": t, "coverage": state, "query_or_identity": s,
  "request_identity": sha256}` — one per observation, in order, keyed by the exact request.
  The key is the COMPLETE effective request (task 2b; H-5): a request that sets nothing
  beyond its query/identity/target keeps that bare text; any other field the gateway acts
  on (kind, cursor, filters, limit, posture, a catalogue browse) makes it a JSON key, so two
  different requests never share one. Recovery (fail → ok) is a transition and is
  never deduplicated away; capability-fact answers, transport failures and failed
  polled jobs all land here, not only lane lists.
- The `gateway` source (lines marked `"scope": "gateway"`) is not a lane: it records the
  gateway transport for the request. `provider_unavailable` there means the gateway itself
  did not answer; `searched_ok` there means ONLY that it answered this request — never that
  any lane searched or found anything (lane lines carry that) — and it is not written for an
  answer still pending (`queued`/`running`). A line with `coverage: unknown` and
  `request_type: telemetry` announces activity lines that could not be written (their
  count and why): lost telemetry is explicit, never silent, and the tool result that lost
  them carries `activity_capture: {"captured": false, "loss": ...}`.
- Chassis → queue: the result record carries `research_failures` (requests whose FINAL
  state is degraded, each with its key), `research_ok` (keys whose final state
  cleared), and `research_coverage` (each source's last state — accumulated on the item
  for the completion stamp). The runner keeps `research_blockers` per item, KEYED BY
  REQUEST: a `provider_unavailable`/`auth_failed` final state adds the request; only
  the SAME request succeeding clears it — a success on an unrelated query never does.
  Historical failures still never become permanent vetoes: the operator releases a
  blocker explicitly with `research-loops resolve-research <id> --reason ...` (a
  recorded evidence decision). An ordinary pause/resume never touches blockers.
- Gate (one condition, used for BOTH saturation eligibility and every automatic
  completion branch): an iteration that recorded a blocking coverage state and
  produced no qualifying semantic change does not advance the saturation streak and
  cannot be the completing pass; reaching the streak limit with unresolved blockers
  HOLDS completion. A completed topic stamps the accumulated coverage map and policy
  it completed under (`completion_coverage`) so a later source-family addition can
  trigger a targeted refresh without invalidating the earlier research.
- Station downloads are TEMPORARY: the chassis provides a per-iteration directory
  (`RESEARCH_LOOP_DOWNLOAD_DIR`) and removes it on every exit path; the agent copies
  what it keeps into the topic's own files during the iteration. Names carry the
  file/revision identity and are created exclusively — never overwritten.

## 3. Discoverability (D-31)

The surface teaches; an agent never has to guess a source's shape:

- `research_sources` is the registry projected for agents — capabilities, domains,
  commercial verdicts, and each statistical source's EXACT declared data contract
  (adapter-owned `DATA_PARAMS`, pinned by tests). Public-safe fields only.
- `research_data` validates against the declared contract BEFORE any budget is spent;
  a bad call returns the contract and a working example instead of an upstream error.
- `research_files` listings carry a ready-made `download_request` per file — the
  arguments pass straight to `research_download`.
- Under a bound topic, the operator-owned policy fields are enforced but not
  advertised in tool schemas.

## 4. Correlation and observation (task 2b; INVARIANTS H-1, H-5)

- The caller's invocation and attempt travel in headers on BOTH front doors (`/v1/*` and
  `POST /mcp`): `X-Research-Invocation` (1–128 of `A-Za-z0-9._:-`) and
  `X-Research-Attempt` (a positive integer: the caller's attempt at this exact request —
  1, then one more for each retry). They travel together; a malformed or half-given pair
  is refused with 400, never dropped — and every RESEARCH request needs them (task
  2b-repair A5: find, resolve, enrich, fetch, data, a download, a batch, a job poll, on
  either door; none is ever run unattributed — 400, or an in-band `gateway_error_400` tool
  result). Health, status, the source registry and the MCP handshake are not research and
  need none. There is no maintenance exemption: an operator's manual query names an
  invocation too. A grant's requests carry the grant's invocation and the caller's own
  attempt — never a default. They never enter the payload, cache keys or the job dedup
  hash. The stdio client sends them when `RESEARCH_INVOCATION_ID` is set (without it, its
  research calls are refused), numbering each repeat of the same effective request — and
  each poll of a job — as the next attempt.
- Every call row (`gateway.calls`: lane dispatches, redirect hops, cache hits, local-index
  lookups, request and coalesce rows) carries `invocation_id`, `attempt` and
  `request_identity`; a queued job keeps its CREATOR's. The schema's trigger refuses any
  later change to them (immutable once written).
- Every answer names its `effective_request` and `request_identity`, and carries the
  caller's own `observation`: `invocation_id`, `attempt`, `request_identity`, `served`
  (`dispatched`, `coalesced` onto another caller's in-flight job — then `dispatched_by`
  names that caller —, `cache`, `queued`, `rejected`), `job_id`, and the durable-capture
  acknowledgement: `captured` with the caller's own request row `call_ref`, or
  `capture_loss` saying why it was not written (no database; a failed write). The
  observation is added per caller at the front door, never inside cached or stored
  content, so shared content keeps the dispatcher's identity. A raw-bytes download
  carries it in the `X-Research-Observation` header, which the station client keeps beside
  the bytes as `observation` (or says it was absent, `observation_loss`: never dropped).
- A job poll (`GET /v1/jobs/{id}`, `research_job`) is research like any other request
  (2b-repair A5): bound to the caller (a grant naming another invocation is refused, 403)
  and recorded as a durable `poll` row in `gateway.calls` under the CALLER's invocation and
  attempt. The job answer carries the caller's own `observation` (`served: polled`, its
  `call_ref` or `capture_loss`); when the job was created by another invocation or attempt,
  `dispatched_by` names it — a shared job never lends its creator's identity to the caller.


## 5. The supported provider-input contract (trust model B)

Operator rulings of 2026-10-02, recorded in INVARIANTS B-1 (Gate D #2). **Trust model B:** the gateway guarantees a complete contract for *supported provider input*; first-party adapters are trusted,
reviewed code, held to their discipline by declared-read inventories, import and parser guards, mutation tests with positive controls and review — a documented design boundary, not by-construction
confinement against deliberate misuse (§2, "The guarantee, exactly"). **Input outside the policy below fails visibly — the lane is unavailable — and is never read as something shorter, emptier or
different.** This is the gateway's policy. It does not claim that every provider uses exactly this subset, and it is not a provider qualification: Phase 4 qualifies the live providers against it.

| Layer | Supported | Outside it (the lane is unavailable) |
|-------|-----------|--------------------------------------|
| Transport | a complete HTTP message: the declared Content-Length met, or chunked framing terminated; a body of at most 256 MiB; a response with neither (close-delimited) is accepted, see below | a body short of its Content-Length; chunked framing with no terminal chunk; Transfer-Encoding together with Content-Length; a coding other than `chunked`; a Content-Length that repeats, is a list or is not digits; a body past 256 MiB (a declared length past it is refused unread) |
| Encoding | UTF-8 only, for JSON, XML and CSV; a leading byte order mark is ignored in JSON and XML and is data in CSV | UTF-16/32, Latin-1 and every other encoding; an invalid UTF-8 sequence (an encoded surrogate included), which is an error and never U+FFFD; an XML declaration of another encoding |
| JSON (RFC 8259) | each name once in an object; finite floats; exact integers (of any size to Python's 4,300-digit conversion limit); nesting of at most 64 levels | a duplicate name; `NaN`, `Infinity`, `-Infinity`; a number that does not fit a double (`1e999`: never read as infinity); an integer past the conversion limit; nesting past 64; anything RFC 8259 refuses |
| XML (SDMX-ML) | well-formed XML 1.x in UTF-8; the SDMX-ML 2.1 vocabulary, by expanded name (namespace URI and local name — the prefix is only a spelling), with the four elements the standard declares unqualified (`Ref`, `URN`, and a structure-specific data message's `Series` and `Obs`); a scalar element that holds no child element; nesting of at most 64 levels | a DOCTYPE; a declared version that is not `1.x`; an element of a name the schema reads in a namespace it does not read it from (another SDMX-ML version, 2.0 or 3.0, included); a scalar element that holds a child element (its first chunk is never taken); nesting past 64 |
| CSV (RFC 4180, with stated extensions) | quoted fields closed and followed by a comma or the line end; LF-only lines; no final newline; blank lines; short rows (a missing cell is nothing); extra cells (kept in the row's raw, never read); a bare CR inside a quoted field (data); cells of at most 131,072 characters | an unclosed quote; text after a closing quote; a quote inside an unquoted field; a bare carriage return outside a quoted field; a cell past 131,072 characters; a header that names a column the schema reads twice |
| Snapshot (a local JSON Lines file) | one source object per line, each line read on its own; a line refused is counted and named, the lines around it are loaded | a file that cannot be read, decompressed or framed fails the load |
| Headers | `Link` read to its last character (RFC 8288); `Retry-After` as `delay-seconds` (ASCII digits) or a date the library's email-date parser reads, a zone-less date being GMT | a `Link` header that does not read through (neither a continuation nor an end); a `Retry-After` that is neither |

The two information-bearing predicates (§2) are part of the policy, not exceptions to it: `Rec.empty`, used only at the reviewed provider-shape predicates, and `Rec.same_as`, equality between
decoded provider objects, used only for the intended comparisons (Unpaywall's best-location check) and never for a value an adapter minted. Both are listed in `gateway/tests/inventory.py`.

**Compatibility limits, stated.** Valid general XML that the policy refuses — a DOCTYPE, a non-UTF-8 document, a namespace other than SDMX-ML 2.1's — is a supported-message restriction, not a claim that
such XML is malformed; the 13c Gate C review read the BIS, ECB, SDMX 2.1, OpenAlex and DOAJ public documentation and found no provider contract that requires those forms (and 2b-repair-14 read the SDMX 2.1 schemas for the namespaces and the unqualified forms), which is a bounded result and no certificate. A structure-specific
data message whose `Series` and `Obs` are qualified in the data structure's own namespace (rather than unqualified, as SDMX 2.1 declares them) is outside the policy and fails visibly until a
provider needs it. Duplicate JSON names are refused although the grammar permits them (RFC 8259 §4 leaves their meaning unpredictable). **Close-delimited bodies:** a response whose only end is the
connection closing (RFC 9112 §6.3) cannot be told from a deliberately shorter body by anything the gateway can see; a CSV cut at a record boundary in such a response is a well-formed shorter
document and loads as one, and a Content-Length or chunked response cut the same way does not. **What is not claimed:** that every provider response is within the policy; that an unused provider
field is valid (nothing is validated that no field reads); universal XML support or an XSD engine; proof over arbitrary adapter programs; live canaries (Phase 4).
