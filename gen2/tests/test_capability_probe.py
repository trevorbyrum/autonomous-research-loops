"""The router's record of one capability observation (gen2/router/capabilities.py),
and the shared `observation` builder the dispatch and composition tests import.

The producer of these observations, the station's local login-status probe, is
retired (S14 D4; DEBT-065). The Router's projection of an observation, its
dated fact and typed hold, and the replay of old `capability_probe` audits
stay, and the gateway still records facts through the same path.

Trace: BOUNDARIES.md Router (holds typed, owned, deadlined); INVARIANTS H-2,
H-3, RG-3, G-13. Every expected fact and hold field is written by hand from
the rules the module states; read-backs are raw SQL on the test's own
connection.
"""
from __future__ import annotations

import json

from gen2.core.instants import utc_instant_ns
from gen2.tests import router_fixtures as rf

CAP = "provider-auth:codex"


def observation(pid: str, outcome: str, observed: str, *, started: str | None = None, detail: str = "by hand", declared: dict | None = None) -> dict:
    return {"probe_id": "probe_" + pid.ljust(32, "0"), "capability": CAP, "outcome": outcome, "detail": detail, "declared_expiry": declared,
            "started_at": started or observed, "observed_at": observed, "runner": {"name": "codex", "version": "0.169.0"},
            "affected_lanes": ["station:station-1"], "requested_by": "alice"}



class ProbeRecordTest(rf.RouterTestCase):
    """The router's record of one observation (capabilities.py), each case by hand."""

    def facts(self) -> list[tuple]:
        return self.rows("SELECT fact_id, state, since, last_success_at, superseded_by_fact_id FROM capability_facts WHERE capability = ? ORDER BY rowid", CAP)

    def holds(self) -> list[dict]:
        cols = ("hold_id", "topic_id", "subject_ref", "hold_class", "cause", "recoverability", "required_authority", "owner", "deadline_at",
                "clears_when", "capability_fact_id", "created_at", "cleared_at")
        return [dict(zip(cols, r)) for r in self.rows(f"SELECT {', '.join(cols)} FROM holds WHERE subject_ref = ? ORDER BY rowid", "capability:" + CAP)]

    def record(self, obs: dict) -> dict:
        return self.router.record_capability_probe(obs)

    def test_the_first_observation_is_a_transition_even_when_usable(self):
        reply = self.record(observation("a1", "usable", "2026-09-27T10:00:05Z"))
        self.assertEqual(reply["status"], "recorded")
        self.assertEqual(reply["fact"]["state"], "healthy")
        self.assertTrue(reply["fact"]["transition"])
        self.assertEqual(self.facts(), [(reply["fact"]["fact_id"], "healthy", "2026-09-27T10:00:05Z", None, None)])
        self.assertIsNone(reply["hold"])
        self.assertEqual(self.holds(), [])

    def test_the_fact_moves_on_a_transition_only_and_names_its_last_success(self):
        first = self.record(observation("b1", "usable", "2026-09-27T10:00:05Z"))
        second = self.record(observation("b2", "usable", "2026-09-27T10:00:06Z"))
        self.assertEqual(second["fact"]["fact_id"], first["fact"]["fact_id"])
        self.assertFalse(second["fact"]["transition"])
        failing = self.record(observation("b3", "unusable_credential", "2026-09-27T10:00:07Z", detail="the runner finds no credential"))
        again = self.record(observation("b4", "unusable_credential", "2026-09-27T10:00:08Z"))
        self.assertEqual(again["fact"]["fact_id"], failing["fact"]["fact_id"])
        self.assertEqual(self.facts(), [
            (first["fact"]["fact_id"], "healthy", "2026-09-27T10:00:05Z", None, failing["fact"]["fact_id"]),
            (failing["fact"]["fact_id"], "failing", "2026-09-27T10:00:07Z", "2026-09-27T10:00:06Z", None)])  # the last usable observation, not the fact's since
        self.assertEqual(self.value("SELECT detail FROM capability_facts WHERE fact_id = ?", failing["fact"]["fact_id"]),
                         "unusable_credential: the runner finds no credential")

    def test_an_unusable_credential_opens_one_typed_owned_deadlined_hold_bound_to_its_fact(self):
        failing = self.record(observation("c1", "unusable_credential", "2026-09-27T10:00:05Z", detail="the runner cannot parse the credential"))
        again = self.record(observation("c2", "unusable_credential", "2026-09-27T10:00:06Z"))
        self.assertTrue(failing["hold"]["opened"])
        self.assertEqual(again["hold"], {"hold_id": failing["hold"]["hold_id"], "opened": False})
        [hold] = self.holds()
        created = hold["created_at"]
        self.assertEqual(hold, {
            "hold_id": failing["hold"]["hold_id"], "topic_id": None, "subject_ref": "capability:" + CAP, "hold_class": "capability",
            "cause": CAP + " unusable_credential: the runner cannot parse the credential", "recoverability": "needs_remediation",
            "required_authority": "operator", "owner": "operator",
            "deadline_at": hold["deadline_at"], "clears_when": hold["clears_when"], "capability_fact_id": failing["fact"]["fact_id"],
            "created_at": created, "cleared_at": None})
        self.assertEqual(utc_instant_ns(hold["deadline_at"]) - utc_instant_ns(created), 3600 * 10**9)  # the router's shipped hold window
        self.assertIn("hold_clearance", hold["clears_when"])
        self.assertNotIn("probe", hold["clears_when"])  # the probe is retired; old holds keep their stored text

    def test_a_long_detail_is_cut_to_500_characters_in_the_hold_cause(self):
        self.record(observation("c3", "unusable_credential", "2026-09-27T10:00:05Z", detail="x" * 500))
        self.assertEqual([h["cause"] for h in self.holds()], [(CAP + " unusable_credential: " + "x" * 500)[:500]])
        self.assertEqual([len(h["cause"]) for h in self.holds()], [500])

    def test_a_runner_error_is_an_unknown_fact_and_a_hold_whose_remedy_is_unknown(self):
        reply = self.record(observation("d1", "runner_error", "2026-09-27T10:00:05Z", detail="login status ran past the probe timeout"))
        self.assertEqual(reply["fact"]["state"], "unknown")
        self.assertEqual([(h["hold_class"], h["recoverability"], h["capability_fact_id"]) for h in self.holds()],
                         [("capability", "unknown", reply["fact"]["fact_id"])])

    def test_a_declared_expiry_is_a_degraded_fact_and_a_hold_to_remedy(self):
        usable = self.record(observation("d21", "usable", "2026-09-27T10:00:05Z"))
        declared = {"access_token": "2001-09-09T01:46:40Z", "id_token": None, "refresh_credential": True}
        reply = self.record(observation("d22", "declared_expired", "2026-09-27T10:00:06Z", detail="its access token declares it expired",
                                        declared=declared))
        self.assertEqual((reply["outcome"], reply["declared_expiry"], reply["fact"]["state"], reply["fact"]["transition"]),
                         ("declared_expired", declared, "degraded", True))
        self.assertEqual(self.facts()[-1], (reply["fact"]["fact_id"], "degraded", "2026-09-27T10:00:06Z", "2026-09-27T10:00:05Z", None))
        self.assertEqual(self.value("SELECT detail FROM capability_facts WHERE fact_id = ?", reply["fact"]["fact_id"]),
                         "declared_expired: its access token declares it expired")
        self.assertEqual([(h["hold_class"], h["recoverability"], h["owner"], h["required_authority"], h["capability_fact_id"], h["cause"])
                          for h in self.holds()],
                         [("capability", "needs_remediation", "operator", "operator", reply["fact"]["fact_id"],
                           CAP + " declared_expired: its access token declares it expired")])
        self.assertIsNone(usable["hold"])

    def test_a_declared_expired_observation_names_its_access_expiry_at_or_before_it_was_observed(self):
        before = self.state(exclude=())
        at = "2026-09-27T10:00:06Z"
        for declared in (None, {"access_token": None, "id_token": "2001-09-09T01:46:40Z", "refresh_credential": False},
                         {"access_token": "2026-09-27T10:00:07Z", "id_token": None, "refresh_credential": False}):
            with self.subTest(declared=declared):
                self.assertEqual(self.record(observation("d31", "declared_expired", at, declared=declared)),
                                 {"status": "refused", "reason": "request_invalid",
                                  "detail": "declared_expired names the access token's declared expiry, at or before the observation"})
        self.assertEqual(self.state(exclude=()), before)
        exact = self.record(observation("d32", "declared_expired", at, declared={"access_token": at, "id_token": None, "refresh_credential": False}))
        self.assertEqual((exact["status"], exact["fact"]["state"]), ("recorded", "degraded"))  # at the instant itself: RFC 7519, on or after

    def test_a_usable_probe_clears_no_hold_an_operator_clearance_does_and_a_later_failure_opens_a_new_one(self):
        failing = self.record(observation("e1", "unusable_credential", "2026-09-27T10:00:05Z"))
        usable = self.record(observation("e2", "usable", "2026-09-27T10:00:06Z"))
        self.assertEqual(usable["fact"]["state"], "healthy")
        self.assertIsNone(usable["hold"])
        self.assertIsNone(self.holds()[0]["cleared_at"])  # a probe clears nothing
        self.assertEqual(self.decide("opd_clearprobe01", "hold_clearance", {"kind": "hold", "ref": failing["hold"]["hold_id"]}, tid=None)["status"], "applied")
        self.assertIsNotNone(self.holds()[0]["cleared_at"])
        later = self.record(observation("e3", "unusable_credential", "2026-09-27T10:00:07Z"))
        holds = self.holds()
        self.assertEqual([(h["hold_id"], h["cleared_at"] is None) for h in holds], [(failing["hold"]["hold_id"], False), (holds[-1]["hold_id"], True)])
        self.assertEqual(later["hold"], {"hold_id": holds[1]["hold_id"], "opened": True})

    def test_a_hold_cleared_while_the_capability_still_fails_is_opened_again_by_the_next_failure(self):
        failing = self.record(observation("f1", "unusable_credential", "2026-09-27T10:00:05Z"))
        self.assertEqual(self.decide("opd_clearprobe02", "hold_clearance", {"kind": "hold", "ref": failing["hold"]["hold_id"]}, tid=None)["status"], "applied")
        again = self.record(observation("f2", "unusable_credential", "2026-09-27T10:00:06Z"))
        self.assertFalse(again["fact"]["transition"])  # still failing: no new fact ...
        holds = self.holds()
        self.assertEqual([h["cleared_at"] is None for h in holds], [False, True])  # ... and a hold again
        self.assertEqual(again["hold"], {"hold_id": holds[1]["hold_id"], "opened": True})

    def test_an_older_observation_is_kept_and_moves_nothing(self):
        newer = self.record(observation("7a1", "usable", "2026-09-27T10:00:09Z"))
        older = self.record(observation("7a2", "unusable_credential", "2026-09-27T10:00:08Z"))
        self.assertEqual(older["status"], "recorded")
        self.assertFalse(older["applied"])
        self.assertEqual(older["fact"]["fact_id"], newer["fact"]["fact_id"])
        self.assertIsNone(older["hold"])
        self.assertEqual([f[1] for f in self.facts()], ["healthy"])
        self.assertEqual(self.holds(), [])
        self.assertEqual(self.value("SELECT count(*) FROM audit_events WHERE kind = 'capability_probe'"), 2)

    def test_the_same_observation_replays_its_answer_and_another_under_its_id_is_a_conflict(self):
        obs = observation("8a1", "unusable_credential", "2026-09-27T10:00:05Z")
        first = self.record(obs)
        self.assertEqual(self.record(obs), {**first, "status": "replayed"})
        self.assertEqual(self.record({**obs, "outcome": "usable"}),
                         {"status": "refused", "reason": "probe_conflict", "detail": f"{obs['probe_id']} was recorded with another observation"})
        self.assertEqual(len(self.facts()), 1)
        self.assertEqual(len(self.holds()), 1)
        recorded = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", "aud_" + obs["probe_id"]))
        self.assertEqual(recorded, {"observation": obs, "reply": first})

    def test_a_lost_reply_is_answered_again_from_the_record(self):
        obs = observation("8b1", "unusable_credential", "2026-09-27T10:00:05Z")
        first = self.record(obs)
        before = self.state(exclude=())
        self.assertEqual(self.record(obs), {**first, "status": "replayed"})
        self.assertEqual(self.state(exclude=()), before)  # the replay writes nothing

    def test_a_malformed_observation_is_refused_and_writes_nothing(self):
        before = self.state(exclude=())
        good = observation("9a1", "usable", "2026-09-27T10:00:05Z")
        for bad in ({**good, "capability": "config-bundle"}, {**good, "outcome": "fine"}, {**good, "probe_id": "probe_short"},
                    {**good, "started_at": "2026-09-27T10:00:06Z"}, {**good, "extra": 1}, {k: v for k, v in good.items() if k != "requested_by"},
                    {k: v for k, v in good.items() if k != "declared_expiry"}, {**good, "declared_expiry": {"access_token": None, "id_token": None}},
                    {**good, "declared_expiry": {"access_token": "2001-09-31T00:00:00Z", "id_token": None, "refresh_credential": False}},
                    {**good, "declared_expiry": {"access_token": None, "id_token": None, "refresh_credential": 1}}):
            with self.subTest(bad=bad):
                self.assertEqual(self.record(bad).get("reason"), "request_invalid")
        self.assertEqual(self.state(exclude=()), before)

    def test_status_lists_the_open_holds_of_no_topic_and_the_current_fact(self):
        failing = self.record(observation("aa1", "unusable_credential", "2026-09-27T10:00:05Z"))
        self.x("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, created_at) "
               "VALUES ('hold_topicheld01', ?, 'topic:x', 'scope', 'c', 'needs_decision', 'operator', 'operator', '2026-09-28T00:00:00Z', 'w', '2026-09-27T09:00:00Z')", rf.TOPIC)
        facts = self.router.status({})
        self.assertEqual([h["hold_id"] for h in facts["holds"]], [failing["hold"]["hold_id"]])  # not the topic's hold
        self.assertEqual(facts["holds"][0]["capability_fact_id"], failing["fact"]["fact_id"])
        self.assertFalse(facts["holds"][0]["deadline_passed"])
        self.assertEqual([(f["capability"], f["state"]) for f in facts["capability_facts"] if f["capability"] == CAP], [(CAP, "failing")])
