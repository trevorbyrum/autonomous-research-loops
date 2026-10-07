"""Mutants of task 2q-b7: the Router's fifth explicit collaborator (gen2/router/scheduling.py), the rules its conversion added broken alone, as router_composition_2qb6.py does
for the fourth. The composition test reads the source, so the static ones are killed by the one test they break (another static test is the paired control); the transaction,
clock and delegate ones are killed by gen2/tests/test_router_scheduling_wiring.py, and the real scheduling tests are their controls.

  2QB7-scheduling-core-omits-a-member             the collaborator uses a member of the core that SchedulingCore no longer declares;
  2QB7-scheduling-opens-the-store-transaction     the shared command path opens a transaction on the store instead of running in the core's `_guarded`;
  2QB7-router-inherits-the-scheduling             the Router inherits Scheduling again, so it is a mixin and no longer composes it;
  2QB7-scheduling-reads-the-clock-first           the shared command path reads the clock before the write lock is won, not after (`_guarded` reads it once the lock is held);
  2QB7-scheduling-refusal-escapes                 the shared command path runs in the core's bare `_transaction`, so a write the store refuses escapes instead of being a refusal;
  2QB7-router-delegate-drops-an-argument          the Router's `_draw` delegate no longer passes `now` on;
  2QB7-router-delegate-calls-another-route        the Router's `create_topic` delegate calls the collaborator's `raise_signal`.
"""
from __future__ import annotations

from .base import Mutation
from .router_composition_2qb2 import COMPOSES, HOLDS_ONLY_CORE, ROUTER_HAS, USED_DECLARED

SCHEDULING, SERVICE = "gen2/router/scheduling.py", "gen2/router/service.py"
WIRING = "test_router_scheduling_wiring."
GUARDED = '            return self._core._guarded("request_invalid", lambda now: body(req, now))'
DRAW = "        return self._scheduling._draw(draw, inv_id, topic_id, now)"
CREATE = "        return self._scheduling.create_topic(request)"

MUTATIONS: list[Mutation] = [
    Mutation("2QB7-scheduling-core-omits-a-member", "2q-b7", "SchedulingCore no longer declares `_audit`, which scheduling uses", (USED_DECLARED,), target=SCHEDULING,
             old="    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str: ...\n", new=""),
    Mutation("2QB7-scheduling-opens-the-store-transaction", "2q-b7", "the shared command path opens a transaction on the store, not the core's `_guarded`", (HOLDS_ONLY_CORE,), target=SCHEDULING,
             old=GUARDED, new="            with self._core._store.transaction():\n                return body(req, self._core._now())",
             also=(("    def _active_bundle(self) -> dict | None: ...\n", "    def _active_bundle(self) -> dict | None: ...\n    def _now(self) -> str: ...\n"),)),
    Mutation("2QB7-router-inherits-the-scheduling", "2q-b7", "the Router inherits Scheduling: a mixin again, not a composed collaborator", (COMPOSES,), target=SERVICE,
             old="class Router(Amendments):", new="class Router(Scheduling, Amendments):"),
    Mutation("2QB7-scheduling-reads-the-clock-first", "2q-b7", "a scheduling route's clock is read before the write lock is won",
             (WIRING + "ClockTest.test_every_route_reads_the_clock_only_while_it_holds_the_write_lock",), target=SCHEDULING, old=GUARDED,
             new="            first = self._core._now()\n            return self._core._guarded(\"request_invalid\", lambda now: body(req, first))"),
    Mutation("2QB7-scheduling-refusal-escapes", "2q-b7", "a scheduling route runs outside `_guarded`: a write the store refuses is an error, not a refusal",
             (WIRING + "TransactionTest.test_each_write_route_is_refused_whole_whichever_write_the_store_refuses",), target=SCHEDULING, old=GUARDED,
             new="            with self._core._transaction():\n                return body(req, self._core._now())",
             also=(("    def _active_bundle(self) -> dict | None: ...\n", "    def _active_bundle(self) -> dict | None: ...\n    def _transaction(self): ...\n"),)),
    Mutation("2QB7-router-delegate-drops-an-argument", "2q-b7", "the Router's `_draw` no longer passes `now` to scheduling", (WIRING + "DelegateTest.test_each_delegate_forwards_its_call_to_the_collaborator_and_returns_its_answer",),
             target=SERVICE, old=DRAW, new="        return self._scheduling._draw(draw, inv_id, topic_id)"),
    Mutation("2QB7-router-delegate-calls-another-route", "2q-b7", "the Router's `create_topic` calls scheduling's `raise_signal`", (WIRING + "DelegateTest.test_each_delegate_forwards_its_call_to_the_collaborator_and_returns_its_answer",),
             target=SERVICE, old=CREATE, new="        return self._scheduling.raise_signal(request)"),
]
