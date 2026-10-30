"""V-6 source identities: raw DDL guards with independent accepted controls."""
import re
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
        before = self.snapshot("source_artifacts")
        with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape("needs its contract-admitted primary commit")):
            self.raw(invocation_id="inv_vvvvvvvv")
        self.assertEqual(self.snapshot("source_artifacts"), before)

    def test_topic(self):
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, topic_id, staged_at) VALUES (?, 10, 'text/plain', ?, ?)", h("e"), TOPIC, T)
        self.x("INSERT INTO works VALUES ('wrk_unretrieved', 'doi', '10.1/unretrieved', NULL, ?)", T)
        before = self.snapshot("source_artifacts")
        for changes in ({"content_hash": h("e")}, {"work_id": "wrk_unretrieved"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape("topic-authorized bytes and a topic-retrieved work")):
                self.raw(**changes)
            self.assertEqual(self.snapshot("source_artifacts"), before)

    def test_update(self):
        self.raw()  # v2 has no acquisition dependent; the FK cannot mask the guard.
        before = self.snapshot("source_artifacts")
        self.rejects("capture provenance are immutable", "UPDATE source_artifacts SET source_version = 'changed' WHERE source_version = 'v2'")
        self.assertEqual(self.snapshot("source_artifacts"), before)

    def test_delete(self):
        self.raw()
        before = self.snapshot("source_artifacts")
        self.rejects("capture provenance are retained", "DELETE FROM source_artifacts WHERE source_version = 'v2'")
        self.assertEqual(self.snapshot("source_artifacts"), before)
