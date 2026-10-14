-- trace: INVARIANTS C-13/H-5/E-2; DOSSIER 2d-4b3e1-json2; operator 2026-10-13.
-- A refused logical request still counts as one failed attempt. Its original
-- octets are retained wholly; Router and Store establish byte SHA-256 truth.
-- F2: opaque descriptors assert no type/page; existing typed descriptors bind too.
ALTER TABLE search_observations ADD COLUMN request_bytes BLOB;
ALTER TABLE search_observations ADD COLUMN request_bytes_hash TEXT;

CREATE TRIGGER search_observations_retained_request
BEFORE INSERT ON search_observations
WHEN (NEW.request_bytes IS NULL) != (NEW.request_bytes_hash IS NULL)
  OR (NEW.request_bytes IS NOT NULL AND (
    NEW.request_bytes_hash IS NOT NEW.request_identity
    OR json_extract(NEW.request, '$.retained_request.bytes_hash') IS NOT NEW.request_bytes_hash
    OR json_extract(NEW.request, '$.retained_request.reason') IS NOT 'member_name_domain'
    OR json_remove(NEW.request, '$.request.request_type', '$.retained_request.bytes_hash', '$.retained_request.reason')
      NOT IN ('{"request":{},"retained_request":{}}', '{"retained_request":{}}')
    OR (json_type(NEW.request, '$.request') IS NOT NULL AND NOT COALESCE(
      json_extract(NEW.request, '$.request.request_type') IN ('find', 'resolve', 'enrich', 'fetch', 'data'), 0))
    OR NEW.coverage_state != 'unknown' OR NEW.completeness != 'unobserved'
    OR NEW.error_class IS NOT 'payload_invalid' OR NEW.page_outcome != 'failed'))
BEGIN
  SELECT RAISE(ABORT, 'retained request must bind exact-byte identity and failed attempt');
END;
