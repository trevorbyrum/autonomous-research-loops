"""Tests for gen2/core/instants.py (the timestamp validation layer, A11).

The oracle is a hand-written list of calendar facts (leap-year rules, month
lengths, RFC 3339 form), not the implementation's own parser. For
utc_instant_ns (task 1b: the router compares lease expiry and deadlines as
instants), the expected nanosecond counts are literals worked out by hand
from the Unix epoch.
"""
from __future__ import annotations

import unittest

from gen2.core.instants import is_utc_instant, utc_instant_ns


class UtcInstantTest(unittest.TestCase):
    VALID = ("2026-09-25T12:00:00Z", "2028-02-29T23:59:59Z", "2000-02-29T00:00:00Z", "2026-01-31T00:00:00.5Z",
             "2026-12-31T23:59:59.123456789Z", "1970-01-01T00:00:00Z",
             "1969-12-31T23:59:59Z", "0001-01-01T00:00:00Z")  # before the Unix epoch is still a real instant
    INVALID = (
        "2026-02-31T12:00:00Z",   # February 31 (the review's probe; the schema pattern admits it)
        "2026-02-30T12:00:00Z",
        "2026-02-29T12:00:00Z",   # 2026 is not a leap year
        "1900-02-29T12:00:00Z",   # century rule: 1900 is not a leap year
        "2026-04-31T12:00:00Z",   # April has 30 days
        "2026-13-01T12:00:00Z", "2026-00-10T12:00:00Z", "2026-09-00T12:00:00Z",
        "2026-09-25T24:00:00Z", "2026-09-25T23:60:00Z", "2026-09-25T23:59:60Z",
        "2026-09-25T12:00:00+00:00", "2026-09-25T12:00:00z", "2026-09-25 12:00:00Z", "2026-09-25T12:00Z",
        "2026-09-25T12:00:00.1234567890Z", "2026-09-25", "", "2026-09-25T12:00:00Z\n",
        "2026-09-25T12:00:00.Z",  # a decimal point needs at least one fraction digit
        # Unicode decimal digits: the schema's ASCII pattern refuses them, and so does the helper
        "\uff12\uff10\uff12\uff16-09-25T12:00:00Z",  # fullwidth 2026
        "\u0662\u0660\u0662\u0666-09-25T12:00:00Z",  # Arabic-Indic 2026
        "2026-09-25T1\u0662:00:00Z", "2026-09-25T12:00:00.\u0665Z",
    )

    def test_real_instants_accepted(self) -> None:
        for value in self.VALID:
            with self.subTest(value=value):
                self.assertTrue(is_utc_instant(value))

    def test_impossible_or_malformed_instants_refused(self) -> None:
        for value in self.INVALID:
            with self.subTest(value=value):
                self.assertFalse(is_utc_instant(value))

    def test_non_strings_refused(self) -> None:
        for value in (None, 20260925, 1.5, ["2026-09-25T12:00:00Z"]):
            with self.subTest(value=value):
                self.assertFalse(is_utc_instant(value))


class UtcInstantOrderTest(unittest.TestCase):
    def test_nanoseconds_since_the_epoch(self) -> None:
        cases = {
            "1970-01-01T00:00:00Z": 0,
            "1970-01-01T00:00:01Z": 1_000_000_000,
            "1970-01-02T00:00:00.5Z": 86_400_500_000_000,
            "1969-12-31T23:59:59.999999999Z": -1,
            "2000-03-01T00:00:00Z": 951_868_800_000_000_000,  # the day after 2000-02-29 (a century leap day)
            "2026-12-31T23:59:59.123456789Z": 1_798_761_599_123_456_789,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(utc_instant_ns(value), expected)

    def test_time_order_is_not_text_order(self) -> None:
        """A shorter fraction can sort after a longer one as text."""
        earlier, later = "2026-09-25T12:00:00.25Z", "2026-09-25T12:00:00.3Z"
        self.assertLess(utc_instant_ns(earlier), utc_instant_ns(later))
        self.assertLess(utc_instant_ns("2026-09-25T12:00:00Z"), utc_instant_ns("2026-09-25T12:00:00.000000001Z"))
        self.assertGreater("2026-09-25T12:00:00Z", "2026-09-25T12:00:00.5Z")  # text order says the whole second is later
        self.assertLess(utc_instant_ns("2026-09-25T12:00:00Z"), utc_instant_ns("2026-09-25T12:00:00.5Z"))

    def test_invalid_instants_are_refused(self) -> None:
        for value in ("2026-02-29T00:00:00Z", "2026-09-25T24:00:00Z", None, "2026-09-25"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                utc_instant_ns(value)


if __name__ == "__main__":
    unittest.main()
