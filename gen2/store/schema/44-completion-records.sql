-- trace: flow S6/S7, INVARIANTS G-1/G-2; 6b2' PR 1.
-- Primary-owned judgments about completion work, one row per record. The
-- Router decides which subject each kind may name; this part keeps the
-- shape pairings and the role binding. Newest per subject is current.
CREATE TABLE completion_records (
  record_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  kind TEXT NOT NULL CHECK (kind IN ('counterevidence_search', 'competing_explanation',
                                     'sufficiency_review', 'verification_adjudication')),
  contract_revision INTEGER NOT NULL,
  subject_ref TEXT NOT NULL CHECK (length(subject_ref) > 0),
  subject_revision INTEGER CHECK (subject_revision >= 0),
  subject_hash TEXT CHECK (subject_hash IS NULL OR (subject_hash GLOB 'sha256:*' AND length(subject_hash) = 71)),
  assessment TEXT NOT NULL CHECK (json_valid(assessment) AND json_type(assessment) = 'object'),
  evidence_refs TEXT NOT NULL CHECK (json_valid(evidence_refs) AND json_type(evidence_refs) = 'array' AND json_array_length(evidence_refs) > 0),
  actor_kind TEXT NOT NULL CHECK (actor_kind = 'primary'),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  FOREIGN KEY (topic_id, contract_revision) REFERENCES contract_revisions (topic_id, revision),
  CHECK ((subject_revision IS NOT NULL) = (kind != 'competing_explanation')),
  CHECK ((subject_hash IS NOT NULL) = (kind = 'sufficiency_review')),
  CHECK (kind != 'sufficiency_review' OR subject_ref IS topic_id)
) STRICT;

-- Role separation, as obligation_assessments_bound: the committing
-- invocation and its operation belong to this topic and this pin.
CREATE TRIGGER completion_records_bound BEFORE INSERT ON completion_records
WHEN NOT EXISTS (
  SELECT 1 FROM invocations i JOIN operation_receipts o ON o.invocation_id = i.invocation_id
  WHERE i.invocation_id = NEW.invocation_id AND o.operation_id = NEW.recorded_by_operation_id
    AND i.topic_id = NEW.topic_id AND o.topic_id = NEW.topic_id
    AND i.kind IN ('research_pass', 'checkpoint') AND i.admission_context = 'contract/1'
    AND i.contract_revision = NEW.contract_revision AND o.contract_revision = NEW.contract_revision)
BEGIN
  SELECT RAISE(ABORT, 'completion record needs its primary commit and exact contract pin');
END;
CREATE TRIGGER completion_records_immutable_u BEFORE UPDATE ON completion_records
BEGIN
  SELECT RAISE(ABORT, 'completion records are append-only');
END;
CREATE TRIGGER completion_records_immutable_d BEFORE DELETE ON completion_records
BEGIN
  SELECT RAISE(ABORT, 'completion records are retained');
END;
