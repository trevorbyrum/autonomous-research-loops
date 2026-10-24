"""2c-2a: hand-specified Router admission, retained lineage and label oracles.

Only in-memory databases and fake invocations; no judgment/provider production.
SQL readbacks are independent of the accounting adapter. Current dispositions,
G-1 semantic reuse and accrual are the later 2c-2b slice.
"""
import json
import sqlite3
import unittest
from fractions import Fraction
from pathlib import Path

from gen2 import accounting as a
from gen2.router.schemas import SchemaSet
from gen2.tests import children
from gen2.tests.router_fixtures import TOPIC, OTHER, empty_outcome
from gen2.tests.store_fixtures import StoreTestCase
from gen2.tests.test_router_workflow import Workflow

OUTCOME_SCHEMA = Path(__file__).resolve().parents[1] / "schema/outcome-document.schema.json"


class LifecycleSchemaTest(unittest.TestCase):
    RECORD = {"disposition_id": "sld_history00", "work_id": "wrk_00000001", "source_version": "v1", "contract_revision": 1,
        "eligibility_protocol_version": 1, "framing_version": 1, "action": "add", "related_work_id": None,
        "related_source_version": None, "supersedes_id": None, "reason_code": "new_source",
        "evidence_refs": [{"content_hash": "sha256:" + "a" * 64, "size_bytes": 10, "media_type": "application/json"}]}

    def errors(self, record):
        return SchemaSet(extra={"outcome-document.schema.json": json.loads(OUTCOME_SCHEMA.read_text())}).errors(record, "outcome-document.schema.json#/$defs/source_disposition")

    def test_control(self):
        self.assertEqual(self.errors(self.RECORD), [])
        self.assertEqual(self.errors({**self.RECORD, "action": "supersede", "related_work_id": "wrk_00000001", "related_source_version": "v2"}), [])

    def test_required_and_attribution_guards(self):
        for field in self.RECORD:
            self.assertTrue(self.errors({k: v for k, v in self.RECORD.items() if k != field}), field)
        for changes in ({"actor_kind": "operator"}, {"created_at": "2026-10-09T00:00:00Z"}, {"action": "invalid"}, {"action": "supersede"}, {"evidence_refs": []}):
            self.assertTrue(self.errors({**self.RECORD, **changes}), changes)


class SemanticTest(Workflow):
    def setUp(self):
        super().setUp()
        self.to_queued()
        self.grant = self.started("inv_semantic01")
        events = self.observe(self.grant, "obs_semantic01", ("A", "A-copy", "B"))
        out = self.register(self.grant, [("doi", "10.1/A", events[:2]), ("doi", "10.1/B", events[2:])])
        self.assertEqual(out["status"], "recorded", out)
        self.works = [w[0] for w in self.rows("SELECT work_id FROM works ORDER BY identity_value")]
        self.ref = self.artifact(b"retained source evidence")

    def record(self, index=0, **changes):
        return {"assessment_id": f"asm_semantic{index:02d}", "work_id": self.works[index % 2], "source_version": "v1",
            "contract_revision": 1, "eligibility_protocol_version": 1, "framing_version": 1, "novelty": "novel" if index == 0 else "not_novel",
            "independence": "shared_origin", "applicability": "applicable", "contribution": "answer", "evidence_refs": [self.ref],
            "lineage": {"relation": "shared_study_origin", "study_origin_id": "study-1", "related_work_id": None, "related_source_version": None}, **changes}

    def send(self, records, grant=None, refs=None):
        grant = grant or self.grant
        outcome = {**empty_outcome(grant["invocation_id"], "interim_transition", grant["topic_id"]), "semantic_assessments": records}
        self.env = self.envelope(grant, self.ids("op_"), outcome, refs=[self.ref] if refs is None else refs)
        return self.router.commit_outcome(self.env)

    def reject(self, records, reason="payload_invalid", **kwargs):
        before = self.state()
        out = self.send(records, **kwargs)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        self.assert_audited_state(before, 1)

    def test_control_records_labels_and_shared_origin(self):
        out = self.send([self.record(), self.record(1)])
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(self.rows("SELECT novelty, actor_kind, invocation_id, contract_revision, framing_version FROM semantic_assessments ORDER BY assessment_id"),
            [("novel", "primary", "inv_semantic01", 1, 1), ("not_novel", "primary", "inv_semantic01", 1, 1)])
        self.assertEqual(self.rows("SELECT study_origin_id FROM source_lineage ORDER BY assessment_id"), [("study-1",), ("study-1",)])
        self.assertEqual(self.router.commit_outcome(self.env)["status"], "replayed")
        before = self.state(exclude=())
        self.router._clock = lambda: self.fail("inventory read used a clock")
        inv = self.router.evidence_inventory(TOPIC, history="native")
        self.assertEqual(a.candidate_units(inv).deduplicated_works.value, 2)
        self.assertEqual(a.candidate_units(inv).assessed_candidates.value, 0)  # semantics do not screen candidates
        self.assertEqual(a.novelty(a.Count(frozenset(self.works)), a.novelty_judgments(inv.semantic_assessments)), Fraction(1, 2))
        self.assertEqual(inv.semantic_assessments[0].evidence_refs, (a.EvidenceReference(**self.ref),))
        self.assertEqual({r.recorded_by_operation_id for r in inv.semantic_assessments}, {self.env["operation_id"]})
        self.assertEqual(len(inv.source_lineage), 2)
        self.assertEqual(self.router.evidence_inventory(OTHER, history="native").source_lineage, ())
        self.assertEqual(self.state(exclude=()), before)

    def test_unauthorized_actor(self):
        delegate = self.started("inv_semdelegate", "delegate", parent=self.grant)
        self.reject([self.record()], "kind_not_permitted", grant=delegate)
        self.reject([{**self.record(), "actor_kind": "operator"}])

    def test_precontract_actor(self):
        self.to_scoping(OTHER)
        grant = self.started("inv_semscoping", tid=OTHER)
        self.reject([self.record()], "kind_not_permitted", grant=grant)

    def test_missing_revision_and_framing(self):
        for field in ("source_version", "contract_revision", "eligibility_protocol_version", "framing_version"):
            with self.subTest(field=field):
                record = self.record()
                del record[field]
                self.reject([record])

    def test_wrong_pins(self):
        self.x("DROP TRIGGER semantic_assessments_bound")  # isolate Router admission from the DDL's mirror
        for field in ("contract_revision", "eligibility_protocol_version", "framing_version"):
            with self.subTest(field=field):
                self.reject([self.record(**{field: 2})])

    def test_subject_and_related_topic(self):
        self.to_queued(OTHER)
        other = self.started("inv_semother01", tid=OTHER)
        events = self.observe(other, "obs_semother01", ("C",))
        out = self.register(other, [("doi", "10.1/C", events)])
        wid = out["works"][0]["work_id"]
        self.reject([self.record(work_id=wid)], "cross_topic")
        self.reject([self.record(lineage={"relation": "version_of", "study_origin_id": None, "related_work_id": wid, "related_source_version": "v2"})], "cross_topic")

    def test_evidence_binding(self):
        self.reject([self.record()], "payload_missing", refs=[])
        self.reject([self.record(evidence_refs=[{**self.ref, "size_bytes": 1}])])
        self.reject([self.record(evidence_refs=[{**self.ref, "media_type": "application/pdf"}])])

    def test_overwrite(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        self.reject([self.record(novelty="not_novel")])
        self.reject([self.record(1), self.record()])  # first insert rolls back on conflict

    def test_version_and_acquisition_lineage_control(self):
        for index, relation in enumerate(("version_of", "derived_from")):
            out = self.send([self.record(index, lineage={"relation": relation, "study_origin_id": None,
                "related_work_id": self.works[1], "related_source_version": "published-2"})])
            self.assertEqual(out["status"], "committed", out)
        self.assertEqual(self.rows("SELECT relation, related_source_version FROM source_lineage ORDER BY assessment_id"),
            [("version_of", "published-2"), ("derived_from", "published-2")])

    def test_unknown_missing_and_duplicate_labels(self):
        self.assertEqual(self.send([self.record(novelty="unknown"), self.record(1)])["status"], "committed")
        records = self.router.evidence_inventory(TOPIC, history="native").semantic_assessments
        count = a.Count(frozenset(self.works))
        self.assertIsNone(a.novelty(count, a.novelty_judgments(records)))
        self.assertIsNone(a.novelty(count, a.novelty_judgments(records[1:])))
        self.assertIsNone(a.novelty(count, a.novelty_judgments((records[1], records[1]))))

    def test_append_keeps_earlier_dated_records(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        before = self.rows("SELECT * FROM semantic_assessments")
        date = self.value("SELECT created_at FROM semantic_assessments")
        self.assertEqual(self.send([self.record(2, novelty="not_novel")])["status"], "committed")
        self.assertEqual(self.rows("SELECT * FROM semantic_assessments WHERE created_at <= ?", date), before)

    def test_schema_control(self):
        schemas = SchemaSet(extra={"outcome-document.schema.json": json.loads(OUTCOME_SCHEMA.read_text())})
        self.assertEqual(schemas.errors(self.record(), "outcome-document.schema.json#/$defs/semantic_assessment"), [])

    def test_schema_guards(self):
        schemas = SchemaSet(extra={"outcome-document.schema.json": json.loads(OUTCOME_SCHEMA.read_text())})
        target = "outcome-document.schema.json#/$defs/semantic_assessment"
        self.assertEqual(schemas.errors(self.record(), target), [])
        for field in ("source_version", "contract_revision", "eligibility_protocol_version", "framing_version", "novelty"):
            record = self.record()
            del record[field]
            self.assertTrue(schemas.errors(record, target), field)
        self.assertTrue(schemas.errors(self.record(actor_kind="operator"), target))
        self.assertTrue(schemas.errors(self.record(lineage={"relation": "shared_study_origin", "study_origin_id": None,
            "related_work_id": self.works[1], "related_source_version": "v1"}), target))

    def test_label_laws(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PROPERTIES = '''
from dataclasses import replace
from fractions import Fraction
from hypothesis import given, settings, strategies as st
from gen2 import accounting as a
@settings(max_examples=40, derandomize=True, database=None)
@given(st.lists(st.sampled_from(["novel", "not_novel"]), min_size=1, max_size=20))
def labels_law(labels):
    template = a.SemanticAssessment("asm", "work", "v1", 1, 1, 1, "novel", "unknown", "unknown", "unknown", (), "primary", "inv", "op", "date")
    records = tuple(replace(template, work_id=str(i), novelty=label) for i, label in enumerate(labels))
    count = a.Count(frozenset(str(i) for i in range(len(labels))))
    judgments = a.novelty_judgments(records)
    assert a.novelty(count, judgments) == Fraction(labels.count("novel"), len(labels))
    assert a.novelty(count, judgments[::-1]) == a.novelty(count, judgments)
    assert a.novelty(count, judgments + judgments[:1]) is None
    assert a.novelty(count, a.novelty_judgments((replace(records[0], novelty="unknown"), *records[1:]))) is None
labels_law()
'''


class RegistrySchemaTest(unittest.TestCase):
    def schemas(self):
        return SchemaSet(extra={"outcome-document.schema.json": json.loads(OUTCOME_SCHEMA.read_text())})

    def record(self, **changes):
        from gen2.tests.test_registry_dispositions import example_disposition
        return example_disposition({"content_hash": "sha256:" + "7" * 64, "size_bytes": 10, "media_type": "application/json"}, **changes)

    def test_control(self):
        for kind, label in (("contradiction", "unresolved"), ("branch", "park")):
            self.assertEqual(self.schemas().errors(self.record(registry_kind=kind, disposition=label), "outcome-document.schema.json#/$defs/registry_disposition"), [])

    def test_guards(self):
        target = "outcome-document.schema.json#/$defs/registry_disposition"
        record = self.record()
        for field in record:
            with self.subTest(field=field):
                self.assertTrue(self.schemas().errors({k: v for k, v in record.items() if k != field}, target))
        for changes in ({"actor_kind": "operator"}, {"created_at": "2026-10-09T00:00:00Z"}, {"registry_kind": "invalid"},
                        {"registry_kind": "invalid", "disposition": "park"}, {"disposition": "invalid"},
                        {"disposition": "park"}, {"registry_kind": "branch"}, {"evidence_refs": []}):
            self.assertTrue(self.schemas().errors(self.record(**changes), target), changes)


class SemanticDDLTest(StoreTestCase):
    """Raw DDL fixture, so mutants exercise guards without the opening identity gate."""
    def setUp(self):
        super().setUp()
        self.populate_every_table()

    def append(self, **changes):
        columns = [r[1] for r in self.rows("PRAGMA table_info(semantic_assessments)")]
        row = dict(zip(columns, self.rows("SELECT * FROM semantic_assessments WHERE assessment_id = 'sem1'")[0]))
        row.update(assessment_id="sem2", **changes)
        self.x(f"INSERT INTO semantic_assessments ({','.join(columns)}) VALUES ({','.join('?' for c in columns)})", *row.values())

    def test_control_insert(self):
        self.append(novelty="novel")
        self.assertEqual(self.rows("SELECT assessment_id, novelty FROM semantic_assessments ORDER BY assessment_id"), [("sem1", "unknown"), ("sem2", "novel")])

    def test_update_guard(self):
        for table in ("semantic_assessments", "source_lineage"):
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                self.x(f"UPDATE {table} SET assessment_id = assessment_id")

    def test_binding_guard(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.append(framing_version=2)

    def test_actor_and_label_guards(self):
        for field in ("actor_kind", "novelty", "independence", "applicability", "contribution"):
            with self.subTest(field=field), self.assertRaises(sqlite3.IntegrityError):
                self.append(**{field: "unauthorized"})

    def test_lineage_shape_guard(self):
        self.append()
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("INSERT INTO source_lineage VALUES ('sem2', 'shared_study_origin', NULL, NULL, NULL)")

    def test_delete_guard(self):
        self.append()  # sem2 has no dependents: no foreign key can mask its guard
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("DELETE FROM semantic_assessments WHERE assessment_id = 'sem2'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("DELETE FROM source_lineage")
