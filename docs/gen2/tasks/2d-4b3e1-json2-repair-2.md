# 2d-4b3e1-json2-repair-2: decouple failed-attempt retention from strict-decoding order (round 3 of 3, the cap)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3e1-json2-r2-astra-review-20261014.md`, round 2 at `db85860`.
- **F1 and F3 are closed**, and everything else is accepted: SQL 24/25, the classification pins, C-11 and the control audit.
- **Exactly one item remains: F2 (HIGH).** This is the last round; if it blocks, the operator decides.
- **Reproduction:** `~/work/research-loops-public/private/evidence/astra-2d-4b3e1-json2-r2/retention-edge-probes.py` and `.json`.

## The remaining defect
- `gen2/router/observations.py` retains a refused request only when `canonical.parse_json_strict` raises `MemberNameError`.
- Any earlier `CanonicalizationError` returns `request_invalid` **before the attempt is recorded**. Examples are an integer beyond ±(2^53−1), or a precision-losing float caught by `_exact_float`.
- So whether a failed attempt survives depends on **member order and parser error order**:
  - `{"request":{"request_type":"find","n":9007199254740992,"filters":{"field\u0000suffix":1}},...}` leaves zero rows.
  - The same members reordered leave one row.
  - A duplicated discriminator next to `n: 0.10000000000000001` disappears the same way.
- This violates the operator ruling (Trevor, 2026-10-13): **every attempt is recorded.** A failed attempt whose request can't be admitted as logical JSON keeps its exact bytes plus their hash.

## Required (root cause)
1. **Decouple retention from strict decoding.**
   - For an authenticated failed/unobserved attempt (genuine capability, running invocation and current lease, correct supplied byte hash, valid failed-attempt envelope), the decision to retain must not depend on which strict-parse error fires first, or on whether strict decoding succeeds at all.
   - **If the request text isn't admissible as logical JSON for any strict-parse reason, record it in the existing opaque failed representation:**
     - exact bytes plus their hash;
     - unknown type, page and count;
     - no invented page;
     - the denominator counted.
   - Record which refusal class applied, as a label, without decoding.
   - The opaque representation already allows this; the reordered controls prove it.
2. **Keep ordinary validation intact.**
   - Observed or exhausted requests, and any logical admission, still need strict JCS/C-13 decoding, including the numeric bounds and the discriminator.
   - Only failed-attempt retention is decoupled.
3. **Keep these unchanged:** replay/conflict semantics, authorization and transaction fences, SQL 24/25 binding and hash truth.
4. **Docs.** Make C-13 and BOUNDARIES' unconditional-retention claims true through this implementation, and state the trigger exactly: a failed attempt whose request is not admissible as logical JSON for any strict-parse reason.
5. **Tests.**
   - Regressions for **both member orders** and for **numeric-parser masking** of NUL and duplicate names: oversized integer, precision-losing float, and NUL-first-then-numeral.
   - Each regression asserts exact byte readback, denominator, replay and unknown inventory.
   - Separate accepted controls.
   - A predicate-level paired mutant for the decoupled retention decision.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2. Write the design and re-estimate in DOSSIER first.
- **`service.py`:** wiring only.
- **Never run a migration against a real database.**
- **Before committing:**
  - the full `make gen2-test`;
  - `make gen2-trigger-order`;
  - the full composition module (`gen2.tests.test_router_composition`);
  - `--only` on every mutant family that targets an edited file **and** on every family whose paired controls use an edited shared fixture, including transitive imports;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
  - If DDL changes, re-review the classification and repin both hashes.
- **Environment:**
  - **Disposable snapshots copy `.venv-gen2` (`cp -a`) and `touch .venv-gen2/.gen2-installed`. Never symlink it.**
  - Don't refresh `.venv-gen2` during mutant runs.
  - Before any heavy run, wait until no `gen2-landing-*` systemd user unit is active. Don't touch those units or their clones.
- **Reading:** anything in the repo, the private design records named in `docs/gen2/tasks/2d-4b3e.md`, and `~/work/research-loops-public/private/evidence/`. Never search `/home/trevor` or `/home/trevor/work` outside them. No provider calls.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3e1-json2-repair-2/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
