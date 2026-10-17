"""Final 22 columns: independent inventory and isolated raw predicate pairs.

Trace: C-13; DOSSIER 2d-4b3e1-json2b continuation part 2. All changes below
are in disposable memory, after checked Store adoption. Mirrored fields and
closed semantic domains need explicit exclusions to isolate a single guard.
"""
import json
import sqlite3
import unittest

from gen2.store import db
from gen2.tests import store_fixtures as fx
from gen2.tests.test_store_json_rollout import RolloutPairs

# Independent of the generator/manifest, including every pending column.
COLUMNS = (
    ('capability_facts', 'affected_lanes', 'CapabilityLanesTest', 'capability_facts_supersede_only', 'capability_facts_no_delete'),
    ('claim_source_links', 'spans', 'ClaimSpansTest', 'claim_source_links_immutable_u', 'claim_source_links_no_delete'),
    ('decision_receipts', 'answer', 'DecisionAnswerTest', 'decision_receipts_immutable_u', 'decision_receipts_immutable_d'),
    ('decision_receipts', 'receipt', 'DecisionReceiptTest', 'decision_receipts_immutable_u', 'decision_receipts_immutable_d'),
    ('decision_specs', 'document', 'DecisionSpecTest', 'decision_specs_immutable_u', 'decision_specs_immutable_d'),
    ('export_delivery_receipts', 'receipt', 'DeliveryReceiptTest', 'export_delivery_receipts_immutable_u', 'export_delivery_receipts_no_delete'),
    ('intake_briefs', 'document', 'IntakeBriefTest', 'intake_briefs_content_immutable', 'intake_briefs_no_delete'),
    ('invocation_reconciliations', 'request', 'ReconciliationTest', 'invocation_reconciliations_immutable_u', 'invocation_reconciliations_no_delete'),
    ('obligation_assessments', 'confidence', 'ObligationConfidenceTest', 'obligation_assessments_immutable_u', 'obligation_assessments_immutable_d'),
    ('obligation_assessments', 'evidence_refs', 'ObligationEvidenceTest', 'obligation_assessments_immutable_u', 'obligation_assessments_immutable_d'),
    ('obligations', 'facet_ids', 'ObligationFacetsTest', 'obligations_immutable', 'obligations_no_delete'),
    ('operation_receipts', 'receipt', 'OperationReceiptTest', 'operation_receipts_immutable_u', 'operation_receipts_immutable_d'),
    ('operator_decisions', 'payload', 'OperatorPayloadTest', 'operator_decisions_immutable_u', 'operator_decisions_immutable_d'),
    ('outbox_events', 'expected_connectors', 'OutboxConnectorsTest', 'outbox_events_immutable_u', 'outbox_events_immutable_d'),
    ('outbox_events', 'manifest', 'OutboxManifestTest', 'outbox_events_immutable_u', 'outbox_events_immutable_d'),
    ('questions', 'document', 'QuestionTest', 'questions_immutable_u', 'questions_no_delete'),
    ('registry_dispositions', 'evidence_refs', 'RegistryEvidenceTest', 'registry_dispositions_immutable_u', 'registry_dispositions_immutable_d'),
    ('semantic_assessments', 'evidence_refs', 'SemanticEvidenceTest', 'semantic_assessments_immutable_u', 'semantic_assessments_immutable_d'),
    ('source_lifecycle', 'evidence_refs', 'LifecycleEvidenceTest', 'source_lifecycle_immutable_u', 'source_lifecycle_immutable_d'),
    ('verification_receipts', 'acquisition', 'VerificationAcquisitionTest', 'verification_receipts_immutable_u', 'verification_receipts_immutable_d'),
    ('verification_receipts', 'cited_spans', 'VerificationSpansTest', 'verification_receipts_immutable_u', 'verification_receipts_immutable_d'),
    ('verification_receipts', 'receipt', 'VerificationReceiptTest', 'verification_receipts_immutable_u', 'verification_receipts_immutable_d'),
)
MIRRORS = {('decision_receipts', 'answer'): ('receipt', '$.provider_response.answer'),
    ('outbox_events', 'expected_connectors'): ('manifest', '$.expected_connectors'),
    ('verification_receipts', 'acquisition'): ('receipt', '$.acquisition'),
    ('verification_receipts', 'cited_spans'): ('receipt', '$.cited_spans')}


class CompletionPairs(RolloutPairs):
    def setUp(self):
        super().setUp()  # preserves mutated/reversed target-table triggers
        exclusions = []
        if (self.table, self.column) in MIRRORS:
            mirror, _ = MIRRORS[self.table, self.column]
            exclusions += [f'member_domain_{self.table}_{mirror}_{e}' for e in ('i', 'u')]
        if self.table == 'verification_receipts':
            # SQL 21 redundantly refuses duplicate/unknown names. Isolate SQL 27;
            # unchanged full-schema span tests still enforce shape and numerals.
            exclusions.append('verification_receipts_span_domain_v2')
        if self.table == 'obligations':
            # Facet tags normally admit strings only. Exercise object names in
            # the array without an unrelated facet/document binding masking it.
            exclusions.append('obligations_bound_to_document_and_facets')
        if self.table == 'questions':
            exclusions.append('questions_carried_by_their_bundle')
        before = self.rows("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name=? ORDER BY rowid", self.table)
        for name in exclusions:
            self.x(f'DROP TRIGGER {name}')
        self.assertEqual(self.rows("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name=? ORDER BY rowid", self.table),
            [(name, sql) for name, sql in before if name not in exclusions])
        if self.table == 'intake_briefs':
            self.brief(brief='brief-domain')
            row = self.x("SELECT rowid,* FROM intake_briefs WHERE brief_id='brief-domain'").fetchone()
            self.rowid, self.template = row[0], dict(zip(self.columns, row[1:]))
            self.document = json.loads(self.template[self.column])
        if self.table == 'invocation_reconciliations':
            self.to_unknown(self.template['invocation_id'])
            self.template['unknown_episode'] += 1
        if self.table == 'operator_decisions':
            row = self.x("SELECT rowid,* FROM operator_decisions WHERE kind='rating_approval' LIMIT 1").fetchone()
            self.rowid, self.template = row[0], dict(zip(self.columns, row[1:]))
            self.document = json.loads(self.template[self.column])

    def document_text(self, members, top=False):
        # Preserve the original object/array shape and every bound field.
        probe = '{' + members + '}'
        if isinstance(self.document, list):
            return json.dumps(self.document)[:-1] + (',' if self.document else '') + probe + ']'
        if self.column == 'expected_connectors':
            probe = '{"connector_type":"sql",' + members + '}'
            if top:
                return json.dumps(self.document)[:-1] + ',"name\\u0000suffix":' + probe + '}'
        if top:
            return json.dumps(self.document or {})[:-1] + (',' if self.document else '') + members + '}'
        return json.dumps(self.document or {})[:-1] + (',' if self.document else '') + '"probe":' + probe + '}'

    def good(self):
        return self.document_text('"a":"kept\\u0000value","A":2,"other":[{"a":3},{"a":4}]')

    def duplicates(self, event):
        for members in ('"a":1,"a":2', '"a":1,"\\u0061":2', '"nested":{"a":1,"a":2}'):
            with self.subTest(members=members):
                self.attempt(event, self.good(), True)
                self.attempt(event, self.document_text(members), False)

    def nul(self, event):
        for members, top in (('"name\\u0000suffix":"kept\\u0000value"', True), ('"nested":{"name\\u0000suffix":1}', False)):
            with self.subTest(members=members):
                self.attempt(event, self.good(), True)
                self.attempt(event, self.document_text(members, top=top), False)

    def attempt(self, event, text, accepted):
        self.x('SAVEPOINT completion_pair')
        try:
            row = {**self.template, self.column: text}
            if (self.table, self.column) in MIRRORS:
                mirror, path = MIRRORS[self.table, self.column]
                row[mirror] = self.rows('SELECT json_set(?, ?, json(?))', row[mirror], path, text)[0][0]
            if event == 'i':
                self.x('PRAGMA defer_foreign_keys=ON')
                self.x(f'DELETE FROM {self.table} WHERE rowid=?', self.rowid)
            before = list(self.db.iterdump())
            def write():
                if event == 'i':
                    self.x(f'INSERT INTO {self.table} ({",".join(row)}) VALUES ({",".join("?" for _ in row)})', *row.values())
                else:
                    self.x(f'UPDATE {self.table} SET {",".join(c+"=?" for c in row)} WHERE rowid=?', *row.values(), self.rowid)
            if accepted:
                write()
                matches = [r for r in self.reader.select(self.table) if all(r[c] == v for c, v in row.items() if c not in self.reader._json[self.table])]
                self.assertEqual(len(matches), 1)
                for column in self.reader._json[self.table]:
                    self.assertEqual(matches[0][column], json.loads(row[column]) if row[column] is not None else None)
                self.assertEqual(self.rows('PRAGMA foreign_key_check'), [])
            else:
                self.assertEqual(self.rows('SELECT json_valid(?)', text), [(1,)])
                with self.assertRaises(sqlite3.IntegrityError) as caught:
                    write()
                self.assertIn('JSON member domain:', str(caught.exception))
                self.assertEqual(list(self.db.iterdump()), before)
        finally:
            self.x('ROLLBACK TO completion_pair')
            self.x('RELEASE completion_pair')


for table, column, cls, update, delete in COLUMNS:
    globals()[cls] = type(cls, (CompletionPairs, fx.StoreTestCase),
        {'table': table, 'column': column, 'removed': (update, delete), '__module__': __name__})


class CoverageTest(unittest.TestCase):
    def test_complete_inventory(self):
        manifest = json.loads((db.SCHEMA_DIR.parents[2] / 'tools/gen2_json_member_domain.json').read_text())
        self.assertEqual(manifest['pending'], {})
        final = {table + '.' + column for table, column, *_ in COLUMNS}
        self.assertEqual(len(final), 22)
        self.assertEqual(set(manifest['covered']), final | {
            'detailed_check_records.assessment', 'detailed_check_records.evidence_ref',
            'extraction_validations.comparison_evidence_ref', 'extraction_validations_v2.comparison_evidence_ref', 'quote_checks.match_result',
            'search_observations.continuation', 'search_observations.obligation_ids', 'search_observations.request', 'source_extractions.output_ref',
            'amendment_impacts.document', 'audit_events.detail', 'config_bundles.document', 'contract_revisions.document',
            'invocation_transitions.facts', 'scoping_reports.document', 'screening_assessments.criterion_results', 'source_proposals.document'})
        with sqlite3.connect(':memory:') as conn:
            conn.executescript(db.schema_text())
            installed = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE name GLOB 'member_domain_*'")}
        self.assertEqual(installed, {f'member_domain_{name.replace(".", "_")}_{event}' for name in manifest['covered'] for event in ('i', 'u')})
