"""Durable own-extraction receipt bindings through the Router."""
import json
import unittest

from gen2.tests.detailed_receipt_fixtures import seed_checks, historical_receipt, historical_admission
from gen2.tests.test_canonical_content_tiers import FULL, fixture
from gen2.tests.test_extraction_acquisitions import extraction_document, send


class OwnCases:

    def setUp(self):
        context = fixture(FULL)
        self.case = context.__enter__()
        self.doc = extraction_document(self.case, 'verifier_extraction')
        seed_checks(self.case, self.doc)
        self.addCleanup(context.__exit__, None, None, None)
        self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = 'bibliographic'

    def submit(self):
        return send(self.case, self.doc)

    def refuse(self):
        # Historical /1 operands isolate the existing extraction predicate.
        historical_receipt(self.doc)
        before = self.case.state(exclude=())
        with historical_admission(self.case):
            out = self.submit()
        self.assertEqual(out['status'], 'rejected', out)
        self.assertEqual(out.get('reason'), 'payload_invalid', out)
        self.assertIn('receipt needs its verifier durable extraction', out['detail'])
        self.case.assert_audited_state(before, 1)
        self.assertEqual(self.case.rows('PRAGMA foreign_key_check'), [])

    def clone(self, table, changes, where=''):
        cur = self.case.db.execute('SELECT * FROM ' + table + (' WHERE ' + where if where else '') + ' LIMIT 1')
        row = {**dict(zip([d[0] for d in cur.description], cur.fetchone())), **changes}
        self.case.x(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())

    def foreign(self, selector):
        c = self.case
        inv = self.doc['verifier_invocation_id']; version = 'v1'; work = c.work; event = c.EVENT_ID
        if selector == 'version':
            version = 'v2'
            self.clone('source_artifacts', {'source_version': version})
            self.clone('source_acquisitions', {'source_version': version})
        elif selector == 'verifier':
            self.assertEqual(c.finish(c.verifier, 'op_oldverify1')['status'], 'committed')
            c.verifier = c.started('inv_foreign01', 'verification')
            c.admit()
            self.doc = extraction_document(c, 'verifier_extraction')
            op = c.value('SELECT operation_id FROM operation_receipts WHERE invocation_id = ?', c.verifier['invocation_id'])
            self.clone('source_extractions', dict(extraction_id='foreign-basis', extracting_invocation_id=c.verifier['invocation_id'],
                recorded_by_operation_id=op), "verifier_invocation_id = '" + inv + "'")
            self.doc['extraction']['extraction_id'] = 'foreign-basis'
            return
        else:
            observation = 'obs_foreign01'; event = 'rev_foreign01'
            changes = dict(observation_id=observation, attempt=2)
            if selector == 'call': changes['gateway_call_ref'] = 'gw-call:102'
            if selector == 'route':
                request = json.loads(c.value('SELECT request FROM search_observations'))
                request['lane'] = 'core'
                changes.update(lane='core', request=json.dumps(request))
            self.clone('search_observations', changes)
            event_changes = dict(event_id=event, observation_id=observation)
            if selector == 'time': event_changes['captured_at'] = '2026-09-28T10:00:00Z'
            if selector == 'work':
                work = 'wrk_foreign01'
                self.clone('works', dict(work_id=work, identity_value='10.1/foreign'))
                event_changes['provider_record_id'] = 'other-record'
            self.clone('retrieval_events', event_changes)
            self.clone('record_work_links', dict(event_id=event, work_id=work))
            if selector == 'work': self.clone('source_artifacts', {'work_id': work})
            obs = dict(zip([d[0] for d in c.db.execute('SELECT * FROM search_observations LIMIT 0').description],
                c.rows('SELECT * FROM search_observations WHERE observation_id = ?', observation)[0]))
            self.clone('source_acquisitions', dict(event_id=event, work_id=work, observation_id=observation, attempt=2,
                gateway_call_ref=obs['gateway_call_ref'], lane=obs['lane'], request_bytes=obs['request'].encode(),
                provider_record_id=event_changes.get('provider_record_id', 'doi:10.1/fixture'),
                retrieved_at=event_changes.get('captured_at', self.doc['acquisition']['retrieved_at'])))
        self.clone('source_extractions', dict(extraction_id='foreign-basis', work_id=work, source_version=version,
            event_id=event, verifier_invocation_id=inv, supported_tier='bibliographic'))
        self.doc['extraction']['extraction_id'] = 'foreign-basis'

    def test_control(self):
        self.assertEqual(self.submit()['status'], 'committed')
        self.assertEqual(json.loads(self.case.value('SELECT receipt FROM verification_receipts')), self.doc)
        self.assertEqual(self.case.rows('PRAGMA foreign_key_check'), [])

    def test_missing(self):
        del self.doc['extraction']['extraction_id']
        self.refuse()

    def test_invented(self):
        self.doc['extraction']['extraction_id'] = 'invented'
        self.refuse()

    def test_tool(self):
        self.doc['extraction']['extractor'] = 'Receipt-tool'
        self.refuse()

    def test_unpinned(self):
        self.case.x('DROP TRIGGER source_extractions_immutable_u')
        self.case.x('UPDATE source_extractions SET extractor_registry_version = NULL')
        self.refuse()

    def test_tier(self):
        self.case.x('DROP TRIGGER source_extractions_immutable_u')
        self.case.x("UPDATE source_extractions SET supported_tier = 'bibliographic'")
        self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = 'abstract'
        self.refuse()

    def test_extractor(self):
        op = self.case.value('SELECT operation_id FROM operation_receipts WHERE invocation_id = ?', self.case.ACQUIRER)
        self.clone('source_extractions', dict(extraction_id='foreign-basis', extracting_invocation_id=self.case.ACQUIRER, recorded_by_operation_id=op))
        self.doc['extraction']['extraction_id'] = 'foreign-basis'
        self.refuse()

    def test_version(self): self.foreign('version'); self.refuse()
    def test_work(self): self.foreign('work'); self.refuse()
    def test_verifier(self): self.foreign('verifier'); self.refuse()
    def test_call(self): self.foreign('call'); self.refuse()
    def test_time(self): self.foreign('time'); self.refuse()
    def test_route(self): self.foreign('route'); self.refuse()


class OwnReceiptRouterTest(OwnCases, unittest.TestCase):
    pass
