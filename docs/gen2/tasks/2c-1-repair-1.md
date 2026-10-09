# 2c-1-repair-1: research windows for E-4 (Astra 2c-1 round 1, F1–F3, N1, N2)

**Source:** Astra's review `private/reviews/gen2-2c-1-astra-review-20261009.md` (verdict BLOCK on A and C, PASS on B), pinned to `bd0a989`. Under review-throughput rules this is **round 1 of 3**; the next review checks only the blocking findings below.

**What passed and must stay as it is:** E-1, E-2, E-3, E-5, E-7 and E-8; the four candidate counts; unknown handling; the split between accounting (pure arithmetic) and the Router (reads only, inside one `_snapshot()`); DEBT-030 placement; and the 13 accepted tests and 12 accepted mutants. Extend these tests; don't weaken or remove them.

## Root cause (one family)
The Router adapter (`gen2/router/accounting.py`) projects an invocation into a `Pass` plus page summaries that don't depend on each other. That projection throws away three relationships, and E-4 needs all three to show that a research window is **complete** and **distinct**:
- **F1, search identity.** Saturation is deduplicated on the exact request hash, the *capture* identity. Two requests that mean the same search, such as the same lanes in a different order, therefore earn two windows. The gateway already treats lane order as a set (`gateway/research_gateway/core/request_identity.py:43`, `core/router.py:260`).
- **F2, ancestry.** `parent_invocation_id` is dropped, so a delegate that failed, captured only partially, or is missing doesn't count against its parent's window (flow S4 puts discovery in delegates).
- **F3, pagination.** The request page or cursor and the returned continuation are dropped. An exhausted tail page is accepted with no captured prefix behind it.

The fix is the representation together with its arithmetic. A piecemeal guard per finding would be a mitigation.

## Required
1. **Typed window operands in `gen2/accounting`,** read by the Router adapter from fields already durable, through the same snapshot:
   - **Search identity:**
     - Make it separate from the capture/replay identity, which stays as it is.
     - Derive it from the durable request semantics.
     - Equivalent representations, such as lane order or default values, give the same identity. Real differences in query, filter or population give different identities.
     - **Reuse the canonical form the gateway already defines** where the engine is allowed to depend on it (check `boundaries.toml`). If it isn't allowed, mirror that form minimally and pin it with a test that compares it to the gateway's form.
   - **Ancestry:** a window covers its research invocation **and its delegates.** A descendant that failed, captured partially, or is missing makes that window ineligible. The scope stays per window: one unrelated historical failure doesn't poison other windows.
   - **Pagination:** a window needs its declared start, continuity (each page's continuation is the next page's cursor) and a terminal end. A missing or partial page in the chain makes it ineligible. If narrower windows bounded by a cursor are supported, declare their bounds explicitly; never infer them from a terminal page.
   - **N2, membership:** non-paging work (resolve, enrich, fetch, data with `end_unknown`) adds no window, but it doesn't erase a valid find window either. Failures in it stay visible.
2. **Regressions at Router level, through the Router APIs** (no raw SQL on invocation state), each paired with a positive control:
   - F1: equivalent requests earn one window; a genuinely different search earns two.
   - F2: a delegate with a partial capture, and a failed delegate, both leave the parent window ineligible. A complete delegated search is eligible.
   - F3: a missing prefix behind an exhausted tail is ineligible, and so is a partial prefix resumed in another pass.
   - N1: a complete linked multi-page search qualifies.
   - **Write the expected values by hand.** Astra's probes (`private/evidence/astra-2c-1/probes.py`, `probes.json`) show the scenarios; use them as reference only, and don't copy their outputs in as expectations.
3. **A paired mutant for each new guard,** with controls: dropping the normalisation, dropping ancestry, accepting a broken chain, and letting non-paging work erase a window.
4. Update `docs/gen2/ACCOUNTING.md` for the window model. **Don't weaken the E-4 claim, and don't defer it to 2c-3.**

## Constraints
- **Coder:** GPT-6.1-Sol, branch gen2.
- **Testing:** targeted tests and `--only` mutants only; the orchestrator runs the full targets.
- **Gates:**
  - SOURCE-CONTRACT v2 with 0 refusals;
  - boundaries check passes;
  - any new file or edge is declared in the metrics ledger;
  - **no arithmetic in `service.py`** (DEBT-030).
- **Size:** stay under about 500 lines; say so if the repair can't fit.
- **Established practice:** no custom proof tooling.
- **Safety:** no provider calls; never touch the live gen-1 gateway or 127.0.0.1:8765; don't search `/home/trevor/work` recursively.
- **Don't edit:** BUILD-STATE.md, REVIEW-LOG.md, DEBT-REGISTER.md.
- **Evidence:** `~/work/research-loops-public/private/evidence/2c-1-repair-1/`.
- **Commits:** end messages with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`, and use `git commit <paths>`.
