# 2d-4b3b-repair-1: a defined nonblank-content rule, and no tier inflation through any method (Astra 2d-4b3 slice 2 part 1, round 1: R1, R2)

**Source:** `private/reviews/gen2-2d-4b3b-astra-review-20261011.md`, pinned b5de4c8.
- **Verdict:** A BLOCK, B PASS, C BLOCK. Classified as a MITIGATION at the V-2 family level.
- **Round:** 1 of 3.
- **Reproductions:** `private/evidence/astra-2d-4b3b/reviewer_probes.py` and its log.

**Accepted; keep:**
- SQL 16's ceiling derivation for canonical bytes: record selection, consuming the observation, ignoring links, `has_full_text`, metadata and labels;
- `metadata_only` never certifies full text;
- canonical bytes never certify `reproduced`;
- the legitimate test edits.

## R1: whitespace-only bodies count as content
**Problem.** DDL 16:14 trims only tab, LF, CR and space. Form feed, vertical tab, U+00A0, U+2003 and U+2028 each pass as an entire body. These are reachable through the gateway's CORE text path, and one probe got a load-bearing claim promoted on `"\f "`.

**Required:**
- Define a **named, versioned nonblank-content rule** based on a cited standard, for example the Unicode `White_Space` property (PropList.txt, the UCD version you pin). Consider whether default-ignorable or format characters such as zero-width space also count as blank, and decide explicitly.
- Enforce the rule consistently at the durable receipt boundary, in the Router **and** in the DDL. SQLite has no Unicode classes, so the DDL may use the complete explicit code-point set the rule defines.
- Tests:
  - independently selected Unicode separator cases, in the Router and in raw DDL;
  - accepted controls with substantive text;
  - predicate counterfactuals.
- **Don't** fix only the reproduced characters, and don't add an arbitrary minimum length.

## R2: switching the extraction method bypasses the ceiling and promotes claims
**Problem.** DDL 16 only applies to `canonical_bytes`. With only an abstract recorded:
- `verifier_extraction` and `validated_extraction` both commit `full_text` and `reproduced` receipts;
- both promote load-bearing claims to `accepted_support`, with no hold;
- `validated_extraction` passes with nothing more than `validation_unrecorded`.

**Required:**
- **Every tier-bearing method must consume a recorded basis that is sufficient for the tier it claims.** At a minimum, extraction methods consume the same admitted acquisition and its recorded-content ceiling.
- A method whose evidence isn't durably bound yet must **not authorize support**. That covers `validated_extraction` until a durable validation record exists, which is the next slice. Its receipts stay non-authoritative. Missing required content follows the existing hold/remediation contract (V-2, the 2d-4 part-1 missing-content cause).
- Full extraction/validation storage can stay scheduled for the next slice. Nothing in this slice may let it inflate tiers in the meantime.
- Tests, in the Router and raw DDL:
  - method-switching cases;
  - load-bearing promotion attempts;
  - `reproduced`;
  - separately accepted valid controls for each method.
- A predicate-level paired mutant for each guard.

## Constraints
- **Coder and branch:** GPT-6.1-Sol, branch gen2.
- **`service.py`:** 1,434 lines. Wiring only.
- **Before committing, run:**
  - targeted tests and the full composition module;
  - `--only` on every mutant family that targets an edited file;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Environment:**
  - Don't refresh `.venv-gen2` while mutants run.
  - Ordered DDL only, with `-- trace:` markers.
  - Never run a migration against a real database.
- **Reading:** anything in the repo and the named private paths. Never search `/home/trevor` or `/home/trevor/work` outside them.
- **No provider calls.**
- **Don't edit:** BUILD-STATE, REVIEW-LOG, DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3b-repair-1/`.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
