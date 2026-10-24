"""Disposable durable admission, offline restore and DDL lifecycle controls."""
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from gen2.store import api, db
from gen2.tests import test_capture_reader as readers


class LifecycleTest(unittest.TestCase):
    setUp = readers.FileReaderTest.setUp

    def test_control(self):
        self.assertEqual(len(db.generation_state(self.store._conn)), 3)
        readers.FileReaderTest.test_control(self)

    def test_reopen_and_restore_renew_epoch(self):
        original = db.generation_state(self.store._conn)
        self.store.close()
        image = self.path.with_suffix('.image')
        shutil.copyfile(self.path, image)
        self.store = api.open_store(self.path)
        reopened = db.generation_state(self.store._conn)
        self.assertNotEqual(reopened[0], original[0])
        self.assertEqual(reopened[1:], original[1:])
        self.store._conn.execute('UPDATE queue_entries SET priority=priority')
        self.store.close()
        shutil.copyfile(image, self.path)  # restore in place, all handles closed
        self.store = api.open_store(self.path)
        restored = db.generation_state(self.store._conn)
        self.assertNotIn(restored[0], (original[0], reopened[0]))
        self.assertEqual(restored[1:], original[1:])

    def test_ddl_and_vacuum_change_cookie(self):
        conn = self.store._conn
        for operation in ('CREATE TABLE transient (value TEXT); DROP TABLE transient;', 'VACUUM;'):
            before = db.generation_state(conn)
            conn.executescript(operation)
            db.check_schema_identity(conn)
            after = db.generation_state(conn)
            self.assertEqual(after[:2], before[:2])
            self.assertNotEqual(after[2], before[2])

    def test_epoch_admission_requires_writer_fence(self):
        before = db.generation_state(self.store._conn)
        self.store._conn.execute('BEGIN IMMEDIATE')
        try:
            pragmas = (*db.OPERATIONAL_PRAGMAS[:-1], ('busy_timeout', '0', 0))
            with patch.object(db, 'OPERATIONAL_PRAGMAS', pragmas):
                with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                    api.open_store(self.path)
            self.assertEqual(db.generation_state(self.store._conn), before)
        finally:
            self.store._conn.execute('ROLLBACK')

    def test_missing_or_incompatible_guards(self):
        conn = self.store._conn
        sql = conn.execute("SELECT sql FROM sqlite_schema WHERE name='capture_generation_works_insert'").fetchone()[0]
        for replacement in ('', sql.replace('generation + 1', 'generation + 2')):
            conn.execute('DROP TRIGGER capture_generation_works_insert')
            if replacement:
                conn.execute(replacement)
            with self.assertRaises(db.StoreOpenError):
                api.open_store(self.path)
            with self.assertRaises(db.StoreOpenError):
                self.store.capture_topic('fleet-a:t1')
            conn.execute('DROP TRIGGER IF EXISTS capture_generation_works_insert')
            conn.execute(sql)

    def test_missing_singleton_no_lazy_initialization(self):
        conn = self.store._conn
        guard = conn.execute("SELECT sql FROM sqlite_schema WHERE name='store_generation_no_delete'").fetchone()[0]
        conn.execute('DROP TRIGGER store_generation_no_delete')
        conn.execute('DELETE FROM store_generation')
        conn.execute(guard)
        for action in (lambda: api.open_store(self.path), lambda: self.store.capture_topic('fleet-a:t1')):
            with self.assertRaisesRegex(db.StoreOpenError, 'missing store generation'):
                action()
            self.assertEqual(conn.execute('SELECT * FROM store_generation').fetchall(), [])

    def test_retained_store_ordered_upgrade(self):
        path = self.path.with_name('retained.db')
        parts = db.schema_parts()
        with sqlite3.connect(path, isolation_level=None) as conn:
            conn.executescript(''.join(p.read_text() for p in parts[:-1]))
            conn.execute("INSERT INTO queue_entries (topic_id,fleet_id,priority,status,created_at,updated_at) VALUES ('fleet-a:t1','fleet-a',7,'awaiting_brief_confirmation','2026-10-24T00:00:00Z','2026-10-24T00:00:00Z')")
            with self.assertRaises(db.StoreOpenError):
                api.open_store(path)
            conn.executescript('BEGIN IMMEDIATE;\n' + parts[-1].read_text() + '\nCOMMIT;')
        with api.open_store(path) as retained:
            self.assertEqual(db.generation_state(retained._conn)[1], 0)
            self.assertEqual(retained._conn.execute('SELECT priority FROM queue_entries').fetchall(), [(7,)])
            retained._conn.execute('UPDATE queue_entries SET priority=priority')
            self.assertEqual(db.generation_state(retained._conn)[1], 1)
