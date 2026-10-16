-- trace: flow S4 step 8; INVARIANTS V-1/V-2/V-3; SQL 17 remains fenced.
-- Earlier acquisition/content errors retain their diagnostics in either order.
CREATE TRIGGER verification_receipts_validated_extraction
AFTER INSERT ON verification_receipts
WHEN NEW.extraction_method = 'validated_extraction'
BEGIN
  SELECT RAISE(ABORT, 'receipt needs its successful durable /2 validation')
  WHERE EXISTS (SELECT 1 FROM source_acquisition_content_tiers available
    WHERE available.work_id = NEW.work_id AND available.source_version = NEW.source_version
      AND available.verifier_invocation_id = NEW.verifier_invocation_id
      AND available.content_hash = NEW.obtained_content_hash
      AND available.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')
      AND available.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')
      AND 'gateway:' || available.lane = json_extract(NEW.acquisition, '$.route')
      AND available.recorded_tier_rank >= CASE NEW.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END)
  AND NOT EXISTS (
    SELECT 1 FROM extraction_validation_results_v2 v
    JOIN source_extractions x ON x.extraction_id = v.target_extraction_id
    JOIN source_acquisitions a
      USING (topic_id, work_id, source_version, event_id, verifier_invocation_id)
    WHERE v.validation_id = NEW.extraction_validation_ref AND v.method_succeeded = 1
      AND v.validator_invocation_id = NEW.verifier_invocation_id
      AND x.topic_id = NEW.topic_id AND x.work_id = NEW.work_id
      AND x.source_version = NEW.source_version AND x.verifier_invocation_id = NEW.verifier_invocation_id
      AND x.extracting_invocation_id = NEW.extraction_invocation_id
      AND x.extractor_identity = json_extract(NEW.receipt, '$.extraction.extractor')
      AND x.extractor_registry_version IS NOT NULL
      AND a.content_hash = NEW.obtained_content_hash
      AND a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')
      AND a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')
      AND 'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route')
      AND (CASE x.supported_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 ELSE 3 END)
        >= CASE NEW.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END);
END;
