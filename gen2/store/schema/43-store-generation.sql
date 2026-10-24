-- trace: flow S5/S8; boundaries: Evidence accounting; invariants: C-8/C-11;
-- DOSSIER D part 3: coarse committed-write-transaction generation, never scientific evidence.
CREATE TABLE store_generation (
  singleton TEXT PRIMARY KEY CHECK (singleton = 'store'),
  epoch TEXT CHECK (length(epoch) = 32 AND epoch NOT GLOB '*[^0-9a-f]*'),
  generation INTEGER NOT NULL CHECK (generation BETWEEN 0 AND 9007199254740991)
) STRICT;

-- Absence means (NULL, 0). Only a writer may establish that initial state.
CREATE TRIGGER store_generation_no_insert BEFORE INSERT ON store_generation
WHEN NEW.singleton IS NOT 'store' OR NEW.epoch IS NOT NULL OR NEW.generation IS NOT 0
  OR EXISTS (SELECT 1 FROM store_generation)
BEGIN
  SELECT RAISE(ABORT, 'store generation singleton cannot be inserted');
END;

CREATE TRIGGER store_generation_no_delete BEFORE DELETE ON store_generation
BEGIN
  SELECT RAISE(ABORT, 'store generation singleton cannot be deleted');
END;

-- Explicit offline maintenance rotates the epoch, never the counter.
-- Ordinary opening and reading perform no initialization or renewal.
CREATE TRIGGER store_generation_step BEFORE UPDATE ON store_generation
WHEN NEW.singleton IS NOT OLD.singleton OR NOT (
  (NEW.epoch IS OLD.epoch AND NEW.generation IS OLD.generation + 1
    AND OLD.generation < 9007199254740991)
  OR (NEW.epoch IS NOT NULL AND NEW.epoch IS NOT OLD.epoch AND NEW.generation IS OLD.generation))
BEGIN
  SELECT RAISE(ABORT, 'store generation must advance once or renew epoch; exhaustion refuses writes');
END;
