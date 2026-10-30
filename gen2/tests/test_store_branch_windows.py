"""Raw integrity guards for branch windows; in-memory fixtures only."""
import re
import sqlite3

from gen2.tests.store_fixtures import StoreTestCase, TOPIC


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
        before = self.snapshot("branch_windows")
        for changes, fragment in (({"registry_id": "B-2"}, "same-topic registered branch identity"),
                                  ({"branch_disposition_id": "rdp_fixture1"}, "same-topic registered branch identity"),
                                  ({"window_invocation_id": "inv_vvvvvvvv"}, "same-topic contract-admitted research window"),
                                  ({"invocation_id": "inv_vvvvvvvv"}, "needs its primary governed commit"),
                                  ({"actor_kind": "operator"}, "CHECK constraint failed: actor_kind = 'primary'")):
            with self.subTest(changes=changes):
                self.x("SAVEPOINT guard")
                try:
                    with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                        self.raw(**changes)
                    self.assertEqual(self.snapshot("branch_windows"), before)
                finally:
                    self.x("ROLLBACK TO guard")
                    self.x("RELEASE guard")
        self.raw()
        before = self.rows("SELECT * FROM branch_windows")
        for sql, fragment in (("UPDATE branch_windows SET registry_id = 'B-2'", "branch/window associations are append-only"),
                              ("DELETE FROM branch_windows", "branch/window provenance is retained")):
            with self.subTest(sql=sql):
                self.rejects(fragment, sql)
            self.assertEqual(self.rows("SELECT * FROM branch_windows"), before)
