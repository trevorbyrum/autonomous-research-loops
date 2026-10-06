"""The client's response: what it received of one call (task 2q-b5; moved out of base.py, unchanged).

`Response` is the one carrier of a provider's bytes into the adapters, so the transport builds it, the client reads and logs it and the Link reader takes it. It is in a module of its own so
that those three depend on it and not on one another: `_transport.py` and `_links.py` import nothing of the client, and base.py imports both. The module name starts with `_` because it is
a part of the client, not an adapter (the loader in `adapters/__init__.py` skips such names).
"""
from __future__ import annotations

import datetime
import email.utils
import time

from ..core.payload import Sealed, SealedAnswer


class Response(SealedAnswer):
    """What the client received: the status, the headers, the URL and any error — and the answer's bytes, which the public API gives an adapter no way to read.

    There is no `.json`, `.text` or `.body`: the payload is opened by `decode` (base.py, core/schema.py), so an adapter that wants to know what a provider said asks the declared schema, and
    the public operations give a payload decision no raw value (2b-repair-13a: Astra's `getattr(resp, "json")` has nothing to find; the private `_body` is a documented boundary of trust
    model B, INVARIANTS B-1, and tests/inventory.py lists every read of it). The one other public way to the bytes is `download()`, for the file a caller asked to download: content, not
    a payload — and since 2b-repair-13c a `Sealed` one, which an adapter can hand to the router and not read (the inventory lists every use).

    What the client (base.py) reads of the bytes, for its own purposes and never to say what a provider's data is: `check()` looks at the first bytes of a success answer to refuse an
    HTML page wearing it (it can only make a lane unavailable); `_text_of` reads a 401/403 body to classify the failure; `_count_of` counts results for the call log, through the
    decoder's own opener (core/wire.py). The decoder's openers are the only reading of a payload that can produce a record or an answer."""
    __slots__ = ("status", "headers", "url", "error")

    def __init__(self, status: int | None, headers: dict, body: bytes, url: str, error: str | None = None):
        super().__init__(body)
        self.status, self.headers, self.url, self.error = status, headers, url, error

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    def download(self) -> Sealed:
        """The bytes of a file the caller asked to download (a data file, a PDF), sealed: content that is handed on and never parsed or decided on. It becomes bytes where the router
        serializes the answer (core/payload.py)."""
        return Sealed(self._body)

    def __repr__(self) -> str:
        return f"<Response {self.status} {self.url!r} {len(self._body)} bytes>"

    def retry_after_seconds(self) -> float | None:
        """How long the provider asks to be left alone, or None when the header is absent or says nothing readable (RFC 9110 §10.2.3).

        A DELAY is `delay-seconds`: ASCII digits and nothing else (`float()` read `inf`, which holds a breaker open for ever, and `nan`, `-5`, `1e3`, `1_0` and Arabic-Indic digits: none is a delay).
        A DATE is whatever `email.utils.parsedate_to_datetime` reads — a tolerant parser of the RFC 5322 family, deliberately not a second parser for the HTTP-date grammar (RFC 9110 §5.6.7 itself
        asks recipients to be robust). Its actual tolerance, which is the contract: the three HTTP-date forms (IMF-fixdate, the obsolete RFC 850 form, asctime); also a numeric zone (`+0200`), the
        zone names the library knows (`PST`), a date with no weekday or with a wrong one (the weekday is not checked), full or lower-case month and zone names, seconds left out, and text after the
        zone (ignored); a two-digit year by the library's rule (69–99 are 19xx, 00–68 are 20xx), not RFC 9110's fifty-year window. Not read: ISO 8601, words, a day or hour out of range, a date
        with no time. A date with no zone (asctime, `-0000`) is GMT — HTTP dates are — and never the host's local time. A date already past is a delay of zero; a date far ahead is the delay
        it says, unbounded: the breaker honours whatever finite delay a provider states (core/broker.py), as it does a digit string of any length that a double holds."""
        v = self.headers.get("retry-after") or self.headers.get("Retry-After")
        v = v.strip() if isinstance(v, str) else v
        if not v:
            return None
        if v.isascii() and v.isdigit():
            try:
                return float(int(v))
            except (ValueError, OverflowError):   # more digits than int() converts, or more seconds than a double holds
                return None
        try:  # the header's other legal form is an HTTP-date (RFC 9110)
            when = email.utils.parsedate_to_datetime(v)
            if when.tzinfo is None:   # asctime and `-0000` name no zone: an HTTP date is GMT, and timestamp() of a zone-less datetime reads the host's local time
                when = when.replace(tzinfo=datetime.timezone.utc)
            return max(0.0, when.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None
