"""C-13 decimal equivalence and pre-repair catalog/hash compatibility."""
import json
import math
import unittest
from decimal import Decimal, InvalidOperation

from gen2.core import canonical as c
from gen2.tests import test_canonical as vectors
from gen2.tests.span_cap_cases import NUMERALS


class DecimalExactnessTest(unittest.TestCase):
    def test_extreme_zero(self):
        for sign in ('', '-'):
            for mantissa in ('0', '0.000'):
                for power in ('999999999999999999999', '-999999999999999999999', '+' + '9' * 5000):
                    text = sign + mantissa + 'e' + power
                    with self.subTest(sign=sign, mantissa=mantissa, power=power[:30]):
                        try:
                            value = c.parse_json_strict(text)
                        except c.CanonicalizationError:
                            self.fail('exact zero was refused')
                        self.assertEqual(value, 0)
                        self.assertEqual(math.copysign(1, value), -1 if sign else 1)
                        self.assertEqual(c.canonical_bytes(value), b'0')
                        self.assertEqual(c.logical_hash(value), vectors.sha(b'0'))

    def test_nonzero_refusals(self):
        for text in ('1e999999999999999999999', '1e-999999999999999999999',
                '-1e-999999999999999999999', '1e-400', '1e400',
                '0.1000000000000000055511151231257827', '9007199254740993.0',
                '333333333.33333329', '2.4e-324'):
            with self.subTest(text=text):
                with self.assertRaises(c.CanonicalizationError):
                    c.parse_json_strict(text)

    def test_equivalent_control(self):
        for text in ('1.2500e+000000', '125e-000002', '0.0125E+2',
                '1' + '0' * 5000 + 'e-5000'):
            expected = b'1' if len(text) > 5000 else b'1.25'
            self.assertEqual(c.canonical_bytes(c.parse_json_strict(text)), expected)

    def test_existing_catalog_hashes(self):
        # The old parser is the compatibility oracle, not the new helper.
        # Extract every numeral from the existing published/cross catalogs.
        numerals = set(NUMERALS)
        def retain(n):
            numerals.add(n)
            return None
        docs = [vectors.RFC_3_2_2_INPUT, vectors.RFC_3_2_3_INPUT]
        docs += [row[1] for row in vectors.PORTAL_VECTORS]
        docs += [row[0] for row in vectors.CROSS_VECTORS]
        docs += [row[1] for row in vectors.RFC_APPENDIX_B if row[1]]
        docs += ['0.1', '4.50', '1E30', '5e-324', '1e-400', '1e400']
        for doc in docs:
            json.loads(doc, parse_int=retain, parse_float=retain)
        def legacy_float(text):
            value = float(text)
            if not math.isfinite(value) or Decimal(repr(value)) != Decimal(text):
                raise ValueError(text)
            return value
        accepted = 0
        for numeral in sorted(numerals):
            try:
                old = json.loads(numeral, parse_float=legacy_float)
                before = c.canonical_bytes(old)
            except InvalidOperation:  # Newly repaired zero spellings: tested above.
                continue
            except (ValueError, c.CanonicalizationError):
                with self.subTest(refused=numeral):
                    self.assertRaises(c.CanonicalizationError, c.parse_json_strict, numeral)
                continue
            with self.subTest(accepted=numeral):
                value = c.parse_json_strict(numeral)
                self.assertEqual(c.canonical_bytes(value), before)
                self.assertEqual(c.logical_hash(value), vectors.sha(before))
                accepted += 1
        self.assertGreater(accepted, 50)
