"""Raw integrity guards for source lifecycle; in-memory fixtures only."""
import re
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
        before = self.snapshot("source_lifecycle")
        for changes, fragment in (({"framing_version": 2}, "lifecycle needs its primary commit and pinned protocol/framing"),
                                  ({"source_version": "v2", "supersedes_id": "sld_fixture1"}, "lifecycle predecessor must exist for this topic and source version")):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                self.append(**changes)
            self.assertEqual(self.snapshot("source_lifecycle"), before)

    def test_update_and_delete_guards(self):
        before = self.snapshot("source_lifecycle")
        for sql, fragment in (("UPDATE source_lifecycle SET action = 'keep'", "source lifecycle is append-only"),
                              ("DELETE FROM source_lifecycle", "source lifecycle is retained")):
            with self.subTest(sql=sql):
                self.rejects(fragment, sql)
            self.assertEqual(self.snapshot("source_lifecycle"), before)

    def test_shape_guards(self):
        # Roll back the control so no primary-key conflict can mask a shape guard.
        self.x("SAVEPOINT coexist_control")
        self.append(action="coexist", source_version="v2", related_work_id="wrk_00000001", related_source_version="v1")
        self.assertEqual(self.rows("SELECT action, related_work_id, related_source_version FROM source_lifecycle WHERE disposition_id = 'sld_fixture2'"),
                         [("coexist", "wrk_00000001", "v1")])
        self.x("ROLLBACK TO coexist_control")
        self.x("RELEASE coexist_control")
        before = self.snapshot("source_lifecycle")
        for changes, fragment in (({"action": "invalid"}, "action IN ('add', 'keep', 'supersede'"),
                                  ({"actor_kind": "operator"}, "actor_kind = 'primary'"), ({"reason_code": ""}, "length(reason_code) > 0"),
                                  ({"source_version": ""}, "length(source_version) > 0"), ({"evidence_refs": "[]"}, "json_array_length(evidence_refs) > 0"),
                                  ({"action": "coexist"}, "action IN ('supersede', 'coexist', 'duplicate-report') AND related_work_id IS NOT NULL")):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                self.append(**changes)
            self.assertEqual(self.snapshot("source_lifecycle"), before)
