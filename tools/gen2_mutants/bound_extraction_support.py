"""Durable promotion predicates, paired with a separate accepted promotion."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW = 'test_store_bound_extraction_support.BoundPromotionDDLTest.test_'
SCOPE = 'claims_accepted_support_detailed_extraction'


def change(name, old, new, killer, scope=None, also=()):
    mid = '2D4B3E3-' + name
    MUTATIONS.append(Mutation(mid, '2d-4b3e3 part 1', name, (RAW + killer,), old=old, new=new, scope=scope, also=also))
    CONTROLS[mid] = dict(controls=[RAW + 'control'], why='Separate bound promotions at all three attainable tiers read the basis view and pass the consuming trigger.')


change('reference-type', "json_type(r.receipt, '$.extraction.extraction_id') = 'text'", '1 = 1', 'reference_type')
change('hash', 'acquired.content_hash = r.obtained_content_hash', '1 = 1', 'hash')
change('own-reference', "basis.extraction_id = json_extract(r.receipt, '$.extraction.extraction_id')", '1 = 1', 'unbound')
change('validation-reference', 'validation.validation_id = r.extraction_validation_ref', '1 = 1', 'unbound')
change('validation-success', 'validation.method_succeeded = 1', '1 = 1', 'unbound')
change('own-method', "r.extraction_method = 'verifier_extraction'", '0', 'control', also=())
# Over-restrictive method mutants use a different accepted method as control.
CONTROLS['2D4B3E3-own-method']['controls'] = [RAW + 'history_control']
CONTROLS['2D4B3E3-own-method']['why'] = 'Separate validated-extraction full-text promotion after a registry merge takes the opposite method through the basis view and consumer.'
change('validation-method', "r.extraction_method = 'validated_extraction'", '0', 'history_control')
CONTROLS['2D4B3E3-validation-method']['controls'] = [RAW + 'own_control']
CONTROLS['2D4B3E3-validation-method']['why'] = 'Separate own-extraction full-text promotion takes the opposite method through the basis view and consumer.'
change('independent-reference', 'independent.extraction_id = validation.validator_extraction_id', 'independent.extraction_id = validation.target_extraction_id', 'independent_tier')
change('independent-tier', "CASE independent.supported_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 0 END", '3', 'independent_tier')
for name in ('independent-reference', 'independent-tier'):
    CONTROLS['2D4B3E3-' + name]['controls'] = [RAW + 'independent_tier_control']
for field, rhs in (('work_id', 'r.work_id'), ('source_version', 'r.source_version'),
        ('extractor_identity', "json_extract(r.receipt, '$.extraction.extractor')")):
    change(field, 'basis.' + field + ' = ' + rhs, '1 = 1', 'bindings')
change('verifier', 'basis.verifier_invocation_id = r.verifier_invocation_id', '1 = 1', 'bindings',
    also=(('validation.validator_invocation_id = r.verifier_invocation_id', '1 = 1'),))
change('extractor', 'basis.extracting_invocation_id = r.extraction_invocation_id', '1 = 1', 'bindings',
    also=(('basis.extracting_invocation_id = r.verifier_invocation_id', '1 = 1'),))
change('pin', 'basis.extractor_registry_version IS NOT NULL', '1 = 1', 'bindings')
for field in ('gateway_call_ref', 'retrieved_at'):
    change(field, f"acquired.{field} = json_extract(r.acquisition, '$.{field}')", '1 = 1', 'bindings')
change('route', "'gateway:' || acquired.lane = json_extract(r.acquisition, '$.route')", '1 = 1', 'bindings')
change('output-tier', "CASE basis.supported_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 ELSE 3 END", '3', 'bindings')
change('recorded-tier', "acquired.recorded_tier_rank >= CASE r.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END", '1 = 1', 'content_ceiling')
for field in ('numeric_units', 'denominators', 'negation', 'qualifications'):
    change(field, f"coalesce(json_extract(c.receipt, '$.checks.{field}'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')", '1 = 1', 'v4', SCOPE)
change('required-tier', 'c.required_access_tier = NEW.required_access_tier', '1 = 1', 'v4', SCOPE)
change('access-tier', "CASE c.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END", '4', 'v4', SCOPE)
change('tier0', "json_extract(c.receipt, '$.checks.tier0.signal') IS NOT 'alarm'", '1 = 1', 'v4', SCOPE)
change('basis', 'EXISTS (SELECT 1 FROM bound_extraction_receipts b WHERE b.verification_receipt_id = c.verification_receipt_id)', '1 = 1', 'unbound', SCOPE)
