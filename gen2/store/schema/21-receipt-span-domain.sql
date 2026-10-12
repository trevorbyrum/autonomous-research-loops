-- trace: flow S4 step 8; BOUNDARIES.md Router/Verifier; INVARIANTS V-1/V-2;
-- verification-receipt.schema.json cited_spans; RFC 7493 section 2.3.
-- Round-3 repair: complete decoded names and exact decimal offset semantics.
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

  -- Required/allowed sets for every receipt object consumed by SQL 03.
  -- Complete decoded names (including NUL suffixes) compare in BINARY.
  -- No schema member name contains NUL; locator VALUES may contain it.
  SELECT RAISE(ABORT, 'receipt JSON member sets must match the receipt schema')
  WHERE EXISTS (WITH shapes(parent_name, name, required, optional, nullable, absent) AS (VALUES
    (NULL, NULL, '["receipt_version","verification_receipt_id","topic_id","claim","source","cited_spans","obtained_content_hash","access_tier","requested_for","acquisition","extraction","producer_invocation_id","verifier_invocation_id","verifier_capability_id","quote_check_id","checks","adjudication","verdict","verified_at"]', '[]', 0, 0),
    ('', 'claim', '["claim_id","claim_revision"]', '[]', 0, 0),
    ('', 'source', '["work_id","source_version"]', '[]', 0, 0),
    ('', 'requested_for', '["use","required_access_tier"]', '[]', 0, 0),
    ('', 'acquisition', '["route","retrieved_at","gateway_call_ref","cache_reuse"]', '[]', 0, 0),
    ('', 'extraction', '["method","extractor","produced_by_invocation_id","validation_ref"]', '[]', 0, 0),
    ('', 'checks', '["exact_quote","numeric_units","denominators","negation","qualifications"]', '["tier0"]', 0, 0),
    ('checks', 'exact_quote', '["status","normalization_version","source_artifact_hash"]', '[]', 0, 0),
    ('checks', 'tier0', '["checker","checker_version","signal"]', '[]', 0, 1),
    ('', 'adjudication', '["adjudication_ref","resolved_at","resolution"]', '[]', 1, 0)
  ), tree AS (SELECT * FROM json_tree(NEW.receipt))
  SELECT 1 FROM shapes p LEFT JOIN tree o ON
    (p.name IS NULL AND o.parent IS NULL) OR (o.key = p.name COLLATE BINARY AND o.parent = (
      SELECT id FROM tree WHERE (p.parent_name = '' AND parent IS NULL)
        OR (key = p.parent_name COLLATE BINARY AND parent = (SELECT id FROM tree WHERE parent IS NULL))))
  WHERE CASE WHEN o.type = 'object' THEN
    EXISTS (SELECT 1 FROM json_each(p.required) r WHERE NOT EXISTS (
      SELECT 1 FROM tree m WHERE m.parent = o.id AND m.key = r.value COLLATE BINARY))
    OR EXISTS (SELECT 1 FROM tree m WHERE m.parent = o.id AND NOT EXISTS (
      SELECT 1 FROM json_each(p.required) r WHERE m.key = r.value COLLATE BINARY)
      AND NOT EXISTS (SELECT 1 FROM json_each(p.optional) r WHERE m.key = r.value COLLATE BINARY))
    ELSE NOT (p.nullable AND o.type IS 'null' OR p.absent AND o.id IS NULL) END);

  SELECT RAISE(ABORT, 'cited spans must match the receipt schema domain')
  WHERE CASE WHEN json_type(NEW.cited_spans) = 'array' THEN
    json_array_length(NEW.cited_spans) > 50
    OR EXISTS (SELECT 1 FROM json_each(NEW.cited_spans) s WHERE
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
      END)
    ELSE 0 END;
END;
