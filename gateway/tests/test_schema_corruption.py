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

REACH (2b-repair-13a, R12-5). A `oneof` is a value that may be any of several kinds, and the kinds that hold fields (an object that names a licence, a list of creators) have positions of
their own that the fixture's value may not hold: it holds one branch, or none. The walk goes into every such branch — the one the fixture holds as it is, the others with a valid sample
of the branch put in the union's place (`sample`) — so a position under a union is corrupted like any other. What it reached is checked against an INVENTORY of the declared paths that is
written separately (`declared_paths`: a traversal of the schema as data, which knows nothing of values or of the decoder), and a declared path the pass did not reach is a failure,
whatever the run counts say. The loaders' CSV (DOAJ) and the doi.org lookup are derived the same way (LoaderCorruptions, LookupCorruptions).

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
from tests.oracle import loaders as loaders_oracle
from tests.invariant_ops import corrupt_route
from research_gateway.adapters.base import MEMBER_ERRORS, PayloadError
from tests.test_invariants import ALL, MISSING, Member, get, members_of, put, run

# What is wrong for a kind of field: values of other kinds, the falsy ones a truthiness test mistakes for "nothing" first.
TEXTLIKE = (False, True, 0, 1.5, [], {}, ["x"], {"a": 1})
WRONG = {
    "text": TEXTLIKE,
    "key": (False, True, 1.5, [], {}, ["x"], {"a": 1}),
    "maybe_key": (False, True, 1.5, [], {}, ["x"]),
    "flag": (0, "", [], {}, "no", 1, [True]),
    "whole": (False, True, 1.5, "7", [], {}),
    "number": (False, True, "7", [], {}, [1]),
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
    if k in LISTS or k == "grid":
        return WRONG["list"] if not spec.bare else tuple(v for v in WRONG["list"] if v != {})
    if k in KEYED:
        return WRONG["keyed"]
    if k == "any":
        return ()
    return WRONG[k]


class Position:
    """A declared position: where it is in the answer (`path`; the answer holds it or `present` is False), in the schema, and which failure boundary of the decoder
    is the nearest around it. `pre`: the valid values to put in the answer first, (path, value), when the position is under a union branch the answer does not hold."""
    __slots__ = ("path", "schema_path", "spec", "boundary", "required", "present", "pre")

    def __init__(self, path, schema_path, spec, boundary, required=False, present=True, pre=()):
        self.path, self.schema_path, self.spec, self.boundary, self.required, self.present, self.pre = path, schema_path, spec, boundary, required, present, pre

    def __repr__(self):
        return f"<{'.'.join(map(str, self.path)) or 'the answer'} {self.spec.kind} {self.boundary[0]}{'' if self.present else ' (not in the valid answer)'}>"


def dig(value, path):
    for step in path:
        if not isinstance(value, dict) or step not in value:
            return MISSING
        value = value[step]
    return value


WRAPPERS = ("soft", "isolated", "maybe")


def fits(spec: S.Spec, value) -> bool:
    """Whether a value the answer holds is of the kind `spec` names, judged by its Python type alone: which branch of a union a value belongs to is decided here, from what it is,
    never by asking the decoder to read it."""
    k = spec.kind
    if k in WRAPPERS:
        return fits(spec.of, value)
    if k in LISTS or k == "grid":
        return isinstance(value, list)
    if k in ("obj",) + KEYED:
        return isinstance(value, dict)
    if k in ("text", "token"):
        return isinstance(value, str)
    if k == "flag":
        return isinstance(value, bool)
    if k in ("whole", "key", "maybe_key", "year", "number"):
        return isinstance(value, (int, float, str)) and not isinstance(value, bool)
    if k == "oneof":
        return any(fits(a, value) for a in spec.of)
    return True


def has_children(spec: S.Spec) -> bool:
    """Whether a kind holds fields or elements of its own (a union branch with none has no position below it)."""
    k = spec.kind
    if k in WRAPPERS:
        return has_children(spec.of)
    if k == "oneof":
        return any(has_children(a) for a in spec.of)
    return k in ("obj", "grid") + LISTS + KEYED


def sample(spec: S.Spec):
    """A VALID value of the kind: the smallest the schema accepts (an object holds the fields it requires), put in a union's place to reach the positions below a branch the
    valid answer does not hold."""
    k = spec.kind
    if k in WRAPPERS:
        return sample(spec.of)
    if k == "obj":
        return {name: sample(fs) for name, fs in spec.of.items() if fs.required and fs.kind not in ("deep", "matching", "by")}
    if k == "grid":
        return [["x"]]
    if k in LISTS:
        return []
    if k in KEYED:
        return {}
    if k == "oneof":
        return sample(spec.of[0])
    return {"text": "x", "token": "t", "key": "k", "maybe_key": "k", "whole": 1, "number": 1, "year": 2021, "flag": True}.get(k, "x")


def walk(spec: S.Spec, value, path: tuple, schema_path: tuple, boundary: tuple, required: bool = False, pre: tuple = (), skip_root: bool = False):
    """Every position the schema declares, outermost first: those the answer `value` holds, and those it does not (a declared field the valid answer leaves out is
    still declared: it is corrupted by putting a wrong value where it would stand). `boundary`: the decoder's nearest failure boundary — ("answer",),
    ("member", element path), ("isolated", path) or ("soft", path). Under a `oneof`, every branch that holds fields is walked: the one the answer holds as it is, each other with a
    valid `sample` put in the union's place first (`pre`; schema path `|i` names the branch)."""
    k = spec.kind
    here = value is not MISSING
    if k in ("soft", "isolated"):
        yield from walk(spec.of, value, path, schema_path, (k, path), required, pre, skip_root)
        return
    if k == "maybe":
        yield from walk(spec.of, value, path, schema_path, boundary, required, pre, skip_root)
        return
    if k == "any":
        return
    if not skip_root:
        yield Position(path, schema_path, spec, boundary, required or spec.required, here, pre)
    if k == "oneof":
        held = next((i for i, a in enumerate(spec.of) if here and fits(a, value)), None)
        for i, alternative in enumerate(spec.of):
            if has_children(alternative):
                branch, before = (value, pre) if i == held else (sample(alternative), pre + ((path, sample(alternative)),))
                yield from walk(alternative, branch, path, schema_path + (f"|{i}",), boundary, required, before, skip_root=True)
        return
    if k == "obj" and (isinstance(value, dict) or not here):
        for name, fs in spec.of.items():
            held = value if here else {}
            if fs.kind == "deep":
                found = dig(held, fs.of[0])
                yield from walk(S.soft(fs.of[1]), found if found is not None else MISSING, path + fs.of[0], schema_path + (name,), boundary, pre=pre)
                continue
            if fs.kind == "matching":
                prefixes, leaf = fs.of
                keys = [key for key in held if isinstance(key, str) and key.startswith(prefixes)]
                for key in keys or [prefixes[0] + "Sample"]:   # a name the provider makes up: one the answer does not hold is put in
                    stand = pre + (() if key in held else ((path + (key,), sample(leaf)),))
                    yield from walk(leaf, held.get(key, MISSING), path + (key,), schema_path + (name,), boundary, pre=stand)
                continue
            if fs.kind == "by":   # the kind of the field is its sibling's to say: every variant is walked, the held one as it is, each other with its tag and a valid sample put in
                tag, variants, other = fs.of
                chosen = held.get(tag) if isinstance(held.get(tag), str) and held.get(tag) in variants else None
                child = held.get(name, MISSING)
                for key, variant in variants.items():
                    if key == chosen:
                        yield from walk(variant, MISSING if child is None else child, path + (name,), schema_path + (name, f"={key}"), boundary, pre=pre)
                    else:
                        stand = pre + ((path + (tag,), key), (path + (name,), sample(variant)))
                        yield from walk(variant, sample(variant), path + (name,), schema_path + (name, f"={key}"), boundary, pre=stand)
                continue
            child = held.get(name, MISSING)
            yield from walk(fs, MISSING if child is None else child, path + (name,), schema_path + (name,), boundary, pre=pre)
        return
    if k == "grid":
        header, cell = spec.of
        for i, row in enumerate(value if isinstance(value, list) else []):
            yield from walk(S.own(S.required(header) if i == 0 else cell), row, path + (i,), schema_path + ("[]",), boundary, pre=pre)
        return
    if k in LISTS and (isinstance(value, list) or not here):
        elements = ((value[:1] if k == "lookup" else value) if here else []) or [MISSING]   # a list the answer leaves empty still has an element declared
        for i, element in enumerate(elements):
            inner = ("member", path + (i,)) if k == "members" else boundary
            yield from walk(spec.of, element, path + (i,), schema_path + ("[]",), inner, pre=pre)
        return
    if k in KEYED and (isinstance(value, dict) or not here):
        for key, element in (list(value.items()) if here else []) or [("key", MISSING)]:
            inner = ("member", path + (key,)) if k == "entries" else boundary
            yield from walk(spec.of, element, path + (key,), schema_path + ("[]",), inner, pre=pre)


def prepared(body, pos: "Position"):
    """The answer with the valid values a position under an unheld union branch or `by` variant needs put in first (`Position.pre`)."""
    for path, valid in pos.pre:
        body = grow(body, path, valid)
    return body


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


def declared_paths(spec: S.Spec) -> set:
    """Every path a schema declares, read off the schema as DATA ALONE: no answer, no decoder, nothing of what a value must be. A path is the field names down from the root, with `[]` for
    the elements of a container, `|i` for the i-th branch of a union (only what is below the branch: a branch is not a position of its own) and `=key` for a variant that a sibling
    selects. Metadata (`any_()`) has no position: there is nothing in it to corrupt. This is written apart from `walk` on purpose: the walk is driven by an answer and by the kinds, this
    by the declarations only, and a path the one finds and the other does not is a reach the pass did not have."""
    found: set = set()

    def visit(s: S.Spec, path: tuple, root: bool = True) -> None:
        if s.kind == "any":
            return
        if s.kind in ("soft", "isolated", "maybe"):
            return visit(s.of, path, root)
        if root:
            found.add(path)
        if s.kind == "obj":
            for name, field in s.of.items():
                if field.kind == "by":
                    for key, variant in field.of[1].items():
                        visit(variant, path + (name, f"={key}"))
                elif field.kind == "deep":
                    visit(S.soft(field.of[1]), path + (name,))
                elif field.kind == "matching":
                    visit(field.of[1], path + (name,))
                else:
                    visit(field, path + (name,))
        elif s.kind == "oneof":
            for i, branch in enumerate(s.of):
                visit(branch, path + (f"|{i}",), root=False)
        elif s.kind == "grid":
            visit(S.own(s.of[0]), path + ("[]",))
            visit(S.own(s.of[1]), path + ("[]",))
        elif s.kind in LISTS + KEYED:
            visit(s.of, path + ("[]",))
    visit(spec, ())
    return found


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
        for p, valid in pos.pre:   # the valid branch of a union the answer does not hold, put in its place: only the corruption below it is wrong
            corrupted = grow(corrupted, p, valid)
        for p, empty in removed:
            corrupted = grow(corrupted, p, empty)
        corrupted = grow(corrupted, pos.path, value)
        out, lane = run(op, corrupted)
        ids = collections.Counter(op.ids)
        label = f"{name}: {pos!r} <- {value!r}" + (f" (alternatives left out: {[p for p, _ in removed]})" if removed else "") + (f" (under union branch {pos.schema_path[-1]})" if pos.pre else "")
        self.assertNotIn("UndeclaredRead", lane.get("error", ""), label)   # nor PassiveRead, SealedRead: they name themselves in the lane's error text
        self.assertNotIn("PassiveRead", lane.get("error", ""), label)
        self.assertNotIn("SealedRead", lane.get("error", ""), label)
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
                elif pos.spec.never_null and pos.path:   # the field may be left out, but the operation's contract does not let it be null
                    values += [None]
                for value in values:
                    if value is MISSING and (not pos.path or isinstance(pos.path[-1], int)):
                        continue
                    if value is None and pos.path and isinstance(pos.path[-1], int) and not pos.required:   # a list's element can be null: a column name cannot
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


class ReachMatchesTheDeclarations(unittest.TestCase):
    """R12-5: what the pass reached is checked against the schema's own declarations, not against its own count of runs."""

    def test_every_declared_path_of_every_operations_schema_is_a_position_the_pass_corrupts(self):
        checked = 0
        for name, op, body in fixtures():
            sid, key, spec = schema_of(name)
            reached = {p.schema_path for p in walk(spec, body, (), (), ("answer",))}
            declared = declared_paths(spec)
            with self.subTest(op=name):
                self.assertEqual((sorted(declared - reached), sorted(reached - declared)), ([], []), "declared and not reached / reached and not declared")
            checked += len(declared)
        self.assertGreater(checked, 1000)

    def test_the_union_branches_that_hold_fields_are_in_the_inventory_and_were_reached(self):
        """The pass of 2b-repair-12 met 50 union positions and generated nothing under any of them (Astra): these are the ones with fields below, by name."""
        wanted = {("doaj", ("results", "[]", "bibjson", "publisher", "|0", "name")), ("doaj", ("results", "[]", "bibjson", "ref", "[]", "|0", "url")),
                  ("harvard_dataverse", ("data", "latestVersion", "license", "|0", "name")), ("socrata", ("license", "|0", "name")),
                  ("huggingface", ("cardData", "license", "|1", "[]")), ("openml", ("data_set_description", "creator", "|1", "[]"))}
        reached = set()
        for name, op, body in fixtures():
            sid, key, spec = schema_of(name)
            reached |= {(sid, p.schema_path) for p in walk(spec, body, (), (), ("answer",)) if any(isinstance(x, str) and x.startswith("|") for x in p.schema_path)}
        self.assertEqual(sorted(wanted - reached), [])

    def test_a_position_under_a_branch_the_answer_does_not_hold_is_corrupted_beside_a_valid_sample_of_it(self):
        """A Hugging Face card's licence is text in the fixture; the elements of its LIST branch are reached by putting a list in the licence's place first, and a wrong element then
        costs the answer. The branch the fixture does hold (Socrata's licence object) needs no substitution."""
        name = "huggingface.resolve"
        op, body = ALL[name], copy.deepcopy(corrupt_route(ALL[name]).body)
        sid, key, spec = schema_of(name)
        under = [p for p in walk(spec, body, (), (), ("answer",)) if p.schema_path[-3:] == ("license", "|1", "[]")]
        self.assertEqual([(p.path, [path for path, _ in p.pre]) for p in under], [(("cardData", "license", 0), [("cardData", "license")])])
        pos = under[0]
        for wrong in (5, False, ["x"], {"a": 1}):
            out, lane = run(op, grow(grow(body, pos.pre[0][0], pos.pre[0][1]), pos.path, wrong))
            self.assertEqual((lane["completeness"], lane.get("error_class")), ("unobserved", "payload_invalid"), repr(wrong))
        out, lane = run(op, grow(grow(body, pos.pre[0][0], pos.pre[0][1]), pos.path, "cc0"))
        self.assertEqual(lane["completeness"], "complete", "control: the same list with a licence in it reads")
        socrata_spec, socrata_body = schema_of("socrata.resolve")[2], copy.deepcopy(corrupt_route(ALL["socrata.resolve"]).body)
        held = [p for p in walk(socrata_spec, socrata_body, (), (), ("answer",)) if p.schema_path[-2:] == ("|0", "name")]
        self.assertEqual([p.pre for p in held], [()], "the branch the fixture holds is walked as it is")

    def test_the_loaders_pages_and_the_direct_resolves_are_in_the_inventory_too(self):
        for key, (sid, schema_key, body, url, identity) in DIRECT.items():
            spec = schema_of_key(sid, schema_key)
            reached = {p.schema_path for p in walk(spec, body, (), (), ("answer",))}
            with self.subTest(op=key):
                self.assertEqual((sorted(declared_paths(spec) - reached)), [])
        for name, url, body, loader, _ in LoaderCorruptions.PAGES:
            spec = adapters_registries_schema(name)
            reached = {p.schema_path for p in walk(spec, body, (), (), ("answer",))}
            with self.subTest(page=name):
                self.assertEqual((sorted(declared_paths(spec) - reached)), [])


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
                    corrupted = grow(prepared(body, pos), pos.path, value)
                    verdict, got = self.ask(sid, key, url, identity, corrupted)
                    kind = pos.boundary[0]
                    first_member = kind == "member" and pos.boundary[1][:1] == ("results",) and pos.boundary[1][1:2] == (0,)   # a lookup reads only its first result
                    want = "unreadable" if kind == "answer" or first_member else "record"
                    if kind == "member" and not first_member and pos.boundary[1][:1] == ("results",):
                        want = "record"
                    with self.subTest(op=name, position=repr(pos), value=repr(value)):
                        self.assertEqual(verdict, want, got)
        self.assertGreater(runs, 100)


class LoaderCorruptions(unittest.TestCase):
    """The registry loaders' pages (harvest/registries.py), the same derivation: a position inside a journal or repository costs that row (the load goes on, and a row that
    was an object and could not be read is reported); the page's envelope costs the load; the end of the registry is read from a count that, unreadable, is a failed load."""

    PAGES = (("crossref journals", "https://api.crossref.org/journals", loaders_oracle.CROSSREF_JOURNALS, "crossref_journals", False),
             ("datacite repositories", "https://api.datacite.org/repositories", loaders_oracle.DATACITE_REPOSITORIES, "datacite_repositories", True))
    LOAD_FAILS = {("datacite repositories", ("meta", "totalPages")): "a page whose count of pages cannot be read does not say it is the last: a failed load, not a complete one"}

    def load(self, loader: str, url: str, body):
        import json
        from research_gateway.adapters.base import Client, FakeTransport
        from research_gateway.core.broker import Broker, RatePolicy
        from research_gateway.harvest import registries
        t = FakeTransport()
        t.add("GET", url, 200, json.dumps(body).encode())
        c = Client(broker=Broker({"crossref": RatePolicy(per_second=100000), "datacite": RatePolicy(per_second=100000)}), transport=t, sleep=lambda s: None)
        skipped = []
        try:
            fn = getattr(registries, loader)
            records = list(fn(c, skipped=skipped) if loader == "crossref_journals" else fn(c))
            return [r["identity"] for r in records], skipped, None
        except ValueError as e:
            return None, skipped, e

    def test_every_declared_position_every_wrong_kind(self):
        runs = 0
        for name, url, body, loader, _ in self.PAGES:
            spec = adapters_registries_schema(name)
            valid, skipped, error = self.load(loader, url, body)
            self.assertEqual((error, skipped, len(valid)), (None, [], 2), name)
            for pos in walk(spec, body, (), (), ("answer",)):
                if not pos.path:
                    continue
                for value in wrong_for(pos.spec) + (tuple([MISSING, None]) if pos.required else ()):
                    if (value is MISSING or value is None) and (not pos.present or isinstance(pos.path[-1], int)):
                        continue
                    runs += 1
                    identities, skipped, error = self.load(loader, url, grow(prepared(body, pos), pos.path, value))
                    kind = pos.boundary[0]
                    label = f"{name}: {pos!r} <- {value!r}"
                    with self.subTest(page=name, position=repr(pos), value=repr(value)):
                        if (name, pos.path) in self.LOAD_FAILS:
                            self.assertIsNotNone(error, label)
                        elif kind == "answer":
                            self.assertIsNotNone(error, label)
                        elif kind == "soft":
                            self.assertEqual((error, identities), (None, valid), label)
                        else:   # a row: the others stand; it is gone; a row that was an object and could not be read is reported (the Crossref loader keeps the list)
                            index = pos.boundary[1][-1] if isinstance(pos.boundary[1][-1], int) else None
                            self.assertIsNone(error, label)
                            self.assertEqual(identities, [i for n, i in enumerate(valid) if n != index], label)
        self.assertGreater(runs, 100)

    def test_a_crossref_row_that_was_an_object_and_cannot_be_read_is_reported_and_one_that_was_not_an_object_is_not(self):
        name, url, body, loader, _ = self.PAGES[0]
        for value, reported in (({"title": "J", "ISSN": "notalist"}, 1), (7, 0), ("x", 0), ({"title": "J", "issn-type": [{"value": False}]}, 1)):
            page = copy.deepcopy(body)
            page["message"]["items"][1] = value
            identities, skipped, error = self.load(loader, url, page)
            self.assertEqual((error, len(identities), len(skipped)), (None, 1, reported), value)
            self.assertTrue(all("PayloadError" in why for why in skipped), skipped)


class CsvCorruptions(unittest.TestCase):
    """DOAJ's journals are read from a CSV dump (harvest/registries.py doaj_journals), decoded by the same decoder (S.decode_csv) against `DOAJ_ROW`. A CSV cell has no wrong KIND — it is
    text — so its positions are the ones a table has: a column the header lacks, a cell a row leaves empty, a row too short to hold it, and what the file is at all. Every column is the
    schema's: derived from `DOAJ_ROW`, with the columns the loader needs of the file (`DOAJ_COLUMNS`) the only ones whose absence costs the load."""

    @staticmethod
    def dump(columns, rows) -> str:
        import csv
        import io
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)
        return out.getvalue()

    def load(self, text):
        import json
        from research_gateway.adapters.base import Client, FakeTransport
        from research_gateway.core.broker import Broker, RatePolicy
        from research_gateway.harvest import registries
        t = FakeTransport()
        t.add("GET", registries.DOAJ_CSV, 200, text.encode())
        c = Client(broker=Broker({"doaj": RatePolicy(per_second=100000)}), transport=t, sleep=lambda s: None)
        try:
            return [r["identity"] for r in registries.doaj_journals(c)], None
        except Exception as e:   # what comes out is the test's to judge: a PayloadError is the channel, anything else is a failure of it
            return None, e

    @property
    def columns(self):
        from research_gateway.harvest import registries
        return list(registries.DOAJ_ROW.of)

    def rows(self):
        cells = {"Journal title": ("Journal of Harvest Testing", "Open Data Quarterly"), "Journal ISSN (print version)": ("9999-9991", ""),
                 "Journal EISSN (online version)": ("", "9999-9983")}
        return [[(cells.get(c) or ("x", "y"))[i] for c in self.columns] for i in (0, 1)]

    def test_the_valid_dump_loads_and_every_column_is_one_the_schema_declares(self):
        self.assertEqual(self.load(self.dump(self.columns, self.rows())), (["issn:9999-9991", "issn:9999-9983"], None))
        self.assertGreater(len(self.columns), 8)

    def test_every_column_left_out_of_the_header_costs_the_load_only_when_the_loader_needs_it(self):
        from research_gateway.harvest import registries
        for i, column in enumerate(self.columns):
            header = [c for c in self.columns if c != column]
            rows = [[cell for j, cell in enumerate(row) if j != i] for row in self.rows()]
            identities, error = self.load(self.dump(header, rows))
            with self.subTest(column=column):
                if column in registries.DOAJ_COLUMNS:
                    self.assertIsNotNone(error, "a dump without its title column is not the dump the loader supports")
                    self.assertIsInstance(error, PayloadError)
                else:
                    self.assertEqual((error, len(identities)), (None, 2), "the cells it would have held are nothing; the journals are still read")

    def test_every_column_empty_in_every_row_or_missing_from_a_short_row_is_nothing_and_costs_no_row(self):
        for i, column in enumerate(self.columns):
            empty = [[("" if j == i else cell) for j, cell in enumerate(row)] for row in self.rows()]
            with self.subTest(column=column, how="empty"):
                identities, error = self.load(self.dump(self.columns, empty))
                self.assertEqual((error, len(identities)), (None, 2), "a cell a row leaves empty is nothing; the journal is keyed by what else it carries")
            if i:
                short = [row[:i] for row in self.rows()]
                with self.subTest(column=column, how="short row"):
                    identities, error = self.load(self.dump(self.columns, short))
                    self.assertEqual((error, len(identities)), (None, 2), "a row too short to hold a column holds nothing there")

    def test_cells_past_the_header_are_not_read(self):
        longer = [row + ["extra", "more"] for row in self.rows()]
        self.assertEqual(self.load(self.dump(self.columns, longer)), (["issn:9999-9991", "issn:9999-9983"], None))

    def test_a_cell_past_the_field_limit_and_a_file_with_no_usable_header_are_unreadable_not_empty(self):
        """Two of the ways a dump is no dump: a cell past the opener's field limit (the csv module's own, 131,072 characters), and a file whose first line is not a header with the title
        column. Neither says anything about quoting: the framing of the serialized bytes is the next test's, and tests/test_openers.py's."""
        huge = self.dump(self.columns, [["x" * 200_000] + ["y"] * (len(self.columns) - 1)])
        identities, error = self.load(huge)
        self.assertIsInstance(error, PayloadError)
        for text in ("", "\n", "no header here\n1,2\n"):
            with self.subTest(text=text):
                self.assertIsInstance(self.load(text)[1], PayloadError)

    def test_a_dump_whose_serialized_framing_is_broken_is_unreadable_not_shorter_or_empty(self):
        """The serialized bytes are corrupted, not the rows (R13A-1): a writer produces the valid dump, with a quoted multiline cell as the control, and the text is edited. An unterminated
        quote in the header, in a cell and in the last cell, text after a closing quote, a quote inside an unquoted cell, a column the schema reads named twice. Each is a PayloadError and
        never a successful load of fewer journals (the unterminated header was a load of ZERO)."""
        rows = self.rows()
        rows[0][0] = "Journal of\nHarvest Testing"
        valid = self.dump(self.columns, rows)
        self.assertEqual(self.load(valid), (["issn:9999-9991", "issn:9999-9983"], None), "control: a quoted multiline cell is one cell")
        first, second = rows[0][0], rows[1][0]
        corrupt = {"an unterminated quote in the header": valid.replace(self.columns[1], '"' + self.columns[1], 1),
                   "the multiline cell's closing quote removed": valid.replace('Harvest Testing"', "Harvest Testing", 1),
                   "an unterminated quote in the second journal's title": valid.replace(second, '"' + second, 1),
                   "an unterminated quote in the last cell of the file": valid.rstrip("\n")[:-1] + '"' + valid.rstrip("\n")[-1:],
                   "text after a closing quote": valid.replace('Harvest Testing"', 'Harvest Testing"junk', 1),
                   "a quote inside an unquoted cell": valid.replace(second, 'Open "Data" Quarterly', 1),
                   "a column the schema reads, named twice": valid.replace(self.columns[3], self.columns[0], 1),
                   "the licence column named twice": valid.replace(self.columns[0], self.columns[6], 1)}
        for name, text in corrupt.items():
            self.assertNotEqual(text, valid, name)
            identities, error = self.load(text)
            with self.subTest(name):
                self.assertIsInstance(error, PayloadError, f"loaded {identities}")


class LookupCorruptions(unittest.TestCase):
    """doi.org's registration-agency lookup (core/identity.py), derived from its schema: the WHOLE answer crosses the decoder before anything is decided from it or remembered
    (R12-1). An answer that is not a list of results is unreadable — a PayloadError, and nothing is cached; a first result that cannot be read names no agency, and nothing is cached
    either; a readable answer caches what it says, including 'unknown' for a DOI it does not know."""
    VALID = [{"DOI": "10.1234/x", "RA": "Crossref"}]

    def ask(self, body, raw: bytes | None = None):
        import json
        from research_gateway.adapters.base import Client, FakeTransport
        from research_gateway.core.broker import Broker, RatePolicy
        from research_gateway.core.identity import RegistrationAgencies
        t = FakeTransport()
        t.add("GET", "https://doi.org/ra/10.1234/x", 200, json.dumps(body).encode() if raw is None else raw)
        cache: dict = {}
        c = Client(broker=Broker({"doi_org": RatePolicy(per_second=100000)}), transport=t, sleep=lambda s: None)
        try:
            return RegistrationAgencies(c, cache).agency("10.1234/x"), cache
        except PayloadError:
            return "raised", cache

    def test_every_declared_position_every_wrong_kind(self):
        from research_gateway.core.identity import SCHEMAS
        spec, runs = SCHEMAS["lookup"], 0
        self.assertEqual(self.ask(self.VALID), ("Crossref", {"10.1234": "Crossref"}), "control")
        for pos in walk(spec, self.VALID, (), (), ("answer",)):
            for value in wrong_for(pos.spec):
                runs += 1
                got = self.ask(grow(prepared(self.VALID, pos), pos.path, value))
                with self.subTest(position=repr(pos), value=repr(value)):
                    self.assertEqual(got[1], {}, "an unreadable answer is never remembered as the prefix's agency")
                    self.assertEqual(got[0], "raised" if pos.boundary[0] == "answer" else "unknown")
        self.assertGreater(runs, 15)

    def test_the_outer_shapes_that_skipped_the_decoder_and_cached_unknown(self):
        """Astra's probes (R12-1): HTTP 200 JSON `false`, `{}`, a string and an object that holds an `RA` were taken for 'no agency' and remembered."""
        for body in (False, True, 0, {}, "not a list", {"RA": "Crossref"}, None, {"results": [{"RA": "Crossref"}]}):
            with self.subTest(body=repr(body)):
                self.assertEqual(self.ask(body), ("raised", {}))
        for raw in (b"", b"[", b"<html>", b"\xff", b"[" * 100_000):
            with self.subTest(raw=raw[:12]):
                self.assertEqual(self.ask(None, raw), ("raised", {}))
        self.assertEqual(self.ask([5]), ("unknown", {}), "a first result that is not an object names no agency, and is not remembered")
        self.assertEqual(self.ask([{"RA": "Crossref"}]), ("Crossref", {"10.1234": "Crossref"}))
        self.assertEqual(self.ask([]), ("unknown", {"10.1234": "unknown"}), "a readable answer that names nobody is unknown, and that is remembered")
        self.assertEqual(self.ask([{"DOI": "10.1234/x"}]), ("unknown", {"10.1234": "unknown"}))


def adapters_registries_schema(name: str) -> S.Spec:
    from research_gateway.harvest import registries
    return registries.SCHEMAS[name]


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
