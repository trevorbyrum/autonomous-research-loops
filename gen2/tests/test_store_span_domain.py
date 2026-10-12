"""Raw span-domain pairs use fresh savepoints and literal JSON, for all methods."""
import json
import sqlite3
from unittest.mock import patch

from gen2.tests.test_store_table_availability import TableDDLTest, PAGE

DOMAIN = "cited spans must match the receipt schema domain"
DUPLICATE = "receipt JSON has duplicate member names"


def span(**changes):
    return {**PAGE, **changes}


def locator(**changes):
    return span(locator={**PAGE["locator"], **changes})


BAD = {
    "array_max": [[PAGE] * 51],
    "span_object": [["page"], [0], [None], [True], [[]]],
    "span_members": [[span(extra=0)]],
    "start_type": [[span(start=v)] for v in (None, True, "0", [], {})]
        + [[{k: v for k, v in span(other=0).items() if k != "start"}]],
    "start_integer": [[span(start=0.5)]],
    "start_min": [[span(start=-1)]],
    "end_type": [[span(end=v)] for v in (None, True, "1", [], {})]
        + [[{k: v for k, v in span(other=0).items() if k != "end"}]],
    "end_integer": [[span(end=1.5)]],
    "end_min": [[span(end=0)]],
    "locator_object": [[span(locator=v)] for v in (None, True, "page", 1, [])]
        + [[{k: v for k, v in span(other=0).items() if k != "locator"}]],
    "locator_members": [[locator(extra=0)]],
    "kind": [[locator(kind=v)] for v in (None, True, 1, [], {}, "TABLE", "Page", "unknown")]
        + [[span(locator={"other": "page", "value": "2"})], [PAGE, locator(kind="TABLE")]],
    "value_type": [[locator(value=v)] for v in (None, True, 1, [], {})]
        + [[span(locator={"kind": "page", "other": "2"})]],
    "value_min": [[locator(value="")]],
    "value_max": [[locator(value="x" * 501)], [locator(value="\0" * 501)], [locator(value="字" * 501)]],
}
DUPLICATES = (
    '[{"start":5,"end":9,"locator":{"kind":"page","kind":"table","value":"2"}}]',
    '[{"start":5,"end":9,"locator":{"kind":"page","value":"2"},"locator":{"kind":"table","value":"T"}}]',
    '[{"start":5,"start":0,"end":9,"locator":{"kind":"page","value":"2"}}]',
    '[{"start":5,"end":9,"end":10,"locator":{"kind":"page","value":"2"}}]',
    '[{"start":5,"end":9,"locator":{"kind":"page","value":"2","value":"T"}}]',
    r'[{"start":5,"end":9,"locator":{"kind":"page","ki\u006ed":"table","value":"2"}}]',
)


class SpanDDLTest(TableDDLTest):
    # Inherited table tests run in their own module; these isolate the domain.
    test_table_control = test_non_table_control = test_lower_table_control = None
    test_insufficient = test_mixed = test_cannot_assess = test_lineage = None
    test_diagnostics = test_tier_diagnostic = test_recorded_evidence = None
    test_bea_table_identity = test_readback_conflict_rollback = None

    def setUp(self):
        super().setUp()
        self.acquired({"identity": "rec-1"})

    def insert(self, spans, transform=lambda doc: doc):
        raw = spans if isinstance(spans, str) else json.dumps(spans)
        original = self.x

        def inject(sql, *params):
            if sql.startswith("INSERT INTO verification_receipts ("):
                cols = sql.split("(", 1)[1].split(")", 1)[0].split(", ")
                row = dict(zip(cols, params))
                doc = json.loads(row["receipt"])
                doc["cited_spans"] = "__RAW_SPANS__"
                row["receipt"] = transform(json.dumps(doc).replace('"__RAW_SPANS__"', raw))
                row["cited_spans"] = raw
                params = tuple(row[col] for col in cols)
            return original(sql, *params)

        with patch.object(self, "x", side_effect=inject):
            self.table_receipt(spans=(PAGE,))

    def pair(self, bad, control=(PAGE,), diagnostic=DOMAIN, transform=lambda doc: doc):
        self.x("SAVEPOINT domain_pair")
        try:
            before = self.rows("SELECT * FROM verification_receipts")
            with self.assertRaisesRegex(sqlite3.IntegrityError, diagnostic):
                self.insert(bad, transform)
            self.assertEqual(self.rows("SELECT * FROM verification_receipts"), before)
            self.insert(control)
            self.assertEqual(json.loads(self.rows("SELECT cited_spans FROM verification_receipts")[0][0]), list(control))
            self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        finally:
            self.x("ROLLBACK TO domain_pair")
            self.x("RELEASE domain_pair")

    def cases(self, name):
        for bad in BAD[name]:
            with self.subTest(predicate=name, bad=bad):
                self.pair(bad)

    def test_array_max(self): self.cases("array_max")
    def test_span_object(self): self.cases("span_object")
    def test_span_object_number(self): self.pair([0])
    def test_all_spans(self): self.pair([PAGE, locator(kind="TABLE")], (PAGE, PAGE))
    def test_span_members(self): self.cases("span_members")
    def test_start_type(self): self.cases("start_type")
    def test_start_integer(self): self.cases("start_integer")
    def test_start_min(self): self.cases("start_min")
    def test_end_type(self): self.cases("end_type")
    def test_end_integer(self): self.cases("end_integer")
    def test_end_min(self): self.cases("end_min")
    def test_locator_object(self): self.cases("locator_object")
    def test_locator_members(self): self.cases("locator_members")
    def test_kind(self): self.cases("kind")
    def test_value_type(self): self.cases("value_type")
    def test_value_min(self): self.cases("value_min")
    def test_value_max(self): self.cases("value_max")

    def test_duplicate(self):
        for raw in DUPLICATES:
            with self.subTest(raw=raw): self.pair(raw, diagnostic=DUPLICATE)
        for transform in (
            lambda d: d[:-1] + ',"access_tier":"full_text"}',
            lambda d: d[:-1] + ',"cited_spans":[{"start":0,"end":1,"locator":{"kind":"table","value":"T"}}]}',
            lambda d: d.replace('"claim_revision": 1', '"claim_revision":1,"claim_revision":2'),
            lambda d: d.replace('"route": "gateway:crossref"', '"route":"gateway:crossref","route":"gateway:core"'),
            lambda d: d.replace('"status": "not_applicable"', '"status":"not_applicable","status":"matched"'),
        ):
            self.pair([PAGE], diagnostic=DUPLICATE, transform=transform)

    def test_domain_control(self):
        self.insert([PAGE])
        self.assertEqual(self.rows("SELECT access_tier, extraction_method FROM verification_receipts"), [("bibliographic", self.METHOD)])

    def test_schema_edges(self):
        controls = [[locator(kind=k)] for k in ("page", "section", "figure", "paragraph", "line")]
        controls += [[PAGE] * 50, [span(start=0.0, end=1.0)], [span(start=2**53 + 1, end=2**63)],
            [span(start=9, end=1)], [locator(value=" ")], [locator(value="\0")],
            [locator(value="字" * 500)], [locator(value="a\0" + "字" * 498)],
            [{"locator": {"value": "2", "kind": "page"}, "end": 9, "start": 5}]]
        for control in controls:
            with self.subTest(control=control): self.pair([locator(kind="TABLE")], control)
        # Escaped valid names are interpreted identically, rather than blacklisted.
        self.insert(r'[{"start":0e0,"end":1e0,"loc\u0061tor":{"ki\u006ed":"p\u0061ge","value":"2"}}]')
        self.assertEqual(json.loads(self.rows("SELECT cited_spans FROM verification_receipts")[0][0]), [span(start=0, end=1)])


class ExtractionSpanDDLTest(SpanDDLTest):
    METHOD = "verifier_extraction"


class ValidatedSpanDDLTest(SpanDDLTest):
    METHOD = "validated_extraction"
