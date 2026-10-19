"""Exact cap predicates with independent accepted paths through each guard."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}


def add(name, killer, control, *, scope=None, old=None, new='', target='ddl'):
    mid = '2D4CCAP-' + name.replace('verification_receipts_span_domain_v4', 'verification_receipts_span_domain_v3').replace('detailed_check_records_spans_v2', 'detailed_check_records_spans')
    MUTATIONS.append(Mutation(mid, '2d-4c cap', name, (killer,), target=target, scope=scope, old=old, new=new))
    CONTROLS[mid] = {'controls': [control], 'why': 'Separate accepted numeric span reaches this admission predicate; exact retained values are asserted.'}


for scope, prefix in (
        ('verification_receipts_span_domain_v4', 'test_store_span_domain.SpanDDLTest.test_cap_'),
        ('detailed_check_records_spans_v2', 'test_store_detailed_checks.DDLCheckTest.test_cap_'),
        ('claim_source_links_span_cap', 'test_store_span_cap.AuxiliaryCapTest.test_')):
    for name, old, new in (
            ('magnitude', "length(ltrim(digits, '0')) + exponent - scale > 16", '0'),
            ('boundary', "COLLATE BINARY > '9007199254740991'", 'COLLATE BINARY > \'9999999999999999\'')):
        add(scope + '-' + name, prefix + ('refusals' if 'links' in scope else 'matrix'), prefix + 'control', scope=scope, old=old, new=new)
for key in ('start', 'end'):
    add('schema-' + key, 'test_span_cap.SpanCapTest.test_schemas', 'test_span_cap.SpanCapTest.test_control',
        target='gen2/schema/verification-receipt.schema.json',
        old=f'"{key}": {{"type": "integer", "minimum": {0 if key == "start" else 1}, "maximum": 9007199254740991}}',
        new=f'"{key}": {{"type": "integer", "minimum": {0 if key == "start" else 1}}}')
add('router', 'test_span_cap.SpanCapTest.test_router_boundary', 'test_span_cap.SpanCapTest.test_control',
    target='gen2/router/boundary.py', old='canonical.identity_integer(span[name], minimum=minimum)', new='pass')
add('quote-end', 'test_store_span_cap.AuxiliaryCapTest.test_refusals', 'test_store_span_cap.AuxiliaryCapTest.test_control',
    scope='quote_checks_span_cap', old='NEW.span_end > 9007199254740991', new='0')
add('link-fraction', 'test_store_span_cap.AuxiliaryCapTest.test_refusals', 'test_store_span_cap.AuxiliaryCapTest.test_control',
    scope='claim_source_links_span_cap', old="rtrim(substr(ltrim(digits, '0'), 17), '0') <> ''", new='0')
