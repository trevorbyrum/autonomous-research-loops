# Task 2b-repair-12 — fix R11-1 and R11-2

**Read first, in full:**
- `~/work/research-loops-public/private/reviews/gen2-2b-repair-11-astra-review-20261001.md`, findings R11-1 and R11-2, and the required corrections.
- Astra's probes and results in `~/work/research-loops-public/private/evidence/astra-2b-repair-11/`.
- The charter sections "Root-cause fixes, not patches", "Evidence is durable", and the no-personal-data rule.

**Accepted and not to be touched:** the scalar fallback mechanism (`base.preferred` / `identity_from`), requested-flow selection, failure-mode accounting, every earlier accepted item, and the oracle files (`gateway/tests/oracle/*`, `gateway/tests/test_oracle.py`). Don't edit the oracle; add new tests elsewhere.

## R11-1 — decode an alternative's supported contents before choosing it
Today a correctly typed outer container is checked, but its supported nested contents are decoded only after selection. So a malformed fallback value hides behind a valid preferred one. Astra reproduced 20 failing cases.

**Fix the three named sites:**

| Site | Malformed input | Required result |
|---|---|---|
| Unpaywall `best_oa_location` (`adapters/unpaywall.py` ~27) | `{"url": false/0/[]/{}}` beside readable `oa_locations` | decoded as a location; all three locations retained as partial with `payload_invalid` |
| ECB SDMX-JSON alternate `structures` / `data.structure` / `data.structures` (`core/sdmx.py` ~68, early return) | `false`, `0`, `[]`, string | unreadable/unobserved, no count |
| Crossref journals loader `ISSN` beside a valid `issn-type` (`harvest/registries.py` ~61) | malformed member | skip and report the journal |

**Then find the rest.** Find every other alternative whose decoding happens after selection, and fix the cause: each supported alternative is fully decoded, its nested supported contents included, before any choice. Validating arbitrary unused fields is not required.

**Tests:** add Astra's three nested forms beside valid preferred values, each with readable and alternate-only controls.

## R11-2 — contradictory structure references are refused, not reduced to the first
`dataflows_xml` (`core/sdmx.py` ~192) takes the first `Ref` via `next(...)` before checking for ambiguity. The SDMX 2.1 schema (DataflowType, ReferenceType) allows one structure reference: one `Ref` with an optional `URN`, or a `URN` alone. When both appear, they must name the same object.

**Required behaviour:**
- Retain every reference alternative and validate them together.
- Multiple or conflicting references produce no template: unreadable or unobserved.
- A `Ref` plus a matching `URN` is fine.
- URN-only stays the disclosed unsupported case, with no template.

**Tests**, for both BIS and ECB:
- both orders of two `Ref`s;
- `Ref` with a conflicting `URN`;
- `Ref` with a matching `URN` (control);
- `URN` alone (control).

## Also
Narrow the claim made for the structural lazy-choice scan in `test_alternatives.py` and the docs. Astra showed an ordinary-spelling bypass, so describe it as a guard, not a proof. Correct the minor source citation Astra flagged.

## Done means
- `make gen2-check` and `make gen2-gateway` exit 0, unpiped.
- Astra's R11 reproductions pass.
- Every oracle case still passes.

## Constraints
- Branch gen2 only.
- No provider API calls and no personal data. Public documentation such as the SDMX schemas may be read.
- Never run a migration against a real database. Never touch `~/work/staging/research-gateway-wt`, its database or `research-gateway.service`.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-12/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Completion report: one sentence per root cause, net lines, and a Remaining section that is literally true.
