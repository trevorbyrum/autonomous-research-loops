"""The byte openers: where a provider's bytes become structure (task 2b-repair-13c; the supported-format policy frozen in 2b-repair-14 by the operator's ruling of 2026-10-02).

Everything the gateway decides from a provider's answer starts as bytes, and the decoder (core/schema.py) validates what a lexer has already turned into values. Until
2b-repair-13c that lexer was each format's library at its default, and every default resolves malformed input instead of refusing it: Python's `csv` ends a quoted
field at the end of the data and reads text after a closing quote as part of the cell; `json` keeps the last of two equal names and reads `NaN`, `Infinity`, `1e999`
and UTF-16; ElementTree was handed text from which invalid bytes had been replaced with U+FFFD and in which a declared encoding had been ignored. A malformed dump
became a definite answer — zero journals — before any schema could see that something was wrong (Astra, R13A-1).

An opener is therefore a layer with a contract of its own, judged against the format's specification. Each function here either returns what the bytes say, read one way,
or raises `Malformed`; none picks a reading. The decoder turns `Malformed` into the one channel (PayloadError). The inventory of every place the gateway opens bytes, with its
classification, is tests/inventory.py (held by tests/test_inventory.py); it fails on a parse call that is not listed.

THE SUPPORTED CONTRACT. These rules are the supported-format and resource policy (STATION-CONTRACT.md, "The supported provider-input contract"): input outside it fails visibly — the lane is
unavailable — and is never read as something shorter. They are the gateway's policy, not a claim that every provider uses exactly this subset: which live providers do is Phase 4's to qualify.

  JSON  (RFC 8259)   UTF-8 only (§8.1; a leading byte order mark is ignored, which §8.1 allows); `NaN`, `Infinity` and `-Infinity` are not JSON (§6); a name that occurs twice in one object is
                     refused (§4: the behaviour of software that receives it is unpredictable, so no reading is chosen, and the record's `raw` never silently loses a value); nesting deeper
                     than MAX_DEPTH (64) is refused. NUMBERS (§6 leaves range and precision to the receiver): an INTEGER (no fraction, no exponent) is read exactly, of any size up to Python's
                     integer-conversion limit (4,300 digits by default; a longer one is refused as not JSON); any other number is read as a DOUBLE — finite, or refused (`1e999` is never read as
                     infinity), with a double's precision (a literal too small for one underflows to 0.0). Accepted as they are: a lone surrogate escape (the grammar allows it, §8.2), a top-level
                     scalar (§2), a `-0`.
  XML   (XML 1.0)    well-formedness is expat's, and strict; the bytes are UTF-8 and read as that — an invalid byte is an error, not U+FFFD, and a declaration of any other
                     encoding is refused rather than ignored; the declaration's version must be `1.` and digits (§2.8: expat reads `2.0`, `1` and `abc`); a document type
                     declaration is refused (the supported messages have none, and an external subset or a parameter entity would be skipped without a word, §4.4.3); nesting
                     deeper than MAX_DEPTH (64) is refused. Namespaces are not this layer's: it returns the tree with each tag `{uri}local`, and the decoder (core/schema.py) holds a field to the
                     namespaces it names.
  CSV   (RFC 4180)   a quoted field must be closed (§2.7) and be followed by a comma or the end of the line (§2.6); a quote may not appear inside an unquoted field (§2.5); a
                     carriage return OUTSIDE a quoted field is half of CRLF or it is refused (§2.1 — inside a quoted field it is data); UTF-8 only. Accepted, and why: a line ending of LF alone and a
                     last line with no ending (de facto, and no reading of either is ambiguous); a blank line (no record — what the csv module and every dump reader does); a field of any Unicode
                     text (the RFC's TEXTDATA is ASCII, which no real dump is); a short row and a row with extra cells (the decoder's policy, core/schema.py: a missing cell is nothing, an extra one
                     is kept in the row's raw and never read); a cell of at most CELL_LIMIT (131,072) characters (the csv module's own limit). A byte order mark is data in CSV (the RFC says nothing
                     of one): it stays the first character of the first cell, so a header that starts with one names no column the loader needs — as it always did.

What no opener can do: a truncation that ends exactly at a record's end is a well-formed shorter document. HTTP's own message framing is the transport's (adapters/base.py `_read_body`:
a body shorter than its Content-Length, or a chunked body with no terminal chunk, is an error Response; tests/test_transport_framing.py), not a CSV rule — and a close-delimited body, whose
only end is the connection closing, cannot be told from a deliberately shorter one (RFC 9112 §6.3).
"""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from typing import Any

from .payload import MAX_DEPTH

CELL_LIMIT = 131_072   # the csv module's own default field limit; a cell past it is a refusal, not a long cell


class Malformed(ValueError):
    """Bytes that are not a document of their format, read any one way: the opener's own words for why. Not a PayloadError: the decoder turns it into one, with the answer's
    context. `syntax` is whether the format's grammar alone refuses the bytes — what the library's default reading refused before too, so the answer's error text for it is
    unchanged (the engine's recorded fixtures pin it) — as against a refusal of something the default reading took for data, which says why."""

    def __init__(self, reason: str, *, syntax: bool = False):
        super().__init__(reason)
        self.syntax = syntax


def _text(body, what: str, *, bom: bool = True) -> str:
    """The bytes as UTF-8 text, strictly: an invalid sequence — an encoded surrogate included — is a refusal, never a replacement character. A leading byte order mark is dropped for the
    formats that say a parser may (JSON, RFC 8259 §8.1; XML, whose grammar allows it); CSV has no such rule, so there it stays what it is, the first character of the first cell."""
    if isinstance(body, str):
        text = body
    else:
        try:
            text = bytes(body).decode("utf-8")
        except UnicodeDecodeError as e:
            raise Malformed(f"{what} is not UTF-8 ({e.reason} at byte {e.start})") from None
    return text[1:] if bom and text.startswith("\ufeff") else text


# ------------------------------------------------------------------ JSON (RFC 8259)
def _refuse_constant(name: str):
    raise Malformed(f"the token {name} is not JSON (RFC 8259 §6)")


def _names_once(pairs: list) -> dict:
    out = dict(pairs)
    if len(out) != len(pairs):   # the common case costs one comparison; the pass that names the culprit runs only for a document that is refused
        seen = set()
        for name, _ in pairs:
            if name in seen:
                raise Malformed(f"the name {name[:40]!r} occurs twice in one object (RFC 8259 §4: no reading of it is defined)")
            seen.add(name)
    return out



def open_json(body) -> Any:
    """The value of a JSON text, read one way (see the module docstring). Malformed for anything else, nesting past MAX_DEPTH and a float literal that overflows a double (`1e999`) included; an integer is read exactly."""
    text = _text(body, "JSON")
    try:
        value = json.loads(text, object_pairs_hook=_names_once, parse_constant=_refuse_constant)
    except Malformed:
        raise
    except RecursionError:   # nesting past the interpreter's own limit is not JSON any provider sends
        raise Malformed(f"JSON nested more than {MAX_DEPTH} levels deep") from None
    except ValueError as e:
        raise Malformed(f"not JSON: {e}", syntax=True) from None
    _check_shape(value, MAX_DEPTH)
    return value


def _check_shape(value, limit: int) -> None:
    """One pass over what was parsed, counted without recursion — which is the point: nothing later walks a structure this answer holds with more depth than `limit` (the root is level 1),
    whatever it does with it (store it, copy it, serialise it) — that also finds the numbers the library read as infinity (`1e999`: the grammar allows the literal, RFC 8259 §6 leaves the
    range to the receiver, and reading it as infinity is a guess; json.dumps would write it back as the non-JSON `Infinity`). Malformed for either."""
    if type(value) is float and not math.isfinite(value):
        raise Malformed("a number does not fit a double (RFC 8259 §6)")
    stack = [(value, 1)]
    pop, push, finite = stack.pop, stack.append, math.isfinite
    while stack:
        v, depth = pop()
        if depth > limit:
            raise Malformed(f"JSON nested more than {limit} levels deep")
        if type(v) is dict:
            children = v.values()
        elif type(v) is list:
            children = v
        else:
            continue   # a scalar at the root
        for child in children:
            kind = type(child)
            if kind is dict or kind is list:
                push((child, depth + 1))
            elif kind is float and not finite(child):
                raise Malformed("a number does not fit a double (RFC 8259 §6 leaves the range to the receiver; reading it as infinity is a guess)")


# ------------------------------------------------------------------ XML (XML 1.0)
_DECLARATION = re.compile(r"<\?xml(?=[ \t\r\n])(.*?)\?>", re.S)
_PSEUDO_ATTRIBUTE = re.compile(r"""[ \t\r\n]+([A-Za-z]+)[ \t\r\n]*=[ \t\r\n]*(?:"([^"]*)"|'([^']*)')""")
_VERSION = re.compile(r"1\.[0-9]+")


class _NoDoctype(ET.TreeBuilder):
    """The tree builder, which refuses a document type declaration where expat would read an internal subset and skip an external one."""

    def doctype(self, name, pubid, system):
        raise Malformed("a document type declaration (DOCTYPE): the supported messages have none, and expat would skip an external subset without a word (XML 1.0 §4.4.3)")


def _check_declaration(text: str) -> None:
    """What expat leaves unchecked of an XML declaration: its version must be `1.` and digits (XML 1.0 §2.8, production [26]), and the encoding it names is the one the bytes were
    read as. (expat checks the rest — a missing version, the order of the parts, `standalone`.)"""
    found = _DECLARATION.match(text)
    if not found:
        return
    parts = {m.group(1): m.group(2) if m.group(2) is not None else m.group(3) for m in _PSEUDO_ATTRIBUTE.finditer(found.group(1))}
    version = parts.get("version")
    if version is not None and not _VERSION.fullmatch(version):
        raise Malformed(f"the XML declaration's version {version[:20]!r} is not 1.x (XML 1.0 §2.8)")
    encoding = parts.get("encoding")
    if encoding is not None and encoding.lower() != "utf-8":
        raise Malformed(f"the XML declaration names the encoding {encoding[:20]!r}; the supported documents are UTF-8")


def open_xml(body) -> ET.Element:
    """The root element of an XML document, read one way (see the module docstring). Malformed for anything else."""
    text = _text(body, "the XML document")
    _check_declaration(text)
    parser = ET.XMLParser(target=_NoDoctype())
    try:
        parser.feed(text)
        root = parser.close()
    except ET.ParseError as e:
        raise Malformed(f"not well-formed XML: {e}") from None
    except RecursionError:
        raise Malformed("XML too deeply nested to read") from None
    stack = [(root, 1)]
    while stack:   # counted without recursion, like JSON's: serialising a deeper tree would recurse
        element, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise Malformed(f"XML nested more than {MAX_DEPTH} levels deep")
        stack.extend((child, depth + 1) for child in element)
    return root


# ------------------------------------------------------------------ CSV (RFC 4180)
_QUOTED = re.compile(r'"([^"]*(?:""[^"]*)*)"')   # a quoted field: no backtracking, linear in the field
_UNQUOTED = re.compile(r'[^",\r\n]*')


def open_csv(body) -> list[list[str]]:
    """The records of a CSV document, each a list of its cells, read one way (see the module docstring). A blank line is the empty record `[]`, as the csv module reads it; the first
    record is the header, and whether a row is too short or too long for it is the caller's."""
    text = _text(body, "the CSV", bom=False)   # a byte order mark is the first character of the first cell, as it always was: a header that names no column the loader needs
    n, i, line, records = len(text), 0, 1, []
    while i < n:
        row, quoted = [], False
        while True:
            if text.startswith('"', i):
                found = _QUOTED.match(text, i)
                if found is None:
                    raise Malformed(f"line {line}: a quoted field is not closed (RFC 4180 §2.7)")
                cell, quoted, line, i = found.group(1).replace('""', '"'), True, line + found.group(0).count("\n"), found.end()
            else:
                found = _UNQUOTED.match(text, i)
                cell, quoted, i = found.group(), False, found.end()
            if len(cell) > CELL_LIMIT:
                raise Malformed(f"line {line}: a cell of more than {CELL_LIMIT} characters")
            row.append(cell)
            if i >= n:
                break
            char = text[i]
            if char == ",":
                i += 1
                continue
            if char == "\n" or text.startswith("\r\n", i):
                i += 1 if char == "\n" else 2
                line += 1
                break
            if char == "\r":
                raise Malformed(f"line {line}: a carriage return that does not end the line (RFC 4180 §2.1)")
            raise Malformed(f"line {line}: " + ("text after a closing quote (RFC 4180 §2.6)" if quoted else "a quote inside an unquoted field (RFC 4180 §2.5)"))
        records.append([] if row == [""] and not quoted else row)
    return records
