-- trace: flow S4 steps 4/8/9, §6.7; BOUNDARIES.md Router/Verifier; V-1, V-4, V-6.
-- (claim_id, revision) is the capture identity. Each cited span has its own
-- check. These views share the exact relationship across admission and use;
-- historical receipts are retained, but cannot certify a later governed capture.
CREATE VIEW governed_receipt_checks AS
SELECT v.verification_receipt_id, q.check_id, q.span_start, q.span_end
FROM verification_receipts v JOIN quote_checks q
  ON q.claim_id = v.claim_id AND q.claim_revision = v.claim_revision
WHERE q.match_result IS NOT NULL
  AND q.topic_id = v.topic_id AND q.work_id = v.work_id AND q.source_version = v.source_version
  AND q.source_artifact_hash IS json_extract(v.receipt, '$.checks.exact_quote.source_artifact_hash')
  AND json_extract(q.match_result, '$.artifact_hash') IS v.obtained_content_hash
  AND q.normalization_version IS json_extract(v.receipt, '$.checks.exact_quote.normalization_version')
  AND q.exact_match IS json_extract(v.receipt, '$.checks.exact_quote.status')
  AND (v.verdict NOT IN ('supports', 'partially_supports') OR (q.exact_match = 'matched' AND q.quote_quarantined = 0));

CREATE VIEW governed_receipt_failures AS
SELECT v.verification_receipt_id FROM verification_receipts v
WHERE EXISTS (SELECT 1 FROM quote_checks q WHERE q.claim_id = v.claim_id AND q.claim_revision = v.claim_revision AND q.match_result IS NOT NULL)
AND (
  (v.verdict IN ('supports', 'partially_supports') AND EXISTS (
    SELECT 1 FROM quote_checks q WHERE q.claim_id = v.claim_id AND q.claim_revision = v.claim_revision
      AND q.match_result IS NOT NULL AND q.quote_quarantined = 1))
  OR NOT EXISTS (SELECT 1 FROM governed_receipt_checks b, json_each(v.cited_spans) s
    WHERE b.verification_receipt_id = v.verification_receipt_id AND b.check_id = v.quote_check_id
      AND b.span_start IS json_extract(s.value, '$.start') AND b.span_end IS json_extract(s.value, '$.end'))
  OR EXISTS (SELECT 1 FROM json_each(v.cited_spans) s WHERE NOT EXISTS (
    SELECT 1 FROM governed_receipt_checks b WHERE b.verification_receipt_id = v.verification_receipt_id
      AND b.span_start IS json_extract(s.value, '$.start') AND b.span_end IS json_extract(s.value, '$.end'))));

CREATE VIEW governed_captures_blocked AS
SELECT c.claim_id, c.revision FROM claims c
WHERE EXISTS (SELECT 1 FROM quote_checks q WHERE q.claim_id = c.claim_id AND q.claim_revision = c.revision AND q.match_result IS NOT NULL)
AND (EXISTS (SELECT 1 FROM quote_checks q WHERE q.claim_id = c.claim_id AND q.claim_revision = c.revision
       AND q.match_result IS NOT NULL AND q.quote_quarantined = 1)
  OR (c.load_bearing = 1 AND NOT EXISTS (
    SELECT 1 FROM verification_receipts v WHERE v.claim_id = c.claim_id AND v.claim_revision = c.revision
      AND v.verdict = 'supports' AND v.use = 'load_bearing'
      AND NOT EXISTS (SELECT 1 FROM governed_receipt_failures f WHERE f.verification_receipt_id = v.verification_receipt_id))));

CREATE TRIGGER verification_receipts_capture_binding AFTER INSERT ON verification_receipts
WHEN EXISTS (SELECT 1 FROM governed_receipt_failures f WHERE f.verification_receipt_id = NEW.verification_receipt_id)
BEGIN
  SELECT RAISE(ABORT, 'receipt must bind every span to its governed capture (V-1, V-6)');
END;

-- Re-fence persisted support when this ordered part is installed, too.
UPDATE claims SET status = 'quarantined'
WHERE status = 'accepted_support' AND EXISTS (
  SELECT 1 FROM governed_captures_blocked b WHERE b.claim_id = claims.claim_id AND b.revision = claims.revision);

CREATE TRIGGER claims_accepted_support_needs_capture BEFORE UPDATE OF status ON claims
WHEN NEW.status = 'accepted_support' AND EXISTS (
  SELECT 1 FROM governed_captures_blocked b WHERE b.claim_id = NEW.claim_id AND b.revision = NEW.revision)
BEGIN
  SELECT RAISE(ABORT, 'governed capture cannot supply accepted support (V-1, V-6)');
END;

-- Checks arriving after a receipt or promotion cannot leave false support live.
CREATE TRIGGER quote_checks_refence_capture AFTER INSERT ON quote_checks
WHEN NEW.match_result IS NOT NULL
BEGIN
  UPDATE claims SET status = 'quarantined' WHERE claim_id = NEW.claim_id AND revision = NEW.claim_revision
    AND status = 'accepted_support' AND EXISTS (
      SELECT 1 FROM governed_captures_blocked b WHERE b.claim_id = NEW.claim_id AND b.revision = NEW.claim_revision);
END;
