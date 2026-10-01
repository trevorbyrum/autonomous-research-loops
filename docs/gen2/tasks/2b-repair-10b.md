# Task 2b-repair-10b — make the gateway pass the independent oracle (R9-1..R9-5)

**Read first, in full:**
- `~/work/research-loops-public/private/reviews/gen2-2b-repair-9-astra-review-20261001.md` (R9-1..R9-5), with evidence in `~/work/research-loops-public/private/evidence/astra-2b-repair-9/`.
- The independent oracle's evidence in `~/work/research-loops-public/private/evidence/2b-repair-10a/`: `README.md`, `failing-cases.md`, `corrections-after-rfc-text.md`, `rfc/`.
- The charter sections "Root-cause fixes, not patches", "Evidence is durable", and the no-personal-data rule.

**What changed this round:** a separate agent wrote `gateway/tests/oracle/` and `gateway/tests/test_oracle.py` from the RFC texts, the provider documentation and the fixtures, without reading the implementation. They currently fail in 191 cases. Your job is to make the **gateway** satisfy them.

## Don't touch the oracle
- **Don't edit** `gateway/tests/oracle/*` or `gateway/tests/test_oracle.py`, and don't change any expected value, vector label or grade there.
- If you believe an oracle expectation is wrong, **don't change it.** List it in your report with the RFC line or documentation excerpt that contradicts it, and leave that test failing. Astra rules on it.
- Oracle independence is the point of this round.

## Required, by root cause
1. **R9-1, URI/Link conformance:**
   - Validate `Link` targets as URI-references and URI-form relation types by the RFC 3986 grammar (Appendix A), not a forbidden-character rule. Malformed means **unknown**, never an end.
   - Resolve relative-reference targets per RFC 8288 §3.1 and RFC 3986 §5.
   - A next link that resolves to the request itself is **not followed** and is **not an end**: it is unknown, reported as partial.
   - Cursor validity per the oracle's cursor vectors.
   - Keep URL, host and credential validation.
2. **R9-2, typed fields:**
   - Validate every present value before any fallback (`a or b`) chooses between spellings: OpenML `licence`/`license` on the find path, and read `license` in resolve and fetch where the documentation supports it.
   - Also fix the oracle's populated-variant findings: a wrong-kind DOAJ journal `ref` must drop and count, not vanish; Europe PMC `isOpenAccess` of the wrong kind must not read as `False`.
   - Search for the same `x or y` / truthiness-fallback pattern across every adapter; don't rely on the named sites.
3. **R9-3, imports:** the import check must analyse or refuse module imports whose reachable names it can't bound, including parser attributes reachable through admitted package modules such as `core.cache.json`. Add Astra's complete mutant as a regression, with a permitted module-use control.
4. **R9-5, catalogues:** the BIS and ECB catalogue cases now execute. A dimension browse in a multi-structure message must not merge structures: keep each structure's own dimensions, without duplicates. Fix the BIS data message read as two series if the documented message says otherwise.
5. **`publisher`:** map it wherever the canonical record contract defines it and the provider supplies it (DataCite find/resolve, DOAJ journal resolve, CORE full text), per the oracle's tagged sources.
6. **`openml.fetch` url members** (oracle `MixedMembersOtherSeeds`): decide from OpenML's documented payload which side is right. If the gateway is wrong, fix it. If the harness generator is wrong, fix the generator: it's in `gateway/tests/invariant_*.py`, which is not the oracle. Explain which and why, citing the documentation.
7. **R9-4 is the oracle itself:** the old metamorphic `run(op, valid)` baseline may stay as supplementary coverage, but stop describing it as independent anywhere in docs or tests.

## Done means
`make gen2-gateway` and `make gen2-check` exit 0 unpiped, with every oracle test passing except any you formally dispute in your report. The oracle's router-output mutants must still be caught.

## Completion report (charter rule)
- State each root cause in one sentence, and why the change removes it for every path.
- List every disputed oracle expectation, with its evidence.
- The Remaining section must be literally true.

## Constraints
- Branch gen2 only.
- You may read public documentation and the RFC texts in the 10a evidence folder. No live calls to provider APIs and no personal data.
- Never run a migration against a real database, and never touch `~/work/staging/research-gateway-wt`, its database or `research-gateway.service`.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-10b/`.
- Commit messages carry `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Never mask `make`'s exit status. Report net lines for engine and gateway separately.
