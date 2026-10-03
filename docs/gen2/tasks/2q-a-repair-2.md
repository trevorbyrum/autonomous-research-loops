# Task 2q-a-repair-2 — the ratchet compares explicit identities: nothing appears or disappears without a ledger entry

**Source:** Astra's 2q-a-repair review, `~/work/research-loops-public/private/reviews/gen2-2q-a-repair-astra-review-20261003.md` (R1–R5 and "Family-level judgment"). Evidence: `private/evidence/astra-2q-a-repair/` (`real-probes.json`, `new-probes.json`, `real-conditional-router.patch`, `real-new-file.patch`, `rebuilt-mutants.json`). Read them in full.

This is the **second consecutive BLOCK on 2q-a**. Per the charter, this repair must be a redesign at the family level, not more special cases. A third BLOCK triggers Gate D.

**Keep, already accepted:**
- the 27/27 historical reproduction;
- C3 attribution and counting each site once;
- the instability-direction policy;
- the `code:`/`history:` marker separation;
- the 15 register entries;
- the reconciled locators.

No production change.

## Family cause (Astra)
The tool derives obligations from a lossy representation of the current code, then treats any loss of identity or recognition as removal, improvement or validity:
- same-name conditional classes collapse into one node (R1);
- a renamed or moved function or file leaves the comparison population (R2, R3);
- a new file is unmeasured until a rebaseline, which is optional (R3);
- a fully qualified locator loses its scope (R4).

## Required redesign
1. **Explicit identity and a closed accounting.** Every obligation the baseline records keeps a stable identity. That covers each function's two scores, each file's fan-out, the fan-in of each stable target, each edge or reach budget, and each collaboration pair. On every check, each baselined identity must be in exactly one of these states:
   - **present** at the same identity, compared in every dimension;
   - **mapped** to a new identity by an explicit entry in a committed **ledger** (`docs/gen2/metrics-ledger.md`, or a section of the exemptions file), which records the reason, the reviewing task, and old → new, and is then compared on both scores or budgets as before;
   - **retired** by an explicit ledger entry giving a reason.

   An identity that is missing with no ledger entry **fails**. Disappearance is never an improvement.
2. **Admission of new budgets.** A new file, a new import edge, new reach, or a new dependent of a stable target **fails** unless the ledger admits it with a reason. This applies whether the source file is old or new.
   - Add `make gen2-metrics-admit`, which drafts the ledger entries for the current diff with a `reason: TODO`. A TODO reason fails the check. Authors fill in the reasons, and Gate A reviews the ledger diff as part of the task.
   - `rebaseline` folds the admitted and mapped entries into the baseline and clears them from the ledger. It never admits anything by itself.
   - Normalised aggregates never authorise growth.
3. **Ambiguity fails closed (R1).** Keep each binding occurrence and its alternatives, including conditional, duplicated and star-reexported class names. If resolution isn't unique and statically certain, report the binding as **unresolved**; that fails the check unless it is classified in the ledger. Never use a last-entry guess or sorted order. Add interpreter-backed controls showing that Python's actual selection matches the tool, or that the tool reports the binding as unresolved.
4. **Locator scope (R4).** A fully qualified module path resolves with a lookup that preserves scope: module attribute, then class attribute. It never uses the flattened short-name index. Any token that looks like a locator but doesn't match the grammar is diagnosed, not silently accepted.
5. **Tests (R5).**
   - Replace the two rejected tests in `test_metrics_dependencies.py` with admission and rename-continuity cases.
   - Rebuild every R1–R4 reproduction as a regression; each must fail on `c87821e` and pass now:
     - the conditional Router;
     - star re-export order;
     - rename and move combined with a 21/0→8/28 complexity change;
     - a renamed importer adding an edge;
     - a new file importing a stable module;
     - the real `gen2/core/normalized.py` patch;
     - nested `f` under a fully qualified locator.
   - Add positive controls: an admitted new file passes; a mapped rename passes; a retirement passes; ordinary unchanged code passes.
   - Add mutants with paired controls for: the "missing means improvement" fallback; admission without a reason; mapping without comparison; last-entry binding; and short-name lookup for qualified paths.
   - Fix the two policy-sensitive mutants Astra flagged: `2QR-dep-fan-in-counts-new-files` and the `KeyError` crash in `2QR-dep-new-files-are-baselined`.

## Done means
- `make gen2-check` and `make gen2-gateway` exit 0, run unpiped.
- Baseline and ledger diffs are shown in the evidence.
- The current tree passes with an **empty** ledger, because no admission is needed at this pin. If one is needed, explain it.

## Constraints
- Branch gen2. Tools, tests, docs and the register only. No production change. The oracle stays unedited.
- No provider calls.
- Never touch the live gen-1 gateway or 127.0.0.1:8765. Don't search `/home/trevor/work` recursively.
- Evidence goes to `~/work/research-loops-public/private/evidence/2q-a-repair-2/`.
- Commit messages end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
- The completion report gives the root cause in one sentence, the identity and accounting contract, net lines, and a literally true Remaining section.
