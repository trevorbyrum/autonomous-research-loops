"""F2: exact refused bytes count without a decoded type/page; no providers."""
import copy
import hashlib
import json
from unittest.mock import patch

from gen2 import accounting
from gen2.core import canonical
from gen2.gateway_client import observe
from gen2.gateway_client.client import GatewayClient
from gen2.router.accounting import convert_inventory
from gen2.tests import test_attempted_request_bytes as attempted
from gen2.tests.router_fixtures import EXPIRES, RouterTestCase

STRUCTURAL = ' \n{"request":{"request_type\\u0000suffix":"find"},"lane":"crossref","page":1} \t'
DUPLICATE = '{"request":{"request_type":"find","request_type":"bad"},"lane":"crossref","page":1}'
OBJECT_BYTES = b'{"lane":"crossref","page":1,"request":{"filters":{"field\\u0000suffix":"\xce\xbb"},"request_type":"find"}}'


class OpaqueAttemptTest(RouterTestCase):
    command = attempted.AttemptTest.command
    send = attempted.AttemptTest.send
    row = attempted.AttemptTest.row

    def setUp(self):
        super().setUp()
        self.to_scoping()
        self.grant = self.started('inv_discover1', 'discovery')

    def retained(self, command, expected):
        reply = self.send(command)
        self.assertEqual(reply['status'], 'recorded', reply)
        self.assertEqual(reply['request_refusal']['reason'], 'request_invalid')
        rows = self.store.select('search_observations')
        self.assertEqual(len(rows), 1)
        row = rows[0]
        digest = 'sha256:' + hashlib.sha256(expected).hexdigest()
        self.assertEqual((row['request_bytes'], row['request_bytes_hash'], row['request_identity']), (expected, digest, digest))
        self.assertEqual(row['request'], {'retained_request': {'bytes_hash': digest, 'reason': 'member_name_domain'}})
        self.assertEqual((row['coverage_state'], row['completeness'], row['error_class'], row['page_outcome'],
                          row['result_count'], row['continuation']), ('unknown', 'unobserved', 'payload_invalid', 'failed', None, None))
        self.assertEqual(self.store.select('retrieval_events'), [])
        inventory = convert_inventory(self.grant['topic_id'], self.store.capture_topic(self.grant['topic_id']), 'native')
        self.assertEqual(len(inventory.observations), 1)
        observation = inventory.observations[0]
        self.assertEqual((observation.request_type, observation.page, observation.result_count), (None, None, None))
        units = accounting.candidate_units(inventory)
        for count in (units.retrieved_records, units.deduplicated_works):
            self.assertIsNone(count.value)
            self.assertIn('unknown', count.unknown_reason)
        self.assertEqual(units.accepted_claims.value, 0)
        self.assertEqual(units.assessed_candidates.value, 0)
        before = self.state(exclude=())
        self.assertEqual(self.send(command)['status'], 'replayed')
        changed = copy.deepcopy(command)
        changed['observation'].update(request=expected.decode() + ' ',
            request_identity='sha256:' + hashlib.sha256(expected + b' ').hexdigest())
        self.assertEqual(self.send(changed)['reason'], 'observation_id_conflict')
        self.assertEqual(self.state(exclude=()), before)

    def test_structural_nul(self):
        self.retained(self.command(STRUCTURAL), STRUCTURAL.encode())

    def test_duplicate_discriminator(self):
        # Both orders, including escaped duplicates, have the same opaque policy.
        raw = DUPLICATE
        self.retained(self.command(raw), raw.encode())

    def test_other_structural_names_and_duplicates(self):
        raws = ('{"request\\u0000suffix":{}}', '{"request":{"request_type":"bad","request_type":"find"}}',
                '{"request":{"request_type":"find","request_\\u0074ype":"bad"}}')
        for number, raw in enumerate(raws, 1):
            command = self.command(raw)
            command['observation']['attempt'] = number
            self.assertEqual(self.send(command)['status'], 'recorded')
            self.assertEqual(self.store.select('search_observations')[-1]['request_bytes'], raw.encode())
        inventory = convert_inventory(self.grant['topic_id'], self.store.capture_topic(self.grant['topic_id']), 'native')
        self.assertEqual(len(inventory.observations), 3)
        self.assertTrue(all(o.request_type is None and o.page is None for o in inventory.observations))

    def test_object_nul(self):
        command = self.command(None)
        command['observation'].update(request=json.loads(attempted.RAW),
            request_identity='sha256:' + hashlib.sha256(OBJECT_BYTES).hexdigest())
        self.retained(command, OBJECT_BYTES)
        self.assertEqual(command['observation']['request'], json.loads(attempted.RAW))

    def test_no_permissive_reparse(self):
        original = canonical.json.loads
        def strict_only(*args, **kwargs):
            self.assertIn('object_pairs_hook', kwargs, 'duplicate document was reparsed permissively')
            return original(*args, **kwargs)
        with patch.object(canonical.json, 'loads', side_effect=strict_only):
            self.assertEqual(self.send(self.command(DUPLICATE))['status'], 'recorded')

    def test_ordinary_discriminator_stays_required(self):
        for document in ({}, {'request': {'request_type': 'bad'}}, {'request': {'request_type\0suffix': 'find'}}):
            command = self.command(None)
            command['observation'].update(request=document, request_identity=canonical.logical_hash(document),
                coverage_state='searched_empty', completeness='complete', result_count=0, error_class=None,
                page_outcome='end_unknown', gateway_call_ref='call-1')
            before = self.state(exclude=())
            self.assertEqual(self.send(command)['status'], 'refused')
            self.assertEqual(self.state(exclude=()), before)

    def test_ordinary_control(self):
        self.assertEqual(self.send(self.command(None))['status'], 'recorded')
        self.assertEqual(self.row()['request']['request']['request_type'], 'find')
        self.assertIsNone(self.row()['request_bytes'])

    def test_legacy_read_control(self):
        raw = attempted.RAW.encode()
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        row = {**self.command(None)['observation'], 'invocation_id': 'inv_discover1', 'topic_id': self.grant['topic_id'],
            'request_identity': digest, 'request_bytes': raw, 'request_bytes_hash': digest,
            'request': {'request': {'request_type': 'find'},
                        'retained_request': {'bytes_hash': digest, 'reason': 'member_name_domain'}}}
        with self.store.transaction():
            self.store.insert('search_observations', row)
        inventory = convert_inventory(self.grant['topic_id'], self.store.capture_topic(self.grant['topic_id']), 'native')
        self.assertEqual([o.request_type for o in inventory.observations], ['find'])
        self.assertTrue(all(o.page is None for o in inventory.observations))

    def test_search_producer_handoff(self):
        calls = []
        def transport(method, url, headers, body, timeout):
            calls.append(body)
            return 400, {}, b'', None
        client = GatewayClient('http://gateway.invalid:9999', 'fixture', transport=transport,
            clock=lambda: '2026-09-27T10:00:00Z')
        sent = {'request_type': 'find', 'lanes': ['crossref'], 'filters': {'field\0suffix': 'λ'}}
        out = client.search(sent, invocation_id='inv_discover1', attempt=1, policy_version='gw-policy/1')
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(calls[0])['filters'], sent['filters'])
        commands = observe.router_requests(out, capability_id=self.grant['capability_id'], invocation_id='inv_discover1')
        self.assertEqual(len(commands), 1)
        method, command = commands[0]
        self.assertEqual(method, 'record_observation')
        expected = b'{"lane":"crossref","page":1,"request":{"request_type":"find","lanes":["crossref"],"filters":{"field\\u0000suffix":"\xce\xbb"}}}'
        self.retained(command, expected)

    def test_wrong_object_hash(self):
        command = self.command(None)
        command['observation'].update(request=json.loads(attempted.RAW), request_identity='sha256:' + '0' * 64)
        before = self.state(exclude=())
        self.assertEqual(self.send(command)['reason'], 'payload_invalid')
        self.assertEqual(self.state(exclude=()), before)

    def test_authorization(self):
        command = self.command(STRUCTURAL)
        command['capability_id'] = 'cap_forgedforged'
        before = self.state()
        self.assertEqual(self.send(command)['reason'], 'capability_invalid')
        self.assertEqual(self.state(), before)

    def test_expired_lease(self):
        self.clock.set(EXPIRES)
        before = self.state(exclude=())
        self.assertEqual(self.send(self.command(DUPLICATE))['reason'], 'lease_not_current')
        self.assertEqual(self.state(exclude=()), before)
        self.clock.set('2026-09-27T11:00:00Z')
        self.assertEqual(self.send(self.command(DUPLICATE))['status'], 'recorded')

    def test_not_running(self):
        self.assertEqual(self.router.record_transition({'capability_id': self.grant['capability_id'],
            'invocation_id': 'inv_discover1', 'to_state': 'failed', 'failure_class': 'exit_nonzero',
            'end_evidence_ref': self.evidence(self.grant)})['status'], 'recorded')
        before = self.state(exclude=())
        self.assertEqual(self.send(self.command(STRUCTURAL))['reason'], 'invocation_state_invalid')
        self.assertEqual(self.state(exclude=()), before)

    def test_opaque_rollback(self):
        before = self.state(exclude=())
        with patch.object(self.router, '_audit', side_effect=RuntimeError('audit failed')):
            with self.assertRaisesRegex(RuntimeError, 'audit failed'):
                self.send(self.command(DUPLICATE))
        self.assertEqual(self.state(exclude=()), before)
