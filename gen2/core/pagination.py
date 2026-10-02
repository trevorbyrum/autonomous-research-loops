"""The page observation's vocabulary and the cursor domain (task 2b-repair-13d; Astra R13B-2). No I/O.

ONE definition for the client that produces observations (gen2/gateway_client/observe.py) and the router that
admits them (gen2/router/boundary.py, and the vocabulary of its command schema). The store's DDL says the same
in SQL (gen2/store/schema/03-evidence-and-decisions.sql, `search_observations`), which cannot import this, so
gen2/tests/test_admission.py holds the two equal case by case.

A page observation says WHICH request it answers (`request.request.request_type`, one of REQUEST_TYPES) because
what `end_unknown` means depends on it: for a `find`, which pages, the page's end is not known (more may remain);
for any other request type, which does not page, there is no end to know. Only a paged request can say that a
population is `exhausted`, or hand back a `continuation` or reach a `limit_reached`.
"""
from __future__ import annotations

from gen2.core import canonical

REQUEST_TYPES = ("find", "resolve", "enrich", "fetch", "data")   # the gateway's request kinds (gateway/docs/STATION-CONTRACT.md)
PAGED_REQUEST_TYPES = ("find",)                                  # the only one whose answers page
PAGE_OUTCOMES = ("exhausted", "continuation", "end_unknown", "limit_reached", "failed")
PAGING_OUTCOMES = ("exhausted", "continuation", "limit_reached")   # what only a paged request's answer can say
EXHAUSTED_CURSOR = "exhausted"   # the gateway's `next` sentinel for a finished lane: never a cursor
CURSOR_MAX_CHARS = 8000          # the longest cursor kept (the schema's long_text)


def request_type(request: object) -> str | None:
    """The request type of an observation's attempted-request document ({"lane", "page", "request": {"request_type", ...}}), if
    it names one from the closed set; None otherwise (a missing, mistyped or invented type)."""
    inner = request.get("request") if isinstance(request, dict) else None
    kind = inner.get("request_type") if isinstance(inner, dict) else None
    return kind if isinstance(kind, str) and kind in REQUEST_TYPES else None


def cursor_problem(cursor: object) -> str | None:
    """Why `cursor` cannot be kept or sent as a cursor, or None when it can: an integer from 0 to the JSON bound, or a string of 1 to
    CURSOR_MAX_CHARS characters, none of them NUL, that is not the finished-lane sentinel. A boolean, a float, null or anything else is no
    cursor (and so, for the client, no continuation and no end either)."""
    if type(cursor) is int:
        return None if 0 <= cursor <= canonical.INT_BOUND else f"the integer {cursor} is outside 0..{canonical.INT_BOUND}"
    if type(cursor) is str:
        if not 1 <= len(cursor) <= CURSOR_MAX_CHARS:
            return f"a cursor string is 1..{CURSOR_MAX_CHARS} characters, not {len(cursor)}"
        if "\x00" in cursor:
            return "a cursor string holds no NUL"
        if cursor == EXHAUSTED_CURSOR:
            return f"{EXHAUSTED_CURSOR!r} is the sentinel of a finished lane, not a cursor"
        return None
    return f"a {type(cursor).__name__} is no cursor"
