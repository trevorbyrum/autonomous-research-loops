"""Tests for gen2/core/instants.py (the timestamp validation layer, A11).

The oracle is a hand-written list of calendar facts (leap-year rules, month
lengths, RFC 3339 form), not the implementation's own parser.
"""
from __future__ import annotations

import unittest

from gen2.core.instants import is_utc_instant


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


if __name__ == "__main__":
    unittest.main()
