"""Status answers why every waiting item waits (task 1e; INVARIANTS RG-9, H-4).

StatusWorld constructs, through the router (and raw SQL only where the
router has no path), one of each waiting state the task names: a brief
overdue, a scope approval, a contract draft, an open judgment hold, an
outcome_unknown episode with its hold (beside a hold already cleared), a
result awaiting its commit, work
fenced by an amendment (amendment_pending), a lane waiting for its re-queue,
one re-queued and not yet claimed, one held by its exhausted budget, a paused
topic's admitted work, work past its deadline and lease, pending signals, an
open review, an open reservation (beside one an amendment closed), the config bundles
active and pinned, a refused bundle's capability fact (after a failure and a
recovery before it), and the station's incidents — a real
retry_exhausted (the supervisor cancelling admitted work its paused topic
kept from launching) and a stalled job's collected-end incident. Status is
read over HTTP; each test states by hand which reason must name which item,
with the owner and deadline read back as raw SQL from the store, not from
the status under test.

The collected-end incident is written as the supervisor's journal holds it
(Supervisor._incident's record: kind outcome_unknown_unresolved, the last
finding naming the collected end): producing it for real needs a descendant
that survives its group, which the supervisor's own suite does. What status
does with an incident does not depend on its kind, and the retry_exhausted
one here is the supervisor's own.
"""
from __future__ import annotations

import json
import sys

from gen2.core import canonical
from gen2.supervisor import jobs
from gen2.supervisor.supervisor import Supervisor, WorkOrder
from gen2.tests import operator_fixtures as of
from gen2.tests import router_fixtures as rf
from gen2.tests.router_fixtures import OTHER, TOPIC, h

T3, T4, T5 = "fleet-a:t3", "fleet-a:t4", "fleet-a:t5"
POLICY_BUNDLE = {"bundle_version": "config-bundle/1", "version": 2, "questions": [rf.QUESTION],
                 "policy": {"router": {"retry": {"attempts": 0, "failure_classes": ["exit_nonzero"]}, "reservations": {"protected_exploration": {"units": 2}}}}}
POLICY = canonical.logical_hash(POLICY_BUNDLE)
LATER_BUNDLE = {**POLICY_BUNDLE, "version": 3}
COLLECTED_END = "the collected end's descendants are not confirmed ended"


class StatusWorld(of.OperatorTestCase):
    def setUp(self) -> None:
        super().setUp()
        from gen2.tests import test_router_amendments as amend  # the module, so its tests are not collected here
        self.amend = amend
        assert self.router.activate_config_bundle(POLICY_BUNDLE)["status"] == "activated"
        for tid in (T3, T4, T5):
            self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)",
                   tid, "2026-09-27T09:00:00Z", "2026-09-27T09:00:00Z")
        self.build_topic()
        self.build_other_topics()
        self.build_station()
        assert self.router.activate_config_bundle(LATER_BUNDLE)["status"] == "activated"  # the work above stays pinned to POLICY
        for version, policy, outcome in ((4, {"router": {"hold_window_s": 0}}, "refused"), (4, {}, "activated"), (5, {"router": {"hold_window_s": 0}}, "refused")):
            out = self.router.activate_config_bundle({**LATER_BUNDLE, "version": version, "policy": policy})
            assert out["status"] == outcome, out  # failing, recovered, failing again: three facts, the last one current
        self.clock.set("2026-09-27T11:00:00Z")  # the short deadline and lease below are over

    def store_draft(self, doc: dict) -> None:
        self.amend.ContractWorld.store_draft(self, doc)

    def claim(self, inv: str, kind: str = "research_pass", tid: str = TOPIC, **extra) -> dict:
        return super().claim(inv, kind, tid, **{"config_bundle_hash": POLICY, **extra})

    def build_topic(self) -> None:
        """TOPIC: an approved contract (revision 2), then work of every lane,
        a hold, an amendment fencing the research pass, a reservation, a
        draft, an open review and a pending signal."""
        self.amend.ContractWorld.build_world(self)
        self.fenced = self.started("inv_fenced00001")
        checkpoint = self.started("inv_ready000001", kind="checkpoint")
        self.hold(checkpoint, "hold_judgment01")
        self.hold(checkpoint, "hold_cleared001")
        assert self.decide("opd_clear0001", "hold_clearance", {"kind": "hold", "ref": "hold_cleared001"})["status"] == "applied"
        env = self.envelope(checkpoint, "op_ready0001", rf.empty_outcome(checkpoint["invocation_id"]))
        self.ready(checkpoint, env["payload_digest"])
        unknown = self.started("inv_unknown0001", kind="verification")
        out = self.router.record_transition({"capability_id": unknown["capability_id"], "invocation_id": unknown["invocation_id"],
                                             "to_state": "outcome_unknown", "unknown_episode": 1, "unknown_cause": "contact_lost"})
        assert out["status"] == "recorded", out
        self.ended(self.started("inv_requeued001", kind="discovery"))
        assert self.router.requeue({"invocation_id": "inv_requeued001", "requested_by": "operator", "reason": "diagnosed"})["status"] == "requeued"
        assert self.router.open_reservation({"reservation_id": "rsv_before00001", "topic_id": TOPIC, "purpose": "protected_exploration"})["status"] == "opened"
        changed = self.amend.contract_doc(3, 2, edit=self.amend.protocol_changed)
        assert self.router.propose_amendment({"document": changed})["status"] == "recorded"
        assert self.amend.ContractWorld.approve(self, changed)["status"] == "applied"  # fences the research pass pinned to revision 2
        assert self.router.open_reservation({"reservation_id": "rsv_explore0001", "topic_id": TOPIC, "purpose": "protected_exploration"})["status"] == "opened"
        draft = self.amend.contract_doc(4, 3, edit=lambda d: (self.amend.protocol_changed(d), self.amend.compatible(d)))
        assert self.router.propose_amendment({"document": draft})["status"] == "recorded"
        self.x("INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at) VALUES (?, ?, 'retraction', 'deterministic', 'doi:10.1/w', ?)",
               h("6"), TOPIC, "2026-09-27T10:00:00Z")
        assert self.router.open_review({"episode_id": "rev_cadence0001", "topic_id": TOPIC, "kind": "fixed_cadence"})["status"] == "opened"  # takes h("6")
        self.x("INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at) VALUES (?, ?, 'retraction', 'deterministic', 'doi:10.1/x', ?)",
               h("7"), TOPIC, "2026-09-27T10:00:00Z")

    def build_other_topics(self) -> None:
        """OTHER: a brief past its deadline, marked overdue. T3: awaiting scope
        approval. T4: queued, a failed research lane never re-queued, a failed
        discovery whose policy re-queue exhausted its budget, admitted
        verification work of a topic paused since, and a checkpoint whose
        deadline and lease pass."""
        self.late_brief(OTHER, "brief-1", "user")
        assert self.router.mark_brief_overdue({"topic_id": OTHER, "brief_id": "brief-1", "version": 1})["status"] == "marked"
        self.to_scoping(T3)
        self.x("UPDATE queue_entries SET status = 'awaiting_scope_approval', state_revision = state_revision + 1 WHERE topic_id = ?", T3)
        self.to_queued(T4)
        self.ended(self.started("inv_t4fail0001", tid=T4))
        self.ended(self.started("inv_t4disc0001", kind="discovery", tid=T4))
        assert self.router.requeue({"invocation_id": "inv_t4disc0001", "requested_by": "policy", "reason": "transient"})["status"] == "exhausted"
        assert self.claim("inv_t4admit001", kind="verification", tid=T4)["status"] == "granted"
        assert self.claim("inv_t4late0001", kind="checkpoint", tid=T4, deadline_at="2026-09-27T10:30:00Z", lease_expires_at="2026-09-27T10:30:00Z")["status"] == "granted"
        self.x("UPDATE queue_entries SET paused_at = '2026-09-27T10:00:00Z' WHERE topic_id = ?", T4)

    def build_station(self) -> None:
        """T5: the station's supervisor (the jobs directory the engine reads)
        claims a verification, the topic is paused, and the supervisor's
        launch budget runs out: it cancels the admitted work and records a
        retry_exhausted incident. And the collected-end incident of TOPIC's
        outcome_unknown verification (module docstring)."""
        self.to_queued(T5)

        class Stop(Exception):
            pass

        def stop(point: str) -> None:
            if point == "claimed":
                raise Stop(point)
        order = WorkOrder(invocation_id="inv_t5paused01", kind="verification", topic_id=T5, config_bundle_hash=POLICY, deadline_at=rf.DEADLINE,
                          lease_expires_at=rf.EXPIRES, command=(sys.executable, "-c", "pass"))
        supervisor = Supervisor(self.router, self.spool.real, self.root / "jobs", station_id="station-1", host_id="host-1", clock=self.clock, fault=stop)
        try:
            supervisor.submit(order)
        except Stop:
            pass
        self.x("UPDATE queue_entries SET paused_at = '2026-09-27T10:00:00Z' WHERE topic_id = ?", T5)
        supervisor._fault = lambda point: None
        outcomes = [supervisor.advance("inv_t5paused01") for _ in range(4)]
        assert outcomes[-1] == "cancelled", outcomes
        job = jobs.Job(self.root / "jobs", "job-inv_unknown0001")
        job.dir.mkdir(parents=True)
        job.write("order.json", {"invocation_id": "inv_unknown0001"})
        job.write("journal.json", {"incident": {"kind": "outcome_unknown_unresolved", "since": "2026-09-27T10:05:00Z", "owner": "supervisor:station-1",
                                                "deadline_at": "2026-09-27T11:05:00Z", "budget": "unknown", "unknown_episode": 1,
                                                "unresolved_since": "2026-09-27T10:04:00Z", "last_finding": COLLECTED_END}})

    # -- reading -----------------------------------------------------------------
    def invocation(self, doc: dict, inv: str) -> dict:
        return next(i for t in doc["topics"] for i in t["invocations"] if i["invocation_id"] == inv)

    @staticmethod
    def reasons(item: dict, reason: str) -> list[dict]:
        return [w for w in item["waiting"] if w["reason"] == reason]

    def one(self, item: dict, reason: str) -> dict:
        found = self.reasons(item, reason)
        self.assertEqual(len(found), 1, f"{reason} in {[w['reason'] for w in item['waiting']]}")
        return found[0]

    def hold_row(self, **where) -> dict:
        key, value = next(iter(where.items()))
        row = self.db.execute(f"SELECT hold_id, owner, deadline_at, required_authority, clears_when FROM holds WHERE {key} = ?", (value,)).fetchone()
        return dict(zip(("hold_id", "owner", "deadline_at", "required_authority", "clears_when"), row))


class TopicWaitingTest(StatusWorld):
    def test_each_topic_waits_for_what_its_status_says(self) -> None:
        doc = self.status_doc()
        expected = {TOPIC: None, OTHER: "brief_confirmation", T3: "scope_approval", T4: "claim", T5: "claim"}
        self.assertEqual(sorted(t["topic_id"] for t in doc["topics"]), sorted(expected))
        for topic in doc["topics"]:
            with self.subTest(topic=topic["topic_id"]):
                own = [w["reason"] for w in topic["waiting"] if w.get("status") == topic["status"]]
                self.assertEqual(own, [] if expected[topic["topic_id"]] is None else [expected[topic["topic_id"]]])

    def test_an_overdue_brief_names_its_owner_and_deadline(self) -> None:
        found = self.one(self.topic_status(OTHER), "brief_awaiting_confirmation")
        overdue = self.value("SELECT overdue_since FROM intake_briefs WHERE topic_id = ?", OTHER)
        self.assertEqual({k: found[k] for k in ("brief_id", "version", "owner", "review_deadline", "overdue_since", "deadline_passed")},
                         {"brief_id": "brief-1", "version": 1, "owner": "user", "review_deadline": "2026-09-27T09:30:00Z", "overdue_since": overdue,
                          "deadline_passed": True})
        self.assertIsNotNone(overdue)

    def test_an_open_hold_names_its_owner_deadline_authority_and_what_clears_it(self) -> None:
        holds = self.reasons(self.topic_status(), "hold")
        self.assertEqual(sorted(w["hold_id"] for w in holds), [r[0] for r in self.rows("SELECT hold_id FROM holds WHERE topic_id = ? AND cleared_at IS NULL ORDER BY 1", TOPIC)])
        found = next(w for w in holds if w["hold_id"] == "hold_judgment01")
        self.assertEqual({k: found[k] for k in ("hold_id", "owner", "deadline_at", "required_authority", "clears_when")},
                         self.hold_row(hold_id="hold_judgment01"))
        self.assertEqual((found["hold_class"], found["deadline_passed"]), ("judgment", False))

    def test_a_draft_that_can_still_be_approved_waits_and_an_older_one_does_not(self) -> None:
        """Revision 4 revises the approved revision 3; revision 1, the unapproved
        rating draft, can never be approved now."""
        drafts = self.reasons(self.topic_status(), "draft_awaiting_approval")
        self.assertEqual([(d["revision"], d["parent_revision"]) for d in drafts], [(4, 3)])
        self.assertEqual(self.rows("SELECT revision FROM contract_revisions WHERE topic_id = ? AND status = 'draft' ORDER BY revision", TOPIC), [(1,), (4,)])

    def test_each_lane_waits_where_its_requeue_stands(self) -> None:
        requeue = self.one(self.topic_status(T4), "requeue")
        self.assertEqual((requeue["scope"], requeue["last_invocation_id"], requeue["failure_class"]), ("research", "inv_t4fail0001", "exit_nonzero"))
        held = self.one(self.topic_status(T4), "requeue_hold")
        self.assertEqual((held["scope"], held["last_invocation_id"]), ("discovery", "inv_t4disc0001"))
        self.assertEqual(held["requeue_hold"], {k: v for k, v in self.hold_row(subject_ref="invocation:inv_t4disc0001#requeue").items() if k != "required_authority"})
        claim = self.one(self.topic_status(), "retry_claim")
        self.assertEqual((claim["scope"], claim["requeue"]), ("discovery", {"attempt": 2, "requested_by": "operator", "claimed_by": None}))

    def test_a_paused_topic_and_its_admitted_work_say_so(self) -> None:
        topic = self.topic_status(T4)
        self.assertEqual(self.one(topic, "paused")["since"], "2026-09-27T10:00:00Z")
        admitted = self.invocation(self.status_doc(), "inv_t4admit001")
        self.assertEqual(self.one(admitted, "launch_refused")["refusal"], {"reason": "topic_paused", "detail": "paused at 2026-09-27T10:00:00Z"})
        self.assertEqual(self.one(admitted, "launch")["state"], "admitted")

    def test_signals_and_an_open_review_are_listed(self) -> None:
        topic = self.topic_status()
        self.assertEqual([(s["trigger_identity"], s["reason_code"]) for s in self.one(topic, "signals")["pending"]], [(h("7"), "retraction")])
        self.assertEqual(self.value("SELECT episode_id FROM review_triggers WHERE trigger_identity = ?", h("6")), "rev_cadence0001")
        self.assertEqual({k: v for k, v in self.one(topic, "review").items() if k != "opened_at"}, {"reason": "review", "episode_id": "rev_cadence0001", "kind": "fixed_cadence"})

    def test_the_open_reservation_stands_with_its_units(self) -> None:
        self.assertEqual(self.rows("SELECT reservation_id, closed_at IS NOT NULL FROM reservations ORDER BY 1"), [("rsv_before00001", 1), ("rsv_explore0001", 0)])
        reservations = self.topic_status()["reservations"]
        self.assertEqual([{k: r[k] for k in ("reservation_id", "purpose", "contract_revision", "units", "drawn")} for r in reservations],
                         [{"reservation_id": "rsv_explore0001", "purpose": "protected_exploration", "contract_revision": 3, "units": 2, "drawn": 0}])


class InvocationWaitingTest(StatusWorld):
    def test_every_live_invocation_waits_for_the_next_step_of_its_state(self) -> None:
        doc = self.status_doc()
        expected = {"inv_fenced00001": "end", "inv_ready000001": "commit", "inv_unknown0001": "reconciliation", "inv_t4admit001": "launch",
                    "inv_t4late0001": "launch"}
        live = {i["invocation_id"]: i for t in doc["topics"] for i in t["invocations"]}
        self.assertEqual(sorted(live), sorted(expected))
        live_rows = self.rows("SELECT invocation_id FROM invocations WHERE state IN ('admitted', 'launching', 'running', 'result_ready', 'outcome_unknown') ORDER BY 1")
        self.assertEqual([r[0] for r in live_rows], sorted(expected))
        for inv, reason in expected.items():
            with self.subTest(invocation=inv):
                self.assertEqual(live[inv]["waiting"][0]["reason"], reason)

    def test_an_outcome_unknown_episode_waits_for_its_reconciliation_under_its_hold(self) -> None:
        found = self.one(self.invocation(self.status_doc(), "inv_unknown0001"), "reconciliation")
        row = self.hold_row(subject_ref="invocation:inv_unknown0001#unknown:1")
        self.assertEqual((found["episode"], found["hold"]), (1, {k: row[k] for k in ("hold_id", "owner", "deadline_at", "clears_when")}))
        self.assertEqual(row["owner"], "supervisor:station-1")
        self.assertEqual(found["since"], self.value("SELECT outcome_unknown_since FROM invocations WHERE invocation_id = 'inv_unknown0001'"))

    def test_fenced_work_is_amendment_pending_naming_what_superseded_its_pin(self) -> None:
        inv = self.invocation(self.status_doc(), "inv_fenced00001")
        found = self.one(inv, "amendment_pending")
        decision = self.value("SELECT approved_by_decision_id FROM contract_revisions WHERE topic_id = ? AND revision = 3", TOPIC)
        self.assertEqual((found["standing"], found["superseded_by"], found["admission"]["contract"]["revision"]),
                         ("protocol_changed", {"contract_revision": 3, "approved_by_decision_id": decision}, 2))
        self.assertEqual(self.one(inv, "cancellation")["by"], "router")

    def test_work_past_its_deadline_and_lease_says_so(self) -> None:
        inv = self.invocation(self.status_doc(), "inv_t4late0001")
        self.assertEqual(self.one(inv, "deadline_passed")["deadline_at"], "2026-09-27T10:30:00Z")
        self.assertEqual(self.one(inv, "lease_expired")["expires_at"], "2026-09-27T10:30:00Z")
        admitted = self.invocation(self.status_doc(), "inv_t4admit001")
        self.assertEqual(self.reasons(admitted, "deadline_passed") + self.reasons(admitted, "lease_expired"), [])

    def test_each_invocation_carries_its_lease_generation_and_pinned_bundle(self) -> None:
        doc = self.status_doc()
        for inv, lease_id, generation, bundle in self.rows(
                "SELECT i.invocation_id, l.lease_id, l.generation, i.config_bundle_hash FROM invocations i JOIN leases l ON l.lease_id = i.lease_id "
                "WHERE i.state IN ('admitted', 'launching', 'running', 'result_ready', 'outcome_unknown')"):
            with self.subTest(invocation=inv):
                found = self.invocation(doc, inv)
                self.assertEqual((found["lease"]["lease_id"], found["lease"]["generation"], found["config_bundle_hash"]), (lease_id, generation, bundle))


class EngineWideTest(StatusWorld):
    def test_the_active_and_the_pinned_bundles_are_named(self) -> None:
        bundles = self.status_doc()["config_bundles"]
        active = self.rows("SELECT bundle_hash, version FROM config_bundles WHERE status = 'active'")
        self.assertEqual((bundles["active"]["bundle_hash"], bundles["active"]["version"]), active[0])
        self.assertEqual(active[0][1], 4)
        pinned = {p["bundle_hash"]: p for p in bundles["pinned"]}
        self.assertEqual(sorted(pinned), [POLICY])
        self.assertEqual((pinned[POLICY]["status"], pinned[POLICY]["invocations"]),
                         ("superseded", ["inv_fenced00001", "inv_ready000001", "inv_t4admit001", "inv_t4late0001", "inv_unknown0001"]))

    def test_a_refused_bundle_is_a_dated_capability_fact(self) -> None:
        facts = [f for f in self.status_doc()["capability_facts"] if f["capability"] == "config-bundle"]
        row = self.rows("SELECT fact_id, state, since FROM capability_facts WHERE capability = 'config-bundle' AND superseded_by_fact_id IS NULL")
        self.assertEqual([(f["fact_id"], f["state"], f["since"]) for f in facts], row)
        self.assertEqual((row[0][1], self.value("SELECT count(*) FROM capability_facts WHERE capability = 'config-bundle'")), ("failing", 3))

    def test_the_station_incidents_are_listed_and_named_on_their_items(self) -> None:
        doc = self.status_doc()
        journal = json.loads((self.root / "jobs" / "job-inv_t5paused01" / "journal.json").read_text())["exhausted"]
        self.assertEqual((journal["kind"], journal["budget"]), ("retry_exhausted", "launch"))
        by_invocation = {i["invocation_id"]: i for i in doc["incidents"]}
        self.assertEqual(by_invocation["inv_t5paused01"], {"invocation_id": "inv_t5paused01", "blocking": False, "topic_id": T5, **journal})
        stalled = by_invocation["inv_unknown0001"]
        self.assertEqual((stalled["kind"], stalled["blocking"], stalled["last_finding"], stalled["owner"], stalled["deadline_at"], stalled["topic_id"]),
                         ("outcome_unknown_unresolved", True, COLLECTED_END, "supervisor:station-1", "2026-09-27T11:05:00Z", TOPIC))
        on_invocation = self.one(self.invocation(doc, "inv_unknown0001"), "incident")["incident"]
        self.assertEqual({k: v for k, v in on_invocation.items()}, {k: v for k, v in stalled.items() if k != "topic_id"})
        topic = next(t for t in doc["topics"] if t["topic_id"] == T5)
        self.assertEqual(self.one(topic, "incident")["incident"]["kind"], "retry_exhausted")
        self.assertEqual(self.one(topic, "requeue")["cancel_requested_by"], "supervisor")


class ReadOnlyTest(StatusWorld):
    def test_status_changes_nothing(self) -> None:
        """Every table's rows, audit events included, and the jobs directory,
        before and after status of the whole engine and of one topic."""
        files = lambda: {str(p.relative_to(self.root)): p.read_bytes() for p in sorted((self.root / "jobs").rglob("*")) if p.is_file()}  # noqa: E731
        before, jobs_before = self.state(exclude=()), files()
        self.status_doc()
        self.status_doc(T4)
        self.assertEqual((self.state(exclude=()), files()), (before, jobs_before))

    def test_one_topic_or_a_refusal(self) -> None:
        doc = self.status_doc(T4)
        self.assertEqual([t["topic_id"] for t in doc["topics"]], [T4])
        code, reply, _ = self.http("GET", "/v1/status?topic=fleet-a:nope")
        self.assertEqual((code, reply["status"], reply["reason"]), (200, "refused", "unknown_topic"))
