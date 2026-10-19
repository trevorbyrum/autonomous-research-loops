-- trace: 2d-4c cap repair-1 B1; verification-receipt span schema string values.
-- Numeric locators are not offsets. Digit-string labels retain their meaning.
CREATE TRIGGER claim_source_links_locator_string BEFORE INSERT ON claim_source_links
BEGIN
  SELECT RAISE(ABORT, 'span locator value must be a string')
  WHERE EXISTS (SELECT 1 FROM json_each(NEW.spans) s WHERE
    CASE WHEN s.type = 'object' THEN
      json_type(s.value, '$.locator.value') IS NOT 'text'
    ELSE 0 END);
END;
