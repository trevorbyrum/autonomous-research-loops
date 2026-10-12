-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-2.
-- All methods consume the same SQL 16 recorded-content rule. Structured
-- provider rows have no durable locator binding and grant no tier here.
-- SQL 15/18 retain missing-acquisition diagnostics; SQL 17 retains its fence.
CREATE TRIGGER verification_receipts_table_availability
AFTER INSERT ON verification_receipts
WHEN NEW.verdict <> 'cannot_assess_at_required_tier'
  -- SQL 16/19 own higher declarations without recorded full text.
  AND NEW.access_tier IN ('bibliographic', 'abstract')
  AND EXISTS (SELECT 1 FROM json_each(NEW.cited_spans) s
    WHERE json_extract(s.value, '$.locator.kind') = 'table')
  AND coalesce((
    SELECT max(a.recorded_tier_rank) FROM source_acquisition_content_tiers a
    WHERE a.work_id = NEW.work_id
      AND a.source_version = NEW.source_version
      AND a.verifier_invocation_id = NEW.verifier_invocation_id
      AND a.content_hash = NEW.obtained_content_hash
      AND (NEW.extraction_method <> 'canonical_bytes'
        OR a.acquired_by_invocation_id = NEW.extraction_invocation_id)
      AND a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')
      AND a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')
      AND 'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route')), 3) < 3
BEGIN
  SELECT RAISE(ABORT, 'table citation requires recorded full-text availability');
END;
