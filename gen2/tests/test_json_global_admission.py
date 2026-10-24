"""Every logical Router/Store surface refuses names before hashing/writing.

Trace: C-13; DOSSIER 2d-4b3e1-json2b. Raw attempted bytes keep the accepted
Observations hand-off contract; all fixtures/providers are local doubles.
"""
import json
from unittest.mock import patch

from gen2.core import canonical
from gen2.router import boundary
from gen2.router.service import MalformedRequest
from gen2.store import api
from gen2.tests import router_fixtures as rf, test_router_workflow as workflow

# Literal inventory, independently reviewed against Router's public surface.
ROUTES = ('status', 'record_capability_probe', 'record_gateway_facts', 'admit_reaccess',
    'activate_config_bundle', 'record_qualification', 'revoke_qualification',
    'request_cancel', 'reconcile', 'invocation_status', 'requeue', 'open_reservation',
    'open_review', 'create_topic', 'raise_signal', 'version_brief', 'open_brief',
    'mark_brief_overdue', 'propose_amendment', 'draft_contract', 'close_brief',
    'claim', 'record_transition', 'register_works', 'commit_outcome',
    'apply_operator_decision', 'ack_delivery', 'record_observation')


class GlobalAdmissionTest(workflow.Workflow):
    def test_router_names(self):
        for route in ROUTES:
            for text, detail in (('{"a\\u0000suffix":1}', 'NUL in object member name'),
                    ('{"outer":[{"a\\u0000suffix":1}]}', 'NUL in object member name'),
                    ('{"a":1,"a":2}', 'duplicate object key'),
                    ('{"outer":[{"a":1,"\\u0061":2}]}', 'duplicate object key')):
                inputs = [text] + ([json.loads(text)] if 'duplicate' not in detail else [])
                for value in inputs:
                    with self.subTest(route=route, value=value):
                        excluded = ('audit_events', 'capability_facts') if route == 'activate_config_bundle' else ('audit_events',)
                        before = self.state(exclude=excluded)
                        if route == 'commit_outcome':
                            if isinstance(value, str):
                                with self.assertRaises(MalformedRequest):
                                    self.router.commit_outcome(value)
                                self.assertEqual(self.state(exclude=excluded), before)
                                continue
                            value = {**value, 'operation_id': 'op_member0001'}
                        candidate = json.loads(text) if isinstance(value, str) else value
                        dumps = canonical.rfc8785.dumps
                        def guard(document):
                            if document == candidate:
                                raise AssertionError('serialized refused document')
                            return dumps(document)  # permitted refusal audit/capability facts
                        with patch.object(canonical.rfc8785, 'dumps', side_effect=guard):
                            result = getattr(self.router, route)(value)
                        self.assertIn(result['status'], ('refused', 'rejected'), result)
                        expected = 'bundle_invalid' if route == 'activate_config_bundle' else 'envelope_invalid' if route == 'commit_outcome' else 'request_invalid'
                        self.assertEqual(result['reason'], expected, result)
                        self.assertIn(detail, result['detail'])
                        if route == 'commit_outcome':
                            self.assert_audited_state(before, 1, exclude=excluded)
                        else:
                            self.assertEqual(self.state(exclude=excluded), before)

    def test_staged_payload(self):
        self.to_scoping()
        grant = self.started('inv_primary01')
        env = self.envelope(grant, 'op_members0001', rf.empty_outcome(grant['invocation_id'], 'interim_transition'))
        for raw in (b'{"a":1,"a":2}', b'{"a":1,"\\u0061":2}',
                b'{"name\\u0000suffix":1}', b'{"outer":{"name\\u0000suffix":1}}'):
            with self.subTest(raw=raw):
                env.update(payload_digest=self.spool.put(raw), payload_size_bytes=len(raw))
                before = self.state()
                result = self.router.commit_outcome(env)
                self.assertEqual((result['status'], result['reason']), ('rejected', 'payload_invalid'), result)
                self.assertTrue('NUL in object member name' in result['detail'] or 'duplicate object key' in result['detail'], result)
                self.assert_audited_state(before, 1)

    def test_store_names(self):
        # Includes all pending raw-DDL columns. Admission must not depend on
        # whether this column's INSERT or UPDATE guard has landed yet.
        store = api.adopt_in_memory(self.db)  # the current module, including its mutant
        for table, columns in store._json.items():
            for column in columns:
                for value in ({'a\0suffix': 1}, {'outer': [{'a\0suffix': 1}]},
                        '{"a\\u0000suffix":1}', '{"outer":[{"a\\u0000suffix":1}]}',
                        '{"a":1,"a":2}', '{"outer":[{"a":1,"\\u0061":2}]}'):
                    for event in ('insert', 'update'):
                        with self.subTest(table=table, column=column, value=value, event=event):
                            before = self.state(exclude=())
                            with patch.object(canonical.rfc8785, 'dumps', side_effect=AssertionError('serialized before refusal')):
                                with self.assertRaises(api.StoreWriteError), store.transaction():
                                    if event == 'insert':
                                        store.insert(table, {column: value})
                                    elif event == 'update':
                                        store.update(table, {column: None}, {column: value})
                            self.assertEqual(self.state(exclude=()), before)

    def test_boundary_control(self):
        value = {'outer': [{'a': 'kept\0value'}, {'a': 2, 'A': 3}]}
        self.assertEqual(boundary.normalize(value, 'request_invalid'), value)
        self.assertEqual(boundary.normalize(json.dumps(value), 'request_invalid'), value)
        with self.store.transaction():
            self.store.insert('audit_events', {'audit_event_id': 'aud_membercontrol',
                'at': self.clock(), 'kind': 'member_control', 'detail': value})
        self.assertEqual(self.store.select('audit_events', {'audit_event_id': 'aud_membercontrol'})[0]['detail'], value)

    def test_store_all_columns_control(self):
        value = {'outer': [{'a': 'kept\0value'}, {'a': 2, 'A': 3}]}
        store = api.adopt_in_memory(self.db)
        for table, columns in store._json.items():
            for column in columns:
                for source in (value, json.dumps(value)):
                    with self.subTest(table=table, column=column):
                        self.assertEqual(json.loads(store._prepare(table, column, source)), value)

    def test_confidence_labels(self):
        doc = workflow.contract(1, None, rated=False)
        doc['confidence_scheme'] = {'scheme_id': 'rubric', 'version': 1,
            'labels': {'strong\0suffix': 'Several independently checked origins'}}
        before = self.state(exclude=())
        with patch.object(canonical.rfc8785, 'dumps', side_effect=AssertionError('hashed refused label')):
            result = self.router.draft_contract({'document': doc})
        self.assertEqual(result['reason'], 'request_invalid', result)
        self.assertIn('NUL in object member name', result['detail'])
        self.assertEqual(self.state(exclude=()), before)

    def test_confidence_control(self):
        self.assertEqual(self.open_brief()['status'], 'recorded')
        self.confirm()
        doc = workflow.contract(1, None, rated=False)
        doc['confidence_scheme'] = {'scheme_id': 'rubric', 'version': 1,
            'labels': {'strong': 'Kept\0value', 'Strong': 'Different case'}}
        doc['content_hash'] = canonical.content_hash(doc)
        result = self.router.draft_contract({'document': doc})
        self.assertEqual(result['status'], 'recorded', result)
        self.assertEqual(self.store.select('contract_revisions', {'topic_id': rf.TOPIC})[0]['document'], doc)

    def test_source_coverage_map(self):
        self.to_scoping()
        grant = self.started('inv_scoping01')
        doc = workflow.proposal(grant)
        doc['motivation']['observed_coverage'] = {'lane\0suffix': 'unknown'}
        env = self.envelope(grant, 'op_proposenul01', {**rf.empty_outcome(grant['invocation_id'], 'interim_transition'), 'source_proposals': [doc]})
        before = self.state()
        result = self.router.commit_outcome(env)
        self.assertEqual((result['status'], result['reason']), ('rejected', 'payload_invalid'), result)
        self.assertIn('NUL in object member name', result['detail'])
        self.assert_audited_state(before, 1)

    def test_source_coverage_control(self):
        self.to_scoping()
        grant = self.started('inv_scoping01')
        doc = workflow.proposal(grant)
        doc['motivation']['observed_coverage'] = {'lane': 'unknown', 'Lane': 'unknown'}
        env = self.envelope(grant, 'op_proposegood01', {**rf.empty_outcome(grant['invocation_id'], 'interim_transition'), 'source_proposals': [doc]})
        result = self.router.commit_outcome(env)
        self.assertEqual(result['status'], 'committed', result)
        self.assertEqual(self.store.select('source_proposals')[0]['document'], doc)
