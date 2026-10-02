"""What a provider's answer is once it has been decoded (task 2b-repair-12).

One defect family came back in every 2b round since repair-7 under a new spelling: malformed members, falsy wrong-kind
holders, lazy `a or b` fallbacks, nested alternatives, contradictory references. Each repair fixed the access patterns
found and the next one got past it, because the cause was never removed: adapters read a provider's payload field by
field, ad hoc, with no declared shape, so every new way of reading was a new place for a malformed value to hide.

The cause is removed here and in core/schema.py. Every provider operation DECLARES the payload it supports (a schema,
plain data, in its adapter module); ONE decoder validates the whole supported payload against it before any adapter logic
runs; adapters receive only what the decoder returns, and what it returns cannot be read any other way:

  * an object is a `Rec`, which holds exactly its declared fields. Reading one it does not declare raises UndeclaredRead
    — a failure, never a member's loss (it is not in MEMBER_ERRORS) — so an adapter cannot read what its schema does not say;
  * a list of independent members is a `MemberList`: every member already decoded alone (a `Rec`, or Unreadable where it could not be), and the
    list cannot be iterated, indexed or searched by an adapter — only read through `members()`, `first_member()`, `take()` and `expand()`, which
    isolate each member — so no spelling of a pass over a provider's candidates (a filter, a `while`, `rows[0]`, a flatten) can lose a readable
    member to a malformed one (R7-2, three times). A record's OWN list (its authors, its tags) is an ordinary list: it is all-or-nothing by nature;
  * every alternative a provider may state (`rightsIdentifier` or `rights`, `best_oa_location` or `oa_locations`, a
    structure's `Ref` or `URN`) is a declared field, decoded completely, nested contents included, before the adapter can
    choose between them.

`Rec.raw` is the member exactly as the provider sent it, for a record's `raw` (I-8). It is for storing, not for reading: tests/test_member_isolation.py
lists every use of it that is not the value of a `raw=` argument, with why, and fails one that is not listed.
"""
from __future__ import annotations


class PayloadError(ValueError):
    """An answer that is not the shape its adapter requires — an empty or unparseable body, or a parsed body that does not
    decode against the operation's schema. The lane is unavailable with error_class payload_invalid: an unreadable answer is
    never zero results (INVARIANTS H-5, RG-4; design review §9, task 2b). Adapters use it through adapters.base."""


class UndeclaredRead(RuntimeError):
    """An adapter read a field its operation's schema does not declare. A programming error, not a malformed answer: it is
    deliberately not a MEMBER_ERROR, so no member is dropped to hide it and no lane reports it as a provider's fault."""


# what decoding one unreadable provider member raises (a missing key, a list where an object
# was expected, a value that is not a date ...): that member's failure, never the answer's
MEMBER_ERRORS = (PayloadError, KeyError, TypeError, AttributeError, ValueError, IndexError)

# what a builder returns for a member it read whole and found to name nothing to report (a deposited
# reference with no DOI): no record, and no malformed member either — that one is None, which the router counts
OMIT = object()


class Unreadable:
    """The decoded stand-in for a member (or an `isolated` field) that could not be decoded, with the reason. Falsy."""
    __slots__ = ("reason", "value")

    def __init__(self, reason: str = "unreadable", value=None):
        self.reason = reason
        self.value = value   # the member as the provider sent it

    def __bool__(self) -> bool:
        return False

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
                out.append(member if isinstance(member, Unreadable) else Unreadable(str(e), member))
        return MemberList(out)

    def unreadable(self) -> list:
        """The members that could not be decoded, each as Unreadable (its reason, and the member as the provider sent it): for a loader that reports
        what it skipped."""
        return [m for m in self._items if isinstance(m, Unreadable)]


class Rec:
    """A decoded object: its declared fields and nothing else (see the module docstring)."""
    __slots__ = ("_v", "raw")
    __hash__ = None

    def __init__(self, values: dict, raw):
        self._v = values
        self.raw = raw   # the object as the provider sent it, for a record's raw; never read from

    def __getitem__(self, name):
        try:
            return self._v[name]
        except KeyError:
            raise UndeclaredRead(f"{name!r} is not a field this operation's schema declares (declared: {', '.join(map(repr, self._v))})") from None

    def get(self, name):
        return self[name]

    @property
    def declared(self) -> tuple:
        return tuple(self._v)

    def __repr__(self) -> str:
        return f"<Rec {', '.join(self._v)}>"

    def __iter__(self):
        raise TypeError("a Rec is read by its declared field names; it is not iterated")

    def __eq__(self, other) -> bool:
        return isinstance(other, Rec) and self._v == other._v and self.raw == other.raw


def plain(value):
    """The value as plain data: a Rec is the object it was decoded from, and any Rec inside a dict, list or tuple likewise. For storing
    a decoded value in a record (raw, extra); never for reading a provider's field."""
    if isinstance(value, Rec):
        return value.raw
    if isinstance(value, MemberList):
        return [plain(v) for v in value._items]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, tuple):
        return tuple(plain(v) for v in value)
    return value
