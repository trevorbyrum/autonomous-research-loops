"""2d-2: literal coverage oracles and isolated provenance guards; fixtures only."""
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from gen2.accounting import views as v
from gen2.core.canonical import logical_hash
from gen2.router.boundary import Refusal
from gen2.router.schemas import SchemaSet
from gen2.store import capture
from gen2.tests.ddl_fixtures import TRIGGERS, restore_triggers
from gen2.tests.router_fixtures import TOPIC, OTHER, empty_outcome, find_request
from gen2.tests.test_registry_dispositions import example_disposition
from gen2.tests.test_router_workflow import Workflow, contract
from gen2.tests.store_fixtures import StoreTestCase

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema/branch-window.schema.json"


class World(Workflow):
    def setUp(self):
        super().setUp()
        self.approved()
        self.grant = self.started("inv_window0001")
        self.ref = self.artifact(b"branch probe evidence")
        branch = example_disposition(self.ref, registry_kind="branch", registry_id="B-1", disposition="promote", contract_revision=2)
        self.assertEqual(self.record_branch(branch, self.grant, "op_branch0001")["status"], "committed")

    def record_branch(self, branch, grant, op):
        doc = {**empty_outcome(grant["invocation_id"], "interim_transition", grant["topic_id"]), "registry_dispositions": [branch]}
        return self.router.commit_outcome(self.envelope(grant, op, doc, refs=branch["evidence_refs"]))

    def record(self, **changes):
        return {"association_id": "bw-first", "registry_id": "B-1", "branch_disposition_id": "rdp_history00",
                "window_invocation_id": "inv_window0001", **changes}

    def send(self, records, grant=None):
        grant = grant or self.grant
        payload = {**empty_outcome(grant["invocation_id"], "interim_transition", grant["topic_id"]), "branch_windows": records}
        self.env = self.envelope(grant, self.ids("op_"), payload)
        return self.router.commit_outcome(self.env)

    def reject(self, record, reason="payload_invalid", grant=None):
        before = self.state()
        out = self.send([record], grant)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        self.assert_audited_state(before, 1)

    def raw(self, **changes):
        row = {**self.record(), "topic_id": TOPIC, "actor_kind": "primary", "invocation_id": "inv_window0001",
               "recorded_by_operation_id": "op_branch0001", "created_at": "2026-09-27T11:00:00Z", **changes}
        self.x(f"INSERT INTO branch_windows ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", *row.values())

    def snapshot(self, tid=TOPIC):
        return self.router.coverage_snapshot(tid, history="native")

    def other(self):
        self.to_queued(OTHER)
        grant = self.started("inv_otherwindow", tid=OTHER)
        ref = self.artifact(b"other topic's branch evidence")
        branch = example_disposition(ref, 1, registry_kind="branch", registry_id="B-1", disposition="promote")
        self.assertEqual(self.record_branch(branch, grant, "op_otherbranch")["status"], "committed")
        return grant


class AdmissionTest(World):
    def test_control(self):
        out = self.send([self.record()])
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(self.rows("SELECT registry_id, window_invocation_id, actor_kind, invocation_id, recorded_by_operation_id FROM branch_windows"),
                         [("B-1", "inv_window0001", "primary", "inv_window0001", self.env["operation_id"])])
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(self.env)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)
        request = find_request("branch-search")
        observation = {"observation_id": "obs_branch0001", "request": request, "request_identity": logical_hash(request), "attempt": 1, "lane": "crossref",
            "obligation_ids": ["O-1"], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:01Z", "coverage_state": "searched_empty",
            "result_count": 0, "completeness": "complete", "error_class": None, "capability_fact_id": None, "policy_version": "pol-1", "cost_units": None,
            "gateway_call_ref": "fixture-call", "page_outcome": "exhausted", "continuation": None}
        self.assertEqual(self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": "inv_window0001",
            "observation": observation, "retrieval_events": []})["status"], "recorded")
        self.assertEqual(self.finish(self.grant, "op_finalwindow")["status"], "committed")
        snap = self.snapshot()
        view = v.coverage_view(snap.inventory, snap.window_pins, snap.branch_links)
        self.assertEqual(snap.window_pins, (v.WindowPin("inv_window0001", 2),))
        self.assertEqual(snap.branch_links, (v.BranchLink("B-1", "inv_window0001"),))
        self.assertEqual([(b.registry_id, b.unknown_reason, len(b.windows)) for b in view.branches], [("B-1", None, 1)])
        self.assertEqual([(w.contract_revision, w.standing, w.capture.state) for w in view.windows],
                         [(None, "unknown", "indeterminate"), (2, "current", "eligible")])

    def test_branch(self):
        self.x("DROP TRIGGER branch_windows_branch")  # test Router admission independently
        self.other()
        for changes in ({"branch_disposition_id": "missing"}, {"registry_id": "B-2"}, {"branch_disposition_id": "rdp_history01"}):
            self.reject(self.record(**changes))
        contradiction = example_disposition(self.ref, 2, contract_revision=2)
        self.assertEqual(self.record_branch(contradiction, self.grant, "op_contradiction")["status"], "committed")
        self.reject(self.record(branch_disposition_id="rdp_history02", registry_id="C-1"))

    def test_window(self):
        self.x("DROP TRIGGER branch_windows_window")
        other = self.other()
        delegate = self.started("inv_delegatewin", "delegate", parent=self.grant)
        for inv in ("inv_missingwin", other["invocation_id"], delegate["invocation_id"]):
            self.reject(self.record(window_invocation_id=inv))

    def test_actor(self):
        self.x("DROP TRIGGER branch_windows_commit")
        delegate = self.started("inv_delegatewin", "delegate", parent=self.grant)
        self.reject(self.record(), "kind_not_permitted", grant=delegate)

    def test_conflict(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        self.reject(self.record())
        before = self.state()
        self.assertEqual(self.send([self.record(association_id="bw-second"), self.record()])["status"], "rejected")
        self.assert_audited_state(before, 1)

    def test_historical_pins(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        new = contract(3, 2)
        self.assertEqual(self.router.propose_amendment({"document": new})["status"], "recorded")
        self.assertEqual(self.approve(new)["status"], "applied")
        self.assertEqual(self.snapshot().window_pins, (v.WindowPin("inv_window0001", 2),))
        self.assertEqual(self.value("SELECT protocol_revision FROM contract_revisions WHERE topic_id = ? AND revision = 2", TOPIC), 1)

    def test_unknown_and_snapshot(self):
        before = self.state(exclude=())
        self.router._clock = lambda: self.fail("snapshot read a clock")
        read = capture.read
        def inside(conn, columns, topic):
            self.assertTrue(self.db.in_transaction)
            return read(conn, columns, topic)
        with patch.object(capture, "read", inside):
            snap = self.snapshot()
        self.assertFalse(self.db.in_transaction)
        branch = v.coverage_view(snap.inventory, snap.window_pins, snap.branch_links).branches[0]
        self.assertEqual((branch.links, branch.windows, branch.unknown_reason), ((), (), "branch search links not recorded"))
        other = self.snapshot(OTHER)
        self.assertEqual((other.branch_links, other.window_pins, other.inventory.passes), ((), (), ()))
        self.assertEqual(self.state(exclude=()), before)
        with self.assertRaises(ValueError):
            self.router.coverage_snapshot(TOPIC, history="invented")
        with self.assertRaises(Refusal):
            self.snapshot("topic_unknown01")

    def test_unverified_branch(self):
        catalog = self.rows(TRIGGERS)
        self.x("DROP TRIGGER branch_windows_branch")
        self.raw(registry_id="B-2")
        restore_triggers(self, "", catalog=catalog)
        self.assertEqual(self.snapshot().branch_links, ())

    def test_unverified_commit(self):
        self.other()
        catalog = self.rows(TRIGGERS)
        self.x("DROP TRIGGER branch_windows_commit")
        self.raw(recorded_by_operation_id="op_otherbranch")
        restore_triggers(self, "", catalog=catalog)
        self.assertEqual(self.snapshot().branch_links, ())

    def test_unverified_contract(self):
        self.raw()
        select = self.store.select
        def unverified(table, where=None):
            records = select(table, where)
            return [{**r, "approved_by_decision_id": None} for r in records] if table == "contract_revisions" else records
        self.store.select = unverified
        original = self.store.capture_topic
        def unverified_capture(topic):
            raw = original(topic)
            return replace(raw, tables=tuple(replace(t, rows=tuple(tuple(None if c == "approved_by_decision_id" else v
                for c, v in zip(t.columns, row)) for row in t.rows)) if t.name == "contract_revisions" else t for t in raw.tables))
        with patch.object(self.store, "capture_topic", unverified_capture):
            self.assertEqual((self.snapshot().window_pins, self.snapshot().branch_links), ((), ()))
        self.reject(self.record(association_id="bw-unverified"))

    def test_pin_kind(self):
        self.started("inv_delegatewin", "delegate", parent=self.grant)
        self.assertEqual(self.snapshot().window_pins, (v.WindowPin("inv_window0001", 2),))

    def schema(self):
        return SchemaSet(extra={"branch-window.schema.json": json.loads(SCHEMA_PATH.read_text())})

    def test_schema_control(self):
        doc = {**empty_outcome("inv_window0001", "interim_transition"), "branch_windows": [self.record()]}
        self.assertEqual(self.schema().errors(doc, "outcome-document.schema.json"), [])

    def test_forged_pins_and_attribution(self):
        for changes in ({"contract_revision": 3}, {"protocol_revision": 3}, {"eligibility_protocol_version": 2}, {"framing_version": 2},
                        {"actor_kind": "operator"}, {"invocation_id": "inv_otherwindow"}, {"recorded_by_operation_id": "op_forged0001"},
                        {"topic_id": OTHER}, {"created_at": "2026-10-10T00:00:00Z"}):
            record = self.record(**changes)
            doc = {**empty_outcome("inv_window0001", "interim_transition"), "branch_windows": [record]}
            self.assertTrue(self.schema().errors(doc, "outcome-document.schema.json"), changes)
            self.reject(record)

    def test_required_subjects(self):
        for field in self.record():
            record = {k: value for k, value in self.record().items() if k != field}
            doc = {**empty_outcome("inv_window0001", "interim_transition"), "branch_windows": [record]}
            self.assertTrue(self.schema().errors(doc, "outcome-document.schema.json"), field)

    def test_noop_control(self):
        self.assertEqual(self.send([])["status"], "committed")
        self.assertEqual(self.rows("SELECT * FROM branch_windows"), [])


class DDLTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.populate_every_table()

    def raw(self, **changes):
        row = {"association_id": "bw-next", "topic_id": TOPIC, "registry_id": "B-1", "branch_disposition_id": "rdp_branch1",
               "window_invocation_id": "inv_pppppppp", "actor_kind": "primary", "invocation_id": "inv_pppppppp",
               "recorded_by_operation_id": "op_00000001", "created_at": "2026-09-27T11:00:00Z", **changes}
        self.x(f"INSERT INTO branch_windows ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", *row.values())

    def test_control(self):
        self.raw()
        self.assertEqual(self.rows("SELECT association_id, registry_id FROM branch_windows ORDER BY association_id"), [("bw-fixture", "B-1"), ("bw-next", "B-1")])

    def test_guards(self):
        for changes in ({"registry_id": "B-2"}, {"branch_disposition_id": "rdp_fixture1"}, {"window_invocation_id": "inv_vvvvvvvv"},
                        {"invocation_id": "inv_vvvvvvvv"}, {"actor_kind": "operator"}):
            with self.subTest(changes=changes):
                self.x("SAVEPOINT guard")
                try:
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.raw(**changes)
                finally:
                    self.x("ROLLBACK TO guard")
                    self.x("RELEASE guard")
        self.raw()
        before = self.rows("SELECT * FROM branch_windows")
        for sql in ("UPDATE branch_windows SET registry_id = 'B-2'", "DELETE FROM branch_windows"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.x(sql)
            self.assertEqual(self.rows("SELECT * FROM branch_windows"), before)
