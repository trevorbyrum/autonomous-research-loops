"""Isolated SQL 29 predicates, retaining mutated/reversed objects in memory."""
import json
import sqlite3
from unittest.mock import patch

from gen2.tests.ddl_fixtures import restore_triggers

from gen2.store import db
from gen2.tests import store_fixtures as fx
from gen2.tests import test_extraction_validations_v2 as v2
from gen2.tests import test_store_extraction_records as raw


class DDLV2Test(v2.V2Case):
    RAW = True
    def setUp(self):
        self.query = "SELECT type,name,sql FROM sqlite_schema WHERE sql IS NOT NULL AND (tbl_name='extraction_validations_v2' OR name='extraction_validation_results_v2') ORDER BY rowid"
        with sqlite3.connect(":memory:") as reference:
            reference.executescript(fx.DDL_TEXT)
            objects = reference.execute(self.query).fetchall()
        with patch.object(fx, "DDL_TEXT", db.schema_text()):
            v2.V2Case.setUp(self)
        self.x("DROP VIEW extraction_validation_results_v2")
        self.x("DROP TABLE extraction_validations_v2")
        for _, _, sql in objects:
            self.x(sql)
        self.assertEqual(self.rows(self.query), objects)
        restore_triggers(self, fx.DDL_TEXT)

    def send(self, grant=None, op="op_record0001", **sections):
        if "extraction_validations" not in sections:
            return raw.DDLTest.send(self, grant, op, **sections)
        grant = grant or self.verifier
        self.x("SAVEPOINT successor_write")
        try:
            for record in sections["extraction_validations"]:
                row = {**record, "validator_invocation_id": grant["invocation_id"],
                    "recorded_by_operation_id": "op_setup_" + grant["invocation_id"], "created_at": "2026-10-14T00:00:00Z"}
                self.x(f"INSERT INTO extraction_validations_v2 ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                    *[json.dumps(v) if isinstance(v, dict) else v for v in row.values()])
            return {"status": "committed"}
        except sqlite3.IntegrityError:
            self.x("ROLLBACK TO successor_write")
            return {"status": "rejected"}
        finally:
            self.x("RELEASE successor_write")

    def test_bindings(self):
        self.basis()
        # Synthetic upstream corruption isolates each downstream binding, including
        # relations that upstream admission already fences. Only in this memory DB.
        self.x("PRAGMA foreign_keys=OFF")
        for table, key, identity, field, value in (
                *(("source_extractions", "extraction_id", "independent", f, "foreign") for f in
                    ("topic_id", "work_id", "source_version", "event_id", "verifier_invocation_id", "extracting_invocation_id")),
                ("source_extractions", "extraction_id", "target", "verifier_invocation_id", self.extractor["invocation_id"]),
                ("source_extractions", "extraction_id", "target", "extracting_invocation_id", self.verifier["invocation_id"]),
                ("source_artifacts", "work_id", self.work, "invocation_id", self.verifier["invocation_id"]),
                *(("invocations", "invocation_id", self.verifier["invocation_id"], f, v) for f, v in
                    (("topic_id", "foreign"), ("kind", "checkpoint"), ("admission_context", "scoping/1"), ("parent_invocation_id", self.extractor["invocation_id"]))),
                *(("operation_receipts", "operation_id", "op_setup_" + self.verifier["invocation_id"], f, v) for f, v in
                    (("invocation_id", self.extractor["invocation_id"]), ("topic_id", "foreign"), ("contract_revision", 999)))):
            with self.subTest(table=table, field=field, identity=identity):
                self.x("SAVEPOINT binding_probe")
                self.x("PRAGMA ignore_check_constraints=ON")
                for name, sql in self.rows("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name=?", table):
                    if "BEFORE UPDATE" in sql:
                        self.x(f'DROP TRIGGER "{name}"')
                self.x(f"UPDATE {table} SET {field}=? WHERE {key}=?", value, identity)
                if table == "source_extractions" and identity == "target" and field == "verifier_invocation_id":
                    self.x("UPDATE source_extractions SET verifier_invocation_id=? WHERE extraction_id='independent'", value)
                self.x("PRAGMA ignore_check_constraints=OFF")
                self.refuse(extraction_validations=[self.validation()])
                self.x("ROLLBACK TO binding_probe")
                self.x("RELEASE binding_probe")
        self.x("PRAGMA foreign_keys=ON")

    def test_evidence_hash(self):
        self.basis()
        self.refuse(extraction_validations=[self.validation(comparison_evidence_ref={**self.evidence, "content_hash": self.output["content_hash"]})])

    def test_registered_validator_pin(self):
        # Isolate historical membership from the common/current registry guards'
        # overlapping NULL refusals, only in this disposable in-memory store.
        self.x("DROP TRIGGER extraction_validations_v2_comparison_registry")
        self.x("DROP TRIGGER extraction_validations_v2_current_registry")
        self.basis()
        self.x("DROP TRIGGER source_extractions_immutable_u")
        self.x("UPDATE source_extractions SET extractor_registry_version=NULL WHERE extraction_id='independent'")
        self.refuse(extraction_validations=[self.validation()])
