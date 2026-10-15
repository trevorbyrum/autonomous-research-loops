"""Each durable own-extraction refusal has an admitted, traced receipt pair."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW = 'test_store_own_extraction_receipts.OwnReceiptDDLTest.test_'
ROUTER = 'test_own_extraction_receipts.OwnReceiptRouterTest.test_'


def change(name, killer, old, new, target='ddl'):
    mid = '2D4B3E2OWN-' + name
    prefix = RAW if target == 'ddl' else ROUTER
    MUTATIONS.append(Mutation(mid, '2d-4b3e2 consumers part 1', name, (prefix + killer,), old=old, new=new,
        target=target, scope='verification_receipts_own_extraction' if target == 'ddl' else None,
        also=(('**doc["source"]', '"source_version": doc["source"]["source_version"]'),) if name == 'router-work_id' else ()))
    CONTROLS[mid] = dict(controls=[prefix + 'control'], why='Separate admitted own-extraction receipt reaches the changed basis predicate.')


for field, killer, rhs in (('extraction_id', 'invented', "json_extract(NEW.receipt, '$.extraction.extraction_id')"),
        ('work_id', 'work', 'NEW.work_id'), ('source_version', 'version', 'NEW.source_version'),
        ('verifier_invocation_id', 'verifier', 'NEW.verifier_invocation_id'),
        ('extracting_invocation_id', 'extractor', 'NEW.extraction_invocation_id'),
        ('extractor_identity', 'tool', "json_extract(NEW.receipt, '$.extraction.extractor')")):
    change(field, killer, f'x.{field} = {rhs}', '1 = 1')
change('pin', 'unpinned', 'x.extractor_registry_version IS NOT NULL', '1 = 1')
change('tier', 'tier', "CASE x.supported_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 ELSE 3 END", '3')
for field, killer in (('gateway_call_ref', 'call'), ('retrieved_at', 'time'), ('route', 'route')):
    lhs = "'gateway:' || a.lane" if field == 'route' else 'a.' + field
    change(field, killer, f"{lhs} = json_extract(NEW.acquisition, '$.{field}')", '1 = 1')
p = 'gen2/router/evidence_writer.py'
change('router-dispatch', 'invented', '            self._require_own_extraction(doc)', '            pass', p)
change('router-lookup', 'invented', '{"extraction_id": doc["extraction"].get("extraction_id")}', '{}', p)
for field, killer in (('extracting_invocation_id', 'extractor'), ('extractor_identity', 'tool')):
    rhs = 'produced_by_invocation_id' if field == 'extracting_invocation_id' else 'extractor'
    change('router-' + field, killer, f'extraction["{field}"] != doc["extraction"]["{rhs}"]', 'False', p)
change('router-pin', 'unpinned', 'extraction["extractor_registry_version"] is None', 'False', p)
change('router-tier', 'tier', 'rank[extraction["supported_tier"]] < rank[doc["access_tier"]]', 'False', p)
for field, killer in (('work_id', 'work'), ('source_version', 'version'), ('verifier_invocation_id', 'verifier'), ('event_id', 'call')):
    keys = '("topic_id", "work_id", "source_version", "event_id", "verifier_invocation_id")'
    replacement = '(' + ', '.join('"' + k + '"' for k in ('topic_id', 'work_id', 'source_version', 'event_id', 'verifier_invocation_id') if k != field) + ')'
    change('router-' + field, killer, keys, replacement, p)

change('reference-type', 'reference_type', "json_type(NEW.receipt, '$.extraction.extraction_id') = 'text'", '1 = 1')
for field, killer in (('gateway_call_ref', 'call'), ('retrieved_at', 'time'), ('lane', 'route')):
    lhs = '"gateway:" + a["lane"]' if field == 'lane' else 'a["' + field + '"]'
    rhs = 'route' if field == 'lane' else field
    change('router-' + rhs, killer, lhs + ' == doc["acquisition"]["' + rhs + '"]', 'True', p)
mid = '2D4B3E2OWN-retired-trigger'
MUTATIONS.append(Mutation(mid, '2d-4b3e2 consumers part 1', 'reverse retired trigger too',
    ('test_trigger_order_tool.TriggerOrderToolTest.test_additive_trigger_replacement',),
    target='tools/gen2_trigger_order.py', old='if m.group(1) not in retired]', new=']'))
CONTROLS[mid] = dict(controls=['test_trigger_order_tool.TriggerOrderToolTest.test_rebuild_creates_the_same_triggers_in_reverse'],
    why='Separate literal schema without a retired definition still reverses all installed triggers.')
