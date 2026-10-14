-- trace: INVARIANTS C-13/H-5/E-2; DOSSIER 2d-4b3e1-json2-repair-1 F1.
-- SQL 24 binds the bytes to the descriptor and failed shape. Bind the
-- descriptor back to this row's bytes as well, including both fields NULL.
CREATE TRIGGER search_observations_retained_representation
BEFORE INSERT ON search_observations
WHEN (json_type(NEW.request, '$.retained_request') IS NOT NULL)
  != (NEW.request_bytes IS NOT NULL)
BEGIN
  SELECT RAISE(ABORT, 'retained descriptor requires its own same-row bytes');
END;
