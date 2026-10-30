"""Raw registry guards, included in both declared and reversed trigger runs."""
import json
import re
import sqlite3

from gen2.tests import store_fixtures as sf
from gen2.tests.test_extractor_registry import approval


NEEDS_AUDIT = "extractor registry needs its operator audit"


class RegistryDDLTest(sf.StoreTestCase):
    def audit(self, doc, **changes):
        row = dict(audit_event_id="aud_registry" + str(doc["registry_version"]), at=sf.T,
            kind="extractor_registry_registered", topic_id=None, invocation_id=None, operation_id=None, detail=json.dumps(doc))
        row.update(changes)
        self.x(f"INSERT INTO audit_events ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())
        return row["audit_event_id"]

    def revision(self, doc, audit):
        self.x("INSERT INTO extractor_registry_revisions VALUES (?, ?, ?, ?, ?)",
            doc["registry_version"], doc["operator_id"], doc["reason"], audit, sf.T)

    def test_control(self):
        doc = approval()
        self.revision(doc, self.audit(doc))
        for tool in doc["tools"]:
            self.x("INSERT INTO extractor_tools VALUES (1, ?, ?)", tool["extractor_identity"], tool["family"])
        self.assertEqual(self.rows("SELECT family FROM extractor_tools ORDER BY extractor_identity"), [("family-a",), ("family-b",)])

    def test_authority(self):
        changes = [{k: "foreign"} for k in ("kind", "topic_id", "invocation_id", "operation_id", "at")]
        changes += [{"detail": json.dumps(approval(**{k: value}))} for k, value in
            (("registry_version", 99), ("operator_id", "foreign"), ("reason", "foreign"))]
        for version, change in enumerate(changes, 1):
            with self.subTest(change=change):
                doc = approval(version)
                # Keep all non-target audit fields equal to this candidate.
                if "detail" in change:
                    detail = json.loads(change["detail"])
                    if detail["registry_version"] != 99:
                        detail["registry_version"] = version
                    change = {"detail": json.dumps(detail)}
                audit = self.audit(doc, **change)
                before = self.snapshot("extractor_registry_revisions")
                with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(NEEDS_AUDIT)):
                    self.revision(doc, audit)
                self.assertEqual(self.snapshot("extractor_registry_revisions"), before)

    def test_mapping(self):
        doc = approval()
        self.revision(doc, self.audit(doc))
        for identity, family in (("alias-a", "family-a"), ("tool-a", "family-b")):
            before = self.snapshot("extractor_tools")
            with self.subTest(identity=identity, family=family), self.assertRaisesRegex(sqlite3.IntegrityError, "extractor tool needs its exact approved mapping"):
                self.x("INSERT INTO extractor_tools VALUES (1, ?, ?)", identity, family)
            self.assertEqual(self.snapshot("extractor_tools"), before)

    def test_audit_reference(self):
        doc = approval()
        self.audit(doc)
        wrong = self.audit(doc, audit_event_id="aud_wrong", kind="commit_outcome")
        before = self.snapshot("extractor_registry_revisions")
        with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(NEEDS_AUDIT)):
            self.revision(doc, wrong)
        self.assertEqual(self.snapshot("extractor_registry_revisions"), before)

    def test_mapping_revision(self):
        self.test_control()
        doc = approval(2, tools=[{"extractor_identity": "tool-c", "family": "family-c"}])
        self.revision(doc, self.audit(doc))
        before = self.snapshot("extractor_tools")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "extractor tool needs its exact approved mapping"):
            self.x("INSERT INTO extractor_tools VALUES (2, 'tool-a', 'family-a')")
        self.assertEqual(self.snapshot("extractor_tools"), before)

    def test_revision_domain(self):
        for version, (change, fragment) in enumerate((({"operator_id": ""}, "length(operator_id) > 0"), ({"reason": ""}, "length(reason) > 0"),
                ({"registry_version": 9007199254740992}, "registry_version BETWEEN 1 AND 9007199254740991")), 1):
            doc = approval(version, **change)
            audit = self.audit(doc)
            before = self.snapshot("extractor_registry_revisions")
            with self.subTest(change=change), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                self.revision(doc, audit)
            self.assertEqual(self.snapshot("extractor_registry_revisions"), before)

    def test_names(self):
        for version, (field, name) in enumerate(((field, name) for field in ("extractor_identity", "family")
                for name in ("Tool-a", "tool a", "1tool", "tool-a\x00alias", "", "a" * 101)), 1):
            with self.subTest(field=field, name=name):
                tool = {"extractor_identity": "tool-a", "family": "family-a", field: name}
                # Admitted counterpart: the same revision and authority approving the valid spelling, rolled back.
                self.x("SAVEPOINT counterpart")
                valid = approval(version, tools=[{"extractor_identity": "tool-a", "family": "family-a"}])
                self.revision(valid, self.audit(valid))
                self.x("INSERT INTO extractor_tools VALUES (?, 'tool-a', 'family-a')", version)
                self.assertEqual(self.rows("SELECT registry_version, extractor_identity, family FROM extractor_tools WHERE registry_version = ?", version),
                    [(version, "tool-a", "family-a")])
                self.x("ROLLBACK TO counterpart")
                self.x("RELEASE counterpart")
                doc = approval(version, tools=[tool])
                self.revision(doc, self.audit(doc))
                before = self.snapshot("extractor_tools")
                with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(f"CHECK constraint failed: length({field}) BETWEEN 1 AND 100")):
                    self.x("INSERT INTO extractor_tools VALUES (?, ?, ?)", version, tool["extractor_identity"], tool["family"])
                self.assertEqual(self.snapshot("extractor_tools"), before)

    def test_order(self):
        doc = approval(2)
        self.revision(doc, self.audit(doc))
        doc = approval(1)
        audit = self.audit(doc)
        before = self.snapshot("extractor_registry_revisions")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "extractor registry revisions must increase"):
            self.revision(doc, audit)
        self.assertEqual(self.snapshot("extractor_registry_revisions"), before)

    def test_immutable(self):
        self.test_control()
        doc = approval(2)
        self.revision(doc, self.audit(doc))  # no children: isolate deletion from the FK
        for table in ("extractor_registry_revisions", "extractor_tools"):
            delete = f"DELETE FROM {table}" + (" WHERE registry_version = 2" if table == "extractor_registry_revisions" else "")
            noun = "extractor registry revisions" if table == "extractor_registry_revisions" else "extractor tools"
            for sql, fragment in ((f"UPDATE {table} SET registry_version = registry_version", f"{noun} are immutable"), (delete, f"{noun} are retained")):
                before = self.snapshot(table)
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                    self.x(sql)
                self.assertEqual(self.snapshot(table), before)
