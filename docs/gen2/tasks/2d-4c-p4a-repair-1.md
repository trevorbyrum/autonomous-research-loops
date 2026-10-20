# 2d-4c-p4a-repair-1: SQL 40 fails open for out-of-domain `/1` summaries (Astra Gates A and C, round 1)

**Subject:** 2d-4c part 4a (`a0f976e`; estimate `db03684`, addendum `dc4237e`).

**Astra round 1** (`private/reviews/gen2-2d-4c-p4a-astra-review-20261020.md`):
- **Gate A BLOCK and Gate C BLOCK** on one finding, B1. Gate B PASS.
- **4a is classed MITIGATION:** activation is incomplete over the raw admission domain. The warm mutation-loader repair is ROOT-CAUSE, and stays as it is.
- Landing at `a0f976e` was green (`gen2-check` 8,482 s, `gen2-gateway` 1,018 s), but green gates don't cover B1.

## B1: SQL 40's performed-status filter fails open
**Where:**
- `gen2/store/schema/40-mandatory-detailed-receipts.sql:10`;
- combined with SQL 37's version-dependent domain guard (`gen2/store/schema/37-detailed-check-receipts.sql:95`);
- and SQL 03's receipt CHECKs.

**The defect:**
- SQL 40 requires a reference only when a summary is `checked_ok`, `checked_problem` or `not_applicable`.
- SQL 37 closes the check-outcome domain for `/2` only. SQL 03 excludes only `not_checked`, `unavailable` and missing values.
- So a raw **`/1` load-bearing positive receipt** with an unrecognized summary skips the presence check. Examples: `succeeded`, `invented`, JSON `1`/`true`/`{}`.
- **Reproduced by Astra** under the complete 338-trigger catalog, foreign keys on, zero detailed-check records, no historical-admission context:
  - `partially_supports` with no adjudication, and `supports` with an adjudication, both **commit without records**;
  - this holds for canonical, own-extraction and validated-extraction bases, in both trigger orders.
- **The layers disagree.** The Router refuses the same operands with `payload_invalid`, and raw insertion then commits them.
- **Consequence:** the adjudicated canonical `supports` row then let an ordinary raw claim update reach `accepted_support`. The blocking defect is receipt admission itself.
- The reproduction script is in the report.

**Required (ROOT-CAUSE):**
- **Current raw load-bearing positive admission must fail closed.** Every new load-bearing `supports`/`partially_supports` receipt must provide all four durable, exactly bound records, whatever its receipt version or summary spelling.
- **Refuse** out-of-domain strings, vocabulary mixing (`/2` words in `/1` or the reverse) and non-string statuses. None of them may bypass presence.
- **Possible approaches** (choose one and justify it in DOSSIER):
  - an unconditional all-four-reference requirement for this use/verdict branch, reusing the existing `/2` domain and binding guards;
  - an explicit closed-domain guard.
- **Keep:**
  - valid sampled and truthful-unsuccessful behavior;
  - historical readback, with no new authority;
  - SQL 03's existing `not_checked`/`unavailable` refusal.
- **DDL:** ordered additive only (SQL 41). Don't edit accepted SQL 01–40. Add `-- trace:` markers and repin both hashes.
- **Tests:**
  - raw-DDL **and** Router regressions, in both trigger orders;
  - canonical and both extraction methods;
  - adjudicated `supports` and unadjudicated `partially_supports`;
  - the full out-of-domain operand set above, string and non-string;
  - an assertion-killed domain-bypass mutant, with a separate accepted control that still passes under the mutation, and a qualified control trace.
- **Family audit:** check whether any other raw consumer (capture, quote, promotion-adjacent triggers) has the same open-domain `/1` gap. Probe it; don't settle for reading.
  - Fix any gap that is part of receipt admission.
  - List any gap that belongs to promotion (4b) in COMPLETION.md, with probe evidence.

## NB1 (fold in): the older extraction-history helper changes trigger order
**Where:** `gen2/tests/test_bound_extraction_support.py:22`.

**The defect:**
- The helper restores the selected triggers by appending them and comparing dictionaries. Definitions are preserved, but order isn't.
- In the reversed catalog, SQL 40 moves from index 0 to index 335.

**Required:**
- Use `restore_triggers(case, None, catalog=definitions)` and assert the ordered catalog, as the new `historical_admission` context does.
- This needs cleaning up before 4b relies on these fixtures for promotion evidence.

## Constraints
- **This is a production repair.** Run the full gates from `docs/gen2/tasks/2d-4c.md`:
  - full `gen2-test` and `gen2-trigger-order`;
  - the composition module;
  - the **full** mutation inventory, because triggers change;
  - the static gates.
- **Environment:** copy the venv with `cp -a`, never symlink it. Wait until no `gen2-landing-*` unit is active before heavy runs.
- **AGENTS.md:** look it up only inside the repository.
- **No provider calls.** Never touch gen-1 runtime state or `127.0.0.1:8765`. Never run a migration against a real database.
- **Don't edit** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER. Don't push or merge.
- **Size:** about 500 hand-written repository lines at most. If it needs more, stop after DOSSIER and report.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4c-p4a-repair-1/`, with a PROGRESS.md kept current and a COMPLETION.md. Every fix is classed ROOT-CAUSE or MITIGATION.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
