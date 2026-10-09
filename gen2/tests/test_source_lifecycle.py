"""2c-2b1: hand-written dated histories and admission/DDL guards; no providers."""
import sqlite3
import unittest
from dataclasses import replace

from gen2 import accounting as a
from gen2.tests import children
from gen2.tests.router_fixtures import TOPIC, OTHER, empty_outcome
from gen2.tests.store_fixtures import StoreTestCase
from gen2.tests.test_router_workflow import Workflow


class LifecycleTest(Workflow):
    def setUp(self):
        super().setUp()
        self.to_queued()
        self.grant = self.started("inv_lifecycle1")
        events = self.observe(self.grant, "obs_lifecycle1", ("A", "B"))
        out = self.register(self.grant, [("doi", "10.1/A", events[:1]), ("doi", "10.1/B", events[1:])])
        self.works = [w["work_id"] for w in out["works"]]
        self.ref = self.artifact(b"lifecycle evidence")

    def record(self, index=0, **changes):
        return {"disposition_id": f"sld_history{index:02d}", "work_id": self.works[0], "source_version": "v1", "contract_revision": 1,
            "eligibility_protocol_version": 1, "framing_version": 1, "action": "add", "related_work_id": None,
            "related_source_version": None, "supersedes_id": None, "reason_code": "new_source", "evidence_refs": [self.ref], **changes}

    def send(self, records, grant=None, refs=None):
        grant = grant or self.grant
        payload = {**empty_outcome(grant["invocation_id"], "interim_transition", grant["topic_id"]), "source_lifecycle": records}
        self.env = self.envelope(grant, self.ids("op_"), payload, refs=[self.ref] if refs is None else refs)
        return self.router.commit_outcome(self.env)

    def reject(self, records, reason="payload_invalid", **kwargs):
        before = self.state()
        out = self.send(records, **kwargs)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        self.assertEqual(self.state(), before)

    def test_control_supersede_then_reversal(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        first = self.router.evidence_inventory(TOPIC, history="native").source_lifecycle[0]
        self.assertEqual(self.send([self.record(1, action="supersede", related_work_id=self.works[1], related_source_version="v2", supersedes_id=first.disposition_id)])["status"], "committed")
        second_date = self.value("SELECT created_at FROM source_lifecycle WHERE disposition_id = 'sld_history01'")
        self.assertEqual(self.send([self.record(2, action="keep", supersedes_id="sld_history01", reason_code="reversal")])["status"], "committed")
        operation = self.env["operation_id"]
        self.assertEqual(self.router.commit_outcome(self.env)["status"], "replayed")
        before = self.state(exclude=())
        self.router._clock = lambda: self.fail("inventory read consulted the clock")
        history = self.router.evidence_inventory(TOPIC, history="native").source_lifecycle
        self.assertEqual([(r.disposition_id, r.action) for r in a.lifecycle_view(history, first.created_at)], [("sld_history00", "add")])
        self.assertEqual([(r.disposition_id, r.action, r.related_work_id) for r in a.lifecycle_view(history, second_date)], [("sld_history01", "supersede", self.works[1])])
        self.assertEqual([(r.disposition_id, r.action) for r in a.lifecycle_view(history, history[-1].created_at)], [("sld_history02", "keep")])
        self.assertEqual((history[-1].actor_kind, history[-1].invocation_id, history[-1].recorded_by_operation_id, history[-1].evidence_refs),
            ("primary", "inv_lifecycle1", operation, (a.EvidenceReference(**self.ref),)))
        self.assertEqual(self.rows("SELECT action FROM source_lifecycle ORDER BY disposition_id"), [("add",), ("supersede",), ("keep",)])
        self.assertEqual(self.router.evidence_inventory(OTHER, history="native").source_lifecycle, ())
        self.assertEqual(self.state(exclude=()), before)

    def test_control_actions_and_disagreement(self):
        for index, action in enumerate(("add", "keep", "supersede", "coexist", "quarantine", "duplicate-report")):
            related = {"related_work_id": self.works[1], "related_source_version": "v2"} if action in ("supersede", "coexist", "duplicate-report") else {}
            self.assertEqual(self.send([self.record(index, action=action, **related)])["status"], "committed")
        history = self.router.evidence_inventory(TOPIC, history="native").source_lifecycle
        self.assertEqual([r.action for r in a.lifecycle_view(history, history[-1].created_at)], ["add", "keep", "supersede", "coexist", "quarantine", "duplicate-report"])

    def test_actor_and_pins(self):
        self.x("DROP TRIGGER source_lifecycle_bound")  # prove Router guards independently
        delegate = self.started("inv_lifedelegate", "delegate", parent=self.grant)
        self.reject([self.record()], "kind_not_permitted", grant=delegate)
        for field in ("contract_revision", "eligibility_protocol_version", "framing_version"):
            self.reject([self.record(**{field: 2})])

    def test_schema_admission(self):
        for field in ("source_version", "contract_revision", "eligibility_protocol_version", "framing_version"):
            self.reject([{k: v for k, v in self.record().items() if k != field}])
        for changes in ({"actor_kind": "operator"}, {"created_at": "2026-10-09T00:00:00Z"}, {"action": "supersede"}, {"action": "invalid"}):
            self.reject([self.record(**changes)])

    def test_topic_and_evidence(self):
        self.to_queued(OTHER)
        other = self.started("inv_lifeother1", tid=OTHER)
        events = self.observe(other, "obs_lifeother1", ("C",))
        wid = self.register(other, [("doi", "10.1/C", events)])["works"][0]["work_id"]
        self.reject([self.record(work_id=wid)], "cross_topic")
        self.reject([self.record(action="coexist", related_work_id=wid, related_source_version="v1")], "cross_topic")
        self.reject([self.record()], "payload_missing", refs=[])
        self.reject([self.record(evidence_refs=[{**self.ref, "size_bytes": 1}])])
        self.reject([self.record(evidence_refs=[{**self.ref, "media_type": "application/pdf"}])])

    def test_predecessor_and_time(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        self.x("DROP TRIGGER source_lifecycle_predecessor")
        self.reject([self.record(1, supersedes_id="sld_nonexistent")])
        self.reject([self.record(1, supersedes_id="sld_history00", work_id=self.works[1])])
        self.reject([self.record(1, supersedes_id="sld_history00", source_version="v2")])
        date = self.value("SELECT created_at FROM source_lifecycle")
        self.clock.next_reads(date)
        self.reject([self.record(1, supersedes_id="sld_history00")])

    def test_overwrite(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        self.reject([self.record(action="quarantine")])
        self.reject([self.record(1), self.record()])  # rollback first insertion too


TEMPLATE = a.SourceDisposition("sld_first001", "wrk_00000001", "v1", 1, 1, 1, "add", None, None, None, "new_source", (), "primary", "inv", "op", "2026-10-09T00:00:00Z")


class DatedViewTest(unittest.TestCase):
    def test_control_current(self):
        self.assertEqual(a.lifecycle_view((TEMPLATE,), "2026-10-09T00:00:00Z"), (TEMPLATE,))
        self.assertEqual(a.lifecycle_view((), "2026-10-09T00:00:00Z"), ())

    def test_dated_and_explicit_replacement(self):
        later = replace(TEMPLATE, disposition_id="sld_later001", action="quarantine", created_at="2026-10-09T00:00:00.1Z", supersedes_id=TEMPLATE.disposition_id)
        self.assertEqual(a.lifecycle_view((TEMPLATE, later), "2026-10-09T00:00:00Z"), (TEMPLATE,))
        self.assertEqual(a.lifecycle_view((later, TEMPLATE), later.created_at), (later,))
        disagreement = replace(later, supersedes_id=None)
        self.assertEqual(a.lifecycle_view((disagreement, TEMPLATE), later.created_at), (TEMPLATE, disagreement))

    def test_later_append_property(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PROPERTIES = '''
from dataclasses import replace
from hypothesis import given, settings, strategies as st
from gen2 import accounting as a
from gen2.tests.test_source_lifecycle import TEMPLATE
@settings(max_examples=50, derandomize=True, database=None)
@given(st.lists(st.sampled_from(["add", "keep", "quarantine"]), min_size=1, max_size=12), st.integers(1, 999999999))
def dated(actions, fraction):
    history = tuple(replace(TEMPLATE, disposition_id=f"sld_{i:08d}", action=action) for i, action in enumerate(actions))
    after = replace(TEMPLATE, disposition_id="sld_future01", supersedes_id=history[0].disposition_id,
                    created_at=f"2026-10-09T00:00:00.{fraction:09d}Z")
    assert a.lifecycle_view(history + (after,), TEMPLATE.created_at) == a.lifecycle_view(history, TEMPLATE.created_at)
dated()
'''


class LifecycleDDLTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.populate_every_table()

    def append(self, **changes):
        columns = [r[1] for r in self.rows("PRAGMA table_info(source_lifecycle)")]
        row = dict(zip(columns, self.rows("SELECT * FROM source_lifecycle")[0]))
        row.update(disposition_id="sld_fixture2", **changes)
        self.x(f"INSERT INTO source_lifecycle ({','.join(columns)}) VALUES ({','.join('?' for c in columns)})", *row.values())

    def test_control_insert(self):
        self.append(action="keep", supersedes_id="sld_fixture1")
        self.assertEqual(self.rows("SELECT action FROM source_lifecycle ORDER BY disposition_id"), [("add",), ("keep",)])

    def test_binding_and_predecessor_guards(self):
        for changes in ({"framing_version": 2}, {"source_version": "v2", "supersedes_id": "sld_fixture1"}):
            with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError):
                self.append(**changes)

    def test_update_and_delete_guards(self):
        for sql in ("UPDATE source_lifecycle SET action = 'keep'", "DELETE FROM source_lifecycle"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.x(sql)

    def test_shape_guards(self):
        for changes in ({"action": "invalid"}, {"actor_kind": "operator"}, {"reason_code": ""}, {"source_version": ""}, {"evidence_refs": "[]"}, {"action": "coexist"}):
            with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError):
                self.append(**changes)
