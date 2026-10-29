"""Optional /2 references bind recorded relationships, never semantic truth."""
import copy
import json

from gen2.core import canonical
from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.router_fixtures import ReceiptCase
from gen2.tests.router_fixtures import CheckCase, KINDS, OUTCOMES


class ReferenceCases:
    record = CheckCase.record

    def setUp(self):
        super().setUp()
        self.admit()
        self.doc = self.document()
        self.doc['receipt_version'] = 'verification-receipt/2'
        self.doc['detailed_checks'] = {k: dict(outcome='succeeded', record_id=k) for k in KINDS}
        for k in KINDS:
            self.doc['checks'][k] = 'checked_ok'
        self.records = [self.make_record(k) for k in KINDS]
        self.assertEqual(self.commit_records(self.records)['status'], 'committed')

    def make_record(self, kind, outcome='succeeded'):
        r = self.record(kind=kind, outcome=outcome, **self.doc['claim'], cited_spans=self.doc['cited_spans'],
            applicability_reason='Qualitative fixture; this aspect is inapplicable.')
        r['check_id'] = kind
        return r

    def commit_records(self, records, op="op_referencechecks"):
        payload = {**empty_outcome(self.verifier['invocation_id'], 'interim_transition'), 'detailed_check_records': records}
        return self.router.commit_outcome(self.envelope(self.verifier, op, payload, refs=[r['evidence_ref'] for r in records]))

    def submit(self):
        return self.send(self.doc, op="op_" + self.doc["verification_receipt_id"])

    def rejected_reference(self):
        before = self.state(exclude=())
        result = self.submit()
        self.assertEqual(result['status'], 'rejected', result)
        self.assertEqual(result.get('reason'), 'payload_invalid', result)
        self.assertIn('receipt detailed check binding', result['detail'])
        self.assert_audited_state(before, 1)

    def corrupt(self, field, value):
        self.x('DROP TRIGGER IF EXISTS detailed_check_records_immutable_u')
        for kind in KINDS:
            original = self.store.select('detailed_check_records', {'check_id': kind})[0]
            if field in ('topic_id', 'performer_invocation_id'):
                self.x('UPDATE detailed_check_records SET ' + field + '=? WHERE check_id=?', value, kind)
            else:
                self.x('UPDATE detailed_check_records SET assessment=json_set(assessment, ?, json(?)) WHERE check_id=?',
                    '$.' + field, json.dumps(value), kind)
            self.rejected_reference()
            self.x('UPDATE detailed_check_records SET topic_id=?, performer_invocation_id=?, assessment=? WHERE check_id=?',
                original['topic_id'], original['performer_invocation_id'], canonical.canonical_bytes(original['assessment']).decode(), kind)

    def test_control(self):
        self.assertEqual(self.submit()['status'], 'committed')
        self.assertEqual(self.store.select('verification_receipts')[0]['receipt'], self.doc)
        self.assertEqual(self.rows('PRAGMA foreign_key_check'), [])
        self.assertEqual(self.value('SELECT status FROM claims'), 'provisional')

    def test_one_reference_control(self):
        for kind in KINDS[1:]:
            del self.doc['detailed_checks'][kind]['record_id']
        self.test_control()

    def test_missing(self):
        for kind in KINDS:
            self.doc['detailed_checks'] = {k: {'outcome': 'succeeded'} for k in KINDS}
            self.doc['detailed_checks'][kind]['record_id'] = 'absent'
            self.rejected_reference()

    def test_claim(self): self.corrupt('claim_id', 'clm_foreign01')
    def test_revision(self): self.corrupt('claim_revision', 2)
    def test_kind(self): self.corrupt('kind', 'invented')
    def test_outcome(self): self.corrupt('outcome', 'failed')
    def test_work(self): self.corrupt('work_id', 'wrk_foreign01')
    def test_version(self): self.corrupt('source_version', 'v2')
    def test_source(self): self.corrupt('source_artifact_hash', 'sha256:' + '0' * 64)
    def test_artifact(self): self.corrupt('examined_artifact_ref.content_hash', 'sha256:' + '1' * 64)
    def test_verifier(self): self.corrupt('performer_invocation_id', self.producer['invocation_id'])
    def test_topic(self): self.corrupt('topic_id', 'fleet-a:t2')

    def test_spans(self):
        span = self.doc['cited_spans'][0]
        for spans in ([{**span, 'end': 6}], [{**span, 'locator': {'kind': 'section', 'value': 'Elsewhere'}}], [span, span]):
            self.corrupt('cited_spans', spans)

    def test_extraction_control(self):
        from gen2.tests.router_fixtures import extraction_document
        for method in ('verifier_extraction', 'validated_extraction'):
            basis = extraction_document(self, method)['extraction']
            self.doc['extraction'] = basis
            self.doc['verification_receipt_id'] = 'ver_' + method
            self.assertEqual(self.submit()['status'], 'committed')

    def test_validated_equal_control(self):
        from gen2.tests.router_fixtures import extraction_document
        self.doc['extraction'] = extraction_document(self, 'validated_extraction')['extraction']
        self.test_control()

    def distinct_validated(self):
        target_ref = self.artifact(b'Target extraction: distinct retained representation.')
        validator_ref = self.artifact(b'Independent extraction: equivalent meaning, distinct bytes.')
        self.assertEqual(len({self.source['content_hash'], target_ref['content_hash'], validator_ref['content_hash']}), 3)
        validation = self.store.select('extraction_validations_v2')[0]
        def extraction(key, identity, ref):
            row = self.store.select('source_extractions', {'extraction_id': validation[key]})[0]
            return {**{k: v for k, v in row.items() if k not in
                ('topic_id', 'extracting_invocation_id', 'recorded_by_operation_id', 'created_at')},
                'extraction_id': identity, 'output_ref': ref}
        target = extraction('target_extraction_id', 'distinct-target', target_ref)
        validator = extraction('validator_extraction_id', 'distinct-validator', validator_ref)
        def commit(grant, op, refs, **sections):
            payload = {**empty_outcome(grant['invocation_id'], 'interim_transition'), **sections}
            out = self.router.commit_outcome(self.envelope(grant, op, payload, refs=refs))
            self.assertEqual(out['status'], 'committed', out)
        commit(self.producer, 'op_distincttarget', [target_ref], source_extractions=[target])
        v = {k: val for k, val in validation.items() if k not in
            ('validator_invocation_id', 'recorded_by_operation_id', 'created_at')}
        v.update(validation_id='distinct-validation', target_extraction_id=target['extraction_id'],
            validator_extraction_id=validator['extraction_id'], comparison='semantic_agreement', comparison_evidence_ref=validator_ref)
        records = []
        for basis, ref in (('target', target_ref), ('validator', validator_ref)):
            for kind in KINDS:
                record = self.record(kind=kind, **self.doc['claim'], cited_spans=self.doc['cited_spans'], examined_artifact_ref=ref)
                record['check_id'] = basis + '-' + kind
                records.append(record)
        commit(self.verifier, 'op_distinctvalidation', [validator_ref, *[r['evidence_ref'] for r in records]],
            source_extractions=[validator], extraction_validations_v2=[v], detailed_check_records=records)
        self.doc['extraction'].update(method='validated_extraction', extractor=target['extractor_identity'],
            produced_by_invocation_id=self.producer['invocation_id'], validation_ref=v['validation_id'])

    def single_validated_reference(self, kind, basis):
        self.doc['verification_receipt_id'] = 'ver_' + basis + '_' + kind
        self.doc['detailed_checks'] = {k: {'outcome': 'succeeded'} for k in KINDS}
        self.doc['detailed_checks'][kind]['record_id'] = kind if basis == 'canonical' else basis + '-' + kind

    def test_distinct_validated_target(self):
        self.distinct_validated()
        for kind in KINDS:
            with self.subTest(kind=kind):
                self.single_validated_reference(kind, 'target')
                out = self.submit()
                self.assertEqual(out['status'], 'committed', out)
                self.assertEqual(self.store.select('verification_receipts',
                    {'verification_receipt_id': self.doc['verification_receipt_id']})[0]['receipt'], self.doc)

    def test_distinct_validated_wrong_basis(self):
        self.distinct_validated()
        for kind in KINDS:
            for basis in ('canonical', 'validator'):
                with self.subTest(kind=kind, basis=basis):
                    self.single_validated_reference(kind, basis)
                    self.rejected_reference()

    def test_extraction_artifact(self):
        from gen2.tests.router_fixtures import extraction_document
        for method in ('verifier_extraction', 'validated_extraction'):
            self.doc['extraction'] = extraction_document(self, method)['extraction']
            self.doc['verification_receipt_id'] = 'ver_' + method
            self.test_artifact()


    def distinct_extraction(self):
        ref = self.artifact(b'Distinct extracted fixture text')
        row = self.store.select('source_extractions', {'extracting_invocation_id': self.verifier['invocation_id']})[0]
        record = {k: v for k, v in row.items() if k not in ('topic_id', 'extracting_invocation_id', 'recorded_by_operation_id', 'created_at')}
        record.update(extraction_id='distinct-output', output_ref=ref)
        records = [self.record(kind=k, **self.doc['claim'], cited_spans=self.doc['cited_spans'], examined_artifact_ref=ref) for k in KINDS]
        for r in records:
            r['check_id'] = r['assessment']['kind'] + '-distinct'
            self.doc['detailed_checks'][r['assessment']['kind']]['record_id'] = r['check_id']
        payload = {**empty_outcome(self.verifier['invocation_id'], 'interim_transition'),
            'source_extractions': [record], 'detailed_check_records': records}
        refs = [ref, *[r['evidence_ref'] for r in records]]
        out = self.router.commit_outcome(self.envelope(self.verifier, 'op_distinctbasis', payload, refs=refs))
        self.assertEqual(out['status'], 'committed', out)
        self.doc['extraction'].update(method='verifier_extraction', extraction_id='distinct-output',
            extractor=record['extractor_identity'], produced_by_invocation_id=self.verifier['invocation_id'])

    def test_distinct_extraction_control(self):
        self.distinct_extraction()
        self.test_control()

    def test_extraction_wrong_basis(self):
        self.distinct_extraction()
        self.x('DROP TRIGGER detailed_check_records_immutable_u')
        for r in self.store.select('detailed_check_records'):
            if r['check_id'].endswith('-distinct'):
                report = r['assessment']
                report['examined_artifact_ref'] = self.source
                self.x('UPDATE detailed_check_records SET assessment=? WHERE check_id=?', canonical.canonical_bytes(report).decode(), r['check_id'])
        self.rejected_reference()


    def test_domain(self):
        for change in ('missing', 'extra', 'null', 'legacy', 'projection', 'version', 'v1'):
            original = copy.deepcopy(self.doc)
            if change == 'missing': del self.doc['detailed_checks']['negation']
            if change == 'extra': self.doc['detailed_checks']['invented'] = {'outcome': 'succeeded'}
            if change == 'null': self.doc['detailed_checks']['negation']['record_id'] = None
            if change == 'legacy': self.doc['detailed_checks']['negation']['outcome'] = 'checked_ok'
            if change == 'projection': self.doc['detailed_checks']['negation']['outcome'] = 'not_applicable'
            if change == 'version': self.doc['receipt_version'] = 'verification-receipt/99'
            if change == 'v1': self.doc['receipt_version'] = 'verification-receipt/1'
            before = self.state(exclude=())
            out = self.submit()
            self.assertEqual((out['status'], out.get('reason')), ('rejected', 'payload_invalid'), change)
            self.assert_audited_state(before, 1)
            self.doc = original

    def test_outcomes_optional_legacy(self):
        for outcome, summary in zip(OUTCOMES, ('checked_ok', 'checked_problem', 'not_applicable', 'not_checked', 'unavailable')):
            self.doc['verdict'] = 'does_not_support'
            records = [self.make_record(k, outcome) for k in KINDS]
            for r in records:
                r['check_id'] += '-' + outcome
                kind = r['assessment']['kind']
                self.doc['detailed_checks'][kind] = {'outcome': outcome, 'record_id': r['check_id']}
                self.doc['checks'][kind] = summary
            self.assertEqual(self.commit_records(records, 'op_records_' + outcome)['status'], 'committed')
            self.doc['verification_receipt_id'] = 'ver_outcome_' + outcome
            self.assertEqual(self.submit()['status'], 'committed', outcome)
        self.doc['verdict'] = 'supports'
        for kind in KINDS:
            self.doc['checks'][kind] = 'checked_ok'
            self.doc['detailed_checks'][kind] = {'outcome': 'succeeded'}
        self.doc['verification_receipt_id'] = 'ver_optional001'
        self.assertEqual(self.submit()['status'], 'committed')  # Sampled use retains optional references.
        self.doc['verification_receipt_id'] = 'ver_legacy001'
        self.doc['receipt_version'] = 'verification-receipt/1'
        del self.doc['detailed_checks']
        self.assertEqual(self.submit()['status'], 'committed')
        self.assertEqual(self.store.select('verification_receipts', {'verification_receipt_id': 'ver_legacy001'})[0]['receipt'], self.doc)


class ReferenceRouterTest(ReferenceCases, ReceiptCase):
    def test_same_commit_replay_rollback(self):
        for r in self.records:
            r['check_id'] += '-new'
            self.doc['detailed_checks'][r['assessment']['kind']]['record_id'] = r['check_id']
        payload = {**empty_outcome(self.verifier['invocation_id'], 'interim_transition'),
            'detailed_check_records': self.records, 'verification_receipts': [self.doc]}
        env = self.envelope(self.verifier, 'op_combinedrefs', payload, refs=[r['evidence_ref'] for r in self.records])
        before = self.state(exclude=())
        self.faults['in_transaction:evidence'] = RuntimeError('combined rollback')
        with self.assertRaisesRegex(RuntimeError, 'combined rollback'):
            self.router.commit_outcome(env)
        self.assertEqual(self.state(exclude=()), before)
        self.faults.clear()
        self.assertEqual(self.router.commit_outcome(env)['status'], 'committed')
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(env)['status'], 'replayed')
        self.assertEqual(self.state(exclude=()), before)
        self.doc['detailed_checks']['negation']['record_id'] = 'missing'
        self.assertEqual(self.send(self.doc, op='op_combinedrefs')['reason'], 'operation_id_conflict')
