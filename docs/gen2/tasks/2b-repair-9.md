# Task 2b-repair-9 — close R8-1..R8-3 and test the invariant, not the instances

Read first, in full: `~/work/research-loops-public/private/reviews/gen2-2b-repair-8-astra-review-20261001.md` (R8-1, R8-2, R8-3, the accepted-changes table and the escape audit), with evidence in `~/work/research-loops-public/private/evidence/astra-2b-repair-8/` (`remaining_regressions.py`, `independent-probes.json`, `behavior-probes.json`, `oc_star_escape.diff`, `oc_reexported_parser.diff`, `check_escape_mutant.py`). Then read the charter sections "Root-cause fixes, not patches", "Evidence is durable", and the no-personal-data rule.

**Accepted and not to be touched:** the runtime view design (`core/payload.py`, `Members`/`Obj`), all 68 audited escape uses, and every earlier ROOT-CAUSE item. Don't return to builder-loop pattern matching.

## Why this round is different
This is the fourth round in which a malformed provider input is read as a definite answer: an end, an empty result, or a complete one. Each round fixed the reported inputs, and the reviewer found the next input beside them. **The test discipline is the cause:** tests enumerate instances instead of asserting the invariant. So alongside the three fixes, this task adds a generative test of the invariant itself.

## Required
1. **R8-1 — relation values.** Validate the decoded `rel` value as an RFC 8288 relation-type list (registered tokens or URIs, valid quoting, no stray quotes or control characters, not empty) before anything establishes absence. An invalid or uninterpretable relation is **unknown**: neither continuation nor end. Preserve unrelated relations, first-rel handling, quoted descriptive parameters, URI relations, repeated lines, and URL/credential validation. Routed negatives: `rel="\"next\""`, `rel=""`, `rel="next, prev"`, and a control character; each beside a readable no-next control.
2. **R8-2 — present means typed.** Distinguish a contract-permitted missing or null field from a present container, and validate the present container's kind **before** looking at its length or truthiness. A present wrong-type holder is an unreadable holder: it is dropped-member accounting, never an empty result. Apply this to every optional member holder: ECB `series` (`core/sdmx.py` ~line 95), HF `siblings` (`adapters/huggingface.py` ~line 142), and any other `if x:` / `x or []` style guard on provider data. Search for that pattern; don't rely on the two named sites.
3. **R8-3 — the inventory is closed over import forms.** Refuse forms the checker can't analyse: forbid star imports in adapters and provider-data helpers. Close the re-exported-parser route: provider data reaches adapters only via `Response.json`, with no `json`/parser re-export usable from `base`. Add Astra's two complete adapter mutations as guard regressions, each with a permitted-import control.
4. **The invariant test (the root-cause fix for the test discipline).** Add a seeded, deterministic, stdlib-only generative harness. For every adapter operation that produces candidate records or end and continuation signals, it should:
   - start from each adapter's valid fixture;
   - apply structured corruptions: wrong-typed values, including falsy ones (`false`, `0`, `""`, `{}`, `[]`, `null`) at every container and scalar position; non-object members mixed among readable ones; malformed and ambiguous `Link` values; garbled totals and cursors;
   - run each through the real router;
   - assert the invariants:
     - (a) a lane is `exhausted` or `complete` only if every field its end rule depends on was readable;
     - (b) never a zero or empty count from an unreadable holder;
     - (c) readable peer members survive as a partial lower bound;
     - (d) no crash escapes as an unhandled error.

   The harness must fail on the code before this task's fixes (show that) and pass after. Bind at least one mutant to each invariant. Keep run time bounded and seed-stable for CI.

## Completion report (charter rule)
Each root cause in one sentence, and why the change removes it for every path. Report what the invariant harness found beyond Astra's named cases. List every remaining limitation with its actual owner. The Remaining section must be literally true.

## Constraints
Branch gen2 only. No live calls to provider APIs and no personal data in any request. Never run a migration against a real database, and never touch `~/work/staging/research-gateway-wt`, its database or `research-gateway.service`. Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-9/`. Small commits with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with final unpiped `make gen2-check` and `make gen2-gateway`, waited on in your turn. Report net lines for engine and gateway separately.
