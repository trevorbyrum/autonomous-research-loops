# Task 2b-repair-8 — make member isolation structural; parse uncertainty is never an end

Read first, in full: `~/work/research-loops-public/private/reviews/gen2-2b-repair-7-astra-review-20261001.md` (R7-1, R7-2, the "unchanged on purpose" ruling), with evidence in `~/work/research-loops-public/private/evidence/astra-2b-repair-7/` (`blocker_regressions.py`, `hf_sdk_probe.py`, `hf-files-probe.json`, `independent-probes.json`, `raw-iteration-audit.txt`, `independent-mutants.json`). Then read the charter sections "Root-cause fixes, not patches" (especially the third-round rule), "Evidence is durable", and the no-personal-data rule.

**Accepted and not to be touched:** F1, F2, F3's shared router decision, F3-R1 (local-index population identity), the provider evidence and `PROVIDER-PAGINATION.md`, and the individual adapter conversions to `members()`/`first_member()`.

## R7-2 — member isolation must be a property of the data, not of a name scan (redesign)
This is the **third round of the same defect family**: Socrata (`f64d20c`), then OpenCitations and eight more paths (`cbba585`), and now Hugging Face file siblings and ECB datasets still lose readable records to one malformed peer. The bypass check in `tests/test_member_decoding.py` scans for builder names in loops. It misses filter comprehensions (`[r for r in rows if r.get(...)]`), `while` loops, aliases (`build = make_record`), direct `rows[0]` indexing, and helpers outside `adapters/` such as `core/sdmx.py`. **Per the charter, don't add more scan patterns. Redesign so raw provider lists can't be iterated at all except through isolation.**

A suggested shape (choose your own if it removes the cause better):
- the shared payload accessor (`need()` and its relatives) never hands an adapter a plain list of raw provider members;
- it returns an opaque member sequence whose only operations are isolated decoding (`members()`, `first_member()`, with `OMIT` and dropped-member accounting), including nested lists whose members become records.

The property then holds by construction, and the remaining check is simple: a raw list escaping that wrapper.

**Required fixes inside this redesign:**
- Hugging Face file siblings (`adapters/huggingface.py` ~line 44);
- ECB datasets, where `core/sdmx.py` ~line 88 flattens before decoding;
- OpenCitations' metadata lookup, which still reads `rows[0]` outside `first_member()`.

**Keep:** licence and membership checks, and explicit dropped-member accounting. Astra's justified exceptions stand: the local index, genuine single-object resolves, GovInfo/OpenML derived file lists, Socrata portal vouching, FRED/Census/BEA rows, and catalogue entries (a separate contract, owner pending with the operator). The Hugging Face file-list and ECB dataset exemptions are rejected.

**Tests:**
- mixed Hugging Face sibling and mixed ECB dataset regressions, each with a readable control;
- Astra's OpenCitations preprocessing-bypass mutant, rebuilt and killed;
- each of Astra's checker-bypass shapes (filter comprehension, while, alias, `rows[0]`) shown to be impossible or caught under the new design.

**Docs:** correct the universal claims in `base.members`, `STATION-CONTRACT.md` and elsewhere to state exactly the property that is enforced.

## R7-1 — a link that can't be parsed is never an end
The `Link` parser (`adapters/base.py` ~line 134) splits on every comma, including one inside a quoted parameter, so `<…cursor=next>; title="next, page"; rel="next"` loses its relation. The Hugging Face adapter then reads the missing link as absent and claims exhaustion.

**Required:**
- Parse `Link` per RFC 8288: quoted parameters, multiple link values, and parameters in any order.
- Keep **parse uncertainty distinct from established absence**. An unparseable or ambiguous header yields an honest partial, never `exhausted: true`.
- Apply the same rule anywhere an adapter derives an end from parsing provider metadata.
- Retain URL and credential validation.
- Tests: a routed quoted-comma regression; multiple-link and reordered-parameter cases; a mutation-sensitive assertion that parser failure cannot produce exhaustion.

## Completion report (charter rule)
State each root cause in one sentence and why the change removes it **for every path**, naming the structural mechanism. The Remaining section must be literally true. Owners for the OpenAIRE deprecation, the Kaggle endpoint drift and catalogue partial results are pending with the operator. List them as pending; don't assign them.

## Constraints
Branch gen2 only. No live calls to provider APIs and no personal data in any request. Never run a migration against a real database, and never touch `~/work/staging/research-gateway-wt`, its database or `research-gateway.service`. Write evidence to `~/work/research-loops-public/private/evidence/2b-repair-8/`. Small commits with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with final unpiped `make gen2-check` and `make gen2-gateway`, waited on in your turn. Report net lines for the engine and gateway separately.
