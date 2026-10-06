"""What a provider's answer is once it has been decoded (task 2b-repair-12, completed in 2b-repair-13a and -13c, and put under its trust model in 2b-repair-14).

TRUST MODEL B (INVARIANTS B-1; the operator's ruling of 2026-10-02; gateway/docs/STATION-CONTRACT.md, "The supported provider-input contract"). The gateway guarantees a complete contract for
SUPPORTED provider input: the response is a complete message, its bytes are valid in their format, the document is in the supported vocabulary, and what a lane reports is what was read — or the
lane is unavailable. First-party adapters are TRUSTED, REVIEWED CODE. What this module hands them — and what it withholds — is how that code is kept honest, not a confinement of Python: the
public operations that would read what an adapter must not decide from do not exist or raise, a declared-read inventory (tests/inventory.py) lists every place the code goes past them, and
review reads that list. Python identity checks (`x is None` on an `any_()` value), the private fields of these classes, importable helpers such as `plain` and finite testing are documented
boundaries of that model, not debts.

One defect family came back in every 2b round since repair-7 under a new spelling: malformed members, falsy wrong-kind holders, lazy `a or b` fallbacks, nested alternatives, contradictory
references, an untyped identifier, a conversion that raised. Each repair fixed the access patterns found and the next one got past it, because the cause was never removed: the contract
between a provider's answer and the rest of the gateway was incomplete. Repair-12 made validation eager and declared; repair-13a closed three gaps, as properties of the decoder and of
what it hands out:

  * FAILURES ARE TOTAL. Whatever a provider's value makes a conversion or a consistency rule do, the decoder's one channel for it is PayloadError, at the narrowest member boundary around it
    (core/schema.py); only UndeclaredRead — a programming error — passes through. MEMBER_ERRORS below is the one statement of what a builder's own reading of a member may raise.
  * DECLARATIONS ARE COMPLETE FOR WHAT DECIDES. A field declared `any_()` is handed over as a `Passive`: carried as sent, for storing, and nothing else — every public way of reading it (truth,
    equality, ordering, iteration, text, arithmetic, attributes) raises PassiveRead. So a value that identifies, selects, ends, continues or is sent in a request is declared a kind in
    its schema, or the first answer that reaches the read fails.
  * THE RAW ANSWER IS SEALED. An adapter is handed a Response that exposes no payload (adapters/base.py): the bytes of a payload are opened by the decoder, and what leaves the decoder for
    provenance — a member's `raw`, an `any_()` value — is a `Sealed`/`Passive` that is stored and not read, and leaves as a copy (`plain`).

What the decoder returns:

  * an object is a `Rec`, which holds exactly its declared fields. Reading one it does not declare raises UndeclaredRead — a failure, never a member's loss (it is not in MEMBER_ERRORS);
  * a list of independent members is a `MemberList`: every member already decoded alone (a `Rec`, or Unreadable where it could not be), and the list cannot be iterated, indexed or searched —
    only read through `members()`, `first_member()`, `take()` and `expand()`, which isolate each member, so none of the passes over a provider's candidates that lost a readable member to a
    malformed one (R7-2, three times: a filter, a `while`, `rows[0]`, a flatten) is an operation of the public API. A record's OWN list (its authors, its tags) is an ordinary list: it is
    all-or-nothing by nature;
  * every alternative a provider may state (`rightsIdentifier` or `rights`, `best_oa_location` or `oa_locations`, a structure's `Ref` or `URN`) is a declared field, decoded completely,
    nested contents included, before the adapter can choose between them.

`Rec.raw` is the member as the provider sent it, for a record's `raw` (I-8): a `Sealed`. The inventory (tests/inventory.py) lists every use of it that is not the value of a `raw=` argument,
with why, and fails one that is not listed.

WHERE A SEALED VALUE BECOMES PLAIN (2b-repair-13c, Astra R13A-2). Until then `make_record` returned `plain(record)`: a record's `raw` and its `extra` values were readable provider data the
moment the builder returned them, so `make_record(raw=row.raw)["raw"].get("timespan")` let a passive field decide which candidates an adapter kept, and no scan could see it. Now a record is
a plain dict whose provenance is still opaque: `raw` is a `Sealed`, and every `extra` value built from a decoded `any_()` field is still a `Passive` (or holds one). So are the bytes of a
download (`Response.download()` is a `Sealed`). The public operations on them do not read; they become plain at the reviewed sinks — where the gateway serializes or stores a result — and
`plain` is the one materialization, called nowhere else: `router.execute` (the answer and everything cached or written from it), `Cache.put_record` and `harvest/index.upsert` (the inventory
holds those three). A typed field of a record (title, venue, licence, identifiers, year ...) accepts its own typed domain and nothing the decoder issued (`make_record`): what is read or
decided on is declared a kind, and no typed field unwraps a decoded object.

Nothing compares a Sealed object with another (2b-repair-14): a raw an adapter passed `make_record` is a Sealed like any other, so a literal it chose cannot be compared with a decoded object
to learn whether they match. Two information-bearing predicates are sanctioned by name (the operator's ruling of 2026-10-02), each listed with its reason in the inventory: `Rec.empty`,
whether a decoded object held anything, used only at the reviewed provider-shape predicates; and `Rec.same_as`, whether two DECODED objects are the same one (did the provider repeat itself:
Unpaywall's best-location check), never for a value an adapter wrote. What stays outside the public operations, and is a documented boundary of the model and not a defect: Python cannot hide
an object's private storage, `x is None` cannot be intercepted, `plain` and `Sealed` are importable, and a finite corpus is not a proof (tests/test_sealed_payload.py says so). An adapter that
goes around the API is a reviewed-code failure the inventory is built to make visible.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET


class PayloadError(ValueError):
    """An answer that is not the shape its adapter requires — an empty or unparseable body, or a parsed body that does not
    decode against the operation's schema. The lane is unavailable with error_class payload_invalid: an unreadable answer is
    never zero results (INVARIANTS H-5, RG-4; design review §9, task 2b). Adapters use it through adapters.base."""


# What an adapter says when it cannot answer, and what the router turns each into (core/router.py). They are the contract between the two, so they live with the base both depend on
# (task 2q-b1: the router, in core, imported them from adapters.base, which depends on core); adapters use them through adapters.base, as they use PayloadError.
class AdapterError(Exception):
    """Raised by adapters for malformed input; never for source failures (those are Responses)."""


class ContinuationInvalid(Exception):
    """A continuation its source can no longer honour — the population it was counted in has
    changed (2b-repair-7 F3-R1). Nothing is read for it and nothing ends: more may remain
    that it cannot ask for. The router reports it unobserved, `partial_pagination`."""


class SourceUnavailable(Exception):
    """A source answered with an error (or the broker refused). The router turns
    this into a capability fact on the job (R-10); it is never a 'not found'."""

    def __init__(self, source_id: str, response):   # response: the adapters.base Response; what is read of it is its `status` and `error`
        detail = response.error or f"HTTP {response.status}"
        super().__init__(f"{source_id}: {detail}")
        self.source_id, self.response = source_id, response


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


def _refusal(held: "_Unread", how: str | None = None) -> UndeclaredRead:
    """The error that reading `held` (a Sealed or a Passive) raises. `how` names the way it was read: a special method's name, or `attribute 'x'`;
    None is a write, which is refused as a change (the object is never changed)."""
    if isinstance(held, Sealed):
        error, what, readable = SealedRead, "the provider's raw object", "it is for storing (a record's `raw=`); declare the field and read it decoded"
    else:
        error, what, readable = (PassiveRead, "this value is declared any_(): metadata carried as sent, stored and never read",
                                 "a value that decides anything is declared a kind in the schema")
    return error(f"{what} is not changed" if how is None else f"{what} ({how}); {readable}")


class _Unread:
    """What Sealed and Passive share: every way of reading an instance raises (task 2q-a-repair-3; it replaces the class decorator `_no_reading`, which installed these
    methods with `setattr`, a form the source contract (docs/gen2/SOURCE-CONTRACT.md) cannot model, and behaves exactly as it did). Each special method that reads —
    truth, ordering, iteration, subscript, text, number, arithmetic, call — raises the class's error through `_refusal`, and so does any attribute that is not its own (a dunder an
    introspecting library probes for is an AttributeError, as for any object) and any attempt to change one. Each subclass defines its own `__hash__`: a class that defines `__eq__`
    would otherwise get `__hash__ = None`, and hashing one raises the same error as every other read."""
    __slots__ = ()

    def __bool__(self, *args, **kwargs):
        raise _refusal(self, "__bool__")

    def __iter__(self, *args, **kwargs):
        raise _refusal(self, "__iter__")

    def __reversed__(self, *args, **kwargs):
        raise _refusal(self, "__reversed__")

    def __len__(self, *args, **kwargs):
        raise _refusal(self, "__len__")

    def __getitem__(self, *args, **kwargs):
        raise _refusal(self, "__getitem__")

    def __contains__(self, *args, **kwargs):
        raise _refusal(self, "__contains__")

    def __lt__(self, *args, **kwargs):
        raise _refusal(self, "__lt__")

    def __le__(self, *args, **kwargs):
        raise _refusal(self, "__le__")

    def __gt__(self, *args, **kwargs):
        raise _refusal(self, "__gt__")

    def __ge__(self, *args, **kwargs):
        raise _refusal(self, "__ge__")

    def __str__(self, *args, **kwargs):
        raise _refusal(self, "__str__")

    def __format__(self, *args, **kwargs):
        raise _refusal(self, "__format__")

    def __int__(self, *args, **kwargs):
        raise _refusal(self, "__int__")

    def __float__(self, *args, **kwargs):
        raise _refusal(self, "__float__")

    def __index__(self, *args, **kwargs):
        raise _refusal(self, "__index__")

    def __bytes__(self, *args, **kwargs):
        raise _refusal(self, "__bytes__")

    def __add__(self, *args, **kwargs):
        raise _refusal(self, "__add__")

    def __radd__(self, *args, **kwargs):
        raise _refusal(self, "__radd__")

    def __mul__(self, *args, **kwargs):
        raise _refusal(self, "__mul__")

    def __rmul__(self, *args, **kwargs):
        raise _refusal(self, "__rmul__")

    def __neg__(self, *args, **kwargs):
        raise _refusal(self, "__neg__")

    def __abs__(self, *args, **kwargs):
        raise _refusal(self, "__abs__")

    def __mod__(self, *args, **kwargs):
        raise _refusal(self, "__mod__")

    def __sub__(self, *args, **kwargs):
        raise _refusal(self, "__sub__")

    def __rsub__(self, *args, **kwargs):
        raise _refusal(self, "__rsub__")

    def __truediv__(self, *args, **kwargs):
        raise _refusal(self, "__truediv__")

    def __floordiv__(self, *args, **kwargs):
        raise _refusal(self, "__floordiv__")

    def __and__(self, *args, **kwargs):
        raise _refusal(self, "__and__")

    def __or__(self, *args, **kwargs):
        raise _refusal(self, "__or__")

    def __xor__(self, *args, **kwargs):
        raise _refusal(self, "__xor__")

    def __call__(self, *args, **kwargs):
        raise _refusal(self, "__call__")

    def __round__(self, *args, **kwargs):
        raise _refusal(self, "__round__")

    def __floor__(self, *args, **kwargs):
        raise _refusal(self, "__floor__")

    def __ceil__(self, *args, **kwargs):
        raise _refusal(self, "__ceil__")

    def __trunc__(self, *args, **kwargs):
        raise _refusal(self, "__trunc__")

    def __matmul__(self, *args, **kwargs):
        raise _refusal(self, "__matmul__")

    def __pow__(self, *args, **kwargs):
        raise _refusal(self, "__pow__")

    def __lshift__(self, *args, **kwargs):
        raise _refusal(self, "__lshift__")

    def __rshift__(self, *args, **kwargs):
        raise _refusal(self, "__rshift__")

    def __invert__(self, *args, **kwargs):
        raise _refusal(self, "__invert__")

    def __pos__(self, *args, **kwargs):
        raise _refusal(self, "__pos__")

    def __complex__(self, *args, **kwargs):
        raise _refusal(self, "__complex__")

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        raise _refusal(self, f"attribute {name!r}")

    def __setattr__(self, name, value):
        raise _refusal(self)


class Sealed(_Unread):
    """The provider's object exactly as it was sent (a member, a whole answer, a download's bytes), kept for storing in a record's `raw`.

    It is stored (`plain`, which hands out a copy: the object kept here is never reachable) and compared with nothing: reading it — truth, iteration, subscript, `.get`, any attribute — raises
    SealedRead, and so does comparing it with another Sealed. What an adapter decides, it decides from what the schema declared. (Until 2b-repair-14 two Sealed objects the decoder had issued
    compared equal and a flag on the object said which those were; `make_record` set it for any raw it was given, so a literal an adapter passed compared with a decoded object and told
    whether they matched — the guess Astra's R13C-2 mutant made. Nothing compares Sealed objects now: `Rec.same_as` is the one comparison, of two decoded objects.)"""
    __slots__ = ("_value",)

    def __init__(self, value):
        object.__setattr__(self, "_value", value)

    def __hash__(self, *args, **kwargs):
        raise _refusal(self, "__hash__")

    def __eq__(self, other) -> bool:
        if isinstance(other, Sealed):
            raise SealedRead("two sealed objects are not compared: a comparison of provider objects is Rec.same_as, between two decoded objects")
        return False   # a sealed object is not equal to a plain value, and asking reads nothing

    def __repr__(self) -> str:
        return "<Sealed>"

    def without(self, *names: str) -> "Sealed":
        """The same object without these fields, for a record whose raw may not keep part of what the provider sent (CORE's full text, I-7)."""
        if not isinstance(self._value, dict):
            raise SealedRead("without() takes fields out of an object")
        return Sealed({k: v for k, v in self._value.items() if k not in names})


class Passive(_Unread):
    """The value of a field a schema declares `any_()`: carried as sent, for storing in a record (`extra`, provenance), and nothing else.

    Every way of reading it raises PassiveRead — `if x`, `x == y`, `x in z`, `str(x)`, `f"{x}"`, `x[0]`, `x.get`, `int(x)`, `x + 1` — so a value that
    identifies a candidate, selects one, ends or continues a listing, or goes into a request cannot be one: the schema gives such a field a kind, and
    the decoder checks it. `plain()` is the one way out, and hands out a copy."""
    __slots__ = ("_value",)

    def __init__(self, value=None):
        object.__setattr__(self, "_value", value)

    def __hash__(self, *args, **kwargs):
        raise _refusal(self, "__hash__")

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
        """The object as the provider sent it, sealed: for a record's `raw=`, never for reading or comparing."""
        return Sealed(self._raw)

    @property
    def empty(self) -> bool:
        """Whether the provider's object says nothing: no field, no attribute, no text, no child. One of the two things about a decoded object an adapter may ask besides its declared fields,
        sanctioned for the provider-shape predicates the inventory lists (tests/inventory.py): an answer that holds an empty object where a record belongs, a structure that says nothing."""
        if isinstance(self._raw, ET.Element):
            return not (len(self._raw) or self._raw.attrib or (self._raw.text or "").strip())
        return not self._raw

    def same_as(self, other: "Rec") -> bool:
        """Whether `other` is the same provider object as this one: equal values of equal kinds (`1` is not `True`, `1` is not `1.0`). The other sanctioned question about decoded objects, for
        the intended comparisons the inventory lists (Unpaywall: is this listed location the best one the answer also states). It takes two decoded objects: a value an adapter wrote is not
        one, and nothing here compares an object with one — so it tells whether the provider repeated itself, never whether it said something an adapter guessed."""
        if not isinstance(other, Rec):
            raise TypeError("same_as compares two decoded objects")
        return _same(self._raw, other._raw)

    @property
    def declared(self) -> tuple:
        return tuple(self._v)

    def __repr__(self) -> str:
        return f"<Rec {', '.join(self._v)}>"

    def __iter__(self):
        raise TypeError("a Rec is read by its declared field names; it is not iterated")

    def __eq__(self, other) -> bool:
        raise SealedRead("a decoded object is compared with another by Rec.same_as, and with nothing else")


def detach(value):
    """A copy of the plain structure of a value — its dicts, lists and tuples, however nested — with every other object in it (a Passive, a Sealed, a decoded Rec) kept as the
    object it is: for a record's `extra`, which is not the adapter's to alias but whose opaque parts stay opaque."""
    if isinstance(value, dict):
        return {k: detach(v) for k, v in value.items()}
    if isinstance(value, list):
        return [detach(v) for v in value]
    if isinstance(value, tuple):
        return tuple(detach(v) for v in value)
    return value


def refuse_opaque(value, what: str) -> None:
    """Raise when `value` is, or holds anywhere in its lists, tuples and dicts, anything the decoder issued: `what` is a field that is read and decided on, so it must be declared a kind (a
    record's title, licence, identifiers ...), and what the decoder keeps of a provider's object is only stored. A Passive is a PassiveRead, a Sealed, a decoded Rec (whose original
    object `plain` would hand out) and a MemberList a SealedRead and an UndeclaredRead — programming errors; an Unreadable is a member that could not be read: a PayloadError."""
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, Passive):
            raise PassiveRead(f"{what} is built from a value declared any_(): metadata is stored, and a field that is read is declared a kind in the schema")
        if isinstance(v, (Sealed, Rec)):
            raise SealedRead(f"{what} is built from the provider's object, which is for storing (a record's `raw=`): a field that is read is declared a kind in the schema")
        if isinstance(v, MemberList):
            raise UndeclaredRead(f"{what} is built from a provider's list of members, which is read through members() and first_member()")
        if isinstance(v, Unreadable):
            raise PayloadError(f"{what} is built from a value that could not be read ({v.reason})")
        if isinstance(v, dict):
            stack.extend(v.values())
        elif isinstance(v, (list, tuple)):
            stack.extend(v)


def plain(value):
    """The value as plain data, COPIED: a Rec, a Sealed, a Passive and an Unreadable are the object the provider sent, and any of them inside a dict, list or
    tuple likewise. THIS IS THE ONE MATERIALIZATION of what the decoder keeps: a record's raw, its passive values and a download's bytes become data here and nowhere else, and it is called
    at the reviewed sinks alone — where the gateway serializes or stores a result (router.execute, cache.put_record, harvest/index.upsert; tests/inventory.py lists every call and fails
    one it does not). Never for reading a provider's field, and not in canonical-record construction: a typed field takes its own typed domain and a raw is stored sealed. What
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
