"""The router's side of the lifecycle ends the supervisor records (task 1c):
failure, cancellation, outcome_unknown and its reconciliation, and status.

Trace: INVARIANTS L-1, L-4, L-5, L-7, L-9, C-9, C-10, H-3, RG-3; BOUNDARIES.md
Station supervisor, Router; design review §5 ("Crash fencing", "Router
outage"), §6; gen2/router/lifecycle.py.

Each refusal is shown on its own, with every table read back unchanged
(audit included unless the operation audits its refusals), beside the same
request minus the one defect accepted. Oracles: expected outcomes written
by hand; raw SQL read-back on the test's own connection; evidence documents
are built here from execution-record/1, not by the supervisor.

What these cannot show: that the supervisor observes truthfully (its own
suites run real processes), or anything about concurrency beyond the
schedules named.
"""
from __future__ import annotations

from gen2.core import canonical
from gen2.tests.router_fixtures import TOPIC, RouterTestCase, empty_outcome, h, jcs

IDENTITY = {"host_id": "host-1", "boot_id": "boot-1", "start_fingerprint": "ticks=1"}


class LifecycleTestCase(RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.grant = self.started("inv_research01")

    def transition(self, to_state: str, grant: dict | None = None, **facts) -> dict:
        grant = grant or self.grant
        return self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "to_state": to_state, **facts})

    def unknown(self, episode: int = 1, grant: dict | None = None, cause: str = "contact_lost") -> dict:
        return self.transition("outcome_unknown", grant, unknown_episode=episode, unknown_cause=cause)

    def reconcile(self, resolution: str, evidence: str, episode: int = 1, grant: dict | None = None, **extra) -> dict:
        grant = grant or self.grant
        method = "execution_group_termination" if resolution == "terminated_group" else "job_handle_lookup"
        return self.router.reconcile({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "unknown_episode": episode,
                                      "resolution": resolution, "method": extra.pop("method", method), "evidence_ref": evidence, **extra})

    def lookup(self, grant: dict | None = None, **overrides) -> str:
        """A job-handle lookup's record of a live process with the fixture's identity."""
        facts = {"method": "job_handle_lookup", "exit": None, **overrides}
        return self.evidence(grant or self.grant, facts.pop("findings", ()), **facts)

    def refused(self, response: dict, reason: str, before: dict, detail: str = "") -> None:
        self.assertEqual((response.get("status"), response.get("reason")), ("refused", reason), response)
        self.assertIn(detail, response.get("detail", ""))
        self.assertEqual(self.state(exclude=()), before)

    def lease_row(self) -> tuple:
        return self.rows("SELECT released_at IS NOT NULL, release_reason FROM leases WHERE lease_id = ?", self.grant["lease"]["lease_id"])[0]

    def inv(self, *columns: str, iid: str = "inv_research01") -> tuple:
        return self.rows(f"SELECT {', '.join(columns)} FROM invocations WHERE invocation_id = ?", iid)[0]


class FailureTest(LifecycleTestCase):
    def test_a_failure_records_its_class_and_evidence_and_releases_capacity(self) -> None:
        evidence = self.evidence(self.grant, ("empty_output",))
        revision = self.state_revision()
        self.assertEqual(self.transition("failed", failure_class="empty_output", end_evidence_ref=evidence)["status"], "recorded")
        self.assertEqual(self.inv("state", "failure_class", "end_evidence_ref"), ("failed", "empty_output", evidence))
        self.assertEqual(self.lease_row(), (1, "failed"))
        self.assertEqual((self.status(), self.state_revision()), ("queued", revision + 1))
        self.assertEqual(self.rows("SELECT media_type, topic_id, staged_by_invocation_id FROM artifacts WHERE content_hash = ?", evidence),
                         [("application/json", TOPIC, "inv_research01")])
        before = self.state(exclude=())
        self.assertEqual(self.transition("failed", failure_class="empty_output", end_evidence_ref=evidence)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        self.refused(self.transition("failed", failure_class="timeout", end_evidence_ref=evidence), "transition_conflict", before)

    def test_a_failure_without_its_record_is_refused(self) -> None:
        before = self.state(exclude=())
        self.refused(self.transition("failed"), "request_invalid", before)
        self.refused(self.transition("failed", failure_class="exit_nonzero"), "request_invalid", before)
        self.refused(self.transition("failed", failure_class="agent_gave_up", end_evidence_ref=self.evidence(self.grant)), "request_invalid", before)

    def test_the_evidence_must_be_this_jobs_record_and_support_the_class(self) -> None:
        other = self.started("inv_verify001", "verification")
        cases = {
            "not staged": (h("9"), "payload_missing", "nothing is staged"),
            "staged as text": (self.spool.put(jcs({"x": 1}), media_type="text/plain"), "payload_invalid", "not application/json"),
            "not a record": (self.evidence(self.grant, ("exit_nonzero", "agent_gave_up")), "evidence_refused", "execution-record"),
            "another invocation's": (self.evidence(other, job_handle="job-inv_research01"), "evidence_refused", "inv_verify001"),
            "another job's": (self.evidence(self.grant, job_handle="job-elsewhere"), "evidence_refused", "job-elsewhere"),
            "another finding": (self.evidence(self.grant, ("timeout",)), "evidence_refused", "not among"),
            "descendants unconfirmed": (self.evidence(self.grant, handling="unconfirmed"), "evidence_refused", "L-7"),
        }
        before = self.state(exclude=())
        for name, (evidence, reason, detail) in cases.items():
            with self.subTest(name):
                self.refused(self.transition("failed", failure_class="exit_nonzero", end_evidence_ref=evidence), reason, before, detail)
        self.assertEqual(self.lease_row(), (0, None))
        self.assertEqual(self.transition("failed", failure_class="exit_nonzero", end_evidence_ref=self.evidence(self.grant))["status"], "recorded")

    def test_a_delegate_failure_releases_nothing(self) -> None:
        delegate = self.started("inv_deleg001", "delegate", parent=self.grant)
        self.assertEqual(self.transition("failed", delegate, failure_class="exit_nonzero", end_evidence_ref=self.evidence(delegate))["status"], "recorded")
        self.assertEqual(self.lease_row(), (0, None))  # the parent's lease


class CancellationTest(LifecycleTestCase):
    def cancel(self, by: str = "operator", grant: dict | None = None, **extra) -> dict:
        grant = grant or self.grant
        return self.router.request_cancel({"invocation_id": grant["invocation_id"], "requested_by": by, "reason": "stop", **extra})

    def test_work_never_launched_is_cancelled_at_once(self) -> None:
        pending = self.claim("inv_checkpt01", "checkpoint")
        out = self.cancel(grant=pending)
        self.assertEqual((out["status"], out["state"]), ("cancelled", "cancelled"))
        self.assertEqual(self.inv("state", "cancel_requested_by", "descendants_confirmed_at IS NOT NULL", "end_evidence_ref", iid="inv_checkpt01"),
                         ("cancelled", "operator", 1, None))
        self.assertEqual(self.rows("SELECT release_reason FROM leases WHERE lease_id = ?", pending["lease"]["lease_id"]), [("cancelled",)])
        self.assertEqual(self.rows("SELECT from_state, to_state, cause FROM invocation_transitions WHERE invocation_id = 'inv_checkpt01' ORDER BY seq"),
                         [(None, "admitted", "claim"), ("admitted", "cancelled", "cancelled_before_launch")])
        before = self.state(exclude=())
        self.assertEqual(self.cancel(grant=pending)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        self.refused(self.cancel("router", grant=pending), "cancel_conflict", before)

    def test_launched_work_is_cancelled_by_the_supervisor_with_confirmed_descendants(self) -> None:
        before = self.state(exclude=())
        self.refused(self.transition("cancelled", end_evidence_ref=self.evidence(self.grant, ())), "transition_not_allowed", before, "no cancellation")
        out = self.cancel()
        self.assertEqual((out["status"], out["state"]), ("recorded", "running"))
        self.assertEqual(self.lease_row(), (0, None))  # capacity is held until the descendants are confirmed (L-7)
        termination = {"method": "execution_group_termination", "termination": {"reason": "cancellation"}, "exit": {"code": None, "signal": 15}}
        before = self.state(exclude=())
        self.refused(self.transition("cancelled", end_evidence_ref=self.evidence(self.grant, (), handling="unconfirmed", **termination)), "evidence_refused", before, "L-7")
        self.refused(self.transition("cancelled"), "request_invalid", before)
        self.assertEqual(self.transition("cancelled", end_evidence_ref=self.evidence(self.grant, (), handling="terminated", **termination))["status"], "recorded")
        self.assertEqual(self.inv("state", "descendants_confirmed_at IS NOT NULL"), ("cancelled", 1))
        self.assertEqual(self.lease_row(), (1, "cancelled"))

    def test_once_requested_no_result_observation_or_commit_is_accepted(self) -> None:
        env = self.envelope(self.grant, "op_interim0001", empty_outcome("inv_research01", "interim_transition"))
        self.assertEqual(self.cancel()["status"], "recorded")
        before = self.state()
        response = self.router.commit_outcome(env)
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "invocation_state_invalid"))
        self.assertIn("cancellation", response.get("detail", ""))
        self.assertEqual(self.state(), before)
        digest, _ = self.stage(empty_outcome("inv_research01"))
        before = self.state(exclude=())
        self.refused(self.transition("result_ready", result_payload_digest=digest), "cancel_requested", before)
        self.assertIsNotNone(self.spool.read(digest, topic_id=TOPIC))  # the result stays retained (C-10)
        request = {"lane": "crossref", "query": "q", "cursor": None}
        observation = {"observation_id": "obs_000000000001", "request": request, "request_identity": canonical.logical_hash(request), "attempt": 1,
                       "lane": "crossref", "obligation_ids": [], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:05Z",
                       "coverage_state": "searched_empty", "result_count": 0, "completeness": "complete", "error_class": None, "capability_fact_id": None,
                       "policy_version": "gw-policy/1", "cost_units": None, "gateway_call_ref": "call-1"}
        response = self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": "inv_research01",
                                                   "observation": observation, "retrieval_events": []})
        self.refused(response, "invocation_state_invalid", before, "cancellation")

    def test_a_staged_result_wins_the_race(self) -> None:
        digest, _ = self.stage(empty_outcome("inv_research01"))
        self.ready(self.grant, digest)
        before = self.state(exclude=())
        self.refused(self.cancel(), "not_cancellable", before, "result_ready")
        env = self.envelope(self.grant, "op_final000001", empty_outcome("inv_research01"))
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")
        self.refused(self.cancel(), "not_cancellable", self.state(exclude=()), "committed")

    def test_the_supervisor_asks_under_the_invocations_capability(self) -> None:
        other = self.claim("inv_verify001", "verification")
        before = self.state(exclude=())
        self.refused(self.cancel("supervisor"), "request_invalid", before)
        self.refused(self.cancel("operator", capability_id=self.grant["capability_id"]), "request_invalid", before)
        self.refused(self.cancel("supervisor", capability_id=other["capability_id"]), "capability_invocation_mismatch", before)
        self.refused(self.router.request_cancel({"invocation_id": "inv_nobody001", "requested_by": "operator", "reason": "stop"}), "unknown_invocation", before)
        self.assertEqual(self.cancel("supervisor", capability_id=self.grant["capability_id"])["status"], "recorded")
        self.assertEqual(self.inv("cancel_requested_by"), ("supervisor",))

    def test_launch_after_a_cancellation_request_is_refused(self) -> None:
        pending = self.claim("inv_checkpt01", "checkpoint")
        self.x("UPDATE invocations SET cancel_requested_at = ?, cancel_requested_by = 'router' WHERE invocation_id = 'inv_checkpt01'", "2026-09-27T10:00:00Z")
        before = self.state(exclude=())
        self.refused(self.transition("launching", pending, job_handle="job-inv_checkpt01"), "cancel_requested", before)


class UnknownTest(LifecycleTestCase):
    def test_entering_outcome_unknown_opens_an_owned_deadlined_hold(self) -> None:
        self.assertEqual(self.unknown()["status"], "recorded")
        self.assertEqual(self.inv("state", "unknown_episode", "outcome_unknown_since IS NOT NULL"), ("outcome_unknown", 1, 1))
        hold = self.rows("SELECT hold_class, recoverability, required_authority, owner, subject_ref, cleared_at, created_at, deadline_at FROM holds")
        self.assertEqual(len(hold), 1)
        self.assertEqual(hold[0][:6], ("unknown", "unknown", "router", "supervisor:station-1", "invocation:inv_research01#unknown:1", None))
        self.assertGreater(hold[0][7], hold[0][6])  # a deadline after its creation (same format: text order is time order here)
        before = self.state(exclude=())
        self.assertEqual(self.unknown()["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        self.refused(self.unknown(3), "transition_conflict", before, "the next is 2")
        self.refused(self.transition("outcome_unknown", unknown_episode=2), "request_invalid", before)

    def test_found_running_records_the_identity_and_clears_the_hold(self) -> None:
        pending = self.claim("inv_checkpt01", "checkpoint")
        self.assertEqual(self.transition("launching", pending, job_handle="job-inv_checkpt01")["status"], "recorded")
        self.assertEqual(self.unknown(grant=pending, cause="spawn_uncertain")["status"], "recorded")
        evidence = self.lookup(pending)
        self.assertEqual(self.reconcile("found_running", evidence, grant=pending, **IDENTITY)["status"], "recorded")
        self.assertEqual(self.inv("state", "host_id", "boot_id", "start_fingerprint", iid="inv_checkpt01"), ("running", "host-1", "boot-1", "ticks=1"))
        rec = self.rows("SELECT reconciliation_id, resolution, method, evidence_ref, descendants_confirmed_at FROM invocation_reconciliations")
        self.assertEqual(rec[0][1:], ("found_running", "job_handle_lookup", evidence, None))
        self.assertEqual(self.rows("SELECT cleared_by_reconciliation_id FROM holds"), [(rec[0][0],)])
        before = self.state(exclude=())
        self.assertEqual(self.reconcile("found_running", evidence, grant=pending, **IDENTITY)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        self.refused(self.reconcile("found_running", self.lookup(pending, observed_at="2026-09-27T10:21:00Z"), grant=pending, **IDENTITY),
                     "reconciliation_conflict", before)

    def test_found_result_needs_the_staged_result_of_a_clean_exit(self) -> None:
        self.unknown()
        digest, size = self.stage(empty_outcome("inv_research01"))
        found = {"status": "present", "content_hash": digest, "size_bytes": size, "declared_digest": None, "detail": None}
        clean = dict(method="job_handle_lookup", exit={"code": 0, "signal": None}, output=found)
        cases = {
            "another digest": (self.evidence(self.grant, (), **{**clean, "output": {**found, "content_hash": h("5")}}), "evidence_refused"),
            "an exit code": (self.evidence(self.grant, (), **{**clean, "exit": {"code": 3, "signal": None}}), "evidence_refused"),
            "a finding": (self.evidence(self.grant, ("output_digest_mismatch",), **clean), "evidence_refused"),
            "another method": (self.evidence(self.grant, (), **{**clean, "method": "exit_observed"}), "evidence_refused"),
        }
        before = self.state(exclude=())
        for name, (evidence, reason) in cases.items():
            with self.subTest(name):
                self.refused(self.reconcile("found_result", evidence, result_payload_digest=digest), reason, before)
        self.refused(self.reconcile("found_result", self.evidence(self.grant, (), **clean), result_payload_digest=h("4")), "payload_missing", before)
        self.assertEqual(self.reconcile("found_result", self.evidence(self.grant, (), **clean), result_payload_digest=digest)["status"], "recorded")
        self.assertEqual(self.inv("state", "result_payload_digest"), ("result_ready", digest))
        before = self.state(exclude=())  # a state reached by reconciliation is not recorded again as a new fact
        self.refused(self.transition("result_ready", result_payload_digest=digest), "transition_not_allowed", before, "already result_ready")
        env = self.envelope(self.grant, "op_final000001", empty_outcome("inv_research01"))
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")

    def test_a_terminal_resolution_needs_confirmed_descendants_and_a_finding(self) -> None:
        self.unknown()
        before = self.state(exclude=())
        self.refused(self.reconcile("confirmed_failed", self.lookup(findings=["no_exit_record"], handling="unconfirmed"), failure_class="no_exit_record"),
                     "evidence_refused", before, "L-7")
        self.refused(self.reconcile("confirmed_failed", self.lookup(findings=["killed"]), failure_class="no_exit_record"), "evidence_refused", before, "not among")
        self.refused(self.reconcile("confirmed_failed", self.lookup(findings=["no_exit_record"])), "request_invalid", before)
        out = self.reconcile("confirmed_failed", self.lookup(findings=["no_exit_record"]), failure_class="no_exit_record")
        self.assertEqual((out["status"], out["state"]), ("recorded", "failed"))
        self.assertEqual(self.inv("state", "failure_class"), ("failed", "no_exit_record"))
        self.assertEqual(self.lease_row(), (1, "failed"))
        self.assertEqual(self.rows("SELECT descendants_confirmed_at IS NOT NULL FROM invocation_reconciliations"), [(1,)])
        self.assertEqual(self.rows("SELECT cleared_at IS NOT NULL FROM holds"), [(1,)])

    def test_termination_ends_cancelled_only_when_cancellation_was_requested(self) -> None:
        """A terminated group ends failed with its failure class, or — when a
        cancellation was requested — cancelled, with none: no failure class is
        invented for a cancellation (Astra 1c review A2; Q5 ruling). The
        requests are the supervisor's own shapes (Supervisor._unknown): a
        timeout's termination with its finding; a cancellation's with no
        finding. Each mismatch is refused on its own, the store unchanged."""
        timeout = dict(method="execution_group_termination", termination={"reason": "timeout"}, exit=None, handling="terminated")
        cancelled = dict(method="execution_group_termination", termination={"reason": "cancellation"}, exit=None, handling="terminated")
        for requested, target in ((False, "failed"), (True, "cancelled")):
            with self.subTest(requested=requested):
                self.tearDown()
                self.setUp()
                self.unknown()
                if requested:
                    self.router.request_cancel({"invocation_id": "inv_research01", "requested_by": "operator", "reason": "stop"})
                before = self.state(exclude=())
                self.refused(self.reconcile("terminated_group", self.evidence(self.grant, ("timeout",), **{**timeout, "termination": None}), failure_class="timeout"),
                             "evidence_refused", before)  # the schema's rule: a group termination records why
                if requested:
                    self.refused(self.reconcile("terminated_group", self.evidence(self.grant, ("timeout",), **timeout), failure_class="timeout"),
                                 "cancel_requested", before, "no failure class")
                    out = self.reconcile("terminated_group", self.evidence(self.grant, (), **cancelled))
                else:
                    self.refused(self.reconcile("terminated_group", self.evidence(self.grant, (), **cancelled)), "request_invalid", before, "no cancellation")
                    out = self.reconcile("terminated_group", self.evidence(self.grant, ("timeout",), **timeout), failure_class="timeout")
                self.assertEqual((out["status"], out["state"]), ("recorded", target))
                self.assertEqual(self.inv("state", "failure_class"), (target, "timeout" if target == "failed" else None))
                self.assertEqual(self.lease_row(), (1, target))

    def test_an_episode_is_reconciled_only_by_its_own_record(self) -> None:
        self.unknown()
        first = self.lookup()
        self.assertEqual(self.reconcile("found_running", first, **IDENTITY)["status"], "recorded")
        self.assertEqual(self.unknown(2)["status"], "recorded")
        before = self.state(exclude=())
        self.assertEqual(self.unknown(1)["status"], "replayed")  # an episode entered earlier replays; it is not entered again
        self.assertEqual(self.reconcile("found_running", first, **IDENTITY)["status"], "replayed")  # episode 1's record answers for episode 1 only
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.inv("state", "unknown_episode"), ("outcome_unknown", 2))
        self.refused(self.reconcile("found_running", self.lookup(observed_at="2026-09-27T10:40:00Z"), 3, **IDENTITY), "transition_not_allowed", before, "episode 2")
        self.assertEqual(self.reconcile("found_running", self.lookup(observed_at="2026-09-27T10:40:00Z"), 2, **IDENTITY)["status"], "recorded")
        self.assertEqual(self.rows("SELECT unknown_episode, cleared_at IS NOT NULL FROM invocation_reconciliations r JOIN holds ON holds.cleared_by_reconciliation_id = r.reconciliation_id "
                                   "ORDER BY unknown_episode"), [(1, 1), (2, 1)])

    def test_found_running_needs_a_live_process_of_this_identity(self) -> None:
        self.unknown()
        before = self.state(exclude=())
        self.refused(self.reconcile("found_running", self.lookup(exit={"code": 0, "signal": None}), **IDENTITY), "evidence_refused", before, "live process")
        self.refused(self.reconcile("found_running", self.lookup(), **{**IDENTITY, "boot_id": "boot-2"}), "evidence_refused", before, "live process")
        self.refused(self.reconcile("found_running", self.lookup()), "request_invalid", before)
        self.assertEqual(self.reconcile("found_running", self.lookup(), **IDENTITY)["status"], "recorded")

    def test_a_result_found_after_a_cancellation_request_stays_retained(self) -> None:
        self.unknown()
        self.router.request_cancel({"invocation_id": "inv_research01", "requested_by": "operator", "reason": "stop"})
        digest, size = self.stage(empty_outcome("inv_research01"))
        found = {"status": "present", "content_hash": digest, "size_bytes": size, "declared_digest": None, "detail": None}
        before = self.state(exclude=())
        self.refused(self.reconcile("found_result", self.evidence(self.grant, (), method="job_handle_lookup", exit={"code": 0, "signal": None}, output=found),
                                    result_payload_digest=digest), "cancel_requested", before)


class StatusAndSpoolTest(LifecycleTestCase):
    def test_status_reads_the_invocation_under_its_capability(self) -> None:
        self.router.request_cancel({"invocation_id": "inv_research01", "requested_by": "operator", "reason": "stop"})
        before = self.state(exclude=())
        status = self.router.invocation_status({"capability_id": self.grant["capability_id"], "invocation_id": "inv_research01"})
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual((status["state"], status["cancel_requested"]["by"], status["unknown_episode"], status["job_handle"], status["topic_paused"],
                          status["state_revision"], status["lease"]["released_at"]), ("running", "operator", 0, "job-inv_research01", False, self.state_revision(), None))
        other = self.claim("inv_verify001", "verification")
        self.assertEqual(self.router.invocation_status({"capability_id": other["capability_id"], "invocation_id": "inv_research01"}).get("reason"),
                         "capability_invocation_mismatch")

    def test_status_reports_the_current_launch_admission_check(self) -> None:
        """Every actual start needs the launch-admission check as it stands
        now, not as it stood when launch intent was recorded (L-7; Astra 1c
        review A1). Status runs the same check the launching transition does,
        against the router's clock, writes nothing, and reports each withdrawn
        authority on its own; the unchanged invocation is admitted (None)."""
        pending = self.claim("inv_checkpt01", "checkpoint", lease_expires_at="2026-11-01T00:00:00Z", deadline_at="2026-10-15T00:00:00Z")
        self.assertEqual(self.transition("launching", pending, job_handle="job-inv_checkpt01")["status"], "recorded")

        def admission() -> str | None:
            before = self.state(exclude=())
            status = self.router.invocation_status({"capability_id": pending["capability_id"], "invocation_id": "inv_checkpt01"})
            self.assertEqual(self.state(exclude=()), before)
            return status["launch_admission"] and status["launch_admission"]["reason"]
        self.assertIsNone(admission())
        self.x("UPDATE queue_entries SET paused_at = '2026-09-27T10:00:00Z' WHERE topic_id = ?", TOPIC)
        self.assertEqual(admission(), "topic_paused")
        self.x("UPDATE queue_entries SET paused_at = NULL WHERE topic_id = ?", TOPIC)
        self.assertIsNone(admission())
        for moment, reason in (("2026-10-15T00:00:00Z", "deadline_passed"), ("2026-11-01T00:00:00Z", "lease_not_current"), ("2026-10-01T00:00:00Z", None)):
            with self.subTest(moment):
                self.clock.set(moment)
                self.assertEqual(admission(), reason)
        self.router.request_cancel({"invocation_id": "inv_checkpt01", "requested_by": "operator", "reason": "stop"})
        self.assertEqual(admission(), "cancel_requested")
        self.x("UPDATE leases SET released_at = '2026-10-01T00:00:00Z', release_reason = 'expired' WHERE lease_id = ?", pending["lease"]["lease_id"])
        self.assertEqual(admission(), "lease_released")

    def test_bytes_are_read_under_the_invocations_topic_with_the_spools_media_type(self) -> None:
        ref = {"content_hash": self.spool.put(b"a packet", media_type="text/plain"), "size_bytes": 8, "media_type": "text/html"}
        env = self.envelope(self.grant, "op_interim0001", empty_outcome("inv_research01", "interim_transition"), refs=[ref])
        before = self.state()
        response = self.router.commit_outcome(env)
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "payload_invalid"))
        self.assertIn("staged as text/plain", response.get("detail", ""))
        self.assertEqual(self.state(), before)
        env = self.envelope(self.grant, "op_interim0002", empty_outcome("inv_research01", "interim_transition"), refs=[{**ref, "media_type": "text/plain"}])
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")
        self.assertEqual(set(self.spool.read_topics), {TOPIC})
