-- trace: flow S4 step 4; BOUNDARIES.md Router; INVARIANTS V-6/C-9/C-11/RG-5.
-- A source version identifies one artifact for this topic and work. Capture
-- attribution is the original primary commit, retained when referenced again.
CREATE TABLE source_artifacts (
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  work_id TEXT NOT NULL REFERENCES works (work_id),
  source_version TEXT NOT NULL CHECK (length(source_version) > 0),
  content_hash TEXT NOT NULL REFERENCES artifacts (content_hash),
  invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (topic_id, work_id, source_version)
) STRICT;
CREATE TRIGGER source_artifacts_commit BEFORE INSERT ON source_artifacts
WHEN NOT EXISTS (
  SELECT 1 FROM invocations i JOIN operation_receipts o ON o.invocation_id = i.invocation_id
  WHERE i.invocation_id = NEW.invocation_id AND o.operation_id = NEW.recorded_by_operation_id
    AND i.topic_id = NEW.topic_id AND o.topic_id = NEW.topic_id
    AND i.kind IN ('research_pass', 'checkpoint') AND i.admission_context = 'contract/1'
    AND o.contract_revision = i.contract_revision)
BEGIN
  SELECT RAISE(ABORT, 'source artifact needs its contract-admitted primary commit');
END;
CREATE TRIGGER source_artifacts_topic BEFORE INSERT ON source_artifacts
WHEN NOT EXISTS (
  SELECT 1 FROM artifact_topics a WHERE a.topic_id = NEW.topic_id AND a.content_hash = NEW.content_hash)
  OR NOT EXISTS (
    SELECT 1 FROM record_work_links w JOIN retrieval_events r ON r.event_id = w.event_id
    WHERE w.work_id = NEW.work_id AND r.topic_id = NEW.topic_id)
BEGIN
  SELECT RAISE(ABORT, 'source artifact needs topic-authorized bytes and a topic-retrieved work');
END;
CREATE TRIGGER source_artifacts_immutable_u BEFORE UPDATE ON source_artifacts
BEGIN
  SELECT RAISE(ABORT, 'source artifact identity and capture provenance are immutable');
END;
CREATE TRIGGER source_artifacts_immutable_d BEFORE DELETE ON source_artifacts
BEGIN
  SELECT RAISE(ABORT, 'source artifact identity and capture provenance are retained');
END;
