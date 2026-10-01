# tests/oracle — independent oracles (task 2b-repair-10a)

Written from specifications, documentation and the harness's valid fixtures by an author who did not read the gateway's adapter, payload, SDMX or canonical code. A
QUALIFIED, source-based oracle, not a clean-room or fully pre-registered one: the author saw some harness internals and production signatures, ran the gateway as a black box
for answer shapes, and changed or removed some expectations after seeing its output (the ledger and every qualification: evidence/2b-repair-11a/independence-statement.md).
They are meant to FAIL wherever the gateway disagrees with those sources; a failing case here is a finding, not a broken test, until a ruling says the specification reading
was wrong. The fixing is a separate author's (2b-repair-10b, 2b-repair-11b).

| module | holds | consumed by |
|---|---|---|
| `link_vectors.py` | RFC 3986 / RFC 8288 `Link` header vectors, each with its expected interpretation (next URL, known absence, unknown), a grade and an RFC section; plus an independent reference grammar that checks the hand-written labels | `test_oracle.LinkConformance`, `VectorsAreConsistent` |
| `expected_records.py` | hand-written identities and canonical fields of every harness operation's valid answer, each field with its source tag; the fields left out and why (`UNDOCUMENTED`) | `test_oracle.ExpectedCanonicalFields` |
| `variants.py` | every fixture again with its provider's documented optional fields populated (OpenML `licence`/`license`, DOAJ journal `ref`, ...) | `tests/invariant_ops.py` appends them to the harness's tuples (the corruption pass reaches them); `test_oracle` runs them with the base operation's expectations |
| `xml_ops.py` | BIS and ECB catalogue execution cases (SDMX-ML) and the BIS data message, with the answers the messages say | `test_oracle.Catalogues` |
| `loaders.py` | valid pages for the Crossref journals, DataCite repositories and OpenAlex sources loaders, and the venue and repository records they must produce | `test_oracle.RegistryLoaders` |
| `coverage.py` | an execution recorder (wraps `Client` and `router.execute`) and the universe of operations; an operation is covered only if it ran, and what is not run is listed with its reason | `test_oracle.ExecutedCoverage` |
| `mutants.py` | damage to the router's answer (erased titles, fabricated records, ...) that the expectations must notice | `test_oracle.OracleNoticesMutants` |

Run: `python3 -m unittest tests.test_oracle` from `gateway/`. `ORACLE_EVIDENCE=<dir> python3 -m unittest tests.test_oracle.Evidence` writes the vectors, the
expectation sources and the coverage universe as JSON.

Adding a source, an operation or a capability: give it an `Op` in `tests/invariant_ops.py`, its hand-written expectation in `expected_records.py`
(or leave the field out and list it in `UNDOCUMENTED`), and a case that runs it; `ExecutedCoverage` fails on a seed capability no execution reached.

2b-repair-11a adds `fallbacks.py` (a malformed alternative beside a valid preferred value, R10-1), `flow_cases.py` (which flow a BIS/ECB browse answers, and a listing whose flows
name no id, R10-2 and R10-3) and, in `coverage.py`, failure-mode accounting kept distinct from execution accounting.
