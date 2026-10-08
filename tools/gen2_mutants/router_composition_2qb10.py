"""Mutants of task 2q-b10: the Router's seventh explicit collaborator (gen2/router/evidence_writer.py), the rules its conversion added broken alone, as router_composition_2qb7.py
does for the fifth. The composition test reads the source, so the static ones are killed by the one test they break (another static test is the paired control); the two delegate
ones are killed by the existing evidence tests, which commit an outbox event and a review closure through `_write_evidence`. (The helper boundaries are 2QB9's.)

  2QB10-evidence-core-omits-a-member                the writer uses a member of the core that EvidenceCore no longer declares;
  2QB10-evidence-writer-opens-its-own-transaction   the writer opens a transaction on the store instead of running inside the commit's;
  2QB10-router-inherits-the-evidence-writer         the Router inherits EvidenceWriter, so it is a mixin and no longer composes it;
  2QB10-router-delegate-drops-the-outbox            the Router's `_write_evidence` delegate hands the writer no outbox events;
  2QB10-router-delegate-drops-the-triggers          the delegate hands the writer no new review triggers.
"""
from __future__ import annotations

from .base import EVW, SVC, Mutation
from .router_composition_2qb2 import COMPOSES, HOLDS_ONLY_CORE, USED_DECLARED

DELEGATE = "        return self._evidence_writer._write_evidence(env, inv, checked, now, new_triggers, outbox)"
OUTBOX, CLOSURE = "test_router_evidence.ExportTest.test_an_approved_manifest_enters_the_outbox_with_its_hash", "test_router_workflow.ReviewClosureTest.test_the_checkpoint_closes_its_episode_and_handles_its_triggers"
HOLD = '            self._core._store.insert("holds", {**hold, "topic_id": topic_id, "created_at": now, "created_by_operation_id": op_id})'

MUTATIONS: list[Mutation] = [
    Mutation("2QB10-evidence-core-omits-a-member", "2q-b10", "EvidenceCore no longer declares `_work_of_topic`, which the evidence writer uses", (USED_DECLARED,), target=EVW,
             old="    def _work_of_topic(self, work_id: str, topic_id: str) -> bool: ...\n", new=""),
    Mutation("2QB10-evidence-writer-opens-its-own-transaction", "2q-b10", "the evidence writer opens a transaction on the store, not running inside the commit's", (HOLDS_ONLY_CORE,), target=EVW,
             old=HOLD, new="            with self._core._store.transaction():\n    " + HOLD),
    Mutation("2QB10-router-inherits-the-evidence-writer", "2q-b10", "the Router inherits EvidenceWriter: a mixin again, not a composed collaborator", (COMPOSES,), target=SVC,
             old="class Router:", new="class Router(EvidenceWriter):"),
    Mutation("2QB10-router-delegate-drops-the-outbox", "2q-b10", "the Router's `_write_evidence` hands the evidence writer no outbox events", (OUTBOX,), target=SVC,
             old=DELEGATE, new=DELEGATE.replace("new_triggers, outbox)", "new_triggers, [])")),
    Mutation("2QB10-router-delegate-drops-the-triggers", "2q-b10", "the Router's `_write_evidence` hands the evidence writer no new review triggers", (CLOSURE,), target=SVC,
             old=DELEGATE, new=DELEGATE.replace("now, new_triggers, outbox)", "now, [], outbox)")),
]
