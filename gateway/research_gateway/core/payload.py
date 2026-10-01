"""A provider's parsed answer, as the adapters see it (task 2b-repair-8, R7-2).

One defect came back three times (Socrata, then OpenCitations and eight more paths, then Hugging Face's file
siblings and ECB's data sets): a malformed member of a provider's list lost every readable member beside it,
because an adapter had its provider's list in hand — a plain Python list of raw members — and iterated, filtered,
indexed or flattened it before the member-by-member decoder ever ran. Every repair so far fixed the paths found and
tested for the next one by name, so the next spelling got past it. This module removes the cause: the adapters
never hold the plain list.

`Response.json` returns a VIEW of the parsed answer. A JSON object is an `Obj`, a JSON list is a `Members`, and
any other value is itself. A view wraps the parsed data and gives nothing back but views:

  * a `Members` cannot be iterated, indexed, sliced or tested for membership. It has a length (how many members the
    provider listed, readable or not: what paging arithmetic needs) and three ways to read its members, each
    isolating them: `decode` (each member on its own: one that is not an object or whose decoding fails is one
    unreadable member, and the rest stand), `first` (a lookup's first result) and `expand` (the members each member
    holds, where a member that cannot be unfolded is one unreadable member in place of what it held). Reading a
    member hands the builder an `Obj` too, so a list inside a member is a `Members` as well.
  * an `Obj` is read by key (`obj[k]`, `obj.get(k)`, `k in obj`); its values are views. It cannot be iterated and
    has no `keys()`, `items()` or `values()`, because a keyed container (an SDMX data set's series) holds members the
    same way a list does: `entries()` gives them as members.

So preprocessing a provider's members before decoding them — a filter comprehension, a `while` loop over an index,
`rows[0]`, a loop under another name, a flatten — has nothing to work on: the operation does not exist. What the
property covers is exactly that: a provider's list or keyed container cannot be iterated or indexed by any
spelling. What it does not cover is `plain()`, the one way out, which hands back the value as plain data. It is for
a list that is not a set of independent members — one record's own data (a record's authors or tags, a series'
observations, the rows of one table, a catalogue's entries) — whose reading is all-or-nothing by nature, and
tests/test_member_isolation.py lists every use of it with why."""
from __future__ import annotations

from collections.abc import Mapping


class PayloadError(ValueError):
    """An answer that is not the shape its adapter requires — an empty or unparseable body, or
    a parsed body without the container its results live in. The lane is unavailable with
    error_class payload_invalid: an unreadable answer is never zero results (INVARIANTS H-5,
    RG-4; design review §9, task 2b). Adapters use it through adapters.base."""


# what decoding one unreadable provider member raises (a missing key, a list where an object
# was expected, a value that is not a date ...): that member's failure, never the answer's
MEMBER_ERRORS = (PayloadError, KeyError, TypeError, AttributeError, ValueError, IndexError)

# what a builder returns for a member it read whole and found to name nothing to report (a deposited
# reference with no DOI): no record, and no malformed member either — that one is None, which the router counts
OMIT = object()

_UNREADABLE = object()   # in a Members built by expand(): a member that could not be unfolded; decodes as unreadable

_OBJ_USE = ("an Obj is read by key; a keyed container's members are read through entries() (each decoded alone), "
            "an object that is one record's own data through plain()")
_LIST_USE = ("a provider's list is read through base.members() or first_member() (each member decoded alone), "
             "or, when it is one record's own data, through plain()")


class Members:
    """A provider's list of members, which cannot be iterated or indexed (see the module docstring)."""
    __slots__ = ("_items",)
    __hash__ = None

    def __init__(self, items: list):
        self._items = items

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __repr__(self) -> str:
        return f"<Members of {len(self._items)}>"

    def __eq__(self, other) -> bool:
        return plain(self) == plain(other)

    def __iter__(self):
        raise TypeError(f"a Members cannot be iterated: {_LIST_USE}")

    def __reversed__(self):
        raise TypeError(f"a Members cannot be iterated: {_LIST_USE}")

    def __getitem__(self, _):
        raise TypeError(f"a Members cannot be indexed or sliced: {_LIST_USE}")

    def __contains__(self, _):
        raise TypeError(f"a Members cannot be searched: {_LIST_USE}")

    def decode(self, build) -> list:
        """Each member through `build` on its own, as an `Obj`: what `build` returns for it, None for a member that is
        not an object or whose decoding raises (what the router counts as dropped), nothing for one `build` calls OMIT."""
        out = []
        for member in self._items:
            try:
                rec = build(Obj(member)) if isinstance(member, dict) else None
            except MEMBER_ERRORS:
                rec = None
            if rec is not OMIT:
                out.append(rec)
        return out

    def first(self, build, source_id: str = ""):
        """The first member through `build`: None when there are none (or `build` calls OMIT). A first member that
        cannot be read is a PayloadError — an unreadable answer is never 'not found', and never answered by the member
        after it, which may be some other work."""
        if not self._items:
            return None
        got = Members(self._items[:1]).decode(build)
        if got and got[0] is None:
            raise PayloadError(f"{source_id + ': ' if source_id else ''}the answer's first result cannot be read")
        return got[0] if got else None

    def take(self, n: int) -> "Members":
        """The first `n` members."""
        return Members(self._items[:n])

    def expand(self, unfold) -> "Members":
        """The members that each member holds, in one list: `unfold` takes a member (an `Obj`) and returns a `Members`.
        A member that cannot be unfolded — not an object, or `unfold` raises — is ONE unreadable member in place of
        everything it held; the other members unfold as they would have alone."""
        out = []
        for member in self._items:
            try:
                if not isinstance(member, dict):
                    raise TypeError("not an object")
                out.extend(unfold(Obj(member))._items)
            except MEMBER_ERRORS:
                out.append(_UNREADABLE)
        return Members(out)


class Obj(Mapping):
    """A provider's object, read by key; what it gives back is a view (see the module docstring)."""
    __slots__ = ("_d",)
    __hash__ = None

    def __init__(self, d: dict):
        self._d = d

    def __getitem__(self, key):
        return view(self._d[key])

    def __iter__(self):
        raise TypeError(_OBJ_USE)

    def __len__(self) -> int:
        return len(self._d)

    def __repr__(self) -> str:
        return f"<Obj of {len(self._d)} keys>"

    def __eq__(self, other) -> bool:
        return plain(self) == plain(other)

    def keys(self):
        raise TypeError(_OBJ_USE)

    items = values = keys

    def entries(self) -> Members:
        """The members of a keyed container: one `{"key": ..., "value": ...}` object per entry."""
        return Members([{"key": k, "value": v} for k, v in self._d.items()])


def view(value):
    """A parsed value as the adapters see it: an Obj for an object, a Members for a list, anything else as it is."""
    if isinstance(value, dict):
        return Obj(value)
    if isinstance(value, list):
        return Members(value)
    return value


def plain(value):
    """The value as plain data: a view's own parsed object or list, and any view inside a plain dict, list or tuple.
    The one way out of a view, for data that is not a set of independent members (see the module docstring)."""
    if isinstance(value, Obj):
        return value._d
    if isinstance(value, Members):
        return value._items
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, tuple):
        return tuple(plain(v) for v in value)
    return value
