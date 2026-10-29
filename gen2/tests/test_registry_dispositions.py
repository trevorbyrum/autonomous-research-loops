"""2b2a: retained judgments, admission and append-only laws; fixtures only."""
import unittest

from gen2 import accounting as a
from gen2.tests import children
from gen2.tests.router_fixtures import TOPIC, OTHER, empty_outcome
from gen2.tests.router_fixtures import Workflow


def example_disposition(ref, index=0, **changes):
    return {"disposition_id": f"rdp_history{index:02d}", "registry_kind": "contradiction", "registry_id": "C-1",
        "subject": "Opposing estimates in the retained evidence", "disposition": "unresolved", "contract_revision": 1,
        "eligibility_protocol_version": 1, "framing_version": 1, "supersedes_id": None,
        "reason_code": "conflicting_estimates", "evidence_refs": [ref], **changes}


class RegistryTest(Workflow):
    def setUp(self):
        super().setUp()
        self.to_queued()
        self.grant = self.started("inv_registry01")
        self.ref = self.artifact(b"both estimates and branch probe")

    def record(self, index=0, **changes):
        return example_disposition(self.ref, index, **changes)

    def send(self, records, grant=None, refs=None):
        grant = grant or self.grant
        payload = {**empty_outcome(grant["invocation_id"], "interim_transition", grant["topic_id"]), "registry_dispositions": records}
        self.env = self.envelope(grant, self.ids("op_"), payload, refs=[self.ref] if refs is None else refs)
        return self.router.commit_outcome(self.env)

    def reject(self, records, reason="payload_invalid", **kwargs):
        before = self.state()
        out = self.send(records, **kwargs)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        self.assert_audited_state(before, 1)

    def test_control_histories(self):
        for index, label in enumerate(("unresolved", "resolved", "contested", "promote", "park", "drop")):
            kind = "contradiction" if index < 3 else "branch"
            self.assertEqual(self.send([self.record(index, registry_kind=kind, disposition=label)])["status"], "committed")
        self.assertEqual(self.router.commit_outcome(self.env)["status"], "replayed")
        before = self.state(exclude=())
        self.router._clock = lambda: self.fail("inventory read used a clock")
        history = self.router.evidence_inventory(TOPIC, history="native").registry_dispositions
        self.assertTrue(all(isinstance(r, a.RegistryDisposition) for r in history))
        self.assertEqual([(r.registry_kind, r.disposition) for r in history],
            [("contradiction", "unresolved"), ("contradiction", "resolved"), ("contradiction", "contested"),
             ("branch", "promote"), ("branch", "park"), ("branch", "drop")])
        self.assertEqual((history[-1].actor_kind, history[-1].invocation_id, history[-1].recorded_by_operation_id, history[-1].evidence_refs),
            ("primary", "inv_registry01", self.env["operation_id"], (a.EvidenceReference(**self.ref),)))
        self.assertEqual(self.router.evidence_inventory(OTHER, history="native").registry_dispositions, ())
        self.assertEqual(self.state(exclude=()), before)

    def test_control_reversal(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        before = self.rows("SELECT * FROM registry_dispositions")
        self.assertEqual(self.send([self.record(1, disposition="resolved", supersedes_id="rdp_history00")])["status"], "committed")
        self.assertEqual(self.rows("SELECT * FROM registry_dispositions WHERE disposition_id = 'rdp_history00'"), before)
        self.assertEqual(self.rows("SELECT disposition, supersedes_id FROM registry_dispositions ORDER BY disposition_id"),
            [("unresolved", None), ("resolved", "rdp_history00")])

    def test_actor_and_pins(self):
        self.x("DROP TRIGGER registry_dispositions_bound")  # Router authority independently of DDL
        delegate = self.started("inv_regdelegate", "delegate", parent=self.grant)
        self.reject([self.record()], "kind_not_permitted", grant=delegate)
        self.to_scoping(OTHER)
        scoping = self.started("inv_regscoping", tid=OTHER)
        self.reject([self.record()], "kind_not_permitted", grant=scoping)
        for field in ("contract_revision", "eligibility_protocol_version", "framing_version"):
            self.reject([self.record(**{field: 2})])

    def test_evidence(self):
        self.reject([self.record()], "payload_missing", refs=[])
        for changes in ({"size_bytes": 1}, {"media_type": "application/pdf"}):
            self.reject([self.record(evidence_refs=[{**self.ref, **changes}])])

    def test_schema_admission(self):
        for field in ("contract_revision", "eligibility_protocol_version", "framing_version"):
            self.reject([{k: v for k, v in self.record().items() if k != field}])
        for changes in ({"actor_kind": "operator"}, {"created_at": "2026-10-09T00:00:00Z"}, {"disposition": "park"}):
            self.reject([self.record(**changes)])

    def test_predecessor(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        self.x("DROP TRIGGER registry_dispositions_predecessor")
        self.reject([self.record(1, supersedes_id="rdp_nonexistent")])
        self.reject([self.record(1, registry_id="C-2", supersedes_id="rdp_history00")])
        self.reject([self.record(1, registry_kind="branch", disposition="park", supersedes_id="rdp_history00")])
        self.to_queued(OTHER)
        other = self.started("inv_regother01", tid=OTHER)
        self.reject([self.record(1, supersedes_id="rdp_history00")], grant=other)
        self.reject([self.record(1, supersedes_id="rdp_history02"), self.record(2)])  # no forward reference

    def test_time(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        date = self.value("SELECT created_at FROM registry_dispositions")
        self.clock.next_reads(date)
        self.reject([self.record(1, supersedes_id="rdp_history00")])

    def test_overwrite(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        self.reject([self.record(disposition="resolved")])
        self.reject([self.record(1), self.record()])  # first insertion also rolls back




class AppendLawTest(unittest.TestCase):
    def test_append_preserves_prefix(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PROPERTIES = '''
from hypothesis import given, settings, strategies as st
from gen2.tests.test_registry_dispositions import RegistryTest
@settings(max_examples=20, derandomize=True, database=None, deadline=None)
@given(st.lists(st.sampled_from(["unresolved", "resolved", "contested"]), min_size=1, max_size=8))
def retained(labels):
    fixture = RegistryTest()
    fixture.setUp()
    try:
        for index, label in enumerate(labels):
            before = fixture.rows("SELECT * FROM registry_dispositions ORDER BY disposition_id")
            record = fixture.record(index, disposition=label, supersedes_id=f"rdp_history{index-1:02d}" if index else None)
            assert fixture.send([record])["status"] == "committed"
            assert fixture.rows("SELECT * FROM registry_dispositions ORDER BY disposition_id")[:-1] == before
    finally:
        fixture.tearDown()
retained()
'''
