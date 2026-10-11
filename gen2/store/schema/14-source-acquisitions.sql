-- V-1/V-3; flow S4 step 8; Router-owned trusted capture authentication.
-- SQL binds recorded rows/size; Router authenticates and hashes retained octets.
CREATE TABLE source_acquisitions (
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  work_id TEXT NOT NULL REFERENCES works (work_id),
  source_version TEXT NOT NULL,
  content_hash TEXT NOT NULL REFERENCES artifacts (content_hash),
  observation_id TEXT NOT NULL REFERENCES search_observations (observation_id),
  event_id TEXT NOT NULL REFERENCES retrieval_events (event_id),
  gateway_call_ref TEXT NOT NULL,
  acquired_by_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  attempt INTEGER NOT NULL CHECK (attempt BETWEEN 1 AND 9007199254740991),
  lane TEXT NOT NULL,
  request_type TEXT NOT NULL,
  provider_record_id TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  verifier_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  request_identity TEXT NOT NULL,
  request_bytes BLOB NOT NULL,
  response_bytes BLOB NOT NULL,
  admitted_at TEXT NOT NULL,
  PRIMARY KEY (topic_id, work_id, source_version, event_id, verifier_invocation_id),
  FOREIGN KEY (topic_id, work_id, source_version)
    REFERENCES source_artifacts (topic_id, work_id, source_version)
) STRICT;
CREATE TRIGGER source_acquisitions_binding BEFORE INSERT ON source_acquisitions
WHEN NOT EXISTS (
  SELECT 1 FROM source_artifacts s JOIN artifacts a ON a.content_hash = s.content_hash
  JOIN retrieval_events e ON e.event_id = NEW.event_id
  JOIN record_work_links w ON w.event_id = e.event_id
  JOIN search_observations o ON o.observation_id = e.observation_id
  WHERE s.topic_id = NEW.topic_id AND s.work_id = NEW.work_id AND s.source_version = NEW.source_version
    AND s.content_hash = NEW.content_hash AND w.work_id = NEW.work_id
    AND e.topic_id = NEW.topic_id AND o.topic_id = NEW.topic_id
    AND o.observation_id = NEW.observation_id AND o.invocation_id = NEW.acquired_by_invocation_id
    AND o.gateway_call_ref = NEW.gateway_call_ref AND o.attempt = NEW.attempt
    AND o.lane = NEW.lane AND json_extract(o.request, '$.request.request_type') = NEW.request_type
    AND o.coverage_state IN ('searched_ok', 'metadata_only') AND o.completeness IN ('complete', 'partial')
    AND e.provider_record_id = NEW.provider_record_id AND e.captured_at = NEW.retrieved_at
    AND o.request_identity = NEW.request_identity AND o.request = CAST(NEW.request_bytes AS TEXT)
    AND a.media_type = 'application/json' AND a.size_bytes = length(NEW.response_bytes))
BEGIN
  SELECT RAISE(ABORT, 'acquisition must bind recorded source, retrieval and capture operands');
END;
CREATE TRIGGER source_acquisitions_verifier BEFORE INSERT ON source_acquisitions
WHEN NOT EXISTS (
  SELECT 1 FROM invocations v WHERE v.invocation_id = NEW.verifier_invocation_id
    AND v.topic_id = NEW.topic_id AND v.kind = 'verification' AND v.admission_context = 'contract/1')
BEGIN
  SELECT RAISE(ABORT, 'acquisition needs a contract-admitted verifier of its topic');
END;
CREATE TRIGGER source_acquisitions_immutable_u BEFORE UPDATE ON source_acquisitions
BEGIN
  SELECT RAISE(ABORT, 'acquisition operands and attribution are immutable');
END;
CREATE TRIGGER source_acquisitions_immutable_d BEFORE DELETE ON source_acquisitions
BEGIN
  SELECT RAISE(ABORT, 'acquisition operands and attribution are retained');
END;
