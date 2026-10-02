"""Task 2b-repair-9: the invariants, tested as invariants, over every adapter operation.

Four rounds in a row (Link headers, malformed members, wrong-kind containers, falsy wrong-kind containers) a provider answer
that could not be read was taken for a definite one — an end, an empty result, a complete one — and each round fixed the
inputs the reviewer had found while the reviewer found the next input beside them. The cause was the tests: each listed
instances of the defect instead of asserting what must hold for every input. This file asserts the invariants.

For each operation in tests/invariant_ops.py (each adapter's find, resolve, enrich, data, catalog and fetch, with valid provider-shaped
answers whose members, end fields and continuations are stated there by hand), it takes the valid answer and corrupts it at
every position of its structure: a wrong-typed value in the place of each container and scalar — false, 0, "", {}, [], null,
and a truthy wrong kind of each — or no value at all; and, for the fields that matter to a lane together (the containers that hold members, the
fields its end and continuation are read from, the count that lets a list be left out), at two of them at once. Each corrupted answer goes
through the real adapter and the real router, and the lane it comes out as is held to four statements:

  (a) a lane is `exhausted` or `complete` only if every field its end rule depends on was readable (and a continuation is
      offered only from a readable one);
  (b) an unreadable container is never an empty one: no zero count, no `searched_empty`, no zero it counted, and no record that says
      less than the provider said (a wrong-kind value inside a kept member is read as what it is, or the member is dropped and counted),
      when something that could hold members was present and unreadable;
  (c) readable members beside an unreadable one survive, as a partial lower bound;
  (d) nothing escapes as an unhandled error: the router answers, and a lane that cannot read its answer says so as the kind of error
      that reading a malformed value is.

What is read is decided here, by position and kind, and never by asking the adapter (`classify`, `readable`). The position pass is
exhaustive, so it is the same on every run. What is generated is seeded (SEED below; random.Random(seed).random() is the one function the
language guarantees across versions): non-objects mixed among readable members in every combination (MixedMembers), `Link` headers written
and damaged by grammar and read by a second reader (LinkHeaders, tests/invariant_links.py), SDMX-ML corruptions (XmlAnswers), and the
registry loaders' pages (RegistryLoaders). INVARIANT_SCALE=n multiplies the generated headers and cuts; INVARIANT_REPORT=<file> writes every
violation found as JSON, which is how the evidence for the repair was taken. A whole run takes about ten seconds.
What it cannot show: that a provider still answers as the fixtures say (Phase 4's canary), and anything about two corruptions of one answer
beyond the pairs of positions above, the mixed members and the damaged headers.

Metamorphic, not independent (2b-repair-9's R9-4, closed in 2b-repair-10b). Statement (b)'s field comparison and the loaders' field-loss comparison take
their baseline from the gateway itself (`baseline = run(op, valid)[0]`): a corrupted answer is held to how it may DIFFER from the gateway's answer to the
valid one. A defect the valid answer already has is in both, and nothing here sees it (a mutant that erased every title passed all 261 tests), and a second
implementation by the same authors (the Link reader below) shares the first one's blind spots. This harness stays as supplementary coverage of
how corruption changes an answer. It is not an oracle of what the answer must say, and nothing about it is to be described as independent: the
independent oracles are tests/test_oracle.py's (tests/oracle/*: expectations written from the RFC texts, the providers' documentation and the fixtures
by an author who had not read the gateway), which also append the documented optional fields of each provider to this harness's operations
(tests/oracle/variants.py, through tests/invariant_ops.py), so that this pass corrupts them too.
"""
from __future__ import annotations

import collections
import copy
import functools
import json
import os
import unittest
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from research_gateway import adapters
from research_gateway.adapters import openaire
from research_gateway.adapters.base import MEMBER_ERRORS, Client, FakeTransport, SourceUnavailable
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.registry.load import read_seed
from research_gateway.core.payload import plain
from tests import invariant_links as links
from tests import invariant_ops as ops
from tests.invariant_ops import Level, Op, corrupt_route

SEED = 20261001
SCALE = max(1, int(os.environ.get("INVARIANT_SCALE", "1")))
MISSING = object()          # the key is not there at all

# the wrong values put in a container's or scalar's place; each is wrong for at least the position it fills, and the falsy ones
# are the ones a truthiness test mistakes for "nothing there" (R8-2)
STRUCTURAL = (False, True, 0, -1, 1.5, "", "x", "7", None, [], {}, [1], {"a": 1}, MISSING)
INSIDE_A_MEMBER = (False, 0, "", None, [], {}, "x", 5, MISSING)
OK, MAYBE, BAD, GONE = "ok", "maybe", "bad", "gone"


class Rng:
    """random.Random(seed).random() is the one function the language guarantees to give the same sequence for the same seed
    in every version; everything here is made from it."""

    def __init__(self, seed: int):
        import random
        self._r = random.Random(seed)

    def below(self, n: int) -> int:
        return min(n - 1, int(self._r.random() * n))

    def chance(self, p: float) -> bool:
        return self._r.random() < p

    def pick(self, seq):
        return seq[self.below(len(seq))]


# ------------------------------------------------------------------ the answer, as data
def get(body, path):
    for step in path:
        body = body[step]
    return body


def safe_get(body, path):
    """The value at `path`, or MISSING when a step is not there."""
    for step in path:
        if isinstance(body, dict) and step in body:
            body = body[step]
        elif isinstance(body, list) and isinstance(step, int) and step < len(body):
            body = body[step]
        else:
            return MISSING
    return body


def put(body, path, value):
    """A copy of `body` with `value` at `path` (MISSING: the key removed)."""
    if not path:
        return value
    out = copy.deepcopy(body)
    parent = get(out, path[:-1])
    if value is MISSING:
        del parent[path[-1]]
    else:
        parent[path[-1]] = value
    return out


def nodes(body, path=()):
    """Every position of the answer, containers and leaves, outermost first, keys in their order."""
    yield path
    if isinstance(body, dict):
        for k, v in body.items():
            yield from nodes(v, path + (k,))
    elif isinstance(body, list):
        for i, v in enumerate(body):
            yield from nodes(v, path + (i,))


def same(a, b) -> bool:
    return type(a) is type(b) and a == b


def encode(value) -> bytes:
    return json.dumps(value).encode()


# ------------------------------------------------------------------ what the answer holds
@dataclass(frozen=True)
class Member:
    path: tuple
    ident: str


def members_of(op: Op, body) -> tuple[list[Member], frozenset, bool]:
    """(the members of the valid answer with the identity each names, the key paths whose absence is a permitted empty,
    whether the last level is keyed). Read from the levels of `op`; the identities are `op.ids`, in order."""
    if op.single is not None:
        return [Member(op.single, op.ids[0])], frozenset(), False
    if op.explicit:
        return [Member(p, i) for p, i in zip(op.explicit, op.ids)], frozenset(op.explicit), False
    optional, current = set(), [()]
    for level in op.levels:
        following = []
        for base in current:
            if level.optional_from is not None:
                optional.update(base + level.path[:k + 1] for k in range(level.optional_from, len(level.path)))
            container = get(body, base + level.path)
            keys = range(len(container)) if isinstance(container, list) else list(container)
            following += [base + level.path + (k,) for k in list(keys)[:level.take]]
        current = following
    assert len(current) == len(op.ids), f"{op.name}: {len(current)} members in the answer, {len(op.ids)} identities stated"
    return [Member(p, i) for p, i in zip(current, op.ids)], frozenset(optional), op.levels[-1].kind is dict


def classify(member: Member, path: tuple, value, optional: frozenset, keyed: bool, leaf: str = "object", bare_row: bool = False) -> str:
    """What putting `value` at `path` does to `member`, from the structure alone:
    ok (nothing touched), maybe (something inside it changed: it may or may not still be readable), bad (it is no longer
    a readable member, or what holds it is unreadable), gone (legitimately not there: a valid empty container, or a
    container the provider is allowed to leave out). `leaf` is what the member itself must be: an "object", a "list" (a holder),
    or "any" value (a keyed entry whose key is all that is read)."""
    at = member.path
    if not (at[:len(path)] == path or path[:len(at)] == at):
        return OK
    if len(path) > len(at):
        return MAYBE
    if (value is MISSING or value is None) and path in optional:
        return GONE
    if value is MISSING:
        return GONE if keyed and path == at else BAD   # a keyed container that no longer has the entry: the entry is not there
    current, rest = value, at[len(path):]
    for i, step in enumerate(rest):
        here, last = at[:len(path) + i + 1], len(path) + i + 1 == len(at)
        if isinstance(step, int):
            if bare_row and isinstance(current, dict) and current and last:
                current = [current]
            if not isinstance(current, list):
                return BAD
            if step >= len(current):
                return GONE
            current = current[step]
        else:
            if not isinstance(current, dict):
                return BAD
            if step not in current:
                return GONE if (last and keyed) or here in optional else BAD
            current = current[step]
        if current is None and here in optional:
            return GONE
    if leaf == "url":
        return GONE if current is None or current == "" else MAYBE if isinstance(current, str) else BAD
    return MAYBE if leaf == "any" or isinstance(current, {"object": dict, "list": list}.get(leaf, object)) else BAD


def readable(body, path: tuple, kind: str, floor: int = 0) -> bool:
    """Whether the field at `path` of `body` can be read as `kind`, by what a field of that kind is:
    list, dict; total (a whole number, not a boolean, no smaller than the records seen); token (a non-blank string: the opaque
    cursor a provider hands back to continue); offset (a whole number past where the page started: the next offset); same (a
    token: it is read only to see whether it equals the one sent); absent (the key is missing or null, under a parent that is an object)."""
    current = body
    for i, step in enumerate(path):
        if isinstance(step, int):
            if not isinstance(current, list) or step >= len(current):
                return False
            current = current[step]
        else:
            if not isinstance(current, dict):
                return False
            if step not in current:
                return kind == "absent" and i == len(path) - 1
            current = current[step]
    if kind == "absent":
        return current is None
    if kind == "list":
        return isinstance(current, list)
    if kind == "dict":
        return isinstance(current, dict)
    whole = isinstance(current, int) and not isinstance(current, bool)
    if kind == "total":
        return whole and current >= floor
    if kind in ("token", "same"):
        return isinstance(current, str) and bool(current.strip())
    if kind == "offset":
        return whole and current > 0   # the next offset of a first page, which started at 0
    raise ValueError(kind)


def related(a: tuple, b: tuple) -> bool:
    return a[:len(b)] == b or b[:len(a)] == a


# ------------------------------------------------------------------ running one answer through the real router
_ROUTERS: dict = {}
LANE_ERRORS = ("payload_invalid",)
MEMBER_ERROR_NAMES = {e.__name__ for e in MEMBER_ERRORS}


def router_for(op: Op):
    if op.name not in _ROUTERS:
        wanted = {op.sid, "doi_org"} if op.agency else {op.sid}
        loaded = adapters.load_all()
        _ROUTERS[op.name] = R.Router([{**s, **(op.seed or {})} if s["id"] == op.sid else s for s in read_seed() if s["id"] in wanted],
                                     {sid: m for sid, m in loaded.items() if sid in wanted})
    return _ROUTERS[op.name]


def run(op: Op, body, headers=None):
    """(the router's answer, this operation's lane entry) for `body` as the corrupted route's answer."""
    t = FakeTransport()
    c = Client(broker=Broker({s: RatePolicy(per_second=100000) for s in (op.sid, "doi_org")}), transport=t, secrets=lambda n, f=None: "k",
               sleep=lambda s: None)
    if op.sid == "openaire":
        openaire.reset_token()
        t.add("POST", openaire.TOKEN_URL, 200, {"access_token": "tok", "expires_in": 3600})
    if op.agency:
        t.add("GET", "https://doi.org/ra/", 200, [{"DOI": op.request["identity"].split(":", 1)[1], "RA": op.agency}])
    for route in op.routes:
        t.add(route.method, route.url, 200, encode(body) if route.corrupt else (route.body if isinstance(route.body, (bytes, str)) else encode(route.body)),
              headers=headers if route.corrupt and headers is not None else route.headers)
    out = R.execute(router_for(op), op.request, c)
    return out, next(e for e in out["lanes"] if e["source"] == op.sid)


@dataclass(frozen=True)
class Violation:
    invariant: str
    op: str
    path: object
    value: str
    detail: str


def nothing(x) -> bool:
    return x is None or x is False or x == 0 or x == "" or x == [] or x == {} or x == ()


def emptier(was, now, value) -> bool:
    """Whether `now` says less than `was`: it is nothing where `was` was something, or it has fewer entries, or one of its entries says less.
    A value carried into the record as the provider sent it (`value`: a wrong-kind one in a raw row, or in a field passed through) is not
    read as anything, and does not count; nor does a different value."""
    if was == now or now == value:
        return False
    if nothing(now):
        return not nothing(was)
    if isinstance(was, dict) and isinstance(now, dict):
        return any(emptier(was[k], now.get(k), value) for k in was)
    if isinstance(was, (list, tuple)) and isinstance(now, (list, tuple)):
        return len(now) < len(was) or any(emptier(a, b, value) for a, b in zip(was, now))
    return False


def show(value) -> str:
    return "<missing>" if value is MISSING else json.dumps(value)


VOLATILE = ("raw", "provenance", "retrieved_at", "sources", "metadata_license", "freshness_lag", "permissions", "rank", "download_request")


def kind_of(value) -> str:
    return "null" if value is None else "bool" if isinstance(value, bool) else type(value).__name__


ORDER = (OK, MAYBE, GONE, BAD)   # what two corruptions of one member come to: the worse of the two (one that is gone is gone; one that is unreadable is unreadable)


def judge(op: Op, valid, path: tuple, value, optional: frozenset, keyed: bool, mem: list[Member], lane: dict, out: dict | None,
          error: BaseException | None, records: list | None = None, baseline: dict | None = None) -> list[Violation]:
    """The lane `lane` that corrupting `path` with `value` produced, held to the four invariants. `lane` is the router's lane entry."""
    return judge_changes(op, valid, ((path, value),), optional, keyed, mem, lane, out, error, records, baseline)


def judge_changes(op: Op, valid, changes: tuple, optional: frozenset, keyed: bool, mem: list[Member], lane: dict, out: dict | None,
                  error: BaseException | None, records: list | None = None, baseline: dict | None = None) -> list[Violation]:
    """The same, for an answer corrupted at one position (`changes` of one) or at two that neither contains the other."""
    path, value = changes[0]

    def violation(inv, detail):
        return Violation(inv, op.name, list(path) if len(changes) == 1 else [list(p) for p, _ in changes],
                         show(value) if len(changes) == 1 else " & ".join(show(v) for _, v in changes), detail)

    if error is not None:
        return [violation("d", f"the router raised {type(error).__name__}: {str(error)[:120]}")]
    corrupted = valid
    for p, v in changes:
        corrupted = put(corrupted, p, v) if p else v
    found = [(max((classify(m, p, v, optional, keyed, op.leaf, op.bare_row) for p, v in changes), key=ORDER.index), m) for m in mem]
    if any(safe_get(corrupted, holder) in (MISSING, None) and type(safe_get(corrupted, count)) is int and safe_get(corrupted, count) == 0
           for holder, count in op.empty_when):
        found = [(GONE, m) for _, m in found]   # the provider may leave a list out when it counts nothing
    state = {s: [m for st, m in found if st == s] for s in (OK, MAYBE, BAD, GONE)}
    shared_hit = any(related(p, s) for p, _ in changes for s in op.shared)
    completeness, coverage = lane.get("completeness"), lane.get("coverage")
    retrieved, count = lane.get("retrieved") or [], lane.get("count")
    problems = []
    # (d) an answer that cannot be read fails its lane as payload_invalid, and as one of the errors that reading a malformed value is
    # (MEMBER_ERRORS: the failures the member decoder treats as that member's): anything else is a crash the router's net happened to catch
    if "error" in lane and op.typed and lane["error"].split(":", 1)[0] not in MEMBER_ERROR_NAMES:
        problems.append(violation("d", f"the lane failed with {lane['error'][:120]}"))
    if "error" in lane and lane.get("error_class") not in LANE_ERRORS:
        problems.append(violation("d", f"the lane failed as {lane.get('error_class')}, not payload_invalid: {lane['error'][:100]}"))
    # (c) readable members survive; counting is consistent
    if count is not None and count != len(retrieved):
        problems.append(violation("c", f"count {count} but {len(retrieved)} identities retrieved"))
    if state[OK] and not shared_hit and not op.whole:
        if completeness == "unobserved":
            problems.append(violation("c", f"{len(state[OK])} readable member(s) beside the corruption, and the lane is unobserved ({lane.get('error', lane.get('error_class'))})"))
        else:
            lost = collections.Counter(m.ident for m in state[OK]) - collections.Counter(retrieved)
            if lost:
                problems.append(violation("c", f"readable member(s) lost: {sorted(lost.elements())}"))
    # (b) an unreadable container is never an empty one
    if coverage == "searched_empty" or count == 0:
        if state[OK] or state[MAYBE] or state[BAD]:
            problems.append(violation("b", f"an empty answer ({coverage}, count {count}) from a corrupted answer that holds "
                                           f"{len(state[OK])} readable, {len(state[MAYBE])} unknown and {len(state[BAD])} unreadable member(s)"))
    if state[BAD] and not state[OK] and not state[MAYBE]:
        if completeness != "unobserved" or count is not None:
            problems.append(violation("b", f"every member's container is unreadable, yet the lane is {completeness} with count {count}"))
    for field, holder, leaving_out_is_empty in op.zero_counts if len(changes) == 1 else ():
        for rec in records or []:
            if rec.get(field) in (0, []):
                for m in mem:
                    held = Member(m.path + holder, m.ident)
                    unreadable = classify(held, path, value, optional | ({held.path} if leaving_out_is_empty else set()), False, "list") == BAD
                    if unreadable and (op.single is not None or rec.get("identity") == m.ident):
                        problems.append(violation("b", f"{field} is {rec[field]!r}, and what it counts ({'.'.join(map(str, holder)) or 'the answer'}) is unreadable"))
    # (b), in a record that is kept: a value of the wrong kind inside a readable member never reads as an empty or absent one — it changes
    # nothing the record says, or the member is dropped and counted. (A value carried into the record as it was sent is not changed.)
    if len(changes) == 1 and baseline and records is not None and len(set(op.ids)) == len(op.ids) and path and value is not MISSING and value is not None:
        here = valid if not path else get(valid, path)
        inside = [m for m in mem if len(path) > len(m.path) and path[:len(m.path)] == m.path]
        if inside and kind_of(value) != kind_of(here):
            known = {r["identity"]: r for r in baseline.get("records", [])}
            for rec in records:
                for f, was in known.get(rec.get("identity"), {}).items():
                    now = rec.get(f)
                    if f not in VOLATILE and not (now is None and f in op.unknowable) and emptier(was, now, value):
                        problems.append(violation("b", f"{rec['identity']}: {f} was {was!r}, and is {now!r}: a {kind_of(value)} where a {kind_of(here)} was read as if it said nothing"))
    # (a) a lane is complete or exhausted, and offers a continuation, only from fields it could read
    if completeness == "complete" and state[BAD]:
        problems.append(violation("a", f"complete, with {len(state[BAD])} member(s) whose container is unreadable"))
    present = len([m for st, m in found if st != GONE])   # what the corrupted answer lists: a total may not be smaller than that
    if lane.get("exhausted") is True:
        floor = present
        if completeness != "complete" or state[BAD]:
            problems.append(violation("a", f"exhausted while {completeness}, with {len(state[BAD])} unreadable member(s)"))
        if not any(all(readable(corrupted, p, k, floor) for p, k in alternative) for alternative in op.end):
            problems.append(violation("a", "exhausted, and no complete set of the fields its end rule reads is readable"))
    if "next" in lane:
        if completeness == "unobserved":
            problems.append(violation("a", "a continuation from a lane that observed nothing"))
        if not all(readable(corrupted, p, k, present) for p, k in op.cursor):
            problems.append(violation("a", "a continuation offered although the field it is made from is unreadable"))
    return problems


# ------------------------------------------------------------------ the corruptions
def positions(op: Op, valid, mem: list[Member]):
    """(path, the values to put there) for every position of the answer: the whole alphabet where a container, a field the answer's end or
    continuation is read from, or a member itself stands, and the shorter one (INSIDE_A_MEMBER) for the fields inside a member. Nothing is
    sampled: every position of every member is corrupted, so the pass is the same on every run."""
    inside = [m.path for m in mem]
    for path in nodes(valid):
        under = any(len(path) > len(m) and path[:len(m)] == m for m in inside)
        values = INSIDE_A_MEMBER if under else STRUCTURAL
        current = get(valid, path) if path else valid
        yield path, [v for v in values if not same(v, current) and not (v is MISSING and (not path or isinstance(path[-1], int)))]


PAIR_VALUES = (False, 0, 0.0, "0", [], None, MISSING)


def pairs(op: Op, valid, mem: list[Member]):
    """((path, value), (path, value)) for two positions of the answer that matter to a lane — the containers that hold members, the fields
    its end and its continuation are read from, the fields every member shares, the count that lets a list be left out — neither of which
    contains the other. What one corruption of each does together is not what each does alone: a list left out is empty only when the
    count says zero, and a count garbled beside it says nothing."""
    relevant = {m.path[:k] for m in mem for k in range(1, len(m.path))} | {p for alt in op.end for p, _ in alt} | {p for p, _ in op.cursor} | set(op.shared)
    relevant |= {p for pair in op.empty_when for p in pair}
    paths = sorted(p for p in relevant if p and safe_get(valid, p) is not MISSING)
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if related(a, b):
                continue
            first, second = ([v for v in PAIR_VALUES if not same(v, get(valid, p)) and not (v is MISSING and isinstance(p[-1], int))] for p in (a, b))
            for va in first:
                for vb in second:
                    yield (a, va), (b, vb)


@functools.lru_cache(maxsize=None)
def corruption_report(name: str) -> tuple:
    op = ALL[name]
    valid = json.loads(json.dumps(corrupt_route(op).body))   # a plain copy: no object of the fixture is shared by two places in it
    mem, optional, keyed = members_of(op, valid)
    found, runs = [], 0
    baseline = run(op, valid)[0]
    for path, values in positions(op, valid, mem):
        for value in values:
            runs += 1
            corrupted = put(valid, path, value) if path else value
            error = out = lane = None
            try:
                out, lane = run(op, corrupted)
            except Exception as e:   # (d): nothing may escape the router
                error = e
            found += judge(op, valid, path, value, optional, keyed, mem, lane, out, error, (out or {}).get("records"), baseline)
    for changes in pairs(op, valid, mem):
        runs += 1
        corrupted = valid
        for p, v in changes:
            corrupted = put(corrupted, p, v)
        error = out = lane = None
        try:
            out, lane = run(op, corrupted)
        except Exception as e:   # (d)
            error = e
        found += judge_changes(op, valid, changes, optional, keyed, mem, lane, out, error)
    return tuple(found), runs


ALL = {op.name: op for op in (*ops.FIND_OPS, *ops.RESOLVE_OPS, *ops.ENRICH_OPS, *ops.DATA_OPS, *ops.FETCH_OPS, *ops.CATALOG_OPS)}


def register(extra) -> None:
    ALL.update({op.name: op for op in extra})


# ------------------------------------------------------------------ the tests
class Controls(unittest.TestCase):
    """The valid answer of each operation is read whole, and says what the operation's fixture says (its identities and lane shape; the canonical
    fields of each record are tests/test_oracle.py's, from hand-written expectations: this harness only compares a corrupted answer with the valid one)."""

    def test_the_valid_answer_of_each_operation_is_its_stated_answer(self):
        for name, op in ALL.items():
            with self.subTest(name):
                out, lane = run(op, copy.deepcopy(corrupt_route(op).body))
                self.assertEqual((lane["coverage"], lane["completeness"], lane.get("error_class"), lane.get("retrieved")),
                                 ("searched_ok", "complete", None, list(op.ids)), lane)
                if op.find:
                    self.assertEqual((lane.get("exhausted") is True, "next" in lane), (op.exhausted, op.continues), lane)


class Judge(unittest.TestCase):
    """The harness's own teeth: each way of failing an invariant, put to `judge` as an answer, is found; and an honest answer is not."""

    OP = ops.CROSSREF_FIND_END
    VALID = corrupt_route(OP).body

    def judged(self, path, value, lane, error=None):
        mem, optional, keyed = members_of(self.OP, self.VALID)
        return {v.invariant for v in judge(self.OP, self.VALID, path, value, optional, keyed, mem, lane, {}, error)}

    def test_each_invariant_finds_its_violation(self):
        ok = {"coverage": "searched_ok", "completeness": "complete", "retrieved": ["doi:10.1000/a1", "doi:10.1000/a2"], "count": 2, "exhausted": True}
        self.assertEqual(self.judged(("message", "total-results"), "x", ok), set(), "an honest answer to a corruption that matters to nothing")
        self.assertEqual(self.judged(("message", "items"), False, ok), {"a", "b"}, "complete and exhausted from an unreadable list; a count from it")
        self.assertEqual(self.judged(("message", "items"), False, {"coverage": "searched_empty", "completeness": "complete", "count": 0, "retrieved": []}), {"a", "b"})
        self.assertEqual(self.judged(("message", "total-results"), "x", {"coverage": "provider_unavailable", "completeness": "unobserved"}), {"c"},
                         "readable members lost to an unreadable total")
        self.assertEqual(self.judged(("message", "items", 0), 7, {**ok, "retrieved": ["doi:10.1000/a2"], "count": 1}), {"a"},
                         "complete and exhausted although one member was lost")
        self.assertEqual(self.judged(("message", "total-results"), "x", ok, error=TypeError("x")), {"d"})
        crash = {"coverage": "provider_unavailable", "completeness": "unobserved", "error_class": "payload_invalid"}
        self.assertEqual(self.judged(("message", "total-results"), "x", {**crash, "error": "AttributeError: 'int' object has no attribute 'get'"}), {"c"},
                         "a malformed value read badly is the answer's to lose, and the member beside it is lost with it: (c), but the router's net was meant for this")
        self.assertEqual(self.judged(("message", "total-results"), "x", {**crash, "error": "ZeroDivisionError: division by zero"}), {"c", "d"},
                         "an error that reading a malformed value is not")
        self.assertEqual(self.judged(("message", "total-results"), "x", {**crash, "error_class": "provider_outage", "error": "PayloadError: x"}), {"c", "d"})

    def test_a_field_is_read_by_its_kind_and_a_member_by_its_place(self):
        body = {"n": 3, "next": None, "t": "tok", "z": [], "m": {"k": [1]}}
        for path, kind, floor, want in ((("n",), "total", 3, True), (("n",), "total", 4, False), (("t",), "total", 0, False), (("t",), "token", 0, True),
                                        (("n",), "token", 0, False), (("n",), "offset", 0, True), (("t",), "offset", 0, False), (("z",), "list", 0, True), (("m",), "list", 0, False), (("m", "k"), "list", 0, True),
                                        (("next",), "absent", 0, True), (("nope",), "absent", 0, True), (("n", "x"), "absent", 0, False),
                                        (("n",), "absent", 0, False), (("t",), "same", 0, True)):
            self.assertEqual(readable(body, path, kind, floor), want, (path, kind))
        self.assertFalse(readable({"n": True}, ("n",), "total"))
        self.assertFalse(readable({"t": "  "}, ("t",), "token"))
        self.assertFalse(readable({"n": -1}, ("n",), "offset"))
        self.assertFalse(readable({"n": 0}, ("n",), "offset"), "an offset that does not advance")
        member = Member(("a", "items", 1), "x")
        optional = frozenset({("a", "items")})
        for path, value, want in ((("a", "items", 0), 7, OK), (("a", "items", 1, "x"), 7, MAYBE), (("a", "items", 1), 7, BAD),
                                  (("a", "items", 1), {}, MAYBE), (("a", "items"), [], GONE), (("a", "items"), None, GONE), (("a", "items"), False, BAD),
                                  (("a", "items"), {}, BAD), (("a",), {}, GONE), (("a",), False, BAD), (("a",), [], BAD), ((), False, BAD),
                                  (("a", "items"), [1, 2], BAD), (("a", "items"), [{}, {}], MAYBE)):
            self.assertEqual(classify(member, path, value, optional, False), want, (path, value))
        self.assertEqual(classify(Member(("s", "0:1"), "x"), ("s",), {}, frozenset(), True), GONE, "an entry a keyed container no longer has")
        self.assertEqual(classify(Member(("s", "0:1"), "x"), ("s",), {}, frozenset(), False), BAD)


BAD_MEMBERS = (7, "x", None, [], False, 0, "", [1], 1.5, ["a"])


class MixedMembers(unittest.TestCase):
    """Non-objects among readable members, in every combination (and, by the seed, with every kind): exactly the readable ones are
    kept, in order, as a partial lower bound; none readable is unobserved and never zero; an answer read whole is unreadable."""

    def test_the_members_that_are_readable_are_exactly_the_ones_kept(self):
        rng, wrong, runs = Rng(SEED), [], 0
        for name, op in ALL.items():
            if op.single is not None or op.leaf == "any":
                continue
            valid = json.loads(json.dumps(corrupt_route(op).body))
            mem, optional, keyed = members_of(op, valid)
            for mask in range(1, 2 ** len(mem)):
                body = valid
                for j, m in enumerate(mem):
                    if mask >> j & 1:
                        # only what the harness's own classifier calls a bad member of this operation: for a `url` leaf, `None` and `""` are a link the
                        # provider leaves out (no file, not an unreadable one) and text is a link, however odd (OpenML's `url`, `parquet_url`)
                        bad = [v for v in BAD_MEMBERS if classify(m, m.path, v, optional, keyed, op.leaf, op.bare_row) == BAD]
                        body = put(body, m.path, rng.pick(bad))
                kept = [m.ident for j, m in enumerate(mem) if not mask >> j & 1]
                out, lane = run(op, body)
                runs += 1
                got = (lane["completeness"], lane.get("count"), lane.get("retrieved"), lane.get("error_class"), lane.get("exhausted") is True)
                want = (("unobserved", None, None, "payload_invalid", False) if op.whole or not kept else
                        ("partial", len(kept), kept, "payload_invalid", False))
                if got != want:
                    wrong.append((name, [m.path for j, m in enumerate(mem) if mask >> j & 1], got, want))
        self.assertGreater(runs, 100)
        self.assertEqual(wrong, [], f"{len(wrong)} of {runs} mixes; the first: {wrong[:2]}")

    def test_an_empty_container_is_empty_when_it_is_a_valid_one(self):
        """The other side of (b): a page the provider sends with no members is `searched_empty` — the invariants do not make an
        answer unreadable merely for holding nothing."""
        for name, op in ALL.items():
            if not op.find or op.leaf == "any":
                continue
            with self.subTest(name):
                valid = json.loads(json.dumps(corrupt_route(op).body))
                path = op.levels[0].path
                out, lane = run(op, put(valid, path, []))
                self.assertEqual((lane["coverage"], lane["completeness"], lane.get("count"), lane.get("retrieved")), ("searched_empty", "complete", 0, []))


class LinkHeaders(unittest.TestCase):
    """Hugging Face pages by its `Link` header: every generated header is read by a second reader (tests/invariant_links.py: not independent of the
    gateway's authors, with the URI productions of the oracle's RFC 3986 transcription) and by the gateway, through the real adapter and router, and they must
    agree — a continuation where the reader found a next link, an end only where it read a header whole that names none, and neither for a header that does
    not read through. What holds the reading to the RFCs is tests/test_oracle.py's vectors."""
    OP = ops.HF_FIND_END

    def test_the_second_reader_agrees_with_the_grammar(self):
        nxt = "https://example.org/n"
        for header, want in ((f'<{nxt}>; rel="next"', ("known", {nxt})), (f"<{nxt}>; rel=next; rel=prev", ("known", {nxt})),
                             (f'<{nxt}>; rel="prev"; rel="next"', ("known", set())), (f'<{nxt}>; rel="https://example.org/next"', ("known", set())),
                             ("", ("known", set())), (", ,", ("known", set())), (f'<{nxt}>; title="a, b"; rel="prev next"', ("known", {nxt})),
                             (f'<{nxt}>; rel="\\"next\\""', ("unknown",)), (f'<{nxt}>; rel=""', ("unknown",)), (f'<{nxt}>; rel="next, prev"', ("unknown",)),
                             (f'<{nxt}>; rel="next\x01"', ("unknown",)), (f"<{nxt}>; rel='next'", ("unknown",)), (f"<{nxt}>; rel", ("unknown",)),
                             (f'<{nxt}>; rel="next" junk', ("unknown",)), (f'<{nxt}>; title="a\x01"; rel="prev"', ("unknown",)),
                             (f'<{nxt}>; rel="next", <https://example.org/m>; rel="next"', ("unknown",)),
                             (f'<{nxt}>; rel="1x"', ("unknown",)), (f'<{nxt}>; rel="  next"', ("unknown",))):
            with self.subTest(header):
                got = links.read(header)
                self.assertEqual((got[0], set(got[1]) if len(got) > 1 else None), (want[0], want[1] if len(want) > 1 else None))

    def test_generated_headers_are_read_alike(self):
        rng, disagree, kinds = Rng(SEED + 1), [], collections.Counter()
        valid = json.loads(json.dumps(corrupt_route(self.OP).body))
        for _ in range(600 * SCALE):
            header = links.generate(rng)
            said = links.read(header)
            out, lane = run(self.OP, valid, {"Link": header})
            if said[0] == "unknown":
                want = "neither"
            elif not said[1]:
                want = "end"
            else:
                (target,) = said[1]
                want = ("next", target) if links.stays_in_the_search(target) else "neither"
            got = ("next", lane["next"]) if "next" in lane else "end" if lane.get("exhausted") is True else "neither"
            kinds[want if isinstance(want, str) else "next"] += 1
            if got != want or (want == "neither" and (lane["completeness"], lane.get("error_class")) != ("partial", "partial_pagination")):
                disagree.append((header, want, got, lane.get("error_class")))
        self.assertGreater(min(kinds.values()), 20, f"every kind of header is generated: {kinds}")
        self.assertEqual(disagree, [], f"{len(disagree)} headers read differently; the first: {disagree[:3]}")


SDMX_NS = "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"


def bis_message(series: list[str], body: str = "") -> str:
    return (f'<message:StructureSpecificData xmlns:message="{SDMX_NS}"><message:Header><message:ID>x</message:ID></message:Header>'
            f'<message:DataSet>{"".join(series)}</message:DataSet>{body}</message:StructureSpecificData>')


def bis_series(area: str, extra: str = "") -> str:
    return f'<Series FREQ="M" REF_AREA="{area}"><Obs TIME_PERIOD="2026-01" OBS_VALUE="1.5"/>{extra}</Series>'


class XmlAnswers(unittest.TestCase):
    """SDMX-ML: BIS's series and the dataflow listings of ECB and BIS are XML, which a JSON corruption cannot reach. The same invariants, for
    the corruptions of XML: a body that does not parse, an element that is no member, a member missing what names it, an element that is not
    where it belongs. Well-formed XML fixes the types of its parts (everything is text), so what can be wrong is structure, not kind."""
    AREAS = ("US", "GB", "DE")
    SERIES_IDS = tuple(f"series:bis:WS_EER:M.{a}" for a in AREAS)
    REQUEST = {"request_type": "data", "source": "bis", "params": {"dataflow": "WS_EER", "key": "M"}}
    URL = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_EER/1.0/M"

    def lane(self, request, url, text):
        t = FakeTransport()
        t.add("GET", url, body=text.encode(), headers={"Content-Type": "application/xml"})
        c = Client(broker=Broker({"bis": RatePolicy(per_second=1000), "ecb": RatePolicy(per_second=1000)}), transport=t, sleep=lambda s: None)
        out = R.execute(R.Router(read_seed(), adapters.load_all()), request, c)
        return out, next(e for e in out["lanes"] if e["source"] == request["source"])

    def corruptions(self):
        """(what, the message, the series left untouched), from structure alone: the series of the valid message are `AREAS`, in order."""
        rng, valid = Rng(SEED + 7), [bis_series(a) for a in self.AREAS]
        message = bis_message(valid)
        yield "the valid message", message, set(self.AREAS)
        for what, text in (("nothing", ""), ("not XML", "x"), ("JSON", "{}"), ("HTML", "<html></html>"), ("another root", "<Foo/>"), ("junk after", message + "x"),
                           ("a message with no data set", bis_message([]).replace("<message:DataSet></message:DataSet>", "")),
                           ("a data set of no series", bis_message([]))):
            yield what, text, set()
        for _ in range(24 * SCALE):
            cut = 1 + rng.below(len(message) - 1)
            yield f"cut at {cut}", message[:cut], set()
        variants = {"no attributes": "<Series/>", "no area": '<Series FREQ="M"><Obs TIME_PERIOD="2026-01" OBS_VALUE="1"/></Series>',
                    "an empty area": '<Series FREQ="M" REF_AREA=""><Obs TIME_PERIOD="2026-01" OBS_VALUE="1"/></Series>',
                    "a text where it stands": "text", "an observation naming nothing": bis_series("{a}", "<Obs/>"),
                    "an observation of text": bis_series("{a}", '<Obs TIME_PERIOD="2026-02" OBS_VALUE="x"/>'),
                    "a series inside it": bis_series("{a}", '<Series FREQ="M" REF_AREA="CH"/>'), "twice": bis_series("{a}") * 2}
        for i, area in enumerate(self.AREAS):
            for what, variant in variants.items():
                body = [variant.replace("{a}", area) if j == i else v for j, v in enumerate(valid)]
                yield f"{what} for {area}", bis_message(body), set(self.AREAS) - {area}

    def test_every_series_that_was_not_touched_is_kept_and_nothing_is_empty_that_is_not(self):
        wrong, runs = [], 0
        for what, text, untouched in self.corruptions():
            runs += 1
            try:
                out, e = self.lane(self.REQUEST, self.URL, text)
            except Exception as error:   # (d)
                wrong.append((what, f"the router raised {type(error).__name__}"))
                continue
            try:
                parses, series = True, sum(1 for el in ET.fromstring(text).iter() if el.tag.rsplit("}", 1)[-1] == "Series")
            except ET.ParseError:
                parses, series = False, 0
            kept = [i.rsplit(".", 1)[-1] for i in e.get("retrieved") or []]
            if "error" in e and e["error"].split(":", 1)[0] not in MEMBER_ERROR_NAMES | {"bis"}:   # "bis: HTML answer ..." is the bot-wall check, as unreadable
                wrong.append((what, f"(d) {e['error']}"))
            if (e["coverage"] == "searched_empty" or e.get("count") == 0) and (series or not parses):
                wrong.append((what, f"(b) an empty answer from a message that {'holds ' + str(series) + ' series' if parses else 'does not parse'}"))
            if untouched and parses and not (set(a for a in untouched) <= set(kept)) and not text.endswith("x"):
                wrong.append((what, f"(c) {sorted(untouched - set(kept))} not kept: {e.get('retrieved')}"))
            if not parses and e["completeness"] != "unobserved":
                wrong.append((what, f"(b) a message that does not parse is {e['completeness']}"))
        self.assertGreater(runs, 50)
        self.assertEqual(wrong, [], f"{len(wrong)} of {runs}: {wrong[:4]}")

    LISTING = ('<s:Structure xmlns:s="urn:s"><s:Structures><s:Dataflows>%s</s:Dataflows></s:Structures></s:Structure>')

    def test_a_dataflow_listing_names_its_flows_or_is_unreadable(self):
        flow = lambda i, name="N": f'<s:Dataflow id="F{i}"><s:Name>{name}</s:Name></s:Dataflow>'   # noqa: E731
        request = {"request_type": "catalog", "source": "ecb"}
        url = "https://data-api.ecb.europa.eu/service/dataflow/ECB"
        for what, text, want in (("the valid listing", self.LISTING % "".join(flow(i) for i in (1, 2, 3)), ("complete", ["F1", "F2", "F3"])),
                                 ("no flows", self.LISTING % "", ("unobserved", None)),
                                 ("flows that name nothing", self.LISTING % '<s:Dataflow><s:Name>x</s:Name></s:Dataflow>' * 2, ("unobserved", None)),
                                 ("one that names nothing", self.LISTING % (flow(1) + "<s:Dataflow/>" + flow(3)), ("complete", ["F1", "F3"])),
                                 ("not XML", "x", ("unobserved", None)), ("another root", "<Foo/>", ("unobserved", None))):
            with self.subTest(what):
                out, e = self.lane(request, url, text)
                self.assertEqual((e["completeness"], e.get("retrieved")), want)


class RegistryLoaders(unittest.TestCase):
    """The registry loaders (harvest/registries.py) page through a provider's registry and stop on its end rule; they are provider-data readers
    like the lanes, and an end they cannot establish is a failed load, not a finished one. Every position of the first page of each is
    corrupted: the load either raises (a ValueError: the load failed) or reads every page the corruption does not take the next one from."""
    JOURNAL = lambda self, i: {"title": f"J{i}", "ISSN": [f"1234-567{i}"]}   # noqa: E731
    REPO = lambda self, i: {"id": f"r.{i}", "attributes": {"name": f"R{i}", "symbol": f"r.{i}"}}   # noqa: E731

    def cases(self):
        from research_gateway.harvest import registries as reg
        first_c, second_c = f"{reg.CROSSREF_JOURNALS}?rows=2&cursor=%2A", f"{reg.CROSSREF_JOURNALS}?rows=2&cursor=c2"
        first_d, second_d = (f"{reg.DATACITE_REPOSITORIES}?page%5Bsize%5D=2&page%5Bnumber%5D={n}" for n in (1, 2))
        yield ("crossref journals", {"message": {"items": [self.JOURNAL(1), self.JOURNAL(2)], "next-cursor": "c2"}}, ("message", "items"),
               [(second_c, {"message": {"items": [self.JOURNAL(3)]}})], first_c, lambda c: reg.crossref_journals(c, rows=2),
               ["issn:1234-5671", "issn:1234-5672"], ["issn:1234-5673"], 2)
        yield ("datacite repositories", {"data": [self.REPO(1), self.REPO(2)], "meta": {"totalPages": 2}}, ("data",),
               [(second_d, {"data": [self.REPO(3)], "meta": {"totalPages": 2}})], first_d, lambda c: reg.datacite_repositories(c, size=2),
               ["repository:datacite:r.1", "repository:datacite:r.2"], ["repository:datacite:r.3"], 2)

    def records(self, load, first_url, first, rest) -> list:
        t = FakeTransport()
        t.add("GET", first_url, body=encode(first))
        for url, body in rest:
            t.add("GET", url, body=body)
        c = Client(broker=Broker({"crossref": RatePolicy(per_second=1000), "datacite": RatePolicy(per_second=1000)}), transport=t, sleep=lambda s: None)
        out = []
        try:
            out = [plain(r) for r in list(load(c))]   # what a loader yields is sealed until it is written: the harness compares the plain copy
        except Exception:   # the loader's failure is judged by run_load
            pass
        return out

    def run_load(self, load, first_url, first, rest):
        t = FakeTransport()
        t.add("GET", first_url, body=encode(first))
        for url, body in rest:
            t.add("GET", url, body=body)
        c = Client(broker=Broker({"crossref": RatePolicy(per_second=1000), "datacite": RatePolicy(per_second=1000)}), transport=t, sleep=lambda s: None)
        got = []
        try:
            for rec in load(c):
                got.append(rec["identity"])
        except Exception as e:   # a failed load: a ValueError (PayloadError is one), or a continuation the fake has no page for (a 404); nothing else may escape
            return got, e
        return got, None

    def test_a_loader_that_cannot_read_where_to_go_on_fails_and_never_finishes_early(self):
        wrong, runs = [], 0
        for name, page, holder, rest, url, load, ids_here, ids_next, per_page in self.cases():
            valid = json.loads(json.dumps(page))
            baseline = {r["identity"]: r for r in self.records(load, url, valid, rest)}
            members_at = [holder + (i,) for i in range(len(get(valid, holder)))]
            for path, values in positions(Op("", "", {}, (), tuple(ids_here), levels=(Level(holder),)), valid, [Member(p, i) for p, i in zip(members_at, ids_here)]):
                for value in values:
                    runs += 1
                    got, failed = self.run_load(load, url, put(valid, path, value) if path else value, rest)
                    if failed is not None and not isinstance(failed, (ValueError, SourceUnavailable)):
                        wrong.append((name, path, show(value), f"(d) the load raised {type(failed).__name__}: {str(failed)[:80]}"))
                        continue
                    inside = len(path) > len(holder) and path[:len(holder)] == holder
                    if inside and failed is None and value is not MISSING and value is not None and kind_of(value) != kind_of(get(valid, path)):
                        for rec in self.records(load, url, put(valid, path, value), rest):   # (b) a wrong-kind value inside a kept record says nothing less
                            was = baseline.get(rec["identity"])
                            if was is None:
                                wrong.append((name, path, show(value), f"(b) a record the valid answer never had: {rec['identity']!r}"))
                            elif any(f not in VOLATILE and emptier(w, rec.get(f), value) for f, w in was.items()):
                                wrong.append((name, path, show(value), f"(b) {rec['identity']} says less than it did"))
                    items = (put(valid, path, value) if path else value)
                    held = safe_get(items, holder)
                    shorter = isinstance(held, list) and len(held) < per_page
                    if failed is None and not shorter and any(i not in got for i in ids_next):
                        wrong.append((name, path, show(value), "(a) the load finished without the next page, on a first page whose end it could not read"))
                    if inside and (failed is not None or any(i not in got for i in ids_next)):
                        wrong.append((name, path, show(value), f"(c) one member's trouble stopped the load: {failed!r} {got}"))
        self.assertGreater(runs, 100)
        self.assertEqual(wrong, [], f"{len(wrong)} of {runs}: {wrong[:3]}")


# What is not run, and why: every (source, capability) of every adapter is an Op above, or is listed here with the reason. A new adapter, or a new
# capability, that is in neither fails the coverage test below: the harness is over every adapter because nothing can join one without it.
EXCLUDED = {
    ("openalex_snapshot", "find"): "the gateway's own local index: it reads the store, never a provider's answer (its offsets and population are tested "
                                   "on a database, tests.test_adapters_platforms.OpenAlexLocalIndex)",
    ("doi_org", "resolve"): "a registration-agency lookup: it names an agency (or 'unknown'), and produces no candidate and no end",
    ("globe", "fetch"): "static files: no answer of a provider is read",
    ("wms", "fetch"): "the Dataverse client under its own source id, fixing the DOI: harvard_dataverse.fetch runs the same code",
    ("qdr", "find"): "the Dataverse client under its own source id: harvard_dataverse.find runs the same code",
    ("qdr", "resolve"): "the Dataverse client: no route reaches it (below)",
    ("harvard_dataverse", "resolve"): "no route reaches it: the router sends a DOI to the registration agency's resolver (Crossref, DataCite, '*'), never to "
                                     "Dataverse; the dataset record is tested directly (tests/test_present_means_typed.py) and its files through fetch",
    ("core", "resolve"): "no route reaches it: a DOI goes to its agency's resolver; core.enrich full_text runs the same lookup and record",
    ("semanticscholar", "enrich:full_text"): "one record read from resolve, and its link: semanticscholar.resolve is run",
}


class Coverage(unittest.TestCase):
    def test_every_capability_of_every_adapter_is_an_operation_here_or_excluded_with_a_reason(self):
        covered = {(op.sid, op.request["request_type"]) for op in ALL.values()} | {(op.sid, "enrich:" + op.request["what"]) for op in ALL.values()
                                                                                    if op.request["request_type"] == "enrich"}
        declared = set()
        for sid, mod in adapters.load_all().items():
            declared |= {(sid, cap) for cap in mod.CAPABILITIES}
            declared |= {(sid, "enrich:" + what) for what in getattr(mod, "ENRICHES", ())}
        # XML answers (BIS's series and the dataflow listings) are run by XmlAnswers; the JSON loaders by RegistryLoaders
        covered |= {("bis", "data"), ("bis", "catalog"), ("ecb", "catalog")}
        self.assertEqual(sorted(declared - covered - set(EXCLUDED)), [], "an adapter capability no operation runs: add its Op, or exclude it with the reason")
        self.assertEqual(sorted(set(EXCLUDED) - declared), [], "an exclusion for a capability that no adapter declares")
        self.assertEqual(sorted(set(EXCLUDED) & covered), [], "an exclusion for a capability that is run")
        self.assertTrue(all(len(why.split()) >= 6 for why in EXCLUDED.values()))

    def test_every_operation_states_its_answer_and_is_found_by_the_router(self):
        self.assertGreaterEqual(len(ALL), 60)
        for name, op in ALL.items():
            with self.subTest(name):
                self.assertEqual(len(corrupt_route(op).method) > 0 and sum(r.corrupt for r in op.routes), 1)
                self.assertTrue(op.ids)
                self.assertTrue(op.levels or op.single is not None or op.explicit)


def _case(name: str, invariant: str):
    def test(self):
        found, runs = corruption_report(name)
        mine = [v for v in found if v.invariant == invariant]
        self.assertGreater(runs, 20, "the operation was corrupted")
        self.assertEqual(mine, [], f"{len(mine)} of {runs} corruptions of {name} break ({invariant}); the first: {mine[:3]}")
    return test


WHY = {"a": "ends_or_continues_only_on_what_it_read",
       "b": "an_unreadable_container_is_never_empty",
       "c": "readable_peers_survive",
       "d": "nothing_escapes_unhandled"}   # tools/gen2_gateway_mutants.py names these tests


def build_tests() -> None:
    for name in ALL:
        slug = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")
        for invariant, why in WHY.items():
            setattr(Corruptions, f"test_{invariant}_{why}__{slug}", _case(name, invariant))


class Corruptions(unittest.TestCase):
    """One test per invariant per operation, so a failure names both; each reads the same single pass over the operation's corruptions."""


@unittest.skipUnless(os.environ.get("INVARIANT_REPORT"), "INVARIANT_REPORT names the file the violations are written to")
class Report(unittest.TestCase):
    def test_write_the_report(self):
        everything, runs = {}, 0
        for name in ALL:
            found, n = corruption_report(name)
            everything[name] = [v.__dict__ for v in found]
            runs += n
        with open(os.environ["INVARIANT_REPORT"], "w") as f:
            json.dump({"seed": SEED, "scale": SCALE, "runs": runs, "operations": len(ALL), "violations": everything}, f, indent=1)


build_tests()

if __name__ == "__main__":
    unittest.main()
