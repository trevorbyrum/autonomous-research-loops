# Task 2b-repair-7 — finish F3: stable local paging, provider-grounded end rules

Read first, in full: `~/work/research-loops-public/private/reviews/gen2-2b-repair-6-astra-review-20261001.md` (F3-R1, F3-R2, the adapter audit table, the limitation rulings), with evidence under `/tmp/gen2-2b-repair-6-astra-review-20261001/` (`provider_probe.py`/`.json`, `provider-evidence/`, plus the changing-index probe). Then read the charter sections "Root-cause fixes, not patches" and the standing rule on live network calls.

**Accepted and not to be touched:** F1, F2, and F3's shared router decision (exhaustion only on an adapter's own end report; otherwise partial). Everything else in 2b stays accepted. The router can't make an adapter's wrongly derived end report true, so this task makes each adapter's end report true.

## F3-R1 — local-index paging must not skip rows when the index changes
Astra reproduced it. Five matches; page one returns `0000`,`0001` with continuation `2`; `0000` is then removed from the index; page two returns `0003`,`0004` marked complete and exhausted. `0002`, still a converted match throughout, was never returned. The offset is applied to a freshly read population on each request, and the one-row lookahead proves only that this offset is at the current tail. **Required:** bind the traversal to a stable result population, or detect that the population changed and return an honest partial or unobserved result without exhaustion. Account for deletes, inserts, and ordering or membership changes, including search-cache reuse; offset arithmetic alone won't do. Tests: a stationary control, plus a mutation-sensitive changing-index reproduction covering delete, insert, and reorder.

## F3-R2 — Hugging Face must follow the provider's own pagination
The official `huggingface_hub` client follows the response `Link: rel="next"` header and treats its absence as the end. The adapter (`gateway/research_gateway/adapters/huggingface.py`, ~line 56) ignores it, invents `offset + len(items)`, and reports exhaustion on any short body. **Required:** follow the next-link protocol, keeping the gateway's URL validation and credential boundaries (a next URL must stay on the provider's host and carry no injected credentials). Or, where continuation is unsupported, emit an honest partial. Never claim exhaustion while a next link is present, and never invent numeric paging. Tests: full and short pages, each with and without a next link, and proof that the second request uses the provider's cursor URL.

## Provider-grounded end rules for every find adapter
For each find adapter (local index, Crossref, DataCite, DOAJ, Europe PMC, GovInfo, Dataverse/QDR, Hugging Face, Kaggle, OpenAIRE, OpenML, Semantic Scholar, Socrata), the rule that produces `exhausted: true` must rest on **primary provider evidence**: the provider's official API documentation, or provider-owned client or SDK source.
- Record each rule in a provenance file (for example `gateway/docs/PROVIDER-PAGINATION.md`) with the source URL or package and version, the date read, and a short quoted excerpt. Then add offline fixtures for that provider's real continuation, end, absent-metadata and cap shapes.
- Where primary evidence can't establish a terminal signal, the adapter must not claim exhaustion on it; report partial instead.
- Fix the tests Astra flagged as not isolating a branch, for example Europe PMC's and GovInfo's "unchanged cursor" tests, which also supply an empty body.
- **Allowed:** reading public documentation pages and installing or reading provider-owned client packages.
- **Not allowed:** live calls to provider APIs. The charter forbids personal data in any live call; don't use the operator's email or any other identity anywhere.

## Pre-existing A4-class defect (found by Astra, not introduced by 2b-repair-6)
A mixed Socrata array that contains a non-object loses the whole page in a domain-cache comprehension that runs before members are decoded. Astra reproduced the identical behaviour on `d7cd61b`. It's 2b's malformed-member contract (A4: isolate member failures, keep readable members as a partial lower bound), so fix it here with a regression and a control.

## Completion report (charter rule, enforced this time)
State each root cause in one sentence and why the change removes it. The **Remaining** section must list every open item with its actual owner. "Remaining: NONE" only if literally true. Astra rejected the last report's "NONE". Already-owned items that stand: Phase 4 for the real-data migration and for live provider canary qualification; withheld rows halting paging ends at that migration.

## Budget and constraints
Engine 9,713, gateway 9,333. Keep it as narrow as the evidence allows; report net lines separately. Branch gen2 only. Never run any migration against a real database, and never touch `~/work/staging/research-gateway-wt`, its database, or `research-gateway.service`. Small commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with final unpiped `make gen2-check` and `make gen2-gateway`. Don't end your turn waiting on a background run.
