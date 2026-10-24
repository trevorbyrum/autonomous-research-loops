"""Disposable schema-only admission and explicit offline maintenance controls."""
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from gen2.store import api, db
from gen2.tests import test_capture_reader as readers


class LifecycleTest(unittest.TestCase):
    setUp = readers.FileReaderTest.setUp

    def maintain(self, operation):
        self.store.close()
        try:
            api.Store.maintain(self.path, operation)
        finally:
            self.store = api.open_store(self.path)
        return db.generation_state(self.store._conn)

    def test_control(self):
        self.assertEqual(len(db.generation_state(self.store._conn)), 3)
        readers.FileReaderTest.test_control(self)

    def test_maintenance_control(self):
        self.maintain(lambda path: None)
        self.test_control()

    def test_reopen_preserves_proof_and_restore_renews_epoch(self):
        original = db.generation_state(self.store._conn)
        self.store.close()
        image = self.path.with_suffix('.image')
        shutil.copyfile(self.path, image)
        self.store = api.open_store(self.path)
        self.assertEqual(db.generation_state(self.store._conn), original)
        with self.store.transaction():
            self.store.update('queue_entries', {'topic_id': 'fleet-a:t1'}, {'priority': 1})
        restored = self.maintain(lambda path: shutil.copyfile(image, path))
        self.assertIsNotNone(restored[0])
        self.assertNotEqual(restored[0], original[0])
        self.assertEqual(restored[1:], original[1:])
        self.store.close()
        self.store = api.open_store(self.path)
        self.assertEqual(db.generation_state(self.store._conn), restored)
        again = self.maintain(lambda path: shutil.copyfile(image, path))
        self.assertNotIn(again[0], (original[0], restored[0]))
        self.assertEqual(again[1:], original[1:])

    def test_ddl_and_vacuum_change_cookie(self):
        for sql in ('CREATE TABLE transient (value TEXT); DROP TABLE transient;', 'VACUUM;'):
            before = db.generation_state(self.store._conn)
            def operation(path):
                with sqlite3.connect(path, isolation_level=None) as conn:
                    conn.executescript(sql)
            after = self.maintain(operation)
            self.assertNotEqual(after[0], before[0])
            self.assertEqual(after[1], before[1])
            self.assertNotEqual(after[2], before[2])

    def test_open_beside_writer_is_read_only(self):
        before = db.generation_state(self.store._conn)
        self.store._conn.execute('BEGIN IMMEDIATE')
        try:
            pragmas = (*db.OPERATIONAL_PRAGMAS[:-1], ('busy_timeout', '0', 0))
            with patch.object(db, 'OPERATIONAL_PRAGMAS', pragmas), api.open_store(self.path) as second:
                self.assertEqual(db.generation_state(second._conn), before)
                self.assertFalse(second._conn.in_transaction)
            self.assertEqual(db.generation_state(self.store._conn), before)
        finally:
            self.store._conn.execute('ROLLBACK')

    def test_missing_or_incompatible_guards(self):
        conn = self.store._conn
        sql = conn.execute("SELECT sql FROM sqlite_schema WHERE name='store_generation_step'").fetchone()[0]
        for replacement in ('', sql.replace('OLD.generation + 1', 'OLD.generation + 2')):
            conn.execute('DROP TRIGGER store_generation_step')
            if replacement:
                conn.execute(replacement)
            with self.assertRaises(db.StoreOpenError):
                api.open_store(self.path)
            with self.assertRaises(db.StoreOpenError):
                self.store.capture_topic('fleet-a:t1')
            conn.execute('DROP TRIGGER IF EXISTS store_generation_step')
            conn.execute(sql)

    def test_initial_state_has_no_read_side_initialization(self):
        path = self.path.with_name('fresh.db')
        with api.open_store(path, create=True) as fresh:
            cookie = fresh._conn.execute('PRAGMA schema_version').fetchone()[0]
            self.assertEqual(fresh.select('store_generation'), [])
        with api.open_store(path) as fresh:
            self.assertEqual(db.generation_state(fresh._conn), (None, 0, cookie))
            fresh.capture_topic('fleet-a:t1')
            self.assertEqual(fresh.select('store_generation'), [])
        api.Store.maintain(path, lambda path: None)
        with api.open_store(path) as fresh:
            epoch, counter, after_cookie = db.generation_state(fresh._conn)
            self.assertIsNotNone(epoch)
            self.assertEqual((counter, after_cookie), (0, cookie))
            self.assertEqual(len(fresh.select('store_generation')), 1)

    def test_invalid_singleton_no_read_repair(self):
        conn = self.store._conn
        guards = conn.execute("SELECT name,sql FROM sqlite_schema WHERE name IN ('store_generation_no_insert','store_generation_no_delete')").fetchall()
        for name, _ in guards:
            conn.execute('DROP TRIGGER ' + name)
        conn.execute('PRAGMA ignore_check_constraints=ON')
        conn.execute('DELETE FROM store_generation')
        conn.execute("INSERT INTO store_generation VALUES ('other',NULL,0)")
        conn.execute('PRAGMA ignore_check_constraints=OFF')
        for _, sql in guards:
            conn.execute(sql)
        for action in (lambda: api.open_store(self.path), lambda: self.store.capture_topic('fleet-a:t1')):
            with self.assertRaisesRegex(db.StoreOpenError, 'invalid store generation'):
                action()
            self.assertEqual(conn.execute('SELECT * FROM store_generation').fetchall(), [('other', None, 0)])

    def test_failed_maintenance_still_invalidates_admissible_result(self):
        before = db.generation_state(self.store._conn)
        def failed(path):
            raise RuntimeError('maintenance failed')
        with self.assertRaisesRegex(RuntimeError, 'maintenance failed'):
            self.maintain(failed)
        after = db.generation_state(self.store._conn)
        self.assertNotEqual(after[0], before[0])
        self.assertEqual(after[1:], before[1:])

    def test_maintenance_refuses_incompatible_result(self):
        self.store.close()
        def broken(path):
            with sqlite3.connect(path) as conn:
                conn.execute('DROP TRIGGER store_generation_step')
        with self.assertRaises(db.StoreOpenError):
            api.Store.maintain(self.path, broken)
        with self.assertRaises(db.StoreOpenError):
            api.open_store(self.path)

    def test_maintenance_failure_rolls_back_bootstrap(self):
        path = self.path.with_name('empty.db')
        api.open_store(path, create=True).close()
        connect = sqlite3.connect
        def broken_connect(*args, **kwargs):
            conn = connect(*args, **kwargs)
            def unavailable(_):
                raise RuntimeError('identity source unavailable')
            conn.create_function('randomblob', 1, unavailable)
            return conn
        with patch.object(sqlite3, 'connect', broken_connect):
            with self.assertRaises(sqlite3.OperationalError):
                api.Store.maintain(path, lambda path: None)
        with api.open_store(path) as fresh:
            self.assertEqual(fresh.select('store_generation'), [])
            self.assertEqual(db.generation_state(fresh._conn)[:2], (None, 0))

    def test_retained_store_ordered_upgrade(self):
        path = self.path.with_name('retained.db')
        parts = db.schema_parts()
        with sqlite3.connect(path, isolation_level=None) as conn:
            conn.executescript(''.join(p.read_text() for p in parts[:-1]))
            conn.execute("INSERT INTO queue_entries (topic_id,fleet_id,priority,status,created_at,updated_at) VALUES ('fleet-a:t1','fleet-a',7,'awaiting_brief_confirmation','2026-10-24T00:00:00Z','2026-10-24T00:00:00Z')")
            with self.assertRaises(db.StoreOpenError):
                api.open_store(path)
            conn.executescript('BEGIN IMMEDIATE;\n' + parts[-1].read_text() + '\nCOMMIT;')
            self.assertEqual(conn.execute('SELECT * FROM store_generation').fetchall(), [])
        with api.open_store(path) as retained:
            self.assertEqual(db.generation_state(retained._conn)[:2], (None, 0))
            self.assertEqual(retained._conn.execute('SELECT priority FROM queue_entries').fetchall(), [(7,)])
            with retained.transaction():
                retained.update('queue_entries', {'topic_id': 'fleet-a:t1'}, {'priority': 7})
            self.assertEqual(db.generation_state(retained._conn)[:2], (None, 1))
