"""Generation event bodies in isolation, plus writes with real business guards.

The isolated probes retain the installed generation SQL from the DDL under
test; tiny relations remove unrelated admission rules so DELETE and immutable
UPDATE bodies can be exercised too. They do not prove business admission.
"""
import re
import sqlite3
import unittest

from gen2.store import capture
from gen2.tests import store_fixtures as fx

TABLES = (*capture.TOPIC_TABLES, *capture.SHARED)


class GenerationTest(unittest.TestCase):
    def setUp(self):
        self.db = fx.connect()
        self.addCleanup(self.db.close)
        self.db.execute("INSERT INTO store_generation SELECT 'store',NULL,0 WHERE NOT EXISTS (SELECT 1 FROM store_generation)")

    def probe(self):
        conn = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(conn.close)
        conn.executescript(fx.CONNECTION_TEXT)
        conn.execute(self.db.execute("SELECT sql FROM sqlite_schema WHERE name='store_generation'").fetchone()[0])
        for table in TABLES:
            conn.execute(f'CREATE TABLE {table} (value INTEGER) STRICT')
        for (sql,) in self.db.execute("SELECT sql FROM sqlite_schema WHERE type='trigger' AND (name LIKE 'capture_generation_%' OR tbl_name='store_generation') ORDER BY rowid"):
            conn.execute(sql)
        return conn

    @staticmethod
    def counter(conn):
        row = conn.execute('SELECT generation FROM store_generation').fetchone()
        return row[0] if row else 0

    def test_inventory(self):
        actual = set()
        installed = self.db.execute("SELECT tbl_name,sql FROM sqlite_schema WHERE type='trigger' AND name LIKE 'capture_generation_%'").fetchall()
        for table, sql in installed:
            event = re.search(r'AFTER (INSERT|UPDATE|DELETE) ON', sql)
            self.assertIsNotNone(event)
            actual.add((table, event[1]))
        expected = {(table, event) for table in TABLES for event in ('INSERT', 'UPDATE', 'DELETE')}
        self.assertEqual(actual, expected)
        self.assertEqual(len(installed), len(expected))

    def test_event_bumps(self):
        conn = self.probe()
        for table in TABLES:
            for sql in (f'INSERT INTO {table} VALUES (1)', f'UPDATE {table} SET value=value',
                        f'UPDATE {table} SET rowid=rowid+1', f'DELETE FROM {table}'):
                with self.subTest(sql=sql):
                    before = self.counter(conn)
                    conn.execute(sql)
                    self.assertEqual(self.counter(conn), before + 1)

    def test_event_control(self):
        # Separate accepted control enters every event body, with no counter
        # oracle, including when its particular bump trigger is removed.
        conn = self.probe()
        conn.execute("INSERT INTO store_generation VALUES ('store',NULL,0)")
        for table in TABLES:
            conn.execute(f'INSERT INTO {table} VALUES (1)')
            self.assertEqual(conn.execute(f'SELECT value FROM {table}').fetchall(), [(1,)])
            conn.execute(f'UPDATE {table} SET value=2')
            self.assertEqual(conn.execute(f'SELECT value FROM {table}').fetchall(), [(2,)])
            conn.execute(f'DELETE FROM {table}')
            self.assertEqual(conn.execute(f'SELECT value FROM {table}').fetchall(), [])

    def test_rollback_savepoint_zero_and_restore(self):
        conn = self.probe()
        self.assertEqual(conn.execute('SELECT * FROM store_generation').fetchall(), [])
        for sql in ('UPDATE works SET value=2 WHERE 0', 'DELETE FROM works WHERE 0',
                    'INSERT INTO works SELECT 2 WHERE 0'):
            conn.execute(sql)
        self.assertEqual(conn.execute('SELECT * FROM store_generation').fetchall(), [])
        before = self.counter(conn)
        conn.execute('BEGIN')
        conn.execute('INSERT INTO works VALUES (1)')
        conn.execute('ROLLBACK')
        self.assertEqual(self.counter(conn), before)
        self.assertEqual(conn.execute('SELECT * FROM store_generation').fetchall(), [])
        conn.execute('BEGIN')
        conn.execute('INSERT INTO works VALUES (1)')
        conn.execute('SAVEPOINT s')
        conn.execute('UPDATE works SET value=2')
        conn.execute('ROLLBACK TO s')
        conn.execute('RELEASE s')
        conn.execute('COMMIT')
        self.assertEqual(self.counter(conn), before + 1)
        for sql in ('UPDATE works SET value=2 WHERE 0', 'DELETE FROM works WHERE 0',
                    'INSERT INTO works SELECT 2 WHERE 0'):
            conn.execute(sql)
        self.assertEqual(self.counter(conn), before + 1)
        conn.execute('BEGIN')
        conn.execute('UPDATE works SET value=2')
        conn.execute('UPDATE works SET value=1')
        conn.execute('COMMIT')
        self.assertEqual(self.counter(conn), before + 3)

    def test_writer_initialization(self):
        conn = self.probe()
        conn.execute('SAVEPOINT first_write')
        try:
            conn.execute('INSERT INTO queue_entries VALUES (1)')
        except sqlite3.IntegrityError as exc:
            self.fail(f'first covered write must establish generation: {exc}')
        self.assertEqual(conn.execute('SELECT * FROM store_generation').fetchall(), [('store', None, 1)])
        conn.execute('ROLLBACK TO first_write')
        conn.execute('RELEASE first_write')
        self.assertEqual(conn.execute('SELECT * FROM store_generation').fetchall(), [])

    def test_insert_protection(self):
        self.db.execute('DROP TRIGGER IF EXISTS store_generation_no_delete')
        self.db.execute('DELETE FROM store_generation')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO store_generation VALUES ('store',?,0)", ('a' * 32,))

    def test_delete_protection(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM store_generation')

    def test_step_protection(self):
        for assignment in ('generation=generation', 'generation=generation-1', 'generation=generation+2', "singleton='other'"):
            with self.subTest(assignment=assignment):
                self.db.execute('SAVEPOINT s')
                try:
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.db.execute('UPDATE store_generation SET ' + assignment)
                finally:
                    self.db.execute('ROLLBACK TO s')
                    self.db.execute('RELEASE s')
        self.db.execute("UPDATE store_generation SET epoch=?", ('a' * 32,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('UPDATE store_generation SET epoch=NULL')

    def test_constraints(self):
        self.db.execute('DROP TRIGGER IF EXISTS store_generation_step')
        self.db.execute('DROP TRIGGER IF EXISTS store_generation_no_insert')
        for sql in ("INSERT INTO store_generation VALUES ('other','" + 'a' * 32 + "',0)",
                    'UPDATE store_generation SET generation=-1', 'UPDATE store_generation SET generation=9007199254740992',
                    "UPDATE store_generation SET epoch=''", "UPDATE store_generation SET epoch='" + 'G' * 32 + "'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)

    def test_missing_singleton_write_refuses(self):
        conn = self.probe()
        conn.execute("CREATE TRIGGER suppress_bootstrap BEFORE INSERT ON store_generation BEGIN SELECT RAISE(IGNORE); END")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute('INSERT INTO queue_entries VALUES (1)')
        self.assertEqual(conn.execute('SELECT * FROM queue_entries').fetchall(), [])

    def test_exhaustion(self):
        conn = self.probe()
        guard = conn.execute("SELECT sql FROM sqlite_schema WHERE name='store_generation_step'").fetchone()[0]
        conn.execute('DROP TRIGGER store_generation_step')
        conn.execute("INSERT INTO store_generation VALUES ('store',NULL,0)")
        conn.execute('UPDATE store_generation SET generation=9007199254740990')
        conn.execute(guard)
        conn.execute('INSERT INTO works VALUES (1)')
        self.assertEqual(self.counter(conn), 9007199254740991)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute('UPDATE works SET value=2')
        self.assertEqual(conn.execute('SELECT * FROM works').fetchall(), [(1,)])
        self.assertEqual(self.counter(conn), 9007199254740991)

    def test_replace_upsert_and_conflict_policies(self):
        conn = self.probe()
        conn.execute('CREATE UNIQUE INDEX works_value ON works(value)')
        for sql, bumps, rows in (
                ('INSERT INTO works VALUES (1)', 1, [(1,)]),
                ('INSERT OR REPLACE INTO works VALUES (1)', 2, [(1,)]),
                ('INSERT INTO works VALUES (1) ON CONFLICT(value) DO UPDATE SET value=excluded.value', 1, [(1,)]),
                ('INSERT INTO works VALUES (1) ON CONFLICT(value) DO NOTHING', 0, [(1,)]),
                ('INSERT INTO works VALUES (2)', 1, [(1,), (2,)]),
                ('UPDATE OR REPLACE works SET value=1 WHERE value=2', 2, [(1,)])):
            with self.subTest(sql=sql):
                before = self.counter(conn)
                conn.execute(sql)
                self.assertEqual(self.counter(conn), before + bumps)
                self.assertEqual(conn.execute('SELECT value FROM works ORDER BY value').fetchall(), rows)
        before = conn.execute('SELECT * FROM store_generation').fetchall()
        for suffix in ('', ' ON CONFLICT(singleton) DO UPDATE SET generation=0'):
            with self.subTest(suffix=suffix), self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT OR REPLACE INTO store_generation VALUES ('store',?,0)" + suffix, ('b' * 32,))
            self.assertEqual(conn.execute('SELECT * FROM store_generation').fetchall(), before)

    def test_exhaustion_conflict_policies(self):
        conn = self.probe()
        step = conn.execute("SELECT sql FROM sqlite_schema WHERE name='store_generation_step'").fetchone()[0]
        conn.execute('DROP TRIGGER store_generation_step')
        conn.execute("INSERT INTO store_generation VALUES ('store',NULL,0)")
        conn.execute('UPDATE store_generation SET generation=9007199254740991')
        conn.execute(step)
        for policy in ('', 'OR IGNORE', 'OR REPLACE', 'OR FAIL'):
            with self.subTest(policy=policy), self.assertRaises(sqlite3.IntegrityError):
                conn.execute('INSERT ' + policy + ' INTO works VALUES (1)')
            self.assertEqual(conn.execute('SELECT * FROM works').fetchall(), [])
            self.assertEqual(self.counter(conn), 9007199254740991)


class RealFamiliesTest(fx.StoreTestCase):
    def test_audit_snapshot_scope(self):
        from gen2.tests.router_fixtures import RouterTestCase
        business = RouterTestCase.state(self, exclude=('audit_events',))
        complete = RouterTestCase.state(self, exclude=())
        before = GenerationTest.counter(self.db)
        self.x("INSERT INTO audit_events (audit_event_id,at,kind,detail) VALUES ('aud_scope001',?,'scope_control','{}')", fx.T)
        self.assertEqual(GenerationTest.counter(self.db), before + 1)
        after = RouterTestCase.state(self, exclude=('audit_events',))
        RouterTestCase.assert_generation_delta(self, business, after, 1)
        self.assertEqual(after, business)
        self.assertNotEqual(RouterTestCase.state(self, exclude=()), complete)
        self.x('UPDATE queue_entries SET priority=2')
        self.assertNotEqual(RouterTestCase.state(self, exclude=('audit_events',)), business)

    def test_representative_writes(self):
        # Intact admission: queue, contracts, normalized facets/obligations,
        # lease/invocation lifecycle and shared works/artifacts.
        for action in (lambda: self.x('UPDATE queue_entries SET priority=priority'),
                       lambda: self.contract(fx.TOPIC, 2),
                       lambda: self.approved_with_obligation(),
                       lambda: self.lease('lease_aaaaaaaa', 1),
                       lambda: self.invocation('inv_aaaaaaaa'),
                       lambda: self.x("INSERT INTO works (work_id,identity_scheme,identity_value,created_at) VALUES ('wrk_aaaaaaaa','doi','10.1/test',?)", fx.T),
                       lambda: self.x("INSERT INTO artifacts (content_hash,size_bytes,media_type,staged_at) VALUES (?,1,'text/plain',?)", fx.h('e'), fx.T)):
            before = GenerationTest.counter(self.db)
            action()
            self.assertGreater(GenerationTest.counter(self.db), before)
