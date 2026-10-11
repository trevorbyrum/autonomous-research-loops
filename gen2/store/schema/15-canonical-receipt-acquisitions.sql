-- trace: flow S4 step 8; BOUNDARIES.md Verifier/Router; INVARIANTS V-1/V-3.
-- Consume admitted canonical bytes. SQL 03 owns missing artifacts/calls;
-- these gates preserve its diagnostics independently of trigger order.
CREATE TRIGGER verification_receipts_admitted_canonical
BEFORE INSERT ON verification_receipts
WHEN NEW.extraction_method = 'canonical_bytes'
  AND json_extract(NEW.acquisition, '$.gateway_call_ref') IS NOT NULL
  AND EXISTS (SELECT 1 FROM artifacts WHERE content_hash = NEW.obtained_content_hash)
  AND NOT EXISTS (
    SELECT 1 FROM source_acquisitions a
    -- SQL 14 and SQL 03 bind this exact verifier to the acquisition/receipt
    -- topic respectively; equality of verifier identities also binds topic.
    WHERE a.work_id = NEW.work_id
      AND a.source_version = NEW.source_version
      AND a.verifier_invocation_id = NEW.verifier_invocation_id
      AND a.content_hash = NEW.obtained_content_hash
      AND a.acquired_by_invocation_id = NEW.extraction_invocation_id
      AND a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')
      AND a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')
      AND 'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route'))
BEGIN
  SELECT RAISE(ABORT, 'canonical receipt must consume its admitted acquisition');
END;
