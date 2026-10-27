"""V-8 durable admission only; literal fixture bytes, no provider execution."""
import json

from gen2.tests.router_fixtures import CheckCase, KINDS, OUTCOMES

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
                    out = self.refuse(self.record(**{'kind': kind, **change}))
                    if not self.RAW:
                        self.assertEqual(out.get('reason'), 'payload_invalid', out)

    def test_missing_evidence(self):
        for kind in KINDS:
            for outcome in OUTCOMES[:3]:
                record = self.record(kind=kind, outcome=outcome, applicability_reason='Explicit scope rationale')
                record['evidence_ref'] = None
                out = self.refuse(record)
                if not self.RAW:
                    self.assertEqual(out.get('reason'), 'payload_invalid', out)

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
                    out = self.refuse(self.record(kind=kind, **{field: [span]}))
                    if not self.RAW:
                        self.assertEqual(out.get('reason'), 'payload_invalid', out)

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
    def test_required_nonblank_nul(self):
        for kind in KINDS:
            for field, outcome in (('assessment', 'succeeded'), ('assessment', 'failed'),
                    ('assessment', 'not_applicable'), ('context_examined', 'succeeded'),
                    ('context_examined', 'failed'), ('context_examined', 'not_applicable'),
                    ('applicability_reason', 'not_applicable')):
                for index, (value, expected) in enumerate((
                        ('\0', ('rejected', 'payload_invalid')),
                        ('Valid text', ('committed', None)),
                        ('Valid text\0', ('committed', None)),
                        ('\0Valid text', ('rejected', 'payload_invalid')),
                        (' \u00a0\u200b\0Valid text', ('rejected', 'payload_invalid')),
                        (' \u00a0\u200bValid text\0', ('committed', None)))):
                    with self.subTest(kind=kind, field=field, outcome=outcome, value=value):
                        report = dict(kind=kind, outcome=outcome, applicability_reason='Explicit scope rationale')
                        report[field] = value
                        record = self.record(**report)
                        record['check_id'] = f'{kind}-{field}-{outcome}-{index}'
                        before = self.state(exclude=())
                        out = self.send(record, op='op_' + record['check_id'])
                        self.assertEqual((out['status'], out.get('reason')), expected, out)
                        rows = self.store.select('detailed_check_records', {'check_id': record['check_id']})
                        if expected == ('rejected', 'payload_invalid'):
                            self.assertEqual(rows, [])
                            self.assert_audited_state(before, 1)
                        else:
                            self.assertEqual(len(rows), 1)
                            self.assertEqual(rows[0]['assessment'], record['assessment'])

    def test_optional_nonblank_nul(self):
        for kind in KINDS:
            for outcome in ('succeeded', 'failed', 'not_checked', 'unavailable'):
                with self.subTest(kind=kind, outcome=outcome):
                    report = dict(kind=kind, outcome=outcome, applicability_reason='\0')
                    if outcome in ('not_checked', 'unavailable'):
                        report.update(assessment='\0', context_examined='\0')
                    record = self.record(**report)
                    record['check_id'] = kind + '-' + outcome
                    out = self.send(record, op='op_' + record['check_id'])
                    self.assertEqual((out['status'], out.get('reason')), ('committed', None), out)
                    rows = self.store.select('detailed_check_records', {'check_id': record['check_id']})
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]['assessment'], record['assessment'])

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
        self.assert_audited_state(before, 1)

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


class AuthenticationRegressionTest(CheckCase):
    def recorded(self):
        record = self.record()
        self.assertEqual(self.send(record)['status'], 'committed')
        return record

    def retry_without_refs(self, record):
        record['check_id'] = 'fresh-check'
        env = self.env(record, op='op_freshcheck1')
        env['result_refs'] = []
        return env

    def test_recorded_bytes_control(self):
        record = self.recorded()
        self.assertEqual(self.router.commit_outcome(self.retry_without_refs(record))['status'], 'committed')

    def corruption(self, field):
        record = self.recorded()
        ref = record['assessment']['examined_artifact_ref'] if field == 'examined' else record['evidence_ref']
        original = self.spool.read
        self.spool.read = lambda digest, **kw: b'corrupt' if digest == ref['content_hash'] else original(digest, **kw)
        env, before = self.retry_without_refs(record), self.state()
        result = self.router.commit_outcome(env)
        self.assertEqual(result['status'], 'rejected', result)
        self.assertIn('hash', result['detail'])
        self.assert_audited_state(before, 1)

    def test_recorded_examined_corrupt(self): self.corruption('examined')
    def test_recorded_evidence_omitted_corrupt(self): self.corruption('evidence')

    def test_fresh_operation_collision(self):
        record = self.recorded()
        before = self.state()
        result = self.send(self.record(outcome='failed'), op='op_newcollision')
        self.assertEqual(result['status'], 'rejected', result)
        self.assertIn('UNIQUE', result['detail'])
        self.assert_audited_state(before, 1)
        self.assertEqual(self.store.select('detailed_check_records')[0]['assessment'], record['assessment'])
