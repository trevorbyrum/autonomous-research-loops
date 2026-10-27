"""Raw integrity guards for obligation admission; in-memory fixtures only."""
import json
import sqlite3

from gen2.tests.router_fixtures import TOPIC, OTHER
from gen2.tests.store_fixtures import StoreTestCase, facet, obligation
from gen2.tests.test_confidence_contract import SCHEME


class DDLTest(StoreTestCase):
    """Raw DDL fixtures, independent of the Store's schema-identity gate."""
    @staticmethod
    def contract_row(*args, **kwargs):
        row = list(StoreTestCase.contract_row(*args, **kwargs))
        doc = json.loads(row[4])
        doc["confidence_scheme"] = SCHEME
        row[4] = json.dumps(doc)
        return tuple(row)

    def approved_with_obligation(self, tid=TOPIC, kind="contract_approval"):
        n = self.rows("SELECT max(revision) + 1 FROM contract_revisions WHERE topic_id = ?", tid)[0][0]
        did = f"opd_obl_ratings{n}"
        rated = {"band": "critical", "score": 8, "decision": did}
        entries = {"facets": (facet("F-1", **rated),), "obligations": tuple(obligation(o, ("F-1",), **rated) for o in ("O-1", "O-2"))}
        self.rate(did, tid, **entries)
        self.contract_with_rows(tid, n + 1, **entries, content_hash=self.chash(tid, n + 1))
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND status = 'approved'", tid)
        self.approve_contract(tid, n + 1, kind=kind)
        return n + 1

    def setUp(self):
        super().setUp()
        self.populate_every_table()

    def test_control(self):
        self.x("INSERT INTO obligation_assessments SELECT 'oa-control', topic_id, obligation_id, subject, contract_revision, contract_content_hash, eligibility_protocol_version, framing_version, "
            "disposition, state, confidence, evidence_refs, actor_kind, invocation_id, recorded_by_operation_id, created_at, reason, 'oa-fixture' FROM obligation_assessments WHERE record_id = 'oa-fixture'")
        self.assertEqual(self.rows("SELECT record_id FROM obligation_assessments ORDER BY record_id"), [("oa-control",), ("oa-fixture",)])

    def categorical_row(self):
        columns = [r[1] for r in self.rows("PRAGMA table_info(obligation_assessments)")]
        row = dict(zip(columns, self.rows("SELECT * FROM obligation_assessments WHERE record_id = 'oa-fixture'")[0]))
        row.update(record_id="oa-categorical", confidence=json.dumps({"basis": "recorded_assessment",
            "scheme": {"scheme_id": "plan-corroboration", "version": 1}, "label": "corroborated",
            "assessed_by_invocation_id": "inv_pppppppp"}))
        return row

    def insert_row(self, row):
        self.x(f"INSERT INTO obligation_assessments ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", *row.values())

    def test_categorical_control(self):
        row = self.categorical_row()
        self.insert_row(row)
        self.assertEqual(json.loads(self.rows("SELECT confidence FROM obligation_assessments WHERE record_id = 'oa-categorical'")[0][0]),
            {"basis": "recorded_assessment", "scheme": {"scheme_id": "plan-corroboration", "version": 1},
             "label": "corroborated", "assessed_by_invocation_id": "inv_pppppppp"})

    def test_categorical_one_field_refusals(self):
        row = self.categorical_row()
        self.insert_row(row)
        before = self.rows("SELECT * FROM obligation_assessments ORDER BY record_id")
        confidence = json.loads(row["confidence"])
        for changes in ({"label": "off-scheme"}, {"scheme": {"scheme_id": "foreign", "version": 1}},
                        {"scheme": {"scheme_id": "plan-corroboration", "version": 2}},
                        {"assessed_by_invocation_id": "inv_vvvvvvvv"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, "confidence must name"):
                self.insert_row({**row, "record_id": "oa-invalid", "confidence": json.dumps({**confidence, **changes})})
            self.assertEqual(self.rows("SELECT * FROM obligation_assessments ORDER BY record_id"), before)

    def raw_approval_admission(self, kind):
        revision = self.approved_with_obligation(kind=kind)
        generation = self.rows("SELECT max(generation) + 1 FROM leases WHERE topic_id = ?", TOPIC)[0][0]
        self.lease("lease_approved_new", generation, scope="checkpoint")
        self.invocation("inv_approved_new", kind="checkpoint", lease="lease_approved_new", contract_rev=revision)
        self.to_running("inv_approved_new")
        before = self.rows("SELECT max(state_revision_after) FROM operation_receipts WHERE topic_id = ?", TOPIC)[0][0]
        self.receipt("op_approved_new", "inv_approved_new", lease="lease_approved_new", gen=generation, before=before)
        row = self.categorical_row()
        confidence = json.loads(row["confidence"])
        row.update(contract_revision=revision, contract_content_hash=self.content_hash_of(TOPIC, revision),
            invocation_id="inv_approved_new", recorded_by_operation_id="op_approved_new",
            confidence=json.dumps({**confidence, "assessed_by_invocation_id": "inv_approved_new"}))
        self.insert_row(row)
        self.assertEqual(self.rows("SELECT contract_revision, invocation_id FROM obligation_assessments WHERE record_id = 'oa-categorical'"),
            [(revision, "inv_approved_new")])

    def test_raw_amendment_admission(self):
        self.raw_approval_admission("amendment_approval")

    def test_raw_reframe_admission(self):
        # Raw DDL checks authority binding; the Router control
        # test_obligation_admission.py::AdmissionTest.test_reframe_approval_admission
        # performs the framework/version change required by G-6/G-7.
        self.raw_approval_admission("reframe_approval")

    def test_ddl_guards(self):
        columns = [r[1] for r in self.rows("PRAGMA table_info(obligation_assessments)")]
        original = dict(zip(columns, self.rows("SELECT * FROM obligation_assessments")[0]))
        changes = [{"actor_kind": "operator"}, {"contract_content_hash": "forged"}, {"recorded_by_operation_id": "op_missing001"},
            {"topic_id": OTHER}, {"contract_revision": 1}, {"framing_version": 2}, {"eligibility_protocol_version": 2},
            {"invocation_id": "inv_vvvvvvvv"}, {"obligation_id": "missing"}, {"supersedes_id": "oa-fixture", "obligation_id": "O-2"}]
        for confidence in ({"basis": "recorded_assessment", "scheme": {"scheme_id": "absent", "version": 1}, "label": "off-scheme", "assessed_by_invocation_id": "inv_pppppppp"}, {"basis": "unknown", "reason": " "}):
            changes.append({"confidence": json.dumps(confidence)})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(sqlite3.IntegrityError):
                self.x(f"INSERT INTO obligation_assessments ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", *{**original, "record_id": "oa-raw", **change}.values())
        for sql in ("UPDATE obligation_assessments SET reason = 'rewritten'", "DELETE FROM obligation_assessments"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.x(sql)
