-- trace: flow S5/S8; boundaries: Evidence accounting; invariants: C-8/C-11;
-- DOSSIER D part 3: coarse committed-row generation, never scientific evidence.
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

-- Mechanical batch: every capture relation, every row event, no filtering.
CREATE TRIGGER capture_generation_queue_entries_insert AFTER INSERT ON queue_entries
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_queue_entries_update AFTER UPDATE ON queue_entries
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_queue_entries_delete AFTER DELETE ON queue_entries
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_contract_revisions_insert AFTER INSERT ON contract_revisions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_contract_revisions_update AFTER UPDATE ON contract_revisions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_contract_revisions_delete AFTER DELETE ON contract_revisions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_facets_insert AFTER INSERT ON facets
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_facets_update AFTER UPDATE ON facets
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_facets_delete AFTER DELETE ON facets
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_obligations_insert AFTER INSERT ON obligations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_obligations_update AFTER UPDATE ON obligations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_obligations_delete AFTER DELETE ON obligations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_invocations_insert AFTER INSERT ON invocations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_invocations_update AFTER UPDATE ON invocations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_invocations_delete AFTER DELETE ON invocations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_leases_insert AFTER INSERT ON leases
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_leases_update AFTER UPDATE ON leases
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_leases_delete AFTER DELETE ON leases
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_search_observations_insert AFTER INSERT ON search_observations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_search_observations_update AFTER UPDATE ON search_observations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_search_observations_delete AFTER DELETE ON search_observations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_retrieval_events_insert AFTER INSERT ON retrieval_events
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_retrieval_events_update AFTER UPDATE ON retrieval_events
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_retrieval_events_delete AFTER DELETE ON retrieval_events
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_screening_assessments_insert AFTER INSERT ON screening_assessments
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_screening_assessments_update AFTER UPDATE ON screening_assessments
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_screening_assessments_delete AFTER DELETE ON screening_assessments
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_claims_insert AFTER INSERT ON claims
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_claims_update AFTER UPDATE ON claims
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_claims_delete AFTER DELETE ON claims
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_semantic_assessments_insert AFTER INSERT ON semantic_assessments
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_semantic_assessments_update AFTER UPDATE ON semantic_assessments
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_semantic_assessments_delete AFTER DELETE ON semantic_assessments
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_lifecycle_insert AFTER INSERT ON source_lifecycle
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_lifecycle_update AFTER UPDATE ON source_lifecycle
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_lifecycle_delete AFTER DELETE ON source_lifecycle
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_registry_dispositions_insert AFTER INSERT ON registry_dispositions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_registry_dispositions_update AFTER UPDATE ON registry_dispositions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_registry_dispositions_delete AFTER DELETE ON registry_dispositions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_branch_windows_insert AFTER INSERT ON branch_windows
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_branch_windows_update AFTER UPDATE ON branch_windows
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_branch_windows_delete AFTER DELETE ON branch_windows
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_obligation_assessments_insert AFTER INSERT ON obligation_assessments
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_obligation_assessments_update AFTER UPDATE ON obligation_assessments
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_obligation_assessments_delete AFTER DELETE ON obligation_assessments
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_amendment_impacts_insert AFTER INSERT ON amendment_impacts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_amendment_impacts_update AFTER UPDATE ON amendment_impacts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_amendment_impacts_delete AFTER DELETE ON amendment_impacts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_claim_source_links_insert AFTER INSERT ON claim_source_links
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_claim_source_links_update AFTER UPDATE ON claim_source_links
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_claim_source_links_delete AFTER DELETE ON claim_source_links
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_verification_receipts_insert AFTER INSERT ON verification_receipts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_verification_receipts_update AFTER UPDATE ON verification_receipts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_verification_receipts_delete AFTER DELETE ON verification_receipts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_artifacts_insert AFTER INSERT ON source_artifacts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_artifacts_update AFTER UPDATE ON source_artifacts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_artifacts_delete AFTER DELETE ON source_artifacts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_acquisitions_insert AFTER INSERT ON source_acquisitions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_acquisitions_update AFTER UPDATE ON source_acquisitions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_acquisitions_delete AFTER DELETE ON source_acquisitions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_extractions_insert AFTER INSERT ON source_extractions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_extractions_update AFTER UPDATE ON source_extractions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_extractions_delete AFTER DELETE ON source_extractions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_detailed_check_records_insert AFTER INSERT ON detailed_check_records
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_detailed_check_records_update AFTER UPDATE ON detailed_check_records
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_detailed_check_records_delete AFTER DELETE ON detailed_check_records
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_holds_insert AFTER INSERT ON holds
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_holds_update AFTER UPDATE ON holds
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_holds_delete AFTER DELETE ON holds
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_operator_decisions_insert AFTER INSERT ON operator_decisions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_operator_decisions_update AFTER UPDATE ON operator_decisions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_operator_decisions_delete AFTER DELETE ON operator_decisions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_artifact_topics_insert AFTER INSERT ON artifact_topics
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_artifact_topics_update AFTER UPDATE ON artifact_topics
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_artifact_topics_delete AFTER DELETE ON artifact_topics
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_dossiers_insert AFTER INSERT ON dossiers
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_dossiers_update AFTER UPDATE ON dossiers
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_dossiers_delete AFTER DELETE ON dossiers
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_operation_receipts_insert AFTER INSERT ON operation_receipts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_operation_receipts_update AFTER UPDATE ON operation_receipts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_operation_receipts_delete AFTER DELETE ON operation_receipts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_record_work_links_insert AFTER INSERT ON record_work_links
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_record_work_links_update AFTER UPDATE ON record_work_links
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_record_work_links_delete AFTER DELETE ON record_work_links
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_works_insert AFTER INSERT ON works
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_works_update AFTER UPDATE ON works
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_works_delete AFTER DELETE ON works
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_lineage_insert AFTER INSERT ON source_lineage
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_lineage_update AFTER UPDATE ON source_lineage
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_source_lineage_delete AFTER DELETE ON source_lineage
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_quote_checks_insert AFTER INSERT ON quote_checks
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_quote_checks_update AFTER UPDATE ON quote_checks
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_quote_checks_delete AFTER DELETE ON quote_checks
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extraction_validations_insert AFTER INSERT ON extraction_validations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extraction_validations_update AFTER UPDATE ON extraction_validations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extraction_validations_delete AFTER DELETE ON extraction_validations
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extraction_validations_v2_insert AFTER INSERT ON extraction_validations_v2
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extraction_validations_v2_update AFTER UPDATE ON extraction_validations_v2
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extraction_validations_v2_delete AFTER DELETE ON extraction_validations_v2
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_artifacts_insert AFTER INSERT ON artifacts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_artifacts_update AFTER UPDATE ON artifacts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_artifacts_delete AFTER DELETE ON artifacts
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extractor_registry_revisions_insert AFTER INSERT ON extractor_registry_revisions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extractor_registry_revisions_update AFTER UPDATE ON extractor_registry_revisions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extractor_registry_revisions_delete AFTER DELETE ON extractor_registry_revisions
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extractor_tools_insert AFTER INSERT ON extractor_tools
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extractor_tools_update AFTER UPDATE ON extractor_tools
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_extractor_tools_delete AFTER DELETE ON extractor_tools
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_audit_events_insert AFTER INSERT ON audit_events
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_audit_events_update AFTER UPDATE ON audit_events
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;

CREATE TRIGGER capture_generation_audit_events_delete AFTER DELETE ON audit_events
BEGIN
  INSERT INTO store_generation SELECT 'store', NULL, 0
    WHERE NOT EXISTS (SELECT 1 FROM store_generation);
  UPDATE store_generation SET generation = generation + 1 WHERE singleton = 'store';
  SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT, 'missing store generation singleton') END;
END;
