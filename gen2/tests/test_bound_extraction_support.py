"""Promotion consumes one durable basis; historical declarations stay fenced."""
import json
import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from gen2.store import db
from gen2.tests import store_fixtures as sf

from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.test_canonical_content_tiers import FULL, fixture
from gen2.tests.test_pending_extraction_support import METHODS, load_claim, support_document
from gen2.tests.test_own_extraction_receipts import OwnCases
from gen2.tests.test_validated_extraction_receipts import ValidatedCases


@contextmanager
def historical(case):
    # Model pre-consumer receipts in disposable memory. Preserve every other
    # guard, then restore the exact installed definitions, including mutants.
    names = ('verification_receipts_own_extraction', 'verification_receipts_validated_extraction')
    definitions = case.rows("SELECT name, sql FROM sqlite_schema WHERE type='trigger' ORDER BY rowid")
    selected = [(n, s) for n, s in definitions if n in names]
    for name, _ in selected:
        case.x('DROP TRIGGER ' + name)
    try:
        yield
    finally:
        for _, sql in selected:
            case.x(sql)
        actual = dict(case.rows("SELECT name, sql FROM sqlite_schema WHERE type='trigger'"))
        case.assertEqual(actual, dict(definitions))


class PromotionCases:
    RAW = False

    def context(self, method, tier='full_text'):
        with patch.object(sf, 'DDL_TEXT', db.schema_text()):
            context = fixture({**FULL, 'abstract': 'Recorded abstract'})
            self.case = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        load_claim(self.case, tier)
        self.doc = support_document(self.case, method, tier)
        self.target, self.independent = self.case.rows('SELECT target_extraction_id, validator_extraction_id FROM extraction_validations_v2')[0]
        # Seed authenticated operands under production DDL, then install exactly
        # the requested live view/trigger (mutants, trace instrumentation and
        # reversed definitions included). Never adopt an instrumented Store.
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(sf.DDL_TEXT)
            objects = reference.execute("SELECT type, name, sql FROM sqlite_schema WHERE type='trigger' OR name='bound_extraction_receipts' ORDER BY rowid").fetchall()
        for name, in self.case.rows("SELECT name FROM sqlite_schema WHERE type='trigger'"):
            self.case.x('DROP TRIGGER ' + name)
        self.case.x('DROP VIEW bound_extraction_receipts')
        for _, _, sql in objects:
            self.case.x(sql)
        actual = self.case.rows("SELECT type, name, sql FROM sqlite_schema WHERE type='trigger' OR name='bound_extraction_receipts' ORDER BY rowid")
        self.assertEqual(actual, objects)

    def clone(self, table, changes, where=''):
        if table == 'source_acquisitions' and changes.get('provider_record_id') == 'other-record':
            raw = self.case.value('SELECT response_bytes FROM source_acquisitions LIMIT 1')
            body = json.loads(raw); body['records'][0]['identity'] = 'other-record'
            changes = {**changes, 'response_bytes': json.dumps(body).encode().ljust(len(raw))}
        if table == 'source_extractions' and changes.get('extraction_id') == 'foreign-basis':
            changes = {**changes, 'supported_tier': 'full_text'}
        if self.doc['extraction']['method'] == 'validated_extraction':
            ValidatedCases.clone(self, table, changes, where)
        else:
            OwnCases.clone(self, table, changes, where)

    def store(self, legacy=False):
        if legacy:
            with historical(self.case):
                out = OwnCases.submit(type('Raw', (), dict(RAW=True, case=self.case, doc=self.doc))())
        elif self.RAW:
            out = OwnCases.submit(self)
        else:
            out = self.case.send(self.doc)
        self.assertEqual(out['status'], 'committed', out)

    def promote(self, expected='committed'):
        c = self.case
        before = c.state()
        if self.RAW:
            try:
                c.x("UPDATE claims SET status='accepted_support' WHERE claim_id='clm_loadbear1' AND revision=1")
                out = dict(status='committed')
            except sqlite3.IntegrityError as exc:
                out = dict(status='rejected', detail=str(exc))
        else:
            self.promotion_env = c.envelope(c.producer, 'op_promote001',
                {**empty_outcome(c.ACQUIRER, 'interim_transition'), 'claim_promotions':[dict(claim_id='clm_loadbear1', revision=1)]})
            out = c.router.commit_outcome(self.promotion_env)
        self.assertEqual(out['status'], expected, out)
        if expected == 'rejected':
            self.assertEqual(c.state(), before)
        else:
            self.assertEqual(c.rows("SELECT status FROM claims WHERE claim_id='clm_loadbear1'"), [('accepted_support',)])
        self.assertEqual(c.rows('PRAGMA foreign_key_check'), [])
        return out

    def test_control(self):
        for method in METHODS:
            for tier in ('bibliographic', 'abstract', 'full_text'):
                with self.subTest(method=method, tier=tier):
                    self.context(method, tier); self.store(); self.promote()
                    self.assertEqual(self.case.rows('SELECT verification_receipt_id FROM bound_extraction_receipts'), [(self.doc['verification_receipt_id'],)])

    def test_own_control(self):
        self.context('verifier_extraction'); self.store(); self.promote()

    def test_history_control(self):
        self.context('validated_extraction')
        tools = self.case.rows('SELECT extractor_identity FROM extractor_tools')
        self.assertEqual(self.case.router.register_extractor_registry(dict(registry_version=2, operator_id='fixture-operator', reason='merge',
            tools=[dict(extractor_identity=t[0], family='merged') for t in tools]))['status'], 'registered')
        self.store(); self.promote()

    def test_unbound(self):
        for method in METHODS:
            for kind in ('missing', 'invented', 'legacy', 'failed', 'integrity'):
                with self.subTest(method=method, kind=kind):
                    self.context(method)
                    if method == 'verifier_extraction':
                        self.doc['extraction'].pop('extraction_id')
                        if kind != 'missing': self.doc['extraction']['extraction_id'] = kind
                    else:
                        if kind in ('legacy', 'failed', 'integrity'):
                            helper = type('Helper', (), dict(case=self.case, doc=self.doc, target=self.target,
                                independent=self.independent, clone=self.clone, refuse=lambda _: None))()
                            getattr(ValidatedCases, 'test_' + kind)(helper)
                        else:
                            self.doc['extraction']['validation_ref'] = kind
                    self.store(legacy=True)
                    self.assertEqual(self.case.rows('SELECT * FROM bound_extraction_receipts'), [])
                    self.promote('rejected')

    def test_bindings(self):
        for method in METHODS:
            for field in ('work', 'version', 'verifier', 'call', 'time', 'route', 'tool', 'extractor', 'unpinned', 'tier'):
                with self.subTest(method=method, field=field):
                    self.context(method)
                    if field in ('work', 'version', 'verifier', 'call', 'time', 'route'):
                        if method == 'validated_extraction' and field == 'verifier':
                            old = self.doc['extraction']['validation_ref']
                            self.assertEqual(self.case.finish(self.case.verifier, 'op_oldverify1')['status'], 'committed')
                            self.case.verifier = self.case.started('inv_foreign01', 'verification'); self.case.admit()
                            self.doc = support_document(self.case, method, 'full_text')
                            self.doc['verifier_invocation_id'] = self.case.verifier['invocation_id']
                            self.doc['extraction']['validation_ref'] = old
                        elif method == 'validated_extraction': ValidatedCases.foreign(self, field)
                        else: OwnCases.foreign(self, field)
                        self.doc['claim']['claim_id'] = 'clm_loadbear1'
                        self.doc['requested_for']['use'] = 'load_bearing'
                        self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = 'full_text'
                    elif field in ('unpinned', 'tier'):
                        self.case.x('DROP TRIGGER source_extractions_immutable_u')
                        column, value = ('extractor_registry_version', None) if field == 'unpinned' else ('supported_tier', 'bibliographic')
                        self.case.x('UPDATE source_extractions SET ' + column + '=?', value)
                    elif field == 'tool': self.doc['extraction']['extractor'] = 'other-tool'
                    else:
                        if method == 'verifier_extraction':
                            self.clone('source_extractions', dict(extraction_id='foreign-basis', extracting_invocation_id=self.case.ACQUIRER,
                                recorded_by_operation_id=self.case.value('SELECT recorded_by_operation_id FROM source_artifacts')))
                            self.doc['extraction']['extraction_id'] = 'foreign-basis'
                        else: self.doc['extraction']['produced_by_invocation_id'] = self.case.verifier['invocation_id']
                    self.store(legacy=True)
                    self.assertEqual(self.case.rows('SELECT * FROM bound_extraction_receipts'), [])
                    self.promote('rejected')

    def test_reference_type(self):
        self.context('verifier_extraction')
        basis = self.doc['extraction']['extraction_id']
        self.clone('source_extractions', dict(extraction_id='123'), "extraction_id='" + basis + "'")
        self.doc['extraction']['extraction_id'] = 123
        self.store(legacy=True)
        self.assertEqual(self.case.rows('SELECT * FROM bound_extraction_receipts'), [])
        self.promote('rejected')

    def test_hash(self):
        self.context('verifier_extraction'); self.store()
        # Isolate the consuming hash binding from earlier INSERT admission.
        immutable = self.case.value("SELECT sql FROM sqlite_schema WHERE name='verification_receipts_immutable_u'")
        self.case.x('DROP TRIGGER verification_receipts_immutable_u')
        receipt = json.loads(self.case.value('SELECT receipt FROM verification_receipts'))
        receipt['obtained_content_hash'] = 'sha256:' + '0' * 64
        self.case.x('UPDATE verification_receipts SET obtained_content_hash=?, receipt=?', receipt['obtained_content_hash'], json.dumps(receipt))
        self.case.x(immutable)
        self.assertEqual(self.case.rows('SELECT * FROM bound_extraction_receipts'), [])
        self.promote('rejected')

    def test_content_ceiling(self):
        for method in METHODS:
            with self.subTest(method=method):
                self.context(method); self.store()
                # Raw relational counterfactual: preserve response size and
                # identity, while isolating consumption from prior admission.
                raw = self.case.value('SELECT response_bytes FROM source_acquisitions')
                body = json.loads(raw)
                body['records'] = [dict(identity='doi:10.1/fixture', abstract='Abstract')]
                self.case.x('DROP TRIGGER source_acquisitions_immutable_u')
                self.case.x('UPDATE source_acquisitions SET response_bytes=?', json.dumps(body).encode().ljust(len(raw)))
                self.assertEqual(self.case.rows('SELECT * FROM bound_extraction_receipts'), [])
                self.promote('rejected')

    def test_v4(self):
        # Sampled adjudicated receipts are legitimate records; V-4 re-reads
        # checks and use. A bound sampled receipt cannot lend authority to an
        # unbound load-bearing declaration at the same claim revision.
        for method in METHODS:
            for field in ('use', 'required', 'access', 'numeric_units', 'denominators', 'negation', 'qualifications', 'tier0'):
                with self.subTest(method=method, field=field):
                    self.context(method)
                    self.doc['requested_for']['use'] = 'sampled'
                    if field not in ('use', 'required', 'access'):
                        self.doc['adjudication'] = dict(adjudication_ref='operator:fixture', resolved_at=self.doc['verified_at'], resolution='supports')
                        if field == 'tier0':
                            self.doc['checks']['tier0'] = dict(checker='minicheck', checker_version='1', signal='alarm')
                        else: self.doc['checks'][field] = 'not_checked'
                    self.store()
                    self.promote('rejected')
                    original_id = self.doc['verification_receipt_id']
                    self.doc['verification_receipt_id'] = 'ver_unbound01'
                    self.doc['requested_for']['use'] = 'load_bearing'
                    self.doc['checks'].pop('tier0', None)
                    for key in ('numeric_units', 'denominators', 'negation', 'qualifications'): self.doc['checks'][key] = 'checked_ok'
                    self.doc['extraction'].pop('extraction_id', None)
                    self.doc['extraction']['validation_ref'] = 'unbound'
                    self.store(legacy=True)
                    # Isolate each consuming predicate from immutable admission
                    # CHECKs. This corruption fixture is not admitted history.
                    self.case.x('PRAGMA ignore_check_constraints=ON')
                    immutable = self.case.value("SELECT sql FROM sqlite_schema WHERE name='verification_receipts_immutable_u'")
                    self.case.x('DROP TRIGGER verification_receipts_immutable_u')
                    receipt = json.loads(self.case.value('SELECT receipt FROM verification_receipts WHERE verification_receipt_id=?', original_id))
                    receipt['requested_for']['use'] = 'load_bearing' if field != 'use' else 'sampled'
                    if field == 'required': receipt['requested_for']['required_access_tier'] = 'abstract'
                    if field == 'access': receipt['access_tier'] = 'abstract'
                    self.case.x('UPDATE verification_receipts SET receipt=?, use=?, required_access_tier=?, access_tier=? WHERE verification_receipt_id=?',
                        json.dumps(receipt), receipt['requested_for']['use'], receipt['requested_for']['required_access_tier'], receipt['access_tier'], original_id)
                    self.case.x(immutable); self.case.x('PRAGMA ignore_check_constraints=OFF')
                    self.promote('rejected')


class BoundPromotionRouterTest(PromotionCases, unittest.TestCase):
    def test_replay_conflict_rollback(self):
        self.context('validated_extraction'); self.store()
        before = self.case.state(exclude=())
        self.case.faults['in_transaction:end'] = RuntimeError('after promotion')
        with self.assertRaisesRegex(RuntimeError, 'after promotion'): self.promote()
        self.assertEqual(self.case.state(exclude=()), before)
        self.case.faults.clear()
        out = self.promote(); env = self.promotion_env
        before = self.case.state(exclude=())
        self.assertEqual(self.case.router.commit_outcome(env), dict(status='replayed', receipt=out['receipt']))
        self.assertEqual(self.case.state(exclude=()), before)
        env = self.case.envelope(self.case.producer, 'op_promote001', empty_outcome(self.case.ACQUIRER, 'interim_transition'))
        self.assertEqual(self.case.router.commit_outcome(env)['reason'], 'operation_id_conflict')
