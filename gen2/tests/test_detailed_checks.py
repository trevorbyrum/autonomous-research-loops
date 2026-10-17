"""V-8 durable admission only; literal fixture bytes, no provider execution."""
import json

from gen2.tests.router_fixtures import TOPIC, empty_outcome
from gen2.tests.test_reaccess_admission import AcquisitionCase

KINDS = ('numeric_units', 'denominators', 'negation', 'qualifications')
OUTCOMES = ('succeeded', 'failed', 'not_applicable', 'not_checked', 'unavailable')


class CheckCase(AcquisitionCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.capture(self.producer, 'op_claimcheck1')['status'], 'committed')
        self.assertEqual(self.capture(self.verifier, 'op_setupcheck1', claim=None)['status'], 'committed')

    def record(self, **changes):
        span = {'start': 0, 'end': 10, 'locator': {'kind': 'paragraph', 'value': '1'}}
        report = dict(claim_id='clm_00000001', claim_revision=1, work_id=self.work, source_version='v1',
            source_artifact_hash=self.source['content_hash'], examined_artifact_ref=self.source,
            cited_spans=[span], context_spans=[{**span, 'end': 20}], kind='numeric_units', outcome='succeeded',
            method='attributed-assessment/1', assessment='Verifier assessment of this claim and source.',
            context_examined='No quantities; units interpreted in the retained surrounding text.', applicability_reason='')
        report.update(changes)
        ref = self.artifact(json.dumps(report).encode(), 'application/json')
        return dict(check_id='check-1', assessment=report, evidence_ref=ref)

    def env(self, record, grant=None, op='op_detailcheck1'):
        grant = grant or self.verifier
        payload = {**empty_outcome(grant['invocation_id'], 'interim_transition'), 'detailed_check_records': [record]}
        return self.envelope(grant, op, payload, refs=[record['evidence_ref']] if record['evidence_ref'] else [])

    def send(self, record, grant=None, op='op_detailcheck1'):
        return self.router.commit_outcome(self.env(record, grant, op))

    def refuse(self, record):
        before = self.state()
        out = self.send(record)
        self.assertEqual(out['status'], 'rejected', out)
        self.assertEqual(self.state(), before)


class RecordMatrix:
    def test_control(self):
        record = self.record()
        self.assertEqual(self.send(record)['status'], 'committed')
        row = self.store.select('detailed_check_records')[0]
        self.assertEqual(row['assessment'], record['assessment'])
        self.assertEqual(row['performer_invocation_id'], self.verifier['invocation_id'])
        self.assertEqual(self.rows('SELECT * FROM verification_receipts'), [])
        self.assertEqual(self.value("SELECT status FROM claims WHERE claim_id='clm_00000001'"), 'provisional')
        self.assertEqual(self.rows('PRAGMA foreign_key_check'), [])

    def test_outcomes(self):
        for kind in KINDS:
            for outcome in OUTCOMES:
                with self.subTest(kind=kind, outcome=outcome):
                    record = self.record(kind=kind, outcome=outcome, applicability_reason='Qualitative statement only; no numerical base is asserted.')
                    record['check_id'] = kind + '-' + outcome
                    if outcome in ('not_checked', 'unavailable'):
                        record['evidence_ref'] = None
                    self.assertEqual(self.send(record, op='op_' + record['check_id'])['status'], 'committed')
        self.assertEqual(len(self.store.select('detailed_check_records')), 20)

    def test_domain(self):
        for kind in KINDS:
            for change in ({'method': 'quote-protection/5'}, {'outcome': 'checked_ok'}, {'claim_revision': 0},
                    {'kind': 'invented'}, {'assessment': ''}, {'context_examined': ' \t\n'}, {'context_examined': '\u200b\u00a0'},
                    {'outcome': 'not_applicable', 'applicability_reason': ''},
                    {'outcome': 'not_applicable', 'applicability_reason': '\u200b\u00a0'}, {'cited_spans': []}):
                with self.subTest(kind=kind, change=change):
                    self.refuse(self.record(**{'kind': kind, **change}))

    def test_missing_evidence(self):
        for kind in KINDS:
            for outcome in OUTCOMES[:3]:
                record = self.record(kind=kind, outcome=outcome, applicability_reason='Explicit scope rationale')
                record['evidence_ref'] = None
                self.refuse(record)

    def test_bindings(self):
        for kind in KINDS:
            for change in ({'claim_id': 'clm_absent001'}, {'claim_revision': 2}, {'work_id': 'wrk_absent001'},
                    {'source_version': 'foreign'}, {'source_artifact_hash': 'sha256:' + '0' * 64}):
                with self.subTest(kind=kind, change=change):
                    self.refuse(self.record(kind=kind, **change))

    def test_producer(self):
        self.x('DROP TRIGGER claims_identity_immutable')
        self.x('UPDATE claims SET producer_invocation_id=?', self.verifier['invocation_id'])
        for kind in KINDS:
            self.refuse(self.record(kind=kind))

    def test_spans(self):
        for field in ('cited_spans', 'context_spans'):
            for span in ({'start': 0.5, 'end': 1}, {'start': -1, 'end': 2}, {'start': 0, 'end': 0},
                    {'start': 0, 'end': 2, 'locator': {'kind': 'invented', 'value': '1'}}):
                for kind in KINDS:
                    self.refuse(self.record(kind=kind, **{field: [span]}))

    def test_topic_artifact(self):
        self.x("DROP TRIGGER artifact_topics_immutable_d")
        self.x("DELETE FROM artifact_topics WHERE content_hash=?", self.source["content_hash"])
        for kind in KINDS:
            self.refuse(self.record(kind=kind))

    def test_artifacts(self):
        for kind in KINDS:
            record = self.record(kind=kind)
            record['assessment']['examined_artifact_ref'] = {**self.source, 'size_bytes': 999}
            self.refuse(record)
            record = self.record(kind=kind)
            record['evidence_ref'] = {**record['evidence_ref'], 'size_bytes': 999}
            self.refuse(record)


class RouterCheckTest(RecordMatrix, CheckCase):
    def test_router_bindings(self):
        self.x("DROP TRIGGER detailed_check_records_binding")
        self.test_bindings()

    def test_evidence_mismatch(self):
        for kind in KINDS:
            record = self.record(kind=kind)
            record['assessment']['outcome'] = 'failed'
            self.refuse(record)

    def test_authentication(self):
        original = self.spool.read
        record = self.record()
        self.spool.read = lambda digest, **kw: b'corrupt' if digest == record['evidence_ref']['content_hash'] else original(digest, **kw)
        self.refuse(record)

    def test_authentication_control(self):
        reads, original = [], self.spool.read
        def read(*a, **kw):
            reads.append(self.db.in_transaction)
            return original(*a, **kw)
        self.spool.read = read
        self.test_control()
        self.assertTrue(reads)
        self.assertFalse(any(reads))

    def test_kind(self):
        before = self.state()
        self.assertEqual(self.send(self.record(), self.producer)['status'], 'rejected')
        self.assertEqual(self.state(), before)

    def test_replay_rollback(self):
        record = self.record()
        env = self.env(record)
        self.assertEqual(self.router.commit_outcome(env)['status'], 'committed')
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(env)['status'], 'replayed')
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.router.commit_outcome({**env, 'expected_state_revision': 999})['reason'], 'operation_id_conflict')
        self.refuse(self.record(outcome='failed'))
        record = self.record(outcome='unavailable')
        record['check_id'] = 'rolled-back'
        before = self.state(exclude=())
        self.faults['in_transaction:evidence'] = RuntimeError('after detailed check')
        with self.assertRaisesRegex(RuntimeError, 'after detailed check'):
            self.send(record, op='op_detailfault1')
        self.assertEqual(self.state(exclude=()), before)
