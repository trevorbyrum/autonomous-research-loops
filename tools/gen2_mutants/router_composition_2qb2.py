"""Mutants of task 2q-b2: the Router's explicit collaborators (gen2/router/status.py, capabilities.py), each interface rule broken alone.

gen2/tests/test_router_composition.py reads the collaborators' sources (a module target's `__file__` is the mutant's copy), so each mutant is killed by the one direction it
breaks, and the other direction's test is its paired control: it passes under the mutant.

  2QB2-status-core-omits-a-member             the collaborator uses a member of the core that its protocol no longer declares;
  2QB2-capabilities-core-declares-a-ghost     the protocol declares a member no Router has, and no collaborator uses;
  2QB2-status-reaches-the-store-directly      the collaborator holds a store of its own instead of reaching it as self._core._store;
  2QB2-status-opens-its-own-transaction       the collaborator opens a transaction on the store instead of taking the core's `_snapshot`;
  2QB2-router-inherits-a-collaborator         the Router inherits Status again, so it is a mixin and no longer composes it;
  2QB2-router-drops-a-public-method           a public method the Router had as a mixin's is no longer public.
"""
from __future__ import annotations

from .base import Mutation

CI = "test_router_composition.CollaboratorInterfaceTest."
USED_DECLARED, DECLARED_USED, ROUTER_HAS = CI + "test_every_core_member_a_collaborator_uses_is_declared", CI + "test_every_declared_member_is_one_the_collaborator_uses", CI + "test_control_every_declared_member_is_one_the_router_has"
HOLDS_ONLY_CORE, COMPOSES = CI + "test_a_collaborator_holds_only_the_core_and_reaches_the_store_through_it", CI + "test_the_router_composes_its_collaborators_and_keeps_its_public_methods"
STATUS, CAPS, SVC = "gen2/router/status.py", "gen2/router/capabilities.py", "gen2/router/service.py"

MUTATIONS: list[Mutation] = [
    Mutation("2QB2-status-core-omits-a-member", "2q-b2", "StatusCore no longer declares `_lane_last`, which the status read uses", (USED_DECLARED,), target=STATUS,
             old="    def _lane_last(self, topic_id: str, scope: str) -> str | None: ...  # scheduling.py\n", new=""),
    Mutation("2QB2-capabilities-core-declares-a-ghost", "2q-b2", "CapabilityCore declares a member no Router has", (ROUTER_HAS, DECLARED_USED), target=CAPS,
             old="    def _router_policy(self, bundle_hash: str) -> dict: ...\n",
             new="    def _router_policy(self, bundle_hash: str) -> dict: ...\n    def _ghost(self) -> None: ...\n"),
    Mutation("2QB2-status-reaches-the-store-directly", "2q-b2", "the status read selects through a store attribute of its own", (HOLDS_ONLY_CORE,), target=STATUS,
             old='        invocations = self._core._store.select("invocations", where)', new='        invocations = self._store.select("invocations", where)'),
    Mutation("2QB2-status-opens-its-own-transaction", "2q-b2", "the status read opens its own transaction instead of the core's snapshot", (HOLDS_ONLY_CORE,), target=STATUS,
             old="            with self._core._snapshot():  # one snapshot", new="            with self._core._store.transaction():  # one snapshot"),
    Mutation("2QB2-router-inherits-a-collaborator", "2q-b2", "the Router inherits Status: a mixin again, not a composed collaborator", (COMPOSES,), target=SVC,
             old="class Router(Lifecycle, Amendments, Scheduling):", new="class Router(Lifecycle, Amendments, Scheduling, Status):"),
    Mutation("2QB2-router-drops-a-public-method", "2q-b2", "the Router's `healthy` is no longer a public method", (COMPOSES,), target=SVC,
             old="    def healthy(self) -> bool:\n        return self._status.healthy()", new="    def _healthy(self) -> bool:\n        return self._status.healthy()"),
]
