"""Bound successful /2 receipt consumption, with separately traced controls."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW = 'test_store_validated_extraction_receipts.ValidatedReceiptDDLTest.test_'
ROUTER = 'test_validated_extraction_receipts.ValidatedReceiptRouterTest.test_'
SCOPE = 'verification_receipts_validated_extraction'
P = 'gen2/router/evidence_writer.py'


def change(name, killer, old, new, target='ddl', also=()):
    mid = '2D4B3E2VAL-' + name
    prefix = RAW if target == 'ddl' else ROUTER
    MUTATIONS.append(Mutation(mid, '2d-4b3e2 consumers part 2', name, (prefix + killer,), old=old, new=new,
        target=target, scope=SCOPE if target == 'ddl' else None, also=also))
    CONTROLS[mid] = dict(controls=[prefix + 'control'], why='Separate admitted validated receipt reaches the changed consumer guard.')


change('target', 'work', 'x.extraction_id = v.target_extraction_id', '1 = 1')
change('reference', 'invented', 'v.validation_id = NEW.extraction_validation_ref', '1 = 1')
change('success', 'failed', 'v.method_succeeded = 1', '1 = 1')
change('verifier', 'verifier', 'v.validator_invocation_id = NEW.verifier_invocation_id', '1 = 1',
    also=(('x.verifier_invocation_id = NEW.verifier_invocation_id', '1 = 1'),))
for field, killer, rhs in (('work_id', 'work', 'NEW.work_id'), ('source_version', 'version', 'NEW.source_version'),
        ('extracting_invocation_id', 'extractor', 'NEW.extraction_invocation_id'),
        ('extractor_identity', 'tool', "json_extract(NEW.receipt, '$.extraction.extractor')")):
    change(field, killer, f'x.{field} = {rhs}', '1 = 1')
change('pin', 'unpinned', 'x.extractor_registry_version IS NOT NULL', '1 = 1')
change('tier', 'tier', "CASE x.supported_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 ELSE 3 END", '3')
for field, killer in (('gateway_call_ref', 'call'), ('retrieved_at', 'time'), ('route', 'route')):
    lhs = "'gateway:' || a.lane" if field == 'route' else 'a.' + field
    change(field, killer, f"{lhs} = json_extract(NEW.acquisition, '$.{field}')", '1 = 1')
change('router-dispatch', 'invented', '            self._require_validated_extraction(doc)', '            pass', P)
change('router-reference', 'invented', '{"validation_id": receipt["extraction"]["validation_ref"]}', '{}', P)
change('router-target', 'work', '{"extraction_id": validation["target_extraction_id"]}',
    '{"extracting_invocation_id": receipt["extraction"]["produced_by_invocation_id"], **receipt["source"]}', P)
change('router-success', 'failed', 'validation["outcome"] != "succeeded"', 'False', P)
change('router-independent', 'integrity', 'validation["method"] != "independent_extraction"', 'False', P)
for field, killer in (('extracting_invocation_id', 'extractor'), ('extractor_identity', 'tool')):
    rhs = 'produced_by_invocation_id' if field == 'extracting_invocation_id' else 'extractor'
    change('router-' + field, killer, f'basis["{field}"] != receipt["extraction"]["{rhs}"]', 'False', P)
change('router-pin', 'unpinned', 'basis["extractor_registry_version"] is None', 'False', P)
change('router-tier', 'tier', 'rank[basis["supported_tier"]] < rank[receipt["access_tier"]]', 'False', P)
keys = "('topic_id', 'work_id', 'source_version', 'event_id', 'verifier_invocation_id')"
for field, killer in (('work_id', 'work'), ('source_version', 'version'), ('verifier_invocation_id', 'verifier'), ('event_id', 'call')):
    replacement = '(' + ', '.join(repr(k) for k in ('topic_id', 'work_id', 'source_version', 'event_id', 'verifier_invocation_id') if k != field) + ')'
    also = (( '**receipt["source"]', '"source_version": receipt["source"]["source_version"]'),) if field == 'work_id' else ()
    if field == 'verifier_invocation_id':
        also = (('validation["validator_invocation_id"] != receipt["verifier_invocation_id"]', 'False'),)
    change('router-' + field, killer, keys, replacement, P, also)
for field, killer in (('gateway_call_ref', 'call'), ('retrieved_at', 'time'), ('lane', 'route')):
    lhs = '"gateway:" + a["lane"]' if field == 'lane' else 'a["' + field + '"]'
    rhs = 'route' if field == 'lane' else field
    change('router-' + rhs, killer, lhs + ' == receipt["acquisition"]["' + rhs + '"]', 'True', P)
