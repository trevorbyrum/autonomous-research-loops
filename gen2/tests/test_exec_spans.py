"""Structural quote location (Astra #140 F1). Oracle: the decoded abstract from `json.loads` of the token and plain `bytes` slicing in
the test, independent of the scanner; and the router's own `quote_matching.check_quote` on the returned span. Limits: a quote that
itself contains an escaped character is refused (a stated limit), and these bytes are the discovery job's canonical reconstruction."""
import json
import unittest

from gen2.core import canonical
from gen2.exec import common, spans
from gen2.router import quote_matching


def response(abstract, identity="doi:10.1/a", **extra):
    """A staged-response-shaped envelope: the selected record last, another record and keys that repeat the text before it."""
    other = {"identity": "doi:10.1/other", "abstract": abstract, "title": abstract}
    chosen = {"identity": identity, "abstract": abstract, **extra}
    return canonical.canonical_bytes({"effective_request": None, "lanes": [], "records": [other, chosen], "request_type": "find", abstract: 1, "a " + abstract: 2})


def check(case, abstract, quote, **extra):
    data = response(abstract, **extra)
    start, end = spans.locate(data, "doi:10.1/a", abstract, quote)
    case.assertEqual(data[start:end], quote.encode("utf-8"))
    token_start, token_end = spans.abstract_token(data, "doi:10.1/a")
    case.assertTrue(token_start < start < end < token_end, "inside the selected record's abstract token")
    case.assertEqual(json.loads(data[token_start:token_end]), abstract)
    match = quote_matching.check_quote(quote.encode(), data, start, end, canonical.bytes_digest(data))
    case.assertFalse(match.quote_quarantined, match)
    return start, token_start


class LocateTest(unittest.TestCase):
    def test_plain_quotes_far_from_escapes_are_located(self):
        for name, abstract, quote in (
                ("escaped quote marks before the quote", 'He said "yes", then an effect observed.', "effect observed"),
                ("a newline before the quote", "First line.\nA later effect observed here.", "effect observed"),
                ("a backslash after the quote", "An effect observed in C:\\data.", "effect observed"),
                ("a tab between two quotes of one abstract", "Alpha beta.\tGamma delta.", "Gamma delta"),
                ("the quote before every escape", 'Plain start effect observed, then "quoted" text.', "Plain start effect observed"),
                ("a control character escaped as \\u", "Ctl\u0001 then effect observed.", "effect observed")):
            with self.subTest(name):
                check(self, abstract, quote)

    def test_a_multibyte_prefix_shifts_bytes_not_characters(self):
        abstract = "Na\u00efve caf\u00e9 \u2014 effect observed \U0001F600 end."
        start, token = check(self, abstract, "effect observed")
        self.assertGreater(start - token, abstract.index("effect observed") + 1, "byte offsets exceed character offsets")
        check(self, abstract, "caf\u00e9 \u2014 effect")   # a multibyte quote itself, no escape inside it

    def test_text_repeated_elsewhere_in_the_envelope_is_not_the_quote_location(self):
        data = response("An effect observed.")
        start, _ = spans.locate(data, "doi:10.1/a", "An effect observed.", "effect observed")
        token_start, token_end = spans.abstract_token(data, "doi:10.1/a")
        first = data.find(b"effect observed")
        self.assertLess(first, token_start, "a global first match would land in another record, a title or a key")
        self.assertTrue(token_start < start < token_end)
        self.assertEqual(data[token_start:token_end], json.dumps("An effect observed.").encode())

    def test_the_record_is_chosen_by_identity(self):
        data = response("Chosen abstract.")
        self.assertNotEqual(spans.abstract_token(data, "doi:10.1/a"), spans.abstract_token(data, "doi:10.1/other"))

    def test_refusals(self):
        abstract = 'Quoted "inner" text and an effect observed.'
        data = response(abstract)
        cases = {"a quote that crosses an escape": (data, abstract, '"inner" text'),
                 "a quote that is an escaped character": (data, abstract, '"'),
                 "a quote that is not in the abstract": (data, abstract, "not there"),
                 "an empty quote": (data, abstract, ""),
                 "the view showed a different abstract": (data, "Another abstract.", "effect observed"),
                 "a record that is not in the response": (data.replace(b"doi:10.1/a", b"doi:10.1/z"), abstract, "effect observed")}
        for name, (blob, content, quote) in cases.items():
            with self.subTest(name), self.assertRaises(common.Refused):
                spans.locate(blob, "doi:10.1/a", content, quote)
