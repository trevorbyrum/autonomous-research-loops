# 2d-4b3d-repair-1: one unambiguous cited-span representation at raw admission (round 2 of 3)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3d-astra-review-20261012.md`, round 1 at `9cece22`. Gate A blocked on **F1**; Gates B and C passed. There is one non-blocking finding, **NB1**. Read the report in full.

**Reproduction:** `~/work/research-loops-public/private/evidence/astra-2d-4b3d/probes.py` and `probes.json`.

## F1 (blocking, MITIGATION at the family level)
**The problem.** SQL 20 detects a table citation with `json_extract(s.value, '$.locator.kind') = 'table'`. SQL 03 checks that `cited_spans` is a nonempty array matching the receipt JSON, but never establishes the span or locator *shape*. As a result, raw inserts are accepted for all three methods as `supports` at `bibliographic`. The cases Astra reproduced are:
- **duplicate keys:** `{"kind":"page","kind":"table"}`, where SQLite reads the first value and a last-key reader sees `table`, or a duplicated `locator` object;
- a span with **no `locator`**;
- a **case-altered kind**, such as `"TABLE"`.

The Router's JSON Schema boundary refuses all of these, so this is not an agent-facing exploit. The raw-admission guarantee is still in scope.

**The root cause:** the guard relies on an input domain the storage layer never enforces.
- **Fix it at the domain.** At the storage admission boundary, before table availability is decided, establish **one well-formed, unambiguous representation**.
- **Don't special-case the reproduced strings.**

**Required:**
1. **Duplicate member names make a document ambiguous.**
   - Refuse receipt JSON whose cited spans contain duplicate member names. Consider whether the guard should cover the whole receipt document, so that the SQL 03 column-to-JSON matching can't be split the same way.
   - Standard practice: I-JSON (RFC 7493 §2.3) says names within an object MUST be unique. RFC 8259 §4 notes that duplicate-name behaviour is unpredictable.
   - Cite the standard you rely on in DOSSIER.
2. **Every span has the exact shape** the receipt JSON Schema requires (`gen2/schema/verification-receipt.schema.json`, `cited_spans`):
   - an object with exactly `start`, `end` and `locator`;
   - integers with `start >= 0` and `end >= 1`;
   - a `locator` object with exactly `kind` and `value`;
   - `kind` in the schema's enum, matched exactly (case-sensitive);
   - `value` a string.
   - Match the schema. Don't invent a stricter or looser domain.
3. **DDL:** ordered additive DDL with a `-- trace:` marker. The checks that decide table availability then rely on this domain.
4. **Keep:** SQL 14–20, their diagnostics, the shared content view, SQL 17's fence, and truthful insufficient-access admission.
5. **Tests.**
   - Isolated raw regression/control pairs for each structural predicate, across all three methods.
   - Router regressions.
   - A predicate-level paired mutant per guard.
6. **Fixture audit.**
   - Some raw capture-support controls deliberately omit locators: `gen2/tests/test_store_capture_support.py`, including around lines 143 and 222.
   - Supply truthful page or section locators without weakening their original capture assertions.
   - Repeat the full receipt-fixture audit across every test that loads a verification-receipt schema example, uses `receipt_document` or `verification_receipts=`, or calls a raw `verify` helper. Record it in evidence.

## NB1 (non-blocking BOUNDARY-DRIFT; fix it here)
- INVARIANTS V-2 (around line 163) and BOUNDARIES Router (around lines 30, 44–45 and 68) still describe table-tier admission as future work.
- Replace that wording, following Astra's proposed text in the report's NB1 section.
- Because this repair closes F1, **omit the F1 caveat**. Describe the structural domain guard instead.
- Don't change the normative V-2 requirement, and don't claim the minimum proves the identity of the cited table.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2. Design and re-estimate in DOSSIER first; split at about 500 lines.
- **`service.py`:** wiring only.
- **Never run a migration against a real database.**
- **Before committing:**
  - targeted tests and the full composition module (`gen2.tests.test_router_composition`);
  - `--only` on every mutant family that targets an edited file **and** on every family whose paired controls use an edited shared fixture, including transitive imports;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Environment:** don't refresh `.venv-gen2` during mutant runs. Before any mutant run, wait until no `gen2-landing-*` systemd user unit is active. Don't touch those units or their clones.
- **Reading:** anything in the repo and the named private paths. Never search `/home/trevor` or `/home/trevor/work` outside them.
- **No provider calls.**
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3d-repair-1/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
