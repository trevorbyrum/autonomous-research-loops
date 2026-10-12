# 2d-4b3d-repair-2: raw receipt admission requires the store's canonical representation (round 3 of 3, the cap)

**Review:** `~/work/research-loops-public/private/reviews/gen2-2d-4b3d-r2-astra-review-20261012.md`, round 2 at `9fa4748`.
- **F1 is still blocking** (Gate A); Gates B and C pass.
- Read the report in full, plus `~/work/research-loops-public/private/evidence/astra-2d-4b3d-r2/probes.py` and `probes.json`.
- **This is the last round.** If it blocks, the operator decides.

## What remains (Astra's "exactly what remains")
**F1(a): a decoded NUL acts as a path alias.**
- On SQLite 3.45.1, `json_extract`/`json_type` path lookups treat a decoded NUL as the end of a member name. So `"cited_spans\u0000suffix"` (or `start`/`locator`/`kind` with a NUL suffix) satisfies a lookup for the plain name, even though the two are distinct names.
- With a NUL-suffixed `cited_spans` placed before the real one, the column binds the page-only array while the real member cites a table. Every method admits it as `supports` at `bibliographic`.

**F1(b): numbers lose meaning before validation.**
- `start: 1.00000000000000001` and `start: -1e-999` become `1.0` and `-0.0` in SQL before the integrality and minimum checks run, so they pass.

## Root cause and direction
**The root cause.**
- SQL 21 validates the receipt through SQLite's lossy *interpretation* of the JSON text: path lookup, and conversion to REAL.
- That interpretation isn't the representation the system actually stores.
- Both remaining families come from this one gap. Don't patch individual strings.

**What the system already standardizes on.**
- `gen2/store/api.py` writes every JSON column as RFC 8785 JCS text (`canonical.parse_json_strict`, then `canonical.canonical_bytes`).
- The Router normalizes through `gen2/router/boundary.py` `normalize`.
- INVARIANTS **C-13** refuses, before anything is stored:
  - duplicate keys;
  - non-finite numbers;
  - invalid Unicode;
  - precision-losing numerals, including underflow to zero;
  - integer-notation numerals beyond ±(2^53−1).
- So the stored domain of `verification_receipts.receipt` and `cited_spans` is **canonical JCS text**.

**Recommended direction. Verify it before relying on it.**
- Raw admission should require the representation the store itself writes, and should check what the guards depend on **from the stored text and the fully decoded names, never from path lookups or REAL conversion.** In particular:
  1. **Exact names.** Exact member sets for the receipt objects that SQL 03, SQL 20 and SQL 21 read, compared on complete decoded names (for example through `json_tree` `key` with binary equality). Refuse member names that no schema-valid canonical receipt can contain, such as names containing U+0000. Valid NUL characters in locator **values** stay allowed.
  2. **Canonical numerals.** Offsets are checked against their numeral **text** as stored. The `->` operator or `json()` rendering may preserve that text; prove this with a compat probe at the SQLite floor, 3.45.1.
     - The canonical form JCS writes for an integer-valued offset is plain integer digits.
     - Where the integer-notation bound applies, it is C-13's ±(2^53−1). That is the system's existing interoperability rule, not a new arbitrary cap.
- **Astra's round-2 note said to preserve integral real spellings (`5.0`) and large integers.**
  - If you rely on canonical form, show in DOSSIER that no path the store or Router admits can produce a non-canonical spelling: the store API re-serializes every JSON column through JCS.
  - Then show that refusing non-canonical text at raw admission therefore excludes no receipt the system can write. Cite C-13 and RFC 8785.
  - If that can't be shown, instead validate the numeral text lexically and exactly, accepting the schema's integral spellings.
  - **Either way, record the reasoning in DOSSIER before writing code.**
- **Compat probe.** If you depend on a SQLite behaviour, pin it in the compat probe, failing closed. That covers NUL-name handling and numeral-text preservation.

## Required
- Close F1(a) and F1(b) at the admission boundary, using ordered additive DDL with a `-- trace:` marker. Editing the undeployed SQL 21 is allowed if it's cleaner; say which you chose.
- **Keep:** SQL 14–20, their diagnostics, the shared content view, SQL 17's fence and truthful cannot-assess behaviour.
- **Tests:**
  - isolated raw regression/control pairs for both families, across all three methods;
  - Router boundary regressions;
  - separately controlled predicate mutants.
- **Docs:** correct the implementation-status wording in BOUNDARIES and INVARIANTS V-2 to match the guarantee that results. Claim nothing beyond it.
- **Fixture audit:** repeat it if any JSON fixture's representation is affected.

## Constraints
- **Coder and branch:** GPT-6.1-Sol on branch gen2. Design and re-estimate in DOSSIER first; split at about 500 lines.
- **`service.py`:** wiring only.
- **Never run a migration against a real database.**
- **Before committing:**
  - targeted tests and the full composition module (`gen2.tests.test_router_composition`);
  - `--only` on every mutant family that targets an edited file (including `gen2/store/compat.py`) **and** on every family whose paired controls use an edited shared fixture, including transitive imports;
  - `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Environment:** don't refresh `.venv-gen2` during mutant runs. Before any mutant run, wait until no `gen2-landing-*` systemd user unit is active; one is running now. Don't touch those units or their clones.
- **Reading:** anything in the repo and the named private paths. Never search `/home/trevor` or `/home/trevor/work` outside them.
- **No provider calls.**
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4b3d-repair-2/`, with a COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
