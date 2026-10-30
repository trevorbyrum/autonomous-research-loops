"""Raw integrity guards for registry dispositions; in-memory fixtures only."""
import sqlite3

from gen2.tests.store_fixtures import StoreTestCase


class RegistryDDLTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.populate_every_table()

    def append(self, **changes):
        columns = [r[1] for r in self.rows("PRAGMA table_info(registry_dispositions)")]
        row = dict(zip(columns, self.rows("SELECT * FROM registry_dispositions WHERE disposition_id = 'rdp_fixture1'")[0]))
        row.update({"disposition_id": "rdp_fixture2", **changes})
        self.x(f"INSERT INTO registry_dispositions ({','.join(columns)}) VALUES ({','.join('?' for c in columns)})", *row.values())

    def test_control_insert(self):
        self.append(disposition="resolved", supersedes_id="rdp_fixture1")
        self.append(disposition_id="rdp_fixture3", registry_kind="branch", disposition="park")
        self.assertEqual(self.rows("SELECT disposition FROM registry_dispositions ORDER BY disposition_id"), [("promote",), ("unresolved",), ("resolved",), ("park",)])

    def test_binding_and_predecessor(self):
        for changes in ({"framing_version": 2}, {"supersedes_id": "rdp_fixture1", "registry_id": "C-2"},
                        {"supersedes_id": "rdp_fixture1", "registry_kind": "branch", "disposition": "park"}):
            with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError):
                self.append(**changes)

    def test_shape(self):
        for changes in ({"registry_kind": "invalid"}, {"disposition": "park"}, {"registry_kind": "branch"},
                        {"registry_id": ""}, {"subject": ""}, {"reason_code": ""}, {"evidence_refs": "[]"}, {"actor_kind": "operator"}):
            with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError):
                self.append(**changes)

    def test_immutable(self):
        for sql in ("UPDATE registry_dispositions SET disposition = 'resolved' WHERE disposition_id = 'rdp_fixture1'",
                    "DELETE FROM registry_dispositions WHERE disposition_id = 'rdp_fixture1'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.x(sql)
