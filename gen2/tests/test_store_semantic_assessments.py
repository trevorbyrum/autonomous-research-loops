"""Raw integrity guards for semantic assessments; in-memory fixtures only."""
import re
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
        for table, fragment in (("semantic_assessments", "semantic assessments are append-only (E-7)"),
                                ("source_lineage", "source lineage is append-only (E-3)")):
            with self.subTest(table=table):
                before = self.snapshot(table)
                self.rejects(fragment, f"UPDATE {table} SET assessment_id = assessment_id")
                self.assertEqual(self.snapshot(table), before)

    def test_binding_guard(self):
        before = self.snapshot("semantic_assessments")
        with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape("needs its primary commit and pinned protocol/framing (E-7, C-12)")):
            self.append(framing_version=2)
        self.assertEqual(self.snapshot("semantic_assessments"), before)

    def test_actor_and_label_guards(self):
        before = self.snapshot("semantic_assessments")
        for field, fragment in (("actor_kind", "CHECK constraint failed: actor_kind = 'primary'"),
                                ("novelty", "novelty IN ("), ("independence", "independence IN ("),
                                ("applicability", "applicability IN ("), ("contribution", "contribution IN (")):
            with self.subTest(field=field), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                self.append(**{field: "unauthorized"})
            self.assertEqual(self.snapshot("semantic_assessments"), before)

    def test_lineage_shape_guard(self):
        self.append()
        before = self.snapshot("source_lineage")
        self.rejects("relation = 'shared_study_origin' AND study_origin_id IS NOT NULL",
                     "INSERT INTO source_lineage VALUES ('sem2', 'shared_study_origin', NULL, NULL, NULL)")
        self.assertEqual(self.snapshot("source_lineage"), before)
        self.x("INSERT INTO source_lineage VALUES ('sem2', 'shared_study_origin', 'origin-1', NULL, NULL)")
        self.assertEqual(self.rows("SELECT * FROM source_lineage WHERE assessment_id = 'sem2'"),
                         [("sem2", "shared_study_origin", "origin-1", None, None)])

    def test_delete_guard(self):
        self.append()  # sem2 has no dependents: no foreign key can mask its guard
        before = self.snapshot("semantic_assessments")
        self.rejects("semantic assessments are retained (E-7)", "DELETE FROM semantic_assessments WHERE assessment_id = 'sem2'")
        self.assertEqual(self.snapshot("semantic_assessments"), before)
        before = self.snapshot("source_lineage")
        self.rejects("source lineage is retained (E-3)", "DELETE FROM source_lineage")
        self.assertEqual(self.snapshot("source_lineage"), before)
