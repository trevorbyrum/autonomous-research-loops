"""Literal V-6 matcher oracles; admission and durable quarantine await 2d-3b."""
import hashlib
import unittest

from gen2.router.quote_matching import Difference, NearMatch, QuoteMatch, check_quote, normalize, negative
from gen2.tests import children


def check(quote: str, source: str):
    artifact = source.encode("utf-8")
    return check_quote(quote.encode("utf-8"), artifact, 0, len(artifact), "sha256:" + hashlib.sha256(artifact).hexdigest())


class MatchingTest(unittest.TestCase):
    def test_exact_control(self):
        result = check_quote(b"abc", b"abc", 0, 3, "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual((result.status, result.reason, result.quote_quarantined), ("match", None, False))
        self.assertEqual((result.quoted_bytes, result.source_span_bytes, result.normalized_quote, result.normalized_source),
                         (b"abc", b"abc", "abc", "abc"))
        self.assertEqual((result.span_start, result.span_end, result.artifact_hash), (0, 3, result.expected_artifact_hash))
        self.assertEqual(result.normalization[0], "quote-nfc-safe")
        self.assertTrue(result.normalization[1].startswith("2+ucd"))
        self.assertEqual(result.token_versions, ("decimal-expression/2", "english-negation/2", "si9-2022+clinical/2"))

    def test_normalized_control(self):
        result = check("office trial", "office\ttrial")
        self.assertEqual((result.status, result.reason, result.quote_quarantined, result.diagnostic), ("match_normalized", None, False, None))

    def test_normalization_rules(self):
        for quote, source, expected in (("the trial", "  the\t\ntrial  ", "the trial"),
                                        ("randomized", "random\u00ad\r\n  ized", "randomized"),
                                        ('"trial\'s"', "“trial’s”", '"trial\'s"'),
                                        ("trial - result", "trial — result", "trial - result"),
                                        ("dose 5 µg", "dose\t5 µg", "dose 5 µg"),
                                        ("café 5 mg", "cafe\u0301 5 mg", "café 5 mg"),
                                        ("café", "cafe\u0301", "café")):
            with self.subTest(source=source):
                result = check(quote, source)
                self.assertEqual((result.status, result.quote_quarantined, result.diagnostic), ("match_normalized", False, None))
                self.assertEqual((result.normalized_quote, result.normalized_source), (expected, expected))
                self.assertEqual(result.source_span_bytes, source.encode())

    def test_near_match(self):
        result = check("a" * 99 + "b", "a" * 99 + "c")
        self.assertEqual((result.status, result.reason, result.quote_quarantined), ("mismatch", "near_match", True))
        self.assertIsNotNone(result.diagnostic)
        self.assertEqual(result.diagnostic.similarity, 0.99)
        self.assertEqual(result.diagnostic.differing_spans, (Difference(99, 100, 99, 100),))
        self.assertIn("autojunk=False", result.diagnostic.measure[0])

    def test_near_control(self):
        quote, source = "5 mg " + "a" * 99 + "b", "5 mg " + "a" * 99 + "c"
        digest = "sha256:" + hashlib.sha256(source.encode()).hexdigest()
        expected = QuoteMatch(quote.encode(), source.encode(), digest, digest, 0, 105,
                              "mismatch", "near_match", quote, source,
                              NearMatch(104 / 105, (Difference(104, 105, 104, 105),)))
        self.assertEqual(check(quote, source), expected)
        self.assertTrue(expected.quote_quarantined)

    def test_below_threshold_control(self):
        quote, source = "alpha", "omega"
        digest = "sha256:" + hashlib.sha256(source.encode()).hexdigest()
        self.assertEqual(check(quote, source), QuoteMatch(b"alpha", b"omega", digest, digest, 0, 5,
                                                       "mismatch", "text_difference", quote, source))

    def test_difflib_not_levenshtein(self):
        # Two insertions: Levenshtein/max-length = 1 - 2/51, below 0.98.
        result = check("a" * 49, "a" * 49 + "bc")
        self.assertEqual((result.status, result.reason, result.quote_quarantined), ("mismatch", "near_match", True))
        self.assertEqual(result.diagnostic, NearMatch(0.98, (Difference(49, 49, 49, 51),)))
        self.assertLess(1 - 2 / 51, 0.98)

    def test_threshold(self):
        result = check("a" * 49 + "b", "a" * 49 + "c")
        self.assertIsNotNone(result.diagnostic)
        self.assertEqual(result.diagnostic.similarity, 0.98)
        result = check("a" * 48 + "b", "a" * 48 + "c")
        self.assertEqual((result.reason, result.diagnostic), ("text_difference", None))

    def test_repetition(self):
        result = check("b" + "a" * 199 + "c", "d" + "a" * 199 + "e")
        self.assertEqual(result.reason, "near_match")
        self.assertEqual(result.diagnostic.similarity, 199 / 201)
        self.assertEqual(result.diagnostic.differing_spans, (Difference(0, 1, 0, 1), Difference(200, 201, 200, 201)))

    def test_similarity_symmetry(self):
        forward = check("x" * 200 + " tide", "x" * 200 + " diet")
        backward = check("x" * 200 + " diet", "x" * 200 + " tide")
        self.assertEqual(forward.reason, "near_match")
        self.assertEqual(backward.reason, "near_match")
        self.assertEqual((forward.diagnostic.similarity, backward.diagnostic.similarity), (202 / 205, 202 / 205))

    def assert_plain(self, quote, source, reason):
        result = check(quote, source)
        self.assertEqual((result.status, result.reason, result.quote_quarantined, result.diagnostic), ("mismatch", reason, True, None))

    def test_number_change(self):
        for quote, source in (("0.05", "0.5"), ("-5", "5"), ("1e-3", "1e3"), ("5.0", "5"), ("dose-5", "dose+5")):
            with self.subTest(quote=quote):
                self.assert_plain("a" * 200 + " " + quote, "a" * 200 + " " + source, "protected_number")

    def test_negation_change(self):
        for word in ("not", "never", "no", "without", "can't", "cannot", "hardly"):
            with self.subTest(word=word):
                self.assert_plain("a" * 200 + " " + word + " trial", "a" * 200 + " trial", "protected_negation")

    def test_unit_change(self):
        for unit in ("µg", "g", "mcg", "mmHg", "MG"):
            with self.subTest(unit=unit):
                self.assert_plain("a" * 200 + " 5 mg", "a" * 200 + " 5 " + unit, "protected_unit")

    def test_moved_negation(self):
        self.assert_plain("a" * 200 + " not early or late", "a" * 200 + " early or not late", "protected_negation")

    def test_compatibility_preserved(self):
        for quote, source, reason in (("Value 102", "Value 10²", "protected_number"),
                                      ("Value 10", "Value 10²", "protected_number"),
                                      ("Area 5 m2", "Area 5 m²", "protected_unit"),
                                      ("Value 12", "Value 1₂", "protected_number"),
                                      ("Value 5", "Value ５", "protected_number"),
                                      ("Dose 5 μg", "Dose 5 µg", "protected_unit")):
            with self.subTest(source=source):
                self.assert_plain("a" * 500 + " " + quote, "a" * 500 + " " + source, reason)
                self.assertEqual(normalize(source), source)
        self.assertEqual(normalize("ofﬁce ½ ①"), "ofﬁce ½ ①")

    def test_hard_hyphen_and_minus(self):
        for quote, source, reason in (("They will resign the consent form.", "They will re-\nsign the consent form.", "text_difference"),
                                      ("genuinecompound", "genuine-\ncompound", "text_difference"),
                                      ("effective", "non-\neffective", "protected_negation"),
                                      ("xy", "x−\ny", "protected_unit")):
            with self.subTest(source=source):
                self.assert_plain(quote, source, reason)
        self.assertEqual(normalize("x−\ny"), "x− y")
        self.assertEqual(normalize("re-\nsign"), "re- sign")
        self.assertEqual(normalize("random\u00ad\nized"), "randomized")
        self.assert_plain("dose -5", "dose −5", "protected_number")

    def test_hangul_idempotence(self):
        for text, expected in (("ᄀ-\nᅡ", "ᄀ- ᅡ"), ("ᄀ\u00ad\nᅡ", "가")):
            self.assertEqual(normalize(text), expected)
            self.assertEqual(normalize(normalize(text)), expected)

    def test_complete_numbers(self):
        for quote, source in (("1;000", "1,000"), ("1000", "1,000"), ("1 000", "1,000"),
                              ("0.050", "0.05"), ("1.2e-3", "1.2e3"), ("10^2", "102"),
                              ("²", "³"), ("₁", "₂"), ("½", "⅓"), ("①", "②")):
            with self.subTest(quote=quote):
                self.assert_plain("a" * 500 + " count " + quote, "a" * 500 + " count " + source, "protected_number")

    def test_unit_expressions(self):
        for quote, source in (("mg/kg", "mg·kg"), ("mg×kg", "mg/kg"), ("m^2", "m²"), ("m", "m²"),
                              ("seconds", "minutes"), ("µg", "micrograms")):
            with self.subTest(quote=quote):
                self.assert_plain("a" * 500 + " dose 5 " + quote, "a" * 500 + " dose 5 " + source, "protected_unit")

    def test_negative_prefixes(self):
        for quote, source in (("non-effective", "effective"), ("unavailable", "available"),
                              ("ineffective", "effective"), ("impossible", "possible"), ("irregular", "regular"),
                              ("illegal", "legal"), ("disagree", "agree"), ("didn't", "did"),
                              ("unproven", "proven"), ("non-testable", "testable")):
            with self.subTest(quote=quote):
                self.assert_plain("a" * 500 + " " + quote, "a" * 500 + " " + source, "protected_negation")
        self.assertTrue(negative("unavailable", frozenset()))
        self.assertTrue(negative("non-effective", frozenset()))

    def test_prefix_positive_control(self):
        for word in ("uniform", "under", "discuss", "information", "image", "iridescent", "illuminate"):
            self.assertFalse(negative(word, frozenset()))
            result = check("a" * 500 + " " + word, "a" * 500 + " " + word + "s")
            self.assertEqual((result.status, result.reason, result.quote_quarantined), ("mismatch", "near_match", True))
            self.assertIsNotNone(result.diagnostic)

    def test_aligned_relocation(self):
        for quote, source, reason in (("not early if later", "later if not early", "protected_negation"),
                                      ("measure mg then rate", "rate then measure mg", "protected_unit"),
                                      ("dose 5 then placebo", "placebo then dose 5", "protected_number")):
            self.assert_plain("a" * 500 + " " + quote, "a" * 500 + " " + source, reason)

    def test_protection_before_diagnostic(self):
        from unittest.mock import patch
        with patch("gen2.router.quote_matching.SequenceMatcher", side_effect=AssertionError("diagnostic used for protection")):
            self.assert_plain("not early if later", "later if not early", "protected_negation")

    def test_original_protection(self):
        from unittest.mock import patch
        # An independent seam proves protection does not consume normalizer output.
        with patch("gen2.router.quote_matching.normalize", return_value="same"):
            self.assert_plain("Value 102", "Value 10²", "protected_number")

    def test_numeric_hyphenation(self):
        self.assert_plain("dose 1e-3", "dose 1e-\n3", "protected_number")

    def test_number_parse_failure(self):
        self.assert_plain("dose 1e999999999999999999999", " dose 1e999999999999999999999", "number_parse")

    def test_wrong_artifact_version(self):
        result = check_quote(b"abc", b"abc", 0, 3, "sha256:" + "0" * 64)
        self.assertEqual((result.status, result.reason, result.quote_quarantined), ("mismatch", "artifact_version", True))

    def test_span_offsets(self):
        digest = "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        for start, end in ((-1, 3), (0, 4), (1, 1), (2, 1), (True, 3), (0, 3.0)):
            with self.subTest(start=start, end=end):
                result = check_quote(b"abc", b"abc", start, end, digest)
                self.assertEqual((result.reason, result.quote_quarantined), ("span_offsets", True))
        self.assertEqual(check_quote(b"abc", b"abc", 1, 3, digest).status, "mismatch")

    def test_span_boolean(self):
        result = check_quote(b"bc", b"abc", True, 3, "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual((result.reason, result.quote_quarantined), ("span_offsets", True))

    def test_utf8(self):
        artifact = "éabc".encode()
        digest = "sha256:" + hashlib.sha256(artifact).hexdigest()
        result = check_quote(b"abc", artifact, 1, 5, digest)
        self.assertEqual((result.reason, result.quote_quarantined), ("utf8", True))
        self.assertEqual(check_quote(b"abc", artifact, 2, 5, digest).status, "match")

    def test_text_difference(self):
        self.assert_plain("alpha", "omega", "text_difference")

    def test_properties(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PROPERTIES = '''
from hypothesis import given, settings, strategies as st
from gen2.router.quote_matching import normalize
from gen2.tests.test_quote_matching import check
@settings(max_examples=100, derandomize=True, database=None)
@given(st.text(max_size=200))
def idempotent(text):
    assert normalize(normalize(text)) == normalize(text)
@settings(max_examples=100, derandomize=True, database=None)
@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=200))
def negation_never_passes(text):
    result = check(text + " not", text)
    assert (result.status, result.reason, result.diagnostic) == ("mismatch", "protected_negation", None)
@settings(max_examples=150, derandomize=True, database=None)
@given(st.lists(st.sampled_from(["ᄀ", "ᅡ", "e", "\\u0301", "\\u00ad\\n", "-\\r\\n", "‘", "—", "−", "\\t", "\\u00a0", "m²", "1,000"]), max_size=30))
def composed_rules(parts):
    text = "".join(parts)
    assert normalize(normalize(text)) == normalize(text)
@settings(max_examples=150, derandomize=True, database=None)
@given(st.lists(st.sampled_from(["early", "later", "measure", "rate", "trial"]), min_size=3, max_size=12),
       st.sampled_from(["not", "never", "cannot", "unavailable", "non-effective", "didn't", "1,000", "−5", "1e-3", "mg/kg", "seconds", "m²"]),
       st.data())
def protected_edits(words, token, data):
    first = data.draw(st.integers(min_value=0, max_value=len(words)))
    second = data.draw(st.sampled_from([i for i in range(len(words) + 1) if i != first]))
    at_first, at_second = words[:], words[:]
    at_first.insert(first, token); at_second.insert(second, token)
    pad = "The trial report describes observations. " * 20
    base, inserted, moved = [pad + " ".join(w) for w in (words, at_first, at_second)]
    for quote, source in ((base, inserted), (inserted, base), (inserted, moved)):
        result = check(quote, source)
        assert result.status == "mismatch" and result.quote_quarantined
        assert result.reason.startswith("protected_") and result.diagnostic is None
idempotent(); negation_never_passes(); composed_rules(); protected_edits()
'''
