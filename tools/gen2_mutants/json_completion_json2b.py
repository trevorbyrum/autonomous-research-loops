"""Separately paired duplicate/NUL predicates for every SQL 27 event guard."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}

for table, column, cls in (
        ('capability_facts', 'affected_lanes', 'CapabilityLanesTest'),
        ('claim_source_links', 'spans', 'ClaimSpansTest'),
        ('decision_receipts', 'answer', 'DecisionAnswerTest'),
        ('decision_receipts', 'receipt', 'DecisionReceiptTest'),
        ('decision_specs', 'document', 'DecisionSpecTest'),
        ('export_delivery_receipts', 'receipt', 'DeliveryReceiptTest'),
        ('intake_briefs', 'document', 'IntakeBriefTest'),
        ('invocation_reconciliations', 'request', 'ReconciliationTest'),
        ('obligation_assessments', 'confidence', 'ObligationConfidenceTest'),
        ('obligation_assessments', 'evidence_refs', 'ObligationEvidenceTest'),
        ('obligations', 'facet_ids', 'ObligationFacetsTest'),
        ('operation_receipts', 'receipt', 'OperationReceiptTest'),
        ('operator_decisions', 'payload', 'OperatorPayloadTest'),
        ('outbox_events', 'expected_connectors', 'OutboxConnectorsTest'),
        ('outbox_events', 'manifest', 'OutboxManifestTest'),
        ('questions', 'document', 'QuestionTest'),
        ('registry_dispositions', 'evidence_refs', 'RegistryEvidenceTest'),
        ('semantic_assessments', 'evidence_refs', 'SemanticEvidenceTest'),
        ('source_lifecycle', 'evidence_refs', 'LifecycleEvidenceTest'),
        ('verification_receipts', 'acquisition', 'VerificationAcquisitionTest'),
        ('verification_receipts', 'cited_spans', 'VerificationSpansTest'),
        ('verification_receipts', 'receipt', 'VerificationReceiptTest')):
    for event in ('i', 'u'):
        test = 'test_store_json_completion.' + cls + '.test_'
        for predicate, old, new in (('duplicate', 'HAVING count(*) > 1', 'HAVING count(*) < 0'),
                ('nul', "instr(CAST(key AS BLOB), x'00') > 0", '0 > 0')):
            mid = f'JSON2BC-{table}-{column}-{event}-{predicate}'
            MUTATIONS.append(Mutation(mid, '2d-4b3e1-json2b part 2', predicate,
                (test + predicate + '_' + event,), old=old, new=new,
                scope=f'member_domain_{table}_{column}_{event}'))
            CONTROLS[mid] = {'controls': [test + 'control_' + event],
                'why': 'Separate accepted Store.select readback; named fixture exclusions isolate mirrored/closed domains, while preserving the transformed target guard and order.'}

mid = 'JSON2BC-generated-completion'
MUTATIONS.append(Mutation(mid, '2d-4b3e1-json2b part 2', 'check final generated DDL',
    ('test_check_ddl_rules.DdlRuleTest.test_completion_generated_drift',),
    old='for output, expected in outputs(covered).items():',
    new='for output, expected in outputs(covered).items():\n            if output == FINAL: continue',
    target='tools/gen2_json_member_domain.py'))
CONTROLS[mid] = {'controls': ['test_check_ddl_rules.DdlRuleTest.test_domain_control'],
    'why': 'Unchanged complete generated schema passes the checked output comparison.'}
