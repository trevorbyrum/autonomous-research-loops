"""Raw SQL 22 guards over admitted fixture operands; in-memory databases only."""
import json
import sqlite3
from unittest.mock import patch

from gen2.store import db
from gen2.tests import store_fixtures, test_extraction_records as records


class DDLTest(records.RecordTest):
    test_authentication = test_authentication_control = None

    def setUp(self):
        # Seed admitted operands under declared DDL, then install raw guards
        # on this disposable connection; mutated DDL never passes Store adoption.
        with sqlite3.connect(":memory:") as reference:
            reference.executescript(store_fixtures.DDL_TEXT)
            query = "SELECT type, name, sql FROM sqlite_schema WHERE sql IS NOT NULL AND (tbl_name IN ('source_extractions', 'extraction_validations') OR name = 'extraction_validation_results') ORDER BY rowid"
            objects = reference.execute(query).fetchall()
        with patch.object(store_fixtures, "DDL_TEXT", db.schema_text()):
            records.RecordCase.setUp(self)
        self.db.executescript("DROP VIEW extraction_validation_results; DROP TABLE extraction_validations; DROP TABLE source_extractions;")
        for _, _, sql in objects:
            self.db.execute(sql)
        self.assertEqual(self.db.execute(query).fetchall(), objects)

    def send(self, grant=None, op="op_record0001", **sections):
        grant = grant or self.extractor
        self.x("SAVEPOINT record_write")
        try:
            for table, attr in (("source_extractions", "extracting_invocation_id"), ("extraction_validations", "validator_invocation_id")):
                for record in sections.get(table, []):
                    row = {**record, attr: grant["invocation_id"], "recorded_by_operation_id": "op_setup_" + grant["invocation_id"], "created_at": records.STAMP}
                    if table == "source_extractions":
                        row["topic_id"] = grant["topic_id"]
                    values = [json.dumps(v) if isinstance(v, dict) else v for v in row.values()]
                    self.x(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *values)
            return {"status": "committed"}
        except sqlite3.IntegrityError:
            self.x("ROLLBACK TO record_write")
            return {"status": "rejected"}
        finally:
            self.x("RELEASE record_write")

    def test_replay(self):
        self.basis()
        self.refuse(source_extractions=[self.extraction()])

    def test_commit(self):
        self.basis()
        before = self.state(exclude=())
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("INSERT INTO source_extractions SELECT 'forged', topic_id, work_id, source_version, event_id, verifier_invocation_id, extractor_identity, extractor_version, extracting_invocation_id, output_ref, supported_tier, 'op_setup_inv_verify0001', created_at FROM source_extractions WHERE extraction_id = 'target'")
        self.assertEqual(self.state(exclude=()), before)


class FullTextDDLTest(records.FullTextTest):
    send = DDLTest.send
    setUp = DDLTest.setUp
