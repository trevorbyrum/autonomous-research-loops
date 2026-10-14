# 2d-4b3e1-json2-repair-1: unambiguous retained-request representation; unconditional failed-attempt retention (round 2 of 3)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3e1-json2-astra-review-20261014.md`, round 1 at `0c1c8fb`.
- **Gate A BLOCK, Gate B PASS, Gate C BLOCK; MITIGATION.**
- Read the full report and the reviewer evidence in `~/work/research-loops-public/private/evidence/astra-2d-4b3e1-json2/`:
  - `reference-probes.*` and `storage-probes.*`;
  - `probes.*`;
  - `controls-audit.json`.
- **Landing at 0c1c8fb:** both suites green. The defects are design gaps the suites don't cover.

**The operator ruling this must satisfy** (Trevor, 2026-10-13):
- **Every attempt is recorded.**
- A failed attempt whose request contains a refused name keeps that request as **exact raw bytes plus their hash**. It isn't renamed, truncated or dropped.

## F1 (HIGH): a retained-byte reference without its own bytes
**The problem.**
- SQL 24's `search_observations_retained_request` checks reference, identity and failure shape **only when `request_bytes IS NOT NULL`**.
- With both byte fields NULL, the logical `request` can carry a copied retained-request reference.
- The Router accepts that reference as an ordinary logical request, even as `searched_empty`/`searched_ok complete exhausted` with a capture acknowledgement.
- A retrieval event then attaches to it, and `accounting.read_page` raises `KeyError: 'page'`.

**Required.** Make the two representations **unambiguous and bound in both directions**:
- A retained-request descriptor requires its own same-row byte/hash pair and the failed/unobserved shape.
- An ordinary logical request can never impersonate a descriptor.
- Foreign-row and foreign-column descriptor variants are refused.
- Keep the Router and Store hash-truth checks.
- Accounting must decide "opaque" from the bound representation, never from a single column.

## F2 (HIGH): retention still depends on decoding the refused document
**The problem.**
- `gen2/router/observations.py` normalizes first and needs `pagination.request_type(json.loads(original))`.
- So refused requests with a NUL-suffixed `request_type` name, or a duplicated `request_type`, produce `request_invalid` and **zero observation rows**.
- Object-form requests with a NUL-bearing filter are refused by whole-command normalization before retention. `test_router_nul` expects that refusal but never checks the denominator.

**Required.**
- Retain an authenticated failed attempt **independently** of whether its refused logical document yields a usable request-type discriminator.
- Model the opaque failed case explicitly: exact supplied bytes plus hash, no invented decoded page, unknown in the inventory.
- Don't weaken the discriminator that ordinary observed requests require.
- Complete the object/raw producer hand-off so that no existing attempt producer can lose an attempt at normalization.
- Never reparse duplicates with last-value-wins to make a decision.

## F3 (MEDIUM): a weakened control pairing
**The problem.** `tools/gen2_mutation_controls.json` entry `2B13-cursor-beyond-the-bound` was re-paired to `TheTrustModel.test_a_relabelled_outcome_is_not_detected_here`, which never reaches the integer bound in `gen2/core/pagination.py::cursor_problem`.

**Required.**
- Pair it with a separate accepted integer-boundary control that reaches the predicate, for example the previous `AtTheRouter.test_the_cursor_domain_is_one`.
- Pin it through the existing manual-control mechanism if needed.
- Show the control is relevant and that it passes under the intended mutant.
- **Audit every other re-paired entry** in this task the same way.

## Tests
- **Router and raw-DDL negatives:**
  - both byte fields absent alongside a descriptor;
  - dangling and foreign descriptors;
  - observed or exhausted claims carrying a descriptor;
  - retrieval-event insertion against a descriptor.
- **Positive controls** for both legitimate representations.
- **For each refusal family** (structural NUL names, a duplicated discriminator, object-form NUL filters):
  - byte-exact readback;
  - denominator counts;
  - replay;
  - unknown inventory.
- **Predicate-level paired mutants** for each new guard.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2. Write the design and re-estimate in DOSSIER first; split at about 500 lines.
- **`service.py`:** wiring only.
- **Never run a migration against a real database.**
- **Before committing:**
  - the full `make gen2-test`;
  - `make gen2-trigger-order`;
  - the full composition module (`gen2.tests.test_router_composition`);
  - `--only` on every mutant family that targets an edited file **and** on every family whose paired controls use an edited shared fixture, including transitive imports;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Classification:** re-review it after any DDL change and repin both hashes explicitly.
- **Environment:** don't refresh `.venv-gen2` during mutant runs. Before any heavy run, wait until no `gen2-landing-*` systemd user unit is active. Don't touch those units or their clones.
- **Reading:** anything in the repo, the private design records named in `docs/gen2/tasks/2d-4b3e.md`, and `~/work/research-loops-public/private/evidence/`. Never search `/home/trevor` or `/home/trevor/work` outside them. No provider calls.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER. C-13, BOUNDARIES and DOSSIER claims must match the code exactly.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3e1-json2-repair-1/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
