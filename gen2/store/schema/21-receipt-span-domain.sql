-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-1/V-2;
-- verification-receipt.schema.json cited_spans; RFC 7493 section 2.3.
-- BEFORE admission establishes SQL 20's discriminator domain for all methods.
-- SQL 03 retains JSON validity, nonempty-array and exact column/JSON matching.
CREATE TRIGGER verification_receipts_span_domain
BEFORE INSERT ON verification_receipts
WHEN json_valid(NEW.receipt) AND json_valid(NEW.cited_spans)
BEGIN
  -- Whole-document uniqueness protects every SQL 03 binding, not just spans.
  -- json_tree keys are decoded; array indices are integers, not member names.
  SELECT RAISE(ABORT, 'receipt JSON has duplicate member names')
  WHERE EXISTS (SELECT 1 FROM json_tree(NEW.receipt)
    WHERE typeof(key) = 'text'
    GROUP BY parent, key COLLATE BINARY HAVING count(*) > 1);

  SELECT RAISE(ABORT, 'cited spans must match the receipt schema domain')
  WHERE CASE WHEN json_type(NEW.cited_spans) = 'array' THEN
    json_array_length(NEW.cited_spans) > 50
    OR EXISTS (SELECT 1 FROM json_each(NEW.cited_spans) s WHERE
      CASE WHEN s.type <> 'object' THEN 1 ELSE
        (SELECT count(*) FROM json_each(s.value)) <> 3
        OR coalesce(json_type(s.value, '$.start'), '') NOT IN ('integer', 'real')
        OR (json_type(s.value, '$.start') = 'real'
          AND json_extract(s.value, '$.start') <> round(json_extract(s.value, '$.start'), 0))
        OR json_extract(s.value, '$.start') < 0
        OR coalesce(json_type(s.value, '$.end'), '') NOT IN ('integer', 'real')
        OR (json_type(s.value, '$.end') = 'real'
          AND json_extract(s.value, '$.end') <> round(json_extract(s.value, '$.end'), 0))
        OR json_extract(s.value, '$.end') < 1
        OR CASE WHEN json_type(s.value, '$.locator') IS NOT 'object' THEN 1 ELSE
          (SELECT count(*) FROM json_each(s.value, '$.locator')) <> 2
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
      END)
    ELSE 0 END;
END;
