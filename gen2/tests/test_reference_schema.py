"""Schema reference construction executes no singleton initialization."""
import sqlite3
import unittest
from unittest.mock import patch

from gen2.store import db


class ReferenceSchemaTest(unittest.TestCase):
    def observed(self, text=None):
        writes = []
        original = sqlite3.connect
        def connect(*args, **kwargs):
            conn = original(*args, **kwargs)
            dropped = set()
            def authorize(action, table, column, database, trigger):
                if action in (sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_VIEW):
                    dropped.add((database, table))
                elif action == sqlite3.SQLITE_DELETE and (database, table) in dropped:
                    dropped.remove((database, table))
                elif action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) and not table.startswith('sqlite_'):
                    writes.append((action, table))
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorize)
            return conn
        with patch.object(sqlite3, 'connect', connect):
            result = db.reference_schema(text)
        return result, writes

    def test_reference_has_all_objects_without_seed_dml(self):
        (objects, version), writes = self.observed()
        self.assertIn(('table', 'store_generation'), objects)
        self.assertIn(('trigger', 'store_generation_no_insert'), objects)
        self.assertEqual(writes, [])
        with sqlite3.connect(':memory:') as conn:
            conn.executescript(db.schema_text())
            self.assertEqual(db._schema_objects(conn), objects)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], version)
            self.assertEqual(conn.execute('SELECT count(*) FROM store_generation').fetchone()[0], 1)

    def test_other_dml_is_not_hidden(self):
        _, writes = self.observed('CREATE TABLE canary (value); /* seed canary */ INSERT INTO canary VALUES (1);')
        self.assertEqual(writes, [(sqlite3.SQLITE_INSERT, 'canary')])
