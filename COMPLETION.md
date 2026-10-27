# Batch R2 completion

INVARIANTS goes back to normative rules plus "enforced at" pointers (ruling 5). The locator narratives move to
`docs/gen2/traceability.toml` (verified mapping) and the generated `docs/gen2/TRACEABILITY.md`; the dropped text is
kept verbatim in `~/work/research-loops-public/private/evidence/dossier-history/INVARIANTS-enforced-at-narratives-20261027.md`.
`docs/gen2/tasks/*` history (165 files, 7,950 lines) moved to `.../dossier-history/tasks-20261027/`; `2d.md` and `2c-4.md` stay.

## Changed INVARIANTS entries (31 lines; every other line byte-identical)
- **Ruling 1/A, scope 3(a), Enforced-at line only:** V-2, V-3, V-4, V-8 now read "router (`DetailedChecks`, `EvidenceWriter`); DDL keeps the SQL 03 base gates."
- **S2-6, scope 3(b):** §13, G-4 row: the Phase 2 cell now reads "2f runs under an operator-authored contract (S2-6; DEBT-049)" and the live S1–S3 intake conversation moves to the Phase 3 cell.
- **Narrative moved, Enforced-at only (one-line category plus locators):** RG-1a, RG-4, RG-9, C-12, C-13, L-3, L-4, E-2, E-3, V-6, V-10, D-5, G-1, G-2, G-3, G-4, G-8, G-11, G-12, G-13, P-2, P-3, P-5, H-1, H-4, H-5.
- The restricted diff (`evidence/r2/rule-text-restricted-diff.txt`) shows no change to any statement, Source or Test-must-show text outside the §13 row.

## Not changed, for the orchestrator and Trevor
- **Size target not reachable under scope 3.** INVARIANTS is 121,113 → 93,544 bytes (420 lines both). The Enforced-at narratives were 32.6 KB of 121 KB; the rest is statements, Sources, Test-must-show (9.5 KB) and the no-ID blocks, all frozen by this brief. About 30 KB needs a ruling that lets statements and Test-must-show text move too.
- **Left byte-identical, but stale:** the "Operator amendment to C-13, 2026-10-13" block (lines 99–155) and the E-2 trust-model paragraph, because they are operator rulings, not locator narrative. The amendment block names SQL 23/26/27/30 (retired by S6) as live enforcement; V-2/V-3/V-4/V-8 statements still cite SQL 16–21/32–34 numbers (S5). Both need an operator-approved amendment.
- Locators the old narratives gave that no longer exist, and vocabulary words, are listed in `evidence/r2/dropped-locators.txt` (not in the toml). Entries whose old text had no Enforced-at (e.g. C-3, C-6) have `enforced_at = []`; tests are listed only where the old text named them.
- `docs/gen2/CI-DESIGN.md` untouched; proposed text in `evidence/r2/CI-DESIGN-amendments.md` (D12).
- `REVIEW-LOG.md` and `DOSSIER.md` still cite moved task files in backticks (not scanned by the locator gate, forbidden to edit here); `gen2/tests/test_router_brief_basis.py`, `test_router_workflow.py` and `export-bundle-v2.schema.json` cite them in comments (production and tests not touched).

## Files
- New: `docs/gen2/traceability.toml` (660 lines), `docs/gen2/TRACEABILITY.md` (101), `tools/gen2_traceability.py` (83), `gen2/tests/test_traceability.py` (60).
- Edited: `tools/check_gen2_locators.py` (toml mode, four default documents), `Makefile` (`gen2-traceability` writes the table; its `--check` runs inside `gen2-locators`, so `gen2-check` and `gen2-push` carry it), `docs/gen2/ACCOUNTING.md` (two moved-task locators marked history), `docs/gen2/INVARIANTS.md`.
- Deleted: 165 `docs/gen2/tasks/*` files.

Evidence: `~/work/research-loops-public/private/evidence/r2/`.

## Follow-up commit: retired-SQL references -> current owners (rulings 1/A, D4; no rule meaning change)
Owners from `private/evidence/s5/RULE-TABLE.md` and `s6/RULE-TABLE.md`. Four sentences changed (C-13 amendment block: three; V-4: one). Everything else byte-identical. V-2, V-3 and V-8 statements contained no retired SQL reference (only their Enforced-at lines did, fixed in the first commit); the E-2 trust-model paragraph names no retired object and is unchanged. SQL 03, 24 and 25 still exist and stay.

1. C-13 amendment, line 104.
   - Before: "...Store preparation on the three SQL 23 guarded columns:"
   - After: "...Store preparation on the three columns (until 2026-10-27, S6, guarded by SQL 23; now by Store preparation alone):"
2. C-13 amendment, lines 125-127.
   - Before: "Ordered additive SQL 23, 26, 27 and 30 cover all 37 logical JSON columns with both INSERT and UPDATE guards; the static-check manifest has no pending columns. SQL 30 adds `extraction_validations_v2.comparison_evidence_ref` under the same closed member-name family."
   - After: "Until 2026-10-27 (S6) ordered additive SQL 23, 26, 27 and 30 covered all 37 logical JSON columns with both INSERT and UPDATE guards, and the static-check manifest had no pending columns; SQL 30 added `extraction_validations_v2.comparison_evidence_ref` under the same closed member-name family. Since S6, Store preparation alone enforces the member domain on those 37 columns."
3. C-13 amendment, lines 128-130.
   - Before: "SQL 21's receipt uniqueness predicate is now redundant under the whole-receipt member-domain guard and is retained unchanged. Its span-shape and preserved-numeral guarantees remain unchanged."
   - After: "Until 2026-10-27 (S5) SQL 21's receipt uniqueness predicate was redundant under the whole-receipt member-domain guard and was retained unchanged, and its span-shape and preserved-numeral guarantees remained unchanged; since S5 the Router's receipt and span checks (`boundary`, schema validation) and Store preparation own those guarantees, unchanged."
4. V-4 statement.
   - Before: "SQL 34 permits extraction support only through the verifier's own pinned extraction or a successful independent /2 validation bound by SQL 32/33."
   - After: "The Router (`DetailedChecks`, `EvidenceWriter`) permits extraction support only through the verifier's own pinned extraction or a successful independent /2 validation bound by the receipt's own durable basis."
Left and listed: none. Checks: `make gen2-locators` and `make gen2-push` green.
