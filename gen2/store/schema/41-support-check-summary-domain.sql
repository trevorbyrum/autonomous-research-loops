-- trace: flow S4 steps 4/8; INVARIANTS V-8; DOSSIER 2d-4c part 4a repair 1.
-- Close the raw operand domain before SQL 40 branches on performed summaries.
-- SQL 03 still refuses unperformed load-bearing positives; SQL 37 projects /2
-- outcomes and binds every reference. Historical readback is unchanged.
CREATE TRIGGER verification_receipts_support_check_domain
BEFORE INSERT ON verification_receipts
WHEN NEW.use = 'load_bearing' AND NEW.verdict IN ('supports', 'partially_supports')
BEGIN
  SELECT RAISE(ABORT, 'load-bearing check summary domain')
  WHERE EXISTS (SELECT 1 FROM json_each('["numeric_units","denominators","negation","qualifications"]') k
    WHERE json_type(NEW.receipt, '$.checks.' || k.value) IS NOT 'text'
      OR coalesce(json_extract(NEW.receipt, '$.checks.' || k.value), '')
        NOT IN ('checked_ok', 'checked_problem', 'not_applicable', 'not_checked', 'unavailable'));
END;
