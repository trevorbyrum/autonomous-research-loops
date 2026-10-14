"""JSON2 part 1: separately paired member-domain and byte-retention predicates."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW = 'test_attempted_request_bytes.AttemptTest.test_'
DDL = 'test_store_observation_domain.ObservationDomainTest.test_'
CONTROLS['2B13-cursor-beyond-the-bound'] = {
    'controls': ['test_admission.AtTheRouter.test_accepted_integer_boundaries'],
    'why': 'Accepted 0, 1 and 2**53-1 reach the integer bound for both continuation outcomes; separate from the unchanged negative oracle (JSON2 repair F3).'}


def add(name, killer, control, old, new, target='ddl', scope=None):
    mid = 'JSON2-' + name
    MUTATIONS.append(Mutation(mid, '2d-4b3e1-json2', name, (killer,), target=target, scope=scope, old=old, new=new))
    CONTROLS[mid] = {'controls': [control], 'why': 'Independent accepted observation passes this predicate; byte retention never canonicalizes the original. UPDATE controls isolate unconditional immutability/cursor shape in disposable schema objects.'}


for column in ('request', 'obligation_ids', 'continuation'):
    for event in ('i', 'u'):
        test = DDL + column + '_' + event + '_'
        for predicate, old, new in (('duplicate', 'HAVING count(*) > 1', 'HAVING count(*) < 0'),
                                   ('nul', "instr(CAST(key AS BLOB), x'00') > 0", '0 > 0')):
            add(f'{column}-{event}-{predicate}', test + predicate, test + 'control', old, new,
                scope=f'member_domain_search_observations_{column}_{event}')

for name, old in (
        ('byte-pair', '(NEW.request_bytes IS NULL) != (NEW.request_bytes_hash IS NULL)'),
        ('identity', 'NEW.request_bytes_hash IS NOT NEW.request_identity'),
        ('reference-hash', "json_extract(NEW.request, '$.retained_request.bytes_hash') IS NOT NEW.request_bytes_hash"),
        ('reference-reason', "json_extract(NEW.request, '$.retained_request.reason') IS NOT 'member_name_domain'"),
        ('reference-shape', "json_remove(NEW.request, '$.request.request_type', '$.retained_request.bytes_hash', '$.retained_request.reason')\n      NOT IN ('{\"request\":{},\"retained_request\":{}}', '{\"retained_request\":{}}')"),
        ('failed-error', "NEW.error_class IS NOT 'payload_invalid'")):
    add('retained-' + name, DDL + 'retained_binding', DDL + 'retained_control', old, '0', scope='search_observations_retained_request')

add('raw-original', RAW + 'retention', RAW + 'client_retention', 'raw = original', 'raw = original.strip()', target='gen2/router/observations.py')
add('failed-only', RAW + 'failed_only', RAW + 'retention',
    'if (obs["coverage_state"], obs["completeness"], obs["error_class"], obs["page_outcome"], events) != (',
    'if False and (obs["coverage_state"], obs["completeness"], obs["error_class"], obs["page_outcome"], events) != (', target='gen2/router/observations.py')
add('router-admission', RAW + 'router_nul', RAW + 'control',
    'req = boundary.normalize(request, "request_invalid", member_domain=True)',
    'req = boundary.normalize(request, "request_invalid")', target='gen2/router/observations.py')
add('store-byte-hash', RAW + 'store_hash', RAW + 'store_hash_control', "if digest != prepared.get('request_bytes_hash'):",
    'if False:', target='gen2/store/api.py')
add('raw-identity', RAW + 'retention', RAW + 'control',
    'identity = canonical.logical_hash(observation["request"]) if request_bytes is None else canonical.bytes_digest(request_bytes)',
    'identity = canonical.logical_hash(observation["request"])', target='gen2/router/boundary.py')
add('client-byte-hash', RAW + 'client_retention', RAW + 'control', "rid = canonical.bytes_digest(request.encode('utf-8'))",
    'rid = canonical.logical_hash(request)', target='gen2/gateway_client/observe.py')
add('accounting-raw', RAW + 'retention', RAW + 'control',
    'return None  # retained refused bytes do not assert a decoded search/page',
    'return a.SearchPage(a.search_identity({}), 1, None, None)', target='gen2/router/accounting.py')

add('descriptor-needs-bytes', DDL + 'descriptor_requires_its_own_bytes', DDL + 'retained_control',
    "(json_type(NEW.request, '$.retained_request') IS NOT NULL)\n  != (NEW.request_bytes IS NOT NULL)",
    '0', scope='search_observations_retained_representation')
add('reserved-descriptor', RAW + 'descriptor_cannot_be_an_ordinary_request', RAW + 'control',
    'if raw is None and isinstance(obs["request"], dict) and "retained_request" in obs["request"]:',
    'if False:', target='gen2/router/observations.py')
for name, old in (
        ('ordinary', 'if not marked and raw is None and digest is None:'),
        ('pair', 'if not marked or type(raw) is not bytes or digest is None:'),
        ('identity', 'if digest != observation["request_identity"]:'),
        ('descriptor', 'if request != descriptor and request != legacy:'),
        ('failed', 'if (observation["coverage_state"], observation["completeness"], observation["error_class"],')):
    new = ('if raw is None and digest is None:' if name == 'ordinary' else
           'if False:' if name in ('pair', 'identity', 'descriptor') else old.replace('if ', 'if False and ', 1))
    add('accounting-binding-' + name,
        RAW + 'accounting_requires_the_complete_binding', RAW + 'bound_accounting_control', old, new,
        target='gen2/core/pagination.py')

OPAQUE = 'test_opaque_attempts.OpaqueAttemptTest.test_'
add('opaque-schema', DDL + 'opaque_control', DDL + 'retained_control',
    "OR json_type(request, '$.retained_request') IS NOT NULL", 'OR 0', scope='search_observations')
add('legacy-discriminator', DDL + 'legacy_discriminator', DDL + 'retained_control',
    "(json_type(NEW.request, '$.request') IS NOT NULL AND NOT COALESCE(\n      json_extract(NEW.request, '$.request.request_type') IN ('find', 'resolve', 'enrich', 'fetch', 'data'), 0))",
    '0', scope='search_observations_retained_request')
add('object-handoff', OPAQUE + 'object_nul', RAW + 'readable_text_control',
    'if handoff is not None:', 'if False:', target='gen2/router/observations.py')
add('opaque-page-exception', OPAQUE + 'structural_nul', OPAQUE + 'ordinary_control',
    'if not opaque:', 'if True:', target='gen2/router/boundary.py')
add('opaque-descriptor', OPAQUE + 'structural_nul', OPAQUE + 'ordinary_control',
    'obs["request"] = {"retained_request": {',
    'obs["request"] = {"request": {"request_type": "find"}, "retained_request": {', target='gen2/router/observations.py')
add('opaque-reader', OPAQUE + 'structural_nul', OPAQUE + 'legacy_read_control',
    'if request != descriptor and request != legacy:', 'if request != legacy:', target='gen2/core/pagination.py')
add('opaque-inventory-type', OPAQUE + 'structural_nul', OPAQUE + 'ordinary_control',
    'pagination.request_type(o["request"])', '"find"', target='gen2/router/accounting.py')
