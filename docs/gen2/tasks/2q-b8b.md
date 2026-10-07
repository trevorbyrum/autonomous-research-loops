# Task 2q-b8b: retarget two metrics tests whose premise 2q-b8 removed

**Found by the orchestrator's 2q-b8 landing run** (`8f59e6f`, evidence `~/work/research-loops-public/private/evidence/2q-b8/orchestrator/gen2-check.log`). `gen2-check` exits 2 on:
1. `gen2/tests/test_metrics_identity.py::BindingTest.test_conditional_real_router_is_refused_while_the_runtime_mro_is_unchanged`, which errors with `ValueError: substring not found` on `"class Router("`, since the production line is now `class Router:`.
2. `gen2/tests/test_metrics_collaboration.py::TheRealRouterTest.test_a_syntax_only_rewrite_of_the_production_routers_bases_leaves_the_inventory_exactly_as_it_was`, which fails its own sentinel ("the production Router no longer has cross-file self-calls: this test has nothing left to protect").

Both tests protect analyser properties (refusing a conditional real-world class; an inventory invariant under a syntax-only base rewrite) using **the production Router as the fixture**, and 2q-b8 deliberately removed the mixins they relied on. The coder of 2q-b8 didn't run the full targets, per the throughput rules, so the landing run caught it, as designed.

## Required
- **Keep both analyser properties tested.** Retarget each test to a **frozen historical fixture**: the mixin-composed Router and its mixin modules as of a named commit before 2q-b6 (for example `c02fa74`), copied verbatim into a test fixture with its provenance recorded. Each test must still fail on the defect it guards: show this with a mutant or a demonstration against the old tools.
- Don't delete either test, and don't weaken an assertion. The sentinel stays meaningful: it now guards the fixture, not production.
- Run the two test modules plus `--only` for any mutants whose controls or killers are these tests. Don't run the full targets; the orchestrator does.

## Constraints
- Branch gen2. Change tests and fixtures only.
- No provider calls. Never touch the live gen-1 gateway. Don't search `/home/trevor/work` recursively.
- Don't edit BUILD-STATE.md, REVIEW-LOG.md or DEBT-REGISTER.md.
- Evidence goes to `~/work/research-loops-public/private/evidence/2q-b8b/`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Use `git commit <paths>`.
