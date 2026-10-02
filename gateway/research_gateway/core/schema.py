"""Declared payload schemas and the one decoder (task 2b-repair-12; the cause is explained in core/payload.py).

A schema is plain data, built from the constructors below, declared once per operation in its adapter module. It says, for the
payload the operation supports: each field's type, which containers are lists of independent members, which fields are required
and which may be left out, which fields are alternatives of one another, and any rule that ties fields together. `decode`
checks the WHOLE declared payload against it, before any adapter logic runs, and hands back what adapters read.

What a failure costs is decided by where it is, never by the adapter:

  members(x), entries(x)  each element is decoded alone. One that cannot be is Unreadable (the router drops and counts it, so the
                          members beside it stand as a partial lower bound). A failure anywhere inside an element is that element's.
  isolated(x)             a field whose failure costs only itself: Unreadable in its place, and the adapter says what that loses.
  soft(x)                 metadata that says nothing when it cannot be read (a total, a cursor): None. It never ends or continues anything.
  everything else         the answer is unreadable: PayloadError, and the lane is unavailable with payload_invalid.

And what can FAIL is total (2b-repair-13a): PayloadError is the one channel. Every scalar conversion goes through `_normalized` and every consistency rule
through `_ruled`, so whatever a provider's value makes them do — a Unicode digit that `int()` refuses, a number past the conversion limit, a rule that
indexes what is not there — is a PayloadError at the nearest boundary above it, never an exception that escapes the member. Only UndeclaredRead, a programming
error, passes. The parse of the answer's bytes is inside the same channel (an empty body, and bytes that are not the document their format requires: core/wire.py is the ruling for JSON, XML and CSV).

"Missing or null" and "present but malformed" are different things, as the accepted contracts say: a field that is left out (or null)
is the empty value of its kind (None, False, [], {}, an object of empty fields) unless it is `required`; one that is there and is
not its kind is unreadable — `false`, `0`, `""`, `[]` and `{}` included, which a truthiness test would take for "nothing". An operation whose
contract tells the two apart says so (`never_null`): a field it lets the provider leave out but not send as null.

Every field an `obj` declares is decoded, nested contents included, whether or not the adapter will use it. That is the whole of the
alternatives rule: `rightsIdentifier` and `rights`, `best_oa_location` and `oa_locations`, a structure's `Ref` and `URN` are all
declared, so all are decoded before the adapter can choose, and what an adapter reads is a decoded value (core/payload.py: Rec).
`alts` names the groups of fields that are alternatives of one another, for the tests that corrupt each beside a valid other.

A field declared `any_()` is metadata: it is handed over as a `Passive`, which can be stored and never read (core/payload.py). Whatever identifies, selects,
ends or continues anything, or goes into a request, is declared a kind.

SDMX-ML is decoded by the same decoder: an `obj` applied to an ElementTree element reads `"@name"` as an attribute, `"@*"` as all of them,
`"#"` as its text (an element whose text is split by child elements has none: unreadable, not its first chunk), `"%"` as its own local name, `"name"` as the list of its child elements of that local name, `"*"` as the list of all its children
and `"**name"` as the list of every descendant of it that is called that.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from typing import Any, Callable

from . import wire
from .payload import MEMBER_ERRORS, MemberList, Passive, PayloadError, Rec, Sealed, SealedAnswer, UndeclaredRead, Unreadable

MISSING = object()


@dataclass(frozen=True)
class Spec:
    """One node of a schema. Build it with the constructors below (adapters import this module as `S`), never by hand."""
    kind: str
    of: Any = None                   # obj: {field: Spec}; own/members/entries/table/soft/isolated: Spec; oneof: (Spec, ...)
    required: bool = False           # the field must be there, and not null
    never_null: bool = False         # the field may be left out, but a null is unreadable: the operation's contract tells the two apart
    default: Any = None              # any_: what a field that is left out (not null) is
    empty_when: tuple | None = None  # a list that may be left out only when the number at this path (from the parent object) is exactly 0
    at_most: int | None = None       # the most elements a list may hold
    bare: bool = False               # a non-empty object stands for a list of one (BEA's habit)
    rule: Callable | None = None     # obj: called with the decoded Rec; raises PayloadError when its fields contradict one another
    alts: tuple = ()                 # obj: groups of field names that are alternatives of one another


# ------------------------------------------------------------------ leaves
def text(default: str | None = None) -> Spec:
    """Text, or nothing (missing, null). A number, a boolean, a list, an object is unreadable. `default` is what the field is when it is left out (not when it is null)."""
    return Spec("text", default=default)


def key() -> Spec:
    """What a member is named by: non-blank text, or a whole number, as sent. Missing, null, blank or anything else names nothing: unreadable."""
    return Spec("key")


def maybe_key(*, only_empty: bool = False) -> Spec:
    """key(), except that missing, null and blank say nothing: a name as sent (None for none; a blank one names nothing). `only_empty`: only the empty string
    is such a blank — one of spaces is a name that cannot be read."""
    return Spec("maybe_key", default=only_empty)


def flag() -> Spec:
    """true or false as sent; false when left out. `0`, `""`, `[]`, `"no"` are unreadable, not a flag."""
    return Spec("flag")


def whole() -> Spec:
    """A whole number (not a boolean), or nothing."""
    return Spec("whole")


def number() -> Spec:
    """A finite number, whole or not (not a boolean), or nothing."""
    return Spec("number")


def year() -> Spec:
    """What a record's year may be: a whole number, the digits of one as text, an integral float, or nothing."""
    return Spec("year")


def token() -> Spec:
    """A non-blank string — an opaque cursor. Anything else is unreadable (wrap it in soft() where a cursor that cannot be read is no cursor)."""
    return Spec("token")


def any_(default: Any = None) -> Spec:
    """Metadata, carried as sent and stored in a record (`extra`, provenance): no kind is demanded, and none can be relied on, so what is handed over is a
    `Passive` that nothing can read (core/payload.py). A field that identifies, selects, ends or continues anything — or goes into a request, or is shown
    as a label — is declared a kind instead. `default` is what the field is when it is left out (not when it is null)."""
    return Spec("any", default=default)


# ------------------------------------------------------------------ what a failure costs
def soft(spec: Spec) -> Spec:
    return Spec("soft", spec)


def isolated(spec: Spec) -> Spec:
    return Spec("isolated", spec)


def oneof(*specs: Spec) -> Spec:
    """A value that may be any of these kinds: the first that decodes it."""
    return Spec("oneof", tuple(specs))


# ------------------------------------------------------------------ containers
def obj(fields: dict, *, alts: tuple = (), rule: Callable | None = None) -> Spec:
    for group in alts:   # a name, or a dotted path through objects declared in this one
        missing = [n for n in group if n.split(".")[0] not in fields]
        if missing:
            raise ValueError(f"alternatives name fields the object does not declare: {missing}")
    return Spec("obj", dict(fields), alts=tuple(tuple(g) for g in alts), rule=rule)


def own(elem: Spec, *, bare: bool = False, at_most: int | None = None, empty_when: tuple | None = None, rule: Callable | None = None) -> Spec:
    """A list that is one record's own data: every element must decode, or the record is unreadable. `rule` is called with the decoded list."""
    return Spec("own", elem, bare=bare, at_most=at_most, empty_when=empty_when, rule=rule)


def members(elem: Spec, *, bare: bool = False, at_most: int | None = None, empty_when: tuple | None = None) -> Spec:
    """A list of independent members, each decoded alone (see the module docstring)."""
    return Spec("members", elem, bare=bare, at_most=at_most, empty_when=empty_when)


def grid(header: Spec, cell: Spec) -> Spec:
    """A table as a list of lists: its first row names the columns (each cell decodes as `header` and none may be left out), every other row is data (each cell as
    `cell`). It is one record's own data: a row that is not a list, or a cell that is not what it should be, makes it unreadable, not shorter. The decoded value is a
    plain list of lists, the header first."""
    return Spec("grid", (header, cell))


def lookup(elem: Spec) -> Spec:
    """A list from which a lookup reads only its first element, which must decode: the decoded first element, None when the list is empty or left out.
    The elements after it are not read, and nothing is asked of them."""
    return Spec("lookup", elem)


def maybe(spec: Spec) -> Spec:
    """`spec`, except that a field that is left out (or null) is None rather than the empty value of its kind: for a reader that must tell a list that is
    not there from one that is there and empty."""
    return Spec("maybe", spec)


def matching(prefixes: tuple, leaf: Spec) -> Spec:
    """Every field of the object whose name starts with one of `prefixes`, as {name: decoded}: for names a provider makes up (BEA's `FirstYear`, `LastYear`).
    A field of the object it is declared in, whose own name is only a label."""
    return Spec("matching", (tuple(prefixes), leaf))


def entries(elem: Spec) -> Spec:
    """A keyed container whose entries are independent members: a list of Rec{key, value}, each decoded alone."""
    return Spec("entries", elem)


def table(elem: Spec) -> Spec:
    """A keyed container that is one record's own data: {key: decoded}, every value must decode."""
    return Spec("table", elem)


def deep(path: tuple, leaf: Spec) -> Spec:
    """Metadata read through containers that may themselves be unreadable (a total at `meta.total`, a cursor at `header.nextCursor`): a field of the
    object it is declared in, None when any step is not an object, the leaf is not there, or it is not `leaf`. It is soft all the way down."""
    return Spec("deep", (tuple(path), leaf))


def by(tag: str, variants: dict, other: Spec | None = None) -> Spec:
    """A field whose kind depends on a sibling field of the same object: `variants[value of the sibling `tag`]`, else `other` (carried as sent).
    Dataverse's citation block is a list of {typeName, value} where the value of `author` is a list of objects and the value of `title` is text."""
    return Spec("by", (tag, dict(variants), other if other is not None else any_()))


def required(spec: Spec) -> Spec:
    return replace(spec, required=True)


def never_null(spec: Spec) -> Spec:
    """`spec`, for a field the operation's contract lets the provider LEAVE OUT but not send as null: left out it is what `spec` says, null it is unreadable. The generic
    rule (null is left out) is wrong for such an operation, and the schema is where it says so (Semantic Scholar's `data`)."""
    return replace(spec, never_null=True)


# ------------------------------------------------------------------ the decoder
def decode(source_id: str, spec: Spec, answer: Any) -> Any:
    """`answer` as `spec` says it must be; PayloadError when its envelope is unreadable — and that is the only thing a provider's answer can make this raise.

    `answer` is what the client received (a Response: its bytes are opened HERE and nowhere else, so nothing but the decoder ever holds the parsed payload), or
    a value already parsed — JSON data, an ElementTree element, or the Sealed raw of a part of an earlier answer (a second pass over it)."""
    try:
        value = _open_json(answer)
    except PayloadError:
        if spec.kind == "soft":   # metadata that says nothing when it cannot be read: the body that cannot be opened included
            return None
        raise   # an empty or unparseable body: the client's own words for it (the call log and the answer's error text say so)
    try:
        return _decode(spec, value, ())
    except PayloadError as e:
        raise PayloadError(f"{source_id}: {e}") from None


def _open_json(answer):
    """The parsed value of an answer: its bytes opened as JSON when it is the client's, as it is when it is already a value (or the Sealed raw of a part of one).
    An empty body and JSON that wire.open_json refuses (not JSON, not UTF-8, a name twice, `NaN`, nesting past MAX_DEPTH ...) are PayloadErrors: the answer is not one."""
    if isinstance(answer, Sealed):
        return answer._value
    if not isinstance(answer, SealedAnswer):
        return answer
    body = answer._body
    if not body:
        raise PayloadError(f"empty body (HTTP {getattr(answer, 'status', None)})")
    try:
        return wire.open_json(body)
    except wire.Malformed as e:
        raise PayloadError(f"unparseable JSON (HTTP {getattr(answer, 'status', None)}, {len(body)} bytes)" + ("" if e.syntax else f": {e}")) from None


def _bytes_or_text(answer):
    """What a byte opener reads of an answer: the client's bytes, or text already."""
    if isinstance(answer, SealedAnswer):
        return answer._body
    if isinstance(answer, str):
        return answer
    raise TypeError(f"an answer is the client's response or text, not a {type(answer).__name__}")


def _where(at: tuple) -> str:
    out = ""
    for step in at:
        out += f"[{step}]" if isinstance(step, int) else (("." if out else "") + str(step))
    return out or "the answer"


def _kind(v) -> str:
    return "null" if v is None else {dict: "an object", list: "a list", bool: "a boolean", int: "a number", float: "a number", str: "text"}.get(type(v), type(v).__name__)


def _bad(at: tuple, v, belongs: str) -> PayloadError:
    return PayloadError(f"{_where(at)} is {_kind(v)} where {belongs} belongs")


def counts_nothing(value) -> bool:
    """Whether a provider's own count says there is nothing: the whole number zero. A `false`, a `0.0`, a `"0"`, a missing count says nothing."""
    return type(value) is int and value == 0


def year_value(value) -> int | None:
    """A year: a whole number, or the digits of one a provider sent as text; nothing when it names none. Anything else is unreadable — including digits that are
    no number `int()` accepts (`"²"`, `"①"`) and a string of them past the interpreter's conversion limit, which `str.isdigit()` lets through."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and value.isdigit():
        try:
            value = int(value)
        except ValueError:
            raise PayloadError(f"a year is text that is not a number ({len(value)} characters)") from None
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise PayloadError(f"a year is {_kind(value)} {value!r}, not a year")


def _number(value):
    if value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)):
        return value
    raise PayloadError(f"{_kind(value)} where a number belongs")


# the scalar normalizers: the functions that turn a provider's value into the kind's. Each is called through `_normalized`, so none can fail any way but one
_NORMALIZERS = {"year": year_value, "number": _number}


def _normalized(at: tuple, kind: str, v):
    """What the normalizer of `kind` makes of a provider's value. Its only input is that value, so whatever it raises — PayloadError, or any exception a conversion of an
    odd value can throw (a Unicode digit, a number past the conversion limit, nesting) — is that value's failure, and surfaces as the one channel: a PayloadError at `at`,
    which the nearest boundary above takes as its own (a member's, a field's, the answer's)."""
    try:
        return _NORMALIZERS[kind](v)
    except PayloadError as e:
        raise PayloadError(f"{_where(at)}: {e}") from None
    except Exception as e:   # a normalizer reads nothing but `v`: nothing it raises is a programming error of the caller's
        raise PayloadError(f"{_where(at)}: {_kind(v)} cannot be read as a {kind} ({type(e).__name__})") from None


def _ruled(rule: Callable, arg, at: tuple) -> None:
    """A schema's consistency rule, run on what its object or list decoded to. It reads declared fields and the provider's values, so a PayloadError, or whatever a
    provider's value makes it raise (MEMBER_ERRORS), is the answer's contradiction, at `at`. UndeclaredRead is not in that set: a rule that reads what its schema does not
    declare is a programming error, and passes."""
    try:
        rule(arg)
    except PayloadError as e:
        raise PayloadError(f"{_where(at)}: {e}") from None
    except UndeclaredRead:
        raise
    except MEMBER_ERRORS as e:
        raise PayloadError(f"{_where(at)}: the rule could not read the answer ({type(e).__name__})") from None


def _decode(s: Spec, v, at: tuple):
    k = s.kind
    if k == "any":
        return Passive(v)
    if k == "text":
        if v is None or isinstance(v, str):
            return v
        raise _bad(at, v, "text")
    if k == "key":
        if (isinstance(v, str) and v.strip()) or (isinstance(v, int) and not isinstance(v, bool)):
            return v   # as sent: a whole number stays one (a record's `file_id` is the provider's own); text() it where text is wanted
        raise PayloadError(f"{_where(at)} is {'nothing' if v is None else _kind(v)} where a member's identifier belongs")
    if k == "maybe_key":   # a name or nothing; what is sent stays as sent (a blank name names nothing, and identity_from knows it)
        if v is None or (isinstance(v, int) and not isinstance(v, bool)):
            return v
        if isinstance(v, str) and not (s.default and v != "" and not v.strip()):   # only_empty: a name of spaces is not "nothing", it is unreadable
            return v
        raise PayloadError(f"{_where(at)} is {_kind(v)} where a member's identifier belongs")
    if k == "flag":
        if v is None or isinstance(v, bool):
            return bool(v)
        raise _bad(at, v, "a flag")
    if k == "whole":
        if v is None or (isinstance(v, int) and not isinstance(v, bool)):
            return v
        raise _bad(at, v, "a whole number")
    if k in _NORMALIZERS:
        return _normalized(at, k, v)
    if k == "token":
        if isinstance(v, str) and v.strip():
            return v
        raise _bad(at, v, "a cursor")
    if k == "maybe":
        return None if v is None else _decode(s.of, v, at)
    if k == "lookup":
        if not isinstance(v, list):
            raise _bad(at, v, "a list")
        return _decode(s.of, v[0], at + (0,)) if v else None
    if k == "soft":
        try:
            return _decode(s.of, v, at)
        except PayloadError:
            return None
    if k == "isolated":
        try:
            return _decode(s.of, v, at)
        except PayloadError as e:
            return Unreadable(str(e), v)
    if k == "oneof":
        problems = []
        for alternative in s.of:
            try:
                return _decode(alternative, v, at)
            except PayloadError as e:
                problems.append(str(e))
        raise PayloadError(" / ".join(problems))
    if k == "obj":
        return _decode_obj(s, v, at)
    if k in ("own", "members"):
        items = _items(s, v, at)
        if k == "own":
            out = [_decode(s.of, m, at + (i,)) for i, m in enumerate(items)]
            if s.rule is not None:
                _ruled(s.rule, out, at)
            return out
        out = []
        for i, m in enumerate(items):
            try:
                out.append(_decode(s.of, m, at + (i,)))
            except PayloadError as e:
                out.append(Unreadable(str(e), m))
        return MemberList(out)
    if k == "grid":
        header, cell = s.of
        if not isinstance(v, list):
            raise _bad(at, v, "a list")
        if not v:
            raise PayloadError(f"{_where(at)} is not a table (no header row)")
        rows = []
        for i, row in enumerate(v):
            if not isinstance(row, list):
                raise _bad(at + (i,), row, "a list")
            rows.append([_decode(header if i == 0 else cell, c, at + (i, j)) for j, c in enumerate(row)])
        if any(c is None for c in rows[0]):
            raise PayloadError(f"{_where(at + (0,))} names a column that is not text: the table is unreadable, not shorter")
        return rows
    if k in ("entries", "table"):
        if not isinstance(v, dict):
            raise _bad(at, v, "an object")
        if k == "table":
            return {name: _decode(s.of, val, at + (name,)) for name, val in v.items()}
        out = []
        for name, val in v.items():
            try:
                out.append(Rec({"key": name, "value": _decode(s.of, val, at + (name,))}, val))
            except PayloadError as e:
                out.append(Unreadable(str(e), val))
        return MemberList(out)
    raise ValueError(f"unknown schema kind {k!r}")


def _items(s: Spec, v, at: tuple) -> list:
    if isinstance(v, dict) and v and s.bare:
        v = [v]   # a list of one that comes as the one object: a row has something in it
    if not isinstance(v, list):
        raise _bad(at, v, "a list")
    if s.at_most is not None and len(v) > s.at_most:
        raise PayloadError(f"{_where(at)} holds {len(v)} where at most {s.at_most} belong")
    return v


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read(v, name: str):
    """The raw value of the declared field `name` of `v` (a JSON object or an element), MISSING when it is not there."""
    if isinstance(v, dict):
        return v.get(name, MISSING)
    if name == "@*":
        return dict(v.attrib)
    if name == "%":
        return _local(v.tag)
    if name == "#":
        if any((child.tail or "").strip() for child in v):   # `<a>x<b/>y</a>`: ElementTree keeps "x" as a's text and "y" as b's tail; reading "x" alone would drop "y" without a word
            raise PayloadError("an element's text is split by child elements: it has no single text to read")
        return v.text if v.text is not None else MISSING
    if name == "*":
        return list(v) or MISSING
    if name.startswith("@"):
        return v.attrib.get(name[1:], MISSING)
    if name.startswith("**"):
        found = [d for d in v.iter() if d is not v and _local(d.tag) == name[2:]]
    else:
        found = [c for c in v if _local(c.tag) == name]
    return found or MISSING


def _decode_obj(s: Spec, v, at: tuple) -> Rec:
    if not isinstance(v, (dict, ET.Element)):
        raise _bad(at, v, "an object")
    values = {}
    for name, fs in s.of.items():
        if fs.kind == "by":
            tag, variants, other = fs.of
            sibling = _read(v, tag)
            fs = variants.get(sibling, other) if isinstance(sibling, str) else other
        if fs.kind == "deep":
            values[name] = _deep(fs, v, at + (name,))
        elif fs.kind == "matching":
            prefixes, leaf = fs.of
            values[name] = {k: _decode(leaf, x, at + (k,)) for k, x in (v.items() if isinstance(v, dict) else ()) if isinstance(k, str) and k.startswith(prefixes)}
        else:
            values[name] = _field(fs, _read(v, name), at + (name,), v)
    rec = Rec(values, v)
    if s.rule is not None:
        _ruled(s.rule, rec, at)
    return rec


def _deep(fs: Spec, v, at: tuple):
    path, leaf = fs.of
    for step in path:
        v = v.get(step) if isinstance(v, dict) else None
    try:
        return None if v is None else _decode(leaf, v, at)
    except PayloadError:
        return None


def _field(fs: Spec, raw, at: tuple, parent):
    if fs.kind == "maybe":
        return None if raw is MISSING or raw is None else _decode(fs.of, raw, at)
    if fs.kind == "soft":
        try:
            return _field(fs.of, raw, at, parent)
        except PayloadError:
            return None
    if fs.kind == "isolated":
        try:
            return _field(fs.of, raw, at, parent)
        except PayloadError as e:
            return Unreadable(str(e), None if raw is MISSING else raw)
    if raw is None and fs.never_null:
        raise PayloadError(f"{_where(at)} is null where {fs.kind} belongs: the answer may leave it out, but this operation's contract does not let it send null")
    if raw is MISSING or raw is None:
        return _absent(fs, at, parent, raw is MISSING)
    return _decode(fs, raw, at)


def _absent(fs: Spec, at: tuple, parent, missing: bool):
    """A field that is left out (or null): its kind's empty value, unless it is required, or may be left out only when the provider counts nothing."""
    if fs.required:
        raise PayloadError(f"{_where(at)}: the answer has no {_where(at)}" if missing else f"{_where(at)} is null where a value belongs")
    if fs.empty_when is not None:
        holder = parent
        for step in fs.empty_when:
            holder = holder.get(step) if isinstance(holder, dict) else None
        if not counts_nothing(holder):
            raise PayloadError(f"{_where(at)} is left out, and the answer does not count nothing ({'.'.join(fs.empty_when)} is not 0)")
    if fs.kind == "key":
        raise PayloadError(f"{_where(at)} is {'missing' if missing else 'null'} where a member's identifier belongs")
    if fs.kind == "any":
        return Passive(fs.default if missing else None)
    if fs.kind == "text" and missing:
        return fs.default
    return _empty(fs)


def _empty(fs: Spec):
    k = fs.kind
    if k == "flag":
        return False
    if k in ("members", "entries"):
        return MemberList([])
    if k == "own":
        return []
    if k == "table":
        return {}
    if k == "obj":
        return Rec({name: _empty(sub) for name, sub in fs.of.items()}, {})
    if k in ("soft", "isolated"):
        return _empty(fs.of)
    if k == "lookup":
        return None
    if k == "deep":
        return None
    if k == "matching":
        return {}
    if k == "oneof":
        return _empty(fs.of[0])
    if k == "any":
        return Passive(None)
    if k == "grid":
        return []
    return None


# ------------------------------------------------------------------ SDMX-ML
def parse_xml(answer, *roots: str) -> ET.Element:
    """The parsed message, whose root must be one of `roots`: unparseable XML, or a document that is not a message of that kind, is an unreadable answer. `answer`
    is the client's response (its bytes are opened here, as for `decode`) or text."""
    try:
        root = wire.open_xml(_bytes_or_text(answer))
    except wire.Malformed as e:
        raise PayloadError(f"unparseable SDMX-ML ({type(e).__name__}: {e})") from None
    if _local(root.tag) not in roots:
        raise PayloadError(f"an SDMX answer rooted at {_local(root.tag)!r}, not {' or '.join(roots)}")
    return root


def decode_csv(source_id: str, spec: Spec, answer, *, columns: tuple = ()) -> MemberList:
    """A CSV answer as the independent members it holds: each row decoded alone against `spec` (an `obj` of its columns), the header first checked for `columns` — a file
    without them is not the file the operation supports — and for a column the header names twice that `spec` declares (which of the two is meant is not for the reader to
    choose). A file that does not parse (core/wire.py: an unclosed quote, text after one, a quote in an unquoted field, a bare carriage return, bytes that are not UTF-8) is no
    file: PayloadError, never a shorter one. A cell the row is too short to hold is nothing and cells past the header are not read (the csv module's own reading of a short
    or long row, kept). `answer` is the client's response, opened here."""
    try:
        records = wire.open_csv(_bytes_or_text(answer))
    except wire.Malformed as e:
        raise PayloadError(f"{source_id}: the CSV does not parse ({e})") from None
    names = list(records[0]) if records else []
    missing = [c for c in columns if c not in names]
    if missing:
        raise PayloadError(f"{source_id}: the CSV shape changed: columns {names[:5]!r} lack {missing!r}")
    twice = sorted(c for c in set(names) if names.count(c) > 1 and c in spec.of)
    if twice:
        raise PayloadError(f"{source_id}: the CSV header names {twice!r} twice: which column is meant cannot be told")
    out = []
    for cells in records[1:]:
        if not cells:   # a blank line is no row
            continue
        row = dict(zip(names, cells))
        if len(cells) > len(names):
            row[None] = cells[len(names):]   # the csv module's restkey: cells past the header, kept in the row's raw and never read
        row.update((c, None) for c in names[len(cells):])   # a row too short for a column holds nothing there
        try:
            out.append(_decode(spec, row, ()))
        except PayloadError as e:
            out.append(Unreadable(str(e), row))
    return MemberList(out)
