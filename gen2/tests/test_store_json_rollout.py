"""Eight-table raw-DDL domain pairs with semantic INSERT guards intact.

Trace: C-13; DOSSIER 2d-4b3e1-json2b. Remove only named immutability/deletion
fences in disposable memory to isolate both generated write-event predicates.
"""
import json
import sqlite3
from unittest.mock import patch

from gen2.tests.ddl_fixtures import restore_triggers

from gen2.store import api, db
from gen2.tests import store_fixtures as fx

# Literal slice inventory, independent of the generated manifest/guards.
COLUMNS = (
    ('amendment_impacts', 'document', 'AmendmentImpactsTest', 'amendment_impacts_immutable_u', 'amendment_impacts_no_delete'),
    ('audit_events', 'detail', 'AuditEventsTest', 'audit_events_append_only_u', 'audit_events_append_only_d'),
    ('config_bundles', 'document', 'ConfigBundlesTest', 'config_bundles_immutable', 'config_bundles_no_delete'),
    ('contract_revisions', 'document', 'ContractRevisionsTest', 'contract_content_immutable', 'contract_no_delete'),
    ('invocation_transitions', 'facts', 'InvocationTransitionsTest', 'invocation_transitions_append_only_u', 'invocation_transitions_append_only_d'),
    ('scoping_reports', 'document', 'ScopingReportsTest', 'scoping_reports_immutable_u', 'scoping_reports_no_delete'),
    ('screening_assessments', 'criterion_results', 'ScreeningAssessmentsTest', 'screening_assessments_immutable_u', 'screening_assessments_immutable_d'),
    ('source_proposals', 'document', 'SourceProposalsTest', 'source_proposals_immutable_u', 'source_proposals_no_delete'),
)


class RolloutPairs:
    def setUp(self):
        # Capture mutated/reversed objects before normal seeding/adoption.
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(fx.DDL_TEXT)
            objects = reference.execute("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name=? ORDER BY rowid", (self.table,)).fetchall()
        with patch.object(fx, 'DDL_TEXT', db.schema_text()):
            fx.StoreTestCase.setUp(self)
            self.populate_every_table()
        self.reader = api.adopt_in_memory(self.db)
        restore_triggers(self, fx.DDL_TEXT)
        self.assertEqual(self.rows("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name=? ORDER BY rowid", self.table), objects)
        self.columns = [r[1] for r in self.rows(f'PRAGMA table_info({self.table})')]
        row = self.x(f'SELECT rowid,* FROM {self.table} ORDER BY rowid LIMIT 1').fetchone()
        self.rowid, self.template = row[0], dict(zip(self.columns, row[1:]))
        self.document = json.loads(self.template[self.column] or '{}')
        # Explicitly isolate the two event guards; preserve every binding and CHECK.
        for name in self.removed:
            self.x(f'DROP TRIGGER {name}')
        self.assertEqual(self.rows("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name=? ORDER BY rowid", self.table),
            [(name, sql) for name, sql in objects if name not in self.removed])

    def attempt(self, event, text, accepted):
        self.x('SAVEPOINT member_pair')
        try:
            if event == 'i':
                self.x('PRAGMA defer_foreign_keys=ON')
                self.x(f'DELETE FROM {self.table} WHERE rowid=?', self.rowid)
            before = list(self.db.iterdump())
            def write():
                if event == 'i':
                    row = {**self.template, self.column: text}
                    self.x(f'INSERT INTO {self.table} ({",".join(row)}) VALUES ({",".join("?" for _ in row)})', *row.values())
                else:
                    self.x(f'UPDATE {self.table} SET {self.column}=? WHERE rowid=?', text, self.rowid)
            if accepted:
                write()
                rows = self.reader.select(self.table)
                matches = [r for r in rows if all(r[c] == v for c, v in self.template.items() if c != self.column)]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0][self.column], json.loads(text))
                self.assertEqual(self.rows('PRAGMA foreign_key_check'), [])
            else:
                self.assertEqual(self.rows('SELECT json_valid(?)', text), [(1,)])
                with self.assertRaises(sqlite3.IntegrityError) as caught:
                    write()
                self.assertIn('JSON member domain:', str(caught.exception))
                self.assertEqual(list(self.db.iterdump()), before)
        finally:
            self.x('ROLLBACK TO member_pair')
            self.x('RELEASE member_pair')

    def good(self):
        return json.dumps({**self.document, 'probe': [{'a': 'kept\0value'}, {'a': 2, 'A': 3}]})

    def duplicates(self, event):
        base = json.dumps(self.document)
        for probe in ('"a":1,"a":2', '"a":1,"\\u0061":2', '"nested":{"a":1,"a":2}'):
            with self.subTest(probe=probe):
                self.attempt(event, self.good(), True)
                self.attempt(event, base[:-1] + (',' if self.document else '') + '"probe":{' + probe + '}}', False)

    def nul(self, event):
        for bad in ({**self.document, 'name\0suffix': 'kept\0value'},
                {**self.document, 'probe': {'name\0suffix': 'kept\0value'}}):
            with self.subTest(bad=bad):
                self.attempt(event, self.good(), True)
                self.attempt(event, json.dumps(bad), False)


for event in ('i', 'u'):
    for name, body in (('control', lambda self, event=event: self.attempt(event, self.good(), True)),
            ('duplicate', lambda self, event=event: self.duplicates(event)),
            ('nul', lambda self, event=event: self.nul(event))):
        setattr(RolloutPairs, f'test_{name}_{event}', body)

for table, column, cls, update, delete in COLUMNS:
    globals()[cls] = type(cls, (RolloutPairs, fx.StoreTestCase),
        {'table': table, 'column': column, 'removed': (update, delete), '__module__': __name__})
