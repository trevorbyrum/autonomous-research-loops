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

import http.client
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


def at(doc, *path):
    """doc[path[0]][path[1]]..., or None where any step is missing: an assertion then compares None, never raises."""
    for key in path:
        if not isinstance(doc, (dict, list)) or (key not in doc if isinstance(doc, dict) else not -len(doc) <= key < len(doc)):
            return None
        doc = doc[key]
    return doc


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


class RecoveryWorld:
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
        launchers = [*getattr(self, "replaced_launchers", [])]  # started by an engine this test has since replaced
        if self.engine is not None:
            launchers += self.engine.station.supervisor._children.values()
        for popen in launchers:
            popen.poll()

    def supervise(self, step):
        return self.engine.call(lambda station: step(station.supervisor))

    order = sf.SupervisedTestCase.order

    def journal(self, inv: str = MAIN) -> dict:
        return json.loads((self.root / "jobs" / f"job-{inv}" / "journal.json").read_text())

    # -- the collected end, stalled ------------------------------------------------
    def stall_on_the_collected_end(self, exits: bool = False) -> dict:
        """A job whose group's termination is not confirmed — a hanging job
        past its deadline, or (`exits`) one that writes its result and exits
        leaving a descendant: the end is retained unconfirmed, the episode
        entered, the unknown budget spent, the job stalled. Returns its
        identity."""
        if self.KIND == "delegate":
            parent = self.order("research_pass", [{"op": "hang"}], inv=PARENT, deadline=sf.rf.DEADLINE)
            self.assertEqual(self.supervise(lambda s: s.submit(parent)), "running")
        steps = [{"op": "spawn_descendant", "marker": "descendant.pid"}, *sf.succeed()] if exits else [{"op": "hang"}]
        self.assertEqual(self.supervise(lambda s: s.submit(self.order(self.KIND, steps))), "running")
        job_dir = self.root / "jobs" / f"job-{MAIN}"
        identity = json.loads((job_dir / "identity.json").read_text())
        if exits:
            deadline = time.monotonic() + 10
            while not (job_dir / "exit.json").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
        else:
            self.clock.set(AFTER_DEADLINE)
        with Unconfirmed().patched():
            outcomes = [self.supervise(lambda s: s.advance(MAIN))]
        while outcomes[-1] != "stalled" and len(outcomes) < 10:
            outcomes.append(self.supervise(lambda s: s.advance(MAIN)))
        self.assertEqual(outcomes, ["unknown_unresolved"] * 5 + ["stalled"])
        journal = self.journal()
        self.assertEqual((journal["incident"]["kind"], journal["incident"]["last_finding"], journal["collected"]["observation"]["descendants"]["handling"],
                          journal["collected"].get("terminated")),
                         ("outcome_unknown_unresolved", "the collected end's descendants are not confirmed ended", "unconfirmed", None if exits else "timeout"))
        self.assertNotEqual(jobs.members(identity), [])  # nothing ended the group: it (or the descendant) lives on
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

    def unfinished(self, stalled: dict, requested_by: str = "alice") -> None:
        """The journal records the recovery unfinished on its one allowance,
        and status lists it once, as its incident, blocking, with who asked
        and what clears it."""
        journal = self.journal()
        self.assertEqual((at(journal, "recovering", "incident"), at(journal, "recovering", "requested_by"), at(journal, "budgets", "recovery"),
                          journal.get("recoveries", [])), (stalled, requested_by, 1, []))
        listed = [i for i in self.status_doc()["incidents"] if i["invocation_id"] == MAIN]
        self.assertEqual([({k: i.get(k) for k in stalled}, i["blocking"], i.get("clears_when"), at(i, "recovery", "status"), at(i, "recovery", "requested_by"))
                          for i in listed], [(stalled, True, "recover_incident", "unfinished", requested_by)])

    def restart_engine(self) -> None:
        """This process's engine replaced by a new one over the same state (its launchers' processes kept reaped)."""
        self.replaced_launchers = [*getattr(self, "replaced_launchers", []), *self.engine.station.supervisor._children.values()]
        self.engine.close()
        self.engine = None
        self.engine = self.start_engine(fixture_policy=sf.FAST, supervisor_options={"launcher": sf.launcher()})


class RecoveryFaults(RecoveryWorld):
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
        self.assertEqual([(w["incident"]["since"], w["incident"].get("clears_when")) for w in on_invocation], [(stalled["since"], "recover_incident")])
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

    def test_a_clean_exit_whose_descendant_lingered_commits_once_the_group_is_ended(self) -> None:
        """The other collected end: the result written and the executor gone,
        its descendant never confirmed ended. The operator's recovery ends
        the descendant; the episode is reconciled as the result found, from
        fresh evidence, and the result commits — capacity released by the
        commit, not before."""
        identity = self.stall_on_the_collected_end(exits=True)
        retained = self.journal()["collected"]
        self.assertEqual(self.held(), self.UNRECONCILED)
        code, reply = self.command("recover_incident", self.request())
        self.assertEqual((code, reply["status"], reply["outcome"], reply["termination"]["descendants"]), (200, "resumed", "committed", {"handling": "terminated", "count": 1}))
        self.assertEqual(jobs.members(identity), [])
        self.assertEqual(self.rows("SELECT resolution, method FROM invocation_reconciliations WHERE invocation_id = ?", MAIN), [("found_result", "job_handle_lookup")])
        evidence = self.value("SELECT evidence_ref FROM invocation_reconciliations WHERE invocation_id = ?", MAIN)
        self.assertNotEqual(evidence, retained["record"]["content_hash"])
        fresh = json.loads(self.spool.real.read(evidence, topic_id=TOPIC))
        self.assertEqual((fresh["descendants"], fresh["termination"], fresh["output"]["content_hash"]),
                         ({"handling": "terminated", "count": 1}, {"reason": "descendants_after_exit"}, retained["result"]["content_hash"]))
        self.assertEqual(json.loads(self.spool.real.read(retained["record"]["content_hash"], topic_id=TOPIC))["descendants"], {"handling": "unconfirmed", "count": 1})
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "committed")
        self.assertEqual(self.rows("SELECT cleared_by_reconciliation_id IS NOT NULL FROM holds WHERE subject_ref = ?", f"invocation:{MAIN}#unknown:1"), [(1,)])
        if self.KIND != "delegate":
            lease = self.value("SELECT lease_id FROM invocations WHERE invocation_id = ?", MAIN)
            self.assertEqual(self.rows("SELECT release_reason FROM leases WHERE lease_id = ?", lease), [("final_outcome",)])

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

    # -- a recovery cut short (Astra 1e-repair re-review finding 1) -------------------------
    # In process, the cut is an exception out of the station's step (the engine answers 500), which leaves the journal as
    # that step last wrote it; ReplacedRecoveryTest cuts it with a real process exit and a replacement engine.
    def test_an_unfinished_recovery_is_finished_by_the_next_advance(self) -> None:
        """Cut before the job is advanced: the incident closed, nothing
        reconciled. After a restart the next advance is the recovery's own:
        it reconciles, and the recovery is recorded finished; the request
        again replays that, drawing nothing."""
        self.stall_on_the_collected_end()
        retained, stalled = self.journal()["collected"], self.journal()["incident"]
        s = self.engine.station.supervisor
        with mock.patch.object(s, "_advance", side_effect=RuntimeError("cut before the advance")):
            self.assertEqual(self.command("recover_incident", self.request()), (500, {"status": "error", "reason": "internal"}))
        self.assertEqual((self.held(), self.journal().get("incident"), at(self.journal(), "collected", "rehandled", "requested_by")), (self.UNRECONCILED, None, "alice"))
        self.unfinished(stalled)
        self.restart_engine()
        self.unfinished(stalled)
        self.assertEqual(self.supervise(lambda s: s.advance(MAIN)), "failed")
        self.reconciled(retained)
        journal = self.journal()
        self.assertEqual(("recovering" in journal, [r.get("outcome") for r in journal.get("recoveries", [])], at(journal, "budgets", "recovery")), (False, ["failed"], 1))
        code, again = self.command("recover_incident", self.request(incident_since=stalled["since"]))
        self.assertEqual((code, again.get("status"), again.get("outcome"), again.get("incident")), (200, "replayed", "failed", stalled))
        self.assertEqual((at(self.journal(), "budgets", "recovery"), [i["invocation_id"] for i in self.status_doc()["incidents"]]), (1, []))

    def test_recover_finishes_an_unfinished_recovery_without_drawing_again(self) -> None:
        """Cut after the recovery was recorded, before the group was ended:
        the incident still open, the group alive. recover() does not close
        the incident on an allowance of its own: it finishes the operator's
        recovery, which ends the group and reconciles."""
        identity = self.stall_on_the_collected_end()
        retained, stalled = self.journal()["collected"], self.journal()["incident"]
        with mock.patch.object(jobs.Job, "terminate", side_effect=RuntimeError("cut before the group is ended")):
            self.assertEqual(self.command("recover_incident", self.request())[0], 500)
        journal = self.journal()
        self.assertEqual((journal.get("incident"), "recovering" in journal, at(journal, "recovering", "termination"), at(journal, "collected", "rehandled")),
                         (stalled, True, None, None))
        self.unfinished(stalled)
        self.assertNotEqual(jobs.members(identity), [])
        self.restart_engine()
        self.assertEqual(self.supervise(lambda s: s.recover())[MAIN], "failed")
        self.assertEqual(jobs.members(identity), [])
        self.reconciled(retained)
        journal = self.journal()
        self.assertEqual((at(journal, "budgets", "recovery"), at(journal, "recoveries", 0, "outcome"), at(journal, "recoveries", 0, "termination", "descendants", "handling")),
                         (1, "failed", "terminated"))

    def test_an_unfinished_recovery_is_finished_before_another_incidents(self) -> None:
        """Cut after the recovery's advance stalled the job on a new incident
        (the router refused the reconciliation as a conflict, which no retry
        changes), before the recovery was recorded finished. Status lists
        both; the operator's request for the new incident first finishes the
        old recovery (its advance stalls again on the new incident), then
        recovers the new one on a second allowance."""
        self.stall_on_the_collected_end()
        retained, stalled = self.journal()["collected"], self.journal()["incident"]
        s = self.engine.station.supervisor
        router, advance = s.control, s._advance

        class Conflicting:
            def __getattr__(self, name):
                if name == "reconcile":
                    return lambda request: {"status": "refused", "reason": "reconciliation_conflict", "detail": "fixture: recorded otherwise"}
                return getattr(router, name)

        def advanced_then_cut(*args):
            advance(*args)
            raise RuntimeError("cut after the advance")
        s.control = Conflicting()
        try:
            with mock.patch.object(s, "_advance", side_effect=advanced_then_cut):
                self.assertEqual(self.command("recover_incident", self.request())[0], 500)
        finally:
            s.control = router
        second = self.journal().get("incident") or {}
        self.assertEqual((second.get("kind"), second.get("write"), at(self.journal(), "recovering", "incident"), self.held()),
                         ("lifecycle_write_refused", "reconcile", stalled, self.UNRECONCILED))
        listed = [(i["since"], "recovery" in i) for i in self.status_doc()["incidents"] if i["invocation_id"] == MAIN]
        self.assertEqual(listed, [(stalled["since"], True), (second["since"], False)])
        code, reply = self.command("recover_incident", self.request(incident_since=second["since"]))
        self.assertEqual((code, reply.get("status"), reply.get("outcome"), reply.get("incident")), (200, "resumed", "failed", second))
        self.reconciled(retained)
        journal = self.journal()
        self.assertEqual([(r["incident"]["since"], r.get("outcome")) for r in journal.get("recoveries", [])], [(stalled["since"], "stalled"), (second["since"], "failed")])
        self.assertEqual(("recovering" in journal, at(journal, "budgets", "recovery")), (False, 2))
        self.assertEqual(self.command("recover_incident", self.request(incident_since=stalled["since"]))[1].get("outcome"), "stalled")  # the first, replayed


class ReplacedRecovery(of.EngineProcesses, RecoveryWorld):
    """The operator's recovery cut short by a real process exit, and carried
    on by a replacement engine (Astra 1e-repair re-review finding 1, its
    reproduction). The stalled job is made in this process as RecoveryFaults
    makes it; then the engine serving it is a process of its own
    (recovery_child: the fixture policy and launcher, and a fault hook that
    ends the process with os._exit(137) at one point of the recovery). The
    operator's recovery is sent to it and gets no answer; an unmodified
    `python -m gen2.app.engine` over the same state takes its place. From the
    cut until the recovery is finished, status lists it, unfinished, as its
    incident. The same request to the replacement carries it on: the episode
    reconciled once, from fresh evidence, the old evidence kept, the hold
    cleared and capacity released by that reconciliation alone, no second
    allowance drawn — and only then answers resumed; the request again
    replays that. Read-backs are raw SQL and the journal on disk."""
    CUT_CLOCK = "2026-09-27T12:30:00Z"  # the cut engine's clock, after this test's (the replacement's is the real one)

    def listener(self) -> tuple[str, int]:
        return self.address

    def serving(self, url: str | None) -> None:
        """This test's requests go to the engine process at `url` from now on."""
        self.assertIsNotNone(url, "the engine printed no address")
        host, _, port = url.removeprefix("http://").rpartition(":")
        self.address = (host, int(port))

    def cut_and_replaced(self, point: str, reconciled_at_the_cut: bool) -> None:
        identity = self.stall_on_the_collected_end()
        retained, stalled = self.journal()["collected"], self.journal()["incident"]
        request = self.request()
        self.replaced_launchers = [*self.engine.station.supervisor._children.values()]
        self.engine.close()
        self.engine = None
        cut, url = self.spawn(["-m", "gen2.tests.recovery_child", str(self.root), point, self.CUT_CLOCK])
        self.serving(url)
        with self.assertRaises((http.client.HTTPException, ConnectionError)):  # no answer: the process ended mid-request
            self.command("recover_incident", request)
        self.assertEqual(cut.wait(timeout=60), 137)
        self.stop(cut)
        # the cut: the recovery recorded unfinished on its one allowance, whatever of its work was done
        journal = self.journal()
        self.assertEqual((at(journal, "recovering", "incident"), at(journal, "budgets", "recovery"), journal.get("recoveries", [])), (stalled, 1, []))
        if point == "recovery_recorded":  # before the group was ended: the incident open, the group alive
            self.assertEqual((journal.get("incident"), at(journal, "collected", "rehandled")), (stalled, None))
            self.assertNotEqual(jobs.members(identity), [])
        else:
            self.assertEqual((journal.get("incident"), at(journal, "collected", "rehandled", "descendants", "handling")), (None, "terminated"))
            self.assertEqual(jobs.members(identity), [])
        if reconciled_at_the_cut:
            self.assertEqual({k: self.held()[k] for k in ("state", "open_holds", "reconciliations")}, {"state": "failed", "open_holds": 0, "reconciliations": 1})
        else:
            self.assertEqual(self.held(), self.UNRECONCILED)

        replacement, url = self.spawn()
        self.serving(url)
        self.unfinished(stalled)  # listed engine-wide; and where the waiting item is:
        topic = self.topic_status()
        on_invocation = [w["incident"] for i in topic["invocations"] if i["invocation_id"] == MAIN for w in i["waiting"] if w["reason"] == "incident"]
        on_topic = [w["incident"] for w in topic["waiting"] if w["reason"] == "incident"]
        self.assertEqual([(i["since"], at(i, "recovery", "status")) for i in (on_topic if reconciled_at_the_cut else on_invocation)], [(stalled["since"], "unfinished")])
        code, reply = self.command("recover_incident", request)
        self.assertEqual((code, reply.get("status"), reply.get("outcome"), reply.get("incident"), reply.get("requested_by"), at(reply, "termination", "descendants", "handling")),
                         (200, "resumed", "failed", stalled, "alice", "terminated"))
        self.assertEqual(jobs.members(identity), [])
        self.reconciled(retained)
        journal = self.journal()
        self.assertEqual(("recovering" in journal, at(journal, "budgets", "recovery"), [r.get("outcome") for r in journal.get("recoveries", [])], journal.get("settled")),
                         (False, 1, ["failed"], "failed"))
        after = self.state(exclude=())
        self.assertEqual(self.command("recover_incident", request), (200, {**reply, "status": "replayed"}))
        self.assertEqual((self.state(exclude=()), [i for i in self.status_doc()["incidents"] if i["invocation_id"] == MAIN]), (after, []))
        self.stop(replacement)
        self.assert_collected(2, "listening on ")
        self.assert_no_token_in_any_output()

    def test_cut_after_the_recovery_is_recorded_before_the_group_is_ended(self) -> None:
        self.cut_and_replaced("recovery_recorded", reconciled_at_the_cut=False)

    def test_cut_after_the_incident_is_closed_before_the_reconciliation(self) -> None:
        """The review's reproduction: the process ends as the job is about
        to be advanced — the group ended, the incident closed, nothing
        reconciled."""
        self.cut_and_replaced("recovery_closed", reconciled_at_the_cut=False)

    def test_cut_after_the_router_reconciled_before_the_journal_says_so(self) -> None:
        self.cut_and_replaced("reconcile_replied", reconciled_at_the_cut=True)

    def test_cut_after_the_advance_before_the_recovery_is_recorded_finished(self) -> None:
        """The work done, the job settled; the process ends before the
        recovery is recorded finished and its reply sent."""
        self.cut_and_replaced("recovery_advanced", reconciled_at_the_cut=True)


class ResearchPassReplacedRecoveryTest(ReplacedRecovery, of.OperatorTestCase):
    KIND = "research_pass"


class DelegateReplacedRecoveryTest(ReplacedRecovery, of.OperatorTestCase):
    KIND = "delegate"


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
