"""JSON2 part 1: separately paired member-domain and byte-retention predicates."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW = 'test_attempted_request_bytes.AttemptTest.test_'
DDL = 'test_store_observation_domain.ObservationDomainTest.test_'


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
        ('reference-shape', "json_remove(NEW.request, '$.request.request_type', '$.retained_request.bytes_hash', '$.retained_request.reason')\n      != '{\"request\":{},\"retained_request\":{}}'"),
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
