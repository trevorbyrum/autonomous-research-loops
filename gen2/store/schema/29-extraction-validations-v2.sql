-- trace: flow S4 step 8; operator ruling 2026-10-12; INVARIANTS V-3/C-9/C-11.
-- extraction-validation/2; no receipt or support consumer in this slice.
-- Semantic agreement is attributed assessment, never store-proven correctness.
CREATE TABLE extraction_validations_v2 (
  validation_id TEXT PRIMARY KEY,
  target_extraction_id TEXT NOT NULL REFERENCES source_extractions (extraction_id),
  validator_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  validator_extraction_id TEXT NOT NULL REFERENCES source_extractions (extraction_id),
  method TEXT NOT NULL CHECK (method IN ('independent_extraction', 'same_family_replay')),
  policy_version INTEGER NOT NULL CHECK (policy_version = 2),
  outcome TEXT NOT NULL CHECK (outcome IN ('succeeded', 'failed')),
  comparison TEXT NOT NULL CHECK (comparison IN ('byte_equal', 'semantic_agreement', 'disagreement')),
  comparison_evidence_ref TEXT NOT NULL CHECK (json_valid(comparison_evidence_ref)),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  CHECK ((outcome = 'succeeded') = (comparison IN ('byte_equal', 'semantic_agreement'))),
  CHECK (method <> 'same_family_replay' OR comparison <> 'semantic_agreement')
) STRICT;
-- trace: operator ruling 2026-10-14; INVARIANTS V-3; both historical NULL pins refuse.
CREATE TRIGGER extraction_validations_v2_registered BEFORE INSERT ON extraction_validations_v2
WHEN NOT EXISTS (
  SELECT 1 FROM source_extractions x JOIN extractor_tools tx
    ON tx.registry_version = x.extractor_registry_version AND tx.extractor_identity = x.extractor_identity
  JOIN source_extractions y ON y.extraction_id = NEW.validator_extraction_id
  JOIN extractor_tools ty
    ON ty.registry_version = y.extractor_registry_version AND ty.extractor_identity = y.extractor_identity
  WHERE x.extraction_id = NEW.target_extraction_id)
BEGIN
  SELECT RAISE(ABORT, 'validation /2 needs both pinned registered tools');
END;
CREATE TRIGGER extraction_validations_v2_binding BEFORE INSERT ON extraction_validations_v2
WHEN NOT EXISTS (
  SELECT 1 FROM source_extractions x JOIN source_extractions y ON y.extraction_id = NEW.validator_extraction_id
  JOIN invocations v ON v.invocation_id = NEW.validator_invocation_id
  JOIN source_artifacts s ON s.topic_id = x.topic_id AND s.work_id = x.work_id AND s.source_version = x.source_version
  JOIN operation_receipts o ON o.operation_id = NEW.recorded_by_operation_id
  WHERE x.extraction_id = NEW.target_extraction_id
    AND y.topic_id = x.topic_id AND y.work_id = x.work_id AND y.source_version = x.source_version
    AND y.event_id = x.event_id AND y.verifier_invocation_id = x.verifier_invocation_id
    AND y.extracting_invocation_id = v.invocation_id AND x.verifier_invocation_id = v.invocation_id
    AND v.invocation_id <> x.extracting_invocation_id AND v.invocation_id <> s.invocation_id
    AND v.topic_id = x.topic_id AND v.kind = 'verification' AND v.admission_context = 'contract/1'
    AND v.parent_invocation_id IS NULL AND o.invocation_id = v.invocation_id
    AND o.topic_id = x.topic_id AND o.contract_revision = v.contract_revision)
BEGIN
  SELECT RAISE(ABORT, 'validation needs independent validator and exact acquisition lineage');
END;
CREATE TRIGGER extraction_validations_v2_method BEFORE INSERT ON extraction_validations_v2
WHEN EXISTS (
  SELECT 1 FROM source_extractions x JOIN source_extractions y ON y.extraction_id = NEW.validator_extraction_id
  JOIN extractor_tools tx ON tx.registry_version = x.extractor_registry_version AND tx.extractor_identity = x.extractor_identity
  JOIN extractor_tools ty ON ty.registry_version = y.extractor_registry_version AND ty.extractor_identity = y.extractor_identity
  WHERE x.extraction_id = NEW.target_extraction_id AND (
    (NEW.method = 'independent_extraction' AND ty.family = tx.family)
    OR (NEW.method = 'same_family_replay' AND ty.family <> tx.family)
    OR (NEW.comparison = 'byte_equal' AND json_extract(y.output_ref, '$.content_hash') <> json_extract(x.output_ref, '$.content_hash'))))
BEGIN
  SELECT RAISE(ABORT, 'validation method or byte comparison disagrees with extraction records');
END;
CREATE TRIGGER extraction_validations_v2_artifact BEFORE INSERT ON extraction_validations_v2
WHEN NOT EXISTS (
  SELECT 1 FROM source_extractions x JOIN artifact_topics t ON t.topic_id = x.topic_id
  JOIN artifacts a USING (content_hash)
  WHERE x.extraction_id = NEW.target_extraction_id AND a.content_hash = json_extract(NEW.comparison_evidence_ref, '$.content_hash')
    AND a.size_bytes = json_extract(NEW.comparison_evidence_ref, '$.size_bytes')
    AND a.media_type = json_extract(NEW.comparison_evidence_ref, '$.media_type'))
BEGIN
  SELECT RAISE(ABORT, 'validation needs topic-authorized comparison evidence');
END;
CREATE TRIGGER extraction_validations_v2_immutable_u BEFORE UPDATE ON extraction_validations_v2
BEGIN
  SELECT RAISE(ABORT, 'validations are immutable');
END;
CREATE TRIGGER extraction_validations_v2_immutable_d BEFORE DELETE ON extraction_validations_v2
BEGIN
  SELECT RAISE(ABORT, 'validations are retained');
END;

-- trace: operator ruling 2026-10-12; INVARIANTS V-3; DOSSIER 2d-4b3e2 continuation part 2.
-- Predicate exposed for readback/testing only; SQL 17 and all consumers stay fenced.
CREATE VIEW extraction_validation_results_v2 AS
SELECT *, (method = 'independent_extraction' AND policy_version = 2 AND outcome = 'succeeded') AS method_succeeded
FROM extraction_validations_v2;
