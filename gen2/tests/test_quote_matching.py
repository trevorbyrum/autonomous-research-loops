"""Literal V-6 matcher oracles; admission and durable quarantine await 2d-3b."""
import hashlib
import unittest

from gen2.router.quote_matching import Difference, check_quote, normalize
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
        self.assertEqual(result.normalization[0], "quote-nfkc")
        self.assertTrue(result.normalization[1].startswith("1+ucd"))
        self.assertEqual(result.token_versions, ("decimal-token/1", "english-negation/1", "si9-2022+clinical/1"))

    def test_normalized_control(self):
        self.assertEqual(check("office", "ofﬁce").status, "match_normalized")

    def test_normalization_rules(self):
        for quote, source, expected in (("the trial", "  the\t\ntrial  ", "the trial"),
                                        ("randomized", "random-\nized", "randomized"),
                                        ("randomized", "random\u00ad\r\n  ized", "randomized"),
                                        ('"trial\'s"', "“trial’s”", '"trial\'s"'),
                                        ("trial - result", "trial — result", "trial - result"),
                                        ("dose 5 μg", "dose ５ µg", "dose 5 μg"),
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
        self.assertEqual(check("5 mg " + "a" * 99 + "b", "5 mg " + "a" * 99 + "c").reason, "near_match")

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
idempotent(); negation_never_passes()
'''
