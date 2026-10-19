"""Literal name/numeral pairs: SQL validates the text before lossy lookup."""
import json
import sqlite3

from gen2.tests import test_store_span_domain as spans

MEMBERS = "receipt JSON member sets must match the receipt schema"


def numeric(name, numeral, late=False):
    raw = json.dumps(spans.PAGE).replace('"' + name + '": ' + str(spans.PAGE[name]),
        '"' + name + '": ' + numeral)
    return '[' + (json.dumps(spans.PAGE) + ',' if late else '') + raw + ']'


def rename(doc, path, suffix="\0suffix"):
    # Decode names with Python too; do not use a JSON path to select a member.
    doc = json.loads(doc)
    *parents, key = path.split('.')
    node = doc
    for part in parents: node = node[part]
    node[key + suffix] = node.pop(key)
    return json.dumps(doc)


class ExactSpanDDLTest(spans.SpanDDLTest):
    def raw_pair(self, bad, control, diagnostic=spans.DOMAIN, transform=lambda d: d):
        self.x("SAVEPOINT exact_pair")
        try:
            before = self.rows("SELECT * FROM verification_receipts")
            with self.assertRaisesRegex(sqlite3.IntegrityError, diagnostic): self.insert(bad, transform, historical=True)
            self.assertEqual(self.rows("SELECT * FROM verification_receipts"), before)
            self.insert(control)
            receipt, retained = self.rows("SELECT receipt,cited_spans FROM verification_receipts")[0]
            self.assertEqual(json.loads(receipt)["cited_spans"], json.loads(retained))
            self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        finally:
            self.x("ROLLBACK TO exact_pair")
            self.x("RELEASE exact_pair")

    def test_receipt_aliases(self):
        paths = ("cited_spans", "claim", "claim.claim_id", "source", "source.source_version",
            "requested_for", "requested_for.use", "acquisition", "acquisition.route", "extraction",
            "extraction.method", "checks", "checks.exact_quote", "checks.exact_quote.status",
            "checks.numeric_units", "adjudication", "verdict", "access_tier")
        for path in paths:
            with self.subTest(path=path):
                self.raw_pair([spans.PAGE], [spans.PAGE], MEMBERS, lambda d: rename(d, path))

    def test_split_receipt(self):
        page = json.dumps([spans.PAGE])
        table = '[{"start":0,"end":5,"locator":{"kind":"table","value":"T"}}]'
        self.raw_pair(page, page, MEMBERS,
            lambda d: d.replace('"cited_spans": ' + page,
                '"cited_spans\\u0000suffix": ' + page + ',"cited_spans":' + table))

    def test_span_names(self):
        for key in ("start", "end", "locator"):
            with self.subTest(key=key): self.raw_pair(json.dumps([spans.PAGE]).replace(
                '"' + key + '":', '"' + key + '\\u0000suffix":'), [spans.PAGE])

    def test_locator_names(self):
        for key in ("kind", "value"):
            with self.subTest(key=key): self.raw_pair(json.dumps([spans.PAGE]).replace(
                '"' + key + '":', '"' + key + '\\u0000suffix":'), [spans.PAGE])

    def test_required_members(self):
        def remove(d):
            d = json.loads(d)
            del d["extraction"]["extractor"]
            return json.dumps(d)
        self.raw_pair([spans.PAGE], [spans.PAGE], MEMBERS, remove)

    def test_extra_members(self):
        self.raw_pair([spans.PAGE], [spans.PAGE], MEMBERS, lambda d: d[:-1] + ',"extension":0}')
        # Distinct Unicode names stay distinct, but neither is a schema member.
        self.raw_pair([spans.PAGE], [spans.PAGE], MEMBERS, lambda d: d[:-1] + ',"é":1,"e\\u0301":2}')

    def test_adjudication_shape(self):
        for value in (0, [], "none"):
            self.raw_pair([spans.PAGE], [spans.PAGE], MEMBERS,
                lambda d, value=value: d.replace('"adjudication": null', '"adjudication": ' + json.dumps(value)))

    def test_tier0_shape(self):
        def transform(d):
            d = json.loads(d)
            d["checks"]["tier0"] = None
            return json.dumps(d)
        self.raw_pair([spans.PAGE], [spans.PAGE], MEMBERS, transform)

    def test_start_exact(self):
        for n in ("1.00000000000000001", "1e-999", "10001e-4", "1.00001e+3"):
            with self.subTest(n=n): self.raw_pair(numeric("start", n), numeric("start", "1.0"))

    def test_end_exact(self):
        for n in ("1.00000000000000001", "1e-999", "10001e-4", "1.00001e+3"):
            with self.subTest(n=n): self.raw_pair(numeric("end", n), numeric("end", "1.0"))

    def test_start_negative(self):
        for n in ("-1e-999", "-1e0"): self.raw_pair(numeric("start", n), numeric("start", "-0.0"))
    def test_end_negative(self):
        for n in ("-1e-999", "-1e0"): self.raw_pair(numeric("end", n), numeric("end", "1e0"))
    def test_late_numeral(self): self.raw_pair(numeric("start", "1.00000000000000001", True), [spans.PAGE] * 2)

    def test_numeric_controls(self):
        for n in ("5.0", "5e0", "50e-1", "0.005e+3", "9007199254740991", "9007199254740991.0",
                "9.007199254740991e15", "100000e-5"):
            with self.subTest(n=n): self.raw_pair(numeric("start", "1e-999"), numeric("start", n))
        self.raw_pair(numeric("end", "0e+999999999999999999999"), numeric("start", "0e-999999999999999999999"))

    def test_over_cap_refusals(self):
        for key in ("start", "end"):
            for n in ("9007199254740992", "9007199254740993", "9223372036854775809", "1e+30", "1.7976931348623157e+308"):
                for spelling in (n, n + ".0" if "e" not in n else n):
                    with self.subTest(key=key, n=spelling):
                        self.raw_pair(numeric(key, spelling), numeric(key, "9007199254740991"))

    def test_exact_control(self):
        self.insert([spans.locator(value="é e\u0301\0value")])
        self.assertEqual(self.rows("SELECT extraction_method,access_tier FROM verification_receipts"), [(self.METHOD, "bibliographic")])


class ExtractionExactSpanDDLTest(ExactSpanDDLTest):
    METHOD = "verifier_extraction"


class ValidatedExactSpanDDLTest(ExactSpanDDLTest):
    METHOD = "validated_extraction"
