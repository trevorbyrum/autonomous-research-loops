-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-1/V-2.
-- Ceiling comes from the consumed record, never the receipt's tier label.
-- SQL 14/15 and the immutable source key imply content-hash/topic equality.
-- No matching acquisition leaves SQL 15's refusal diagnostic in charge.
CREATE TRIGGER verification_receipts_canonical_content_tier
BEFORE INSERT ON verification_receipts
WHEN NEW.extraction_method = 'canonical_bytes'
  AND (CASE NEW.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2
       WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END) > coalesce((
    SELECT max(CASE
      WHEN o.coverage_state = 'searched_ok'
        AND json_extract(r.value, '$.kind') = 'full_text'
        AND json_type(r.value, '$.text') = 'text'
        AND length(trim(json_extract(r.value, '$.text'), char(9,10,13,32))) > 0 THEN 3
      WHEN json_type(r.value, '$.abstract') = 'text'
        AND length(trim(json_extract(r.value, '$.abstract'), char(9,10,13,32))) > 0 THEN 2
      ELSE 1 END)
    FROM source_acquisitions a JOIN search_observations o USING (observation_id)
    LEFT JOIN json_each(CASE WHEN json_valid(CAST(a.response_bytes AS TEXT))
      THEN CASE WHEN json_type(CAST(a.response_bytes AS TEXT), '$.records') = 'array'
        THEN CAST(a.response_bytes AS TEXT) ELSE '{}' END ELSE '{}' END, '$.records') r
      ON json_extract(CASE WHEN r.type = 'object' THEN r.value ELSE '{}' END, '$.identity') = a.provider_record_id
    WHERE a.work_id = NEW.work_id
      AND a.source_version = NEW.source_version
      AND a.verifier_invocation_id = NEW.verifier_invocation_id
      AND a.acquired_by_invocation_id = NEW.extraction_invocation_id
      AND a.gateway_call_ref = json_extract(NEW.acquisition, '$.gateway_call_ref')
      AND a.retrieved_at = json_extract(NEW.acquisition, '$.retrieved_at')
      AND 'gateway:' || a.lane = json_extract(NEW.acquisition, '$.route')), 4)
BEGIN
  SELECT RAISE(ABORT, 'canonical receipt tier exceeds recorded content');
END;
