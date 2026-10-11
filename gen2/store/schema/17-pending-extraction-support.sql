-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-2/V-3.
-- Extraction declarations have no durable validation/input/output basis yet.
-- Retain them, but no declaration or validation_ref can authorize support.
-- The activation gate preserves SQL 03's diagnostics for missing/partial/
-- sampled receipts. SQL 03 still owns substantive checks and tier ordering.
-- SQL 03 binds load-bearing use to the claim and enforces sufficient tier.
-- The extraction slice replaces this fence only with durable basis consumption.
CREATE TRIGGER claims_accepted_support_pending_extraction
BEFORE UPDATE OF status ON claims
WHEN NEW.status = 'accepted_support'
  AND EXISTS (SELECT 1 FROM verification_receipts v
    WHERE v.claim_id = NEW.claim_id AND v.claim_revision = NEW.revision
      AND v.verdict = 'supports' AND v.use = 'load_bearing'
      AND v.extraction_method IN ('verifier_extraction', 'validated_extraction'))
  AND NOT EXISTS (SELECT 1 FROM verification_receipts c
    WHERE c.claim_id = NEW.claim_id AND c.claim_revision = NEW.revision
      AND c.verdict = 'supports' AND c.use = 'load_bearing'
      AND c.extraction_method = 'canonical_bytes')
BEGIN
  SELECT RAISE(ABORT, 'unbound extraction cannot authorize accepted support');
END;
