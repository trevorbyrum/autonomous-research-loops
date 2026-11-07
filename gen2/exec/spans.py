"""Locate a quote in the staged response by structure: the selected record's `abstract` string, mapped to exact byte offsets.

Trace: Astra #140 F1; V-6 (the engine computes the match from operands; the builder only supplies the span); flow S4.8. The staged
response is canonical JSON, so the abstract is stored with JSON escapes. This finds the string token of the `abstract` field of the
record whose `identity` is the selected one (by field, never a global first match: a key, another record or another field with the
same text is not it), decodes it keeping, for every decoded character, the byte range of its encoding, finds the quote in the
decoded text, and returns the encoded byte span. An escape elsewhere in the abstract does not matter.
Oracle: the raw slice must equal the quote's UTF-8 bytes, which is exactly what `quote_matching.check_quote` compares. Limits: a
quote that itself contains an escaped character (a quote mark, backslash, newline, tab) has a raw slice that differs from its text,
so it is refused: matching is not weakened, escapes are not stripped, nothing is re-hashed or relabelled. Supporting such quotes needs
a decoded-content matching route in the router (lane A), described in the PR, not built here.
"""
from __future__ import annotations

import json

from gen2.exec.common import Refused

ESCAPES = {ord(c): chr(v) for c, v in {'"': 0x22, "\\": 0x5C, "/": 0x2F, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9}.items()}


def _string_end(data: bytes, i: int) -> int:
    """The index just past the string token that starts at data[i] (an opening quote)."""
    i += 1
    while data[i] != 0x22:
        i += 2 if data[i] == 0x5C else 1
    return i + 1


def _value_end(data: bytes, i: int) -> int:
    if data[i] == 0x22:
        return _string_end(data, i)
    if data[i] in b"{[":
        closer = 0x7D if data[i] == 0x7B else 0x5D
        i += 1
        while data[i] != closer:
            if data[i] in b",:":
                i += 1
            else:
                i = _value_end(data, i)
                if closer == 0x7D and data[i] == 0x3A:   # a key: its value follows
                    i = _value_end(data, i + 1)
        return i + 1
    while data[i] not in b",]}":
        i += 1
    return i


def _members(data: bytes, i: int):
    """(key, value_start, value_end) for each member of the object that starts at data[i]."""
    i += 1
    while data[i] != 0x7D:
        if data[i] == 0x2C:
            i += 1
            continue
        key_end = _string_end(data, i)
        start = key_end + 1
        yield json.loads(data[i:key_end]), start, _value_end(data, start)
        i = _value_end(data, start)


def abstract_token(data: bytes, identity: str) -> tuple[int, int]:
    """The byte range [start, end) of the `abstract` string token (quotes included) of the record with this identity."""
    def records_of(start: int):
        for key, a, b in _members(data, start):
            if key == "records" and data[a] == 0x5B:
                i = a + 1
                while data[i] != 0x5D:
                    if data[i] == 0x2C:
                        i += 1
                        continue
                    end = _value_end(data, i)
                    yield i, end
                    i = end
            elif key == "gateway_response" and data[a] == 0x7B:   # the T12-G fixture's wrapped form, as views.abstract_of reads it
                yield from records_of(a)
    try:
        for start, end in records_of(0):
            members = {key: (a, b) for key, a, b in _members(data, start)}
            if "identity" in members and "abstract" in members and json.loads(data[slice(*members["identity"])]) == identity:
                a, b = members["abstract"]
                if data[a] == 0x22:
                    return a, b
    except (IndexError, ValueError):
        pass
    raise Refused(f"the staged response has no abstract string for {identity}")


def decode(token: bytes) -> tuple[str, list[tuple[int, int]]]:
    """(the decoded string, and for each decoded character the (start, end) offsets of its encoding within `token`)."""
    text, ranges, i, end = [], [], 1, len(token) - 1
    while i < end:
        start = i
        if token[i] == 0x5C:
            code = token[i + 1]
            if code == 0x75:
                char, i = chr(int(token[i + 2:i + 6], 16)), i + 6   # RFC 8785 writes only control characters this way (never a surrogate pair)
            else:
                char, i = ESCAPES[code], i + 2
        else:
            size = 1 if token[i] < 0x80 else 2 if token[i] < 0xE0 else 3 if token[i] < 0xF0 else 4
            char, i = token[i:i + size].decode("utf-8"), i + size
        text.append(char)
        ranges.append((start, i))
    return "".join(text), ranges


def locate(data: bytes, identity: str, content: str, quote: str) -> tuple[int, int]:
    """The half-open byte span of `quote` inside the selected record's abstract, whose decoded text must be `content`."""
    a, b = abstract_token(data, identity)
    decoded, ranges = decode(data[a:b])
    at = decoded.find(quote) if quote else -1
    if decoded != content or at < 0:
        raise Refused("a cited quote is not in the retained abstract the verifier was shown")
    start, end = a + ranges[at][0], a + ranges[at + len(quote) - 1][1]
    if data[start:end] != quote.encode("utf-8"):
        raise Refused("a cited quote contains a character the JSON encoding escapes; quoting across an escape is not supported")
    return start, end
