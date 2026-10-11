# 2d-4b2a-repair-1: DDL trace marker and predicate-level acquisition coverage (Astra 2d-4b2 slice 1, round 1: F1, F2)

**Source:** `private/reviews/gen2-2d-4b2a-astra-review-20261011.md`, pinned at 708b528.
- **Gates:** A BLOCK, B PASS, C BLOCK.
- **Round:** 1 of 3.

**Already accepted, keep as is:**
- the capture hand-off (`CaptureReader` protocol, injected by trusted construction) and the boundary;
- the acquisition binding;
- concurrency and storage.

The trust limit is documented: an injected reader is trusted, and production reader provenance belongs to 2e2.

## F1: landing check fails
- **Symptom:** `gen2-check` exits 2 at `gen2-ddl` with "CREATE TABLE source_acquisitions lacks a `-- trace:` comment directly above it".
- **Fix:** add the required `-- trace:` declaration in `gen2/store/schema/14-source-acquisitions.sql`, in the same form as the other DDL parts.
- **Don't** change the checker.

## F2: predicates without coverage
Each of these predicates can be removed on its own and every relevant test still passes:
- `s.content_hash = NEW.content_hash` (SQL 14:33);
- `w.work_id = NEW.work_id` (SQL 14:33);
- `v.topic_id = NEW.topic_id` (SQL 14:48).

The existing verifier negative swaps the role, not the verifier's topic.

**Required:**
1. Inventory every admission and DDL relationship the brief requires.
2. For each relationship that isn't redundant, add:
   - an isolated negative, with no unrelated constraint masking it (follow Astra's counterexamples);
   - a separately accepted control;
   - a predicate-level mutant.
3. If a predicate really is redundant, explain why. Don't count deleting the whole trigger as proof that each condition in it is covered.
4. Keep the current negatives.

## New standing rule: pre-commit gates
From now on, the coder's pre-commit gates **include `make gen2-ddl gen2-schemas`** in addition to the six existing ones. `gen2-check` runs those first, and missing them is what sank this landing.

## Constraints
- **Coder:** GPT-6.1-Sol, branch gen2. Leave `service.py` unchanged.
- **Before committing, run:**
  - the targeted tests and the full composition module;
  - `--only` on every mutant family that targets an edited file;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Don't** refresh `.venv-gen2` while mutants run.
- **Reading:** you may read anything in the repo and the named private paths, including Astra's counterexamples in `private/evidence/astra-2d-4b2a/`. Never search `/home/trevor` or `/home/trevor/work` outside them.
- **No** provider calls.
- **Don't edit** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b2a-repair-1/`.
- **Commits:** end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
