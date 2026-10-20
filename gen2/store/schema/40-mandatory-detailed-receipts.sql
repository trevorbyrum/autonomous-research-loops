-- trace: flow S4 steps 4/8; INVARIANTS V-8; DOSSIER 2d-4c part 4a.
-- Current load-bearing support consumes records; SQL 37 binds every reference.
-- Performed failures also need records, including adjudicated support.
-- Historical rows remain readable. Promotion consumers follow in part 4b.
CREATE TRIGGER verification_receipts_require_detailed_checks
AFTER INSERT ON verification_receipts
WHEN NEW.use = 'load_bearing' AND NEW.verdict IN ('supports', 'partially_supports')
BEGIN
  SELECT RAISE(ABORT, 'load-bearing support requires detailed check records')
  WHERE EXISTS (SELECT 1 FROM json_each('["numeric_units","denominators","negation","qualifications"]') k
    WHERE json_extract(NEW.receipt, '$.checks.' || k.value) IN ('checked_ok', 'checked_problem', 'not_applicable')
      AND json_type(NEW.receipt, '$.detailed_checks.' || k.value || '.record_id') IS NOT 'text');
END;
