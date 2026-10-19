"""Paired predicate counterfactuals for the raw receipt discriminator domain."""
from .base import Mutation

SCOPE = "verification_receipts_span_domain_v4"
TESTS = tuple("test_store_span_domain." + cls + ".test_" for cls in
    ("SpanDDLTest", "ExtractionSpanDDLTest", "ValidatedSpanDDLTest"))
MUTATIONS, CONTROLS = [], {}


def change(name, old, new, killer=None):
    mid = "2D4B3DR1-" + name
    MUTATIONS.append(Mutation(mid, "2d-4b3d-repair-1", name,
        tuple(t + (killer or name) for t in TESTS), old=old, new=new, scope=SCOPE))
    CONTROLS[mid] = {"controls": [t + "domain_control" for t in TESTS],
        "why": "Separate unique-name page receipts at bibliographic tier remain admitted for every method; no domain predicate is bypassed in setup."}


change("duplicate", "HAVING count(*) > 1", "HAVING count(*) > 2")
change("array_max", "json_array_length(NEW.cited_spans) > 50", "json_array_length(NEW.cited_spans) > 51")
change("all_spans", "json_each(NEW.cited_spans) s WHERE", "json_each(NEW.cited_spans) s WHERE s.key = 0 AND")
change("span_object", "s.type <> 'object' THEN 1", "s.type <> 'object' THEN 0", "span_object_number")
change("span_members", "EXISTS (SELECT 1 FROM json_each(s.value) m\n          WHERE m.key COLLATE BINARY NOT IN ('start', 'end', 'locator'))", "0")
change("locator_object", "json_type(s.value, '$.locator') IS NOT 'object' THEN 1",
    "json_type(s.value, '$.locator') IS NOT 'object' THEN 0")
change("locator_members", "EXISTS (SELECT 1 FROM json_each(s.value, '$.locator') m\n            WHERE m.key COLLATE BINARY NOT IN ('kind', 'value'))", "0")
change("kind", "coalesce(json_extract(s.value, '$.locator.kind'), '') COLLATE BINARY\n            NOT IN ('page', 'section', 'table', 'figure', 'paragraph', 'line')", "0")
change("value_type", "json_type(s.value, '$.locator.value') IS NOT 'text'", "0")
change("value_min", "NOT BETWEEN 1 AND 500", "NOT BETWEEN 0 AND 500")
change("value_max", "NOT BETWEEN 1 AND 500", "NOT BETWEEN 1 AND 501")
change("value_characters", "substr(h, pos, 1) NOT IN ('8', '9', 'A', 'B')", "1 = 1", "schema_edges")
for key, minimum in (("start", 0), ("end", 1)):
    change(key + "_type", f"coalesce(json_type(s.value, '$.{key}'), '') NOT IN ('integer', 'real')", "0")
    change(key + "_integer", f"(name = '{key}' AND rtrim(digits, '0') <> '' AND exponent < scale - (length(digits) - length(rtrim(digits, '0'))))", "0")
    predicate = "(name = 'start' AND substr(n, 1, 1) = '-' AND rtrim(digits, '0') <> '')" if key == 'start' else "(name = 'end' AND (substr(n, 1, 1) = '-' OR rtrim(digits, '0') = ''))"
    change(key + "_min", predicate, "0")
