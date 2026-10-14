"""Isolated SQL relationship negatives and separately accepted literal controls.

Supporting rows are admitted by the original DDL, without disabling guards.
Each scenario rolls back to the same fixture, including under one-predicate
mutants. SQL proves recorded relationships, not transport authenticity.
"""
import sqlite3

from gen2.tests import test_store_acquisitions as acquisitions
from gen2.tests.store_fixtures import TOPIC, OTHER, T, h

SCENARIOS = ("source_hash", "source_topic", "source_work", "source_version",
    "artifact_join", "event_join", "link_join", "observation_join", "event_work",
    "observation_id", "media", "verifier_id", "verifier_topic",
    "attempt_upper", "source_fk", "topic")


class RelationshipTest(acquisitions.DDLTest):
    def artifact(self, *, size=10, media="application/json"):
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, topic_id, staged_at) VALUES (?, ?, ?, ?, ?)", h("e"), size, media, TOPIC, T)
        self.x("INSERT INTO artifact_topics VALUES (?, ?, 'inv_pppppppp', ?)", h("e"), TOPIC, T)

    def source(self, *, topic=TOPIC, work="wrk_00000001", version="v3", digest=None,
            invocation="inv_pppppppp", operation="op_00000001"):
        self.x("INSERT INTO source_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)", topic, work, version, digest or h("e"), invocation, operation, T)

    def observation(self, *, topic=TOPIC, invocation="inv_pppppppp", attempt=2):
        self.x("""INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt,
            lane, request, obligation_ids, started_at, ended_at, coverage_state, result_count, completeness,
            error_class, capability_fact_id, policy_version, cost_units, gateway_call_ref, page_outcome, continuation)
            SELECT 'o2', ?, ?, request_identity, ?, lane, request, obligation_ids, started_at, ended_at, coverage_state,
            result_count, completeness, error_class, capability_fact_id, policy_version, cost_units, gateway_call_ref,
            page_outcome, continuation FROM search_observations WHERE observation_id = 'o1'""", invocation, topic, attempt)

    def event(self, *, observation="o1", topic=TOPIC, work="wrk_00000001"):
        self.x("INSERT INTO retrieval_events VALUES ('e2', ?, ?, 'rec-2', 1, ?)", observation, topic, T)
        self.x("INSERT INTO record_work_links VALUES ('e2', ?, 'dedup-1', ?)", work, T)

    def other_work(self):
        self.x("INSERT INTO works VALUES ('wrk_other001', 'doi', '10.1/other', NULL, ?)", T)
        self.event(work="wrk_other001")
        self.source(work="wrk_other001", version="v2", digest=h("7"))

    def other_topic(self):
        self.lease("lease_other001", 99, tid=OTHER, scope="checkpoint")
        self.invocation("inv_other001", kind="checkpoint", lease="lease_other001", tid=OTHER)
        self.receipt("op_other001", "inv_other001", lease="lease_other001", gen=99, tid=OTHER, before=1)
        self.observation(topic=OTHER, invocation="inv_other001")
        self.event(observation="o2", topic=OTHER)
        self.x("INSERT INTO artifact_topics VALUES (?, ?, 'inv_other001', ?)", h("7"), OTHER, T)
        self.source(topic=OTHER, version="v2", digest=h("7"), invocation="inv_other001", operation="op_other001")
        self.lease("lease_other002", 100, tid=OTHER, scope="verification")
        self.invocation("inv_other002", kind="verification", lease="lease_other002", tid=OTHER)

    def scenario(self, name):
        """Return one invalid acquisition and one fully valid acquisition."""
        if name == "source_hash":
            self.artifact()
            self.source()
            return {"content_hash": h("e")}, {"source_version": "v3", "content_hash": h("e")}
        if name == "source_topic":
            self.other_topic()
            self.artifact()
            self.x("INSERT INTO artifact_topics VALUES (?, ?, 'inv_other001', ?)", h("e"), OTHER, T)
            self.source(topic=OTHER, version="v3", invocation="inv_other001", operation="op_other001")
            self.source(version="v3", digest=h("7"))
            return {"source_version": "v3", "content_hash": h("e")}, {}
        if name == "source_work":
            self.other_work()
            self.artifact()
            self.source(work="wrk_other001", version="v3")
            self.source(version="v3", digest=h("7"))
            return {"source_version": "v3", "content_hash": h("e")}, {"work_id": "wrk_other001", "source_version": "v3", "content_hash": h("e"), "event_id": "e2", "provider_record_id": "rec-2"}
        if name == "source_version":
            self.artifact()
            self.source()
            return {"content_hash": h("e")}, {"source_version": "v3", "content_hash": h("e")}
        if name == "artifact_join":
            self.artifact(size=11)
            self.source()
            return {"response_bytes": b'{}         '}, {"source_version": "v3", "content_hash": h("e"), "response_bytes": b'{}         '}
        if name == "event_join":
            self.event()
            return {"provider_record_id": "rec-2"}, {"event_id": "e2", "provider_record_id": "rec-2"}
        if name in ("link_join", "event_work"):
            self.other_work()
            return {"work_id": "wrk_other001"}, {"work_id": "wrk_other001", "event_id": "e2", "provider_record_id": "rec-2"}
        if name in ("observation_join", "observation_id"):
            self.observation()
            self.event(observation="o2")
            negative = {"observation_id": "o2"}
            if name == "observation_join":
                negative["attempt"] = 2
            return negative, {"event_id": "e2", "provider_record_id": "rec-2", "observation_id": "o2", "attempt": 2}
        if name == "media":
            self.artifact(media="text/plain")
            self.source()
            return {"source_version": "v3", "content_hash": h("e")}, {}
        if name == "verifier_id":
            return {"verifier_invocation_id": "inv_pppppppp"}, {}
        if name == "verifier_topic":
            self.lease("lease_other001", 99, tid=OTHER, scope="verification")
            self.invocation("inv_other001", kind="verification", lease="lease_other001", tid=OTHER)
            return {"verifier_invocation_id": "inv_other001"}, {}
        if name == "attempt_upper":
            self.observation(attempt=9007199254740992)
            self.event(observation="o2")
            return {"event_id": "e2", "provider_record_id": "rec-2", "observation_id": "o2", "attempt": 9007199254740992}, {}
        if name == "source_fk":
            return {"source_version": "absent"}, {}
        if name == "topic":
            self.other_topic()
            return {"event_id": "e2", "provider_record_id": "rec-2", "observation_id": "o2", "attempt": 2, "acquired_by_invocation_id": "inv_other001"}, {"topic_id": OTHER, "event_id": "e2", "provider_record_id": "rec-2", "observation_id": "o2", "attempt": 2, "acquired_by_invocation_id": "inv_other001", "verifier_invocation_id": "inv_other002"}
        raise AssertionError(name)

    def test_natural_key(self):
        self.raw()
        before = self.rows("SELECT * FROM source_acquisitions")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "UNIQUE constraint"):
            self.raw(admitted_at="2026-09-28T00:00:00Z")
        self.assertEqual(self.rows("SELECT * FROM source_acquisitions"), before)

    def test_relationships(self):
        for name in SCENARIOS:
            with self.subTest(relationship=name):
                self.x("SAVEPOINT relationship")
                try:
                    negative, _ = self.scenario(name)
                    self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
                    before = self.rows("SELECT * FROM source_acquisitions")
                    message = "CHECK constraint" if name == "attempt_upper" else "contract-admitted verifier" if name.startswith("verifier_") else "acquisition must bind"
                    with self.assertRaisesRegex(sqlite3.IntegrityError, message):
                        self.raw(**negative)
                    self.assertEqual(self.rows("SELECT * FROM source_acquisitions"), before)
                finally:
                    self.x("ROLLBACK TO relationship")
                    self.x("RELEASE relationship")

    def test_relationship_controls(self):
        for name in SCENARIOS:
            with self.subTest(relationship=name):
                self.x("SAVEPOINT relationship")
                try:
                    _, control = self.scenario(name)
                    self.raw(**control)
                    self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
                    self.assertEqual(self.rows("SELECT topic_id, work_id, source_version, content_hash, event_id, observation_id, verifier_invocation_id, response_bytes FROM source_acquisitions WHERE source_version != 'v1'"),
                        [(control.get("topic_id", TOPIC), control.get("work_id", "wrk_00000001"), control.get("source_version", "v2"), control.get("content_hash", h("7")), control.get("event_id", "e1"), control.get("observation_id", "o1"), control.get("verifier_invocation_id", "inv_vvvvvvvv"), control.get("response_bytes", b'{}        '))])
                finally:
                    self.x("ROLLBACK TO relationship")
                    self.x("RELEASE relationship")
