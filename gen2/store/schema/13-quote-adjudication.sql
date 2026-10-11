-- trace: flow S4 step 4 / §6.7; BOUNDARIES.md Router/Verifier; V-5, V-6.
-- Receipt adjudication cannot waive a byte mismatch, regardless of verdict or
-- omitted/substituted check reference. Near matches have exact_match=mismatch.
-- Matched-byte NLI alarms and non-quote V-8 adjudication retain their authority.
CREATE TRIGGER verification_receipts_no_byte_adjudication BEFORE INSERT ON verification_receipts
WHEN json_type(NEW.receipt, '$.adjudication') IS 'object' AND (
  json_extract(NEW.receipt, '$.checks.exact_quote.status') = 'mismatch'
  OR EXISTS (SELECT 1 FROM quote_checks q WHERE q.claim_id = NEW.claim_id
    AND q.claim_revision = NEW.claim_revision
    AND (q.exact_match = 'mismatch' OR (q.quote_quarantined = 1 AND q.nli_signal != 'alarm'))
    AND (q.match_result IS NOT NULL OR q.check_id = NEW.quote_check_id)))
BEGIN
  SELECT RAISE(ABORT, 'byte-mismatch quarantine cannot be adjudicated (V-6)');
END;

CREATE TRIGGER operator_decisions_no_byte_clearance BEFORE INSERT ON operator_decisions
WHEN NEW.kind = 'hold_clearance' AND NEW.disposition = 'approved' AND EXISTS (
  SELECT 1 FROM holds h JOIN quote_checks q ON h.subject_ref = 'quote:' || q.check_id
  WHERE h.hold_id = NEW.subject_ref
    AND (q.exact_match = 'mismatch' OR (q.quote_quarantined = 1 AND q.nli_signal != 'alarm')))
BEGIN
  SELECT RAISE(ABORT, 'byte-mismatch quarantine cannot be adjudicated (V-6)');
END;

-- A direct operation/reconciliation update has no more authority than a
-- decision. The original capture and its attention record remain retained.
CREATE TRIGGER holds_no_byte_clearance BEFORE UPDATE OF cleared_at ON holds
WHEN OLD.cleared_at IS NULL AND NEW.cleared_at IS NOT NULL AND EXISTS (
  SELECT 1 FROM quote_checks q WHERE OLD.subject_ref = 'quote:' || q.check_id
    AND (q.exact_match = 'mismatch' OR (q.quote_quarantined = 1 AND q.nli_signal != 'alarm')))
BEGIN
  SELECT RAISE(ABORT, 'byte-mismatch quarantine cannot be adjudicated (V-6)');
END;
