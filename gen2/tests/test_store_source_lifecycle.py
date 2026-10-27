"""Raw integrity guards for source lifecycle; in-memory fixtures only."""
import sqlite3

from gen2.tests.store_fixtures import StoreTestCase


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
