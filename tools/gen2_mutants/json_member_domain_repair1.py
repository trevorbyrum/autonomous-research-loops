"""Separate predicate mutants for each generated guard and staged admission."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}


def add(name, killer, control, old, new, target='ddl', scope=None):
    mid = 'JSON-DOMAIN-' + name
    MUTATIONS.append(Mutation(mid, '2d-4b3e1-repair-1', name, (killer,), old=old, new=new, target=target, scope=scope))
    CONTROLS[mid] = {'controls': [control], 'why': 'Independent accepted/readable record passes this predicate; UPDATE pairs remove only unconditional immutability in the disposable fixture.'}


for table, column, cls in (('source_extractions','output_ref','OutputTest'),
        ('extraction_validations','comparison_evidence_ref','ComparisonTest'), ('quote_checks','match_result','QuoteTest')):
    for event in ('i', 'u'):
        test = 'test_store_json_member_domain.' + cls + '.test_'
        for predicate, old, new in (('duplicate', 'HAVING count(*) > 1', 'HAVING count(*) < 0'),
                                   ('nul', "instr(CAST(key AS BLOB), x'00') > 0", '0 > 0')):
            add(f'{table}-{event}-{predicate}', test + predicate + '_' + event, test + 'control_' + event,
                old, new, scope=f'member_domain_{table}_{column}_{event}')

admission = 'test_json_member_admission.AdmissionTest.test_'
add('canonical-nul', admission+'router_nul', admission+'control', "if member_domain and '\\0' in key:",
    'if False:', target='gen2/core/canonical.py')
add('store-admission', admission+'store_nul', admission+'control',
    'guarded = f"member_domain_{table}_{column}_i" in self._member_domain', 'guarded = False', target='gen2/store/api.py')
add('router-admission', admission+'payload_wiring', admission+'control',
    'payload = boundary.normalize(raw, "payload_invalid", member_domain=True)',
    'payload = boundary.normalize(raw, "payload_invalid")', target='gen2/router/service.py')
add('static-check', 'test_check_ddl_rules.DdlRuleTest.test_json_column_uncovered',
    'test_check_ddl_rules.DdlRuleTest.test_domain_control', 'failures += check_member_domain(root, conn, text)',
    'pass', target='tools/check_gen2_schemas.py')
