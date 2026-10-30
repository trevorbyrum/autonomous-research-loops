"""Retained-request representation and bindings on observations (SQL 24/25)."""
import json
import re
import sqlite3


from gen2.store import api
from gen2.tests import store_fixtures as fx


DESCRIPTOR_RULE = "retained descriptor requires its own same-row bytes"
RETAINED_RULE = "retained request must bind exact-byte identity and failed attempt"


class ObservationDomainTest(fx.StoreTestCase):
    def setUp(self):
        super().setUp()
        self.reader = api.adopt_in_memory(self.db)
        self.lease('lease_aaaaaaaa', 1)
        self.invocation('inv_aaaaaaaa')
        self.row = dict(observation_id='obs_domain001', invocation_id='inv_aaaaaaaa', topic_id=fx.TOPIC,
            request_identity=fx.h('4'), attempt=1, lane='crossref', request=json.loads(fx.FIND_REQUEST), obligation_ids=[],
            started_at=fx.T, coverage_state='unknown', completeness='unobserved', error_class='payload_invalid',
            policy_version='pol1', page_outcome='failed', continuation=None)

    def insert_raw(self, row):
        values = [json.dumps(v) if k in ('request', 'obligation_ids', 'continuation') and v is not None and not isinstance(v, str) else v for k, v in row.items()]
        self.x(f"INSERT INTO search_observations ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", *values)

    def retained_row(self):
        raw = b'{"request":{"request_type":"find","a\\u0000":1}}'
        digest = fx.h('4')  # DDL binds labels; Router/Store separately prove hash truth.
        row = {**self.row, 'request_bytes': raw, 'request_bytes_hash': digest, 'request': {
            'request': {'request_type': 'find'}, 'retained_request': {'bytes_hash': digest, 'reason': 'member_name_domain'}}}
        row['request'] = json.dumps(row['request'], separators=(',', ':'))
        return row

    def test_retained_control(self):
        row = self.retained_row()
        self.insert_raw(row)
        self.assertEqual(self.reader.select('search_observations')[0]['request_bytes'], row['request_bytes'])

    def opaque_row(self):
        row = self.retained_row()
        descriptor = json.loads(row['request'])
        del descriptor['request']
        row['request'] = json.dumps(descriptor, separators=(',', ':'))
        return row

    def test_opaque_control(self):
        row = self.opaque_row()
        self.insert_raw(row)
        stored = self.reader.select('search_observations')[0]
        self.assertEqual(stored['request'], json.loads(row['request']))
        self.assertEqual(stored['request_bytes'], row['request_bytes'])
        self.assertNotIn('request', stored['request'])

    def test_ordinary_discriminator(self):
        self.x('SAVEPOINT control')
        self.insert_raw({**self.row, 'request': {'request': {'request_type': 'find'}}})
        self.x('ROLLBACK TO control')
        self.x('RELEASE control')
        for request in ({}, {'request': {}}, {'request': {'request_type': 'bad'}}):
            before = list(self.db.iterdump())
            with self.subTest(request=request), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape("json_extract(request, '$.request.request_type') IN ('find', 'resolve', 'enrich', 'fetch', 'data')")):
                self.insert_raw({**self.row, 'request': request})
            self.assertEqual(list(self.db.iterdump()), before)

    def test_opaque_binding(self):
        row = self.opaque_row()
        self.x('SAVEPOINT control')
        self.insert_raw({**row, 'gateway_call_ref': 'call-1'})
        self.x('ROLLBACK TO control')
        self.x('RELEASE control')
        descriptor = json.loads(row['request'])
        for change, fragment in (({'request_bytes': None, 'request_bytes_hash': None}, DESCRIPTOR_RULE),
                       ({'request_bytes': None}, DESCRIPTOR_RULE), ({'request_bytes_hash': None}, RETAINED_RULE),
                       ({'request_identity': fx.h('5')}, RETAINED_RULE), ({'error_class': 'timeout'}, RETAINED_RULE),
                       ({'request': {**descriptor, 'page': 1}}, RETAINED_RULE),
                       ({'request': {**descriptor, 'request': {}}}, RETAINED_RULE),
                       ({'request': {'retained_request': {**descriptor['retained_request'], 'column': 'response_bytes'}}}, RETAINED_RULE),
                       ({'coverage_state': 'searched_empty', 'completeness': 'complete', 'result_count': 0,
                        'error_class': None, 'page_outcome': 'end_unknown', 'gateway_call_ref': 'call-1'}, RETAINED_RULE)):
            before = list(self.db.iterdump())
            with self.subTest(change=change), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                self.insert_raw({**row, **change})
            self.assertEqual(list(self.db.iterdump()), before)

    def test_legacy_discriminator(self):
        row = self.retained_row()
        for kind in (None, 'bad', 1):
            request = json.loads(row['request'])
            request['request']['request_type'] = kind
            before = list(self.db.iterdump())
            with self.subTest(kind=kind), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(RETAINED_RULE)):
                self.insert_raw({**row, 'request': request})
            self.assertEqual(list(self.db.iterdump()), before)

    def test_opaque_retrieval_refused(self):
        # Pair the successful search with the same ordinary failed request.
        self.x('SAVEPOINT control')
        self.insert_raw({**self.row, 'coverage_state': 'searched_ok', 'completeness': 'complete',
            'result_count': 1, 'error_class': None, 'page_outcome': 'exhausted', 'gateway_call_ref': 'call-1'})
        self.x('INSERT INTO retrieval_events VALUES (?,?,?,?,?,?)',
            'rev_opaque001', self.row['observation_id'], fx.TOPIC, 'rec-1', 1, fx.T)
        self.x('ROLLBACK TO control')
        self.insert_raw({**self.row, 'gateway_call_ref': 'call-1'})
        before = list(self.db.iterdump())
        self.rejects('retrieval events come only from successful searches of the same topic (E-2)',
            'INSERT INTO retrieval_events VALUES (?,?,?,?,?,?)',
            'rev_opaque001', self.row['observation_id'], fx.TOPIC, 'rec-1', 1, fx.T)
        self.assertEqual(list(self.db.iterdump()), before)
        self.x('ROLLBACK TO control')
        self.x('RELEASE control')
        self.insert_raw(self.opaque_row())
        before = list(self.db.iterdump())
        self.rejects('retrieval events come only from successful searches of the same topic (E-2)',
            'INSERT INTO retrieval_events VALUES (?,?,?,?,?,?)',
            'rev_opaque001', self.row['observation_id'], fx.TOPIC, 'rec-1', 1, fx.T)
        self.assertEqual(list(self.db.iterdump()), before)

    def test_retained_binding(self):
        row = self.retained_row()
        self.x('SAVEPOINT control')
        self.insert_raw({**row, 'request': fx.FIND_REQUEST, 'request_bytes': None, 'request_bytes_hash': None})
        self.x('ROLLBACK TO control')
        self.x('RELEASE control')
        wrong_hash = json.loads(row['request'])
        wrong_hash['retained_request']['bytes_hash'] = fx.h('5')
        wrong_reason = json.loads(row['request'])
        wrong_reason['retained_request']['reason'] = 'other'
        for changes, fragment in (({'request_bytes': None}, DESCRIPTOR_RULE),
                        ({'request_bytes_hash': None}, RETAINED_RULE), ({'request_identity': fx.h('5')}, RETAINED_RULE),
                        ({'request': fx.FIND_REQUEST, 'request_bytes': None}, RETAINED_RULE),
                        ({'request': fx.FIND_REQUEST}, DESCRIPTOR_RULE),
                        # Same typed request as the admitted retained row; only its descriptor is missing.
                        ({'request': {'request': {'request_type': 'find'}}}, DESCRIPTOR_RULE),
                        ({'error_class': 'timeout'}, RETAINED_RULE),
                        ({'request': wrong_hash}, RETAINED_RULE), ({'request': wrong_reason}, RETAINED_RULE),
                        ({'request': {**json.loads(row['request']), 'extra': 1}}, RETAINED_RULE)):
            before = list(self.db.iterdump())
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
                self.insert_raw({**row, **changes})
            self.assertEqual(list(self.db.iterdump()), before)
        self.insert_raw(row)
        self.assertEqual(self.reader.select('search_observations')[0]['request_bytes'], row['request_bytes'])

    def test_descriptor_requires_its_own_bytes(self):
        row = self.retained_row()
        for extra in ({}, {'observation_id': 'obs_other001'}, {'column': 'response_bytes'}):
            for observed in (False, True):
                changed = json.loads(row['request'])
                changed['retained_request'].update(extra)
                candidate = {**row, 'request': changed, 'request_bytes': None, 'request_bytes_hash': None}
                if observed:
                    candidate.update(coverage_state='searched_ok', completeness='complete', result_count=1,
                        error_class=None, page_outcome='exhausted', gateway_call_ref='call-1')
                self.x('SAVEPOINT control')
                self.insert_raw({**candidate, 'request': {'request': changed['request']}})
                self.x('ROLLBACK TO control')
                self.x('RELEASE control')
                before = list(self.db.iterdump())
                with self.subTest(extra=extra, observed=observed), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(DESCRIPTOR_RULE)):
                    self.insert_raw(candidate)
                self.assertEqual(list(self.db.iterdump()), before)

    def test_retained_foreign_and_observed(self):
        row = self.retained_row()
        self.x('SAVEPOINT control')
        self.insert_raw({**row, 'gateway_call_ref': 'call-1'})
        self.x('ROLLBACK TO control')
        self.x('RELEASE control')
        for extra in ({'observation_id': 'obs_other001'}, {'column': 'response_bytes'}):
            changed = json.loads(row['request'])
            changed['retained_request'].update(extra)
            before = list(self.db.iterdump())
            with self.subTest(extra=extra), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(RETAINED_RULE)):
                self.insert_raw({**row, 'request': changed})
            self.assertEqual(list(self.db.iterdump()), before)
        for state, count in (('searched_empty', 0), ('searched_ok', 1)):
            before = list(self.db.iterdump())
            with self.subTest(state=state), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(RETAINED_RULE)):
                self.insert_raw({**row, 'coverage_state': state, 'completeness': 'complete',
                    'result_count': count, 'error_class': None, 'page_outcome': 'exhausted', 'gateway_call_ref': 'call-1'})
            self.assertEqual(list(self.db.iterdump()), before)

    def test_retained_retrieval_refused(self):
        # Pair the successful search with the same ordinary failed request.
        self.x('SAVEPOINT control')
        self.insert_raw({**self.row, 'coverage_state': 'searched_ok', 'completeness': 'complete',
            'result_count': 1, 'error_class': None, 'page_outcome': 'exhausted', 'gateway_call_ref': 'call-1'})
        self.x('INSERT INTO retrieval_events VALUES (?,?,?,?,?,?)',
            'rev_retained01', self.row['observation_id'], fx.TOPIC, 'rec-1', 1, fx.T)
        self.x('ROLLBACK TO control')
        self.insert_raw({**self.row, 'gateway_call_ref': 'call-1'})
        before = list(self.db.iterdump())
        self.rejects('retrieval events come only from successful searches of the same topic (E-2)',
            'INSERT INTO retrieval_events VALUES (?,?,?,?,?,?)',
            'rev_retained01', self.row['observation_id'], fx.TOPIC, 'rec-1', 1, fx.T)
        self.assertEqual(list(self.db.iterdump()), before)
        self.x('ROLLBACK TO control')
        self.x('RELEASE control')
        row = self.retained_row()
        self.insert_raw(row)
        before = list(self.db.iterdump())
        self.rejects('retrieval events come only from successful searches of the same topic (E-2)',
            'INSERT INTO retrieval_events VALUES (?,?,?,?,?,?)',
            'rev_retained01', row['observation_id'], fx.TOPIC, 'rec-1', 1, fx.T)
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(self.reader.select('retrieval_events'), [])

    def test_observed_retrieval_control(self):
        row = {**self.row, 'coverage_state': 'searched_ok', 'completeness': 'complete',
            'result_count': 1, 'error_class': None, 'page_outcome': 'exhausted', 'gateway_call_ref': 'call-1'}
        self.insert_raw(row)
        self.x('INSERT INTO retrieval_events VALUES (?,?,?,?,?,?)',
            'rev_observed01', row['observation_id'], fx.TOPIC, 'rec-1', 1, fx.T)
        self.assertEqual(self.reader.select('retrieval_events')[0]['provider_record_id'], 'rec-1')
        self.assertIsNone(self.reader.select('search_observations')[0]['request_bytes'])
