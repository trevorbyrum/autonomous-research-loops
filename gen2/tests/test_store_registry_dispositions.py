"""Raw integrity guards for registry dispositions; in-memory fixtures only."""
import re
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
        before = self.snapshot("registry_dispositions")
        for changes, fragment in (({"framing_version": 2}, "needs its primary commit and pinned protocol/framing"),
                                  ({"supersedes_id": "rdp_fixture1", "registry_id": "C-2"}, "registry predecessor must exist for this topic, kind and identity"),
                                  ({"supersedes_id": "rdp_fixture1", "registry_kind": "branch", "disposition": "park"}, "registry predecessor must exist for this topic, kind and identity")):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                self.append(**changes)
            self.assertEqual(self.snapshot("registry_dispositions"), before)

    def test_shape(self):
        before = self.snapshot("registry_dispositions")
        for changes, fragment in (({"registry_kind": "invalid"}, "registry_kind IN ('contradiction', 'branch')"),
                                  ({"disposition": "park"}, "registry_kind = 'contradiction' AND disposition IN ("),
                                  ({"registry_kind": "branch"}, "registry_kind = 'contradiction' AND disposition IN ("),
                                  ({"registry_id": ""}, "length(registry_id) > 0"), ({"subject": ""}, "length(subject) > 0"),
                                  ({"reason_code": ""}, "length(reason_code) > 0"),
                                  ({"evidence_refs": "[]"}, "json_array_length(evidence_refs) > 0"), ({"actor_kind": "operator"}, "actor_kind = 'primary'")):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                self.append(**changes)
            self.assertEqual(self.snapshot("registry_dispositions"), before)

    def test_immutable(self):
        before = self.snapshot("registry_dispositions")
        for sql, fragment in (("UPDATE registry_dispositions SET disposition = 'resolved' WHERE disposition_id = 'rdp_fixture1'", "registry dispositions are append-only"),
                              ("DELETE FROM registry_dispositions WHERE disposition_id = 'rdp_fixture1'", "registry disposition history is retained")):
            with self.subTest(sql=sql):
                self.rejects(fragment, sql)
            self.assertEqual(self.snapshot("registry_dispositions"), before)
