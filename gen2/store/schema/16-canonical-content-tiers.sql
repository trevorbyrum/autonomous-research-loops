-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-2.
-- recorded-nonblank/1+ucd17.0.0: at least one character outside White_Space
-- (PropList.txt) and Default_Ignorable_Code_Point (DerivedCoreProperties.txt).
-- https://www.unicode.org/Public/17.0.0/ucd/ ; complete sets, merged ranges.
-- GLOB ranges compare Unicode code points; formatting is preserved in text.
CREATE VIEW recorded_nonblank_v1 AS
SELECT '*[^' || char(9) || '-' || char(13) || char(32,133,160,5760)
  || char(8192) || '-' || char(8202) || char(8232,8233,8239,8287,12288)
  || char(173,847,1564) || char(4447) || '-' || char(4448)
  || char(6068) || '-' || char(6069) || char(6155) || '-' || char(6159)
  || char(8203) || '-' || char(8207) || char(8234) || '-' || char(8238)
  || char(8288) || '-' || char(8303) || char(12644)
  || char(65024) || '-' || char(65039) || char(65279,65440)
  || char(65520) || '-' || char(65528) || char(113824) || '-' || char(113827)
  || char(119155) || '-' || char(119162) || char(917504) || '-' || char(921599)
  || ']*' AS pattern;

-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-1/V-2.
-- One recorded-content rule for canonical and extraction receipt consumers.
CREATE VIEW source_acquisition_content_tiers AS
    SELECT a.*, CASE
      WHEN o.coverage_state = 'searched_ok'
        AND json_extract(r.value, '$.kind') = 'full_text'
        AND json_type(r.value, '$.text') = 'text'
        AND json_extract(r.value, '$.text') GLOB (SELECT pattern FROM recorded_nonblank_v1) THEN 3
      WHEN json_type(r.value, '$.abstract') = 'text'
        AND json_extract(r.value, '$.abstract') GLOB (SELECT pattern FROM recorded_nonblank_v1) THEN 2
      ELSE 1 END AS recorded_tier_rank
    FROM source_acquisitions a JOIN search_observations o USING (observation_id)
    LEFT JOIN json_each(CASE WHEN json_valid(CAST(a.response_bytes AS TEXT))
      THEN CASE WHEN json_type(CAST(a.response_bytes AS TEXT), '$.records') = 'array'
        THEN CAST(a.response_bytes AS TEXT) ELSE '{}' END ELSE '{}' END, '$.records') r
      ON json_extract(CASE WHEN r.type = 'object' THEN r.value ELSE '{}' END, '$.identity') = a.provider_record_id;

-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-1/V-2.
-- SQL 14/15 and the immutable source key imply content-hash/topic equality.
-- No matching acquisition leaves SQL 15's refusal diagnostic in charge.
CREATE TRIGGER verification_receipts_canonical_content_tier
BEFORE INSERT ON verification_receipts
WHEN NEW.extraction_method = 'canonical_bytes'
  AND (CASE NEW.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2
       WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END) > coalesce((
    SELECT max(a.recorded_tier_rank) FROM source_acquisition_content_tiers a
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
