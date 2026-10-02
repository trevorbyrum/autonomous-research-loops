"""The router's other operations: claim, lifecycle facts, observations,
operator decisions, delivery acknowledgements (task 1b).

Trace: design review §5 (claim / record_observation / apply_operator_decision
/ ack_delivery, each with its uniqueness, fencing and atomicity); INVARIANTS
L-1, L-2, L-7, L-8 (leases with generations, one live lease per (topic,
scope)), C-12 (admission derived from state), E-2, RG-4, RG-U, H-2, H-5 (the
A10 observation comparison), G-4, G-13 (decisions bound to their exact
subject; subject hash truth, RA6), P-2, P-7 (delivery receipts, watermarks,
capability facts); gen2/core/control.py.

Oracles: expected outcomes by hand; the store read back with raw SQL; a
refusal leaves every table (audit log included — these operations log only
what they change) as it was.

Structural limits: no transport, so the operator and exporter are trusted
callers here (1e); scheduling (which topic, when a rest ends) is 1d; the
real station/gateway that produces observations is 1c/Phase 2.
"""
from __future__ import annotations

import copy

from gen2.core import canonical
from gen2.tests.router_fixtures import CONFIG, DEADLINE, EXPIRES, OTHER, TOPIC, RouterTestCase, empty_outcome, h, jcs


class ClaimTest(RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.to_queued()

    def test_one_live_lease_per_topic_and_scope(self) -> None:
        first = self.claim("inv_verify001", "verification")
        self.assertEqual(first["status"], "granted")
        before = self.state(exclude=())
        second = self.claim("inv_verify002", "verification")
        self.assertEqual((second["status"], second.get("reason")), ("refused", "lease_held"))
        self.assertEqual(self.state(exclude=()), before)

    def test_scopes_coexist_and_generations_strictly_increase(self) -> None:
        grants = [self.claim(f"inv_{kind[:8]}01", kind) for kind in ("research_pass", "discovery", "verification", "checkpoint")]
        self.assertEqual([g["status"] for g in grants], ["granted"] * 4)
        self.assertEqual([g["lease"]["generation"] for g in grants], [1, 2, 3, 4])
        self.assertEqual(self.rows("SELECT scope FROM leases WHERE released_at IS NULL ORDER BY generation"),
                         [("research",), ("discovery",), ("verification",), ("checkpoint",)])

    def test_an_expired_lease_is_released_and_superseded(self) -> None:
        old = self.claim("inv_verify001", "verification")
        self.clock.set(EXPIRES)
        new = self.claim("inv_verify002", "verification", deadline_at="2027-02-01T00:00:00Z", lease_expires_at="2027-02-01T00:00:00Z")
        self.assertEqual(new["status"], "granted", new)
        self.assertGreater(new["lease"]["generation"], old["lease"]["generation"])
        self.assertEqual(self.rows("SELECT release_reason FROM leases WHERE lease_id = ?", old["lease"]["lease_id"]), [("expired",)])

    def test_a_lost_claim_reply_is_recovered_by_invocation_id(self) -> None:
        first = self.claim("inv_research01")
        before = self.state(exclude=())
        again = self.claim("inv_research01")
        self.assertEqual(again["status"], "replayed")
        self.assertEqual({k: v for k, v in again.items() if k != "status"}, {k: v for k, v in first.items() if k != "status"})
        self.assertEqual(self.state(exclude=()), before)
        self.clock.set("2026-12-30T12:00:00Z")  # past the deadline: the replay still returns the grant it made
        self.assertEqual(self.claim("inv_research01")["status"], "replayed")
        for field, value in (("station_id", "station-2"), ("deadline_at", "2026-12-29T00:00:00Z"), ("config_bundle_hash", h("d")), ("kind", "checkpoint")):
            with self.subTest(field):
                conflict = self.claim("inv_research01", **{field: value}) if field != "kind" else self.claim("inv_research01", "checkpoint")
                self.assertEqual((conflict["status"], conflict.get("reason")), ("refused", "invocation_id_conflict"))
                self.assertEqual(self.state(exclude=()), before)

    def test_a_research_claim_activates_the_topic(self) -> None:
        revision = self.state_revision()
        self.assertEqual(self.claim("inv_research01")["status"], "granted")
        self.assertEqual((self.status(), self.state_revision()), ("active", revision + 1))
        self.assertEqual(self.claim("inv_research02").get("reason"), "topic_not_claimable")  # active: the status gate refuses before the lease check

    def test_admission_comes_from_state_not_from_the_request(self) -> None:
        refused = self.router.claim({"invocation_id": "inv_research01", "kind": "research_pass", "topic_id": TOPIC, "config_bundle_hash": CONFIG,
                                     "deadline_at": DEADLINE, "station_id": "s", "lease_expires_at": EXPIRES,
                                     "admission": {"context": "pre-contract/1"}})
        self.assertEqual((refused["status"], refused.get("reason")), ("refused", "request_invalid"))
        self.assertIn("/admission", refused.get("detail", ""))
        grant = self.claim("inv_research01")
        self.assertEqual(grant["admission"]["context"], "contract/1")
        self.assertEqual(self.rows("SELECT admission_context, contract_revision FROM invocations WHERE invocation_id = 'inv_research01'"), [("contract/1", 1)])

    def test_topic_state_gates_claims(self) -> None:
        self.x("UPDATE queue_entries SET paused_at = '2026-09-27T09:59:00Z' WHERE topic_id = ?", TOPIC)
        self.assertEqual(self.claim("inv_research01").get("reason"), "topic_paused")
        self.assertEqual(self.claim("inv_research01", tid="fleet-a:nowhere").get("reason"), "unknown_topic")
        self.assertEqual(self.claim("inv_research01", tid=OTHER).get("reason"), "not_admissible")  # OTHER is at intake: no brief, no contract
        self.x("UPDATE queue_entries SET paused_at = NULL, status = 'held', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        self.assertEqual(self.claim("inv_research01").get("reason"), "topic_not_claimable")
        self.assertIn("deadline_at", self.claim("inv_research01", deadline_at="2026-09-01T00:00:00Z").get("detail", ""))

    def test_pre_contract_admission_is_for_scoping_kinds_only(self) -> None:
        self.to_scoping(OTHER)
        grant = self.claim("inv_scoping01", "discovery", tid=OTHER)
        self.assertEqual(grant["admission"]["context"], "pre-contract/1")
        self.assertEqual(grant["admission"]["brief"]["brief_id"], "brief-1")
        self.assertEqual(self.claim("inv_verify001", "verification", tid=OTHER).get("reason"), "not_admissible")
        self.assertEqual(self.status(OTHER), "scoping")

    def test_a_delegate_runs_under_its_running_parent(self) -> None:
        parent = self.claim("inv_research01")
        self.assertEqual(self.claim("inv_deleg001", "delegate", parent=parent).get("reason"), "parent_not_running")
        self.running(parent)
        delegate = self.claim("inv_deleg001", "delegate", parent=parent)
        self.assertEqual(delegate["status"], "granted")
        self.assertEqual(delegate["lease"], parent["lease"])
        self.assertEqual(self.rows("SELECT lease_id, parent_invocation_id, contract_revision FROM invocations WHERE invocation_id = 'inv_deleg001'"),
                         [(None, "inv_research01", 1)])
        self.assertEqual(self.claim("inv_deleg002", "delegate", parent=parent, config_bundle_hash=h("d")).get("reason"), "config_bundle_mismatch")
        self.to_queued(OTHER)
        self.assertEqual(self.claim("inv_deleg003", "delegate", tid=OTHER, parent=parent).get("reason"), "cross_topic")


class TransitionTest(RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.grant = self.claim("inv_research01")

    def transition(self, to_state: str, **facts) -> dict:
        return self.router.record_transition({"capability_id": self.grant["capability_id"], "invocation_id": "inv_research01", "to_state": to_state, **facts})

    def test_the_lifecycle_moves_along_l1_only(self) -> None:
        before = self.state(exclude=())
        out = self.transition("running", host_id="h", boot_id="b", start_fingerprint="s")
        self.assertEqual((out["status"], out.get("reason")), ("refused", "transition_not_allowed"))  # admitted -> running skips launch intent (L-2)
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.transition("launching", job_handle="job-1")["status"], "recorded")
        self.assertEqual(self.transition("launching", job_handle="job-1")["status"], "replayed")
        self.assertEqual(self.transition("launching", job_handle="job-2").get("reason"), "transition_conflict")
        self.assertEqual(self.transition("running", host_id="h", boot_id="b", start_fingerprint="s")["status"], "recorded")
        self.assertEqual(self.rows("SELECT seq, from_state, to_state, cause FROM invocation_transitions WHERE invocation_id = 'inv_research01' ORDER BY seq"),
                         [(1, None, "admitted", "claim"), (2, "admitted", "launching", "launch_intent"), (3, "launching", "running", "identity_recorded")])

    def test_a_recorded_fact_replays_after_the_invocation_moves_on(self) -> None:
        """Astra 1b review A5: the key is (invocation, target state), not the
        current state. A lost reply of each earlier fact, resent after the
        invocation advanced and after its lease ended, replays with nothing
        written (state, timestamps, history, audit); the same key with any
        other fact, or with an optional fact left out, conflicts."""
        identity = {"host_id": "h", "container_id": "c", "boot_id": "b", "start_fingerprint": "s"}
        digest, _ = self.stage(empty_outcome("inv_research01"))
        other, _ = self.stage(empty_outcome("inv_research01", "interim_transition"))
        facts = (("launching", {"job_handle": "job-1"}), ("running", identity), ("result_ready", {"result_payload_digest": digest}))
        for to_state, recorded in facts:
            self.assertEqual(self.transition(to_state, **recorded)["status"], "recorded")
        before = self.state(exclude=())
        self.clock.set(EXPIRES)  # the lease has ended: a replay needs no current authority
        for to_state, recorded in facts:
            with self.subTest(to_state):
                self.assertEqual(self.transition(to_state, **recorded), {"status": "replayed", "invocation_id": "inv_research01", "state": to_state})
                self.assertEqual(self.state(exclude=()), before)
        for to_state, changed in (("launching", {"job_handle": "job-2"}), ("running", {**identity, "boot_id": "b2"}),
                                  ("running", {k: v for k, v in identity.items() if k != "container_id"}), ("result_ready", {"result_payload_digest": other})):
            with self.subTest(to_state, changed=changed):
                out = self.transition(to_state, **changed)
                self.assertEqual((out["status"], out.get("reason")), ("refused", "transition_conflict"), out)
                self.assertEqual(self.state(exclude=()), before)

    def test_each_state_is_recorded_with_exactly_its_facts(self) -> None:
        for facts, fragment in (({}, "exactly"), ({"job_handle": "j", "host_id": "h"}, "exactly"), ({"job_handle": "j", "role": "supervisor"}, "/role")):
            with self.subTest(facts):
                out = self.transition("launching", **facts)
                self.assertEqual(out.get("reason"), "request_invalid")
                self.assertIn(fragment, out.get("detail", ""))

    def test_the_final_launch_admission_check(self) -> None:
        """L-7: launch needs a current lease, an unpaused topic and a live deadline."""
        self.x("UPDATE queue_entries SET paused_at = '2026-09-27T10:00:00Z' WHERE topic_id = ?", TOPIC)
        self.assertEqual(self.transition("launching", job_handle="job-1").get("reason"), "topic_paused")
        self.x("UPDATE queue_entries SET paused_at = NULL WHERE topic_id = ?", TOPIC)
        self.clock.set(EXPIRES)
        self.assertEqual(self.transition("launching", job_handle="job-1").get("reason"), "lease_not_current")

    def test_launch_after_the_deadline_is_refused(self) -> None:
        late = self.claim("inv_verify001", "verification", deadline_at="2026-11-01T00:00:00Z")
        self.clock.set("2026-11-01T00:00:00Z")
        out = self.router.record_transition({"capability_id": late["capability_id"], "invocation_id": "inv_verify001", "to_state": "launching", "job_handle": "j"})
        self.assertEqual(out.get("reason"), "deadline_passed")

    def test_a_result_is_ready_only_when_its_bytes_are_staged(self) -> None:
        self.running(self.grant)
        missing = h("4")
        self.assertEqual(self.transition("result_ready", result_payload_digest=missing).get("reason"), "payload_missing")
        self.spool.blobs[missing] = b"not these bytes"
        self.assertEqual(self.transition("result_ready", result_payload_digest=missing).get("reason"), "payload_digest_mismatch")
        digest, _ = self.stage(empty_outcome("inv_research01"))
        self.assertEqual(self.transition("result_ready", result_payload_digest=digest)["status"], "recorded")

    def test_a_failure_releases_the_lease_and_requeues(self) -> None:
        self.running(self.grant)
        revision = self.state_revision()
        facts = {"failure_class": "exit_nonzero", "end_evidence_ref": self.evidence(self.grant)}
        self.assertEqual(self.transition("failed", **facts)["status"], "recorded")
        self.assertEqual(self.rows("SELECT release_reason FROM leases WHERE lease_id = ?", self.grant["lease"]["lease_id"]), [("failed",)])
        self.assertEqual((self.status(), self.state_revision()), ("queued", revision + 1))
        before = self.state(exclude=())
        self.assertEqual(self.transition("failed", **facts)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)

    def test_only_the_invocations_capability_records_its_facts(self) -> None:
        other = self.claim("inv_verify001", "verification")
        out = self.router.record_transition({"capability_id": other["capability_id"], "invocation_id": "inv_research01", "to_state": "launching", "job_handle": "j"})
        self.assertEqual(out.get("reason"), "capability_invocation_mismatch")


class ObservationTest(RouterTestCase):
    """A10 / E-2 / RG-4: an observed result set's count is exactly the
    identities captured with it; unknown is never a zero."""

    def setUp(self) -> None:
        super().setUp()
        self.to_scoping()  # observations are scoping material: open to pre-contract work (C-12)
        self.grant = self.started("inv_discover1", "discovery")

    def observe(self, n_events: int, *, count: int | None = "same", coverage: str = "searched_ok", completeness: str = "complete",
                error: str | None = None, oid: str = "obs_000000000001", request: dict | None = None, identity: str | None = None, **extra) -> dict:
        request = request or {"lane": "crossref", "query": "intake latency", "cursor": None}
        observation = {"observation_id": oid, "request": request, "request_identity": identity or canonical.logical_hash(request), "attempt": 1,
                       "lane": "crossref", "obligation_ids": [], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:05Z",
                       "coverage_state": coverage, "result_count": n_events if count == "same" else count, "completeness": completeness,
                       "error_class": error, "capability_fact_id": None, "policy_version": "gw-policy/1", "cost_units": None, "gateway_call_ref": "call-1",
                       "page_outcome": "failed" if coverage in ("provider_unavailable", "auth_failed", "unknown") else "end_unknown", "continuation": None}
        observation.update(extra)
        events = [{"event_id": f"rev_{oid[4:]}{i:04d}", "provider_record_id": f"rec-{i}", "rank": i + 1, "captured_at": "2026-09-27T10:00:04Z"}
                  for i in range(n_events)]
        return self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": "inv_discover1",
                                               "observation": observation, "retrieval_events": events})

    def refused(self, out: dict, reason: str, before: dict, detail: str) -> None:
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        self.assertIn(detail, out.get("detail", ""))
        self.assertEqual(self.state(exclude=()), before)

    def test_a_complete_count_is_its_captured_identities(self) -> None:
        before = self.state(exclude=())
        self.refused(self.observe(3, count=5), "payload_invalid", before, "result_count 5 is not the 3")  # 5 claimed, 3 captured
        self.refused(self.observe(3, count=2), "payload_invalid", before, "result_count 2 is not the 3")
        out = self.observe(3)
        self.assertEqual((out["status"], out["retrieval_events"]), ("recorded", 3))
        self.assertEqual(self.rows("SELECT result_count, completeness FROM search_observations"), [(3, "complete")])
        self.assertEqual(self.value("SELECT count(*) FROM retrieval_events WHERE observation_id = 'obs_000000000001'"), 3)

    def test_a_partial_set_keeps_what_was_seen_as_a_lower_bound(self) -> None:
        before = self.state(exclude=())
        self.refused(self.observe(2, count=4, completeness="partial", error="partial_pagination"), "payload_invalid", before, "result_count 4 is not the 2")
        self.assertEqual(self.observe(2, completeness="partial", error="partial_pagination")["status"], "recorded")
        self.assertEqual(self.rows("SELECT result_count, completeness, error_class FROM search_observations"), [(2, "partial", "partial_pagination")])

    def test_a_page_outcome_is_typed_and_consistent_with_what_was_read(self) -> None:
        """Gate D #3 (2b-repair-13b): how pagination ended or continued is part of the observation. The vocabulary and the
        cursor's shape are the command schema's; that a page nothing could be read from failed (and only it), that a cursor
        belongs to a continuation or a page cap read off a page that was read, and that a partial page never reports an end
        are the boundary's own checks (the store enforces the same). Each refused observation differs from the recorded
        one in that one respect."""
        before = self.state(exclude=())
        unread = dict(count=None, coverage="provider_unavailable", completeness="unobserved", error="provider_outage")
        for label, kwargs, reason, detail in (
                ("outside the vocabulary", dict(page_outcome="finished"), "request_invalid", "page_outcome"),
                ("a page that was read, failed", dict(page_outcome="failed"), "payload_invalid", "is failed, and only it is"),
                ("a page nothing could be read from, with an unknown end", {**unread, "page_outcome": "end_unknown"}, "payload_invalid", "is failed, and only it is"),
                ("a continuation without its cursor", dict(page_outcome="continuation"), "payload_invalid", "carry one"),
                ("a page cap without its cursor", dict(page_outcome="limit_reached"), "payload_invalid", "carry one"),
                ("a cursor on an end", dict(page_outcome="exhausted", continuation={"cursor": "c2"}), "payload_invalid", "carry one"),
                ("a cursor on an unknown end", dict(continuation={"cursor": "c2"}), "payload_invalid", "carry one"),
                ("a cursor from a page nothing was read from",
                 dict(count=None, coverage="not_searched", completeness="unobserved", page_outcome="continuation", continuation={"cursor": 2}),
                 "payload_invalid", "has no continuation"),
                ("an end reported by a partial page", dict(completeness="partial", error="partial_pagination", page_outcome="exhausted"),
                 "payload_invalid", "an exhausted end is reported by a page read whole"),
                ("a cursor that is not a string or an integer", dict(page_outcome="continuation", continuation={"cursor": 1.5}), "request_invalid", "continuation"),
                ("an empty cursor", dict(page_outcome="continuation", continuation={"cursor": ""}), "request_invalid", "continuation"),
                ("a cursor too long to keep", dict(page_outcome="continuation", continuation={"cursor": "c" * 8001}), "request_invalid", "continuation"),
                ("a cursor with company", dict(page_outcome="continuation", continuation={"cursor": "c2", "x": 1}), "request_invalid", "continuation"),
                ("a bare cursor", dict(page_outcome="continuation", continuation="c2"), "request_invalid", "continuation")):
            with self.subTest(label):
                kwargs = dict(kwargs)
                events = 0 if kwargs.get("coverage") in ("not_searched", "provider_unavailable") else 1
                self.refused(self.observe(events, **kwargs), reason, before, detail)
        for oid, (outcome, cursor) in enumerate((("continuation", {"cursor": "c2"}), ("limit_reached", {"cursor": 20}), ("end_unknown", None), ("exhausted", None)), start=1):
            with self.subTest(recorded=outcome):
                self.assertEqual(self.observe(1, oid=f"obs_00000000000{oid}", request={"q": outcome}, page_outcome=outcome, continuation=cursor)["status"], "recorded")
        self.assertEqual(self.rows("SELECT json_extract(request, '$.q'), page_outcome, completeness, continuation FROM search_observations ORDER BY observation_id"),
                         [("continuation", "continuation", "complete", '{"cursor":"c2"}'), ("limit_reached", "limit_reached", "complete", '{"cursor":20}'),
                          ("end_unknown", "end_unknown", "complete", None), ("exhausted", "exhausted", "complete", None)],
                         "a page read whole stays complete whatever it says of the population; the cursor keeps its type")
        again = dict(request={"q": "continuation"}, oid="obs_000000000001", page_outcome="continuation")
        self.assertEqual(self.observe(1, continuation={"cursor": "c2"}, **again)["status"], "replayed")
        conflicting = self.state(exclude=())
        self.refused(self.observe(1, **{**again, "page_outcome": "exhausted"}, continuation=None), "observation_id_conflict", conflicting, "different content")
        self.refused(self.observe(1, continuation={"cursor": "c3"}, **again), "observation_id_conflict", conflicting, "different content")

    def test_unknown_is_not_zero(self) -> None:
        before = self.state(exclude=())
        self.refused(self.observe(1, count=None, coverage="provider_unavailable", completeness="unobserved", error="provider_outage"), "payload_invalid", before, "unobserved")
        self.refused(self.observe(0, count=0, coverage="provider_unavailable", completeness="unobserved", error="provider_outage"), "payload_invalid", before, "unknown is not zero")
        self.assertEqual(self.observe(0, count=None, coverage="provider_unavailable", completeness="unobserved", error="provider_outage")["status"], "recorded")
        self.assertEqual(self.rows("SELECT result_count FROM search_observations"), [(None,)])
        self.assertEqual(self.observe(0, coverage="searched_empty", oid="obs_000000000002", request={"q": "nothing"})["status"], "recorded")
        self.assertEqual(self.rows("SELECT result_count FROM search_observations WHERE observation_id = 'obs_000000000002'"), [(0,)])

    def test_a_request_identity_is_the_hash_of_its_request(self) -> None:
        """H-5: two different requests never share an identity."""
        before = self.state(exclude=())
        self.refused(self.observe(1, identity=canonical.logical_hash({"lane": "crossref", "query": "something else", "cursor": None})), "payload_invalid", before, "request_identity is not the hash")
        self.assertEqual(self.observe(1)["status"], "recorded")

    def test_a_record_is_captured_once_per_observation(self) -> None:
        before = self.state(exclude=())
        out = self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": "inv_discover1",
                                              "observation": {**self.observation_doc(2)}, "retrieval_events": [
                                                  {"event_id": "rev_000000000001", "provider_record_id": "rec-1", "rank": 1, "captured_at": "2026-09-27T10:00:04Z"},
                                                  {"event_id": "rev_000000000002", "provider_record_id": "rec-1", "rank": 2, "captured_at": "2026-09-27T10:00:04Z"}]})
        self.refused(out, "payload_invalid", before, "captured twice")

    def observation_doc(self, count: int) -> dict:
        request = {"lane": "crossref", "query": "intake latency", "cursor": None}
        return {"observation_id": "obs_000000000001", "request": request, "request_identity": canonical.logical_hash(request), "attempt": 1,
                "lane": "crossref", "obligation_ids": [], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:05Z",
                "coverage_state": "searched_ok", "result_count": count, "completeness": "complete", "error_class": None, "capability_fact_id": None,
                "policy_version": "gw-policy/1", "cost_units": None, "gateway_call_ref": "call-1", "page_outcome": "end_unknown", "continuation": None}

    def test_an_unobserved_result_set_is_recorded_with_no_count(self) -> None:
        """The accepted case of test_unknown_is_not_zero, split out as a control of its own (task 1c-repair-3; Astra 1c re-review 2 BLOCK 2): an
        unobserved set with no records and no count is recorded, its count
        unknown."""
        self.assertEqual(self.observe(0, count=None, coverage="provider_unavailable", completeness="unobserved", error="provider_outage")["status"], "recorded")
        self.assertEqual(self.rows("SELECT result_count, completeness FROM search_observations"), [(None, "unobserved")])

    def test_the_same_observation_again_replays(self) -> None:
        """The accepted case of test_replay_and_conflict_by_observation_id,
        split out as a control of its own (task 1c-repair-3; Astra 1c re-review 2 BLOCK 2)."""
        self.assertEqual(self.observe(2)["status"], "recorded")
        before = self.state(exclude=())
        self.assertEqual(self.observe(2)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)

    def test_replay_and_conflict_by_observation_id(self) -> None:
        self.assertEqual(self.observe(2)["status"], "recorded")
        before = self.state(exclude=())
        self.assertEqual(self.observe(2)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        self.refused(self.observe(3), "observation_id_conflict", before, "different content")
        self.refused(self.observe(2, lane="openalex"), "observation_id_conflict", before, "different content")

    def test_impossible_or_contradictory_times_are_refused(self) -> None:
        before = self.state(exclude=())
        self.refused(self.observe(1, started_at="2026-02-29T10:00:00Z"), "request_invalid", before, "started_at")
        self.refused(self.observe(1, ended_at="2026-09-27T09:59:59Z"), "payload_invalid", before, "ended before")

    def test_only_a_running_invocation_records_observations(self) -> None:
        self.assertEqual(self.router.record_transition({"capability_id": self.grant["capability_id"], "invocation_id": "inv_discover1", "to_state": "failed",
                                                        "failure_class": "exit_nonzero", "end_evidence_ref": self.evidence(self.grant)})["status"], "recorded")
        before = self.state(exclude=())
        self.refused(self.observe(1), "invocation_state_invalid", before, "failed")

    def test_a_running_invocation_past_its_lease_records_nothing(self) -> None:
        """Astra 1b review C1: the invocation is still running, so only the
        lease can refuse; the same observation records once the clock is back
        inside the lease. (Exact expiry and a lock wait: test_router_time.)"""
        self.clock.set(EXPIRES)
        before = self.state(exclude=())
        self.refused(self.observe(1), "lease_not_current", before, "expired at")
        self.clock.set("2026-09-27T11:00:00Z")
        self.assertEqual(self.observe(1)["status"], "recorded")

    def test_a_paused_topic_records_no_observation(self) -> None:
        self.x("UPDATE queue_entries SET paused_at = '2026-09-27T10:00:00Z' WHERE topic_id = ?", TOPIC)
        before = self.state(exclude=())
        self.refused(self.observe(1), "topic_paused", before, "paused at")
        self.x("UPDATE queue_entries SET paused_at = NULL WHERE topic_id = ?", TOPIC)
        self.assertEqual(self.observe(1)["status"], "recorded")


class OperatorDecisionTest(RouterTestCase):
    def test_the_same_decision_again_replays(self) -> None:
        """The accepted replay of test_brief_confirmation_moves_intake_to_scoping,
        split out as a control of its own (task 1c-repair-3; Astra 1c re-review 2 BLOCK 2)."""
        subject = {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": self.brief()}
        self.assertEqual(self.decide("opd_brief0001", "brief_confirmation", subject)["status"], "applied")
        before = self.state(exclude=())
        self.assertEqual(self.decide("opd_brief0001", "brief_confirmation", subject)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)

    def test_brief_confirmation_moves_intake_to_scoping(self) -> None:
        bhash = self.brief()
        subject = {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": bhash}
        out = self.decide("opd_brief0001", "brief_confirmation", subject)
        self.assertEqual(out["status"], "applied")
        self.assertEqual(out["effects"]["queue_transition"], {"from": "awaiting_brief_confirmation", "to": "scoping"})
        self.assertEqual(self.rows("SELECT status, confirmed_by_decision_id FROM intake_briefs"), [("confirmed", "opd_brief0001")])
        before = self.state(exclude=())
        self.assertEqual(self.decide("opd_brief0001", "brief_confirmation", subject)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        conflict = self.decide("opd_brief0001", "brief_confirmation", subject, disposition="rejected")
        self.assertEqual((conflict["status"], conflict.get("reason")), ("rejected", "decision_id_conflict"))
        self.assertEqual(self.state(exclude=()), before)

    def test_a_decision_about_a_near_miss_subject_records_nothing(self) -> None:
        bhash = self.brief()
        before = self.state(exclude=())
        for subject in ({"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": h("0")},
                        {"kind": "intake_brief", "ref": "brief-1", "revision": 2, "hash": bhash},
                        {"kind": "intake_brief", "ref": "brief-2", "revision": 1, "hash": bhash}):
            with self.subTest(subject):
                out = self.decide("opd_brief0001", "brief_confirmation", subject)
                self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"))
                self.assertIn("existing subject", out.get("detail", ""))
                self.assertEqual(self.state(exclude=()), before)

    def test_approval_binds_to_a_hash_that_is_true_of_the_stored_document(self) -> None:
        """RA6 hash truth: a contract whose recorded hash is not the hash of
        its stored document cannot be approved (the DDL binds label to
        label; the router recomputes)."""
        self.to_scoping()
        forged = self.contract_draft(TOPIC, 1, true_hash=False)
        self.scope_seeded()
        before = self.state(exclude=())
        out = self.decide("opd_cntr0001", "contract_approval", {"kind": "contract_revision", "revision": 1, "hash": forged})
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "subject_hash_untrue"))
        self.assertEqual(self.state(exclude=()), before)

    def test_a_first_contract_approval_supersedes_nothing(self) -> None:
        """The alternative the supersession loop admits (task 1c-repair-4, the
        C4 re-check): the topic's first approval finds no approved revision,
        supersedes nothing, and approves exactly this one."""
        self.to_scoping()
        chash = self.contract_draft(TOPIC, 1)
        self.scope_seeded()
        out = self.decide(f"opd_cntr{TOPIC[-2:]}01", "contract_approval", {"kind": "contract_revision", "revision": 1, "hash": chash})
        self.assertEqual(out["status"], "applied", out)
        self.assertEqual((out["effects"]["contract_approved"], out["effects"]["contract_superseded"]), (1, []))
        self.assertEqual(self.rows("SELECT revision, status FROM contract_revisions WHERE topic_id = ? ORDER BY revision", TOPIC), [(1, "approved")])
        self.assertEqual(self.rows("SELECT status, active_contract_revision FROM queue_entries WHERE topic_id = ?", TOPIC), [("queued", 1)])

    def test_contract_approval_queues_the_topic_and_an_amendment_supersedes(self) -> None:
        self.to_queued()
        self.assertEqual(self.rows("SELECT status, active_contract_revision FROM queue_entries WHERE topic_id = ?", TOPIC), [("queued", 1)])
        chash = self.contract_draft(TOPIC, 2)
        out = self.decide("opd_amend0001", "amendment_approval", {"kind": "contract_revision", "revision": 2, "hash": chash})
        self.assertEqual(out["status"], "applied", out)
        self.assertEqual((out["effects"]["contract_approved"], out["effects"]["contract_superseded"]), (2, [1]))
        self.assertEqual(self.rows("SELECT revision, status FROM contract_revisions WHERE topic_id = ? ORDER BY revision", TOPIC), [(1, "superseded"), (2, "approved")])
        self.assertEqual(self.value("SELECT active_contract_revision FROM queue_entries WHERE topic_id = ?", TOPIC), 2)

    def test_a_decision_whose_transition_the_state_forbids_is_refused_whole(self) -> None:
        self.to_scoping()
        report = self.scoped()  # the topic now awaits contract approval
        before = self.state(exclude=())
        out = self.decide("opd_scope0002", "scope_approval", {"kind": "scoping_report", "ref": "scope-1", "revision": 1, "hash": report["content_hash"]})
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"))  # awaiting contract approval, not scope approval
        self.assertIn("moves it only from", out.get("detail", ""))
        self.assertEqual(self.state(exclude=()), before)

    def test_retirement_is_bound_to_the_state_revision_being_left(self) -> None:
        self.to_scoping()
        stale = self.state_revision() - 1
        before = self.state(exclude=())
        out = self.decide("opd_retire001", "retirement", {"kind": "topic", "revision": stale})
        self.assertEqual(out.get("reason"), "decision_refused")
        self.assertIn("current state revision", out.get("detail", ""))
        self.assertEqual(self.state(exclude=()), before)
        out = self.decide("opd_retire001", "retirement", {"kind": "topic", "revision": self.state_revision()})
        self.assertEqual((out["status"], self.status()), ("applied", "retired"))

    def test_completion_binds_to_the_current_dossier(self) -> None:
        """G-8 through the router: completion names an approved completion
        approval of the current dossier revision; a decision about a dossier
        that is not stored records nothing; the approved one completes the
        topic and becomes its authorizing decision."""
        self.to_queued()
        self.started("inv_research01")  # active
        before = self.state(exclude=())
        missing = self.decide("opd_complete01", "completion_approval", {"kind": "dossier", "revision": 1, "hash": h("3")})
        self.assertEqual((missing["status"], missing.get("reason")), ("rejected", "decision_refused"))
        self.assertIn("existing subject", missing.get("detail", ""))
        self.assertEqual(self.state(exclude=()), before)
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), "2026-09-27T09:00:00Z")
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) "
               "VALUES (?, 1, 1, 1, 'eval-1', ?, ?, '2026-09-27T09:00:00Z')", TOPIC, h("3"), h("7"))  # dossier assembly is Phase 2
        out = self.decide("opd_complete01", "completion_approval", {"kind": "dossier", "revision": 1, "hash": h("3")})
        self.assertEqual(out["effects"]["queue_transition"], {"from": "active", "to": "completed_with_qualified_conclusions"})
        self.assertEqual(self.rows("SELECT status, status_decision_id FROM queue_entries WHERE topic_id = ?", TOPIC),
                         [("completed_with_qualified_conclusions", "opd_complete01")])

    def test_a_rejected_decision_is_recorded_and_changes_nothing_else(self) -> None:
        bhash = self.brief()
        out = self.decide("opd_brief0001", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": bhash}, disposition="rejected")
        self.assertEqual((out["status"], out["effects"]), ("applied", {}))
        self.assertEqual(self.rows("SELECT status FROM intake_briefs"), [("awaiting_confirmation",)])
        self.assertEqual(self.status(), "awaiting_brief_confirmation")

    def test_hold_clearance(self) -> None:
        self.to_queued()
        grant = self.started("inv_research01")
        outcome = empty_outcome("inv_research01", "interim_transition")
        outcome["holds"] = [{"hold_id": "hold_000000000001", "subject_ref": "obligation:O-1", "hold_class": "judgment", "cause": "c", "recoverability": "needs_decision",
                             "required_authority": "operator", "owner": "user", "deadline_at": "2026-10-01T00:00:00Z", "clears_when": "the user decides",
                             "capability_fact_id": None}]
        self.assertEqual(self.router.commit_outcome(self.envelope(grant, "op_interim0001", outcome))["status"], "committed")
        self.assertEqual(self.rows("SELECT created_by_operation_id, cleared_at FROM holds"), [("op_interim0001", None)])
        out = self.decide("opd_clear0001", "hold_clearance", {"kind": "hold", "ref": "hold_000000000001"})
        self.assertEqual(out["effects"], {"hold_cleared": "hold_000000000001"})
        self.assertEqual(self.rows("SELECT cleared_by_decision_id FROM holds"), [("opd_clear0001",)])


class AckDeliveryTest(RouterTestCase):
    """P-2 / P-7 / H-2: one receipt per attempt, only for a committed
    manifest's own connectors; watermarks never regress; failures and unknown
    outcomes raise dated capability facts on transitions."""

    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.checkpoint = self.started("inv_checkpt01", "checkpoint")
        for generation in (1, 2):
            self.export(self.checkpoint, generation)

    def receipt(self, rid: str, status: str = "delivered", **extra) -> dict:
        return self.delivery_receipt(rid, status, **extra)

    def ack(self, doc: dict) -> dict:
        return self.router.ack_delivery(doc)

    def test_a_delivery_is_recorded_once_and_advances_the_watermark(self) -> None:
        self.assertEqual(self.ack(self.receipt("exr_000000000001"))["status"], "recorded")
        self.assertEqual(self.rows("SELECT generation, options_revision FROM connector_watermarks WHERE connector_id = 'warehouse'"), [(1, 1)])
        before = self.state(exclude=())
        self.assertEqual(self.ack(self.receipt("exr_000000000001"))["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        conflict = self.ack(self.receipt("exr_000000000001", attempted_at="2026-09-27T12:00:00.5Z"))
        self.assertEqual((conflict["status"], conflict.get("reason")), ("rejected", "export_receipt_id_conflict"))
        self.assertEqual(self.state(exclude=()), before)

    def test_the_whole_receipt_is_recorded(self) -> None:
        """Astra 1b review A2 (EXPORT-API.md §9 item 3): the receipt is stored
        as it came, byte for byte in its JCS form, beside its columns. The
        written count keeps each of its three states (a partial lower bound is
        not an unknown, an unknown is not a zero), and the hold and invocation
        a receipt names are kept."""
        self.hold(self.checkpoint, "hold_000000000001")
        docs = [self.receipt("exr_000000000001", "outcome_unknown", attempt=1, capability_fact_id="fact_warehouse01", hold_id="hold_000000000001",
                             invocation_id="inv_checkpt01", written={"status": "partial", "value": 7, "reason": "seven rows acknowledged, the rest unknown"}),
                self.receipt("exr_000000000002", "outcome_unknown", attempt=2, capability_fact_id="fact_warehouse01"),
                self.receipt("exr_000000000003", attempt=3)]
        for doc in docs:
            self.assertEqual(self.ack(doc)["status"], "recorded")
        self.assertEqual(self.rows("SELECT receipt, written_status, written_value, hold_id FROM export_delivery_receipts ORDER BY attempt"),
                         [(jcs(docs[0]).decode(), "partial", 7, "hold_000000000001"), (jcs(docs[1]).decode(), "unknown", None, None),
                          (jcs(docs[2]).decode(), "observed", 12, None)])

    def test_the_same_receipt_again_replays(self) -> None:
        """The accepted replay of test_a_replay_is_the_same_document, split out
        as a control of its own (task 1c-repair-3; Astra 1c re-review 2 BLOCK 2):
        the same receipt, its keys in another order, replays with nothing written."""
        doc = self.receipt("exr_000000000001")
        self.assertEqual(self.ack(doc)["status"], "recorded")
        before = self.state(exclude=())
        self.assertEqual(self.ack(dict(reversed(list(doc.items()))))["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)

    def test_a_replay_is_the_same_document(self) -> None:
        """Astra 1b review A2: an export receipt id replays exactly the
        document it recorded. The same document (in any key order) replays
        with nothing written, audit included; a document differing in any one
        field — the topic and ordering pair it repeats from its manifest, the
        written count, an optional reference added, changed or left out — is a
        conflict, and no watermark, fact or row moves."""
        self.hold(self.checkpoint, "hold_000000000001")
        self.hold(self.checkpoint, "hold_000000000002")
        doc = self.receipt("exr_000000000001", "outcome_unknown", capability_fact_id="fact_warehouse01", hold_id="hold_000000000001",
                           invocation_id="inv_checkpt01", written={"status": "partial", "value": 7, "reason": "seven rows acknowledged, the rest unknown"})
        self.assertEqual(self.ack(doc)["status"], "recorded")
        self.assertEqual(self.ack(self.receipt("exr_000000000002", attempt=2))["status"], "recorded")
        before = self.state(exclude=())
        self.assertEqual(self.ack(dict(reversed(list(copy.deepcopy(doc).items())))), {"status": "replayed", "export_receipt_id": "exr_000000000001"})
        self.assertEqual(self.state(exclude=()), before)
        changes = {"topic_id": OTHER, "generation": 2, "options_revision": 2,
                   "written": {"status": "partial", "value": 999, "reason": "seven rows acknowledged, the rest unknown"},
                   "hold_id": "hold_000000000002", "invocation_id": "inv_research01", "unknown_cause": "unreadable_response", "attempted_at": "2026-09-27T12:00:00.5Z"}
        variants = [(field, {**copy.deepcopy(doc), field: value}) for field, value in changes.items()]
        variants.append(("written unknown", {**copy.deepcopy(doc), "written": {"status": "unknown", "reason": "no counts observed"}}))
        variants += [(f"without {field}", {k: v for k, v in copy.deepcopy(doc).items() if k != field}) for field in ("hold_id", "invocation_id")]
        for name, changed in variants:
            with self.subTest(name):
                out = self.ack(changed)
                self.assertEqual((out["status"], out.get("reason")), ("rejected", "export_receipt_id_conflict"), out)
                self.assertEqual(self.state(exclude=()), before)

    def test_a_named_hold_is_one_of_the_manifests_topic(self) -> None:
        """H-3: a receipt's hold owns this topic's delivery, so it is a
        recorded hold of the manifest's topic; nothing is written otherwise."""
        self.to_queued(OTHER)
        self.hold(self.started("inv_checkpt02", "checkpoint", tid=OTHER), "hold_000000000009")
        self.hold(self.checkpoint, "hold_000000000001")
        before = self.state(exclude=())
        for hold in ("hold_000000000009", "hold_000000000404"):
            with self.subTest(hold):
                out = self.ack(self.receipt("exr_000000000001", "failed", capability_fact_id="fact_warehouse01", hold_id=hold))
                self.assertEqual((out["status"], out.get("reason")), ("rejected", "delivery_refused"), out)
                self.assertIn("is not a recorded hold of", out.get("detail", ""))
                self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.ack(self.receipt("exr_000000000001", "failed", capability_fact_id="fact_warehouse01", hold_id="hold_000000000001"))["status"],
                         "recorded")

    def test_a_receipt_must_describe_its_manifest(self) -> None:
        before = self.state(exclude=())
        for doc, reason, fragment in ((self.receipt("exr_000000000001", generation=1, attempt=2), "delivery_refused", "next attempt"),
                                      (self.receipt("exr_000000000001", options_revision=2), "delivery_refused", "does not describe"),
                                      (self.receipt("exr_000000000001", topic_id=OTHER), "delivery_refused", "does not describe"),
                                      (self.receipt("exr_000000000001", manifest_id="man_nowhere01"), "unknown_manifest", "not a committed manifest"),
                                      (self.receipt("exr_000000000001", connector="lake"), "delivery_refused", "does not name")):
            with self.subTest(fragment=fragment):
                out = self.ack(doc)
                self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
                self.assertIn(fragment, out.get("detail", ""))
                self.assertEqual(self.state(exclude=()), before)

    def test_a_delivery_of_the_pair_the_watermark_holds_leaves_it(self) -> None:
        """A second attempt delivering the pair the connector already holds is
        recorded and the watermark stays (neither older nor newer; split out as a control of its own (task 1c-repair-3; Astra 1c re-review 2 BLOCK 2))."""
        self.assertEqual(self.ack(self.receipt("exr_000000000001", generation=2))["status"], "recorded")
        self.assertEqual(self.ack(self.receipt("exr_000000000002", generation=2, attempt=2))["status"], "recorded")
        self.assertEqual(self.rows("SELECT generation, options_revision FROM connector_watermarks WHERE connector_id = 'warehouse'"), [(2, 1)])

    def test_the_watermark_never_regresses(self) -> None:
        self.assertEqual(self.ack(self.receipt("exr_000000000001", generation=1))["status"], "recorded")
        self.assertEqual(self.ack(self.receipt("exr_000000000002", generation=2))["status"], "recorded")
        self.assertEqual(self.rows("SELECT generation, options_revision FROM connector_watermarks WHERE connector_id = 'warehouse'"), [(2, 1)])
        before = self.state(exclude=())
        out = self.ack(self.receipt("exr_000000000009", generation=1, attempt=2))
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "watermark_regression"))
        self.assertEqual(self.state(exclude=()), before)
        self.assertIn("already holds (2, 1)", out.get("detail", ""))
        self.assertEqual(self.ack(self.receipt("exr_000000000003", generation=1, attempt=2, status="skipped_superseded", written={"status": "observed", "value": 0},
                                               tombstones_acknowledged=False, acked_at=None))["status"], "recorded")

    def test_failures_raise_capability_facts_on_transitions(self) -> None:
        self.assertEqual(self.ack(self.receipt("exr_000000000001", "failed", capability_fact_id="fact_warehouse01"))["status"], "recorded")
        self.assertEqual(self.rows("SELECT fact_id, capability, state, since FROM capability_facts"),
                         [("fact_warehouse01", "export-connector:warehouse", "failing", "2026-09-27T12:00:00Z")])
        # a second failure while failing names the current fact; a new id would claim a transition that did not happen
        self.assertEqual(self.ack(self.receipt("exr_000000000002", "failed", attempt=2, capability_fact_id="fact_warehouse01"))["status"], "recorded")
        before = self.state(exclude=())
        out = self.ack(self.receipt("exr_000000000003", "failed", attempt=3, capability_fact_id="fact_warehouse02"))
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "delivery_refused"))
        self.assertIn("already failing", out.get("detail", ""))
        self.assertEqual(self.state(exclude=()), before)
        # an unknown outcome is a transition of its own (P-7)
        self.assertEqual(self.ack(self.receipt("exr_000000000003", "outcome_unknown", attempt=3, capability_fact_id="fact_warehouse02"))["status"], "recorded")
        self.assertEqual(self.ack(self.receipt("exr_000000000004", attempt=4))["status"], "recorded")
        facts = self.rows("SELECT state, superseded_by_fact_id IS NULL FROM capability_facts WHERE capability = 'export-connector:warehouse' ORDER BY rowid")
        self.assertEqual(facts, [("failing", 0), ("unknown", 0), ("healthy", 1)])
        self.assertEqual(self.rows("SELECT status FROM export_delivery_receipts ORDER BY attempt"), [("failed",), ("failed",), ("outcome_unknown",), ("delivered",)])
