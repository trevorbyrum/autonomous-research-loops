"""Raw integrity guards for semantic assessments; in-memory fixtures only."""
import json
import sqlite3

from gen2.tests.store_fixtures import StoreTestCase


class SemanticDDLTest(StoreTestCase):
    """Raw DDL fixture, so mutants exercise guards without the opening identity gate."""
    def setUp(self):
        super().setUp()
        self.populate_every_table()

    def append(self, **changes):
        columns = [r[1] for r in self.rows("PRAGMA table_info(semantic_assessments)")]
        row = dict(zip(columns, self.rows("SELECT * FROM semantic_assessments WHERE assessment_id = 'sem1'")[0]))
        row.update(assessment_id="sem2", **changes)
        self.x(f"INSERT INTO semantic_assessments ({','.join(columns)}) VALUES ({','.join('?' for c in columns)})", *row.values())

    def test_control_insert(self):
        self.append(novelty="novel")
        self.assertEqual(self.rows("SELECT assessment_id, novelty FROM semantic_assessments ORDER BY assessment_id"), [("sem1", "unknown"), ("sem2", "novel")])

    def test_update_guard(self):
        for table in ("semantic_assessments", "source_lineage"):
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                self.x(f"UPDATE {table} SET assessment_id = assessment_id")

    def test_binding_guard(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.append(framing_version=2)

    def test_actor_and_label_guards(self):
        for field in ("actor_kind", "novelty", "independence", "applicability", "contribution"):
            with self.subTest(field=field), self.assertRaises(sqlite3.IntegrityError):
                self.append(**{field: "unauthorized"})

    def test_lineage_shape_guard(self):
        self.append()
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("INSERT INTO source_lineage VALUES ('sem2', 'shared_study_origin', NULL, NULL, NULL)")

    def test_delete_guard(self):
        self.append()  # sem2 has no dependents: no foreign key can mask its guard
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("DELETE FROM semantic_assessments WHERE assessment_id = 'sem2'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("DELETE FROM source_lineage")
