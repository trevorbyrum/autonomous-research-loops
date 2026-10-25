"""Freshness fences on disposable WAL stores; explicit interleaving barriers."""
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock, patch

from gen2.router.boundary import Refusal
from gen2.router.service import Router
from gen2.store import api, capture, db
from gen2.tests import router_crash_child as crash, router_fixtures as rf

DEADLINE = '2026-09-27T11:00:00Z'
LIVE = '2026-09-27T10:59:59.999999999Z'


class FreshnessTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.world = crash.World(Path(directory.name))
        try:
            self.world.setUp()
        except Exception as exc:
            self.fail(f'durable Router admission must succeed: {exc!r}')
        self.addCleanup(lambda: self.world.db.close())
        self.addCleanup(lambda: self.world.store.close())
        try:
            self.world.to_queued()
        except Exception as exc:
            self.fail(f'contract admission must succeed: {exc!r}')
        self.store, self.router = self.world.store, self.world.router
        self.invocation_id = self.world.started('inv_freshness001', deadline_at=DEADLINE)['invocation_id']
        self.other = api.open_store(self.world.directory / 'store.sqlite3')
        self.addCleanup(self.other.close)

    def token(self):
        try:
            return self.store.capture_topic(rf.TOPIC).freshness
        except Exception as exc:
            self.fail(f'freshness capture must succeed: {exc!r}')

    def update(self, store, topic=rf.TOPIC, priority=7):
        store.update('queue_entries', {'topic_id': topic}, {'priority': priority})

    def refused(self, token, kind=api.StaleInput):
        before = self.world.state()
        error = None
        try:
            with self.store.transaction(freshness=token):
                self.update(self.store)
        except Exception as exc:
            error = exc
        self.assertIsInstance(error, kind)
        self.assertEqual(self.world.state(), before)
        self.assertFalse(self.store._conn.in_transaction)
        return error

    def test_snapshot_token_and_first_write(self):
        before = self.world.state()
        token = self.token()
        stat = self.world.directory.joinpath('store.sqlite3').stat()
        self.assertEqual(token.file[1], (stat.st_dev, stat.st_ino))
        self.assertEqual(token.generation, db.generation_state(self.store._conn))
        with self.assertRaises(FrozenInstanceError):
            token.file = None
        self.assertEqual(self.world.state(), before)
        with self.store.transaction(freshness=token):
            self.update(self.store)
            self.update(self.store, priority=8)
        self.assertEqual(db.generation_state(self.store._conn)[1], token.generation[1] + 1)
        self.assertEqual(self.store.select('queue_entries', {'topic_id': rf.TOPIC})[0]['priority'], 8)

    def test_writer_commits_inside_reader_snapshot(self):
        read = capture.read
        original = self.token()
        def barrier(conn, columns, topic):
            self.assertTrue(conn.in_transaction)
            with self.other.transaction():
                self.update(self.other)
            return read(conn, columns, topic)
        with patch.object(capture, 'read', barrier):
            raw = self.store.capture_topic(rf.TOPIC)
        self.assertEqual(raw.freshness, original)
        table = next(t for t in raw.tables if t.name == 'queue_entries')
        self.assertEqual(table.rows[0][table.columns.index('priority')], 1)
        self.refused(raw.freshness, api.GenerationMismatch)

    def test_unrelated_topic_and_rollback(self):
        token = self.token()
        with self.assertRaisesRegex(RuntimeError, 'rollback'), self.other.transaction():
            self.update(self.other, rf.OTHER)
            raise RuntimeError('rollback')
        self.assertEqual(self.token(), token)
        with self.store.transaction(freshness=token):
            pass
        with self.other.transaction():
            self.update(self.other, rf.OTHER)
            self.update(self.other, rf.OTHER, 8)
        self.assertEqual(self.token().generation[1], token.generation[1] + 1)
        self.refused(token, api.GenerationMismatch)

    def test_cookie_change_without_generation_change(self):
        token = self.token()
        self.other._conn.executescript('CREATE TABLE transient(x); DROP TABLE transient;')
        self.assertEqual(self.token().generation[:2], token.generation[:2])
        error = self.refused(token)
        self.assertNotIsInstance(error, api.GenerationMismatch)
        self.other._conn.execute(f'PRAGMA schema_version={token.generation[2] - 1}')
        self.assertNotIsInstance(self.refused(token), api.GenerationMismatch)

    def test_restore_epoch(self):
        token = self.token()
        self.other.close()
        self.store.close()
        self.world.db.close()
        path = self.world.directory / 'store.sqlite3'
        image = path.with_suffix('.image')
        shutil.copyfile(path, image)
        api.Store.maintain(path, lambda target: shutil.copyfile(image, target))
        self.store = self.world.store = api.open_store(path)
        self.world.db = self.store._conn
        self.assertEqual(self.token().generation[1:], token.generation[1:])
        self.assertEqual(self.token().file, token.file)
        self.refused(token, api.GenerationMismatch)

    def test_replacement_and_missing_file(self):
        token = self.token()
        path = self.world.directory / 'store.sqlite3'
        self.other.close()
        self.store._conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        image = path.with_suffix('.replacement')
        shutil.copyfile(path, image)
        image.replace(path)
        self.assertNotEqual(path.stat().st_ino, token.file[1][1])
        self.assertNotIsInstance(self.refused(token), api.GenerationMismatch)
        path.unlink()
        self.assertNotIsInstance(self.refused(token), api.GenerationMismatch)

    def run_operation(self, prepare, commit):
        try:
            return self.router._commit_dossier_inputs(topic_id=rf.TOPIC, invocation_id=self.invocation_id,
                history='native', prepare=prepare, commit=commit)
        except Refusal:
            raise
        except Exception as exc:
            self.fail(f'operation escaped its typed failure path: {exc!r}')

    def test_zero_one_two_recaptures_and_audit(self):
        for conflicts in range(3):
            captured, committed = [], []
            def prepare(inputs):
                self.assertFalse(self.store._conn.in_transaction)
                captured.append(inputs)
                if len(captured) <= conflicts:
                    with self.other.transaction():
                        self.update(self.other, rf.OTHER)
                return inputs.input_hash
            def commit(prepared, now):
                self.assertTrue(self.store._conn.in_transaction)
                self.assertEqual(prepared, captured[-1].input_hash)
                committed.append(now)
                self.update(self.store)
                return 'written'
            self.assertEqual(self.run_operation(prepare, commit), 'written')
            self.assertEqual((len(captured), len(committed)), (conflicts + 1, 1))
            audits = self.store.select('audit_events', {'kind': 'dossier_input_recaptures'})
            self.assertEqual(audits[-1]['detail'], {'recaptures': conflicts})
            self.assertEqual((audits[-1]['topic_id'], audits[-1]['at']), (rf.TOPIC, committed[0]))

    def test_exhaustion_has_only_audit_effect(self):
        barriers, before = [], []
        def prepare(inputs):
            barriers.append(inputs)
            self.assertLessEqual(len(barriers), 3, 'contention must never start a fourth attempt')
            with self.other.transaction():
                self.update(self.other, rf.OTHER)
            before[:] = [self.world.state()]
        commit = Mock(side_effect=AssertionError('stale operation ran'))
        with self.assertRaises(Refusal) as error:
            self.run_operation(prepare, commit)
        self.assertEqual((error.exception.reason, len(barriers), commit.call_count), ('stale_inputs', 3, 0))
        self.world.assert_audited_state(before[0], 1)
        self.assertEqual(self.store.select('audit_events')[-1]['detail'], {'recaptures': 2})

    def test_expiry_prevents_capture_preparation_and_recapture(self):
        read = self.store.capture_topic
        for stage in ('before_capture', 'after_capture', 'mismatch', 'prepare'):
            with self.subTest(stage=stage):
                clock = {'now': DEADLINE if stage == 'before_capture' else LIVE}
                self.router._clock = lambda: clock['now']
                before = [self.world.state()]
                def capture_at_deadline(topic):
                    raw = read(topic)
                    if stage == 'after_capture':
                        clock['now'] = DEADLINE
                    return raw
                def prepare_at_deadline(inputs):
                    if stage == 'mismatch':
                        with self.other.transaction():
                            self.update(self.other, rf.OTHER)
                        before[:] = [self.world.state()]
                    clock['now'] = DEADLINE
                prepared = Mock(side_effect=prepare_at_deadline)
                committed = Mock(side_effect=AssertionError('expired operation committed'))
                with patch.object(self.store, 'capture_topic', side_effect=capture_at_deadline) as captured:
                    with self.assertRaises(Refusal) as error:
                        self.run_operation(prepared, committed)
                self.assertEqual(error.exception.reason, 'deadline_passed')
                expected = {'before_capture': (0, 0, 0), 'after_capture': (1, 0, 0)}.get(stage, (1, 1, 0))
                self.assertEqual((captured.call_count, prepared.call_count, committed.call_count), expected)
                self.world.assert_audited_state(before[0], 1)
                self.assertEqual(self.store.select('audit_events')[-1]['detail'], {'recaptures': 0})

    def test_deadline_crossing_while_waiting_for_writer_fence(self):
        for expires in (False, True):
            with self.subTest(expires=expires), ThreadPoolExecutor(1) as pool:
                clock, issued = {'now': LIVE}, threading.Event()
                def admitted():
                    router = Router.open(self.world.directory / 'store.sqlite3', self.world.spool, clock=lambda: clock['now'])
                    router._store._conn.set_trace_callback(lambda sql: issued.set() if sql == 'BEGIN IMMEDIATE' else None)
                    return router
                router = pool.submit(admitted).result(timeout=10)
                prepared = Mock(return_value='prepared')
                def commit(value, now):
                    self.assertEqual((value, now), ('prepared', LIVE))
                    self.update(router._store)
                    return 'written'
                committed = Mock(side_effect=commit)
                before = self.world.state()
                try:
                    self.other._conn.execute('BEGIN IMMEDIATE')
                    pending = pool.submit(router._commit_dossier_inputs, rf.TOPIC, invocation_id=self.invocation_id,
                        history='native', prepare=prepared, commit=committed)
                    self.assertTrue(issued.wait(10), 'operation never requested its writer fence')
                    clock['now'] = DEADLINE if expires else LIVE
                    self.other._conn.execute('ROLLBACK')
                    try:
                        result = pending.result(timeout=10)
                    except Exception as exc:
                        self.assertIsInstance(exc, Refusal)
                        self.assertTrue(expires)
                        self.assertEqual(exc.reason, 'deadline_passed')
                    else:
                        self.assertFalse(expires)
                        self.assertEqual(result, 'written')
                        self.assertEqual(self.store.select('queue_entries', {'topic_id': rf.TOPIC})[0]['priority'], 7)
                    self.assertEqual((prepared.call_count, committed.call_count), (1, int(not expires)))
                    if expires:
                        self.world.assert_audited_state(before, 1)
                    self.assertEqual(self.store.select('audit_events')[-1]['detail'], {'recaptures': 0})
                finally:
                    if self.other._conn.in_transaction:
                        self.other._conn.execute('ROLLBACK')
                    pool.submit(router.close).result(timeout=10)

    def test_deadline_authority_requires_own_admitted_invocation(self):
        before = self.world.state()
        for topic, invocation in ((rf.TOPIC, 'inv_missing001'), (rf.OTHER, self.invocation_id),
                                  ('fleet-a:t0', self.invocation_id)):
            error = None
            try:
                self.router._commit_dossier_inputs(topic, invocation_id=invocation, history='native',
                    prepare=Mock(side_effect=AssertionError('invalid caller prepared')), commit=Mock())
            except Exception as exc:
                error = exc
            self.assertIsInstance(error, Refusal)
            self.assertEqual(error.reason, 'unknown_invocation')
        self.assertEqual(self.world.state(), before)

    def test_schema_and_semantic_refusals_are_not_retried(self):
        def schema(inputs):
            self.other._conn.executescript('CREATE TABLE transient(x); DROP TABLE transient;')
        for prepare, failure in ((schema, 'stale_inputs'), (lambda inputs: None, 'lease_not_current')):
            prepared = Mock(side_effect=prepare)
            def refuse(*args):
                self.update(self.store)
                raise Refusal('lease_not_current', 'expired')
            committed = Mock(side_effect=refuse)
            before = self.world.state()
            with self.assertRaises(Refusal) as error:
                self.run_operation(prepared, committed)
            self.assertEqual((error.exception.reason, prepared.call_count), (failure, 1))
            self.assertEqual(committed.call_count, int(failure == 'lease_not_current'))
            if failure == 'stale_inputs':
                self.assertEqual(self.world.state(), before)
            else:
                self.world.assert_audited_state(before, 1)
                self.assertEqual(self.store.select('audit_events')[-1]['detail'], {'recaptures': 0})

    def test_preparation_refusal_after_one_recapture(self):
        attempts = []
        def prepare(inputs):
            attempts.append(inputs)
            if len(attempts) == 1:
                with self.other.transaction():
                    self.update(self.other, rf.OTHER)
            else:
                raise Refusal('no_approved_contract', 'changed')
        commit = Mock(side_effect=AssertionError('preparation refused'))
        with self.assertRaises(Refusal) as error:
            self.run_operation(prepare, commit)
        self.assertEqual((error.exception.reason, len(attempts), commit.call_count), ('no_approved_contract', 2, 0))
        self.assertEqual(self.store.select('audit_events')[-1]['detail'], {'recaptures': 1})

    def test_inode_refusal_does_not_write_to_replaced_handle(self):
        before = self.world.state()
        def prepare(inputs):
            self.other.close()
            path = self.world.directory / 'store.sqlite3'
            self.store._conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            image = path.with_suffix('.replacement')
            shutil.copyfile(path, image)
            image.replace(path)
        commit = Mock(side_effect=AssertionError('replaced file was used'))
        with self.assertRaises(Refusal) as error:
            self.run_operation(prepare, commit)
        self.assertEqual((error.exception.reason, commit.call_count), ('stale_inputs', 0))
        self.assertEqual(self.world.state(), before)

    def test_memory_and_missing_metadata(self):
        from gen2.tests import store_fixtures as fx
        with api.adopt_in_memory(fx.connect()) as store:
            token = store.capture_topic(rf.TOPIC).freshness
            self.assertEqual((token.generation[:2], token.file), ((None, 0), None))
            try:
                with store.transaction(freshness=token):
                    store.insert('queue_entries', dict(topic_id=rf.TOPIC, fleet_id='fleet-a', priority=1,
                        status='awaiting_brief_confirmation', created_at=fx.T, updated_at=fx.T))
            except Exception as exc:
                self.fail(f'fresh initial inputs must commit: {exc!r}')
            self.assertEqual(db.generation_state(store._conn)[:2], (None, 1))
