"""Mutants of task 2q-b6: the Router's fourth explicit collaborator (gen2/router/lifecycle.py), the rules its conversion added broken alone, as router_composition_2qb3.py does
for the third. The composition test reads the source, so the static ones are killed by the one test they break (another static test is the paired control); the transaction and
delegate ones are killed by gen2/tests/test_router_lifecycle_wiring.py, and the real lifecycle tests are their controls.

  2QB6-lifecycle-core-omits-a-member             the collaborator uses a member of the core that LifecycleCore no longer declares;
  2QB6-lifecycle-opens-the-store-transaction     the cancellation opens a transaction on the store instead of running in the core's `_guarded`;
  2QB6-router-inherits-the-lifecycle             the Router inherits Lifecycle again, so it is a mixin and no longer composes it;
  2QB6-lifecycle-cancel-reads-the-clock-first    the cancellation reads the clock before the write lock is won, not after (`_guarded` reads it once the lock is held);
  2QB6-lifecycle-reconcile-refusal-escapes       the reconciliation runs in the core's bare `_transaction`, so a write the store refuses escapes instead of being a refusal;
  2QB6-router-delegate-drops-an-argument         the Router's `_bind_evidence` delegate no longer passes `terminal` on.
"""
from __future__ import annotations

from .base import Mutation
from .router_composition_2qb2 import COMPOSES, CI, HOLDS_ONLY_CORE, ROUTER_HAS, USED_DECLARED

LIFECYCLE, SERVICE = "gen2/router/lifecycle.py", "gen2/router/service.py"
WIRING = "test_router_lifecycle_wiring."
CANCEL = '            return self._core._guarded("transition_not_allowed", lambda now: self._cancel_in_transaction(req, now))'
RECONCILE = '            return self._core._guarded("transition_not_allowed", lambda now: self._reconcile_in_transaction(req, identity, evidence, now))'
BIND = "        return self._lifecycle._bind_evidence(inv, evidence, failure_class=failure_class, terminal=terminal)"

MUTATIONS: list[Mutation] = [
    Mutation("2QB6-lifecycle-core-omits-a-member", "2q-b6", "LifecycleCore no longer declares `_audit`, which the lifecycle uses", (USED_DECLARED,), target=LIFECYCLE,
             old="    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str: ...\n", new=""),
    Mutation("2QB6-lifecycle-opens-the-store-transaction", "2q-b6", "the cancellation opens a transaction on the store, not the core's `_guarded`", (HOLDS_ONLY_CORE,), target=LIFECYCLE,
             old=CANCEL, new="            with self._core._store.transaction():\n                return self._cancel_in_transaction(req, self._core._now())"),
    Mutation("2QB6-router-inherits-the-lifecycle", "2q-b6", "the Router inherits Lifecycle: a mixin again, not a composed collaborator", (COMPOSES,), target=SERVICE,
             old="class Router(Amendments):", new="class Router(Lifecycle, Amendments):"),
    Mutation("2QB6-lifecycle-cancel-reads-the-clock-first", "2q-b6", "a cancellation is dated by a clock read before the write lock is won", (WIRING + "LockWaitTest.test_a_cancellation_is_dated_by_the_clock_read_after_the_lock_is_won",),
             target=LIFECYCLE, old=CANCEL,
             new="            first = self._core._now()\n            return self._core._guarded(\"transition_not_allowed\", lambda now: self._cancel_in_transaction(req, first))"),
    Mutation("2QB6-lifecycle-reconcile-refusal-escapes", "2q-b6", "a reconciliation runs outside `_guarded`: a write the store refuses is an error, not a refusal",
             (WIRING + "TransactionTest.test_a_reconciliation_is_refused_whole_whichever_write_the_store_refuses",), target=LIFECYCLE, old=RECONCILE,
             new="            with self._core._transaction():\n                return self._reconcile_in_transaction(req, identity, evidence, self._core._now())",
             also=(("    def _router_policy(self, bundle_hash: str) -> dict: ...\n", "    def _router_policy(self, bundle_hash: str) -> dict: ...\n    def _transaction(self): ...\n"),)),
    Mutation("2QB6-router-delegate-drops-an-argument", "2q-b6", "the Router's `_bind_evidence` no longer passes `terminal` to the lifecycle", (WIRING + "DelegateTest.test_each_delegate_forwards_its_call_to_the_collaborator_and_returns_its_answer",),
             target=SERVICE, old=BIND, new="        return self._lifecycle._bind_evidence(inv, evidence, failure_class=failure_class)"),
]
