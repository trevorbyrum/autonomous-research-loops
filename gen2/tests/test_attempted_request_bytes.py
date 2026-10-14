"""Exact attempted-byte retention, hash truth and denominator; no providers."""
import copy
import hashlib
import json
from unittest.mock import patch

from gen2.core import canonical, pagination
from gen2.gateway_client import observe
from gen2.router.accounting import read_inventory, read_page
from gen2.store import api
from gen2.tests.router_fixtures import RouterTestCase

RAW = ' \n{"request":{"request_type":"find","filters":{"field\\u0000suffix":"λ"}},"lane":"crossref","page":1} \t'
DUPLICATE = '{"request":{"request_type":"find","filters":{"field":1,"\\u0066ield":2}}}'


class AttemptTest(RouterTestCase):
    def setUp(self):
        super().setUp()
        self.to_scoping()
        self.grant = self.started('inv_discover1', 'discovery')

    def command(self, raw=RAW):
        doc = observe.observation(observe.unobserved('crossref', 'unknown', 'payload_invalid'),
            request={'request': {'request_type': 'find'}, 'lane': 'crossref', 'page': 1}, invocation_id='inv_discover1', attempt=1,
            obligation_ids=[], policy_version='gw-policy/1', started_at='2026-09-27T10:00:00Z',
            ended_at='2026-09-27T10:00:05Z', call_ref=None)
        if raw is not None:
            digest = hashlib.sha256(raw.encode()).hexdigest()
            doc['observation'].update(observation_id='obs_' + digest[:32], request=raw, request_identity='sha256:' + digest)
        return {**doc, 'invocation_id': 'inv_discover1', 'capability_id': self.grant['capability_id']}

    def send(self, command=None):
        return self.router.record_observation(self.command() if command is None else command)

    def row(self):
        return self.store.select('search_observations')[0]

    def test_retention(self):
        for raw in (RAW, DUPLICATE):
            with self.subTest(raw=raw):
                cmd = self.command(raw)
                cmd['observation']['attempt'] = len(self.store.select('search_observations')) + 1
                out = self.send(cmd)
                self.assertEqual(out['status'], 'recorded', out)
                self.assertEqual(out['request_refusal']['reason'], 'request_invalid')
                row = self.store.select('search_observations')[-1]
                self.assertEqual(row['request_bytes'], raw.encode())
                digest = 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()
                self.assertEqual((row['request_identity'], row['request_bytes_hash']), (digest, digest))
                self.assertEqual(row['request']['retained_request']['bytes_hash'], digest)
                self.assertEqual((row['coverage_state'], row['result_count'], row['completeness']), ('unknown', None, 'unobserved'))
        self.assertEqual(len(self.store.select('search_observations')), 2)
        self.assertEqual(self.store.select('retrieval_events'), [])
        inventory = read_inventory(self.store, self.grant['topic_id'], 'native')
        self.assertEqual(len(inventory.observations), 2)
        self.assertTrue(all(o.page is None and o.result_count is None for o in inventory.observations))

    def test_control(self):
        out = self.send(self.command(None))
        self.assertEqual(out['status'], 'recorded', out)
        self.assertIsNone(self.row()['request_bytes'])
        self.assertIsNone(self.row()['request_bytes_hash'])
        inventory = read_inventory(self.store, self.grant['topic_id'], 'native')
        self.assertIsNotNone(inventory.observations[0].page)

    def test_readable_text_control(self):
        command = self.command(None)
        document = {'request': {'request_type': 'find', 'filters': {'a': 'allowed\0value'}}}
        command['observation'].update(request=json.dumps(document), request_identity=canonical.logical_hash(document))
        self.assertEqual(self.send(command)['status'], 'recorded')
        self.assertEqual(self.row()['request'], document)

    def test_wrong_hash(self):
        command = self.command()
        command['observation']['request_identity'] = 'sha256:' + '0' * 64
        before = self.state(exclude=())
        self.assertEqual(self.send(command)['reason'], 'payload_invalid')
        self.assertEqual(self.state(exclude=()), before)

    def test_failed_only(self):
        for changes in ({'coverage_state': 'searched_empty', 'completeness': 'complete', 'result_count': 0,
                          'page_outcome': 'end_unknown', 'error_class': None, 'gateway_call_ref': 'call-1'},
                        {'error_class': 'timeout'}):
            command = self.command()
            command['observation'].update(changes)
            before = self.state(exclude=())
            out = self.send(command)
            self.assertEqual(out['reason'], 'request_invalid', out)
            self.assertEqual(self.state(exclude=()), before)

    def test_router_nul(self):
        for column, value in (('request', json.loads(RAW)), ('obligation_ids', [{'name\0suffix': 1}]),
                              ('continuation', {'cursor': 'next', 'name\0suffix': 1})):
            command = self.command(None)
            command['observation'][column] = value
            with self.subTest(column=column), patch.object(canonical.rfc8785, 'dumps', side_effect=AssertionError('serialized before refusal')):
                out = self.send(command)
                self.assertEqual(out['reason'], 'request_invalid', out)
                self.assertIn('NUL in object member name', out['detail'])

    def test_store_nul(self):
        for column in ('request', 'obligation_ids', 'continuation'):
            with self.subTest(column=column), self.assertRaisesRegex(api.StoreWriteError, 'NUL in object member name'), self.store.transaction():
                self.store.insert('search_observations', {column: {'outer': [{'name\0suffix': 1}]}})

    def test_replay_conflict(self):
        command = self.command()
        self.assertEqual(self.send(command)['status'], 'recorded')
        before = self.state(exclude=())
        self.assertEqual(self.send(command)['status'], 'replayed')
        changed = copy.deepcopy(command)
        raw = RAW + ' '
        changed['observation'].update(request=raw, request_identity=canonical.bytes_digest(raw.encode()))
        self.assertEqual(self.send(changed)['reason'], 'observation_id_conflict')
        self.assertEqual(self.state(exclude=()), before)

    def test_rollback(self):
        before = self.state(exclude=())
        with patch.object(self.router, '_audit', side_effect=RuntimeError('audit failed')):
            with self.assertRaisesRegex(RuntimeError, 'audit failed'):
                self.send()
        self.assertEqual(self.state(exclude=()), before)

    def test_store_hash(self):
        self.assertEqual(self.send()['status'], 'recorded')
        row = self.row()
        row['observation_id'], row['attempt'] = 'obs_storehash01', 2
        row['request_bytes'] += b' '
        current = api.adopt_in_memory(self.db)  # include the API module's mutant
        with self.assertRaisesRegex(api.StoreWriteError, 'byte hash mismatch'), current.transaction():
            current.insert('search_observations', row)
        self.assertEqual(len(self.store.select('search_observations')), 1)

    def test_store_hash_control(self):
        self.assertEqual(self.send()['status'], 'recorded')
        row = self.row()
        row['observation_id'], row['attempt'] = 'obs_storehash01', 2
        current = api.adopt_in_memory(self.db)
        with current.transaction():
            current.insert('search_observations', row)
        self.assertEqual(current.select('search_observations')[-1]['request_bytes'], RAW.encode())

    def test_client_retention(self):
        request = json.loads(RAW)
        command = self.command(None)
        produced = observe.observation(observe.unobserved('crossref', 'unknown', 'payload_invalid'),
            request=request, invocation_id='inv_discover1', attempt=1, obligation_ids=[], policy_version='gw-policy/1',
            started_at='2026-09-27T10:00:00Z', ended_at='2026-09-27T10:00:05Z', call_ref=None)
        command.update(produced)
        self.assertIsInstance(command['observation']['request'], str)
        self.assertEqual(self.send(command)['status'], 'recorded')
        self.assertEqual(self.row()['request_bytes'], produced['observation']['request'].encode())
        self.assertEqual(json.loads(self.row()['request_bytes']), request)

    def test_descriptor_cannot_be_an_ordinary_request(self):
        self.assertEqual(self.send()['status'], 'recorded')
        descriptor = self.row()['request']
        for extra in ({}, {'observation_id': self.row()['observation_id']}, {'column': 'response_bytes'}):
            for observed in (False, True):
                for text in (False, True):
                    ref = copy.deepcopy(descriptor)
                    ref['retained_request'].update(extra)
                    command = self.command(None)
                    command['observation'].update(observation_id='obs_forged001', attempt=2,
                        request=json.dumps(ref) if text else ref, request_identity=canonical.logical_hash(ref))
                    if observed:
                        command['observation'].update(coverage_state='searched_empty', completeness='complete',
                            result_count=0, error_class=None, page_outcome='exhausted', gateway_call_ref='call-1')
                    before = self.state(exclude=())
                    with self.subTest(extra=extra, observed=observed, text=text):
                        result = self.send(command)
                        self.assertEqual(result['reason'], 'request_invalid', result)
                        self.assertIn('reserved for same-row', result['detail'])
                        self.assertEqual(self.state(exclude=()), before)

    def test_bound_accounting_control(self):
        self.assertEqual(self.send()['status'], 'recorded')
        self.assertTrue(pagination.retained_request(self.row()))
        self.assertIsNone(read_page(self.row()))
        ordinary = self.command(None)
        ordinary['observation'].update(observation_id='obs_ordinary01', attempt=2)
        self.assertEqual(self.send(ordinary)['status'], 'recorded')
        rows = self.store.select('search_observations')
        self.assertFalse(pagination.retained_request(rows[-1]))
        inventory = read_inventory(self.store, self.grant['topic_id'], 'native')
        self.assertEqual(len(inventory.observations), 2)
        self.assertIsNone(inventory.observations[0].page)
        self.assertIsNotNone(inventory.observations[1].page)

    def test_accounting_requires_the_complete_binding(self):
        self.assertEqual(self.send()['status'], 'recorded')
        row = self.row()
        changes = ({'request_bytes': None, 'request_bytes_hash': None}, {'request_bytes': None},
            {'request_bytes_hash': None}, {'request_identity': 'sha256:' + '0' * 64},
            {'request': self.command(None)['observation']['request']},
            {'coverage_state': 'searched_empty'}, {'completeness': 'complete'}, {'error_class': 'timeout'},
            {'page_outcome': 'exhausted'}, {'result_count': 0}, {'continuation': {'cursor': 1}})
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'retained request'):
                pagination.retained_request({**row, **change})
        for extra in ({'column': 'response_bytes'}, {'observation_id': row['observation_id']},
                      {'bytes_hash': 'sha256:' + '0' * 64}, {'reason': 'other'}):
            changed = copy.deepcopy(row)
            changed['request']['retained_request'].update(extra)
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'retained request descriptor'):
                pagination.retained_request(changed)

    def test_accounting_refuses_an_unbound_descriptor(self):
        self.assertEqual(self.send()['status'], 'recorded')
        for change in ({'request_bytes': None, 'request_bytes_hash': None},
                       {'request_bytes_hash': None}, {'request_bytes': None}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'retained request byte pair'):
                read_page({**self.row(), **change})
