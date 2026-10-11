"""Literal V-6 matcher oracles; admission and durable quarantine await 2d-3b."""
import hashlib
import unittest

from gen2.router.quote_matching import (Difference, NearMatch, QuoteMatch, check_quote, normalize, negative,
                                       _protected_difference, edit_protection, skeleton)
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
        self.assertEqual(result.token_versions, ("decimal-expression/2", "english-negation/3", "si9-2022+clinical/2"))
        self.assertEqual(result.protection, "quote-protection/4")

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
        for quote, source, reason in (("They will resign the consent form.", "They will re-\nsign the consent form.", "protected_character"),
                                      ("genuinecompound", "genuine-\ncompound", "protected_character"),
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
                reason = {"unproven": "protected_prefix", "non-testable": "protected_character"}.get(quote, "protected_negation")
                self.assert_plain("a" * 500 + " " + quote, "a" * 500 + " " + source, reason)
        self.assertTrue(negative("unavailable"))
        self.assertTrue(negative("non-effective"))

    def test_prefix_positive_control(self):
        for word in ("uniform", "under", "discuss", "information", "image", "iridescent", "illuminate"):
            self.assertFalse(negative(word))
            result = check("a" * 500 + " " + word, "a" * 500 + " " + word + "s")
            self.assertEqual((result.status, result.reason, result.quote_quarantined), ("mismatch", "near_match", True))
            self.assertIsNotNone(result.diagnostic)
            # An unchanged lookalike must not classify as a negative token.
            result = check("a" * 500 + " " + word + " trial", "a" * 500 + " " + word + " trials")
            self.assertEqual((result.status, result.reason), ("mismatch", "near_match"))
            self.assertIsNotNone(result.diagnostic)
        result = check("a" * 500 + " discuss cuss trial", "a" * 500 + " discuss cuss trials")
        self.assertEqual((result.status, result.reason), ("mismatch", "near_match"))
        self.assertIsNotNone(result.diagnostic)

    def test_skeleton(self):
        self.assertEqual(skeleton("abc1def2ghi3"), (("1", 0), ("2", 3), ("3", 3)))
        self.assertEqual(skeleton("abcd1efg2hij3"), (("1", 0), ("2", 3), ("3", 3)))
        self.assertNotEqual(skeleton("1abc2"), skeleton("1abcd2"))
        self.assertEqual(skeleton("²x₃ + 5"), (("²", 0), ("₃", 1), ("+", 1), ("5", 1)))
        self.assertEqual(edit_protection("1abc2", "1abcd2", (Difference(4, 4, 4, 5),)), "protected_character")

    def test_safe_edit_regions(self):
        for quote, source in (("abc1def", "abc1xef"), ("not-yet", "not-wet"),
                              ("dose-mg", "rose-mg"), ("abc²def", "abc²xef"), ("abcⁱdef", "abcⁱxef"),
                              ("abc1def2ghi3jzz", "abcd1efg2hij3zz")):
            with self.subTest(quote=quote):
                self.assert_plain("a" * 500 + " " + quote, "a" * 500 + " " + source, "protected_edit")
        self.assert_plain("a" * 500 + " 5mg", "a" * 500 + " 5µg", "protected_unit")

    def test_apostrophe_boundaries(self):
        # Literal protected-word edits, independently specified in both forms.
        cases = (
            ("insert", "say'now", "say'not'now"),
            ("delete", "say'not'now", "say'now"),
            ("replace", "say'no'now", "say'yes'now"),
            ("move", "alpha'not'omega'delta", "alpha'omega'not'delta"),
            ("unit move", "alpha'mg'omega'delta", "alpha'omega'mg'delta"),
            ("unit-word move", "alpha'seconds'omega'delta", "alpha'omega'seconds'delta"),
            ("start delete", "not'early", "early"),
            ("curly insert", "say’now", "say’not’now"),
            ("curly delete", "say’not’now", "say’now"),
            ("curly replace", "say’no’now", "say’yes’now"),
            ("curly move", "alpha’not’omega’delta", "alpha’omega’not’delta"),
            ("curly unit move", "alpha’mg’omega’delta", "alpha’omega’mg’delta"),
            ("curly unit-word move", "alpha’seconds’omega’delta", "alpha’omega’seconds’delta"),
            ("curly start delete", "not’early", "early"),
        )
        pad = "The trial report describes the observations and their limitations. " * 10
        for name, quote, source in cases:
            for left, right in ((quote, source), (source, quote)):
                with self.subTest(edit=name, quote=left):
                    self.assert_plain(pad + left, pad + right, "protected_edit")

    def test_apostrophe_near_control(self):
        quote = "a" * 200 + " alpha'trial'omega"
        source = "a" * 200 + " alpha'trials'omega"
        digest = "sha256:" + hashlib.sha256(source.encode()).hexdigest()
        self.assertEqual(check(quote, source),
                         QuoteMatch(quote.encode(), source.encode(), digest, digest, 0, 219,
                                    "mismatch", "near_match", quote, source,
                                    NearMatch(436 / 437, (Difference(212, 212, 212, 213),))))

    def test_apostrophe_whitespace_control(self):
        quote = "a" * 200 + " trial's"
        source = "a" * 200 + " trial's a"
        digest = "sha256:" + hashlib.sha256(source.encode()).hexdigest()
        self.assertEqual(check(quote, source),
                         QuoteMatch(quote.encode(), source.encode(), digest, digest, 0, 210,
                                    "mismatch", "near_match", quote, source,
                                    NearMatch(208 / 209, (Difference(208, 208, 208, 210),))))

    def test_prefix_edit_regions(self):
        for prefix in ("un", "non", "in", "im", "ir", "il", "dis"):
            for quote, source in ((prefix + "zzzz", "zzzz"), ("zzzz", prefix + "zzzz")):
                self.assert_plain("a" * 500 + " " + quote, "a" * 500 + " " + source, "protected_prefix")
        for quote, source in (("discuss", "cuss"), ("information", "formation"), ("image", "age")):
            self.assert_plain("a" * 500 + " " + quote, "a" * 500 + " " + source, "protected_prefix")
        for quote, source in (("ununiform", "uniform"), ("ununverified", "unverified"),
                              ("disdiscuss", "discuss"), ("ininformation", "information")):
            for a, b in ((quote, source), (source, quote)):
                self.assert_plain("a" * 500 + " " + a, "a" * 500 + " " + b, "protected_prefix")

    def test_relocation_regions(self):
        for token in ("not", "mg", "5"):
            self.assert_plain("a" * 500 + " abc early " + token + " later xyz",
                              "a" * 500 + " xyz early " + token + " later abc", "protected_relocation")
        # Even one letter moved across an unchanged negation changes its scope.
        self.assert_plain("a" * 500 + " ab early not later xy",
                          "a" * 500 + " ax early not later by", "protected_relocation")

    def test_lexical_layer(self):
        # Independent spelling oracles keep the accepted extra lexical layer
        # mutation-tested even where the new edit checks also reject the pair.
        for quote, source, kind in (("0.05", "0.5", "number"), ("1;000", "1,000", "number"),
                                    ("102", "10²", "number"), ("10²", "10", "number"), ("①", "②", "number"),
                                    ("no trial", "trial", "negation"), ("unavailable", "available", "negation"),
                                    ("mg", "g", "unit"), ("mg/kg", "mg·kg", "unit"),
                                    ("seconds", "minutes", "unit"), ("xy", "x− y", "unit")):
            with self.subTest(quote=quote):
                self.assertEqual(_protected_difference(quote, source), kind)

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

    def test_review_probe_literals(self):
        # Astra round-1 and round-2 operands, both directions. The operator's
        # amended prefix ruling makes the three lookalike stem removals plain.
        for name, quote, source, expected, padded in REVIEW_PROBES:
            for a, b in ((quote, source), (source, quote)):
                with self.subTest(probe=name, quote=a):
                    pad = "The trial report describes the observations and their limitations. " * 10 if padded else ""
                    result = check(pad + a, pad + b)
                    if expected == "normalized":
                        self.assertEqual((result.status, result.reason, result.diagnostic), ("match_normalized", None, None))
                    else:
                        self.assertEqual((result.status, result.quote_quarantined), ("mismatch", True))
                        self.assertEqual(result.diagnostic is not None, expected == "near")

    def test_review_input_literals(self):
        artifact = "éabc".encode()
        digest = "sha256:" + hashlib.sha256(artifact).hexdigest()
        for name, quote, start, end, expected in (
                ("negative_offset", b"abc", -1, 5, "span_offsets"),
                ("beyond_end", b"abc", 2, 6, "span_offsets"),
                ("empty_span", b"", 2, 2, "span_offsets"),
                ("reversed_span", b"abc", 5, 2, "span_offsets"),
                ("bool_offset", b"abc", True, 5, "span_offsets"),
                ("float_offset", b"abc", 2, 5.0, "span_offsets"),
                ("utf8_start_split", b"abc", 1, 5, "utf8"),
                ("utf8_end_split", b"x", 0, 1, "utf8"),
                ("invalid_quote_utf8", b"\xff", 2, 5, "utf8")):
            with self.subTest(probe=name):
                result = check_quote(quote, artifact, start, end, digest)
                self.assertEqual((result.status, result.reason, result.diagnostic), ("mismatch", expected, None))
        result = check_quote(b"abc", artifact, 2, 5, "sha256:" + "0" * 64)
        self.assertEqual((result.status, result.reason, result.diagnostic), ("mismatch", "artifact_version", None))
        self.assertEqual(check_quote(b"abc", artifact, 2, 5, digest).status, "match")
        for quote in (b"abc", b"\xff"):
            result = check_quote(quote, b"\xff", 0, 1, "sha256:" + hashlib.sha256(b"\xff").hexdigest())
            self.assertEqual((result.status, result.reason, result.diagnostic), ("mismatch", "utf8", None))

    def test_review_normalization_literals(self):
        for original, expected in (("a-\n\vb", "a- b"), ("a-\n\u00a0b", "a- b"),
                                   ("a\u00ad\n\vb", "ab"), ("a\r\nb", "a b"),
                                   ("a-\n b", "a- b"), ("Dose 5 m²", "Dose 5 m²"),
                                   ("ᄀ-\nᅡ", "ᄀ- ᅡ"), ("ᄀ\u00ad\nᅡ", "가")):
            self.assertEqual(normalize(original), expected)
            self.assertEqual(normalize(expected), expected)

    def test_properties(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


REVIEW_PROBES = (
    ('superscript_unit', 'Area 5 m2', 'Area 5 m²', 'plain', False),
    ('superscript_exponent', 'Value 102', 'Value 10²', 'plain', False),
    ('fraction', 'Value 1⁄2', 'Value ½', 'plain', False),
    ('true_compound', 'They will resign the consent form.', 'They will re-\nsign the consent form.', 'plain', False),
    ('negative_prefix_dehyphenation', 'The compound is unionized.', 'The compound is un-\nionized.', 'plain', False),
    ('linebreak_minus', 'x-y', 'x−\ny', 'plain', False),
    ('scientific_notation', 'dose 1e-3', 'dose 1e3', 'plain', True),
    ('decimal_precision', 'dose 0.050', 'dose 0.05', 'plain', True),
    ('thousands_removed', 'count 1000', 'count 1,000', 'plain', True),
    ('thousands_split', 'counts 1 000', 'counts 1,000', 'plain', True),
    ('non_prefix', 'non-effective', 'effective', 'plain', True),
    ('un_prefix', 'unavailable', 'available', 'plain', True),
    ('no_not', 'no benefit', 'not benefit', 'plain', True),
    ('contraction', "didn't improve", 'did improve', 'plain', True),
    ('micro_u', 'dose 5 µg', 'dose 5 ug', 'plain', True),
    ('micro_word', 'dose 5 µg', 'dose 5 micrograms', 'plain', True),
    ('u_micro_word', 'dose 5 ug', 'dose 5 microgram', 'plain', True),
    ('percent', 'rate 5%', 'rate 5 percent', 'plain', True),
    ('moved_negation', 'not early or late', 'early or not late', 'plain', True),
    ('unicode_minus_sign_change', 'dose −5', 'dose 5', 'plain', True),
    ('unicode_minus_equivalent', 'dose −5', 'dose -5', 'plain', False),
    ('uppercase_negation', 'NOT effective', 'not effective', 'plain', True),
    ('compound_unit_operator', 'dose 5 mg/kg', 'dose 5 mg·kg', 'plain', True),
    ('unit_words', 'time 5 seconds', 'time 5 minutes', 'plain', True),
    ('unicode_primes', 'length 5″', 'length 5′′', 'plain', False),
    ('threshold_exact', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaab', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaac', 'near', False),
    ('threshold_below', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaab', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaac', 'plain', False),
    ('ordinary_near', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaab', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaac', 'near', False),
    ('arithmetic_minus', 'xy', 'x−\ny', 'plain', False),
    ('thousands_semicolon', 'count 1;000', 'count 1,000', 'plain', True),
    ('moved_negation_aligned', 'not early or later', 'later or not early', 'plain', True),
    ('moved_negation_scope', 'not improved and declined', 'declined and not improved', 'plain', True),
    ('moved_negation_subject', 'Drug A is not effective; Drug B is effective.', 'Drug A is effective; Drug B is not effective.', 'plain', True),
    ('moved_negation_condition', 'not early if later', 'later if not early', 'plain', True),
    ('moved_number_context', 'Dose 5 for arm alpha; placebo for arm beta.', 'Placebo for arm alpha; dose 5 for arm beta.', 'plain', True),
    ('moved_unit_context', 'measure mg then rate', 'rate then measure mg', 'plain', True),
    ('compatibility_circled_ten', 'Value ⑩', 'Value 10', 'plain', True),
    ('compatibility_vulgar_fraction', 'Value ⅔', 'Value 2⁄3', 'plain', True),
    ('compatibility_ligature_retained', 'office', 'ofﬁce', 'near', True),
    ('compatibility_whitelisted_dash', 'non-effective', 'non‑effective', 'normalized', True),
    ('unlisted_unshared_prefix', 'unverified', 'confirmed', 'near', True),
    ('unlisted_shared_prefix', 'unproven', 'proven', 'plain', True),
    ('listed_unshared_prefix', 'unavailable', 'confirmed', 'plain', True),
    ('hyphenated_not_removed', 'not-yet', 'yet', 'plain', True),
    ('hyphenated_no_removed', 'no-effect', 'effect', 'plain', True),
    ('hyphenated_cannot_removed', 'cannot-act', 'can-act', 'plain', True),
    ('changed_digit_in_word', 'abc1def', 'abc2def', 'plain', True),
    ('moved_digit_in_word', 'abc1def', 'abcde1f', 'plain', True),
    ('moved_digit_in_identifier', 'BRCA1-positive', 'BRCA-positive1', 'plain', True),
    ('moved_three_digits', 'abc1def2ghi3jzz', 'abcd1efg2hij3zz', 'plain', True),
    ('moved_across_several_tokens', 'not 5 mg then 7 kg', '5 mg then 7 kg not', 'plain', True),
    ('grouping_punctuation_changed', 'count 1;000', 'count 1,000', 'plain', True),
    ('spaced_sign_changed', 'dose - 5', 'dose + 5', 'plain', True),
    ('arithmetic_punctuation_changed', 'dose 5 - 3', 'dose 5 + 3', 'plain', True),
    ('unit_operator_changed', 'dose 5 mg/kg', 'dose 5 mg·kg', 'plain', True),
    ('whitespace_control', 'dose 5 mg', 'dose\t5\xa0mg', 'normalized', True),
    ('curly_quote_control', '"trial\'s"', '“trial’s”', 'normalized', True),
    ('soft_wrap_control', 'randomized', 'random\xad\r\n  ized', 'normalized', True),
    ('nfc_control', 'café 5 mg', 'café 5 mg', 'normalized', True),
    ('unit_whitespace_runs_control', '5 mg / kg', '5 mg  /  kg', 'normalized', True),
    ('uniform_control', 'uniform', 'uniforms', 'near', True),
    ('under_control', 'under', 'unders', 'near', True),
    ('discuss_control', 'discuss', 'discusss', 'near', True),
    ('discuss_lookalike_stem', 'discuss', 'cuss', 'plain', True),
    ('information_lookalike_stem', 'information', 'formation', 'plain', True),
    ('image_lookalike_stem', 'image', 'age', 'plain', True),
)


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

@settings(max_examples=100, derandomize=True, database=None, deadline=None)
@given(st.one_of(st.text(alphabet="abcxyz-012+ " + chr(9) + chr(10), min_size=1, max_size=5),
                  st.text(alphabet=st.characters(categories=("L", "N", "P", "S", "M"),
                                                 exclude_characters="‘’‚‛“”„‟‐‑‒–—―"), min_size=1, max_size=5),
                  st.sampled_from(["not-yet", "5mg", "1not2", "mg-x", "x1y2z3", "unabc", "a-b"])), st.sampled_from([
    ("1", "2"), ("٥", "６"), ("+", "-"), ("−", "±"), ("×", "/"), ("·", "^"),
    ("%", "‰"), ("=", "<"), (">", "≤"), ("≥", "⁄"), ("²", "³"), ("₁", "₂"),
    ("ⁱ", "ⁿ"), ("ₐ", "ₓ"), ("½", "⅓"), ("①", "②"),
    ("-not-", "-never-"), ("-no-", "-cannot-"), ("-can't-", "-without-"),
    ("-mg-", "-µg-"), ("-s-", "-kg-"), ("-seconds-", "-minutes-")]), st.sampled_from([" ", "-", "'", "’"]))
def soundness(text, tokens, boundary):
    # Word packets create letter boundaries at EVERY character position,
    # including inside a lexeme, across hyphens and apostrophe-joined words.
    # Character material needs no boundary. All four edit kinds are exercised.
    token, replacement = tokens
    if token.startswith("-") and token.endswith("-") and len(token) > 2:
        token, replacement = boundary + token[1:-1] + boundary, boundary + replacement[1:-1] + boundary
    pad = "a" * 200 + " "
    def plain(left, right):
        result = check(pad + left, pad + right)
        assert result.status == "mismatch" and result.quote_quarantined and result.diagnostic is None
    for position in range(len(text) + 1):
        inserted = text[:position] + token + text[position:]
        replaced = text[:position] + replacement + text[position:]
        for left, right in ((text, inserted), (inserted, text), (inserted, replaced), (replaced, inserted)):
            plain(left, right)
        for destination in range(len(text) + 1):
            moved = text[:destination] + token + text[destination:]
            # Moving an identical token only across whitespace is equivalent
            # under the independently specified permitted whitespace fold.
            if " ".join(moved.split()) != " ".join(inserted.split()):
                plain(inserted, moved)
@settings(max_examples=80, derandomize=True, database=None, deadline=None)
@given(st.text(alphabet="abcxyz", min_size=1, max_size=12),
       st.sampled_from([" ", "\\t", "\\n", "\\u00a0"]), st.sampled_from(["'", "’"]))
def utility(text, whitespace, apostrophe):
    pad = "a" * 200
    source = pad + " trial's " + text
    for position in range(len(text) + 1):
        variants = [text[:position] + "q" + text[position:]]
        if position < len(text):
            variants.extend([text[:position] + text[position + 1:], text[:position] + "q" + text[position + 1:]])
        for changed in variants:
            quote = pad + whitespace + "trial" + apostrophe + "s" + whitespace + changed
            result = check(quote, source)
            assert (result.status, result.reason, result.quote_quarantined) == ("mismatch", "near_match", True)
            assert result.diagnostic is not None and result.diagnostic.similarity >= 0.98

idempotent(); negation_never_passes(); composed_rules(); protected_edits(); soundness(); utility()
'''
