"""Rule: a recorded purpose's evidence is written, replayably, before its result reaches the router (2e2 T12-B; Astra F2).

Oracle: raw store reads (`ended`) and a recorder whose effects are keyed by a stable id, as a real one's must be.
Limits: the effects here are a set, not router writes (T13/T15/T16 own those); the reconciled path is fail-closed by choice.
"""
from dataclasses import replace
from pathlib import Path

from gen2.supervisor.supervisor import RecorderMissing
from gen2.tests import children
from gen2.tests.supervisor_fixtures import MAIN, SupervisedTestCase

KEY = "discovery/search"


class Recording(SupervisedTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.effects, self.calls, self.states, self.fail = set(), [], [], 0

    def recorder(self, control, order, grant, scratch) -> None:
        self.calls.append((control, order["invocation_id"], grant["invocation_id"], scratch))
        self.states.append(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN))
        self.effects.add("observation:" + order["invocation_id"])  # a stable identity: a repeat adds nothing
        if len(self.calls) <= self.fail:
            raise RuntimeError("lost reply")

    def station(self, **options):
        return self.make_supervisor(recorders={KEY: self.recorder}, **options)

    def order_for(self, purpose="search", inv=MAIN):
        return replace(self.order("discovery", inv=inv), env={"GEN2_PURPOSE": purpose})

    def test_a_required_purpose_without_a_recorder_refuses_before_anything_is_written(self) -> None:
        for number, (purpose, supervisor, refused) in enumerate((("search", self.supervisor, True), ("search", self.station(), False),
                                                                 ("other", self.supervisor, False))):
            with self.subTest(purpose=purpose, refused=refused):
                inv = f"inv_subject10{number}"
                if refused:
                    with self.assertRaises(RecorderMissing):
                        supervisor.prepare(self.order_for(purpose, inv))
                else:
                    supervisor.prepare(self.order_for(purpose, inv))
                self.assertEqual((self.root / "jobs" / ("job-" + inv) / "order.json").exists(), not refused)

    def test_the_recorder_runs_while_running_and_before_the_result_is_committed(self) -> None:
        supervisor = self.station()
        self.assertEqual(supervisor.submit(self.order_for()), "running")
        self.assertEqual(supervisor.run(MAIN), "committed")
        (control, ordered, granted, scratch), = self.calls
        self.assertEqual((control, ordered, granted, self.states, Path(scratch).name), (supervisor.control, MAIN, MAIN, ["running"], "scratch"))
        self.assertEqual(self.journal()["recorded"], True)
        self.assertEqual(self.ended()["state"], "committed")

    def test_a_failing_recorder_leaves_the_job_running_and_is_retried(self) -> None:
        self.fail = 2
        supervisor = self.station()
        supervisor.prepare(self.order_for())
        outcomes = []
        while not outcomes or outcomes[-1] not in ("committed", "failed"):
            outcomes.append(supervisor.advance(MAIN))
            self.assertLess(len(outcomes), 40)
        self.assertIn("record_failed", outcomes)
        self.assertEqual((self.ended()["state"], len(self.calls), self.effects), ("committed", 3, {"observation:" + MAIN}))

    def test_a_crash_after_the_effect_before_the_marker_replays_without_a_second_effect(self) -> None:
        def die(point):
            if point == "recorded_effects":
                raise KeyboardInterrupt(point)
        self.station(fault=die).prepare(self.order_for())
        with self.assertRaises(KeyboardInterrupt):
            self.station(fault=die).run(MAIN)
        self.assertNotIn("recorded", self.journal())
        self.assertEqual(self.station().run(MAIN), "committed")
        self.assertEqual((len(self.calls), len(self.effects)), (2, 1))
        self.assertEqual(self.value("SELECT count(*) FROM invocation_transitions WHERE to_state = 'result_ready' AND invocation_id = ?", MAIN), 1)

    def test_exhausted_recording_ends_the_job_failed_with_an_owned_deadlined_incident_and_no_commit(self) -> None:
        self.fail = 99
        supervisor = self.station()
        supervisor.prepare(self.order_for())
        self.assertEqual(supervisor.run(MAIN), "failed")
        ended, journal = self.ended(), self.journal()
        self.assertEqual((ended["state"], ended["failure_class"], len(self.calls), "result_ready" in ended["transitions"]), ("failed", "result_rejected", 3, False))
        self.assertEqual(self.evidence_record()["output"]["detail"], "result_not_recorded")
        self.assertEqual((journal["exhausted"]["kind"], journal["exhausted"]["budget"], journal["exhausted"]["owner"].startswith("supervisor:")),
                         ("retry_exhausted", "write", True))
        self.assertTrue(journal["exhausted"]["deadline_at"])

    def test_a_result_found_by_reconciliation_is_not_committed_unrecorded(self) -> None:
        self.station().prepare(self.order_for())
        child = children.python(["-m", "gen2.tests.supervisor_child", str(self.root), MAIN, "spawned", "2026-09-27T10:30:00Z"],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(child.returncode, 137, child.stderr)
        self.wait_for_file("exit.json")
        self.clock.set("2026-09-27T11:00:00Z")
        supervisor = self.station()
        supervisor.recover()
        self.assertEqual(supervisor.run(MAIN), "failed")
        ended = self.ended()
        self.assertEqual((ended["failure_class"], ended["reconciliations"], self.calls), ("result_rejected", ["confirmed_failed"], []))
        self.assertEqual(self.evidence_record()["output"]["detail"], "result_not_recorded")
