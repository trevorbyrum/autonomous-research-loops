-- trace: operator ruling 2026-10-14; DOSSIER 2d-4b3e2; INVARIANTS V-3/C-11.
-- Empty by default. The operator surface authenticates authority; DDL binds its retained audit.
CREATE TABLE extractor_registry_revisions (
  registry_version INTEGER PRIMARY KEY CHECK (registry_version BETWEEN 1 AND 9007199254740991),
  operator_id TEXT NOT NULL CHECK (length(operator_id) > 0),
  reason TEXT NOT NULL CHECK (length(reason) > 0),
  audit_event_id TEXT NOT NULL UNIQUE REFERENCES audit_events (audit_event_id),
  created_at TEXT NOT NULL
) STRICT;
CREATE TRIGGER extractor_registry_authority BEFORE INSERT ON extractor_registry_revisions
WHEN NOT EXISTS (
  SELECT 1 FROM audit_events a WHERE a.audit_event_id = NEW.audit_event_id
    AND a.kind = 'extractor_registry_registered' AND a.topic_id IS NULL
    AND a.invocation_id IS NULL AND a.operation_id IS NULL AND a.at = NEW.created_at
    AND json_extract(a.detail, '$.registry_version') = NEW.registry_version
    AND json_extract(a.detail, '$.operator_id') = NEW.operator_id
    AND json_extract(a.detail, '$.reason') = NEW.reason)
BEGIN
  SELECT RAISE(ABORT, 'extractor registry needs its operator audit');
END;
CREATE TRIGGER extractor_registry_order BEFORE INSERT ON extractor_registry_revisions
WHEN NEW.registry_version <= coalesce((SELECT max(registry_version) FROM extractor_registry_revisions), 0)
BEGIN
  SELECT RAISE(ABORT, 'extractor registry revisions must increase');
END;
CREATE TRIGGER extractor_registry_immutable_u BEFORE UPDATE ON extractor_registry_revisions
BEGIN
  SELECT RAISE(ABORT, 'extractor registry revisions are immutable');
END;
CREATE TRIGGER extractor_registry_immutable_d BEFORE DELETE ON extractor_registry_revisions
BEGIN
  SELECT RAISE(ABORT, 'extractor registry revisions are retained');
END;

-- trace: operator ruling 2026-10-14; DOSSIER 2d-4b3e2; INVARIANTS V-3/C-11.
CREATE TABLE extractor_tools (
  registry_version INTEGER NOT NULL REFERENCES extractor_registry_revisions (registry_version),
  extractor_identity TEXT NOT NULL CHECK (length(extractor_identity) BETWEEN 1 AND 100
    AND extractor_identity GLOB '[a-z]*' AND extractor_identity NOT GLOB '*[^a-z0-9._-]*'
    AND instr(CAST(extractor_identity AS BLOB), X'00') = 0),
  family TEXT NOT NULL CHECK (length(family) BETWEEN 1 AND 100
    AND family GLOB '[a-z]*' AND family NOT GLOB '*[^a-z0-9._-]*'
    AND instr(CAST(family AS BLOB), X'00') = 0),
  PRIMARY KEY (registry_version, extractor_identity)
) STRICT;
CREATE TRIGGER extractor_tools_authority BEFORE INSERT ON extractor_tools
WHEN NOT EXISTS (
  SELECT 1 FROM extractor_registry_revisions r JOIN audit_events a USING (audit_event_id),
    json_each(a.detail, '$.tools') t
  WHERE r.registry_version = NEW.registry_version
    AND json_extract(t.value, '$.extractor_identity') = NEW.extractor_identity
    AND json_extract(t.value, '$.family') = NEW.family)
BEGIN
  SELECT RAISE(ABORT, 'extractor tool needs its exact approved mapping');
END;
CREATE TRIGGER extractor_tools_immutable_u BEFORE UPDATE ON extractor_tools
BEGIN
  SELECT RAISE(ABORT, 'extractor tools are immutable');
END;
CREATE TRIGGER extractor_tools_immutable_d BEFORE DELETE ON extractor_tools
BEGIN
  SELECT RAISE(ABORT, 'extractor tools are retained');
END;

-- trace: operator ruling 2026-10-14; DOSSIER 2d-4b3e2; INVARIANTS V-3.
-- NULL keeps historical /1 readable; every new extraction pins an approved snapshot.
ALTER TABLE source_extractions ADD COLUMN extractor_registry_version INTEGER
  REFERENCES extractor_registry_revisions (registry_version);
CREATE TRIGGER source_extractions_registered_tool BEFORE INSERT ON source_extractions
WHEN NOT EXISTS (
  SELECT 1 FROM extractor_tools t WHERE t.registry_version = NEW.extractor_registry_version
    AND t.extractor_identity = NEW.extractor_identity)
BEGIN
  SELECT RAISE(ABORT, 'extraction needs an exact registered tool and registry revision');
END;
