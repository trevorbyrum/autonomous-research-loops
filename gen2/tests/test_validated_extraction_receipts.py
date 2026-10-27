"""Successful retained /2 bases bind receipts through the Router."""
import json
import unittest

from gen2.tests.detailed_receipt_fixtures import seed_checks, historical_receipt, historical_admission
from gen2.tests.test_canonical_content_tiers import FULL, fixture
from gen2.tests.test_extraction_acquisitions import extraction_document
from gen2.tests.test_own_extraction_receipts import OwnCases
from gen2.tests.independent_tier_fixtures import independent_basis


class ValidatedCases:
    def clone(self, table, changes, where=''):
        if table == 'source_extractions' and changes.get('extraction_id') == 'foreign-basis':
            changes = {**changes, 'extracting_invocation_id': self.doc['extraction']['produced_by_invocation_id'],
                'extractor_identity': self.doc['extraction']['extractor'], 'recorded_by_operation_id': self.case.value(
                    'SELECT recorded_by_operation_id FROM source_extractions WHERE extraction_id=?', self.target)}
        OwnCases.clone(self, table, changes, where)

    submit = OwnCases.submit

    def setUp(self):
        context = fixture(FULL)
        self.case = context.__enter__()
        self.doc = extraction_document(self.case, 'validated_extraction')
        seed_checks(self.case, self.doc)
        self.addCleanup(context.__exit__, None, None, None)
        self.validation = self.doc['extraction']['validation_ref']
        self.target, self.independent = self.case.rows('SELECT target_extraction_id, validator_extraction_id FROM extraction_validations_v2')[0]

    def refuse(self):
        # Historical /1 operands isolate the existing validation predicate.
        historical_receipt(self.doc)
        before = self.case.state(exclude=())
        with historical_admission(self.case):
            out = self.submit()
        self.assertEqual(out['status'], 'rejected', out)
        self.assertEqual(out.get('reason'), 'payload_invalid', out)
        self.assertIn('receipt needs its successful durable /2 validation', out['detail'])
        self.case.assert_audited_state(before, 1)
        self.assertEqual(self.case.rows('PRAGMA foreign_key_check'), [])

    def test_control(self):
        self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = 'bibliographic'
        self.assertEqual(self.submit()['status'], 'committed')
        self.assertEqual(json.loads(self.case.value('SELECT receipt FROM verification_receipts')), self.doc)
        self.assertEqual(self.case.rows('PRAGMA foreign_key_check'), [])

    def test_abstract_control(self):
        self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = 'abstract'
        self.assertEqual(self.submit()['status'], 'committed')

    def test_full_text_control(self):
        self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = 'full_text'
        self.assertEqual(self.submit()['status'], 'committed')

    def test_invented(self):
        self.doc['extraction']['validation_ref'] = 'invented'
        self.refuse()

    def test_all_verdicts(self):
        self.doc['extraction']['validation_ref'] = 'invented'
        for verdict in ('supports', 'partially_supports', 'does_not_support', 'cannot_assess_at_required_tier'):
            with self.subTest(verdict=verdict):
                self.doc['verdict'] = verdict
                self.refuse()

    def test_missing(self):
        historical_receipt(self.doc)
        self.doc['extraction']['validation_ref'] = None
        before = self.case.state(exclude=())
        with historical_admission(self.case):
            self.assertEqual(self.submit()['status'], 'rejected')
        self.case.assert_audited_state(before, 1)

    def test_legacy(self):
        cur = self.case.db.execute('SELECT * FROM extraction_validations_v2')
        row = dict(zip([d[0] for d in cur.description], cur.fetchone()))
        row.update(validation_id='legacy', policy_version=1)
        self.case.x(f"INSERT INTO extraction_validations ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())
        self.doc['extraction']['validation_ref'] = 'legacy'
        self.refuse()

    def test_failed(self):
        self.clone('extraction_validations_v2', dict(validation_id='failed', outcome='failed', comparison='disagreement'))
        self.doc['extraction']['validation_ref'] = 'failed'
        self.refuse()

    def test_integrity(self):
        self.clone('source_extractions', dict(extraction_id='same-family', extractor_identity=self.doc['extraction']['extractor']), "extraction_id='" + self.independent + "'")
        self.clone('extraction_validations_v2', dict(validation_id='integrity', method='same_family_replay', validator_extraction_id='same-family'))
        self.doc['extraction']['validation_ref'] = 'integrity'
        self.refuse()

    def test_unpinned(self):
        self.case.x('DROP TRIGGER source_extractions_immutable_u')
        self.case.x('UPDATE source_extractions SET extractor_registry_version=NULL WHERE extraction_id=?', self.target)
        self.refuse()

    def test_tool(self):
        self.doc['extraction']['extractor'] = 'Receipt-tool'
        self.refuse()

    def test_extractor(self):
        self.doc['extraction']['produced_by_invocation_id'] = self.case.verifier['invocation_id']
        self.refuse()

    def test_tier(self):
        self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = 'abstract'
        self.case.x('DROP TRIGGER source_extractions_immutable_u')
        self.case.x("UPDATE source_extractions SET supported_tier='bibliographic' WHERE extraction_id=?", self.target)
        self.refuse()

    def foreign(self, selector):
        # Reuse the admitted foreign acquisition builder, then record a valid
        # independent pair on that acquisition. Every foreign key stays valid.
        OwnCases.foreign(self, selector)
        self.clone('source_extractions', dict(extraction_id='foreign-independent', extractor_identity=self.case.value('SELECT extractor_identity FROM source_extractions WHERE extraction_id=?', self.independent),
            extracting_invocation_id=self.case.verifier['invocation_id'], recorded_by_operation_id=self.case.value('SELECT recorded_by_operation_id FROM source_extractions WHERE extraction_id=?', self.independent)), "extraction_id='foreign-basis'")
        self.clone('extraction_validations_v2', dict(validation_id='foreign-validation', target_extraction_id='foreign-basis', validator_extraction_id='foreign-independent'))
        self.doc['extraction']['validation_ref'] = 'foreign-validation'

    def test_work(self): self.foreign('work'); self.refuse()
    def test_version(self): self.foreign('version'); self.refuse()
    def test_call(self): self.foreign('call'); self.refuse()
    def test_time(self): self.foreign('time'); self.refuse()
    def test_route(self): self.foreign('route'); self.refuse()

    def test_verifier(self):
        old_validation = self.validation
        self.assertEqual(self.case.finish(self.case.verifier, 'op_oldverify1')['status'], 'committed')
        self.case.verifier = self.case.started('inv_foreign01', 'verification')
        self.case.admit()
        self.doc = extraction_document(self.case, 'validated_extraction')
        self.doc['extraction']['validation_ref'] = old_validation
        self.refuse()

    def test_history_control(self):
        tools = self.case.rows('SELECT extractor_identity FROM extractor_tools')
        self.assertEqual(self.case.router.register_extractor_registry(dict(registry_version=2, operator_id='fixture-operator', reason='merge families',
            tools=[dict(extractor_identity=t[0], family='merged') for t in tools]))['status'], 'registered')
        self.test_control()


class ValidatedReceiptRouterTest(ValidatedCases, unittest.TestCase):
    def test_independent_tier(self):
        for n, (required, independent) in enumerate((('abstract', 'bibliographic'), ('full_text', 'bibliographic'), ('full_text', 'abstract'))):
            with self.subTest(required=required, independent=independent):
                self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = required
                independent_basis(self.case, self.doc, independent, 'low' + str(n))
                self.assertEqual(self.case.value('SELECT supported_tier FROM source_extractions WHERE extraction_id=?', self.target), 'full_text')
                self.assertEqual(self.case.router._detailed_checks._content_rank(self.case.store.select('source_acquisitions')[0]), 3)
                self.refuse()

    def test_independent_tier_control(self):
        self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = 'full_text'
        independent_basis(self.case, self.doc, 'full_text')
        self.test_full_text_control()

    def test_replay_conflict_rollback(self):
        before = self.case.state(exclude=())
        self.case.faults['in_transaction:end'] = RuntimeError('after validated receipt')
        with self.assertRaisesRegex(RuntimeError, 'after validated receipt'):
            self.submit()
        self.assertEqual(self.case.state(exclude=()), before)
        self.case.faults.clear()
        self.test_control()
        before = self.case.state(exclude=())
        self.assertEqual(self.case.router.commit_outcome(self.case.env)['status'], 'replayed')
        self.assertEqual(self.case.state(exclude=()), before)
        self.doc['extraction']['validation_ref'] = 'different'
        self.assertEqual(self.submit()['reason'], 'operation_id_conflict')
