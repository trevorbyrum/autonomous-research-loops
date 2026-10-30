"""Round-3 F2: any strict-parse refusal retains an authenticated failed attempt.

Literal parser-order probes, independent byte hashes and unknown denominators;
all transports are fixtures and all stores are disposable.
"""
import copy
import hashlib
import json
from unittest.mock import patch

from gen2 import accounting
from gen2.core import canonical
from gen2.router.accounting import convert_inventory
from gen2.tests import test_attempted_request_bytes as attempted
from gen2.tests.router_fixtures import EXPIRES, RouterTestCase

NUMERIC = '{"request":{"request_type":"find","n":9007199254740992},"lane":"crossref","page":1}'
NAME_ONLY = '{"request_type\\u0000suffix":"find"}'
PARSER_LIMITS = ('{"n":' + '1' * 5000 + '}', '[' * 2000 + '0' + ']' * 2000)


class FailedAttemptTest(RouterTestCase):
    command = attempted.AttemptTest.command
    send = attempted.AttemptTest.send

    def setUp(self):
        super().setUp()
        self.to_scoping()
        self.grant = self.started('inv_discover1', 'discovery')

    def refusal_audits(self):
        return self.store.select('audit_events', {'kind': 'observation_request_refused'})

    def assert_retained(self, raw, refusal_class='logical_json_invalid'):
        expected = raw.encode('utf-8')
        digest = 'sha256:' + hashlib.sha256(expected).hexdigest()
        prior = len(self.store.select('search_observations'))
        command = self.command(raw)
        command['observation']['attempt'] = prior + 1
        reply = self.send(command)
        self.assertEqual(reply['status'], 'recorded', reply)
        self.assertEqual(reply['request_refusal']['reason'], 'request_invalid')
        self.assertEqual(reply['request_refusal']['class'], refusal_class)
        rows = self.store.select('search_observations')
        self.assertEqual(len(rows), prior + 1)
        row = rows[-1]
        self.assertEqual((row['request_bytes'], row['request_bytes_hash'], row['request_identity']),
                         (expected, digest, digest))
        self.assertEqual(row['request'], {'retained_request': {'bytes_hash': digest, 'reason': 'member_name_domain'}})
        self.assertEqual((row['coverage_state'], row['completeness'], row['error_class'], row['page_outcome'],
                          row['result_count'], row['continuation']),
                         ('unknown', 'unobserved', 'payload_invalid', 'failed', None, None))
        self.assertEqual(self.store.select('retrieval_events'), [])
        audits = self.refusal_audits()
        self.assertEqual(len(audits), prior + 1)
        self.assertEqual(audits[-1]['invocation_id'], 'inv_discover1')
        self.assertEqual(audits[-1]['detail'], {'observation_id': row['observation_id'],
            'request_bytes_hash': digest, 'refusal_class': refusal_class})
        inventory = convert_inventory(self.grant['topic_id'], self.store.capture_topic(self.grant['topic_id']), 'native')
        self.assertEqual(len(inventory.observations), prior + 1)
        for obs in inventory.observations:
            self.assertEqual((obs.request_type, obs.page, obs.result_count), (None, None, None))
        units = accounting.candidate_units(inventory)
        for count in (units.retrieved_records, units.deduplicated_works):
            self.assertIsNone(count.value)
            self.assertIn('unknown', count.unknown_reason)
        before = self.state(exclude=())
        replay = self.send(command)
        self.assertEqual(replay['status'], 'replayed', replay)
        self.assertEqual(replay['observation_id'], row['observation_id'])
        self.assertEqual(replay['request_refusal'], reply['request_refusal'])
        self.assertEqual(self.state(exclude=()), before)
        changed = copy.deepcopy(command)
        changed['observation'].update(request=raw + ' ',
            request_identity='sha256:' + hashlib.sha256(expected + b' ').hexdigest())
        self.assertEqual(self.send(changed)['reason'], 'observation_id_conflict')
        self.assertEqual(self.state(exclude=()), before)

    def test_integer_and_duplicate_both_orders(self):
        cases = ('{"n":9007199254740992,"request":{"request_type":"find","request_type":"bad"}}',
                 '{"request":{"request_type":"find","request_type":"bad"},"n":9007199254740992}')
        # Duplicate detection precedes integer validation in both orders.
        for raw in cases:
            with self.subTest(raw=raw):
                self.assert_retained(raw, 'member_name_domain')

    def test_float_and_nul_both_orders(self):
        cases = ('{"n":0.10000000000000001,"request_type\\u0000suffix":"find"}',
                 '{"request_type\\u0000suffix":"find","n":0.10000000000000001}')
        # Even a NUL name first is masked by the numeric parse hook.
        for raw in cases:
            with self.subTest(raw=raw):
                self.assert_retained(raw)

    def test_numeric_and_name_faults_both_orders(self):
        # Each pair: the same numeric fault and name fault in both member orders; the first met names the class.
        cases = (
            ('{"request":{"request_type":"find","n":9007199254740992,"filters":{"field\\u0000suffix":1}},"lane":"crossref","page":1}', 'logical_json_invalid'),
            ('{"request":{"request_type":"find","filters":{"field\\u0000suffix":1},"n":9007199254740992},"lane":"crossref","page":1}', 'member_name_domain'),
            ('{"n":9007199254740992,"request_type\\u0000suffix":"find"}', 'logical_json_invalid'),
            ('{"request_type\\u0000suffix":"find","n":9007199254740992}', 'member_name_domain'),
            ('{"n":0.10000000000000001,"request":{"request_type":"find","request_type":"bad"}}', 'logical_json_invalid'),
            ('{"request":{"request_type":"find","request_type":"bad"},"n":0.10000000000000001}', 'member_name_domain'))
        for raw, label in cases:
            with self.subTest(raw=raw):
                self.assert_retained(raw, label)

    def test_numeric_failures_without_names(self):
        for raw in (NUMERIC, NUMERIC.replace('9007199254740992', '-9007199254740992'),
                    NUMERIC.replace('9007199254740992', '0.10000000000000001')):
            with self.subTest(raw=raw):
                self.assert_retained(raw)

    def test_other_strict_parse_reasons(self):
        for raw in (' \n{"broken": \t', '{"n":NaN}', '{"n":Infinity}', '{"n":1e999}',
                    '{"n":1e-999}', '{"text":"\\ud800"}'):
            with self.subTest(raw=raw):
                self.assert_retained(raw)

    def test_parser_limits(self):
        for raw in PARSER_LIMITS:
            with self.subTest(kind='integer_digits' if raw.startswith('{') else 'nesting'):
                self.assert_retained(raw)

    def test_retained_name_control(self):
        # Separate accepted name-only opaque path through the retention decision.
        command = self.command(NAME_ONLY)
        reply = self.send(command)
        self.assertEqual(reply['status'], 'recorded', reply)
        self.assertEqual(reply['request_refusal']['class'], 'member_name_domain')
        self.assertEqual(self.store.select('search_observations')[0]['request_bytes'], NAME_ONLY.encode())
        self.assertEqual(self.refusal_audits()[0]['detail']['refusal_class'], 'member_name_domain')

    def test_ordinary_numeric_control(self):
        for attempt, number in enumerate(('-9007199254740991', '9007199254740991', '0.1', '1e30'), 1):
            raw = NUMERIC.replace('9007199254740992', number)
            logical = json.loads(raw)
            command = self.command(None)
            command['observation'].update(request=raw, request_identity=canonical.logical_hash(logical),
                observation_id=f'obs_accepted{attempt:02}', attempt=attempt, coverage_state='searched_empty',
                completeness='complete', result_count=0, error_class=None, page_outcome='exhausted',
                gateway_call_ref='call-1')
            reply = self.send(command)
            self.assertEqual(reply['status'], 'recorded', reply)
            self.assertNotIn('request_refusal', reply)
            row = self.store.select('search_observations')[-1]
            self.assertEqual(row['request'], logical)
            self.assertIsNone(row['request_bytes'])
            self.assertIsNone(row['request_bytes_hash'])
        self.assertEqual(self.refusal_audits(), [])
        inventory = convert_inventory(self.grant['topic_id'], self.store.capture_topic(self.grant['topic_id']), 'native')
        self.assertEqual(len(inventory.observations), 4)
        self.assertTrue(all(o.request_type == 'find' and o.page is not None for o in inventory.observations))

    def test_invalid_observed_and_exhausted_still_refuse(self):
        raws = (NUMERIC, NUMERIC.replace('9007199254740992', '0.10000000000000001'),
                '{"request":{"request_type":"find","n":9007199254740992,"filters":{"field\\u0000suffix":1}}}',
                '{"n":0.10000000000000001,"request":{"request_type":"find","request_type":"bad"}}',
                *PARSER_LIMITS)
        for raw in raws:
            for outcome in ('end_unknown', 'exhausted'):
                with self.subTest(raw=raw, outcome=outcome):
                    command = self.command(raw)
                    command['observation'].update(coverage_state='searched_empty', completeness='complete',
                        result_count=0, error_class=None, page_outcome=outcome, gateway_call_ref='call-1')
                    before = self.state(exclude=())
                    reply = self.send(command)
                    self.assertEqual((reply['status'], reply['reason']), ('refused', 'request_invalid'), reply)
                    self.assertEqual(self.state(exclude=()), before)

    def test_wrong_byte_hash(self):
        command = self.command(NUMERIC)
        command['observation']['request_identity'] = 'sha256:' + '0' * 64
        before = self.state(exclude=())
        self.assertEqual(self.send(command)['reason'], 'payload_invalid')
        self.assertEqual(self.state(exclude=()), before)

    def test_invalid_failed_envelope(self):
        for change in ({'error_class': 'timeout'}, {'result_count': 0}, {'continuation': {'cursor': 1}}):
            command = self.command(NUMERIC)
            command['observation'].update(change)
            before = self.state(exclude=())
            self.assertEqual(self.send(command)['status'], 'refused')
            self.assertEqual(self.state(exclude=()), before)

    def test_authorization(self):
        command = self.command(NUMERIC)
        command['capability_id'] = 'cap_forgedforged'
        before = self.state(exclude=())
        self.assertEqual(self.send(command)['reason'], 'capability_invalid')
        self.assertEqual(self.state(exclude=()), before)

    def test_current_lease(self):
        self.clock.set(EXPIRES)
        before = self.state(exclude=())
        self.assertEqual(self.send(self.command(NUMERIC))['reason'], 'lease_not_current')
        self.assertEqual(self.state(exclude=()), before)

    def test_running_invocation(self):
        self.assertEqual(self.router.record_transition({'capability_id': self.grant['capability_id'],
            'invocation_id': 'inv_discover1', 'to_state': 'failed', 'failure_class': 'exit_nonzero',
            'end_evidence_ref': self.evidence(self.grant)})['status'], 'recorded')
        before = self.state(exclude=())
        self.assertEqual(self.send(self.command(NUMERIC))['reason'], 'invocation_state_invalid')
        self.assertEqual(self.state(exclude=()), before)

    def test_refusal_audit_rollback(self):
        original = self.router._audit
        def audit(kind, *args, **kwargs):
            if kind == 'observation_request_refused':
                raise RuntimeError('refusal audit failed')
            return original(kind, *args, **kwargs)
        before = self.state(exclude=())
        with patch.object(self.router, '_audit', side_effect=audit):
            with self.assertRaisesRegex(RuntimeError, 'refusal audit failed'):
                self.send(self.command(NUMERIC))
        self.assertEqual(self.state(exclude=()), before)

    def test_no_permissive_reparse(self):
        original = canonical.json.loads
        def strict_only(*args, **kwargs):
            self.assertIn('object_pairs_hook', kwargs)
            return original(*args, **kwargs)
        with patch.object(canonical.json, 'loads', side_effect=strict_only):
            self.assertEqual(self.send(self.command(NUMERIC))['status'], 'recorded')
