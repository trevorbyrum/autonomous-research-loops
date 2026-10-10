"""2d-1: literal judgment oracles, raw SQL history and atomic refusals.

Only disposable fixture stores; this tests admission, not scientific truth.
"""
import json
import sqlite3
from pathlib import Path

from gen2.router.schemas import SchemaSet
from gen2.tests.router_fixtures import TOPIC, OTHER, empty_outcome
from gen2.tests.test_confidence_contract import declare, SCHEME
from gen2.tests.test_router_workflow import Workflow, contract
from gen2.tests.store_fixtures import StoreTestCase, facet, obligation

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema/obligation-assessment.schema.json"


class AdmissionTest(Workflow):
    def setUp(self):
        super().setUp()
        self.open_brief()
        self.confirm()
        self.doc = contract(2, 1, edit=declare)
        self.assertEqual(self.draft(contract(1, None, rated=False, edit=declare))["status"], "recorded")
        self.assertEqual(self.rate(self.doc)["status"], "applied")
        self.assertEqual(self.draft(self.doc)["status"], "recorded")
        self.scope_approved()
        self.assertEqual(self.approve(self.doc)["status"], "applied")
        self.grant = self.started("inv_obligation01")
        self.ref = self.artifact(b"independent retained assessment evidence")

    def record(self, **changes):
        return {"record_id": "oa-first", "obligation_id": "O-1", "subject": "Effect on omissions", "contract_revision": 2,
            "contract_content_hash": self.doc["content_hash"], "eligibility_protocol_version": 1, "framing_version": 1,
            "evidence_refs": [self.ref], "reason": "Independent evidence within the declared scope", "supersedes_id": None,
            "disposition": "supported", "confidence": {"basis": "recorded_assessment", "scheme": {"scheme_id": SCHEME["scheme_id"], "version": 1}, "label": "corroborated"}, **changes}

    def send(self, records, grant=None, refs=None):
        grant = grant or self.grant
        outcome = {**empty_outcome(grant["invocation_id"], "interim_transition", grant["topic_id"]), "obligation_assessments": records}
        self.env = self.envelope(grant, self.ids("op_"), outcome, refs=[self.ref] if refs is None else refs)
        return self.router.commit_outcome(self.env)

    def reject(self, record, reason="payload_invalid", detail=None, **kwargs):
        before = self.state()
        out = self.send([record], **kwargs)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        if detail is not None:
            self.assertIn(detail, out["detail"])
        self.assertEqual(self.state(), before)

    def test_control(self):
        out = self.send([self.record()])
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(self.rows("SELECT actor_kind, invocation_id, recorded_by_operation_id, contract_revision, disposition FROM obligation_assessments"),
            [("primary", "inv_obligation01", self.env["operation_id"], 2, "supported")])
        confidence = json.loads(self.value("SELECT confidence FROM obligation_assessments"))
        self.assertEqual(confidence, {"basis": "recorded_assessment", "scheme": {"scheme_id": "plan-corroboration", "version": 1},
            "label": "corroborated", "assessed_by_invocation_id": "inv_obligation01"})
        self.assertEqual(json.loads(self.value("SELECT evidence_refs FROM obligation_assessments")), [self.ref])
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(self.env)["status"], "replayed")
        self.assertEqual(self.state(exclude=()), before)

    def test_scheme_and_pins(self):
        self.x("DROP TRIGGER obligation_assessments_bound")  # isolate admission from its DDL mirror
        self.x("DROP TRIGGER obligation_assessments_scheme")
        for change in ({"label": "off-scheme"}, {"scheme": {"scheme_id": "foreign", "version": 1}}, {"scheme": {"scheme_id": SCHEME["scheme_id"], "version": 2}}):
            self.reject(self.record(confidence={**self.record()["confidence"], **change}))
        for change in ({"contract_revision": 1}, {"contract_content_hash": "sha256:" + "1" * 64}, {"framing_version": 2}, {"eligibility_protocol_version": 2}, {"obligation_id": "missing"}):
            self.reject(self.record(**change), detail="obligation does not exist" if "obligation_id" in change else "exact contract pins")

    def test_evidence(self):
        self.reject(self.record(), "payload_missing", refs=[])
        self.reject(self.record(evidence_refs=[{**self.ref, "size_bytes": self.ref["size_bytes"] + 1}]))
        foreign = self.artifact(b"other topic's evidence")
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, topic_id, staged_at) VALUES (?, ?, ?, ?, '2026-09-27T09:00:00Z')",
            foreign["content_hash"], foreign["size_bytes"], foreign["media_type"], OTHER)
        self.reject(self.record(evidence_refs=[foreign]), "payload_missing", refs=[])

    def test_roles_and_attribution(self):
        delegate = self.claim("inv_obl_delegate", "delegate", parent=self.grant)
        self.reject(self.record(), "kind_not_permitted", grant=delegate)
        self.to_scoping(OTHER)
        scoping = self.started("inv_obl_scoping", tid=OTHER)
        self.reject(self.record(), "kind_not_permitted", grant=scoping)
        for field, value in (("actor_kind", "operator"), ("invocation_id", "inv_foreign001"), ("created_at", "2026-10-10T00:00:00Z")):
            self.reject(self.record(**{field: value}))
        self.reject(self.record(confidence={**self.record()["confidence"], "assessed_by_invocation_id": "inv_foreign001"}))

    def test_histories_and_conflicts(self):
        self.x("DROP TRIGGER obligation_assessments_predecessor")  # isolate the Router chain check
        self.assertEqual(self.send([self.record()])["status"], "committed")
        unknown = {"basis": "unknown", "reason": "Access is unavailable"}
        open_record = self.record(record_id="oa-open", confidence=unknown, state="open")
        del open_record["disposition"]
        self.assertEqual(self.send([self.record(record_id="oa-defer", disposition="deferred", confidence=unknown, supersedes_id="oa-first"),
            self.record(record_id="oa-competing", disposition="contradicted", supersedes_id="oa-first"), open_record])["status"], "committed")
        self.assertEqual(self.rows("SELECT record_id, disposition, state, supersedes_id FROM obligation_assessments ORDER BY record_id"),
            [("oa-competing", "contradicted", None, "oa-first"), ("oa-defer", "deferred", None, "oa-first"), ("oa-first", "supported", None, None), ("oa-open", None, "open", None)])
        self.assertEqual(json.loads(self.value("SELECT confidence FROM obligation_assessments WHERE record_id = 'oa-defer'")), unknown)
        self.reject(self.record(disposition="unresolved"))  # identity conflict rolls back
        self.reject(self.record(record_id="oa-new", supersedes_id="missing"))
        self.reject(self.record(record_id="oa-new", obligation_id="O-2", supersedes_id="oa-first"))

    def test_predecessor_time(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        self.router._clock = lambda: self.value("SELECT created_at FROM obligation_assessments WHERE record_id = 'oa-first'")
        self.reject(self.record(record_id="oa-new", supersedes_id="oa-first"))

    def test_schema(self):
        target = "obligation-assessment.schema.json"
        schemas = SchemaSet(extra={target: json.loads(SCHEMA_PATH.read_text())})
        self.assertEqual(schemas.errors(self.record(), target), [])
        for field in self.record():
            self.assertTrue(schemas.errors({k: v for k, v in self.record().items() if k != field}, target), field)
        for changes in ({"actor_kind": "operator"}, {"state": "open"}, {"evidence_refs": []}):
            self.assertTrue(schemas.errors(self.record(**changes), target), changes)
        for changes in ({"confidence": {"basis": "unknown", "reason": ""}}, {"confidence": {"basis": "unknown", "reason": " "}},
                        {"state": "open"}, {"evidence_refs": []}, {"disposition": "invented"}, {"confidence": {"probability": 0.9}}):
            self.reject(self.record(**changes), detail="unknown confidence requires its reason" if changes == {"confidence": {"basis": "unknown", "reason": " "}} else None)

    def test_schema_control(self):
        self.assertEqual(SchemaSet(extra={"obligation-assessment.schema.json": json.loads(SCHEMA_PATH.read_text())}).errors(self.record(), "obligation-assessment.schema.json"), [])

    def test_noop_control(self):
        self.assertEqual(self.send([])["status"], "committed")
        self.assertEqual(self.rows("SELECT * FROM obligation_assessments"), [])

    def test_historical_scheme_and_standing(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        before = self.rows("SELECT * FROM obligation_assessments")
        def change(doc):
            declare(doc)
            doc["protocol_revision"] = 3
            doc["confidence_scheme"]["version"] = 2
            doc["confidence_scheme"]["labels"] = {"new-label": "A newly approved rubric"}
        new = contract(3, 2, edit=change)
        self.assertEqual(self.router.propose_amendment({"document": new})["status"], "recorded")
        self.assertEqual(self.approve(new)["status"], "applied")
        self.assertEqual(self.rows("SELECT * FROM obligation_assessments"), before)
        self.assertEqual(json.loads(self.value("SELECT document FROM contract_revisions WHERE topic_id = ? AND revision = 2", TOPIC))["confidence_scheme"], SCHEME)
        self.assertEqual(json.loads(self.value("SELECT document FROM amendment_impacts WHERE topic_id = ? AND kind = 'contract' ORDER BY rowid DESC", TOPIC))["classification"], "protocol_changed")
        self.reject(self.record(record_id="oa-stale"), "amendment_pending")

class DDLTest(StoreTestCase):
    """Raw DDL fixtures, independent of the Store's schema-identity gate."""
    def approved_with_obligation(self, tid=TOPIC):
        n = self.rows("SELECT max(revision) + 1 FROM contract_revisions WHERE topic_id = ?", tid)[0][0]
        did = "opd_obl_ratings"
        rated = {"band": "critical", "score": 8, "decision": did}
        entries = {"facets": (facet("F-1", **rated),), "obligations": tuple(obligation(o, ("F-1",), **rated) for o in ("O-1", "O-2"))}
        self.rate(did, tid, **entries)
        self.contract_with_rows(tid, n + 1, **entries, content_hash=self.chash(tid, n + 1))
        self.approve_contract(tid, n + 1)
        return n + 1

    def setUp(self):
        super().setUp()
        self.populate_every_table()

    def test_control(self):
        self.x("INSERT INTO obligation_assessments SELECT 'oa-control', topic_id, obligation_id, subject, contract_revision, contract_content_hash, eligibility_protocol_version, framing_version, "
            "disposition, state, confidence, evidence_refs, actor_kind, invocation_id, recorded_by_operation_id, created_at, reason, 'oa-fixture' FROM obligation_assessments WHERE record_id = 'oa-fixture'")
        self.assertEqual(self.rows("SELECT record_id FROM obligation_assessments ORDER BY record_id"), [("oa-control",), ("oa-fixture",)])

    def test_ddl_guards(self):
        columns = [r[1] for r in self.rows("PRAGMA table_info(obligation_assessments)")]
        original = dict(zip(columns, self.rows("SELECT * FROM obligation_assessments")[0]))
        changes = [{"actor_kind": "operator"}, {"contract_content_hash": "forged"}, {"recorded_by_operation_id": "op_missing001"}, {"supersedes_id": "oa-fixture", "obligation_id": "O-2"}]
        for confidence in ({"basis": "recorded_assessment", "scheme": {"scheme_id": "absent", "version": 1}, "label": "off-scheme", "assessed_by_invocation_id": "inv_pppppppp"}, {"basis": "unknown", "reason": " "}):
            changes.append({"confidence": json.dumps(confidence)})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(sqlite3.IntegrityError):
                self.x(f"INSERT INTO obligation_assessments ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", *{**original, "record_id": "oa-raw", **change}.values())
        for sql in ("UPDATE obligation_assessments SET reason = 'rewritten'", "DELETE FROM obligation_assessments"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.x(sql)
