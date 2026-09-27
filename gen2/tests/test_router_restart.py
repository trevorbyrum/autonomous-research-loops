"""What a restart keeps: recorded facts replay, and recorded documents read
back whole, from a durable store opened again by a new router (task 1b;
Astra 1b review A2, A5; Astra 1b-repair review A5-R).

Trace: gen2/core/control.py (each operation is idempotent under its own key,
so a caller that lost a reply resubmits after any restart); INVARIANTS C-5,
C-11, L-1, P-7.

Each test builds its world through one router on a durable store, closes it,
and opens the store again with a new router (a new connection, nothing
carried in memory). Oracles: expected outcomes by hand; raw SQL read-back on
a separate connection.

A committed result's lost result_ready reply is also resent from a fresh
process (router_crash_child.py), past its lease and deadline, and then from a
reopened router in this one: the mutation runner's in-memory mutants reach
only the second.

Structural limits: a clean close and reopen (and a fresh process that shares
nothing in memory); a killed process is test_router_crash.py.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gen2.router import service
from gen2.tests import children
from gen2.tests import router_crash_child  # not its World by name: the loader would collect it
from gen2.tests import router_fixtures as rf

LAPSED = "2026-09-27T10:30:00Z"  # a lease and deadline every restart below comes after (the child's clock starts at 11:00)


class RestartTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.world = router_crash_child.World(Path(self.tmp.name))
        self.world.setUp()
        self.world.to_queued()

    def tearDown(self) -> None:
        self.world.router.close()
        self.world.db.close()
        self.tmp.cleanup()

    def restart(self) -> None:
        self.world.router.close()
        self.world.router = service.Router.open(self.world.directory / "store.sqlite3", self.world.spool, clock=self.world.clock, new_id=self.world.ids)

    def committed_result(self) -> tuple[dict, dict]:
        """A checkpoint whose result_ready is recorded and whose final outcome
        is committed, its lease and deadline at LAPSED; its router closed.
        Returns the result_ready request and every table's rows."""
        grant = self.world.started("inv_checkpt01", "checkpoint", lease_expires_at=LAPSED, deadline_at=LAPSED)
        env = self.world.envelope(grant, "op_final000001", rf.empty_outcome("inv_checkpt01"))
        request = {"capability_id": grant["capability_id"], "invocation_id": "inv_checkpt01", "to_state": "result_ready",
                   "result_payload_digest": env["payload_digest"]}
        self.assertEqual(self.world.router.record_transition(request)["status"], "recorded")
        self.assertEqual(self.world.router.commit_outcome(env)["status"], "committed")
        self.world.router.close()
        return request, self.world.state(exclude=())

    def resent(self, request: dict) -> list[dict]:
        """The request answered by a fresh process, then by a router reopened
        here with its clock past LAPSED."""
        child = children.python(["-m", "gen2.tests.router_crash_child", str(self.world.directory), "transition"],
                                input=json.dumps(request), capture_output=True, text=True, timeout=120)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.world.clock.set("2026-09-27T11:00:00Z")
        self.restart()
        return [json.loads(child.stdout), self.world.router.record_transition(request)]

    def test_recorded_facts_replay_after_a_restart(self) -> None:
        grant = self.world.started("inv_research01")
        facts = (("launching", {"job_handle": "job-inv_research01"}),
                 ("running", {"host_id": "host-1", "boot_id": "boot-1", "start_fingerprint": "ticks=1"}))
        self.restart()
        before = self.world.state(exclude=())
        for to_state, recorded in facts:
            with self.subTest(to_state):
                out = self.world.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"],
                                                           "to_state": to_state, **recorded})
                self.assertEqual(out["status"], "replayed", out)
                self.assertEqual(self.world.state(exclude=()), before)
        out = self.world.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"],
                                                   "to_state": "launching", "job_handle": "job-other"})
        self.assertEqual((out["status"], out.get("reason")), ("refused", "transition_conflict"))
        self.assertEqual(self.world.state(exclude=()), before)

    def test_a_committed_result_replays_without_its_staged_bytes(self) -> None:
        """Astra 1b-repair review A5-R (1): once the outcome is committed its
        staged copy may be gone (C-9); the identical result_ready, resent
        after a restart and past the lease and deadline, still replays, and
        nothing is written (state, timestamps, history, audit)."""
        request, before = self.committed_result()
        self.world.spool.remove(request["result_payload_digest"])
        for where, out in zip(("fresh process", "reopened router"), self.resent(request)):
            with self.subTest(where):
                self.assertEqual(out, {"status": "replayed", "invocation_id": "inv_checkpt01", "state": "result_ready"})
                self.assertEqual(self.world.state(exclude=()), before)

    def test_a_committed_result_resent_with_an_unstaged_digest_conflicts(self) -> None:
        """Astra 1b-repair review A5-R (2): the recorded key with another
        digest, one staged nowhere, is a transition_conflict (the recorded
        fact decides), not payload_missing; nothing is written."""
        request, before = self.committed_result()
        changed = {**request, "result_payload_digest": rf.h("8")}
        self.assertIsNone(self.world.spool.read(changed["result_payload_digest"], topic_id=rf.TOPIC))
        for where, out in zip(("fresh process", "reopened router"), self.resent(changed)):
            with self.subTest(where):
                self.assertEqual((out["status"], out.get("reason")), ("refused", "transition_conflict"), out)
                self.assertEqual(self.world.state(exclude=()), before)

    def test_delivery_receipts_read_back_whole_after_a_restart(self) -> None:
        """Astra 1b review A2: what a connector reported survives a restart
        exactly — the stored document is the receipt's JCS bytes, the count
        keeps its state, the references are kept — and after the restart the
        same document replays while a changed one conflicts."""
        checkpoint = self.world.started("inv_checkpt01", "checkpoint")
        self.world.export(checkpoint, 1)
        self.world.hold(checkpoint, "hold_000000000001")
        docs = [self.world.delivery_receipt("exr_000000000001", "outcome_unknown", capability_fact_id="fact_warehouse01", hold_id="hold_000000000001",
                                            invocation_id="inv_checkpt01", written={"status": "partial", "value": 7, "reason": "seven rows acknowledged"}),
                self.world.delivery_receipt("exr_000000000002", "outcome_unknown", attempt=2, capability_fact_id="fact_warehouse01"),
                self.world.delivery_receipt("exr_000000000003", attempt=3)]
        for doc in docs:
            self.assertEqual(self.world.router.ack_delivery(doc)["status"], "recorded")
        self.restart()
        self.assertEqual(self.world.rows("SELECT receipt, written_status, written_value, hold_id FROM export_delivery_receipts ORDER BY attempt"),
                         [(rf.jcs(docs[0]).decode(), "partial", 7, "hold_000000000001"), (rf.jcs(docs[1]).decode(), "unknown", None, None),
                          (rf.jcs(docs[2]).decode(), "observed", 12, None)])
        before = self.world.state(exclude=())
        for doc in docs:
            self.assertEqual(self.world.router.ack_delivery(doc)["status"], "replayed")
        self.assertEqual(self.world.state(exclude=()), before)
        out = self.world.router.ack_delivery({**docs[0], "written": {"status": "unknown", "reason": "no counts observed"}})
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "export_receipt_id_conflict"))
        self.assertEqual(self.world.state(exclude=()), before)


if __name__ == "__main__":
    unittest.main()
