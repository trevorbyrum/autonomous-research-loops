-- trace: flow S4 steps 4/8; INVARIANTS V-4/V-8/C-9/C-11;
-- DOSSIER 2d-4c part 1; operator ruling 2026-10-17.
-- Relationships only. No receipt or promotion consumer; no semantic certification.
CREATE TABLE detailed_check_records (
  check_id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES queue_entries (topic_id),
  performer_invocation_id TEXT NOT NULL REFERENCES invocations (invocation_id),
  assessment TEXT NOT NULL CHECK (json_valid(assessment)),
  evidence_ref TEXT CHECK (evidence_ref IS NULL OR json_valid(evidence_ref)),
  recorded_by_operation_id TEXT NOT NULL REFERENCES operation_receipts (operation_id),
  created_at TEXT NOT NULL
) STRICT;
CREATE TRIGGER detailed_check_records_domain BEFORE INSERT ON detailed_check_records
BEGIN
  SELECT RAISE(ABORT, 'detailed check report domain')
  WHERE json_type(NEW.assessment) IS NOT 'object'
    OR (SELECT count(*) FROM json_each(NEW.assessment)) <> 14
    OR EXISTS (WITH fields(name, kind) AS (VALUES
      ('claim_id','text'), ('claim_revision','integer'), ('work_id','text'), ('source_version','text'),
      ('source_artifact_hash','text'), ('examined_artifact_ref','object'), ('cited_spans','array'),
      ('context_spans','array'), ('kind','text'), ('outcome','text'), ('method','text'),
      ('assessment','text'), ('context_examined','text'), ('applicability_reason','text'))
      SELECT 1 FROM fields WHERE json_type(NEW.assessment, '$.' || name) IS NOT kind)
    OR json_extract(NEW.assessment, '$.claim_revision') NOT BETWEEN 1 AND 9007199254740991
    OR json_extract(NEW.assessment, '$.method') <> 'attributed-assessment/1'
    OR json_extract(NEW.assessment, '$.kind') NOT IN ('numeric_units','denominators','negation','qualifications')
    OR json_extract(NEW.assessment, '$.outcome') NOT IN ('succeeded','failed','not_applicable','not_checked','unavailable')
    OR json_array_length(NEW.assessment, '$.cited_spans') NOT BETWEEN 1 AND 50
    OR json_array_length(NEW.assessment, '$.context_spans') > 50;
  SELECT RAISE(ABORT, 'performed detailed check needs assessment, context and evidence; exemption needs reason')
  WHERE (json_extract(NEW.assessment, '$.outcome') IN ('succeeded','failed','not_applicable') AND
    (NEW.evidence_ref IS NULL OR NOT (json_extract(NEW.assessment, '$.assessment') GLOB (SELECT pattern FROM recorded_nonblank_v1))
      OR NOT (json_extract(NEW.assessment, '$.context_examined') GLOB (SELECT pattern FROM recorded_nonblank_v1))))
    OR (json_extract(NEW.assessment, '$.outcome') = 'not_applicable'
      AND NOT (json_extract(NEW.assessment, '$.applicability_reason') GLOB (SELECT pattern FROM recorded_nonblank_v1)));
END;
CREATE TRIGGER detailed_check_records_binding BEFORE INSERT ON detailed_check_records
WHEN NOT EXISTS (
  SELECT 1 FROM claims c JOIN source_artifacts s ON s.topic_id = c.topic_id
  JOIN invocations v ON v.invocation_id = NEW.performer_invocation_id
  JOIN operation_receipts o ON o.operation_id = NEW.recorded_by_operation_id
  WHERE c.claim_id = json_extract(NEW.assessment, '$.claim_id')
    AND c.revision = json_extract(NEW.assessment, '$.claim_revision') AND c.topic_id = NEW.topic_id
    AND s.work_id = json_extract(NEW.assessment, '$.work_id')
    AND s.source_version = json_extract(NEW.assessment, '$.source_version')
    AND s.content_hash = json_extract(NEW.assessment, '$.source_artifact_hash')
    AND v.topic_id = c.topic_id AND v.kind = 'verification' AND v.admission_context = 'contract/1'
    AND v.parent_invocation_id IS NULL AND v.invocation_id <> c.producer_invocation_id
    AND v.invocation_id <> s.invocation_id AND o.invocation_id = v.invocation_id
    AND o.topic_id = c.topic_id AND o.contract_revision = v.contract_revision)
BEGIN
  SELECT RAISE(ABORT, 'detailed check needs exact claim/source and independent committing verifier');
END;
CREATE TRIGGER detailed_check_records_artifacts BEFORE INSERT ON detailed_check_records
BEGIN
  SELECT RAISE(ABORT, 'detailed check needs topic-authorized artifact metadata')
  WHERE EXISTS (WITH refs(ref) AS (
    SELECT json_extract(NEW.assessment, '$.examined_artifact_ref')
    UNION ALL SELECT NEW.evidence_ref WHERE NEW.evidence_ref IS NOT NULL)
    SELECT 1 FROM refs WHERE json_type(ref) IS NOT 'object'
      OR (SELECT count(*) FROM json_each(ref)) <> 3
      OR json_type(ref, '$.content_hash') IS NOT 'text'
      OR json_type(ref, '$.size_bytes') IS NOT 'integer'
      OR json_type(ref, '$.media_type') IS NOT 'text'
      OR NOT EXISTS (SELECT 1 FROM artifacts a JOIN artifact_topics t USING (content_hash)
        WHERE t.topic_id = NEW.topic_id AND a.content_hash = json_extract(ref, '$.content_hash')
          AND a.size_bytes = json_extract(ref, '$.size_bytes') AND a.media_type = json_extract(ref, '$.media_type')));
END;
-- trace: SQL 21 exact decimal/locator domain, applied to citation and context separately.
CREATE TRIGGER detailed_check_records_spans BEFORE INSERT ON detailed_check_records
BEGIN
  SELECT RAISE(ABORT, 'detailed check span domain')
  WHERE EXISTS (SELECT 1 FROM (SELECT value, type FROM json_each(NEW.assessment, '$.cited_spans')
    UNION ALL SELECT value, type FROM json_each(NEW.assessment, '$.context_spans')) s WHERE
      CASE WHEN s.type <> 'object' THEN 1 ELSE
        EXISTS (SELECT 1 FROM json_each(s.value) m
          WHERE m.key COLLATE BINARY NOT IN ('start', 'end', 'locator'))
        OR coalesce(json_type(s.value, '$.start'), '') NOT IN ('integer', 'real')
        OR coalesce(json_type(s.value, '$.end'), '') NOT IN ('integer', 'real')
        -- -> preserves the numeral, unlike json_extract's INTEGER/REAL.
        -- A decimal is integral iff its exponent covers its fractional
        -- digits after trailing zeroes. Zero is handled before that test.
        OR EXISTS (WITH numbers(name, n) AS (VALUES
            ('start', lower(s.value -> '$.start')), ('end', lower(s.value -> '$.end'))
          ), parts AS (SELECT name, n,
            CASE WHEN instr(n, 'e') > 0 THEN substr(n, 1, instr(n, 'e') - 1) ELSE n END AS mantissa,
            CASE WHEN instr(n, 'e') > 0 THEN CAST(substr(n, instr(n, 'e') + 1) AS INTEGER) ELSE 0 END AS exponent
            FROM numbers
          ), decimals AS (SELECT *, replace(replace(mantissa, '-', ''), '.', '') AS digits,
            CASE WHEN instr(mantissa, '.') > 0 THEN length(mantissa) - instr(mantissa, '.') ELSE 0 END AS scale
            FROM parts
          ) SELECT 1 FROM decimals WHERE
            (name = 'start' AND rtrim(digits, '0') <> '' AND exponent < scale - (length(digits) - length(rtrim(digits, '0'))))
            OR (name = 'end' AND rtrim(digits, '0') <> '' AND exponent < scale - (length(digits) - length(rtrim(digits, '0'))))
            OR (name = 'start' AND substr(n, 1, 1) = '-' AND rtrim(digits, '0') <> '')
            OR (name = 'end' AND (substr(n, 1, 1) = '-' OR rtrim(digits, '0') = '')))
        OR CASE WHEN json_type(s.value, '$.locator') IS NOT 'object' THEN 1 ELSE
          EXISTS (SELECT 1 FROM json_each(s.value, '$.locator') m
            WHERE m.key COLLATE BINARY NOT IN ('kind', 'value'))
          OR coalesce(json_extract(s.value, '$.locator.kind'), '') COLLATE BINARY
            NOT IN ('page', 'section', 'table', 'figure', 'paragraph', 'line')
          OR json_type(s.value, '$.locator.value') IS NOT 'text'
          -- Count UTF-8 leading bytes, including NUL, as Unicode characters.
          OR (WITH RECURSIVE bytes(h, pos) AS (
            SELECT hex(CAST(json_extract(s.value, '$.locator.value') AS BLOB)), 1
            UNION ALL SELECT h, pos + 2 FROM bytes WHERE pos < length(h)
          ) SELECT count(*) FROM bytes WHERE pos <= length(h)
            AND substr(h, pos, 1) NOT IN ('8', '9', 'A', 'B')) NOT BETWEEN 1 AND 500
        END
      END);
END;
CREATE TRIGGER detailed_check_records_immutable_u BEFORE UPDATE ON detailed_check_records
BEGIN
  SELECT RAISE(ABORT, 'detailed checks are immutable');
END;
CREATE TRIGGER detailed_check_records_immutable_d BEFORE DELETE ON detailed_check_records
BEGIN
  SELECT RAISE(ABORT, 'detailed checks are retained');
END;
