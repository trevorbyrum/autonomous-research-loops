"""RFC 3339 UTC instants, validated as real calendar instants.

Trace: Astra 0a review A11 ("validate calendar instants at the boundary and
say which layer does it"); common.schema.json#/$defs/timestamp; INVARIANTS
C-2 (typed envelopes at the router boundary).

Layer: this function is the single timestamp validator. The router's
schema-validation boundary applies it to every `format: "date-time"` field
(Phase 1), and tools/check_gen2_schemas.py registers it as the `date-time`
format checker so the schema fixtures exercise the same rule today. The
schema's `pattern` is only a shape pre-filter (it admits February 31); the
store DDL keeps router-validated text and does not re-validate it.

Accepted form: YYYY-MM-DDTHH:MM:SS with an optional 1-9 digit fraction and a
literal upper-case Z, ASCII digits only — the Gregorian date must exist (leap
years included; any year 0001-9999) and the time must be a real time of day
(no leap second, no 24:00).
"""
from __future__ import annotations

import re
from datetime import date, datetime

# ASCII digits only ([0-9], not \d, which matches every Unicode decimal digit
# and so would admit what the schema's ASCII pattern refuses — Astra
# re-review, non-blocking cleanup).
_SHAPE = re.compile(r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,9})?Z\Z")


def is_utc_instant(value: object) -> bool:
    """True iff value is an RFC 3339 UTC timestamp naming a real instant."""
    if not isinstance(value, str):
        return False
    match = _SHAPE.match(value)
    if match is None:
        return False
    try:
        datetime(*(int(part) for part in match.groups()))
    except ValueError:
        return False
    return True


def utc_instant_ns(value: object) -> int:
    """The instant as exact nanoseconds since 1970-01-01T00:00:00Z, for
    comparing instants (task 1b: lease expiry, deadlines). Text order is not
    time order once fractions differ in length ("...:00.5Z" sorts after
    "...:00.25Z" but so does "...:00Z" after "...:00.1Z"), and a float would
    round a 9-digit fraction, so the fraction is kept as an integer.
    ValueError unless is_utc_instant(value)."""
    if not is_utc_instant(value):
        raise ValueError(f"{value!r} is not an RFC 3339 UTC instant")
    year, month, day, hour, minute, second = (int(part) for part in _SHAPE.match(value).groups())
    fraction = value[20:-1] if value[19] == "." else ""
    days = (date(year, month, day) - date(1970, 1, 1)).days
    return (days * 86400 + hour * 3600 + minute * 60 + second) * 10**9 + int(fraction.ljust(9, "0"))
