"""Raw domain predicates and retained-reference bindings on observations."""
import json
import sqlite3
from unittest.mock import patch

from gen2.tests.ddl_fixtures import restore_triggers

from gen2.store import api, db
from gen2.tests import store_fixtures as fx


class ObservationDomainTest(fx.StoreTestCase):
    def setUp(self):
        # Isolate the domain from the existing cursor shape: keep every other
        # constraint/trigger, transformed mutant SQL and requested trigger order.
        schema = fx.DDL_TEXT
        start = schema.index('  continuation TEXT CHECK')
        end = schema.index('  UNIQUE (invocation_id, request_identity, attempt)', start)
        schema = schema[:start] + '  continuation TEXT CHECK (continuation IS NULL OR json_valid(continuation)),\n' + schema[end:]
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(schema)
            objects = reference.execute("SELECT name,sql FROM sqlite_schema WHERE tbl_name='search_observations' AND sql IS NOT NULL ORDER BY rowid").fetchall()
        with patch.object(fx, 'DDL_TEXT', db.schema_text()):
            super().setUp()
        self.reader = api.adopt_in_memory(self.db)
        self.lease('lease_aaaaaaaa', 1)
        self.invocation('inv_aaaaaaaa')
        self.x('DROP TABLE search_observations')
        for _, sql in objects:
            self.x(sql)
        restore_triggers(self, fx.DDL_TEXT)
        self.assertEqual(self.rows("SELECT name,sql FROM sqlite_schema WHERE tbl_name='search_observations' AND sql IS NOT NULL ORDER BY rowid"), objects)
        self.row = dict(observation_id='obs_domain001', invocation_id='inv_aaaaaaaa', topic_id=fx.TOPIC,
            request_identity=fx.h('4'), attempt=1, lane='crossref', request=json.loads(fx.FIND_REQUEST), obligation_ids=[],
            started_at=fx.T, coverage_state='unknown', completeness='unobserved', error_class='payload_invalid',
            policy_version='pol1', page_outcome='failed', continuation=None)

    def insert_raw(self, row):
        values = [json.dumps(v) if k in ('request', 'obligation_ids', 'continuation') and v is not None and not isinstance(v, str) else v for k, v in row.items()]
        self.x(f"INSERT INTO search_observations ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", *values)

    def attempt(self, column, event, document, accepted):
        self.x('SAVEPOINT pair')
        try:
            base = dict(self.row)
            if column == 'continuation':
                base.update(coverage_state='searched_ok', completeness='partial', error_class='partial_pagination',
                            result_count=1, page_outcome='continuation', continuation={'cursor': 'next'})
            row = {**base, column: document}
            if event == 'u':
                self.insert_raw(base)
                self.x('DROP TRIGGER search_observations_immutable_u')
            before = list(self.db.iterdump())
            def write():
                if event == 'i':
                    self.insert_raw(row)
                else:
                    self.x(f'UPDATE search_observations SET {column}=?', document)
            if accepted:
                write()
                self.assertEqual(self.reader.select('search_observations')[0][column], json.loads(document))
            else:
                with self.assertRaises(sqlite3.IntegrityError):
                    write()
                self.assertEqual(list(self.db.iterdump()), before)
        finally:
            self.x('ROLLBACK TO pair')
            self.x('RELEASE pair')

    def document(self, column, members):
        if column == 'obligation_ids':
            return '[{' + members + '}]'
        prefix = '"request":{"request_type":"find"},' if column == 'request' else '"cursor":"next",'
        return '{' + prefix + members + '}'

    def control(self, column, event):
        self.attempt(column, event, self.document(column, '"a":"allowed\\u0000value","A":2,"other":[{"a":1},{"a":2}]'), True)

    def pairs(self, column, event, predicate):
        members = ('"a":1,"a":2', '"a":1,"\\u0061":2', '"nested":{"a":1,"a":2}') if predicate == 'duplicate' else (
            '"a\\u0000suffix":1', '"nested":{"a\\u0000suffix":1}')
        for member in members:
            with self.subTest(column=column, event=event, member=member):
                self.control(column, event)
                self.attempt(column, event, self.document(column, member), False)

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
        for request in ({}, {'request': {}}, {'request': {'request_type': 'bad'}}):
            before = list(self.db.iterdump())
            with self.subTest(request=request), self.assertRaises(sqlite3.IntegrityError):
                self.insert_raw({**self.row, 'request': request})
            self.assertEqual(list(self.db.iterdump()), before)

    def test_opaque_binding(self):
        row = self.opaque_row()
        descriptor = json.loads(row['request'])
        for change in ({'request_bytes': None, 'request_bytes_hash': None}, {'request_bytes': None},
                       {'request_bytes_hash': None}, {'request_identity': fx.h('5')}, {'error_class': 'timeout'},
                       {'request': {**descriptor, 'page': 1}}, {'request': {**descriptor, 'request': {}}},
                       {'request': {'retained_request': {**descriptor['retained_request'], 'column': 'response_bytes'}}},
                       {'coverage_state': 'searched_empty', 'completeness': 'complete', 'result_count': 0,
                        'error_class': None, 'page_outcome': 'end_unknown', 'gateway_call_ref': 'call-1'}):
            before = list(self.db.iterdump())
            with self.subTest(change=change), self.assertRaises(sqlite3.IntegrityError):
                self.insert_raw({**row, **change})
            self.assertEqual(list(self.db.iterdump()), before)

    def test_legacy_discriminator(self):
        row = self.retained_row()
        for kind in (None, 'bad', 1):
            request = json.loads(row['request'])
            request['request']['request_type'] = kind
            before = list(self.db.iterdump())
            with self.subTest(kind=kind), self.assertRaises(sqlite3.IntegrityError):
                self.insert_raw({**row, 'request': request})
            self.assertEqual(list(self.db.iterdump()), before)

    def test_opaque_retrieval_refused(self):
        self.insert_raw(self.opaque_row())
        before = list(self.db.iterdump())
        with self.assertRaises(sqlite3.IntegrityError):
            self.x('INSERT INTO retrieval_events VALUES (?,?,?,?,?,?)',
                'rev_opaque001', self.row['observation_id'], fx.TOPIC, 'rec-1', 1, fx.T)
        self.assertEqual(list(self.db.iterdump()), before)

    def test_retained_binding(self):
        row = self.retained_row()
        wrong_hash = json.loads(row['request'])
        wrong_hash['retained_request']['bytes_hash'] = fx.h('5')
        wrong_reason = json.loads(row['request'])
        wrong_reason['retained_request']['reason'] = 'other'
        for changes in ({'request_bytes': None}, {'request_bytes_hash': None}, {'request_identity': fx.h('5')},
                        {'request': fx.FIND_REQUEST, 'request_bytes': None},
                        {'request': fx.FIND_REQUEST}, {'error_class': 'timeout'}, {'request': wrong_hash},
                        {'request': wrong_reason}, {'request': {**json.loads(row['request']), 'extra': 1}}):
            before = list(self.db.iterdump())
            with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError):
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
                before = list(self.db.iterdump())
                with self.subTest(extra=extra, observed=observed), self.assertRaises(sqlite3.IntegrityError):
                    self.insert_raw(candidate)
                self.assertEqual(list(self.db.iterdump()), before)

    def test_retained_foreign_and_observed(self):
        row = self.retained_row()
        for extra in ({'observation_id': 'obs_other001'}, {'column': 'response_bytes'}):
            changed = json.loads(row['request'])
            changed['retained_request'].update(extra)
            before = list(self.db.iterdump())
            with self.subTest(extra=extra), self.assertRaises(sqlite3.IntegrityError):
                self.insert_raw({**row, 'request': changed})
            self.assertEqual(list(self.db.iterdump()), before)
        for state, count in (('searched_empty', 0), ('searched_ok', 1)):
            before = list(self.db.iterdump())
            with self.subTest(state=state), self.assertRaises(sqlite3.IntegrityError):
                self.insert_raw({**row, 'coverage_state': state, 'completeness': 'complete',
                    'result_count': count, 'error_class': None, 'page_outcome': 'exhausted', 'gateway_call_ref': 'call-1'})
            self.assertEqual(list(self.db.iterdump()), before)

    def test_retained_retrieval_refused(self):
        row = self.retained_row()
        self.insert_raw(row)
        before = list(self.db.iterdump())
        with self.assertRaises(sqlite3.IntegrityError):
            self.x('INSERT INTO retrieval_events VALUES (?,?,?,?,?,?)',
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


for column in ('request', 'obligation_ids', 'continuation'):
    for event in ('i', 'u'):
        def control(self, column=column, event=event):
            self.control(column, event)
        setattr(ObservationDomainTest, f'test_{column}_{event}_control', control)
        for predicate in ('duplicate', 'nul'):
            def test(self, column=column, event=event, predicate=predicate):
                self.pairs(column, event, predicate)
            setattr(ObservationDomainTest, f'test_{column}_{event}_{predicate}', test)
