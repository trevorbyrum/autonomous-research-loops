"""Current receipt admission: attributed records, never self-declared authority."""
import copy
import unittest
from unittest.mock import patch

from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests import test_detailed_check_receipts as references
from gen2.tests.ddl_fixtures import TRIGGERS, restore_triggers
from gen2.tests.detailed_receipt_fixtures import OUTCOME, attach_checks, seed_checks, historical_receipt, historical_admission
from gen2.tests.test_pending_extraction_support import load_claim
from gen2.tests.test_store_fixture_order import reverse_triggers


class MandatoryCases:
    RAW = False

    def opened(self):
        from gen2.tests import test_store_detailed_check_receipts as raw
        case = (raw.ReferenceDDLTest if self.RAW else references.ReferenceRouterTest)('test_control')
        case.setUp()
        self.addCleanup(case.tearDown)
        restore_triggers(case, db.schema_text())
        load_claim(case, 'abstract')
        case.doc['claim']['claim_id'] = 'clm_loadbear1'
        case.doc['requested_for']['use'] = 'load_bearing'
        seed_checks(case, case.doc)
        # Router must independently refuse even with both SQL consumer guards absent.
        restore_triggers(case, sf.DDL_TEXT, omit=() if self.RAW else (
            'verification_receipts_require_detailed_checks', 'verification_receipts_detailed_binding'))
        return case

    def refused(self, case, detail=None):
        before = case.state()
        out = case.submit()
        self.assertEqual(out['status'], 'rejected', out)
        if detail: self.assertIn(detail, out['detail'])
        self.assertEqual(case.state(), before)

    def test_control(self):
        case = self.opened()
        self.assertEqual(case.submit()['status'], 'committed')
        self.assertEqual(case.store.select('verification_receipts')[0]['receipt'], case.doc)
        self.assertEqual(case.rows('PRAGMA foreign_key_check'), [])

    def test_missing(self):
        case = self.opened()
        original = copy.deepcopy(case.doc)
        for verdict in ('supports', 'partially_supports'):
            for kind in references.KINDS:
                with self.subTest(verdict=verdict, kind=kind):
                    case.doc = copy.deepcopy(original)
                    case.doc['verdict'] = verdict
                    del case.doc['detailed_checks'][kind]['record_id']
                    self.refused(case, 'requires detailed check records')

    def test_legacy(self):
        case = self.opened()
        case.doc['receipt_version'] = 'verification-receipt/1'
        del case.doc['detailed_checks']
        for verdict in ('supports', 'partially_supports'):
            case.doc['verdict'] = verdict
            self.refused(case, 'requires detailed check records')

    def test_bindings(self):
        case = self.opened()
        original = copy.deepcopy(case.doc)
        for kind in references.KINDS:
            with self.subTest(kind=kind):
                # All other references match; only this reference names the
                # independently admitted record for the other claim revision.
                case.doc = copy.deepcopy(original)
                case.doc['detailed_checks'][kind]['record_id'] = kind
                self.refused(case, 'receipt detailed check binding')
                case.doc = copy.deepcopy(original)
                case.doc['detailed_checks'][kind]['record_id'] = 'absent'
                self.refused(case, 'receipt detailed check binding')

    def test_outcomes(self):
        case = self.opened()
        original = copy.deepcopy(case.doc)
        for kind in references.KINDS:
            for summary, outcome in OUTCOME.items():
                with self.subTest(kind=kind, outcome=outcome):
                    case.doc = copy.deepcopy(original)
                    case.doc['checks'][kind] = summary
                    case.doc['verification_receipt_id'] = 'ver_' + kind + '_' + outcome
                    if outcome == 'failed':
                        case.doc['adjudication'] = dict(adjudication_ref='adj-performed',
                            resolved_at=case.doc['verified_at'], resolution='Explicit fixture resolution after re-reading.')
                    attach_checks(case, case.doc)
                    if outcome in ('not_checked', 'unavailable'):
                        for verdict in ('supports', 'partially_supports'):
                            case.doc['verdict'] = verdict
                            self.refused(case)
                        case.doc['verdict'] = 'does_not_support'
                    self.assertEqual(case.submit()['status'], 'committed', case.doc)
                    self.assertEqual(case.store.select('verification_receipts',
                        {'verification_receipt_id': case.doc['verification_receipt_id']})[0]['receipt'], case.doc)

    def test_failed_without_record(self):
        case = self.opened()
        for kind in references.KINDS:
            case.doc['checks'][kind] = 'checked_problem'
        attach_checks(case, case.doc)
        case.doc['adjudication'] = dict(adjudication_ref='adj-unperformed',
            resolved_at=case.doc['verified_at'], resolution='An adjudication cannot perform absent checks.')
        self.missing_entries(case)

    def test_exemption_without_record(self):
        case = self.opened()
        for kind in references.KINDS:
            case.doc['checks'][kind] = 'not_applicable'
        attach_checks(case, case.doc)
        self.missing_entries(case)

    def test_historical_isolation_restores_current_policy_and_catalog(self):
        for reverse in (False, True):
            ddl = reverse_triggers(sf.DDL_TEXT) if reverse else sf.DDL_TEXT
            ddl = ddl.replace('d.topic_id = NEW.topic_id', '1 = 1')
            ddl += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
            with self.subTest(reverse=reverse), patch.object(sf, 'DDL_TEXT', ddl):
                case = self.opened()
                restore_triggers(case, ddl)
                case.x("CREATE TRIGGER legacy_sentinel BEFORE INSERT ON verification_receipts "
                    "WHEN NEW.verification_receipt_id='ver_sentinel' BEGIN SELECT RAISE(ABORT,'legacy sentinel'); END")
                catalog = case.rows(TRIGGERS)
                historical_receipt(case.doc)
                with historical_admission(case):
                    self.assertNotIn('verification_receipts_require_detailed_checks', dict(case.rows(TRIGGERS)))
                    self.assertEqual(case.submit()['status'], 'committed')
                    case.doc['verification_receipt_id'] = 'ver_sentinel'
                    self.refused(case, 'legacy sentinel')
                self.assertEqual(case.rows(TRIGGERS), catalog)
                retained = case.store.select('verification_receipts')[0]['receipt']
                self.assertEqual(retained['receipt_version'], 'verification-receipt/1')
                with self.assertRaisesRegex(RuntimeError, 'historical rollback'):
                    with historical_admission(case):
                        raise RuntimeError('historical rollback')
                self.assertEqual(case.rows(TRIGGERS), catalog)
                case.doc['verification_receipt_id'] = 'ver_current001'
                self.refused(case, 'requires detailed check records')

    def missing_entries(self, case):
        for kind in references.KINDS:
            entry = case.doc['detailed_checks'][kind]
            identity = entry.pop('record_id')
            self.refused(case, 'requires detailed check records')
            entry['record_id'] = identity


class MandatoryRouterTest(MandatoryCases, unittest.TestCase):
    def test_replay_conflict_rollback(self):
        case = self.opened()
        before = case.state(exclude=())
        case.faults['in_transaction:end'] = RuntimeError('mandatory rollback')
        with self.assertRaisesRegex(RuntimeError, 'mandatory rollback'):
            case.submit()
        self.assertEqual(case.state(exclude=()), before)
        case.faults.clear()
        self.assertEqual(case.submit()['status'], 'committed')
        before = case.state(exclude=())
        self.assertEqual(case.router.commit_outcome(case.env)['status'], 'replayed')
        self.assertEqual(case.state(exclude=()), before)
        del case.doc['detailed_checks']['negation']['record_id']
        self.assertEqual(case.submit()['reason'], 'operation_id_conflict')


class MandatoryLoaderTest(unittest.TestCase):
    def test_boundary_reload_covers_collaborator_refusal_imports(self):
        import ast
        from gen2.tests.test_mutation_verdict import harness
        runner = harness()
        importers = set()
        for path in (runner.ROOT / 'gen2/router').glob('*.py'):
            binds_refusal = any(isinstance(n, ast.ImportFrom) and n.module == 'gen2.router.boundary'
                and any(a.name == 'Refusal' for a in n.names) for n in ast.walk(ast.parse(path.read_text())))
            if binds_refusal:
                importers.add('gen2.router.' + path.stem)
        for target, how in runner.FILE_TARGETS.items():
            if how[0] == 'module' and 'gen2.router.boundary' in how[1:]:
                with self.subTest(target=target):
                    self.assertFalse(importers - set(how[how.index('gen2.router.boundary') + 1:]))

    def test_warm_boundary_reload_keeps_typed_refusals(self):
        import importlib
        import sys
        from gen2.tests.test_mutation_verdict import harness
        runner = harness()
        importlib.import_module('gen2.router.detailed_checks')  # Warm its Refusal alias.
        for target in ('gen2/router/boundary.py', 'gen2/core/canonical.py', 'gen2/core/pagination.py'):
            with self.subTest(target=target):
                marker = (runner.ROOT / target).read_text().splitlines()[0]
                probe = runner.Mutation('warm-boundary', '2d-4c part 4a', 'identity reload',
                    ('test_mandatory_detailed_receipts.MandatoryRouterTest.test_missing',), target=target,
                    old=marker, new=marker)
                with patch.object(sys, 'path', [str(runner.TESTS), *sys.path]), patch.object(runner, '_CONTROLS', {}):
                    result = runner._run_file_mutation(probe)
                self.assertFalse(result.errored, result.errored_detail)
                self.assertFalse(result.failed)
                self.assertEqual(result.testsRun, 1)
