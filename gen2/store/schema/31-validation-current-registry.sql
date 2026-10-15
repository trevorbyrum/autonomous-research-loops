-- trace: operator ruling 2026-10-15; INVARIANTS V-3; DOSSIER 2d-4b3e2 part 2 slice 2.
-- New admission uses the current snapshot; retained validations keep their pin.
CREATE TRIGGER extraction_validations_v2_current_registry BEFORE INSERT ON extraction_validations_v2
WHEN NOT EXISTS (
  SELECT 1 FROM source_extractions y
  WHERE y.extraction_id = NEW.validator_extraction_id
    AND y.extractor_registry_version = (SELECT max(registry_version) FROM extractor_registry_revisions))
BEGIN
  SELECT RAISE(ABORT, 'validation /2 needs the current extractor registry revision');
END;
