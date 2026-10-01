"""Independent oracles for the gateway invariant harness (tasks 2b-repair-10a and 2b-repair-11a): a qualified, source-based oracle.

Expected values come from specifications (RFC 3986, 8288 and 9110, read as text), provider documentation, the repository's contracts and the harness's valid fixtures; no
adapter, `core/payload.py`, `core/sdmx.py` or `core/canonical.py` body was read. That is NOT the same as an untouched, pre-registered, clean-room oracle, and it is not claimed
to be: only the link vectors and expected records were committed before any comparison with the gateway (e4b7eac; the 11a cases in caf4b13); several expectations were changed or
removed after the gateway's output was seen; the author saw the harness's old Link reader's constants and two harness wrapper bodies, read production signatures and docstrings,
and ran the gateway as a black box to learn answer shapes and which documented fields it reads. The full statement, with every qualification and the ledger of changes, is
evidence/2b-repair-11a/independence-statement.md (and 2b-repair-10a/corrections-*.md). Where a specification or document does not decide a case, the vector or field says so (a
`grade` of "judgement", or a field left out and listed in `UNDOCUMENTED`) rather than guessing. Coverage of field mappings is limited to what is documented.
"""
