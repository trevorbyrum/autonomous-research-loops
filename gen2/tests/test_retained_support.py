"""Guarded admission and historical inspection over real admitted records."""
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gen2.app import engine, station
from gen2.router import history as reader, service
from gen2.store import api, compat, db
from gen2.tests import router_fixtures as rf, test_store_detailed_support as raw
from gen2.tests.detailed_support_fixtures import history
from gen2.tests.test_capture_support import CaptureCase
from gen2.tests.test_detailed_check_receipts import ReferenceCases
from gen2.tests.test_receipt_summary_domain import METHODS


class RetainedSupportTest(unittest.TestCase):
    RAW = True

    def retained(self, method='canonical_bytes', reverse=False):
        case = raw.DetailedSupportDDLTest.opened(self, method, reverse, seed=True,
            distinct=method == 'validated_extraction')
        self.assertEqual(ReferenceCases.submit(case)['status'], 'committed')
        case.x("UPDATE claims SET status='accepted_support' WHERE claim_id='clm_loadbear1'")
        return case

    def disk(self, case):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'store.sqlite3'
        with sqlite3.connect(path) as target:
            case.db.backup(target)
        return path

    def deficient(self, case):
        with history(case):
            case.x('DELETE FROM verification_receipts')

    def refused(self, case, action=None):
        before = case.state(exclude=())
        with self.assertRaises(reader.ReconciliationRequired) as caught:
            (action or case.make_router)()
        diagnostic = caught.exception.diagnostic
        self.assertEqual(diagnostic['reason'], 'reconciliation_required')
        self.assertEqual(diagnostic['deficiencies'][0]['claim_id'], 'clm_loadbear1')
        self.assertIn('no qualifying receipt', diagnostic['deficiencies'][0]['deficiency'])
        self.assertIn('clm_loadbear1 revision 1', str(caught.exception))
        self.assertEqual(case.state(exclude=()), before)
        self.assertFalse(case.db.in_transaction)
        return diagnostic

    def test_control(self):
        with tempfile.TemporaryDirectory() as root:
            router = service.Router.open(Path(root) / 'fresh', None, create=True)
            router.close()
        for reverse in (False, True):
            for method in METHODS:
                with self.subTest(reverse=reverse, method=method):
                    case = self.retained(method, reverse)
                    before = case.state(exclude=())
                    self.assertIsInstance(case.make_router(), service.Router)
                    with service.Router.open(self.disk(case), case.spool)._store:
                        pass
                    self.assertEqual(case.state(exclude=()), before)
                    self.doCleanups()

    def test_refusal_and_owned_close(self):
        case = self.retained()
        self.deficient(case)
        direct = self.refused(case)
        path = self.disk(case)
        owned = api.open_store(path)
        with patch.object(service.api, 'open_store', return_value=owned), patch.object(owned, 'close', wraps=owned.close) as close:
            self.assertEqual(self.refused(case, lambda: service.Router.open(path, None)), direct)
            close.assert_called_once_with()
        with self.assertRaises(sqlite3.ProgrammingError):
            owned.select('claims')
        self.assertEqual(case.store.select('claims', {'claim_id': 'clm_loadbear1'})[0]['status'], 'accepted_support')

    def test_every_revision_and_topic(self):
        case = self.retained()
        self.deficient(case)
        claim = case.store.select('claims', {'claim_id': 'clm_loadbear1'})[0]
        with history(case):
            for changes in (dict(revision=2, status='provisional'),
                    dict(claim_id='clm_otherstore', topic_id=rf.OTHER),
                    dict(claim_id='clm_nonbearing', load_bearing=0, required_access_tier=None)):
                row = {**claim, **changes}
                case.x('INSERT INTO claims (' + ','.join(row) + ') VALUES (' + ','.join('?' * len(row)) + ')', *row.values())
        diagnostic = self.refused(case)
        self.assertEqual([(d['topic_id'], d['claim_id'], d['claim_revision']) for d in diagnostic['deficiencies']],
            [(rf.TOPIC, 'clm_loadbear1', 1), (rf.OTHER, 'clm_otherstore', 1)])

    def test_complete_relation(self):
        for method in METHODS:
            case = self.retained(method)
            for table, field, value in (('verification_receipts', 'receipt', json.dumps({**case.doc,
                    'detailed_checks': {**case.doc['detailed_checks'], 'negation': dict(outcome='not_checked')}})),
                    ('source_acquisitions', 'lane', 'foreign'),
                    ('verification_receipts', 'use', 'sampled')):
                with self.subTest(method=method, field=field):
                    old = case.value('SELECT ' + field + ' FROM ' + table + ' LIMIT 1')
                    with history(case, unchecked=True):
                        case.x('UPDATE ' + table + ' SET ' + field + '=?', value)
                    self.refused(case)
                    with history(case, unchecked=True):
                        case.x('UPDATE ' + table + ' SET ' + field + '=?', old)
            self.doCleanups()

    def capture(self):
        case = CaptureCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        record, doc = case.operands()
        case.accepted(record, verification_receipts=[doc])
        case.promote()
        return case

    def test_capture_control(self):
        case = self.capture()
        self.assertIsInstance(case.make_router(), service.Router)

    def test_capture_refusal(self):
        case = self.capture()
        with history(case, unchecked=True):
            case.x("UPDATE quote_checks SET normalization_version='foreign/1' WHERE match_result IS NOT NULL")
        with self.assertRaises(reader.ReconciliationRequired):
            case.make_router()

    def test_startup_before_effects(self):
        case = self.retained()
        self.deficient(case)
        path = self.disk(case)
        for use_engine in (False, True):
            for mounted in (None, rf.BUNDLE):
                with self.subTest(engine=use_engine, mounted=mounted is not None), \
                        patch.object(station, 'Router', service.Router), \
                        patch.object(service.Router, 'activate_config_bundle') as activate, \
                        patch.object(service.Router, 'restore_config_bundle') as restore, \
                        patch.object(station, 'Spool') as spool, patch.object(station, 'Supervisor') as supervisor, patch.object(station, '_probe') as probe, \
                        patch.object(engine, '_Server') as server:
                    clock, control = Mock(), Mock()
                    opener = lambda: station.open_station(path.parent, station_id='test', host_id='fixture',
                        clock=clock, config_bundle=mounted, control=control)
                    with self.assertRaises(reader.ReconciliationRequired):
                        engine.Engine(opener, Mock()) if use_engine else opener()
                    for effect in (spool, activate, restore, supervisor, probe, server, clock, control):
                        effect.assert_not_called()

    def test_startup_control(self):
        case = self.retained()
        path = self.disk(case)
        active = station.open_station(path.parent, station_id='test', host_id='fixture', clock=case.clock,
            config_bundle=rf.BUNDLE)
        self.addCleanup(active.close)
        self.assertIsInstance(active.router, service.Router)
        fresh = station.open_station(path.parent / 'fresh-root', station_id='test', host_id='fixture',
            clock=case.clock, config_bundle=rf.BUNDLE, create=True)
        self.addCleanup(fresh.close)
        self.assertIs(fresh.router._spool, fresh.spool)

    def test_spool_failure_closes_router(self):
        case = self.retained()
        path = self.disk(case)
        opened = service.Router.open(path, None)
        with patch.object(station.Router, 'open', return_value=opened), \
                patch.object(station, 'Spool', side_effect=RuntimeError('spool failed')), \
                patch.object(opened, 'close', wraps=opened.close) as close:
            with self.assertRaisesRegex(RuntimeError, 'spool failed'):
                station.open_station(path.parent, station_id='test', host_id='fixture', clock=case.clock)
            close.assert_called_once_with()

    def test_history_control(self):
        case = self.retained()
        viewer = reader.HistoryReader.open(self.disk(case))
        self.assertEqual(viewer.diagnostic()['deficiencies'], [])
        self.assertEqual(viewer.records('claims')['records'], case.store.select('claims'))

    def test_history_closed_readback(self):
        case = self.retained('validated_extraction')
        with history(case):
            case.x("UPDATE verification_receipts SET receipt=json_remove(receipt,'$.detailed_checks')")
        path = self.disk(case)
        before = case.state(exclude=())
        viewer = reader.HistoryReader.open(path)
        self.assertEqual({n for n in dir(viewer) if not n.startswith('_')}, {'open', 'records', 'diagnostic'})
        expected = ('claims', 'operation_receipts', 'verification_receipts', 'detailed_check_records',
            'quote_checks', 'source_artifacts', 'source_acquisitions', 'source_extractions',
            'extraction_validations', 'extraction_validations_v2', 'audit_events')
        for family in expected:
            out = viewer.records(family)
            self.assertEqual(out, dict(interpretation='historical_records', family=family, records=case.store.select(family)))
            out['records'].clear()
            self.assertEqual(viewer.records(family)['records'], case.store.select(family))
        self.assertEqual(viewer.diagnostic()['reason'], 'reconciliation_required')
        self.assertEqual(viewer.diagnostic()['interpretation'], 'historical_records')
        diagnostic = viewer.diagnostic()
        diagnostic['deficiencies'].clear()
        self.assertEqual(len(viewer.diagnostic()['deficiencies']), 1)
        for forbidden in ('queue_entries', 'config_bundles', 'dossiers', 'export_manifests', 'sqlite_schema'):
            try: viewer.records(forbidden)
            except Exception as exc: self.assertIsInstance(exc, ValueError)
            else: self.fail('forbidden historical family was exposed')
        self.assertFalse(any(isinstance(v, (api.Store, service.Router)) for v in vars(viewer).values()))
        self.assertEqual(case.state(exclude=()), before)

    def test_snapshot_and_no_dml(self):
        case = self.retained()
        path = self.disk(case)
        statements, observations = [], []
        original = sqlite3.connect
        def connect(*args, **kwargs):
            conn = original(*args, **kwargs)
            conn.set_trace_callback(statements.append)
            return conn
        qualify = reader.support_diagnostics
        def snapshot(store):
            self.assertTrue(store._conn.in_transaction)
            with original(path, isolation_level=None, timeout=0) as contender:
                with self.assertRaises(sqlite3.OperationalError): contender.execute('BEGIN IMMEDIATE')
            observations.append(True)
            return qualify(store)
        with patch.object(sqlite3, 'connect', connect):
            api.open_store(path.parent / 'new.sqlite3', create=True).close()
        with patch.object(sqlite3, 'connect', connect), patch.object(reader, 'support_diagnostics', snapshot):
            router = service.Router.open(path, None)
            router.close()
            viewer = reader.HistoryReader.open(path)
        self.assertEqual(observations, [True, True])
        self.assertEqual(viewer.diagnostic(), dict(interpretation='historical_records', reason=None, deficiencies=[]))
        self.assertEqual([s for s in statements if re.match(r'\s*(INSERT|UPDATE|DELETE|REPLACE)\b', s, re.I)], [])
        before = viewer.records('claims')
        with original(path, isolation_level=None) as durable:
            durable.execute("UPDATE claims SET status='quarantined' WHERE claim_id='clm_loadbear1'")
        self.assertEqual(viewer.records('claims'), before)
        self.assertNotEqual(reader.HistoryReader.open(path).records('claims'), before)

    def test_history_compatibility_and_schema(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'missing'
            with self.assertRaises(db.StoreOpenError): reader.HistoryReader.open(path)
            self.assertFalse(path.exists())
            api.open_store(path, create=True).close()
            with patch.object(compat, 'SQLITE_FLOOR', (999, 0, 0)):
                with self.assertRaises(compat.StoreCompatibilityError): reader.HistoryReader.open(path)
            with sqlite3.connect(path) as conn: conn.execute('CREATE TABLE foreign_table (id INTEGER)')
            with self.assertRaises(db.StoreOpenError): reader.HistoryReader.open(path)
