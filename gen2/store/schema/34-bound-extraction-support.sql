-- trace: flow S4 step 8; INVARIANTS V-2/V-3/V-4/V-8; DOSSIER 2d-4b3e3.
-- Re-read the SQL 32/33 basis at consumption, including historical receipts.
-- Registry interpretation belongs to the retained validation, not the current registry revision.
CREATE VIEW bound_extraction_receipts AS
SELECT r.verification_receipt_id
FROM verification_receipts r
LEFT JOIN extraction_validation_results_v2 validation
  ON validation.validation_id = r.extraction_validation_ref
  AND validation.method_succeeded = 1 AND validation.validator_invocation_id = r.verifier_invocation_id
JOIN source_extractions basis ON
  (r.extraction_method = 'verifier_extraction'
    AND json_type(r.receipt, '$.extraction.extraction_id') = 'text'
    AND basis.extraction_id = json_extract(r.receipt, '$.extraction.extraction_id')
    AND basis.extracting_invocation_id = r.verifier_invocation_id)
  OR (r.extraction_method = 'validated_extraction' AND basis.extraction_id = validation.target_extraction_id)
JOIN source_acquisition_content_tiers acquired
  ON acquired.topic_id = basis.topic_id AND acquired.work_id = basis.work_id
  AND acquired.source_version = basis.source_version AND acquired.event_id = basis.event_id
  AND acquired.verifier_invocation_id = basis.verifier_invocation_id
WHERE basis.topic_id = r.topic_id AND basis.work_id = r.work_id
  AND basis.source_version = r.source_version AND basis.verifier_invocation_id = r.verifier_invocation_id
  AND basis.extracting_invocation_id = r.extraction_invocation_id
  AND basis.extractor_identity = json_extract(r.receipt, '$.extraction.extractor')
  AND basis.extractor_registry_version IS NOT NULL
  AND acquired.content_hash = r.obtained_content_hash
  AND acquired.gateway_call_ref = json_extract(r.acquisition, '$.gateway_call_ref')
  AND acquired.retrieved_at = json_extract(r.acquisition, '$.retrieved_at')
  AND 'gateway:' || acquired.lane = json_extract(r.acquisition, '$.route')
  AND (CASE basis.supported_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 ELSE 3 END)
    >= CASE r.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END
  AND acquired.recorded_tier_rank >= CASE r.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END;

-- trace: flow S4 step 8; INVARIANTS V-3/V-4; SQL 17 diagnostic retained.
DROP TRIGGER claims_accepted_support_pending_extraction;
-- The installed-trigger inventory preserves the retired CREATE/DROP in place.
-- Keep SQL 17's activation, canonical escape and missing/partial/sampled errors.
-- A bound extraction must itself satisfy V-4; two receipts cannot pool gates.
CREATE TRIGGER claims_accepted_support_bound_extraction
BEFORE UPDATE OF status ON claims
WHEN NEW.status = 'accepted_support'
  AND EXISTS (SELECT 1 FROM verification_receipts v
    WHERE v.claim_id = NEW.claim_id AND v.claim_revision = NEW.revision
      AND v.verdict = 'supports' AND v.use = 'load_bearing'
      AND v.extraction_method IN ('verifier_extraction', 'validated_extraction'))
  AND NOT EXISTS (SELECT 1 FROM verification_receipts c
    WHERE c.claim_id = NEW.claim_id AND c.claim_revision = NEW.revision
      AND c.verdict = 'supports' AND c.use = 'load_bearing'
      AND (c.extraction_method = 'canonical_bytes' OR (
        EXISTS (SELECT 1 FROM bound_extraction_receipts b WHERE b.verification_receipt_id = c.verification_receipt_id)
        AND c.required_access_tier = NEW.required_access_tier
        AND (CASE c.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END)
          >= CASE NEW.required_access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END
        AND coalesce(json_extract(c.receipt, '$.checks.numeric_units'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
        AND coalesce(json_extract(c.receipt, '$.checks.denominators'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
        AND coalesce(json_extract(c.receipt, '$.checks.negation'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
        AND coalesce(json_extract(c.receipt, '$.checks.qualifications'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
        AND json_extract(c.receipt, '$.checks.tier0.signal') IS NOT 'alarm')))
BEGIN
  SELECT RAISE(ABORT, 'unbound extraction cannot authorize accepted support');
END;
