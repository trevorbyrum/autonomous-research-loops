CREATE VIEW recorded_nonblank_v1 AS
SELECT '*[^' || char(9) || '-' || char(13) || char(32,133,160,5760)
  || char(8192) || '-' || char(8202) || char(8232,8233,8239,8287,12288)
  || char(173,847,1564) || char(4447) || '-' || char(4448)
  || char(6068) || '-' || char(6069) || char(6155) || '-' || char(6159)
  || char(8203) || '-' || char(8207) || char(8234) || '-' || char(8238)
  || char(8288) || '-' || char(8303) || char(12644)
  || char(65024) || '-' || char(65039) || char(65279,65440)
  || char(65520) || '-' || char(65528) || char(113824) || '-' || char(113827)
  || char(119155) || '-' || char(119162) || char(917504) || '-' || char(921599)
  || ']*' AS pattern;

CREATE VIEW source_acquisition_content_tiers AS
    SELECT a.*, CASE
      WHEN o.coverage_state = 'searched_ok'
        AND json_extract(r.value, '$.kind') = 'full_text'
        AND json_type(r.value, '$.text') = 'text'
        AND json_extract(r.value, '$.text') GLOB (SELECT pattern FROM recorded_nonblank_v1) THEN 3
      WHEN json_type(r.value, '$.abstract') = 'text'
        AND json_extract(r.value, '$.abstract') GLOB (SELECT pattern FROM recorded_nonblank_v1) THEN 2
      ELSE 1 END AS recorded_tier_rank
    FROM source_acquisitions a JOIN search_observations o USING (observation_id)
    LEFT JOIN json_each(CASE WHEN json_valid(CAST(a.response_bytes AS TEXT))
      THEN CASE WHEN json_type(CAST(a.response_bytes AS TEXT), '$.records') = 'array'
        THEN CAST(a.response_bytes AS TEXT) ELSE '{}' END ELSE '{}' END, '$.records') r
      ON json_extract(CASE WHEN r.type = 'object' THEN r.value ELSE '{}' END, '$.identity') = a.provider_record_id;

-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-1/V-2/V-3/C-9/C-11.
-- extraction-validation/1 (DOSSIER 2d-4b3e1). Records grant no support authority.
CREATE TABLE source_extractions (
  extraction_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  work_id TEXT NOT NULL REFERENCES works (work_id),
  source_version TEXT NOT NULL,
  event_id TEXT NOT NULL REFERENCES retrieval_events (event_id),
  verifier_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  extractor_identity TEXT NOT NULL CHECK (length(extractor_identity) > 0),
  extractor_version TEXT NOT NULL CHECK (length(extractor_version) > 0),
  extracting_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  output_ref TEXT NOT NULL CHECK (json_valid(output_ref)),
  supported_tier TEXT NOT NULL CHECK (supported_tier IN ('bibliographic', 'abstract', 'full_text')),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  FOREIGN KEY (topic_id, work_id, source_version, event_id, verifier_invocation_id)
    REFERENCES source_acquisitions (topic_id, work_id, source_version, event_id, verifier_invocation_id)
) STRICT;
CREATE TRIGGER source_extractions_commit BEFORE INSERT ON source_extractions
WHEN NOT EXISTS (
  SELECT 1 FROM invocations i JOIN operation_receipts o ON o.invocation_id = i.invocation_id
  WHERE i.invocation_id = NEW.extracting_invocation_id AND i.topic_id = NEW.topic_id
    AND i.admission_context = 'contract/1' AND o.operation_id = NEW.recorded_by_operation_id
    AND o.topic_id = NEW.topic_id AND o.contract_revision = i.contract_revision)
BEGIN
  SELECT RAISE(ABORT, 'extraction needs its extracting invocation commit');
END;
CREATE TRIGGER source_extractions_artifact BEFORE INSERT ON source_extractions
WHEN NOT EXISTS (
  SELECT 1 FROM artifacts a JOIN artifact_topics t USING (content_hash)
  WHERE a.content_hash = json_extract(NEW.output_ref, '$.content_hash') AND t.topic_id = NEW.topic_id
    AND a.size_bytes = json_extract(NEW.output_ref, '$.size_bytes')
    AND a.media_type = json_extract(NEW.output_ref, '$.media_type'))
BEGIN
  SELECT RAISE(ABORT, 'extraction needs topic-authorized output metadata');
END;
CREATE TRIGGER source_extractions_tier BEFORE INSERT ON source_extractions
WHEN (CASE NEW.supported_tier WHEN 'bibliographic' THEN 1 WHEN 'abstract' THEN 2 ELSE 3 END) > coalesce((
  SELECT max(a.recorded_tier_rank) FROM source_acquisition_content_tiers a
  WHERE a.topic_id = NEW.topic_id AND a.work_id = NEW.work_id AND a.source_version = NEW.source_version
    AND a.event_id = NEW.event_id AND a.verifier_invocation_id = NEW.verifier_invocation_id), 3)
BEGIN
  SELECT RAISE(ABORT, 'extraction tier exceeds recorded content');
END;
CREATE TRIGGER source_extractions_immutable_u BEFORE UPDATE ON source_extractions
BEGIN
  SELECT RAISE(ABORT, 'extractions are immutable');
END;
CREATE TRIGGER source_extractions_immutable_d BEFORE DELETE ON source_extractions
BEGIN
  SELECT RAISE(ABORT, 'extractions are retained');
END;

-- trace: flow S4 step 8; operator ruling 2026-10-12; INVARIANTS V-3/C-9/C-11.
-- Semantic agreement is attributed assessment, never store-proven correctness.
CREATE TABLE extraction_validations (
  validation_id TEXT PRIMARY KEY,
  target_extraction_id TEXT NOT NULL REFERENCES source_extractions (extraction_id),
  validator_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  validator_extraction_id TEXT NOT NULL REFERENCES source_extractions (extraction_id),
  method TEXT NOT NULL CHECK (method IN ('independent_extraction', 'same_extractor_replay')),
  policy_version INTEGER NOT NULL CHECK (policy_version = 1),
  outcome TEXT NOT NULL CHECK (outcome IN ('succeeded', 'failed')),
  comparison TEXT NOT NULL CHECK (comparison IN ('byte_equal', 'semantic_agreement', 'disagreement')),
  comparison_evidence_ref TEXT NOT NULL CHECK (json_valid(comparison_evidence_ref)),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  CHECK ((outcome = 'succeeded') = (comparison IN ('byte_equal', 'semantic_agreement'))),
  CHECK (method <> 'same_extractor_replay' OR comparison <> 'semantic_agreement')
) STRICT;
CREATE TRIGGER extraction_validations_binding BEFORE INSERT ON extraction_validations
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
CREATE TRIGGER extraction_validations_method BEFORE INSERT ON extraction_validations
WHEN EXISTS (
  SELECT 1 FROM source_extractions x JOIN source_extractions y ON y.extraction_id = NEW.validator_extraction_id
  WHERE x.extraction_id = NEW.target_extraction_id AND (
    (NEW.method = 'independent_extraction' AND y.extractor_identity = x.extractor_identity)
    OR (NEW.method = 'same_extractor_replay' AND (y.extractor_identity <> x.extractor_identity OR y.extractor_version <> x.extractor_version))
    OR (NEW.comparison = 'byte_equal' AND json_extract(y.output_ref, '$.content_hash') <> json_extract(x.output_ref, '$.content_hash'))))
BEGIN
  SELECT RAISE(ABORT, 'validation method or byte comparison disagrees with extraction records');
END;
CREATE TRIGGER extraction_validations_artifact BEFORE INSERT ON extraction_validations
WHEN NOT EXISTS (
  SELECT 1 FROM source_extractions x JOIN artifact_topics t ON t.topic_id = x.topic_id
  JOIN artifacts a USING (content_hash)
  WHERE x.extraction_id = NEW.target_extraction_id AND a.content_hash = json_extract(NEW.comparison_evidence_ref, '$.content_hash')
    AND a.size_bytes = json_extract(NEW.comparison_evidence_ref, '$.size_bytes')
    AND a.media_type = json_extract(NEW.comparison_evidence_ref, '$.media_type'))
BEGIN
  SELECT RAISE(ABORT, 'validation needs topic-authorized comparison evidence');
END;
CREATE TRIGGER extraction_validations_immutable_u BEFORE UPDATE ON extraction_validations
BEGIN
  SELECT RAISE(ABORT, 'validations are immutable');
END;
CREATE TRIGGER extraction_validations_immutable_d BEFORE DELETE ON extraction_validations
BEGIN
  SELECT RAISE(ABORT, 'validations are retained');
END;

-- trace: operator ruling 2026-10-12; INVARIANTS V-3; DOSSIER 2d-4b3e1.
-- Predicate exposed for readback/testing only; SQL 17 and all consumers stay fenced.
CREATE VIEW extraction_validation_results AS
SELECT *, (method = 'independent_extraction' AND policy_version = 1 AND outcome = 'succeeded') AS method_succeeded
FROM extraction_validations;
