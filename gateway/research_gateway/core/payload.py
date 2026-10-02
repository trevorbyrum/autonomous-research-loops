"""What a provider's answer is once it has been decoded (task 2b-repair-12, completed in 2b-repair-13a).

One defect family came back in every 2b round since repair-7 under a new spelling: malformed members, falsy wrong-kind
holders, lazy `a or b` fallbacks, nested alternatives, contradictory references, an untyped identifier, a conversion that
raised. Each repair fixed the access patterns found and the next one got past it, because the cause was never removed: the
contract between a provider's answer and the rest of the gateway was incomplete. Repair-12 made validation eager and
declared; repair-13a closes the three gaps that were left, as properties of the decoder and of what it hands out:

  * FAILURES ARE TOTAL. Whatever a provider's value makes a conversion or a consistency rule do, the decoder's one channel
    for it is PayloadError, at the narrowest member boundary around it (core/schema.py); only UndeclaredRead — a programming
    error — passes through. MEMBER_ERRORS below is the one statement of what a builder's own reading of a member may raise.
  * DECLARATIONS ARE COMPLETE FOR WHAT DECIDES. A field declared `any_()` is handed over as a `Passive`: carried as sent, for
    storing, and nothing else — every attempt to read it (truth, equality, ordering, iteration, text, arithmetic, attributes)
    raises PassiveRead. So a value that identifies, selects, ends, continues or is sent in a request cannot be an `any_()` one:
    its schema must give it a kind, or the first answer that reaches the read fails.
  * THE RAW ANSWER IS SEALED. An adapter is handed a Response that holds no readable payload (adapters/base.py): the bytes are
    opened by the decoder alone, and what leaves the decoder for provenance — a member's `raw`, an `any_()` value — is a
    `Sealed`/`Passive` that can be compared or stored and never read, leaving as a copy (`plain`).

The decoder returns exactly these, and nothing an adapter can read otherwise:

  * an object is a `Rec`, which holds exactly its declared fields. Reading one it does not declare raises UndeclaredRead
    — a failure, never a member's loss (it is not in MEMBER_ERRORS) — so an adapter cannot read what its schema does not say;
  * a list of independent members is a `MemberList`: every member already decoded alone (a `Rec`, or Unreadable where it could not be), and the
    list cannot be iterated, indexed or searched by an adapter — only read through `members()`, `first_member()`, `take()` and `expand()`, which
    isolate each member — so no spelling of a pass over a provider's candidates (a filter, a `while`, `rows[0]`, a flatten) can lose a readable
    member to a malformed one (R7-2, three times). A record's OWN list (its authors, its tags) is an ordinary list: it is all-or-nothing by nature;
  * every alternative a provider may state (`rightsIdentifier` or `rights`, `best_oa_location` or `oa_locations`, a
    structure's `Ref` or `URN`) is a declared field, decoded completely, nested contents included, before the adapter can
    choose between them.

`Rec.raw` is the member as the provider sent it, for a record's `raw` (I-8): a `Sealed`. tests/test_member_isolation.py lists every use of it
that is not the value of a `raw=` argument, with why, and fails one that is not listed.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET


class PayloadError(ValueError):
    """An answer that is not the shape its adapter requires — an empty or unparseable body, or a parsed body that does not
    decode against the operation's schema. The lane is unavailable with error_class payload_invalid: an unreadable answer is
    never zero results (INVARIANTS H-5, RG-4; design review §9, task 2b). Adapters use it through adapters.base."""


class UndeclaredRead(RuntimeError):
    """An adapter read a field its operation's schema does not declare. A programming error, not a malformed answer: it is
    deliberately not a MEMBER_ERROR, so no member is dropped to hide it and no lane reports it as a provider's fault."""


class PassiveRead(UndeclaredRead):
    """An adapter read the value of a field its schema declares `any_()`: metadata, carried as sent. A programming error like any undeclared read:
    a value that decides something is declared a kind, and an `any_()` one is only ever stored (`plain`)."""


class SealedRead(UndeclaredRead):
    """An adapter read the provider's raw object. It is for storing (a record's `raw`) and for comparing, never for reading."""


# what a builder's own reading of one provider member may raise (a missing key, a list where an object was expected, a value that is not a date, a
# number too large to convert ...): that member's failure, never the answer's. UndeclaredRead (and with it PassiveRead, SealedRead) is deliberately not here
MEMBER_ERRORS = (PayloadError, KeyError, TypeError, AttributeError, ValueError, IndexError, ArithmeticError, RecursionError)

# what a builder returns for a member it read whole and found to name nothing to report (a deposited
# reference with no DOI): no record, and no malformed member either — that one is None, which the router counts
OMIT = object()

MAX_DEPTH = 64   # no provider answer the gateway supports nests deeper; one that does is unreadable (core/schema.py), which also bounds every later walk over it


_READS = ("__bool__", "__iter__", "__reversed__", "__len__", "__getitem__", "__contains__", "__lt__", "__le__", "__gt__", "__ge__", "__str__", "__format__",
          "__int__", "__float__", "__index__", "__bytes__", "__add__", "__radd__", "__mul__", "__rmul__", "__neg__", "__abs__", "__mod__", "__sub__",
          "__rsub__", "__truediv__", "__floordiv__", "__and__", "__or__", "__xor__", "__hash__", "__call__", "__round__", "__floor__", "__ceil__", "__trunc__", "__matmul__", "__pow__", "__lshift__",
          "__rshift__", "__invert__", "__pos__", "__complex__")


def _no_reading(error: type, what: str, readable: str):
    """The class decorator that makes every way of reading an instance raise `error`: each special method that reads (truth, ordering, iteration, subscript,
    text, number, arithmetic), and any attribute that is not its own (a dunder an introspecting library probes for is an AttributeError, as for any object)."""
    def refuse(name):
        def read(self, *args, **kwargs):
            raise error(f"{what} ({name}); {readable}")
        read.__name__ = name
        return read

    def decorate(cls):
        for name in _READS:
            setattr(cls, name, refuse(name))

        def __getattr__(self, name):
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            raise error(f"{what} (attribute {name!r}); {readable}")
        cls.__getattr__ = __getattr__

        def __setattr__(self, name, value):
            raise error(f"{what} is not changed")
        cls.__setattr__ = __setattr__
        return cls
    return decorate


@_no_reading(SealedRead, "the provider's raw object", "it is for storing (a record's `raw=`) and comparing; declare the field and read it decoded")
class Sealed:
    """The provider's object exactly as it was sent (a member, a whole answer), kept for storing in a record's `raw`.

    It can be compared with another (`==`: a record builder asks whether two members are the one the provider repeated) and
    stored (`plain`, which hands out a copy: the object kept here is never reachable). Reading it — truth, iteration, subscript, `.get`,
    any attribute — raises SealedRead: what an adapter decides, it decides from what the schema declared."""
    __slots__ = ("_value",)
    __hash__ = None

    def __init__(self, value):
        object.__setattr__(self, "_value", value)

    def __eq__(self, other) -> bool:
        return isinstance(other, Sealed) and _same(self._value, other._value)

    def __repr__(self) -> str:
        return "<Sealed>"

    def without(self, *names: str) -> "Sealed":
        """The same object without these fields, for a record whose raw may not keep part of what the provider sent (CORE's full text, I-7)."""
        if not isinstance(self._value, dict):
            raise SealedRead("without() takes fields out of an object")
        return Sealed({k: v for k, v in self._value.items() if k not in names})


@_no_reading(PassiveRead, "this value is declared any_(): metadata carried as sent, stored and never read",
             "a value that decides anything is declared a kind in the schema")
class Passive:
    """The value of a field a schema declares `any_()`: carried as sent, for storing in a record (`extra`, provenance), and nothing else.

    Every way of reading it raises PassiveRead — `if x`, `x == y`, `x in z`, `str(x)`, `f"{x}"`, `x[0]`, `x.get`, `int(x)`, `x + 1` — so a value that
    identifies a candidate, selects one, ends or continues a listing, or goes into a request cannot be one: the schema gives such a field a kind, and
    the decoder checks it. `plain()` is the one way out, and hands out a copy."""
    __slots__ = ("_value",)
    __hash__ = None

    def __init__(self, value=None):
        object.__setattr__(self, "_value", value)

    def __eq__(self, other) -> bool:
        raise PassiveRead("this value is declared any_(): metadata carried as sent, stored and never read (comparison)")

    def __ne__(self, other) -> bool:
        raise PassiveRead("this value is declared any_(): metadata carried as sent, stored and never read (comparison)")

    def __repr__(self) -> str:
        return "<Passive>"


class SealedAnswer:
    """What the client received of a provider's answer: the bytes, which only the decoder opens (core/schema.py `decode`). A Response (adapters/base.py)
    is one, and holds nothing else of the payload: no parsed value, no text, no body an adapter can read."""
    __slots__ = ("_body",)

    def __init__(self, body: bytes):
        self._body = body


def _same(a, b) -> bool:
    """Whether two provider objects are the same one: equal values of equal kinds (`1` is not `True`, `1` is not `1.0`), elements by what they serialize to."""
    if isinstance(a, ET.Element) or isinstance(b, ET.Element):
        return isinstance(a, ET.Element) and isinstance(b, ET.Element) and ET.tostring(a) == ET.tostring(b)
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(v, b[k]) for k, v in a.items())
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


class Unreadable:
    """The decoded stand-in for a member (or an `isolated` field) that could not be decoded, with the reason. Falsy. What the provider sent in its place is
    sealed like any raw object: `was_object` says whether it was an object at all, which is all a loader needs to know to report it."""
    __slots__ = ("reason", "_value")

    def __init__(self, reason: str = "unreadable", value=None):
        self.reason = reason
        self._value = value   # the member as the provider sent it

    def __bool__(self) -> bool:
        return False

    @property
    def was_object(self) -> bool:
        return isinstance(self._value, (dict, ET.Element))

    @property
    def raw(self) -> Sealed:
        return Sealed(self._value)

    def __repr__(self) -> str:
        return f"Unreadable({self.reason!r})"


def is_unreadable(value) -> bool:
    return isinstance(value, Unreadable)


_LIST_USE = ("a provider's list of members is read through base.members() or first_member() (each member decoded alone), take(), or expand(); "
             "a list that is one record's own data is declared own(...) in the schema and is an ordinary list")


class MemberList:
    """A provider's list of independent members, as the decoder leaves it (see the module docstring)."""
    __slots__ = ("_items",)
    __hash__ = None

    def __init__(self, items: list):
        self._items = items

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __repr__(self) -> str:
        return f"<MemberList of {len(self._items)}>"

    def __iter__(self):
        raise TypeError(f"a MemberList cannot be iterated: {_LIST_USE}")

    def __reversed__(self):
        raise TypeError(f"a MemberList cannot be iterated: {_LIST_USE}")

    def __getitem__(self, _):
        raise TypeError(f"a MemberList cannot be indexed or sliced: {_LIST_USE}")

    def __contains__(self, _):
        raise TypeError(f"a MemberList cannot be searched: {_LIST_USE}")

    def each(self, build) -> list:
        """Each member through `build` on its own: what `build` returns for it, None for a member the decoder could not read or whose build raises
        (what the router counts as dropped), nothing for one `build` calls OMIT. UndeclaredRead is not caught: it is not a member's fault."""
        out = []
        for member in self._items:
            try:
                rec = None if isinstance(member, Unreadable) else build(member)
            except MEMBER_ERRORS:
                rec = None
            if rec is not OMIT:
                out.append(rec)
        return out

    def first(self, build, source_id: str = ""):
        """The first member through `build`: None when there are none (or `build` calls OMIT). A first member that cannot be read is a PayloadError — an
        unreadable answer is never 'not found', and never answered by the member after it, which may be some other work."""
        if not self._items:
            return None
        got = MemberList(self._items[:1]).each(build)
        if got and got[0] is None:
            raise PayloadError(f"{source_id + ': ' if source_id else ''}the answer's first result cannot be read")
        return got[0] if got else None

    def at(self, position: int):
        """The member at a position, as decoded (a Rec, or Unreadable), None past the end: for a lookup table whose positions are the data (an SDMX
        dimension's values, which a series names by index). One member's position does not depend on the others."""
        return self._items[position] if -len(self._items) <= position < len(self._items) else None

    def take(self, n: int) -> "MemberList":
        """The first `n` members."""
        return MemberList(self._items[:n])

    def expand(self, unfold) -> "MemberList":
        """The members that each member holds, in one list: `unfold` takes a member and returns a MemberList. A member that cannot be unfolded — it could not
        be decoded, or `unfold` raises — is ONE unreadable member in place of everything it held; the other members unfold as they would have alone."""
        out = []
        for member in self._items:
            try:
                if isinstance(member, Unreadable):
                    raise PayloadError(member.reason)
                out.extend(unfold(member)._items)
            except MEMBER_ERRORS as e:
                out.append(member if isinstance(member, Unreadable) else Unreadable(str(e), member._raw if isinstance(member, Rec) else None))
        return MemberList(out)

    def unreadable(self) -> list:
        """The members that could not be decoded, each as Unreadable (its reason, and whether it was an object): for a loader that reports what it skipped."""
        return [m for m in self._items if isinstance(m, Unreadable)]


class Rec:
    """A decoded object: its declared fields and nothing else (see the module docstring)."""
    __slots__ = ("_v", "_raw")
    __hash__ = None

    def __init__(self, values: dict, raw):
        self._v = values
        self._raw = raw   # the object as the provider sent it; reachable only sealed (`raw`)

    def __getitem__(self, name):
        try:
            return self._v[name]
        except KeyError:
            raise UndeclaredRead(f"{name!r} is not a field this operation's schema declares (declared: {', '.join(map(repr, self._v))})") from None

    def get(self, name):
        return self[name]

    @property
    def raw(self) -> Sealed:
        """The object as the provider sent it, sealed: for a record's `raw=` and for comparing, never for reading."""
        return Sealed(self._raw)

    @property
    def empty(self) -> bool:
        """Whether the provider's object says nothing: no field, no attribute, no text, no child. The one thing about it an adapter may ask besides its declared fields."""
        if isinstance(self._raw, ET.Element):
            return not (len(self._raw) or self._raw.attrib or (self._raw.text or "").strip())
        return not self._raw

    @property
    def declared(self) -> tuple:
        return tuple(self._v)

    def __repr__(self) -> str:
        return f"<Rec {', '.join(self._v)}>"

    def __iter__(self):
        raise TypeError("a Rec is read by its declared field names; it is not iterated")

    def __eq__(self, other) -> bool:
        return isinstance(other, Rec) and tuple(self._v) == tuple(other._v) and Sealed(self._raw) == Sealed(other._raw)


def _copy(value):
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_copy(v) for v in value)
    return value


def plain(value):
    """The value as plain data, COPIED: a Rec, a Sealed, a Passive and an Unreadable are the object the provider sent, and any of them inside a dict, list or
    tuple likewise. This is the one way out of a sealed or passive value, for storing it in a record (raw, extra); never for reading a provider's field. What
    it returns is a copy, so nothing a record holds is the object the decoder kept."""
    if isinstance(value, Rec):
        return plain(value._raw)
    if isinstance(value, (Sealed, Passive)):
        return plain(value._value)
    if isinstance(value, Unreadable):
        return plain(value._value)
    if isinstance(value, ET.Element):
        return ET.tostring(value, encoding="unicode")
    if isinstance(value, MemberList):
        return [plain(v) for v in value._items]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, tuple):
        return tuple(plain(v) for v in value)
    return value
