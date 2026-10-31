"""Result codec for dossier/2; the Router builds and validates the envelope.

encode returns the result member only. decode accepts that member from a
schema-validated document (including integral JSON number spellings).
The field walker refuses unknown/missing fields; schema validation at the
Router boundary supplies enum, integer-bound and tagged-union validation.
"""
from dataclasses import fields, is_dataclass
from fractions import Fraction
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from gen2.accounting import stopping as s


def encode(value):
    if is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in fields(value) if f.name not in ("schema_version",)}
    if isinstance(value, Fraction):
        return {"numerator": value.numerator, "denominator": value.denominator}
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, tuple):
        return [encode(v) for v in value]
    return value


def decode(result: dict) -> s.ProfileResult:
    return _decode(result, s.ProfileResult)


def _decode(value, hint):
    if value is None:
        return None
    origin, args = get_origin(hint), get_args(hint)
    if origin is UnionType:
        return _decode(value, next(t for t in args if t is not type(None)))
    if origin in (tuple, frozenset):
        return origin(_decode(v, args[0]) for v in value)
    if hint is Fraction:
        return Fraction(int(value["numerator"]), int(value["denominator"]))
    if is_dataclass(hint):
        hints = get_type_hints(hint)
        names = {f.name for f in fields(hint) if f.name not in ("schema_version",)}
        if set(value) != names:
            raise ValueError("result fields differ from the dossier/2 contract")
        if hint is s.RuleResult:
            hints["operands"] = {"descriptive": s.DescriptiveOperands, "coverage": s.CoverageOperands,
                                 "known_item": s.KnownItemOperands}[value["evaluator"]]
        return hint(**{name: _decode(value[name], hints[name]) for name in names})
    return value
