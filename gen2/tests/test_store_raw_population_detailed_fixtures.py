"""Final population and capture consumers retain real attributed assessments."""
import copy
import importlib
import json
import sqlite3
import unittest
from unittest.mock import patch

from gen2.core import canonical
from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests import raw_population_fixtures as population
from gen2.tests import test_store_governed_quotes as quote
from gen2.tests import test_store_capture_support as capture
from gen2.tests import test_quote_attention as attention
from gen2.tests import test_store_ddl_evidence as evidence
from gen2.tests import test_store_detailed_receipt_fixtures as converted
from gen2.tests import test_store_json_rollout as rollout
from gen2.tests import test_store_json_completion as completion
from gen2.tests.ddl_fixtures import TRIGGERS
from gen2.tests.test_store_fixture_order import reverse_triggers


class RawPopulationFixtureTest(unittest.TestCase):
    check_receipt = converted.ConvertedFixtureTest.check_receipt

    def opened(self, owner, method='runTest'):
        case = owner(method)
        case.setUp()
        self.addCleanup(case.tearDown)
        return case

    def retained(self, case):
        docs = [json.loads(r[0]) for r in case.rows('SELECT receipt FROM verification_receipts')]
        self.assertTrue(docs)
        for doc in docs:
            self.assertEqual(doc["receipt_version"], "verification-receipt/2")
            self.assertTrue(all("record_id" in entry for entry in doc["detailed_checks"].values()))
            self.check_receipt(case.population_assessments, doc, case.population_assessments.source)
        return docs

    def test_every_population_consumer_including_all_thirty_generated_owners(self):
        owners = [('test_store_history', n) for n in ('EveryTableSweepTest', 'RecordIdentityTest')]
        owners += [(m, n) for m, n in (
            ('test_branch_windows', 'DDLTest'), ('test_obligation_admission', 'DDLTest'),
            ('test_registry_dispositions', 'RegistryDDLTest'), ('test_semantic_assessments', 'SemanticDDLTest'),
            ('test_source_lifecycle', 'LifecycleDDLTest'), ('test_store_source_artifacts', 'DDLTest'),
            ('test_store_json_member_domain', 'QuoteTest'), ('test_store_span_cap', 'AuxiliaryCapTest'))]
        owners += [(m.__name__.split('.')[-1], row[2]) for m in (rollout, completion) for row in m.COLUMNS]
        self.assertEqual(len(owners), 40)
        for module, name in owners:
            with self.subTest(module=module, owner=name):
                case = self.opened(getattr(importlib.import_module('gen2.tests.' + module), name))
                self.retained(case)
                self.assertEqual(case.rows('SELECT count(*) FROM detailed_check_records'), [(12,)])
                self.assertEqual(case.rows("SELECT status FROM claims WHERE revision=1"), [('accepted_support',)])
                self.assertEqual(case.rows('SELECT response_bytes FROM source_acquisitions'), [(population.SOURCE_BYTES,)])

    def test_original_quote_capture_and_adjudication_positive_paths(self):
        for owner, methods in ((quote.DDLTest, ('test_control',)),
                (capture.CaptureDDLTest, ('test_capture_control', 'test_non_quote_control', 'test_recapture',
                    'test_multi_control', 'test_late_valid_control', 'test_late_multi_control')),
                (attention.AdjudicationDDLTest, ('test_capture_control', 'test_nli_control'))):
            for method in methods:
                with self.subTest(owner=owner.__name__, method=method):
                    case = self.opened(owner, method)
                    getattr(case, method)()
                    docs = self.retained(case)
                    sets = {canonical.logical_hash([d['claim'], d['cited_spans']]):
                        {e['record_id'] for e in d['detailed_checks'].values()} for d in docs}
                    self.assertEqual(sum(map(len, sets.values())), len(set.union(*sets.values())))

    def test_causal_verifier_and_adopted_revisions_keep_independent_records(self):
        for owner, method in ((evidence.VerificationTest, 'test_verifier_must_be_separate_verification_invocation'),
                (evidence.ContractAdmittedSupportTest, 'test_adopted_pre_contract_claim_with_a_receipt_is_allowed')):
            with self.subTest(owner=owner.__name__):
                case = self.opened(owner, method)
                getattr(case, method)()
                docs = self.retained(case)
                groups = {}
                for row in case.population_assessments.store.select('detailed_check_records'):
                    report = row['assessment']
                    key = (row['performer_invocation_id'], report['claim_id'], report['claim_revision'])
                    groups.setdefault(key, set()).add(row['check_id'])
                self.assertEqual(len(groups), 2 if owner is evidence.VerificationTest else 3)
                self.assertTrue(all(len(ids) == 12 for ids in groups.values()))
                self.assertEqual(sum(map(len, groups.values())), len(set.union(*groups.values())))
                if owner is evidence.VerificationTest:
                    self.assertEqual(docs[0]['verifier_invocation_id'], 'inv_reqdver1')

    def test_all_kinds_outcomes_and_methods_preserve_catalog_conflict_and_rollback(self):
        case = self.opened(evidence.VerificationTest)
        case.recorded_verification_basis()
        before = population.snapshot(case.db)
        for method in ('canonical_bytes', 'verifier_extraction', 'validated_extraction'):
            for kind in case.CHECKS_OK:
                for status in ('checked_ok', 'checked_problem', 'not_applicable'):
                    with self.subTest(method=method, kind=kind, status=status):
                        case.x('SAVEPOINT receipt')
                        try:
                            changes = dict(method=method, extraction='inv_vvvvvvvv' if method == 'verifier_extraction' else 'inv_pppppppp',
                                verdict='partially_supports', checks=dict(case.CHECKS_OK, **{kind: status}))
                            case.verify('ver_retained1', **changes)
                            self.retained(case)
                            with self.assertRaisesRegex(sqlite3.IntegrityError, 'UNIQUE constraint'):
                                case.verify('ver_retained1', **changes)
                        finally:
                            case.x('ROLLBACK TO receipt'); case.x('RELEASE receipt')
                        self.assertEqual(population.snapshot(case.db), before)

    def test_foreign_span_refuses_atomically_then_matching_promotes(self):
        case = self.opened(capture.CaptureDDLTest)
        case.raw(); case.bound()
        cursor = case.x("SELECT * FROM verification_receipts WHERE verification_receipt_id='ver_bound00001'")
        row = dict(zip([d[0] for d in cursor.description], cursor.fetchone()))
        doc = json.loads(row['receipt']); bad = copy.deepcopy(doc)
        bad['verification_receipt_id'] = 'ver_foreign1'
        foreign = copy.deepcopy(doc)
        foreign['cited_spans'].append(dict(start=5, end=10, locator=dict(kind='page', value='3')))
        population.attach_checks(case.population_assessments, foreign)
        bad['detailed_checks'] = foreign['detailed_checks']
        self.assertNotEqual(bad['detailed_checks'], doc['detailed_checks'])
        row.update(verification_receipt_id=bad['verification_receipt_id'], receipt=canonical.canonical_bytes(bad).decode(),
            cited_spans=canonical.canonical_bytes(bad['cited_spans']).decode())
        before = population.snapshot(case.db)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt detailed check binding'):
            case.x(f"INSERT INTO verification_receipts ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", *row.values())
        self.assertEqual(population.snapshot(case.db), before)
        case.promote(); self.retained(case)
        self.assertEqual(case.rows('SELECT status FROM claims'), [('accepted_support',)])

    def test_full_admission_preserves_requested_tables_views_triggers_and_local_drops(self):
        requested = reverse_triggers(sf.DDL_TEXT).replace('d.topic_id = NEW.topic_id', '1 = 1')
        requested = requested.replace('ELSE 1 END AS recorded_tier_rank', 'ELSE (0 + 1) END AS recorded_tier_rank')
        requested = requested.replace('verification_receipt_id TEXT PRIMARY KEY CHECK (',
            "verification_receipt_id TEXT PRIMARY KEY CHECK (verification_receipt_id != 'ver_blocked1') CHECK (")
        requested += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
        query = "SELECT type,name,sql FROM sqlite_schema WHERE type IN ('table','view','trigger') ORDER BY type,rowid"
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(requested); expected = list(reference.execute(query))
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(db.schema_text()); full = list(reference.execute(query))
        seed = population.seed_checks; seen = []
        def observe(bridge, doc):
            self.assertEqual(bridge.rows(query), full)
            self.assertEqual([bridge.rows('PRAGMA '+name)[0][0] for name in
                ('foreign_keys', 'recursive_triggers', 'ignore_check_constraints')], [1, 1, 0])
            seen.append(doc['claim'])
            return seed(bridge, doc)
        with patch.object(sf, 'DDL_TEXT', requested), patch.object(population, 'seed_checks', observe):
            case = self.opened(capture.CaptureDDLTest)
            self.assertEqual(case.rows(query), expected)
            case.x('DROP TRIGGER verification_receipts_capture_binding')
            local = case.rows(TRIGGERS)
            population.prepare(case)  # already seeded; preserve subject-local omission too
            self.assertEqual(case.rows(TRIGGERS), local)
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'CHECK constraint'):
                case.canonical_verify('ver_blocked1', quote=('not_applicable', None))
            self.retained(case)
        self.assertEqual(len(seen), 2)
