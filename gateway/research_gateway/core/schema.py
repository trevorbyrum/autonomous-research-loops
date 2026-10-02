"""Declared payload schemas and the one decoder (task 2b-repair-12; the cause is explained in core/payload.py).

A schema is plain data, built from the constructors below, declared once per operation in its adapter module. It says, for the
payload the operation supports: each field's type, which containers are lists of independent members, which fields are required
and which may be left out, which fields are alternatives of one another, and any rule that ties fields together. `decode` checks
the WHOLE declared payload against it, before any adapter logic runs, and hands back what adapters read.

What a failure costs is decided by where it is, never by the adapter:

  members(x), entries(x)  each element is decoded alone. One that cannot be is Unreadable (the router drops and counts it, so the
                          members beside it stand as a partial lower bound). A failure anywhere inside an element is that element's.
  isolated(x)             a field whose failure costs only itself: Unreadable in its place, and the adapter says what that loses.
  soft(x)                 metadata that says nothing when it cannot be read (a total, a cursor): None. It never ends or continues anything.
  everything else         the answer is unreadable: PayloadError, and the lane is unavailable with payload_invalid.

"Missing or null" and "present but malformed" are different things, as the accepted contracts say: a field that is left out (or null)
is the empty value of its kind (None, False, [], {}, an object of empty fields) unless it is `required`; one that is there and is
not its kind is unreadable — `false`, `0`, `""`, `[]` and `{}` included, which a truthiness test would take for "nothing".

Every field an `obj` declares is decoded, nested contents included, whether or not the adapter will use it. That is the whole of the
alternatives rule: `rightsIdentifier` and `rights`, `best_oa_location` and `oa_locations`, a structure's `Ref` and `URN` are all
declared, so all are decoded before the adapter can choose, and what an adapter reads is a decoded value (core/payload.py: Rec).
`alts` names the groups of fields that are alternatives of one another, for the tests that corrupt each beside a valid other.

SDMX-ML is decoded by the same decoder: an `obj` applied to an ElementTree element reads `"@name"` as an attribute, `"@*"` as all of them,
`"#"` as its text, `"%"` as its own local name, `"name"` as the list of its child elements of that local name, `"*"` as the list of all its children
and `"**name"` as the list of every descendant of it that is called that.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from typing import Any, Callable

from .payload import MemberList, PayloadError, Rec, Unreadable

MISSING = object()


@dataclass(frozen=True)
class Spec:
    """One node of a schema. Build it with the constructors below (adapters import this module as `S`), never by hand."""
    kind: str
    of: Any = None                   # obj: {field: Spec}; own/members/entries/table/soft/isolated: Spec; oneof: (Spec, ...)
    required: bool = False           # the field must be there, and not null
    default: Any = None              # any_: what a field that is left out (not null) is
    empty_when: tuple | None = None  # a list that may be left out only when the number at this path (from the parent object) is exactly 0
    at_most: int | None = None       # the most elements a list may hold
    bare: bool = False               # a non-empty object stands for a list of one (BEA's habit)
    rule: Callable | None = None     # obj: called with the decoded Rec; raises PayloadError when its fields contradict one another
    alts: tuple = ()                 # obj: groups of field names that are alternatives of one another


# ------------------------------------------------------------------ leaves
def text() -> Spec:
    """Text, or nothing (missing, null). A number, a boolean, a list, an object is unreadable."""
    return Spec("text")


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


def year() -> Spec:
    """What a record's year may be: a whole number, the digits of one as text, an integral float, or nothing."""
    return Spec("year")


def token() -> Spec:
    """A non-blank string — an opaque cursor. Anything else is unreadable (wrap it in soft() where a cursor that cannot be read is no cursor)."""
    return Spec("token")


def any_(default: Any = None) -> Spec:
    """Carried as sent, for storing in a record; no kind is demanded. `default` is what the field is when it is left out (not when it is null)."""
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


# ------------------------------------------------------------------ the decoder
def decode(source_id: str, spec: Spec, value: Any) -> Any:
    """`value` (a parsed answer: JSON data, or an ElementTree element) as `spec` says it must be; PayloadError when its envelope is unreadable."""
    try:
        return _decode(spec, value, ())
    except PayloadError as e:
        raise PayloadError(f"{source_id}: {e}") from None


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
    """A year: a whole number, or the digits of one a provider sent as text; nothing when it names none. Anything else is unreadable."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise PayloadError(f"a year is {_kind(value)} {value!r}, not a year")


def _decode(s: Spec, v, at: tuple):
    k = s.kind
    if k == "any":
        return v
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
    if k == "year":
        try:
            return year_value(v)
        except PayloadError as e:
            raise PayloadError(f"{_where(at)}: {e}") from None
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
                try:
                    s.rule(out)
                except PayloadError as e:
                    raise PayloadError(f"{_where(at)}: {e}") from None
            return out
        out = []
        for i, m in enumerate(items):
            try:
                out.append(_decode(s.of, m, at + (i,)))
            except PayloadError as e:
                out.append(Unreadable(str(e), m))
        return MemberList(out)
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
        try:
            s.rule(rec)
        except PayloadError as e:
            raise PayloadError(f"{_where(at)}: {e}") from None
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
    if fs.kind == "any" and missing:
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
    return None


# ------------------------------------------------------------------ SDMX-ML
def parse_xml(text_: str, *roots: str) -> ET.Element:
    """The parsed message, whose root must be one of `roots`: unparseable XML, or a document that is not a message of that kind, is an unreadable answer."""
    try:
        root = ET.fromstring(text_)
    except ET.ParseError as e:
        raise PayloadError(f"unparseable SDMX-ML ({e})") from None
    if _local(root.tag) not in roots:
        raise PayloadError(f"an SDMX answer rooted at {_local(root.tag)!r}, not {' or '.join(roots)}")
    return root
