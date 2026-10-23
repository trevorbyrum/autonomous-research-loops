"""Checked WAL readers, deterministic interleaving and failure cleanup."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gen2.store import api, capture, compat, db
from gen2.tests.router_fixtures import TOPIC
from gen2.tests.test_extraction_records import RecordCase
from gen2.tests.test_topic_capture import group


class MemoryReaderTest(RecordCase):
    def test_dml_is_prohibited(self):
        read = capture.read
        def guarded(conn, columns, topic):
            self.assertTrue(conn.in_transaction)
            self.assertEqual(conn.execute('PRAGMA query_only').fetchone(), (1,))
            for sql in ('INSERT INTO works DEFAULT VALUES', 'DELETE FROM works WHERE 0',
                        'UPDATE queue_entries SET priority=priority WHERE 0'):
                with self.assertRaisesRegex(sqlite3.OperationalError, 'readonly'):
                    conn.execute(sql)
            return read(conn, columns, topic)
        with patch.object(capture, 'read', guarded):
            self.assertEqual(self.store.capture_topic(TOPIC).topic_id, TOPIC)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute('PRAGMA query_only').fetchone(), (0,))

    def test_failure_releases_memory_reader(self):
        with patch.object(capture, 'read', side_effect=RuntimeError('capture failed')):
            with self.assertRaisesRegex(RuntimeError, 'capture failed'):
                self.store.capture_topic(TOPIC)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute('PRAGMA query_only').fetchone(), (0,))
        with self.store.transaction():
            self.store.update('queue_entries', {'topic_id': TOPIC}, {'priority': 3})
        self.assertEqual(self.store.capture_topic(TOPIC).topic_id, TOPIC)


class FileReaderTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'authoritative.db'
        self.store = api.open_store(self.path, create=True)
        self.addCleanup(lambda: self.store.close())
        with self.store.transaction():
            self.store.insert('queue_entries', dict(topic_id=TOPIC, fleet_id=TOPIC.split(':')[0], priority=1,
                status='awaiting_brief_confirmation', created_at='2026-10-23T00:00:00Z', updated_at='2026-10-23T00:00:00Z'))
        self.store._conn.execute('PRAGMA busy_timeout=0')

    def test_control(self):
        snap = self.store.capture_topic(TOPIC)
        self.assertEqual(group(snap, 'queue_entries').rows[0][2], 1)
        self.assertFalse(self.store._conn.in_transaction)
        self.assertTrue(capture.input_hash(snap, 'native').startswith('sha256:'))

    def test_coherent_while_writer_commits(self):
        read, readers = capture.read, []
        def interleave(conn, columns, topic):
            readers.append(conn)
            self.assertIsNot(conn, self.store._conn)
            self.assertEqual(conn.execute('PRAGMA query_only').fetchone(), (1,))
            self.assertEqual(conn.execute('SELECT priority FROM queue_entries').fetchall(), [(1,)])
            with self.store.transaction():
                self.store.update('queue_entries', {'topic_id': TOPIC}, {'priority': 2})
            return read(conn, columns, topic)
        with patch.object(capture, 'read', interleave):
            snap = self.store.capture_topic(TOPIC)
        self.assertEqual(group(snap, 'queue_entries').rows[0][2], 1)
        self.assertEqual(group(self.store.capture_topic(TOPIC), 'queue_entries').rows[0][2], 2)
        with self.assertRaises(sqlite3.ProgrammingError):
            readers[0].execute('SELECT 1')

    def test_failure_closes_file_reader(self):
        readers = []
        def fail(conn, *_):
            readers.append(conn)
            raise RuntimeError('mid-capture')
        with patch.object(capture, 'read', fail):
            with self.assertRaisesRegex(RuntimeError, 'mid-capture'):
                self.store.capture_topic(TOPIC)
        with self.assertRaises(sqlite3.ProgrammingError):
            readers[0].execute('SELECT 1')
        self.test_control()

    def test_reopened_store(self):
        expected = self.store.capture_topic(TOPIC)
        self.store.close()
        self.store = api.open_store(self.path)
        self.assertEqual(self.store.capture_topic(TOPIC), expected)

    def test_reader_connection_contract(self):
        read = capture.read
        def checked(conn, columns, topic):
            self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone(), ('wal',))
            for pragma in ('foreign_keys', 'recursive_triggers', 'query_only'):
                self.assertEqual(conn.execute(f'PRAGMA {pragma}').fetchone(), (1,))
            self.assertEqual(conn.execute('PRAGMA synchronous').fetchone(), (2,))
            self.assertEqual(conn.execute('PRAGMA busy_timeout').fetchone(), (db.BUSY_TIMEOUT_MS,))
            with self.assertRaisesRegex(sqlite3.OperationalError, 'readonly'):
                conn.execute('UPDATE queue_entries SET priority=priority')
            return read(conn, columns, topic)
        with patch.object(capture, 'read', checked):
            self.test_control()

    def test_schema_and_connection_failures_close_reader(self):
        connect = sqlite3.connect
        readers = []
        def track(*args, **kwargs):
            conn = connect(*args, **kwargs)
            if '?mode=ro' in str(args[0]):
                readers.append(conn)
            return conn
        for gate in ('check_schema_identity', 'compatibility'):
            with self.subTest(gate=gate), patch.object(db.sqlite3, 'connect', track):
                owner, name = (db, gate) if gate != 'compatibility' else (compat, 'check_connection')
                with patch.object(owner, name, side_effect=db.StoreOpenError('refused gate')):
                    with self.assertRaisesRegex(db.StoreOpenError, 'refused gate'):
                        self.store.capture_topic(TOPIC)
                with self.assertRaises(sqlite3.ProgrammingError):
                    readers[-1].execute('SELECT 1')
        self.test_control()

    def test_schema_drift_refuses(self):
        self.store._conn.execute('CREATE TABLE unexpected (value TEXT)')
        with self.assertRaisesRegex(db.StoreOpenError, 'schema is not'):
            self.store.capture_topic(TOPIC)

    def test_failed_pragma_readbacks_refuse(self):
        connect = sqlite3.connect
        for pragma in ('query_only', 'synchronous', 'busy_timeout'):
            readers = []
            class Misreported:
                def __init__(self, conn):
                    self.conn = conn
                def execute(self, sql, *args):
                    return self.conn.execute('SELECT 0') if sql == 'PRAGMA ' + pragma else self.conn.execute(sql, *args)
                def executescript(self, sql):
                    return self.conn.executescript(sql)
                def close(self):
                    self.conn.close()
            def report(*args, **kwargs):
                conn = connect(*args, **kwargs)
                if '?mode=ro' in str(args[0]):
                    readers.append(conn)
                    return Misreported(conn)
                return conn
            with self.subTest(pragma=pragma), patch.object(db.sqlite3, 'connect', report):
                with self.assertRaises(db.StoreOpenError):
                    self.store.capture_topic(TOPIC)
                with self.assertRaises(sqlite3.ProgrammingError):
                    readers[-1].execute('SELECT 1')

    def test_nonwal_refuses(self):
        self.store._conn.execute('PRAGMA journal_mode=DELETE')
        with self.assertRaisesRegex(db.StoreOpenError, 'WAL'):
            self.store.capture_topic(TOPIC)

    def test_file_replacement_refuses(self):
        replacement = self.path.with_name('replacement.db')
        with api.open_store(replacement, create=True):
            pass
        replacement.replace(self.path)
        with self.assertRaisesRegex(db.StoreOpenError, 'replaced'):
            self.store.capture_topic(TOPIC)

    def test_file_identity_mismatch_refuses(self):
        path, (device, inode) = self.store._capture_file
        self.store._capture_file = path, (device, inode + 1)
        with self.assertRaisesRegex(db.StoreOpenError, 'replaced'):
            self.store.capture_topic(TOPIC)
