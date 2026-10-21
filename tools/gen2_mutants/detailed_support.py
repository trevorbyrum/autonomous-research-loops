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

# 4b2a: public Router promotion with SQL support consumers explicitly omitted.
ROUTER = 'test_router_detailed_support.RouterDetailedSupportTest.test_'
DETAIL = 'gen2/router/detailed_checks.py'
for name, target, old, new, killer in (
        ('writer', 'gen2/router/evidence_writer.py', 'self._core._require_detailed_support(row)', 'None', 'historical_shapes'),
        ('delegate', 'gen2/router/service.py', 'self._detailed_checks.require_support(claim, self._evidence_writer._quote_support_valid)', 'None', 'historical_shapes'),
        ('load-bearing', DETAIL, 'if not claim["load_bearing"]:', 'if True:', 'historical_shapes'),
        ('verdict', DETAIL, 'row["verdict"] != "supports"', 'False', 'claim_owned_gates'),
        ('use', DETAIL, 'row["use"] != "load_bearing"', 'False', 'claim_owned_gates'),
        ('required-tier', DETAIL, 'row["required_access_tier"] != claim["required_access_tier"]', 'False', 'claim_owned_gates'),
        ('access-tier', DETAIL, 'rank[row["access_tier"]] < rank[claim["required_access_tier"]]', 'False', 'claim_owned_gates'),
        ('version', DETAIL, 'doc.get("receipt_version") != "verification-receipt/2"', 'False', 'historical_shapes'),
        ('four', DETAIL, 'set(entries) != {"numeric_units", "denominators", "negation", "qualifications"}', 'False', 'historical_shapes'),
        ('performed', DETAIL, 'entry.get("outcome") not in ("succeeded", "failed", "not_applicable")', 'False', 'missing_and_outcomes'),
        ('binding', DETAIL, 'try:\n                self.require_receipt(doc)', 'try:\n                None', 'bindings'),
        ('stored-topic', DETAIL, '"topic_id": row["topic_id"]', '"topic_id": row["receipt"]["topic_id"]', 'stored_operands'),
        ('stored-verifier', DETAIL, '"verifier_invocation_id": row["verifier_invocation_id"]', '"verifier_invocation_id": row["receipt"]["verifier_invocation_id"]', 'stored_operands'),
        ('stored-spans', DETAIL, '"cited_spans": row["cited_spans"]', '"cited_spans": row["receipt"]["cited_spans"]', 'stored_operands')):
    mid = '2D4C4B2A-' + name
    MUTATIONS.append(Mutation(mid, '2d-4c part 4b2a', name, (ROUTER + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = dict(controls=[ROUTER + 'control'],
        why='Separate public Router promotions consume four real exactly bound performed records in both orders for all three methods, with SQL support consumers omitted.')

# 4b2b: the SAME candidate also needs its acquisition and durable basis.
BASIS = 'test_router_support_basis.RouterSupportBasisTest.test_'
for name, old, new, killer in (
        ('decoder', 'canonical.parse_json_strict(acquired["response_bytes"])', '__import__("json").loads(acquired["response_bytes"])', 'content'),
        ('same-candidate', 'if not self._has_basis(row, rank):', 'if False:', 'no_pooling'),
        ('hash', 'acquired["content_hash"] != row["obtained_content_hash"]', 'False', 'acquisition'),
        ('call', 'acquired["gateway_call_ref"] != row["acquisition"]["gateway_call_ref"]', 'False', 'acquisition'),
        ('time', 'acquired["retrieved_at"] != row["acquisition"]["retrieved_at"]', 'False', 'acquisition'),
        ('route', '"gateway:" + acquired["lane"] != row["acquisition"]["route"]', 'False', 'acquisition'),
        ('content', 'self._content_rank(acquired) < rank[row["access_tier"]]', 'False', 'content'),
        ('acquirer', 'acquired["acquired_by_invocation_id"] == row["extraction_invocation_id"]', 'True', 'acquisition'),
        ('lineage', 'elif all(basis[k] == acquired[k] for k in\n                    ("topic_id", "work_id", "source_version", "event_id", "verifier_invocation_id")):', 'elif True:', 'extraction'),
        ('validation-method', 'validation["method"] != "independent_extraction"', 'False', 'validation'),
        ('validation-policy', 'validation["policy_version"] != 2', 'False', 'validation'),
        ('validation-outcome', 'validation["outcome"] != "succeeded"', 'False', 'validation'),
        ('validation-verifier', 'validation["validator_invocation_id"] != row["verifier_invocation_id"]', 'False', 'validation'),
        ('independent-tier', 'rank[independent[0]["supported_tier"]] < rank[row["access_tier"]]', 'False', 'validation'),
        ('target-tier', 'rank[basis["supported_tier"]] < rank[row["access_tier"]]', 'False', 'extraction'),
        ('pin', 'basis["extractor_registry_version"] is None', 'False', 'extraction'),
        ('invocation', 'basis["extracting_invocation_id"] != row["extraction_invocation_id"]', 'False', 'extraction'),
        ('tool', 'basis["extractor_identity"] != row["receipt"]["extraction"]["extractor"]', 'False', 'extraction'),
        ('own-verifier', 'basis["extracting_invocation_id"] != row["verifier_invocation_id"]', 'False', 'extraction'),
        ('tier0', 'row["receipt"]["checks"].get("tier0", {}).get("signal") == "alarm"', 'False', 'extraction'),
        ('selected-record', 'record.get("identity") == acquired["provider_record_id"]', 'True', 'content'),
        ('coverage', 'searched and record.get("kind") == "full_text"', 'record.get("kind") == "full_text"', 'content'),
        ('full-text', 'record.get("kind") == "full_text" and self._nonblank(record.get("text"))', 'record.get("kind") == "full_text"', 'content'),
        ('abstract', 'else 2 if self._nonblank(record.get("abstract")) else 1', 'else 2', 'content')):
    mid = '2D4C4B2B-' + name
    MUTATIONS.append(Mutation(mid, '2d-4c part 4b2b', name, (BASIS + killer,), target=DETAIL, old=old, new=new))
    CONTROLS[mid] = dict(controls=[BASIS + 'control'],
        why='Separate public promotion controls consume real admitted detailed records and the same acquired canonical/own/validated basis at abstract and full-text tiers in both trigger orders, with SQL authority views permissive.')

# 4b2c1: capture binding is part of that candidate, then refenced once at end.
CAPTURE_ROUTER = 'test_router_capture_support.RouterCaptureSupportTest.test_'
WRITER = 'gen2/router/evidence_writer.py'
for name, target, old, new, killer, control in (
        ('candidate', DETAIL, 'if not capture_valid(doc):', 'if False:', 'no_pooling', 'control'),
        ('canonical', WRITER, 'doc["extraction"]["method"] == "canonical_bytes" and self._quote_receipt_valid(doc)',
            'self._quote_receipt_valid(doc)', 'no_pooling', 'control'),
        ('binding', WRITER, 'and self._quote_receipt_valid(doc)', 'and True', 'capture_binding_and_columns', 'control'),
        ('stored-check', DETAIL, '"quote_check_id": row["quote_check_id"]',
            '"quote_check_id": row["receipt"]["quote_check_id"]', 'capture_binding_and_columns', 'control'),
        ('final-wiring', 'gen2/router/service.py', 'self._evidence_writer.refence_captures(env["operation_id"])',
            'None', 'final_missing_and_history', 'final_control'),
        ('final-operation', WRITER, '{"recorded_by_operation_id": operation_id}',
            'None', 'scope_and_status', 'final_control'),
        ('final-status', WRITER, 'if claim["status"] != "accepted_support":',
            'if False:', 'scope_and_status', 'final_control'),
        ('final-detailed', WRITER, 'self._core._require_detailed_support(claim)',
            'None', 'final_records_and_basis', 'final_control'),
        ('final-quarantine', WRITER, 'self._require_quote_support(claim)',
            'None', 'scope_and_status', 'final_control')):
    mid = '2D4C4B2C1-' + name
    MUTATIONS.append(Mutation(mid, '2d-4c part 4b2c1', name, (CAPTURE_ROUTER + killer,),
        target=target, old=old, new=new))
    CONTROLS[mid] = dict(controls=[CAPTURE_ROUTER + control],
        why='Separate real-record canonical captures promote or remain accepted through completed interim/final commits in both trigger orders with SQL authority views disabled.')
