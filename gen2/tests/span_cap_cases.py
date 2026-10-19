"""Literal decimal operands; expected verdicts do not use SQLite/binary64."""
import json
from fractions import Fraction

LIMIT = 9007199254740991
NUMERALS = ('-1', '-0', '0', '0.0', '-0.0', '1', '9007199254740990',
    '9007199254740991', '9007199254740992', '9007199254740993', '9223372036854775809',
    '9007199254740991.0', '9.007199254740991e15', '90071992547409910e-1',
    '9007199254740992.0', '9.007199254740992e15', '9007199254740993e0',
    '9223372036854775809.0', '1e30', '1e999', '1e-999', '0e999',
    '9007199254740991.00000000000000001', '900719925474099099999e-5',
    '0e999999999999999999999', '0e-999999999999999999999',
    '-0.000e+999999999999999999999', '-0.000e-999999999999999999999',
    '1e999999999999999999999', '1e-999999999999999999999')


def number(numeral):
    # Independent rational oracle. Outside this catalog's scale, a nonzero
    # extreme exponent is represented by an equally out-of-domain witness.
    mantissa, _, exponent = numeral.lower().partition('e')
    if not int(mantissa.replace('.', '')):
        return Fraction(0)
    power = int(exponent or '0')
    if abs(power) > 10000:
        return Fraction(10**40) if power > 0 else Fraction(1, 10**40)
    return Fraction(numeral)


def admitted(key, numeral):
    value = number(numeral)
    return value.denominator == 1 and (0 if key == 'start' else 1) <= value <= LIMIT


def literal(key, numeral):
    return json.dumps(
        [{'start': 0, 'end': 1, 'locator': {'kind': 'page', 'value': '2'}}]).replace('"' + key + '": ' + ('0' if key == 'start' else '1'), '"' + key + '": ' + numeral)


def exact_value(raw):
    # Schema validates values. Decode integral decimals to exact integers;
    # never feed it a binary64-rounded interpretation of a refused numeral.
    def exact(n):
        value = number(n)
        return int(value) if value.denominator == 1 else value
    return json.loads(raw, parse_float=exact)
