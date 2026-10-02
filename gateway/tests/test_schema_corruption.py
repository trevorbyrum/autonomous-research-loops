"""Task 2b-repair-12: the corruption positions are DERIVED from the declared schemas, not listed by hand.

Every 2b round since repair-7 fixed the access patterns a reviewer had found and left the next one (malformed members, falsy wrong-kind holders, lazy fallbacks,
nested alternatives, contradictory references), because the places a payload could be corrupted were enumerated by whoever wrote the test. Each operation now
declares the payload it supports (`SCHEMAS` in its adapter module, core/schema.py), so this file walks those declarations over the valid answers of
tests/invariant_ops.py (and the populated variants of tests/oracle/variants.py), and corrupts every position the schema declares that the answer holds:

  * every declared field, with a value of a kind that is wrong for it (what is wrong for a kind is stated here, by kind, not asked of the decoder), and, where the schema
    says the field is required, with the field left out or null;
  * every list element, whole (an element that is not an object, a text, ...);
  * every ALTERNATIVE the schema declares (`alts`): corrupted beside a valid other, and with the others left out ("the alternate alone").

What a corruption must cost is read from WHERE the schema puts the position, never from the adapter: a position inside a `members` element costs that member (the lane is
partial, the others stand, payload_invalid); inside an `isolated` field, that field only; inside a `soft` one, nothing a member has; anywhere else, the answer
(unobserved, payload_invalid, no count). The harness's own statements about ends, continuations and zero counts stay in tests/test_invariants.py; this file is about
reach: a declared field the pass cannot corrupt is a failure, and so is an adapter that reads a field it does not declare (UndeclaredRead is not a member's loss, so it
shows as a lane error in every one of these runs).

What it does not do: SDMX-ML. An XML attribute or element has no wrong kind (everything is text); its schemas' positions are cardinality and agreement (a flow's
references), which tests/test_flow_binding.py states for BIS and ECB. The Socrata voucher and the OpenAIRE token exchange are not the answer these operations read, and
OpenML's 412 error body is read for one code: they are listed in NOT_DERIVED with why.
"""
from __future__ import annotations

import collections
import copy
import unittest

from research_gateway import adapters
from research_gateway.core import schema as S
from tests import invariant_ops as ops
from tests.invariant_ops import corrupt_route
from research_gateway.adapters.base import MEMBER_ERRORS
from tests.test_invariants import ALL, MISSING, Member, get, members_of, put, run

# What is wrong for a kind of field: values of other kinds, the falsy ones a truthiness test mistakes for "nothing" first.
TEXTLIKE = (False, True, 0, 1.5, [], {}, ["x"], {"a": 1})
WRONG = {
    "text": TEXTLIKE,
    "key": (False, True, 1.5, [], {}, ["x"], {"a": 1}),
    "maybe_key": (False, True, 1.5, [], {}, ["x"]),
    "flag": (0, "", [], {}, "no", 1, [True]),
    "whole": (False, True, 1.5, "7", [], {}),
    "year": (False, True, [], {}, "x", "20x1", 1.5),
    "token": (False, True, 0, 1.5, [], {}, ""),
    "obj": (False, True, 0, 1.5, "", "x", [], [1]),
    "list": (False, True, 0, 1.5, "", "x", {}),
    "keyed": (False, True, 0, 1.5, "", "x", []),
}
LISTS = ("own", "members", "lookup")
KEYED = ("entries", "table")


def wrong_for(spec: S.Spec) -> tuple:
    """Values that are wrong for every way `spec` can be read."""
    k = spec.kind
    if k in ("soft", "isolated", "maybe"):
        return wrong_for(spec.of)
    if k == "oneof":
        sets = [wrong_for(alternative) for alternative in spec.of]
        return tuple(v for v in sets[0] if all(any(type(v) is type(w) and v == w for w in other) for other in sets[1:]))
    if k in LISTS:
        return WRONG["list"] if not spec.bare else tuple(v for v in WRONG["list"] if v != {})
    if k in KEYED:
        return WRONG["keyed"]
    if k == "any":
        return ()
    return WRONG[k]


class Position:
    """A declared position: where it is in the answer (`path`; the answer holds it or `present` is False), in the schema, and which failure boundary of the decoder
    is the nearest around it."""
    __slots__ = ("path", "schema_path", "spec", "boundary", "required", "present")

    def __init__(self, path, schema_path, spec, boundary, required=False, present=True):
        self.path, self.schema_path, self.spec, self.boundary, self.required, self.present = path, schema_path, spec, boundary, required, present

    def __repr__(self):
        return f"<{'.'.join(map(str, self.path)) or 'the answer'} {self.spec.kind} {self.boundary[0]}{'' if self.present else ' (not in the valid answer)'}>"


def dig(value, path):
    for step in path:
        if not isinstance(value, dict) or step not in value:
            return MISSING
        value = value[step]
    return value


def walk(spec: S.Spec, value, path: tuple, schema_path: tuple, boundary: tuple, required: bool = False):
    """Every position the schema declares, outermost first: those the answer `value` holds, and those it does not (a declared field the valid answer leaves out is
    still declared: it is corrupted by putting a wrong value where it would stand). `boundary`: the decoder's nearest failure boundary — ("answer",),
    ("member", element path), ("isolated", path) or ("soft", path)."""
    k = spec.kind
    here = value is not MISSING
    if k in ("soft", "isolated"):
        yield from walk(spec.of, value, path, schema_path, (k, path), required)
        return
    if k == "maybe":
        yield from walk(spec.of, value, path, schema_path, boundary, required)
        return
    if k == "any":
        return
    yield Position(path, schema_path, spec, boundary, required or spec.required, here)
    if k == "obj" and (isinstance(value, dict) or not here):
        for name, fs in spec.of.items():
            held = value if here else {}
            if fs.kind == "deep":
                found = dig(held, fs.of[0])
                yield from walk(S.soft(fs.of[1]), found if found is not None else MISSING, path + fs.of[0], schema_path + (name,), boundary)
                continue
            if fs.kind == "matching":
                prefixes, leaf = fs.of
                for key in held:
                    if isinstance(key, str) and key.startswith(prefixes):
                        yield from walk(S.soft(leaf), held[key], path + (key,), schema_path + (name,), boundary)
                continue
            if fs.kind == "by":
                tag, variants, other = fs.of
                fs = variants.get(held.get(tag), other) if isinstance(held.get(tag), str) else other
            child = held.get(name, MISSING)
            yield from walk(fs, MISSING if child is None else child, path + (name,), schema_path + (name,), boundary)
        return
    if k in LISTS and (isinstance(value, list) or not here):
        elements = (value[:1] if k == "lookup" else value) if here else [MISSING]
        for i, element in enumerate(elements):
            inner = ("member", path + (i,)) if k == "members" else boundary
            yield from walk(spec.of, element, path + (i,), schema_path + ("[]",), inner)
        return
    if k in KEYED and (isinstance(value, dict) or not here):
        for key, element in (value.items() if here else [("key", MISSING)]):
            inner = ("member", path + (key,)) if k == "entries" else boundary
            yield from walk(spec.of, element, path + (key,), schema_path + ("[]",), inner)


def grow(body, path: tuple, value):
    """A copy of `body` with `value` at `path`, the containers on the way created where the answer leaves them out (an object for a name, a list for a position)."""
    out = copy.deepcopy(body)
    if not path:
        return value
    cur = out
    for i, step in enumerate(path[:-1]):
        following = path[i + 1]
        if isinstance(cur, dict):
            if cur.get(step) is None:
                cur[step] = [] if isinstance(following, int) else {}
            cur = cur[step]
        else:
            while len(cur) <= step:
                cur.append([] if isinstance(following, int) else {})
            cur = cur[step]
    last = path[-1]
    if isinstance(cur, dict):
        if value is MISSING:
            cur.pop(last, None)
        else:
            cur[last] = value
    else:
        while len(cur) <= last:
            cur.append({})
        cur[last] = value
    return out


# which schema an operation's answer is decoded with: (the adapter, the key in its SCHEMAS). An operation not listed here is a failure.
BINDINGS = {
    "crossref.find": ("crossref", "find"), "crossref.resolve": ("crossref", "resolve"), "crossref.enrich references": ("crossref", "enrich:references"),
    "openml.find": ("openml", "find"), "openml.resolve": ("openml", "resolve"),
    "datacite.find": ("datacite", "find"), "datacite.resolve": ("datacite", "resolve"),
    "doaj.find": ("doaj", "find"), "doaj.resolve (a journal by its ISSN)": ("doaj", "resolve:journal"),
    "europepmc.find": ("europepmc", "find"), "europepmc.resolve": ("europepmc", "resolve"),
    "govinfo.find": ("govinfo", "find"), "govinfo.resolve": ("govinfo", "resolve"), "govinfo.fetch (a package's formats)": ("govinfo", "fetch"),
    "harvard_dataverse.find": ("harvard_dataverse", "find"), "harvard_dataverse.fetch (a dataset's files)": ("harvard_dataverse", "fetch"),
    "huggingface.find": ("huggingface", "find"), "huggingface.resolve": ("huggingface", "resolve"), "huggingface.fetch (a dataset's files)": ("huggingface", "fetch"),
    "kaggle.find": ("kaggle", "find"), "kaggle.fetch (a dataset's files)": ("kaggle", "fetch"),
    "openaire.find": ("openaire", "find"), "openaire.resolve": ("openaire", "resolve"),
    "openml.fetch (a dataset's file links)": ("openml", "fetch"),
    "semanticscholar.find": ("semanticscholar", "find"), "semanticscholar.resolve": ("semanticscholar", "resolve"),
    "semanticscholar.enrich citations": ("semanticscholar", "enrich:citations"), "semanticscholar.enrich references": ("semanticscholar", "enrich:references"),
    "socrata.find": ("socrata", "find"), "socrata.resolve": ("socrata", "resolve"), "socrata.fetch (the rows)": ("socrata", "fetch"),
    "opencitations.enrich citations": ("opencitations", "enrich:citations"), "opencitations.enrich references": ("opencitations", "enrich:references"),
    "opencitations.enrich metadata": ("opencitations", "enrich:metadata"),
    "unpaywall.enrich oa_location": ("unpaywall", "SCHEMA"), "core.enrich full_text": ("core", "enrich:full_text"),
    "bls.data": ("bls", "data"), "bls.catalog (the surveys)": ("bls", "catalog:surveys"), "bls.catalog (a survey's popular series)": ("bls", "catalog:popular"),
    "ecb.data": ("ecb", "data"),
    "fred.data (the observations)": ("fred", "data:observations"), "fred.data (the series metadata)": ("fred", "data:series"),
    "fred.catalog (a search)": ("fred", "catalog"), "fred.catalog (one series)": ("fred", "catalog"),
    "bea.data (GetData)": ("bea", "data:getdata"), "bea.data (GETDATASETLIST)": ("bea", "data:list"), "bea.catalog (the datasets)": ("bea", "catalog:datasets"),
    "bea.catalog (a dataset's parameters)": ("bea", "catalog:parameters"), "bea.catalog (a parameter's values)": ("bea", "catalog:values"),
    "census.data": ("census", "data"), "census.catalog (the datasets)": ("census", "catalog:datasets"), "census.catalog (a dataset's variables)": ("census", "catalog:variables"),
}
_XML = ("SDMX-ML has no wrong kind (every attribute and element is text): its positions are cardinality and agreement, stated for BIS and ECB by "
        "tests/test_flow_binding.py and tests/test_adapters_statistical.py")
NOT_DERIVED = {
    **{(sid, f"catalog:{part}"): _XML for sid in ("bis", "ecb") for part in ("flows", "flow", "structures")},
    ("bis", "data"): _XML,
    ("socrata", "vouch"): "the portal voucher is a security check that fails closed (a member that cannot be read vouches for nothing: AdapterError, not payload_invalid), "
                          "tested by tests/test_adapters_datasets.py and tests/test_station_contract.py",
    ("openaire", "token"): "the token exchange is not the answer an operation reads; its failures are the lane's missing credentials (tests/test_exhaustion.py)",
    ("openml", "ERROR"): "the 412 error body is read for one code on one route (tests/test_adapters_datasets.py)",
}


def binding_of(name: str) -> tuple[str, str] | None:
    """The (adapter, schema) an operation is bound to: the longest bound name it starts with (a populated variant is named after its base operation)."""
    matches = [bound for bound in BINDINGS if name.startswith(bound)]
    return BINDINGS[max(matches, key=len)] if matches else None


# Operations the router cannot reach (a DOI goes to its registration agency's resolver, never to Dataverse or DOAJ), run by calling the adapter: (adapter, schema key,
# a valid answer, the URL it is answered at, what is asked). An answer that does not decode is a PayloadError; one that does is a record.
DIRECT = {
    "harvard_dataverse.resolve": ("harvard_dataverse", "resolve",
                                  {"data": {**ops.DV_DATASET["data"], "latestVersion": {**ops.DV_DATASET["data"]["latestVersion"], "metadataBlocks": {"citation": {"fields": [
                                      {"typeName": "title", "value": "T"}, {"typeName": "author", "value": [{"authorName": {"value": "A, B"}}]}, {"typeName": "other", "value": 5}]}}}}},
                                  "https://dataverse.harvard.edu/api/datasets/:persistentId/", "doi:10.7910/DVN/X1"),
    "doaj.resolve (an article by its DOI)": ("doaj", "resolve:article", {"results": [ops.doaj_article(1), ops.doaj_article(2)]},
                                             "https://doaj.org/api/search/articles/", "doi:10.1000/j1"),
}


def schema_of(name: str):
    sid, key = binding_of(name)
    module = adapters.load_all()[sid]
    return sid, key, (module.SCHEMAS.get(key) if key != "SCHEMA" else module.SCHEMA)


def schemas_of(module) -> dict:
    out = dict(getattr(module, "SCHEMAS", {}))
    out.pop("SCHEMA", None)
    return out


def fixtures():
    """(operation name, operation, valid body) for every operation the invariant harness holds."""
    for name, op in ALL.items():
        yield name, op, copy.deepcopy(corrupt_route(op).body)


class SchemasAreDeclaredAndBound(unittest.TestCase):
    def test_every_operation_of_the_harness_reads_through_a_declared_schema(self):
        unbound = sorted(name for name in ALL if binding_of(name) is None)
        self.assertEqual(unbound, [], "an operation the harness runs, with no schema bound to it here")
        for name in ALL:
            with self.subTest(name):
                sid, key, spec = schema_of(name)
                self.assertIsInstance(spec, S.Spec, f"{sid}.SCHEMAS has no {key!r}")

    def test_every_schema_an_adapter_declares_is_bound_to_an_operation_or_listed_with_its_reason(self):
        bound = {(sid, key) for sid, key in BINDINGS.values()} | {(sid, key) for sid, key, *_ in DIRECT.values()}
        for sid, module in adapters.load_all().items():
            for key, spec in schemas_of(module).items():
                with self.subTest(sid=sid, key=key):
                    same = any(schema_of_key(b_sid, b_key) == spec for b_sid, b_key in bound if b_sid == sid)   # an operation that reads the same schema under another name
                    self.assertTrue((sid, key) in bound or same or (sid, key) in NOT_DERIVED, f"{sid}.SCHEMAS[{key!r}] is exercised by no operation here and is not listed in NOT_DERIVED")
        for (sid, key), why in NOT_DERIVED.items():
            self.assertGreater(len(why.split()), 5)


def schema_of_key(sid: str, key: str):
    module = adapters.load_all()[sid]
    return module.SCHEMA if key == "SCHEMA" else module.SCHEMAS[key]


def operation_members(op, body):
    mem, _, _ = members_of(op, body)
    return mem


def lost_by(op, mem: list[Member], pos: Position, body) -> tuple[str, list]:
    """What corrupting `pos` must cost, from its place in the schema: ("kept", []) — nothing a member has; ("answer", []) — the answer; ("lost", [members]) — those
    members; ("some", []) — a member that no operation member contains or is contained in (a lookup table another member points into): any of them, and the lane says
    exactly what it lost."""
    kind, where = pos.boundary[0], pos.boundary[1] if len(pos.boundary) > 1 else ()
    if kind == "soft":
        return "kept", []
    if kind == "isolated":
        explicit = [m for m in mem if m.path == where]
        return ("lost", explicit) if explicit else ("partial", [])
    if kind == "answer":
        return "answer", []
    inside = [m for m in mem if m.path[:len(where)] == where]
    if inside:
        return "lost", inside
    around = [m for m in mem if where[:len(m.path)] == m.path]
    if around:
        return "lost", around   # the failing element is a part of an operation member
    return "some", []


class Corruptions(unittest.TestCase):
    def check(self, name, op, body, mem, pos: Position, value, removed=()):
        """Corrupt `pos` of `body` with `value` (and leave out the positions in `removed`), run the real adapter and router, and hold the lane to the schema's statement."""
        corrupted = body
        for p, empty in removed:
            corrupted = grow(corrupted, p, empty)
        corrupted = grow(corrupted, pos.path, value)
        out, lane = run(op, corrupted)
        ids = collections.Counter(op.ids)
        label = f"{name}: {pos!r} <- {value!r}" + (f" (alternatives left out: {[p for p, _ in removed]})" if removed else "")
        self.assertNotIn("UndeclaredRead", lane.get("error", ""), label)
        retrieved = collections.Counter(lane.get("retrieved") or [])
        what, lost = lost_by(op, mem, pos, body)
        if removed:   # the alternatives left out change what the answer holds, so which members remain is not the valid answer's: what must hold is that the loss of the
                      # corrupted one is never read as a complete answer, that it is not among the members kept, and that nothing is kept that the valid answer did not hold
            gone = collections.Counter(m.ident for m in lost)
            self.assertFalse(retrieved - ids, label)
            self.assertFalse(retrieved & gone and any(retrieved[i] > ids[i] - gone[i] for i in gone), label)
            if what == "answer":
                self.assertEqual((lane["completeness"], lane.get("error_class")), ("unobserved", "payload_invalid"), label)
            elif what in ("lost", "partial"):
                self.assertIn(lane["completeness"], ("partial", "unobserved"), label)
                self.assertIn(lane.get("error_class"), ("payload_invalid", "partial_pagination"), label)
            return
        if what == "answer" or (what == "lost" and not (ids - collections.Counter(m.ident for m in lost))):
            self.assertEqual((lane["coverage"], lane["completeness"], lane.get("error_class"), "count" in lane), ("provider_unavailable", "unobserved", "payload_invalid", False), label)
        elif what == "lost":
            gone = collections.Counter(m.ident for m in lost)
            self.assertEqual((lane["completeness"], lane.get("error_class")), ("partial", "payload_invalid"), label)
            self.assertEqual(retrieved, ids - gone, label)
        elif what == "partial":   # a field whose loss the adapter accounts for: a side value (payload_invalid), or a continuation that cannot be read (partial_pagination)
            self.assertEqual((lane["completeness"], retrieved), ("partial", ids), label)
            self.assertIn(lane.get("error_class"), ("payload_invalid", "partial_pagination"), label)
        elif what == "kept":
            self.assertNotEqual(lane["completeness"], "unobserved", label)
            self.assertEqual(retrieved, ids, label)
            self.assertNotEqual(lane.get("error_class"), "payload_invalid", label)
        else:   # "some"
            self.assertFalse(retrieved - ids, label)
            if retrieved == ids:
                self.assertEqual(lane["completeness"], "complete", label)
            else:
                self.assertIn(lane.get("error_class"), ("payload_invalid",), label)

    def positions(self, name, op, body):
        sid, key, spec = schema_of(name)
        return list(walk(spec, body, (), (), ("answer",)))

    def test_every_declared_position_every_wrong_kind(self):
        runs = 0
        for name, op, body in fixtures():
            mem = operation_members(op, body)
            for pos in self.positions(name, op, body):
                if pos.path == () and op.single is None and not op.levels:
                    continue
                values = list(wrong_for(pos.spec))
                if pos.required and pos.path:
                    values += [MISSING, None]
                for value in values:
                    if value is MISSING and (not pos.path or isinstance(pos.path[-1], int)):
                        continue
                    if value is None and pos.path and isinstance(pos.path[-1], int):
                        continue
                    if not pos.present and (value is MISSING or value is None):   # a field the valid answer leaves out is already left out
                        continue
                    runs += 1
                    with self.subTest(op=name, position=repr(pos), value=repr(value)):
                        self.check(name, op, body, mem, pos, value)
        self.assertGreater(runs, 1000, "the derivation reached very little")

    def test_every_alternative_beside_a_valid_other_and_alone(self):
        runs = 0
        for name, op, body in fixtures():
            mem = operation_members(op, body)
            sid, key, spec = schema_of(name)
            for owner_path, owner_schema, group in alternative_groups(spec, body):
                present = [p for p in group if dig_value(body, owner_path + tuple(p)) is not MISSING]
                for f in present:
                    others = [(owner_path + tuple(p), left_out(spec_at(owner_schema, p))) for p in present if p != f]   # left out, or empty where the schema requires it
                    spec_f = spec_at(owner_schema, f)
                    if spec_f is None:
                        continue
                    pos = Position(owner_path + tuple(f), (), spec_f, boundary_at(spec, body, owner_path + tuple(f)))
                    for value in wrong_for(spec_f):
                        runs += 1
                        with self.subTest(op=name, alternative=".".join(f), alone=bool(others), value=repr(value)):
                            self.check(name, op, body, mem, pos, value, removed=others)
        self.assertGreater(runs, 100, "no alternative reached")


def dig_value(body, path):
    for step in path:
        if isinstance(body, dict) and step in body:
            body = body[step]
        elif isinstance(body, list) and isinstance(step, int) and step < len(body):
            body = body[step]
        else:
            return MISSING
    return body


def alternative_groups(spec: S.Spec, value, path: tuple = ()):
    """(path of the object, its schema, group as tuples of keys) for every `alts` group of every object of the schema that `value` holds."""
    k = spec.kind
    if k in ("soft", "isolated", "maybe"):
        yield from alternative_groups(spec.of, value, path)
    elif k == "obj" and isinstance(value, dict):
        for group in spec.alts:
            yield path, spec, [tuple(name.split(".")) for name in group]
        for name, fs in spec.of.items():
            if fs.kind in ("deep", "matching", "by", "any") or name not in value:
                continue
            yield from alternative_groups(fs, value[name], path + (name,))
    elif k in LISTS and isinstance(value, list):
        for i, element in enumerate(value[:1] if k == "lookup" else value):
            yield from alternative_groups(spec.of, element, path + (i,))
    elif k in KEYED and isinstance(value, dict):
        for key, element in value.items():
            yield from alternative_groups(spec.of, element, path + (key,))


def left_out(spec: S.Spec):
    """What leaving an alternative out is: the field gone — or, where the schema requires it, its empty value (nothing listed)."""
    while spec is not None and spec.kind in ("soft", "isolated", "maybe"):
        spec = spec.of
    if spec is None or not spec.required:
        return MISSING
    return [] if spec.kind in LISTS + ("entries",) else {} if spec.kind in ("obj", "table") else MISSING


def spec_at(owner: S.Spec, route: tuple) -> S.Spec | None:
    current = owner
    for step in route:
        while current.kind in ("soft", "isolated", "maybe"):
            current = current.of
        if current.kind != "obj" or step not in current.of:
            return None
        current = current.of[step]
    return current


def boundary_at(spec: S.Spec, body, target: tuple) -> tuple:
    """The nearest failure boundary around the position at `target`."""
    for pos in walk(spec, body, (), (), ("answer",)):
        if pos.path == target:
            return pos.boundary
    return ("answer",)


class DirectResolves(unittest.TestCase):
    """The same derivation for the operations no route reaches: every declared position, every wrong kind; what it costs is read from the place in the schema."""

    def ask(self, sid, key, url, identity, body):
        from research_gateway.adapters.base import Client, FakeTransport, PayloadError
        from research_gateway.core.broker import Broker, RatePolicy
        t = FakeTransport()
        t.add("GET", url, 200, __import__("json").dumps(body).encode())
        c = Client(broker=Broker({sid: RatePolicy(per_second=100000)}), transport=t, secrets=lambda n, f=None: "k", sleep=lambda s: None)
        try:
            return "record", adapters.load_all()[sid].resolve(c, identity)
        except PayloadError as e:
            return "unreadable", e

    def test_every_declared_position_every_wrong_kind(self):
        runs = 0
        for name, (sid, key, body, url, identity) in DIRECT.items():
            self.assertEqual(self.ask(sid, key, url, identity, body)[0], "record", f"{name}: the valid answer reads")
            spec = schema_of_key(sid, key)
            for pos in walk(spec, body, (), (), ("answer",)):
                if not pos.path:
                    continue
                values = list(wrong_for(pos.spec)) + ([MISSING, None] if pos.required else [])
                for value in values:
                    if (value is MISSING or value is None) and isinstance(pos.path[-1], int):
                        continue
                    runs += 1
                    if not pos.present and (value is MISSING or value is None):
                        continue
                    corrupted = grow(body, pos.path, value)
                    verdict, got = self.ask(sid, key, url, identity, corrupted)
                    kind = pos.boundary[0]
                    first_member = kind == "member" and pos.boundary[1][:1] == ("results",) and pos.boundary[1][1:2] == (0,)   # a lookup reads only its first result
                    want = "unreadable" if kind == "answer" or first_member else "record"
                    if kind == "member" and not first_member and pos.boundary[1][:1] == ("results",):
                        want = "record"
                    with self.subTest(op=name, position=repr(pos), value=repr(value)):
                        self.assertEqual(verdict, want, got)
        self.assertGreater(runs, 100)


class UndeclaredReads(unittest.TestCase):
    def test_a_field_an_adapter_reads_and_its_schema_does_not_declare_is_a_failure_and_not_a_lost_member(self):
        """The mutation the whole derivation depends on: read an undeclared field in a member builder, and every run of the operation shows it."""
        from research_gateway.adapters import crossref
        original = crossref._record

        def reading_more(client, w):
            w["undeclared"]
            return original(client, w)
        crossref._record = reading_more
        try:
            out, lane = run(ops.CROSSREF_FIND_END, copy.deepcopy(corrupt_route(ops.CROSSREF_FIND_END).body))
        finally:
            crossref._record = original
        self.assertNotEqual(lane.get("completeness"), "complete", lane)
        self.assertIn("UndeclaredRead", lane.get("error", ""), "the lane names the adapter's mistake")
        self.assertNotIn("UndeclaredRead", {e.__name__ for e in MEMBER_ERRORS}, "and no member is dropped to hide it")


if __name__ == "__main__":
    unittest.main()
