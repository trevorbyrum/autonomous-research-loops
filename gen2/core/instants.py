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
literal upper-case Z — the Gregorian date must exist (leap years included)
and the time must be a real time of day (no leap second, no 24:00).
"""
from __future__ import annotations

import re
from datetime import datetime

_SHAPE = re.compile(r"\A(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?Z\Z")


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
