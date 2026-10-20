-- trace: flow S4 steps 4/8/9; BOUNDARIES.md Router/Verifier; V-4/V-8.
-- Consumption binds attributed records, not scientific correctness. Enumerate
-- the four required kinds independently of the supplied object: no empty or
-- partial object, historical summary or adjudication can manufacture authority.
CREATE VIEW detailed_support_receipts AS
SELECT v.verification_receipt_id FROM verification_receipts v
WHERE json_extract(v.receipt, '$.receipt_version') = 'verification-receipt/2'
  AND json_type(v.receipt, '$.detailed_checks') = 'object'
  AND (SELECT count(*) FROM json_each(v.receipt, '$.detailed_checks')) = 4
  AND NOT EXISTS (WITH kinds(kind) AS (VALUES
    ('numeric_units'), ('denominators'), ('negation'), ('qualifications'))
    SELECT 1 FROM kinds k WHERE NOT EXISTS (
      SELECT 1 FROM detailed_check_records d JOIN source_artifacts s
        ON s.topic_id = v.topic_id AND s.work_id = v.work_id AND s.source_version = v.source_version
      WHERE d.check_id = json_extract(v.receipt, '$.detailed_checks.' || k.kind || '.record_id')
        AND d.topic_id = v.topic_id AND d.performer_invocation_id = v.verifier_invocation_id
        AND json_extract(d.assessment, '$.kind') = k.kind
        AND json_extract(d.assessment, '$.outcome') IN ('succeeded','failed','not_applicable')
        AND json_extract(d.assessment, '$.outcome') = json_extract(v.receipt, '$.detailed_checks.' || k.kind || '.outcome')
        AND json_extract(v.receipt, '$.checks.' || k.kind) = CASE json_extract(d.assessment, '$.outcome')
          WHEN 'succeeded' THEN 'checked_ok' WHEN 'failed' THEN 'checked_problem'
          ELSE json_extract(d.assessment, '$.outcome') END
        AND json_extract(d.assessment, '$.claim_id') = v.claim_id
        AND json_extract(d.assessment, '$.claim_revision') = v.claim_revision
        AND json_extract(d.assessment, '$.cited_spans') = json(v.cited_spans)
        AND json_extract(d.assessment, '$.work_id') = v.work_id
        AND json_extract(d.assessment, '$.source_version') = v.source_version
        AND s.content_hash = json_extract(d.assessment, '$.source_artifact_hash')
        AND json_extract(d.assessment, '$.examined_artifact_ref.content_hash') =
          CASE v.extraction_method WHEN 'canonical_bytes' THEN v.obtained_content_hash ELSE (
            SELECT json_extract(x.output_ref, '$.content_hash') FROM source_extractions x
            WHERE x.extraction_id = CASE v.extraction_method WHEN 'verifier_extraction'
              THEN json_extract(v.receipt, '$.extraction.extraction_id') ELSE (
                SELECT target_extraction_id FROM extraction_validations_v2
                WHERE validation_id = v.extraction_validation_ref) END) END))
  AND (v.extraction_method <> 'canonical_bytes' OR EXISTS (
    SELECT 1 FROM source_acquisition_content_tiers a
    WHERE a.topic_id = v.topic_id AND a.work_id = v.work_id AND a.source_version = v.source_version
      AND a.verifier_invocation_id = v.verifier_invocation_id AND a.content_hash = v.obtained_content_hash
      AND a.gateway_call_ref = json_extract(v.acquisition, '$.gateway_call_ref')
      AND a.retrieved_at = json_extract(v.acquisition, '$.retrieved_at')
      AND 'gateway:' || a.lane = json_extract(v.acquisition, '$.route')
      AND a.recorded_tier_rank >= CASE v.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END));

-- trace: flow S4 step 9; V-4/V-8; SQL 03 successor, claim-owned gates.
DROP TRIGGER claims_accepted_support_needs_receipt;
CREATE TRIGGER claims_accepted_support_detailed_receipt
BEFORE UPDATE OF status ON claims
WHEN NEW.status = 'accepted_support' AND NEW.load_bearing = 1 AND NOT EXISTS (
  SELECT 1 FROM verification_receipts v
  WHERE v.claim_id = NEW.claim_id AND v.claim_revision = NEW.revision AND v.verdict = 'supports'
    AND EXISTS (SELECT 1 FROM detailed_support_receipts d WHERE d.verification_receipt_id = v.verification_receipt_id)
    AND v.use = 'load_bearing'
    AND v.required_access_tier = NEW.required_access_tier
    AND (CASE v.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END)
     >= (CASE NEW.required_access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 WHEN 'reproduced' THEN 4 END)
    AND coalesce(json_extract(v.receipt, '$.checks.numeric_units'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
    AND coalesce(json_extract(v.receipt, '$.checks.denominators'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
    AND coalesce(json_extract(v.receipt, '$.checks.negation'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing')
    AND coalesce(json_extract(v.receipt, '$.checks.qualifications'), 'missing') NOT IN ('not_checked', 'unavailable', 'missing'))
BEGIN
  SELECT RAISE(ABORT, 'a load-bearing claim needs a supporting load-bearing-use verification receipt at its own required tier with every check performed (V-2, V-4, V-8)');
END;


-- trace: flow S4 step 9; V-3/V-4/V-8; SQL 34 successor, no receipt pooling.
DROP TRIGGER claims_accepted_support_bound_extraction;
CREATE TRIGGER claims_accepted_support_detailed_extraction
BEFORE UPDATE OF status ON claims
WHEN NEW.status = 'accepted_support'
  AND EXISTS (SELECT 1 FROM verification_receipts v
    WHERE v.claim_id = NEW.claim_id AND v.claim_revision = NEW.revision
      AND v.verdict = 'supports' AND v.use = 'load_bearing'
      AND v.extraction_method IN ('verifier_extraction', 'validated_extraction'))
  AND NOT EXISTS (SELECT 1 FROM verification_receipts c
    WHERE c.claim_id = NEW.claim_id AND c.claim_revision = NEW.revision
      AND c.verdict = 'supports' AND c.use = 'load_bearing'
      AND EXISTS (SELECT 1 FROM detailed_support_receipts d WHERE d.verification_receipt_id = c.verification_receipt_id)
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


-- trace: flow S4 steps 4/8/9; V-1/V-4/V-6/V-8; SQL 12 consumers.
-- Both the existing promotion trigger and operation-scoped final audit trigger
-- read this successor relation. Installation remains schema-only.
DROP VIEW governed_captures_blocked;
CREATE VIEW governed_captures_blocked AS
SELECT c.claim_id, c.revision FROM claims c
WHERE EXISTS (SELECT 1 FROM quote_checks q WHERE q.claim_id = c.claim_id AND q.claim_revision = c.revision AND q.match_result IS NOT NULL)
AND (EXISTS (SELECT 1 FROM quote_checks q WHERE q.claim_id = c.claim_id AND q.claim_revision = c.revision
       AND q.match_result IS NOT NULL AND q.quote_quarantined = 1)
  OR (c.load_bearing = 1 AND NOT EXISTS (
    SELECT 1 FROM verification_receipts r WHERE r.claim_id = c.claim_id AND r.claim_revision = c.revision
      AND r.verdict = 'supports' AND r.use = 'load_bearing'
      AND r.extraction_method = 'canonical_bytes'
      AND EXISTS (SELECT 1 FROM detailed_support_receipts d WHERE d.verification_receipt_id = r.verification_receipt_id)
      AND r.required_access_tier = c.required_access_tier
      AND (CASE r.access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END)
        >= CASE c.required_access_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 WHEN 'full_text' THEN 3 ELSE 4 END
      AND NOT EXISTS (SELECT 1 FROM governed_receipt_failures f WHERE f.verification_receipt_id = r.verification_receipt_id))));
