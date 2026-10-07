"""Mutants of task 2q-b8: the Router's sixth and last explicit collaborator (gen2/router/amendments.py), the rules its conversion added broken alone, as router_composition_2qb7.py
does for the fifth. The composition test reads the source, so the static ones are killed by the one test they break (another static test is the paired control); the transaction,
clock, fence and delegate ones are killed by gen2/tests/test_router_amendments_wiring.py, and the real amendment tests are their controls.

  2QB8-amendments-core-omits-a-member             the collaborator uses a member of the core that AmendmentsCore no longer declares;
  2QB8-amendments-opens-the-store-transaction     the shared command path opens a transaction on the store instead of running in the core's `_guarded`;
  2QB8-router-inherits-the-amendments             the Router inherits Amendments again, so it is a mixin and no longer composes it;
  2QB8-amendments-reads-the-clock-first           the shared command path reads the clock before the write lock is won, not after (`_guarded` reads it once the lock is held);
  2QB8-amendments-refusal-escapes                 the shared command path runs in the core's bare `_transaction`, so a write the store refuses escapes instead of being a refusal;
  2QB8-fence-opens-its-own-transaction            the fence requests a cancellation in a transaction of its own inside the approval's, which the store refuses (they do not nest);
  2QB8-router-delegate-drops-an-argument          the Router's `_record_replacements` delegate no longer passes `now` on;
  2QB8-router-delegate-calls-another-route        the Router's `close_brief` delegate calls the collaborator's `mark_brief_overdue`.
"""
from __future__ import annotations

from .base import Mutation
from .router_composition_2qb2 import COMPOSES, HOLDS_ONLY_CORE, USED_DECLARED

AMENDMENTS, SERVICE = "gen2/router/amendments.py", "gen2/router/service.py"
WIRING = "test_router_amendments_wiring."
GUARDED = '            return self._core._guarded("request_invalid", lambda now: body(req, now))'
CANCEL = '''            self._core._cancel_in_transaction({"invocation_id": inv["invocation_id"], "requested_by": "router", "reason": f"pins superseded by {d['decision_id']}"}, now)\n'''
TEMPLATES = "    def _templates(self) -> dict: ...\n"
REPLACEMENTS = "        return self._amendments._record_replacements(d, current, now)"
CLOSE = "        return self._amendments.close_brief(request)"

MUTATIONS: list[Mutation] = [
    Mutation("2QB8-amendments-core-omits-a-member", "2q-b8", "AmendmentsCore no longer declares `_audit`, which amendments uses", (USED_DECLARED,), target=AMENDMENTS,
             old="    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str: ...\n", new=""),
    Mutation("2QB8-amendments-opens-the-store-transaction", "2q-b8", "the shared command path opens a transaction on the store, not the core's `_guarded`", (HOLDS_ONLY_CORE,), target=AMENDMENTS,
             old=GUARDED, new="            with self._core._store.transaction():\n                return body(req, self._core._now())",
             also=((TEMPLATES, TEMPLATES + "    def _now(self) -> str: ...\n"),)),
    Mutation("2QB8-router-inherits-the-amendments", "2q-b8", "the Router inherits Amendments: a mixin again, not a composed collaborator", (COMPOSES,), target=SERVICE,
             old="class Router:", new="class Router(Amendments):"),
    Mutation("2QB8-amendments-reads-the-clock-first", "2q-b8", "an amendments route's clock is read before the write lock is won",
             (WIRING + "ClockTest.test_every_route_reads_the_clock_only_while_it_holds_the_write_lock",), target=AMENDMENTS, old=GUARDED,
             new="            first = self._core._now()\n            return self._core._guarded(\"request_invalid\", lambda now: body(req, first))"),
    Mutation("2QB8-amendments-refusal-escapes", "2q-b8", "an amendments route runs outside `_guarded`: a write the store refuses is an error, not a refusal",
             (WIRING + "TransactionTest.test_each_write_route_is_refused_whole_whichever_write_the_store_refuses",), target=AMENDMENTS, old=GUARDED,
             new="            with self._core._transaction():\n                return body(req, self._core._now())",
             also=((TEMPLATES, TEMPLATES + "    def _transaction(self): ...\n"),)),
    Mutation("2QB8-fence-opens-its-own-transaction", "2q-b8", "the fence requests a cancellation in a transaction of its own, inside the approval's",
             (WIRING + "ApprovalTest.test_an_approval_that_fences_work_is_refused_whole_whichever_write_the_store_refuses",), target=AMENDMENTS, old=CANCEL,
             new="            with self._core._store.transaction():\n    " + CANCEL),
    Mutation("2QB8-router-delegate-drops-an-argument", "2q-b8", "the Router's `_record_replacements` no longer passes `now` to amendments",
             (WIRING + "DelegateTest.test_each_delegate_forwards_its_call_to_the_collaborator_and_returns_its_answer",), target=SERVICE,
             old=REPLACEMENTS, new="        return self._amendments._record_replacements(d, current)"),
    Mutation("2QB8-router-delegate-calls-another-route", "2q-b8", "the Router's `close_brief` calls amendments' `mark_brief_overdue`",
             (WIRING + "DelegateTest.test_each_delegate_forwards_its_call_to_the_collaborator_and_returns_its_answer",), target=SERVICE,
             old=CLOSE, new="        return self._amendments.mark_brief_overdue(request)"),
]
