"""Raw consumption rechecks historical operands under the complete subject DDL."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests.ddl_fixtures import TRIGGERS, restore_triggers
from gen2.tests.detailed_support_fixtures import history, subject_views, prior_consumption
from gen2.tests.detailed_receipt_fixtures import seed_checks, attach_checks, historical_receipt
from gen2.tests.test_detailed_check_receipts import KINDS, ReferenceCases
from gen2.tests.test_receipt_summary_domain import SummaryCases, METHODS
from gen2.tests import test_store_capture_support as capture
from gen2.tests.test_store_fixture_order import reverse_triggers


class DetailedSupportDDLTest(unittest.TestCase):
    RAW = True
    def opened(self, method='canonical_bytes', reverse=False, *, seed=False, distinct=False):
        ddl = reverse_triggers(sf.DDL_TEXT) if reverse else sf.DDL_TEXT
        with patch.object(sf, 'DDL_TEXT', db.schema_text()):
            case = SummaryCases.opened(self, method)
            if distinct:
                case.record = ReferenceCases.record.__get__(case)
                ReferenceCases.distinct_validated(case)
                case.doc['checks'].update({k: 'checked_ok' for k in KINDS})
                case.doc['detailed_checks'] = {k: dict(outcome='succeeded', record_id='target-' + k) for k in KINDS}
                case.doc['receipt_version'] = 'verification-receipt/2'
            elif seed:
                seed_checks(case, case.doc)
        subject_views(case, ddl)
        return case

    def test_historical_claims(self):
        # Exact six repair-1 operands: sole adjudicated /1, invented summaries,
        # no records; all admission omissions end before ordinary promotion.
        for reverse in (False, True):
            for method in METHODS:
                with self.subTest(reverse=reverse, method=method):
                    case = self.opened(method, reverse)
                    case.doc['adjudication'] = dict(adjudication_ref='adj-history',
                        resolved_at=case.doc['verified_at'], resolution='Explicit old-domain fixture.')
                    for kind in KINDS:
                        case.doc['checks'][kind] = 'invented'
                    with history(case):
                        self.assertEqual(ReferenceCases.submit(case)['status'], 'committed')
                    self.assertEqual(case.value('SELECT count(*) FROM detailed_check_records'), 0)
                    self.assertEqual(case.value('SELECT count(*) FROM verification_receipts'), 1)
                    self.promotion(case, False)
                    self.doCleanups()

    def promotion(self, case, accepted):
        before = case.state(exclude=())
        if accepted:
            case.x("UPDATE claims SET status='accepted_support' WHERE claim_id='clm_loadbear1'")
            self.assertEqual(case.value("SELECT status FROM claims WHERE claim_id='clm_loadbear1'"), 'accepted_support')
        else:
            with self.assertRaises(sqlite3.IntegrityError):
                case.x("UPDATE claims SET status='accepted_support' WHERE claim_id='clm_loadbear1'")
            self.assertEqual(case.state(exclude=()), before)
        self.assertEqual(case.rows('PRAGMA foreign_key_check'), [])

    def test_promotion_control(self):
        for reverse in (False, True):
            for method in METHODS:
                case = self.opened(method, reverse, seed=True)
                for summary in ('checked_ok', 'checked_problem', 'not_applicable'):
                    with self.subTest(method=method, summary=summary, reverse=reverse):
                        for kind in KINDS:
                            case.doc['checks'][kind] = summary
                        attach_checks(case, case.doc)
                        if method == 'canonical_bytes' and summary == 'checked_problem':
                            case.doc['checks']['tier0'] = dict(checker='fixture', checker_version='1', signal='alarm')
                        else:
                            case.doc['checks'].pop('tier0', None)
                        case.doc['adjudication'] = dict(adjudication_ref='adj-control',
                            resolved_at=case.doc['verified_at'], resolution='Explicit performed assessment.')
                        case.x('SAVEPOINT control')
                        self.assertEqual(ReferenceCases.submit(case)['status'], 'committed')
                        self.promotion(case, True)
                        case.x('ROLLBACK TO control'); case.x('RELEASE control')
                self.doCleanups()

    def test_bindings(self):
        for reverse in (False, True):
            for method in METHODS:
                case = self.opened(method, reverse, seed=True, distinct=method == 'validated_extraction')
                self.assertEqual(ReferenceCases.submit(case)['status'], 'committed')
                self.assertEqual(case.rows('SELECT * FROM detailed_support_receipts'), [(case.doc['verification_receipt_id'],)])
                for kind in KINDS:
                    rid = case.doc['detailed_checks'][kind]['record_id']
                    fields = dict(kind='foreign', outcome='failed', claim_id='clm_foreign01', claim_revision=2,
                        cited_spans=[*case.doc['cited_spans'], case.doc['cited_spans'][0]], work_id='wrk_foreign01',
                        source_version='v2', source_artifact_hash='sha256:' + '0' * 64,
                        **{'examined_artifact_ref.content_hash': 'sha256:' + '1' * 64})
                    for field, value in fields.items():
                        with self.subTest(method=method, kind=kind, field=field, reverse=reverse):
                            case.x('SAVEPOINT binding')
                            with history(case):
                                case.x('UPDATE detailed_check_records SET assessment=json_set(assessment,?,json(?)) WHERE check_id=?',
                                    '$.' + field, json.dumps(value), rid)
                            self.assertEqual(case.rows('SELECT * FROM detailed_support_receipts'), [])
                            self.promotion(case, False)
                            case.x('ROLLBACK TO binding'); case.x('RELEASE binding')
                    for column, value in (('performer_invocation_id', case.producer['invocation_id']),
                            ('topic_id', sf.OTHER)):
                        case.x('SAVEPOINT lineage')
                        with history(case):
                            case.x('UPDATE detailed_check_records SET ' + column + '=? WHERE check_id=?', value, rid)
                        self.assertEqual(case.rows('SELECT * FROM detailed_support_receipts'), [])
                        self.promotion(case, False)
                        case.x('ROLLBACK TO lineage'); case.x('RELEASE lineage')
                self.doCleanups()

    def test_missing_and_unperformed(self):
        for method in METHODS:
            case = self.opened(method, seed=True)
            for kind in KINDS:
                for outcome in ('missing', 'not_checked', 'unavailable', 'projection', 'outcome'):
                    with self.subTest(method=method, kind=kind, outcome=outcome):
                        doc = copy.deepcopy(case.doc)
                        entry = doc['detailed_checks'][kind]
                        if outcome == 'missing': entry.pop('record_id')
                        elif outcome == 'projection': doc['checks'][kind] = 'invented'
                        elif outcome == 'outcome': entry['outcome'] = 'failed'
                        else:
                            entry['outcome'] = outcome
                            doc['checks'][kind] = outcome
                        doc['adjudication'] = dict(adjudication_ref='adj-unperformed',
                            resolved_at=doc['verified_at'], resolution='Cannot waive absent performance.')
                        case.x('SAVEPOINT absent')
                        original, case.doc = case.doc, doc
                        try:
                            with history(case, unchecked=True):
                                if outcome in ('not_checked', 'unavailable'):
                                    case.x("UPDATE detailed_check_records SET assessment=json_set(assessment,'$.outcome',?) WHERE check_id=?",
                                        outcome, entry['record_id'])
                                self.assertEqual(ReferenceCases.submit(case)['status'], 'committed')
                            self.assertEqual(case.rows('SELECT * FROM detailed_support_receipts'), [])
                            self.promotion(case, False)
                        finally:
                            case.x('ROLLBACK TO absent'); case.x('RELEASE absent')
                            case.doc = original
            self.doCleanups()

    def test_canonical_basis(self):
        case = self.opened(seed=True)
        original = copy.deepcopy(case.doc)
        for field in ('gateway_call_ref', 'retrieved_at', 'route', 'content'):
            case.x('SAVEPOINT acquisition')
            try:
                with history(case):
                    if field == 'content':
                        raw = case.value('SELECT response_bytes FROM source_acquisitions')
                        body = json.loads(raw)
                        body['records'][0].pop('abstract', None)
                        case.x('UPDATE source_acquisitions SET response_bytes=?', json.dumps(body).encode().ljust(len(raw)))
                    else:
                        case.doc = copy.deepcopy(original)
                        case.doc['acquisition'][field] = 'foreign-acquisition'
                    self.assertEqual(ReferenceCases.submit(case)['status'], 'committed')
                self.assertEqual(case.rows('SELECT * FROM detailed_support_receipts'), [])
                self.promotion(case, False)
            finally:
                case.doc = original
                case.x('ROLLBACK TO acquisition'); case.x('RELEASE acquisition')

    def test_shapes(self):
        case = self.opened(seed=True)
        for shape in ('legacy', 'empty', 'null', 'partial', 'extra'):
            with self.subTest(shape=shape):
                doc = copy.deepcopy(case.doc)
                if shape == 'legacy': doc['receipt_version'] = 'verification-receipt/1'
                elif shape == 'empty': doc['detailed_checks'] = {}
                elif shape == 'null': doc['detailed_checks'] = None
                elif shape == 'partial': doc['detailed_checks'].pop('qualifications')
                else: doc['detailed_checks']['foreign'] = dict(outcome='succeeded')
                original, case.doc = case.doc, doc
                case.x('SAVEPOINT shape')
                try:
                    with history(case):
                        self.assertEqual(ReferenceCases.submit(case)['status'], 'committed')
                    self.assertEqual(case.rows('SELECT * FROM detailed_support_receipts'), [])
                    self.promotion(case, False)
                finally:
                    case.x('ROLLBACK TO shape'); case.x('RELEASE shape')
                    case.doc = original

    def test_history_catalog(self):
        for reverse in (False, True):
            case = self.opened(reverse=reverse)
            case.x('DROP TRIGGER verification_receipts_detailed_domain')
            sql = case.value("SELECT sql FROM sqlite_schema WHERE name='verification_receipts_detailed_binding'")
            case.x('DROP TRIGGER verification_receipts_detailed_binding')
            case.x(sql.replace('d.topic_id = NEW.topic_id', '1 = 1'))
            catalog = case.rows(TRIGGERS)
            view = case.value("SELECT sql FROM sqlite_schema WHERE name='detailed_support_receipts'")
            for checks in (0, 1):
                case.x('PRAGMA ignore_check_constraints=' + str(checks))
                for exceptional in (False, True):
                    try:
                        with history(case, unchecked=True):
                            self.assertEqual(case.value('PRAGMA ignore_check_constraints'), 1)
                            if exceptional: raise RuntimeError('history exit')
                    except RuntimeError:
                        self.assertTrue(exceptional)
                    self.assertEqual(case.value('PRAGMA ignore_check_constraints'), checks)
                    self.assertEqual(case.rows(TRIGGERS), catalog)
            case.x('PRAGMA ignore_check_constraints=OFF')
            for exceptional in (False, True):
                try:
                    with prior_consumption(case):
                        if exceptional: raise RuntimeError('history exit')
                except RuntimeError:
                    self.assertTrue(exceptional)
                self.assertEqual(case.rows(TRIGGERS), catalog)
                self.assertEqual(case.value("SELECT sql FROM sqlite_schema WHERE name='detailed_support_receipts'"), view)

    def test_non_pooling(self):
        for method in METHODS[1:]:
            case = self.opened(method, seed=True)
            for i in (0, 1):
                doc = copy.deepcopy(case.doc)
                doc['verification_receipt_id'] += str(i)
                if i == 0: doc['extraction']['extractor'] = 'foreign-tool'
                else: doc['detailed_checks']['negation'].pop('record_id')
                original, case.doc = case.doc, doc
                with history(case):
                    self.assertEqual(ReferenceCases.submit(case)['status'], 'committed')
                case.doc = original
            self.assertEqual(case.rows('SELECT * FROM detailed_support_receipts'), [(case.doc['verification_receipt_id'] + '0',)])
            self.assertEqual(case.rows('SELECT * FROM bound_extraction_receipts'), [(case.doc['verification_receipt_id'] + '1',)])
            self.promotion(case, False)
            self.doCleanups()


class DetailedCaptureDDLTest(unittest.TestCase):
    def opened(self, reverse):
        with patch.object(sf, 'DDL_TEXT', db.schema_text()):
            case = capture.CaptureDDLTest(); case.setUp()
        self.addCleanup(case.tearDown)
        subject_views(case, reverse_triggers(sf.DDL_TEXT) if reverse else sf.DDL_TEXT)
        catalog = case.rows(TRIGGERS)
        with history(case):
            case.x('DELETE FROM verification_receipts')
        case.raw()
        checks = {k: 'invented' for k in KINDS}
        checks['exact_quote'] = dict(status='matched', normalization_version='quote-nfc-safe/2+ucd15.0.0',
            source_artifact_hash=case.source_hash)
        with history(case):
            case.bound(historical=True, checks=checks, adjudication=dict(adjudication_ref='adj-capture-history',
                resolved_at=sf.T, resolution='Explicit history operand.'))
        self.assertEqual(case.rows(TRIGGERS), catalog)
        self.assertEqual(case.rows('SELECT count(*) FROM verification_receipts'), [(1,)])
        return case

    def test_historical_capture(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                case = self.opened(reverse)
                # Isolate SQL 12 from SQL 03/34 for this capture-promotion assertion.
                catalog = case.rows(TRIGGERS)
                case.x('DROP TRIGGER IF EXISTS claims_accepted_support_detailed_receipt')
                case.refused(case.promote)
                restore_triggers(case, None, catalog=catalog)
                self.doCleanups()

    def test_historical_refence(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                case = self.opened(reverse)
                # Install accepted history explicitly; the subject is the existing
                # operation-scoped final refence, not activation or store opening.
                with history(case):
                    case.promote()
                before = case.snapshot()
                case.x('SAVEPOINT refence'); case.finish()
                self.assertEqual(case.rows('SELECT status FROM claims'), [('quarantined',)])
                case.x('ROLLBACK TO refence'); case.x('RELEASE refence')
                self.assertEqual(case.snapshot(), before)
                self.doCleanups()

    def test_capture_tiers(self):
        case = self.opened(False)
        with history(case):
            case.x('DELETE FROM verification_receipts')
        case.bound()
        for field in ('required_access_tier', 'access_tier'):
            case.x('SAVEPOINT tier')
            try:
                doc = json.loads(case.rows('SELECT receipt FROM verification_receipts')[0][0])
                if field == 'required_access_tier': doc['requested_for'][field] = 'bibliographic'
                else: doc[field] = 'bibliographic'
                with history(case, unchecked=True):
                    case.x('UPDATE verification_receipts SET ' + field + '=?,receipt=?', 'bibliographic', json.dumps(doc))
                self.assertEqual(case.rows('SELECT * FROM governed_captures_blocked'), [('clm_00000001', 1)])
                case.refused(case.promote)
            finally:
                case.x('ROLLBACK TO tier'); case.x('RELEASE tier')

    def test_capture_control(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                case = self.opened(reverse)
                with history(case):
                    case.x('DELETE FROM verification_receipts')
                case.bound(); case.promote(); case.finish()
                self.assertEqual(case.rows('SELECT status FROM claims'), [('accepted_support',)])
                self.assertEqual(case.rows('PRAGMA foreign_key_check'), [])
                self.doCleanups()
