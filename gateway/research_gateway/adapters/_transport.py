"""HTTP transport and message framing (task 2q-b5; moved out of base.py, unchanged).

The one place a provider's bytes arrive over the network: `Transport` (never raises, never follows a redirect, returns a Response for every outcome), the message framing it enforces
(`_read_body`, `_read_chunked`: a 2xx is a complete message or an error), the redirect rules the client applies to a 3xx (`redirect_target`, `same_origin`, the constants) and the test
transport. It knows nothing of the broker, the call log or the schema; the client (base.py) composes it. The module name starts with `_` because it is a part of the client, not an
adapter (the loader in `adapters/__init__.py` skips such names).
"""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from ._response import Response


MAX_BODY_BYTES = 256 * 1024 * 1024   # a response bigger than this is an error, not a memory event
MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
CREDENTIAL_HEADERS = {"authorization", "x-api-key", "x-dataverse-key", "x-app-token", "cookie"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """3xx answers come back to the metered client instead of being followed underneath it (D-23)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def redirect_target(current_url: str, location: str) -> tuple[str | None, str | None]:
    """(next url, None) when the hop is permitted; (None, reason) otherwise. Permitted means:
    http/https only, no https→http downgrade, and no destination outside global address space —
    every address the hostname resolves to must be global (SSRF guard, D-23). Known residual
    (D-24): the connect after the check re-resolves, so a DNS answer that changes between the
    two lookups could still land elsewhere — pinning the vetted address under stdlib TLS would
    break certificate verification, so the residual is documented instead of half-fixed."""
    try:
        nxt = urllib.parse.urljoin(current_url, location)
        old, new = urllib.parse.urlsplit(current_url), urllib.parse.urlsplit(nxt)
        scheme = (new.scheme or "").lower()
        if scheme not in ("http", "https"):
            return None, f"redirect to scheme {new.scheme!r} refused"
        if old.scheme.lower() == "https" and scheme == "http":
            return None, "redirect downgrades https to http"
        host, port = new.hostname or "", new.port  # .port raises ValueError on a malformed port
    except ValueError as e:
        return None, f"unparseable redirect location ({e})"
    if not host:
        return None, "redirect without a host"
    try:
        addresses = [info[4][0] for info in socket.getaddrinfo(host, port or (443 if scheme == "https" else 80),
                                                               proto=socket.IPPROTO_TCP)]
    except OSError as e:
        return None, f"redirect host does not resolve ({e})"
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            return None, f"redirect host resolves to unparseable address {addr!r}"
        if not ip.is_global:
            return None, f"redirect into a non-global address ({ip}) refused"
    return nxt, None


def same_origin(a: str, b: str) -> bool:
    ua, ub = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    return (ua.scheme, ua.hostname, ua.port) == (ub.scheme, ub.hostname, ub.port)


def header_map(headers) -> dict:
    """Header name (lower-cased) -> value. Field lines that repeat a name are one list-valued field, joined with ", "
    (RFC 9110 §5.3): a dict built line by line kept only the last and dropped the rest, a `Link` relation among them."""
    out: dict = {}
    for name, value in headers.items():
        name = name.lower()
        out[name] = f"{out[name]}, {value}" if name in out else value
    return out


class FramingError(http.client.HTTPException):
    """A response whose message framing is invalid or conflicts with itself (RFC 9112 §6), so that how long its body is cannot be told."""


class BodyTooLarge(Exception):
    """A response body past MAX_BODY_BYTES."""


_DIGITS = re.compile(r"[0-9]+")

_MAX_LINE = 65536     # http.client's own bound on one line of framing
_READ_STEP = 1 << 20  # a chunk is read a megabyte at a time: the size it announces is not memory to reserve
_TOKEN = rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_QUOTED = rb'"(?:[\t \x21\x23-\x5b\x5d-\x7e\x80-\xff]|\\[\t \x21-\x7e\x80-\xff])*"'
_CHUNK_HEAD = re.compile(rb"([0-9A-Fa-f]+)(?:[ \t]*;[ \t]*" + _TOKEN + rb"(?:[ \t]*=[ \t]*(?:" + _TOKEN + rb"|" + _QUOTED + rb"))?)*")   # chunk-size [ chunk-ext ]
_TRAILER_FIELD = re.compile(_TOKEN + rb":[\t \x21-\x7e\x80-\xff]*")                                                                  # field-line


def _read_chunked(fp) -> bytes:
    """The body of a chunked message (RFC 9112 §7.1), read here and not by http.client. Its decoder takes `int(line, 16)` for a size (`+0` and `0x0` pass), never looks at the CRLF after a chunk's
    data, and takes EOF for the end of the trailer section: a message cut after a chunk, or inside the last-chunk line, or inside the trailer, arrives as a whole one (task 2b-repair-15; Astra F1).

        chunked-body = *chunk last-chunk trailer-section CRLF     chunk = chunk-size [ chunk-ext ] CRLF chunk-data CRLF
        chunk-size   = 1*HEXDIG                                   last-chunk = 1*("0") [ chunk-ext ] CRLF

    The body is complete when its final CRLF has arrived. EOF anywhere before it is IncompleteRead, and what the grammar does not allow (a size that is not 1*HEXDIG, a chunk's data not followed by CRLF,
    a line ended by a bare LF, a trailer line that is no field line) is FramingError: neither returns a body. Extensions and trailer fields have to be well-formed, and are not read. The data is held
    to MAX_BODY_BYTES like every body, and the trailer section to the same: a chunk that announces more than is left is refused before any of it is read."""
    pieces: list[bytes] = []
    total = 0

    def line(what: str) -> bytes:
        got = fp.readline(_MAX_LINE + 1)
        if len(got) > _MAX_LINE:
            raise FramingError(f"chunked framing: {what} is longer than {_MAX_LINE} bytes")
        if not got.endswith(b"\n"):
            raise http.client.IncompleteRead(b"".join(pieces))   # the connection ended inside the line
        if not got.endswith(b"\r\n"):
            raise FramingError(f"chunked framing: {what} ends in a bare LF (RFC 9112 §7.1)")
        return got[:-2]

    while True:
        head = line("a chunk-size line")
        match = _CHUNK_HEAD.fullmatch(head)
        if match is None:
            raise FramingError(f"chunked framing: {head[:40]!r} is no chunk size (1*HEXDIG, then extensions: RFC 9112 §7.1)")
        size = int(match.group(1), 16)
        if size == 0:
            break
        total += size
        if total > MAX_BODY_BYTES:
            raise BodyTooLarge(f"the chunks announce more than {MAX_BODY_BYTES} bytes")
        left = size
        while left:
            piece = fp.read(min(left, _READ_STEP))
            if not piece:
                raise http.client.IncompleteRead(b"".join(pieces), left)
            pieces.append(piece)
            left -= len(piece)
        end = fp.read(2)
        if len(end) < 2:
            raise http.client.IncompleteRead(b"".join(pieces))
        if end != b"\r\n":
            raise FramingError(f"chunked framing: a chunk's data is followed by {end!r}, not CRLF (RFC 9112 §7.1)")
    seen = 0
    while True:   # the trailer section: field lines up to the empty line that ends the message
        field = line("a trailer line")
        if not field:
            return b"".join(pieces)
        seen += len(field) + 2
        if seen > MAX_BODY_BYTES:
            raise BodyTooLarge(f"the trailer section is past {MAX_BODY_BYTES} bytes")
        if _TRAILER_FIELD.fullmatch(field) is None:
            raise FramingError(f"chunked framing: {field[:40]!r} is no trailer field (RFC 9112 §7.1.2)")


def _read_body(resp) -> bytes:
    """The whole body of a response, or an exception: a body that is not the message the response's own framing described is never returned as if it were (task 2b-repair-14; Astra F1).

    RFC 9112 §6.3 says how long a message is: bodyless for 204 and 304; else chunked when Transfer-Encoding is `chunked`, which ends at the final CRLF after the last chunk and its trailer section (§7.1);
    else the Content-Length (§6.2; RFC 9110 §8.6); else, for a response, whatever arrives before the connection closes. http.client settles which of these a response has; its bounded `read(amt)`
    returns what arrived at EOF without saying whether the framing was met, so the framing it settled on is checked first (it is lenient — `int("1_0")` is a length of ten, a Content-Length list is no
    length at all and a body then runs to EOF), and its state read after, since CPython only raises IncompleteRead on an unbounded read. A chunked body is not read by http.client at all (`_read_chunked`).

      * Transfer-Encoding with Content-Length: refused (§6.3 item 3: the message may be an attempt at smuggling or splitting); a Transfer-Encoding that is not exactly `chunked`: refused,
        no other transfer coding is read; several Content-Length fields, or one that is not digits: refused (§6.3 item 5 lets a recipient merge identical values; this one does not).
      * FramingError when the library's reading of the headers is not the one just made. IncompleteRead when the Content-Length is not met, or the chunked framing is not complete (`_read_chunked`).
        BodyTooLarge past MAX_BODY_BYTES — checked on the declared length first, so a body that announces more is not read at all.
      * A response with neither header is close-delimited: EOF ends it, and EOF cannot tell a deliberately shorter body from an interrupted one (§6.3 item 8). That is accepted — it is
        what HTTP says of such a message — and is the one framing in which a connection cut at a record boundary is a well-formed shorter document."""
    if resp.status not in (204, 304):
        encodings, lengths = resp.headers.get_all("Transfer-Encoding", []), resp.headers.get_all("Content-Length", [])
        if encodings and lengths:
            raise FramingError("a response with both Transfer-Encoding and Content-Length: its framing is ambiguous (RFC 9112 §6.3)")
        if encodings and [c.strip().lower() for v in encodings for c in v.split(",")] != ["chunked"]:
            raise FramingError(f"Transfer-Encoding {encodings!r}: only `chunked` is read (RFC 9112 §6.1)")
        if lengths and (len(lengths) > 1 or not _DIGITS.fullmatch(lengths[0].strip())):
            raise FramingError(f"Content-Length {lengths!r} is not one number of digits (RFC 9110 §8.6)")
        declared = int(lengths[0]) if lengths else None
        if resp.chunked != bool(encodings) or resp.length != declared:
            raise FramingError(f"the library read this response's framing as chunked={resp.chunked}, length={resp.length}, not as its headers state")
        if declared is not None and declared > MAX_BODY_BYTES:
            raise BodyTooLarge(f"Content-Length {declared} is past {MAX_BODY_BYTES}")
    if resp.chunked:
        return _read_chunked(resp.fp)
    data = resp.read(MAX_BODY_BYTES + 1)
    if len(data) > MAX_BODY_BYTES:
        raise BodyTooLarge(f"more than {MAX_BODY_BYTES} bytes")
    if resp.length:   # a Content-Length with bytes still to come: the connection ended before the message did
        raise http.client.IncompleteRead(data, resp.length)
    return data


class Transport:
    """Real network transport. Never raises and never follows redirects: every outcome —
    including a 3xx, an oversized body, a body that ends before its framing says it should, or a mid-read failure — is a Response, so the
    caller's accounting and logging always run (I-6). A 2xx is returned only for a complete message (`_read_body`); an error status keeps its status
    whatever happens to its body."""

    def request(self, method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> Response:
        try:
            req = urllib.request.Request(url, data=body, method=method, headers=headers)
        except Exception as e:  # a URL the stdlib refuses to even build is an error Response too
            return Response(None, {}, b"", url, error=f"{type(e).__name__}: {e}")
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                try:
                    data = _read_body(resp)
                except BodyTooLarge:
                    return Response(None, header_map(resp.headers), b"", url,
                                    error=f"response exceeds {MAX_BODY_BYTES} bytes")
                return Response(resp.status, header_map(resp.headers), data, url)
        except urllib.error.HTTPError as e:
            try:
                payload, why = _read_body(e.fp), None
            except Exception as problem:   # the status stands; the body is not trusted, and the response says why it is not here
                payload, why = b"", f"HTTP {e.code}, body unusable: {type(problem).__name__}: {problem}"
            return Response(e.code, header_map(e.headers), payload, url, error=why)
        except Exception as e:  # URLError, timeouts, IncompleteRead, FramingError, TLS errors, anything: an error Response
            return Response(None, {}, b"", url, error=f"{type(e).__name__}: {e}")


class FakeTransport:
    """Test transport: canned responses matched by (method, url-prefix)."""

    def __init__(self):
        self.routes: list[tuple[str, str, Response]] = []
        self.calls: list[tuple[str, str, dict, bytes | None]] = []

    def add(self, method: str, url_prefix: str, status: int = 200, body: bytes | str | dict | list = b"",
            headers: dict | None = None) -> None:
        if isinstance(body, (dict, list)):
            import json
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.routes.append((method.upper(), url_prefix, Response(status, {k.lower(): v for k, v in (headers or {}).items()}, body, url_prefix)))

    def request(self, method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> Response:
        self.calls.append((method.upper(), url, headers, body))
        for m, prefix, resp in self.routes:
            if m == method.upper() and url.startswith(prefix):
                return Response(resp.status, resp.headers, resp._body, url)
        return Response(404, {}, b"", url)
