"""Mutants of task 2q-b3: the Router's third explicit collaborator (gen2/router/registries.py), the rules its conversion added broken alone, as router_composition_2qb2.py
does for the first two; gen2/tests/test_router_composition.py reads the source, so each is killed by the one test it breaks and another static test is its paired control.

  2QB3-registries-core-omits-a-member           the collaborator uses a member of the core that RegistriesCore no longer declares;
  2QB3-registries-opens-the-store-transaction   the collaborator opens a transaction on the store instead of taking the core's `_transaction`;
  2QB3-registries-takes-the-read-snapshot       the collaborator takes the core's `_snapshot` (declared, so only the snapshot rule sees it): a write in the status read's transaction.
"""
from __future__ import annotations

from .base import Mutation
from .router_composition_2qb2 import CI, HOLDS_ONLY_CORE, USED_DECLARED

SNAPSHOT_ONLY_STATUS = CI + "test_only_the_status_read_takes_the_core_snapshot"
REGISTRIES = "gen2/router/registries.py"
RESTORE = "        with self._core._transaction():\n            active = self._active_bundle()"
TRANSACTION_DECLARATION = "    def _transaction(self) -> AbstractContextManager: ...  # the two writes that are not _guarded's: see the note on Registries\n"

MUTATIONS: list[Mutation] = [
    Mutation("2QB3-registries-core-omits-a-member", "2q-b3", "RegistriesCore no longer declares `_audit`, which the registries use", (USED_DECLARED,), target=REGISTRIES,
             old="    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str: ...\n", new=""),
    Mutation("2QB3-registries-opens-the-store-transaction", "2q-b3", "the start's recovery fact opens a transaction on the store, not the core's", (HOLDS_ONLY_CORE,), target=REGISTRIES,
             old=RESTORE, new=RESTORE.replace("self._core._transaction()", "self._core._store.transaction()")),
    Mutation("2QB3-registries-takes-the-read-snapshot", "2q-b3", "the start's recovery fact is written in the status read's snapshot", (SNAPSHOT_ONLY_STATUS,), target=REGISTRIES,
             old=RESTORE, new=RESTORE.replace("self._core._transaction()", "self._core._snapshot()"),
             also=((TRANSACTION_DECLARATION, "    def _snapshot(self) -> AbstractContextManager: ...\n" + TRANSACTION_DECLARATION),)),
]
