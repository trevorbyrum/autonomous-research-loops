"""Store transaction invalidation and the retained generation integrity guards."""
import re
import sqlite3
import unittest

from gen2.store import api, db
from gen2.tests import store_fixtures as fx

STEP = "store generation must advance once or renew epoch; exhaustion refuses writes"


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
        with self.assertRaisesRegex(sqlite3.IntegrityError, "store generation singleton cannot be inserted"):
            self.db.execute("INSERT INTO store_generation VALUES ('store',?,0)", ('a' * 32,))
        self.assertEqual(self.db.execute('SELECT * FROM store_generation').fetchall(), [])

    def test_delete_protection(self):
        before = self.db.execute('SELECT * FROM store_generation').fetchall()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "store generation singleton cannot be deleted"):
            self.db.execute('DELETE FROM store_generation')
        self.assertEqual(self.db.execute('SELECT * FROM store_generation').fetchall(), before)

    def test_step_protection(self):
        self.db.execute('SAVEPOINT s')  # the admitted ordinary increment, which the singleton refusal below pairs with
        self.db.execute('UPDATE store_generation SET generation=generation+1')
        self.assertEqual(self.db.execute('SELECT * FROM store_generation').fetchall(), [('store', None, 1)])
        self.db.execute('ROLLBACK TO s')
        self.db.execute('RELEASE s')
        for assignment in ('generation=generation', 'generation=generation-1', 'generation=generation+2', "singleton='other'",
                           "singleton='other', generation=generation+1"):
            with self.subTest(assignment=assignment):
                self.db.execute('SAVEPOINT s')
                before = self.db.execute('SELECT * FROM store_generation').fetchall()
                try:
                    with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(STEP)):
                        self.db.execute('UPDATE store_generation SET ' + assignment)
                    self.assertEqual(self.db.execute('SELECT * FROM store_generation').fetchall(), before)
                finally:
                    self.db.execute('ROLLBACK TO s')
                    self.db.execute('RELEASE s')
        self.db.execute("UPDATE store_generation SET epoch=?", ('a' * 32,))
        # epoch=NULL refuses under the step trigger, not under NOT NULL.
        before = self.db.execute('SELECT * FROM store_generation').fetchall()
        with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(STEP)):
            self.db.execute('UPDATE store_generation SET epoch=NULL')
        self.assertEqual(self.db.execute('SELECT * FROM store_generation').fetchall(), before)

    def test_constraints(self):
        self.db.execute('DROP TRIGGER IF EXISTS store_generation_step')
        self.db.execute('DROP TRIGGER IF EXISTS store_generation_no_insert')
        self.db.execute('SAVEPOINT s')  # the admitted singleton: same epoch and generation as the refused insert, into an emptied table
        self.db.execute('DROP TRIGGER store_generation_no_delete')
        self.db.execute('DELETE FROM store_generation')
        self.db.execute("INSERT INTO store_generation VALUES ('store',?,0)", ('a' * 32,))
        self.assertEqual(self.db.execute('SELECT * FROM store_generation').fetchall(), [('store', 'a' * 32, 0)])
        self.db.execute('ROLLBACK TO s')
        self.db.execute('RELEASE s')
        for sql, fragment in (("INSERT INTO store_generation VALUES ('other','" + 'a' * 32 + "',0)", "singleton = 'store'"),
                    ('UPDATE store_generation SET generation=-1', "generation BETWEEN 0 AND 9007199254740991"),
                    ('UPDATE store_generation SET generation=9007199254740992', "generation BETWEEN 0 AND 9007199254740991"),
                    ("UPDATE store_generation SET epoch=''", "length(epoch) = 32"),
                    ("UPDATE store_generation SET epoch='" + 'G' * 32 + "'", "length(epoch) = 32")):
            before = self.db.execute('SELECT * FROM store_generation').fetchall()
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                self.db.execute(sql)
            self.assertEqual(self.db.execute('SELECT * FROM store_generation').fetchall(), before)



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
        with self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(STEP)), self.store.transaction():
            self.store.update('queue_entries', {'topic_id': fx.TOPIC}, {'priority': 2})
        self.assertEqual(self.state(), before)
