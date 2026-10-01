# Task 2b-repair-11 — R10-1..R10-3: oracle additions (11a), then fixes (11b)

Source: `~/work/research-loops-public/private/reviews/gen2-2b-repair-10-astra-review-20261001.md`; evidence in `~/work/research-loops-public/private/evidence/astra-2b-repair-10/` (`new_corruptions.py`, `new-corruptions.json`, `oracle_mutants.py`, `bis-coverage-mutant.diff`, `source-spotchecks.md`).

**Accepted (don't reopen):** the R9-1 URI grammar, the R9-3 import closure, typed reading at the corrected sites, publisher mapping, the per-structure dimension reader, the coverage registry's execution accounting, and the oracle's source-based expectations (qualified).

## 11a — oracle author, from specifications and fixtures only (same rules as 2b-repair-10a)
Add to `gateway/tests/oracle/` only; touch nothing under `gateway/research_gateway/`.
1. **Fallback alternatives beside a valid preferred value (R10-1).** For every documented field pair where a provider supplies alternatives (for example DataCite `rightsIdentifier`/`rights`, BEA `Desc`/`Description`, OpenML `licence`/`license`, and any other pair the provider documentation shows), populate **both**. Then corrupt the alternate while the preferred stays valid. Expected outcome per the accepted contract: a present malformed supported field drops and counts the member, or makes a whole-catalogue answer unreadable under the existing catalogue rule. Cite the documentation that makes each field a supported field.
2. **Flow binding (R10-2).** Multi-flow BIS and ECB messages, with the requested flow first, non-first and last, under different flow orders, plus a requested flow absent from the message. Expected: the label, dimensions and request template all come from the requested flow's own referenced structure. An absent or ambiguous flow yields no template: unobserved or unavailable, never complete.
3. **Unnamed-flow input (R10-3).** An all-unnamed BIS (and ECB) flow listing must be unobserved with no count, beside a readable control.
4. **Evidence corrections:**
   - the populated-variant count is 63, not 61;
   - the independence description must state the disclosed qualifications instead of claiming a clean pre-registered oracle;
   - the OpenML `fetch` explanation must be narrowed as Astra ruled: error 113 and lines 808–817, not "every null or empty url means no file".
Report which new cases fail on the current code.

## 11b — coder (separate agent), against the oracle without editing it
1. **R10-1:** read and validate **every supported operand first, then select**. Remove the short-circuit exemption from `STATION-CONTRACT.md` (~line 137). Sweep every `x or y` / `text(a) or text(b)` site in the adapters, SDMX, loaders and `identity.py` that the 190→182 inventory retained; each must validate all present operands. List every site, and what it does now, in evidence.
2. **R10-2:** select the requested Dataflow first, then its referenced DataStructure, and bind label, dimensions and request to that one selection. A missing or ambiguous target invents nothing.
3. **R10-3:** the BIS `identified(...)` validation mutant must be killed by the oracle's new unnamed-flow case. Keep execution accounting distinct from failure-mode coverage.
4. **Done:** `make gen2-check` and `make gen2-gateway` exit 0 unpiped. Every oracle case passes, unless formally disputed with evidence and left failing.

## Both
Branch gen2. No live provider API calls and no personal data; public documentation and the RFC texts in evidence may be read. Never touch `~/work/staging/research-gateway-wt`, its database or `research-gateway.service`; never run a migration against a real database. Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-11a/` and `.../2b-repair-11b/`. Commits carry `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Completion reports: root cause in one sentence for each fix; a Remaining section that is literally true.
