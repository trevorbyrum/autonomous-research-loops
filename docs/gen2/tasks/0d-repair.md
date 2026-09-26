# Task 0d-repair: close the three 0d findings (docs and tests; no engine logic)

Read first: `~/work/research-loops-public/private/reviews/gen2-0d-astra-review-20260926.md`, findings 1–3, which give exact locations and required repairs. Then read the operator ruling in `docs/gen2/tasks/0d.md`. The ruling applies to the whole build surface, not a list of examples. Everything the review accepted stays as is: the one export API, the unchanged internal process, the preserved guarantees and Gate B.

## Finding 1 (P1): host-specific deployment material
Follow the review's table:
- **Remove or generalize:**
  - `DEPLOYMENT-CONTRACT.md` ~35, ~57, ~76, ~471: this host's running gen-1 service, its listeners, the occupied ports it observed, and defaults "chosen around" them. Numeric defaults may stay as public product defaults. Say that port availability is checked at each deployment. Describe a dedicated stack instance, not a second instance next to gen-1.
  - `tools/gen_source_catalog.py` ~484, ~491, ~549 and its opening docstring (gen-1 coexistence and "on this host"). Then regenerate `SOURCE-CATALOG.md` and `deploy/gen2.env.example`.
- **Wording only:** `ENVIRONMENT.md` ~31. Keep it, but say "the reviewed test environment". Keep the evidentiary limit.
- **Move to review history:** the `ENVIRONMENT.md` ~73 personal user-site cleanup note. Keep the generic rule that the isolated venv excludes user-site packages.
- **Make locators portable:** `BUILD-CHARTER.md` ~12 and `INVARIANTS.md` ~12 hardcode `~/work/research-loops-public/private/`. Use document identities or portable references instead. This changes no authority.

Then do your own sweep for anything else that assumes this operator's host, services, paths or deployment, and report what you found.

## Finding 2 (P2, Gate C): four replacement rules survive mutation
Add isolated negatives, each with a bound mutation that makes that negative validate:
- an extension `implementation` missing only `module`;
- an extension `implementation` missing only `review_ref`;
- a `/2` freshness envelope that carries the retired `mixed_generation`;
- a delivered pair missing only `options_revision`, plus its mirror, a pair missing only `generation`.

Keep the existing valid extension and complete pair as positive controls. Reproduce each of Astra's four survivors against the old tree first, and show each is killed at HEAD.

## Finding 3 (P2): `EXPORT-API.md` ~326 claims the store refuses an extension with no implementation
Choose one of the review's two options:
- **Doc correction (preferred in Phase 0):** extension implementation/review admission is a schema rule, validated by the router/exporter before outbox admission, which is a named obligation for Phase 1 and 3. Stop attributing it to the DDL, consistent with the store README's split.
- **DDL enforcement:** enforce it in the DDL, with isolated tests and mutants.

Say which you chose and why.

## Constraints (unchanged)
Branch gen2 only. No engine logic. Never touch `gateway/`, gen-1, running services or main. Small commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with the completion report as your final message; don't end your turn waiting on a background run. The report covers, for each finding: what changed, the evidence, your sweep results, and the final unpiped `make gen2-check` result.
