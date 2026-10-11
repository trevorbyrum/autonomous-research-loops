-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-1/V-2/V-3.
-- Extraction consumes acquired input; its producer names the extractor, not
-- the acquiring invocation. SQL 14/03 bind the verifier to the same topic.
-- AFTER preserves existing BEFORE/row-CHECK diagnostics. ABORT undoes the
-- insertion and the Router rolls back its enclosing commit transaction.
-- SQL 17 still fences support; content ceilings follow in the next part.
CREATE TRIGGER verification_receipts_admitted_extraction
AFTER INSERT ON verification_receipts
WHEN NEW.extraction_method IN ('verifier_extraction', 'validated_extraction')
  AND NOT EXISTS (
    SELECT 1 FROM source_acquisitions a
    WHERE a.work_id = NEW.work_id
      AND a.source_version = NEW.source_version
      AND a.verifier_invocation_id = NEW.verifier_invocation_id
      AND a.content_hash = NEW.obtained_content_hash
      AND a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')
      AND a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')
      AND 'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route'))
BEGIN
  SELECT RAISE(ABORT, 'extraction receipt must consume its admitted acquisition');
END;
