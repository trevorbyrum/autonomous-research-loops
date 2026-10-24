"""Store transaction invalidation and the retained generation integrity guards."""
import sqlite3
import unittest

from gen2.store import api, db
from gen2.tests import store_fixtures as fx


class GenerationTest(unittest.TestCase):
    def setUp(self):
        self.db = fx.connect()
        self.addCleanup(self.db.close)
        self.db.execute("INSERT INTO store_generation SELECT 'store',NULL,0 WHERE NOT EXISTS (SELECT 1 FROM store_generation)")

    @staticmethod
    def counter(conn):
        row = conn.execute('SELECT generation FROM store_generation').fetchone()
        return row[0] if row else 0

    def test_guard_control(self):
        self.db.execute('UPDATE store_generation SET generation=generation+1')
        self.assertEqual(self.db.execute('SELECT singleton,epoch FROM store_generation').fetchall(), [('store', None)])

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



class CounterTest(unittest.TestCase):
    def setUp(self):
        self.db = fx.connect()
        self.store = api.adopt_in_memory(self.db)
        self.addCleanup(self.store.close)

    def queue(self):
        self.store.insert('queue_entries', dict(topic_id=fx.TOPIC, fleet_id='fleet-a', priority=1,
            status='awaiting_brief_confirmation', created_at=fx.T, updated_at=fx.T))

    def state(self):
        return {t: self.store.select(t) for t in ('queue_entries', 'works', 'store_generation')}

    def test_control(self):
        # Initialized metadata gives a separate accepted path for bootstrap,
        # call-site and once-only mutants without asserting their property.
        self.db.execute("INSERT INTO store_generation VALUES ('store',NULL,0)")
        with self.store.transaction():
            self.queue()
        self.assertEqual(self.store.select('queue_entries')[0]['priority'], 1)

    def test_update_control(self):
        self.db.execute("INSERT INTO queue_entries (topic_id,fleet_id,priority,status,created_at,updated_at) VALUES (?, 'fleet-a',1,'awaiting_brief_confirmation',?,?)", (fx.TOPIC, fx.T, fx.T))
        self.db.execute("INSERT INTO store_generation VALUES ('store',NULL,0)")
        with self.store.transaction():
            self.store.update('queue_entries', {'topic_id': fx.TOPIC}, {'priority': 2})
        self.assertEqual(self.store.select('queue_entries')[0]['priority'], 2)

    def test_first_write(self):
        self.assertEqual(self.store.select('store_generation'), [])
        try:
            with self.store.transaction():
                self.queue()
        except api.StoreWriteError as exc:
            self.fail(f'first covered write must bootstrap: {exc}')
        self.assertEqual(db.generation_state(self.db)[:2], (None, 1))
        self.assertEqual(self.store.select('queue_entries')[0]['priority'], 1)

    def test_once_and_reset(self):
        with self.store.transaction():
            self.queue()
            self.store.insert('works', dict(work_id='wrk_aaaaaaaa', identity_scheme='doi', identity_value='10.1/test', created_at=fx.T))
            self.store.update('queue_entries', {'topic_id': fx.TOPIC}, {'priority': 2})
        self.assertEqual(db.generation_state(self.db)[:2], (None, 1))
        self.assertEqual(self.store.select('queue_entries')[0]['priority'], 2)
        self.assertEqual(len(self.store.select('works')), 1)
        with self.store.transaction():
            self.store.update('queue_entries', {'topic_id': fx.TOPIC}, {'priority': 2})
            self.store.advance('queue_entries', {'topic_id': fx.TOPIC}, 'state_revision', expected=0)
        self.assertEqual(db.generation_state(self.db)[:2], (None, 2))
        self.assertEqual(self.store.select('queue_entries')[0]['state_revision'], 1)

    def test_rollback_and_zero_row(self):
        before = self.state()
        with self.assertRaisesRegex(RuntimeError, 'rollback'), self.store.transaction():
            self.queue()
            raise RuntimeError('rollback')
        self.assertEqual(self.state(), before)
        with self.assertRaises(api.StoreWriteError), self.store.transaction():
            self.store.update('queue_entries', {'topic_id': fx.TOPIC}, {'priority': 2})
        self.assertEqual(self.state(), before)
        self.test_first_write()  # a new successful transaction must still bump

    def test_uncovered_and_reads(self):
        with self.store.transaction():
            self.store.insert('config_bundles', dict(bundle_hash=fx.h('c'), version=1, document=fx.BUNDLE,
                status='active', activated_at=fx.T))
        with self.store.transaction():
            self.assertEqual(self.store.select('config_bundles')[0]['version'], 1)
            self.assertEqual(self.store.next_in_sequence('queue_entries', 'state_revision', {}), 1)
        self.store.capture_topic(fx.TOPIC)
        self.assertEqual(self.store.select('store_generation'), [])

    def test_missing_singleton_write_refuses(self):
        self.db.execute("CREATE TRIGGER suppress_bootstrap BEFORE INSERT ON store_generation BEGIN SELECT RAISE(IGNORE); END")
        with self.assertRaises(api.StoreWriteError), self.store.transaction():
            self.queue()
        self.assertEqual(self.state(), {'queue_entries': [], 'works': [], 'store_generation': []})

    def test_exhaustion(self):
        self.test_first_write()
        step = self.db.execute("SELECT sql FROM sqlite_schema WHERE name='store_generation_step'").fetchone()[0]
        self.db.execute('DROP TRIGGER store_generation_step')
        self.db.execute('UPDATE store_generation SET generation=9007199254740991')
        self.db.execute(step)
        before = self.state()
        with self.assertRaises(sqlite3.IntegrityError), self.store.transaction():
            self.store.update('queue_entries', {'topic_id': fx.TOPIC}, {'priority': 2})
        self.assertEqual(self.state(), before)
