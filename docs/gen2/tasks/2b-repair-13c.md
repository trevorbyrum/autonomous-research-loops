# Task 2b-repair-13c — gateway: strict byte openers; sealed provenance through the canonical record

**Source:** Astra's 13a review, `~/work/research-loops-public/private/reviews/gen2-2b-repair-13a-astra-review-20261002.md`, and its evidence in `~/work/research-loops-public/private/evidence/astra-2b-repair-13a/`: `new-parser-probes*.json`, `index-zero-probe.json`, `escape-probes.json`, `copy-escape-tree/`, `per-test-audit.md`. Read them in full.

**Runs after 2b-repair-13b.** Keep everything 13a got accepted, finding by finding: R12-1..R12-5, Gate D #1 and Gate D #2. The oracle stays unedited.

## Family cause (unchanged): the decoder's contract with the rest of the gateway is incomplete
13a closed three gaps: failure escape, untyped decision fields and raw response access. Astra found the two places where the contract still stops short.

1. **The opener layer (R13A-1).** Decoding starts *after* a permissive lexical parser has already resolved bytes into structure. Python's `csv` default dialect accepts unterminated quotes and junk after a quote, so a malformed DOAJ CSV loads as **zero journals**, a false successful empty result. Treat this as a layer, not as one CSV bug:
   - inventory **every byte opener** that feeds a provider-input decision (CSV, JSON, XML and any other);
   - for each, state what malformed lexical input it silently accepts or resolves, judged against the format's specification.

   Known candidates:
   - CSV: non-strict quoting, and duplicate header names (last one wins);
   - JSON: duplicate object keys (`json.loads` keeps the last), and the non-standard `NaN`/`Infinity` tokens;
   - XML: whatever ElementTree resolves silently. Check it; don't assume.

   Malformed framing must fail through `PayloadError`. An ambiguous supported field, such as a duplicate key or column the contract reads, must fail and must not pick a reading. Valid multiline quoted fields and the accepted short-row and extra-cell policies stay as they are. **Test by corrupting serialized bytes,** not by generating rows with a well-behaved writer.
2. **The materialization exit (R13A-2).** `make_record` returns `plain(rec)`, so a record's `raw` and `extra` are readable provider values in adapter code. A record built with `raw=row.raw` let a passive field decide selection, and no scan noticed. The fix:
   - provenance (`raw`, plus `extra` built from passive values) stays **opaque** for as long as adapter selection and coverage decisions can run;
   - it is materialized only at the trusted serialization or storage boundary, the router's answer and evidence write;
   - every indirect exit is covered: canonical-record construction, `download()`, and any other route Astra's `escape-probes.json` lists.

   Once this is structural, the source scan is a backstop, not the guarantee.
3. **Test-claim rewrites (Gate C).** Astra's `per-test-audit.md` lists **10 overbroad test claims**. Rewrite each so it asserts only what it checks, keeping the narrow regression. In particular:
   - the "XML schemas too" totality test actually selects JSON schemas;
   - the named-accessor tests don't prove exclusive byte access;
   - the copy-independence tests don't prove opacity.
4. **State the scope of the claim precisely.** "Only `decode` opens bytes" applies to *payload decisions*. The client still opens bytes for HTTP diagnostics and call-log bookkeeping (e.g. `adapters/base.py:85`). Either route those through the same opener or narrow the documented claim to what is true.

## What can't be closed by construction in Python (do not attempt; list it)
`x is None` on a `Passive` can't be intercepted, private names are reachable, and a hostile corpus is finite, not a proof. These are language-level limits. **Don't build workarounds for them.** List them in the completion report as the residual set that needs the operator's ruling.

## Done means
- Astra's R13A-1 byte probes and R13A-2 copy-escape mutant are rebuilt as regressions and fail on `2d62753`.
- A byte-corruption family runs for every opener in the inventory.
- `make gen2-check` and `make gen2-gateway` exit 0 when run unpiped.
- The oracle is unedited.
- The differential against `2d62753` has every difference justified.

## Constraints
- Branch gen2, gateway only.
- No provider API calls; public documentation (RFC 4180, RFC 8259, the XML spec, Python docs) is allowed.
- No personal data.
- Never touch the live gen-1 gateway.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-13c/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Completion report:
  - the opener inventory with each opener's strictness ruling;
  - how provenance opacity is enforced;
  - each root cause in one sentence;
  - net lines;
  - a literally-true Remaining section that includes the language-level residual set.
