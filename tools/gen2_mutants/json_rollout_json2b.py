"""Paired predicate mutants for global admission and eight additive guards."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}


def add(name, killer, control, old, new, target='ddl', scope=None, also=()):
    mid = 'JSON2B-' + name
    MUTATIONS.append(Mutation(mid, '2d-4b3e1-json2b', name, (killer,),
        old=old, new=new, target=target, scope=scope, also=also))
    CONTROLS[mid] = {'controls': [control], 'why':
        'Separate accepted/readable control passes the changed predicate; raw fixtures preserve all semantic INSERT guards and assert transformed trigger order.'}


for table, column, cls in (
        ('amendment_impacts', 'document', 'AmendmentImpactsTest'),
        ('audit_events', 'detail', 'AuditEventsTest'),
        ('config_bundles', 'document', 'ConfigBundlesTest'),
        ('contract_revisions', 'document', 'ContractRevisionsTest'),
        ('invocation_transitions', 'facts', 'InvocationTransitionsTest'),
        ('scoping_reports', 'document', 'ScopingReportsTest'),
        ('screening_assessments', 'criterion_results', 'ScreeningAssessmentsTest'),
        ('source_proposals', 'document', 'SourceProposalsTest')):
    for event in ('i', 'u'):
        test = 'test_store_json_rollout.' + cls + '.test_'
        for predicate, old, new in (('duplicate', 'HAVING count(*) > 1', 'HAVING count(*) < 0'),
                ('nul', "instr(CAST(key AS BLOB), x'00') > 0", '0 > 0')):
            add(f'{table}-{event}-{predicate}', test + predicate + '_' + event,
                test + 'control_' + event, old, new,
                scope=f'member_domain_{table}_{column}_{event}')

TEST = 'test_json_global_admission.GlobalAdmissionTest.test_'
add('boundary-default', TEST + 'router_names', TEST + 'boundary_control',
    'member_domain: bool = True', 'member_domain: bool = False', target='gen2/router/boundary.py')
add('store-global', TEST + 'store_names', TEST + 'store_all_columns_control',
    'canonical.parse_json_strict(value, member_domain=True)',
    'canonical.parse_json_strict(value, member_domain=False)', target='gen2/store/api.py',
    also=(('canonical.canonical_bytes(parsed, member_domain=True)',
           'canonical.canonical_bytes(parsed, member_domain=False)'),))
add('generated-rollout', 'test_check_ddl_rules.DdlRuleTest.test_rollout_generated_drift',
    'test_check_ddl_rules.DdlRuleTest.test_domain_control',
    'for output, expected in outputs(covered).items():',
    'for output, expected in outputs(covered).items():\n            if output == ROLLOUT: continue',
    target='tools/gen2_json_member_domain.py')
