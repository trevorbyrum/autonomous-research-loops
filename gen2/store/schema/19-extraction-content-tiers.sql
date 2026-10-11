-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-1/V-2/V-3.
-- Consume SQL 18's acquisition and SQL 16's selected-record/nonblank ceiling.
-- Match the obtained hash even on invalid receipts; verifier implies topic.
-- Extractor identity does not select the acquirer. Missing admission remains
-- SQL 18's diagnostic, independent of trigger order. SQL 17 still fences support.
CREATE TRIGGER verification_receipts_extraction_content_tier
AFTER INSERT ON verification_receipts
WHEN NEW.extraction_method IN ('verifier_extraction', 'validated_extraction')
  AND (CASE NEW.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2
       WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END) > coalesce((
    SELECT max(a.recorded_tier_rank) FROM source_acquisition_content_tiers a
    WHERE a.work_id = NEW.work_id
      AND a.source_version = NEW.source_version
      AND a.verifier_invocation_id = NEW.verifier_invocation_id
      AND a.content_hash = NEW.obtained_content_hash
      AND a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')
      AND a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')
      AND 'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route')), 4)
BEGIN
  SELECT RAISE(ABORT, 'extraction receipt tier exceeds recorded content');
END;
