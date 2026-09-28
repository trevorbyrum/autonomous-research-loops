"""The operator's recovery of a stalled job (task 1e-repair; Astra 1e review
finding 2, carrying the 1c re-review 2 ruling): an authenticated operator
command, recover_incident, that asks the station to end the job's execution
group afresh, reconcile its outcome_unknown episode through the router under
the invocation's own capability, and resume it — for all five invocation
kinds, over real HTTP to the engine (operator_fixtures), with real child
processes (supervisor_fixtures' launcher and fake executor).

The collected-end incident is produced for real, as the 1c re-review
demonstrated it: a hanging job passes its deadline, the supervisor's
termination of its group is not confirmed (jobs.Job.terminate patched to
confirm nothing, as test_supervisor_budgets' Unconfirmed does: a group that
will not end cannot be made on demand), the end is retained with its
descendants unconfirmed, and the unknown budget runs out. Then, as the review
showed, ending the owned group from outside and calling recover() stays
stalled: the retained observation is what the job holds. The operator's
recovery is the route that reconciles it: fresh termination evidence, the
episode reconciled, the old evidence kept, capacity released only then.

Read-backs are raw SQL on the test's own connection, the spool and the job's
journal read from disk; expected outcomes are written by hand.
"""
from __future__ import annotations

import io
import json
import os
import signal
import time
import unittest
from unittest import mock

from gen2.app import cli
from gen2.supervisor import jobs
from gen2.tests import operator_fixtures as of
from gen2.tests import supervisor_fixtures as sf
from gen2.tests.router_fixtures import TOPIC
from gen2.tests.supervisor_fixtures import AFTER_DEADLINE, MAIN, PARENT

FORBIDDEN = {"status": "refused", "reason": "forbidden"}


class Unconfirmed:
    """jobs.Job.terminate for a group that will not end: nothing is
    signalled, the group is never confirmed empty (test_supervisor_budgets)."""

    def __init__(self) -> None:
        self.calls = 0

    def patched(self):
        def terminate(job, identity, **kwargs) -> dict:
            self.calls += 1
            return {"found": len(jobs.members(identity)), "confirmed": False}
        return mock.patch.object(jobs.Job, "terminate", terminate)


class RecoveryFaults:
    """The engine's station runs real jobs under the fast fixture policy
    (recovery budget 3, unknown budget 5), its supervisor driven on the
    engine's owner thread as the composition root would drive it."""
    KIND: str

    def setUp(self) -> None:
        super().setUp()
        self.engine.close()
        self.engine = None
        self.to_queued()
        self.engine = self.start_engine(fixture_policy=sf.FAST, supervisor_options={"launcher": sf.launcher()})

    def tearDown(self) -> None:
        survivors = self.end_every_process()  # while the engine, whose supervisor reaps its launchers, still runs
        super().tearDown()
        self.assertEqual(survivors, [], "a job's process outlived its test")

    def end_every_process(self) -> list[int]:
        """SIGKILL every member of every job's group; returns any pid still
        alive after that (supervisor_fixtures' own, for this engine's jobs)."""
        own, left = os.getsid(0), []
        for identity_file in (self.root / "jobs").glob("*/identity.json"):
            identity = json.loads(identity_file.read_text())
            if identity["session"] == own:
                continue
            for pid in jobs.members(identity):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + 5
            while jobs.members(identity) and time.monotonic() < deadline:
                self.reap()
                time.sleep(0.01)
            left += jobs.members(identity)
        self.reap()
        return left

    def reap(self) -> None:
        if self.engine is not None:
            for popen in list(self.engine.station.supervisor._children.values()):
                popen.poll()

    def supervise(self, step):
        return self.engine.call(lambda station: step(station.supervisor))

    order = sf.SupervisedTestCase.order

    def journal(self, inv: str = MAIN) -> dict:
        return json.loads((self.root / "jobs" / f"job-{inv}" / "journal.json").read_text())

    # -- the collected end, stalled ------------------------------------------------
    def stall_on_the_collected_end(self) -> dict:
        """A hanging job past its deadline whose group's termination is not
        confirmed: the end is retained unconfirmed, the episode entered, the
        unknown budget spent, the job stalled. Returns its identity."""
        if self.KIND == "delegate":
            parent = self.order("research_pass", [{"op": "hang"}], inv=PARENT, deadline=sf.rf.DEADLINE)
            self.assertEqual(self.supervise(lambda s: s.submit(parent)), "running")
        self.assertEqual(self.supervise(lambda s: s.submit(self.order(self.KIND, [{"op": "hang"}]))), "running")
        identity = json.loads((self.root / "jobs" / f"job-{MAIN}" / "identity.json").read_text())
        self.clock.set(AFTER_DEADLINE)
        with Unconfirmed().patched():
            outcomes = [self.supervise(lambda s: s.advance(MAIN))]
        while outcomes[-1] != "stalled" and len(outcomes) < 10:
            outcomes.append(self.supervise(lambda s: s.advance(MAIN)))
        self.assertEqual(outcomes, ["unknown_unresolved"] * 5 + ["stalled"])
        journal = self.journal()
        self.assertEqual((journal["incident"]["kind"], journal["incident"]["last_finding"], journal["collected"]["observation"]["descendants"]["handling"],
                          journal["collected"]["terminated"]),
                         ("outcome_unknown_unresolved", "the collected end's descendants are not confirmed ended", "unconfirmed", "timeout"))
        self.assertNotEqual(jobs.members(identity), [])  # nothing ended the group: it hangs on
        return identity

    def held(self) -> dict:
        """What must not move before the reconciliation: the invocation's
        state, its episode's hold, its lease (the parent's, for a delegate)."""
        lease = self.value("SELECT lease_id FROM invocations WHERE invocation_id = ?", MAIN) or self.value(
            "SELECT lease_id FROM invocations WHERE invocation_id = ?", PARENT)
        return {"state": self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN),
                "open_holds": self.value("SELECT count(*) FROM holds WHERE subject_ref = ? AND cleared_at IS NULL", f"invocation:{MAIN}#unknown:1"),
                "lease_released": self.value("SELECT released_at IS NOT NULL FROM leases WHERE lease_id = ?", lease),
                "reconciliations": self.value("SELECT count(*) FROM invocation_reconciliations WHERE invocation_id = ?", MAIN)}

    UNRECONCILED = {"state": "outcome_unknown", "open_holds": 1, "lease_released": 0, "reconciliations": 0}

    def request(self, **change) -> dict:
        """The operator's request for the job's open incident (the one status names)."""
        since = change.pop("incident_since", None) or self.journal()["incident"]["since"]
        return {"invocation_id": MAIN, "incident_since": since, "reason": "the operator ended the stray group", **change}

    def reconciled(self, retained: dict) -> None:
        """The episode reconciled by the router from fresh evidence, the old
        evidence as it was, the hold cleared by that reconciliation, and the
        lease released only then (a delegate's is its running parent's)."""
        rec_id, evidence, resolution, method = self.rows(
            "SELECT reconciliation_id, evidence_ref, resolution, method FROM invocation_reconciliations WHERE invocation_id = ?", MAIN)[0]
        self.assertEqual((resolution, method), ("terminated_group", "execution_group_termination"))
        self.assertEqual(self.rows("SELECT state, failure_class, end_evidence_ref FROM invocations WHERE invocation_id = ?", MAIN),
                         [("failed", "timeout", evidence)])
        self.assertNotEqual(evidence, retained["record"]["content_hash"])
        fresh = json.loads(self.spool.real.read(evidence, topic_id=TOPIC))
        old = json.loads(self.spool.real.read(retained["record"]["content_hash"], topic_id=TOPIC))
        self.assertEqual(old["descendants"]["handling"], "unconfirmed")  # the old evidence, unchanged in the spool
        self.assertEqual({k: v for k, v in fresh.items() if k not in ("observed_at", "descendants")},
                         {k: v for k, v in old.items() if k not in ("observed_at", "descendants")})
        self.assertIn(fresh["descendants"]["handling"], ("terminated", "none_found"))
        journal = self.journal()
        self.assertEqual({k: journal["collected"][k] for k in ("observation", "record")}, {k: retained[k] for k in ("observation", "record")})
        self.assertEqual(self.rows("SELECT cleared_by_reconciliation_id FROM holds WHERE subject_ref = ?", f"invocation:{MAIN}#unknown:1"), [(rec_id,)])
        self.assertEqual(self.value("SELECT count(*) FROM operator_decisions WHERE kind = 'hold_clearance'"), 0)  # only the reconciliation cleared it (A7)
        if self.KIND == "delegate":  # its parent runs on under the lease they share
            self.assertEqual(self.held()["lease_released"], 0)
        else:
            lease = self.value("SELECT lease_id FROM invocations WHERE invocation_id = ?", MAIN)
            self.assertEqual(self.rows("SELECT release_reason FROM leases WHERE lease_id = ?", lease), [("failed",)])

    # -- the tests -----------------------------------------------------------------
    def test_recover_alone_stays_stalled_and_the_operators_recovery_reconciles_the_collected_end(self) -> None:
        identity = self.stall_on_the_collected_end()
        retained = self.journal()["collected"]
        old_bytes = self.spool.real.read(retained["record"]["content_hash"], topic_id=TOPIC)
        # the 1c re-review's demonstration: the owned group ended from outside, then recover() — it stalls again at once
        jobs.Job(self.root / "jobs", f"job-{MAIN}").terminate(identity, term_grace=0.5, kill_grace=5.0, reap=self.reap)
        self.assertEqual(jobs.members(identity), [])
        self.assertEqual(self.supervise(lambda s: s.recover())[MAIN], "stalled")
        self.assertEqual(self.held(), self.UNRECONCILED)
        stalled = self.journal()["incident"]
        self.assertEqual((stalled["kind"], self.journal()["budgets"]["recovery"]), ("outcome_unknown_unresolved", 1))
        # refused without the operator: nothing changes
        before, journal_before = self.state(exclude=()), self.journal()
        for token, code, reply in ((None, 401, {"status": "refused", "reason": "unauthenticated"}), (of.EXPORTER_TOKEN, 403, FORBIDDEN)):
            with self.subTest(token=token):
                self.assertEqual(self.command("recover_incident", self.request(), token=token), (code, reply))
        for field in ("requested_by", "capability_id"):
            with self.subTest(field=field):
                code, reply = self.command("recover_incident", self.request(**{field: "mallory"}))
                self.assertEqual((code, reply.get("reason")), (400, "authority_in_request"))
        self.assertEqual((self.state(exclude=()), self.journal()), (before, journal_before))
        # the operator's recovery: the incident status names, then the store
        on_invocation = [w for i in self.topic_status()["invocations"] if i["invocation_id"] == MAIN for w in i["waiting"] if w["reason"] == "incident"]
        self.assertEqual([(w["incident"]["since"], w["incident"]["clears_when"]) for w in on_invocation], [(stalled["since"], "recover_incident")])
        code, reply = self.command("recover_incident", self.request())
        self.assertEqual((code, reply["status"], reply["outcome"], reply["incident"], reply["requested_by"]), (200, "resumed", "failed", stalled, "alice"))
        self.assertEqual(reply["termination"]["descendants"], {"handling": "none_found", "count": 0})  # already ended from outside: nothing left
        self.reconciled(retained)
        self.assertEqual(self.spool.real.read(retained["record"]["content_hash"], topic_id=TOPIC), old_bytes)
        journal = self.journal()
        self.assertEqual((journal["budgets"]["recovery"], journal["incident"], journal["settled"]), (2, None, "failed"))
        self.assertEqual(journal["collected"]["rehandled"]["requested_by"], "alice")
        # the same request again replays the recovery that closed the incident; nothing more happens
        after = self.state(exclude=())
        code, again = self.command("recover_incident", self.request(incident_since=stalled["since"]))
        self.assertEqual((code, again), (200, {**reply, "status": "replayed"}))
        self.assertEqual(self.state(exclude=()), after)
        self.assertEqual([i["invocation_id"] for i in self.status_doc()["incidents"]], [])

    def test_the_station_ends_a_live_group_itself(self) -> None:
        """Nothing ended the group from outside: the operator's recovery,
        sent by the CLI, ends it, and only then is the episode reconciled."""
        identity = self.stall_on_the_collected_end()
        retained = self.journal()["collected"]
        host, port = self.engine.address
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["call", "recover_incident"], environ={"GEN2_OPERATOR_URL": f"http://{host}:{port}", "GEN2_OPERATOR_TOKEN": of.OTHER_OPERATOR_TOKEN},
                        stdin=io.StringIO(json.dumps(self.request())), stdout=out, stderr=err)
        reply = json.loads(out.getvalue())
        self.assertEqual((code, reply["status"], reply["outcome"], reply["requested_by"]), (0, "resumed", "failed", "bob"), err.getvalue())
        self.assertEqual(reply["termination"]["descendants"]["handling"], "terminated")
        self.assertGreater(reply["termination"]["descendants"]["count"], 0)
        self.assertEqual(jobs.members(identity), [])
        self.reconciled(retained)

    def test_capacity_is_not_released_while_the_group_is_not_confirmed_ended(self) -> None:
        """The station's fresh termination is not confirmed either: refused,
        the incident kept as raised, the episode's hold and the lease held;
        the recovery budget spent. The next request, the group ending, recovers."""
        identity = self.stall_on_the_collected_end()
        incident = self.journal()["incident"]
        before = self.state(exclude=())
        unconfirmed = Unconfirmed()
        with unconfirmed.patched():
            code, reply = self.command("recover_incident", self.request())
        self.assertEqual((code, reply["status"], reply["reason"], unconfirmed.calls), (200, "refused", "termination_unconfirmed", 1))
        self.assertEqual(reply["termination"]["descendants"]["handling"], "unconfirmed")
        self.assertEqual((self.held(), self.state(exclude=())), (self.UNRECONCILED, before))
        journal = self.journal()
        self.assertEqual((journal["incident"], journal["budgets"]["recovery"], journal["collected"].get("rehandled")), (incident, 1, None))
        self.assertNotEqual(jobs.members(identity), [])
        code, reply = self.command("recover_incident", self.request())
        self.assertEqual((code, reply["status"], reply["outcome"]), (200, "resumed", "failed"))
        self.assertEqual((self.held()["state"], self.held()["open_holds"], self.journal()["budgets"]["recovery"]), ("failed", 0, 2))

    def test_the_recovery_budget_bounds_the_operators_requests(self) -> None:
        """Three recoveries (the fixture policy's budget), each unconfirmed;
        the fourth is refused before anything is signalled, and changes
        nothing: the lease and the hold stay held."""
        self.stall_on_the_collected_end()
        unconfirmed = Unconfirmed()
        with unconfirmed.patched():
            reasons = [self.command("recover_incident", self.request())[1]["reason"] for _ in range(3)]
            before, journal_before = self.state(exclude=()), self.journal()
            code, reply = self.command("recover_incident", self.request())
        self.assertEqual(reasons, ["termination_unconfirmed"] * 3)
        self.assertEqual((code, reply["status"], reply["reason"], unconfirmed.calls), (200, "refused", "recovery_exhausted", 3))
        self.assertEqual((self.state(exclude=()), self.journal(), self.held()), (before, journal_before, self.UNRECONCILED))
        self.assertEqual(self.supervise(lambda s: s.recover())[MAIN], "stalled")  # recover() draws on the same spent budget
        self.assertEqual(self.held(), self.UNRECONCILED)

    def test_a_request_not_naming_the_open_incident_is_refused(self) -> None:
        self.stall_on_the_collected_end()
        before, journal_before = self.state(exclude=()), self.journal()
        for label, body, reason in (("another incident", self.request(incident_since="2026-09-27T10:00:00Z"), "incident_not_open"),
                                    ("an unknown job", self.request(invocation_id="inv_nosuchjob01"), "unknown_invocation"),
                                    ("a path for a job", self.request(invocation_id="inv_../../../x1"), "request_invalid"),
                                    ("a field too many", {**self.request(), "evidence_ref": sf.rf.h("1")}, "request_invalid"),
                                    ("no reason", {k: v for k, v in self.request().items() if k != "reason"}, "request_invalid")):
            with self.subTest(label=label):
                code, reply = self.command("recover_incident", body)
                self.assertEqual((code, reply["status"], reply["reason"]), (200, "refused", reason))
        self.assertEqual((self.state(exclude=()), self.journal()), (before, journal_before))
        self.assertEqual(self.command("recover_incident", self.request())[1]["status"], "resumed")


class ResearchPassRecoveryTest(RecoveryFaults, of.OperatorTestCase):
    KIND = "research_pass"


class DiscoveryRecoveryTest(RecoveryFaults, of.OperatorTestCase):
    KIND = "discovery"


class DelegateRecoveryTest(RecoveryFaults, of.OperatorTestCase):
    KIND = "delegate"


class VerificationRecoveryTest(RecoveryFaults, of.OperatorTestCase):
    KIND = "verification"


class CheckpointRecoveryTest(RecoveryFaults, of.OperatorTestCase):
    KIND = "checkpoint"


if __name__ == "__main__":
    unittest.main()
