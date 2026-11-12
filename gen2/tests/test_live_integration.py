"""L1 + L2 together on the fixture route (no provider, no container): the production driver walks one topic through the real station, Router and
supervisor with a verified qualification record mounted and `live` set. Oracle: the Router's own audit rows (dispatch_authorized, dispatch_result),
its records, and the job files. What is real: the authority and record verification, the plan writer, the live gate, the Router's authorization and
result recording, the driver's flag, the production child and builders. What is canned: the model (OfflineAgent) and the backend's confirmed end,
which `live_fixture_child` leaves as the same `docker-complete.json` `DockerCLI.run` writes. The real-route backend is PR-L2's own suite; a native run
is lane C's.
"""
import json
import sqlite3
import unittest
from pathlib import Path

from gen2.tests.offline_run import Offline
from gen2.tests.test_supervisor_live import MANIFEST, record_doc

CHILD = "gen2.tests.live_fixture_child"
POLICY = {"run_id": "trial-1", "accounting_owner": "operator", "deadline_at": "2026-12-30T00:00:00Z", "max_attempts": 60, "ceiling_minor_units": 10000,
          "currency": "USD", "ceiling_scope": ["model", "delegates", "retries", "verification", "gateway", "maintenance"], "policy_version": "v1"}


def record(root):
    return record_doc(root, policy=POLICY), MANIFEST


def audit(run, kind):
    with sqlite3.connect(Path(run.tmp.name) / "station" / "store.sqlite3") as db:
        return [json.loads(row[0]) for row in db.execute("SELECT detail FROM audit_events WHERE kind = ? ORDER BY at, audit_event_id", (kind,))]


class LiveFixtureRoute(unittest.TestCase):
    def world(self, **options):
        run = Offline(child_module=CHILD, **options)
        self.addCleanup(run.close)
        return run

    def test_every_model_step_is_authorized_before_its_start_charged_worst_case_and_the_topic_still_completes(self):
        run = self.world(record=record, live=True)
        self.assertEqual(run.walk(), "done")
        intents, results = audit(run, "dispatch_authorized"), audit(run, "dispatch_result")
        self.assertGreaterEqual(len(intents), 5)                                           # scope, research, verify, challenge x2, review: all model purposes
        self.assertEqual(len(intents), len(results))                                       # each authorized attempt has its one recorded result
        self.assertEqual({i["origin"]["route"] for i in intents}, {"fixture"})             # a fixture run can never present a real route
        self.assertEqual({(r["charge_minor_units"], r["response"]["charge_state"]) for r in results}, {(400, "worst_case")})   # unknown cost: U, and the walk continued (DEBT-052)
        self.assertEqual(run.topic()["status"], "completed_with_qualified_conclusions")

    def test_refused_fixture_judgment_has_a_confirmed_failed_end_and_worst_case_charge(self):
        """Local oracle for the native fixture seam; this does not run the dedicated endpoint."""
        run = self.world(record=record, live=True, invalid_judgment=True)
        self.assertTrue(run.walk().startswith("stopped"))
        self.assertEqual([(r["state"], r["failure_class"]) for r in run.records("invocations")], [("failed", "exit_nonzero")])
        self.assertEqual(len(audit(run, "dispatch_authorized")), 1)
        (result,) = audit(run, "dispatch_result")
        self.assertEqual((result["charge_minor_units"], result["response"]["charge_state"]), (400, "worst_case"))
        (end,) = (Path(run.tmp.name) / "station" / "jobs").glob("*/exit.json")
        self.assertEqual(json.loads(end.read_text())["code"], 2)
        self.assertTrue(end.with_name("docker-complete.json").exists())
        journal = json.loads(end.with_name("journal.json").read_text())
        self.assertEqual(journal["settled"], "failed")
        self.assertNotEqual(journal["collected"]["observation"]["descendants"]["handling"], "unconfirmed")
        self.assertEqual(run.records("operator_decisions")[-1]["kind"], "brief_confirmation")

    def test_without_the_flag_the_same_record_is_never_used_and_no_intent_is_written(self):
        run = self.world(record=record, live=False)
        self.assertEqual(run.walk(), "done")
        self.assertEqual((audit(run, "dispatch_authorized"), audit(run, "dispatch_result")), ([], []))

    def test_with_no_record_a_live_walk_refuses_at_the_first_model_step_and_starts_nothing(self):
        run = self.world(live=True)
        self.assertEqual(run.walk(), "stopped: live_refused")  # the walker maps LiveProfileRefused to its own fixed code
        self.assertEqual(audit(run, "dispatch_authorized"), [])
        self.assertFalse(list((Path(run.tmp.name) / "station" / "jobs").glob("*/spawn.json")))

    def test_an_end_that_cannot_be_confirmed_stops_the_walk_keeps_the_intent_and_records_no_result(self):
        run = self.world(record=record, live=True)
        (Path(run.tmp.name) / "station" / "no-end").write_text("")                         # the backend leaves no confirmed end
        text = run.walk()
        self.assertTrue(text.startswith("stopped") and "needs_person" in text, text)
        self.assertEqual((len(audit(run, "dispatch_authorized")), audit(run, "dispatch_result")), (1, []))


if __name__ == "__main__":
    unittest.main()
