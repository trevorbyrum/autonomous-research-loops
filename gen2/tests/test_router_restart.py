"""What a restart keeps: recorded facts replay, and recorded documents read
back whole, from a durable store opened again by a new router (task 1b;
Astra 1b review A2, A5).

Trace: gen2/core/control.py (each operation is idempotent under its own key,
so a caller that lost a reply resubmits after any restart); INVARIANTS C-5,
C-11, L-1, P-7.

Each test builds its world through one router on a durable store, closes it,
and opens the store again with a new router (a new connection, nothing
carried in memory). Oracles: expected outcomes by hand; raw SQL read-back on
a separate connection.

Structural limits: a clean close and reopen in one process; a killed process
is test_router_crash.py.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gen2.router import service
from gen2.tests import router_crash_child  # not its World by name: the loader would collect it
from gen2.tests import router_fixtures as rf


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


if __name__ == "__main__":
    unittest.main()
