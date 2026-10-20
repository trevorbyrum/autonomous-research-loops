"""SQL consumer predicates with separate, real-record accepted controls."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW = 'test_store_detailed_support.DetailedSupportDDLTest.test_'
CAPTURE = 'test_store_detailed_support.DetailedCaptureDDLTest.test_'


def change(name, old, killer, new='1 = 1', scope=None, capture=False):
    mid = '2D4C4B1-' + name
    prefix = CAPTURE if capture else RAW
    MUTATIONS.append(Mutation(mid, '2d-4c part 4b1', name, (prefix + killer,), old=old, new=new, scope=scope))
    CONTROLS[mid] = dict(controls=[prefix + ('capture_control' if capture else 'promotion_control')],
        why='Separate real-record support promotes under the subject relation and consuming trigger; capture control also passes final operation refencing.')


for name, old in (
        ('id', "d.check_id = json_extract(v.receipt, '$.detailed_checks.' || k.kind || '.record_id')"),
        ('topic', 'd.topic_id = v.topic_id'), ('verifier', 'd.performer_invocation_id = v.verifier_invocation_id'),
        ('kind', "json_extract(d.assessment, '$.kind') = k.kind"),
        *[(field, "json_extract(d.assessment, '$." + field + "') = " + rhs) for field, rhs in (
            ('claim_id', 'v.claim_id'), ('claim_revision', 'v.claim_revision'),
            ('cited_spans', 'json(v.cited_spans)'), ('work_id', 'v.work_id'),
            ('source_version', 'v.source_version'))]):
    change(name, old, 'missing_and_unperformed' if name == 'id' else 'bindings')
change('source_artifact_hash', "s.content_hash = json_extract(d.assessment, '$.source_artifact_hash')", 'bindings')
change('outcome', "json_extract(d.assessment, '$.outcome') = json_extract(v.receipt, '$.detailed_checks.' || k.kind || '.outcome')", 'missing_and_unperformed')
change('performed', "json_extract(d.assessment, '$.outcome') IN ('succeeded','failed','not_applicable')", 'missing_and_unperformed')
change('projection', "json_extract(v.receipt, '$.checks.' || k.kind) = CASE json_extract(d.assessment, '$.outcome')\n          WHEN 'succeeded' THEN 'checked_ok' WHEN 'failed' THEN 'checked_problem'\n          ELSE json_extract(d.assessment, '$.outcome') END", 'missing_and_unperformed')
change('examined', "json_extract(d.assessment, '$.examined_artifact_ref.content_hash') =\n          CASE v.extraction_method WHEN 'canonical_bytes' THEN v.obtained_content_hash ELSE (\n            SELECT json_extract(x.output_ref, '$.content_hash') FROM source_extractions x\n            WHERE x.extraction_id = CASE v.extraction_method WHEN 'verifier_extraction'\n              THEN json_extract(v.receipt, '$.extraction.extraction_id') ELSE (\n                SELECT target_extraction_id FROM extraction_validations_v2\n                WHERE validation_id = v.extraction_validation_ref) END) END", 'bindings')
change('version', "json_extract(v.receipt, '$.receipt_version') = 'verification-receipt/2'", 'shapes')
change('four', "(SELECT count(*) FROM json_each(v.receipt, '$.detailed_checks')) = 4", 'shapes')
for field in ('gateway_call_ref', 'retrieved_at'):
    change(field, f"a.{field} = json_extract(v.acquisition, '$.{field}')", 'canonical_basis')
change('route', "'gateway:' || a.lane = json_extract(v.acquisition, '$.route')", 'canonical_basis')
change('content', "a.recorded_tier_rank >= CASE v.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END", 'canonical_basis')
change('sql03', 'EXISTS (SELECT 1 FROM detailed_support_receipts d WHERE d.verification_receipt_id = v.verification_receipt_id)', 'historical_claims', scope='claims_accepted_support_detailed_receipt')
change('sql34', 'EXISTS (SELECT 1 FROM detailed_support_receipts d WHERE d.verification_receipt_id = c.verification_receipt_id)', 'non_pooling', scope='claims_accepted_support_detailed_extraction')
change('capture', 'EXISTS (SELECT 1 FROM detailed_support_receipts d WHERE d.verification_receipt_id = r.verification_receipt_id)', 'historical_capture', capture=True)
change('validated-target', 'SELECT target_extraction_id FROM extraction_validations_v2\n                WHERE validation_id = v.extraction_validation_ref', 'bindings', 'SELECT validator_extraction_id FROM extraction_validations_v2\n                WHERE validation_id = v.extraction_validation_ref')
change('capture-required-tier', 'r.required_access_tier = c.required_access_tier', 'capture_tiers', capture=True)
change('capture-access-tier', "(CASE r.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END)\n        >= CASE c.required_access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END", 'capture_tiers', capture=True)

HARNESS = 'tools/gen2_mutations.py'
BASELINE = 'test_mutation_verdict.BaselineModesTest.test_'
for name, replacement, killer, control in (
        ('sql-baseline', 'False', 'sql_baseline_refusal_stops_selected_sql', 'file_selection_runs_its_baseline_without_unrelated_sql'),
        ('file-mode', 'True', 'file_selection_runs_its_baseline_without_unrelated_sql', 'sql_selection_runs_its_baseline')):
    mid = '2D4C4B1-' + name
    MUTATIONS.append(Mutation(mid, '4b1 validation integration', name, (BASELINE + killer,), target=HARNESS,
        old='any(m.target in ("ddl", "connection") for m in selected)', new=replacement))
    CONTROLS[mid] = dict(controls=[BASELINE + control], why='Separate loading mode preserves its required baseline and existing refusal; the full inventory still selects SQL.')
