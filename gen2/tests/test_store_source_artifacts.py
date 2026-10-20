"""V-6 source identities: raw DDL guards with independent accepted controls."""
import sqlite3

from gen2.tests.store_fixtures import TOPIC, T, StoreTestCase, h


class DDLTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.populate_every_table()

    def raw(self, **changes):
        row = {"topic_id": TOPIC, "work_id": "wrk_00000001", "source_version": "v2", "content_hash": self.source_hash,
               "invocation_id": "inv_pppppppp", "recorded_by_operation_id": "op_00000001", "created_at": T, **changes}
        self.x("INSERT INTO source_artifacts VALUES (?,?,?,?,?,?,?)", *row.values())

    def test_control(self):
        self.raw()
        self.assertEqual(self.rows("SELECT source_version, content_hash, invocation_id FROM source_artifacts ORDER BY source_version"),
                         [("v1", self.source_hash, "inv_pppppppp"), ("v2", self.source_hash, "inv_pppppppp")])

    def test_commit(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw(invocation_id="inv_vvvvvvvv")

    def test_topic(self):
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, topic_id, staged_at) VALUES (?, 10, 'text/plain', ?, ?)", h("e"), TOPIC, T)
        self.x("INSERT INTO works VALUES ('wrk_unretrieved', 'doi', '10.1/unretrieved', NULL, ?)", T)
        for changes in ({"content_hash": h("e")}, {"work_id": "wrk_unretrieved"}):
            with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError):
                self.raw(**changes)

    def test_update(self):
        self.raw()  # v2 has no acquisition dependent; the FK cannot mask the guard.
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("UPDATE source_artifacts SET source_version = 'changed' WHERE source_version = 'v2'")

    def test_delete(self):
        self.raw()
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("DELETE FROM source_artifacts WHERE source_version = 'v2'")
