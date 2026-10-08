# Frozen fixture: the mixin-composed Router

The router package as it was before task 2q-b2 began taking the mixins apart, copied
**verbatim** (byte for byte) from this repository's history, for the tests of the
metrics tool's implicit-collaboration inventory and of its refusal of a conditional
class (`gen2/tests/test_metrics_collaboration.py`, `gen2/tests/test_metrics_identity.py`).

- Commit: `f21613395102cfd79265b87ca651ff898d9e2122`
  (`gen2 2b-repair-13d (2/n): the observation admission contract, at the router and the store alike (Astra R13B-2)`, 2026-10-02), the last commit before 2q-b2 (`bb0f7bc`).
- Shape at that commit: `class Router(Lifecycle, Registries, Amendments, Scheduling, Status, Capabilities):`, six mixin bases, each defined in its own module of `gen2/router/`.
- Files, each stored under its repository path with `.txt` added (`gen2/router/service.py.txt`): the content is the commit's file, byte for byte; the suffix keeps the
  copy out of every tool that scans `*.py` under `gen2/` (the boundary check would otherwise count it as test code importing a third-party package it does not declare).
  `gen2/router/service.py` and the five modules it composes, plus every first-party
  module they import (`gen2/router/{boundary,schemas}.py`, `gen2/core/{canonical,instants,pagination}.py`,
  `gen2/store/{api,compat,db}.py`), the full import closure of `gen2.router.service`.
  Nothing else of that commit is here, and nothing was edited, renamed or reformatted.
- `SHA256SUMS` lists each file's digest. To check a file against history:
  `git show f21613395102cfd79265b87ca651ff898d9e2122:gen2/router/service.py | cmp - gen2/tests/fixtures/router_mixins_f216133/gen2/router/service.py.txt`.
  `FrozenRouterFixtureTest` checks the digests on every run.

Why a fixture and not the production tree: the production Router is now `class Router:` with no
bases (2q-b8). Those tests protect properties of the *analyser* (a base spelled any supported way
gives the same inventory; a conditional `class Router` is refused), and a property of the analyser
must not depend on how the production class happens to be composed. This tree is the independent,
frozen composition they use. It is test data: it is never imported by the engine, never measured
as production (`gen2/tests/` is outside every production scope), and never edited. Do not
update it to follow the production router; add a new fixture if a different shape is needed.
