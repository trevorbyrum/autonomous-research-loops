# Task 2b-repair-10a — independent oracles, written from specifications only

**Why this task exists:** Astra's review of 2b-repair-9 (`~/work/research-loops-public/private/reviews/gen2-2b-repair-9-astra-review-20261001.md`, findings R9-1, R9-4, R9-5) found that the invariant harness's expectations were partly derived from the code under test (`baseline = run(op, valid)[0]`). It also found that the "independent" `Link` reader shares production's faulty URI rule, because one author wrote both. **The root cause is shared authorship of code and oracle.** This task fixes that: you write only tests and expected values, from specifications and fixtures. A different agent will then fix the code against your tests (task 2b-repair-10b).

## The one hard rule
**Do not read the implementation.** Don't open `gateway/research_gateway/adapters/*.py`, `core/payload.py`, `core/sdmx.py`, `core/canonical.py`, or the existing `gateway/tests/invariant_*.py` and `test_invariants.py` internals. You may read:
- the specifications: RFC 3986 (URI), RFC 8288 (Link), and the provider documentation captured in `~/work/research-loops-public/private/evidence/2b-repair-7/` and indexed in `gateway/docs/PROVIDER-PAGINATION.md`;
- the contracts: `gateway/docs/STATION-CONTRACT.md`, `docs/gen2/INVARIANTS.md` (RG-4, H-5), and the canonical record field list wherever the contract documents it;
- the valid fixtures the harness uses, as data, and only the public test entry points you need in order to invoke an operation (the harness's operation table and how to run one operation through the router). Read the signature, not the body.

State in your report every file you opened.

## Deliverables (tests and data only; no production code)
1. **URI/Link conformance vectors** (`gateway/tests/oracle/link_vectors.py`):
   - valid and invalid `Link` headers and `rel` values built directly from the RFC 3986 and RFC 8288 grammars: percent-escape validity, IP-literal brackets, non-ASCII, empty, quoted-string escapes, multiple links, unknown and URI extension relations;
   - for each, the expected interpretation: a next URL, a known absence, or unknown;
   - cite the RFC section for each class.
2. **Expected canonical fields for every valid fixture** (`gateway/tests/oracle/expected_records.py`):
   - for each harness operation's valid answer, write by hand, from the fixture data and the documented field mapping, the identities and canonical field values the gateway must produce, including registry-loader records;
   - where the mapping isn't documented, say so explicitly and leave that field out rather than guess.
3. **Populated optional-field variants:** for each fixture, add a variant that populates the supported optional fields the minimal fixture omits (for example OpenML `licence`/`license`, DOAJ journal `ref`), so they enter the corruption domain.
4. **Executable coverage registry:** a mechanism where each operation counts as covered only if it actually executed during the harness run (recorded by instrumentation, not asserted by a list). Include BIS catalogue execution cases and the catalogue sub-operations; dimension browsing is either covered or listed with a reason.
5. Wire 1–4 into the harness as **additional** assertions next to the existing metamorphic ones. Expect them to **fail** on the current code at least for the R9-1 URI cases, R9-2 OpenML licence and R9-5 BIS. Report exactly which fail and why. Don't fix production code.

## Constraints
Branch gen2 only. Tests and data only; touch nothing under `gateway/research_gateway/`. No live network calls and no personal data. Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-10a/`. Commits carry `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Run `make gen2-gateway` unpiped at the end and report its result: failures in your new oracle tests are expected and must be listed one by one; any other failure is yours to fix. Finish with a completion report listing every file you opened, every new expectation's source (RFC section, doc excerpt or fixture field), and the failing cases.
