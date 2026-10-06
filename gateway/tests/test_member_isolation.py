"""Task 2b-repair-12 (R7-2, restated for the decoder): a malformed member never costs the readable members beside it, and nothing reads a provider's answer
except through its declared schema.

The defect came back three times in 2b-repair-7 and -8 (Socrata; then OpenCitations and eight more paths; then Hugging Face's file siblings and ECB's data sets):
one malformed member of a provider's list lost every readable member beside it, because an adapter held its provider's list as a plain Python list and iterated,
filtered, indexed or flattened it before the member-by-member decoder ran. Repair-8 made the list a view that could not be iterated. Repair-12 removes the deeper
cause (core/payload.py, core/schema.py): every operation declares the payload it supports, ONE decoder checks the whole payload before any adapter logic runs, and an
adapter receives only what the decoder returns:

  * a provider's list of members is a `MemberList`: every member already decoded alone, and the list cannot be iterated, indexed, sliced or searched — only read
    through members(), first_member(), take() and expand(), which isolate each member (Views and Bypasses below, run, not scanned for);
  * a provider's object is a `Rec` holding exactly its declared fields: reading another raises UndeclaredRead, which is not a member's loss (Decoded);
  * a payload is reached only through `decode(...)`: the client's Response holds no readable payload at all (no `.json`, `.text` or `.body`: tests/test_sealed_payload.py runs every
    spelling of asking for one), so no adapter parses, subscripts or `.get`s a provider's answer.

What this file holds: the runtime behaviour above, and the IMPORT guard (`Imports`: what a provider-data module may import, closed over every import form). The inventory of where an answer
leaves the decoder — the doors, each listed with its reason — is tests/inventory.py (held by tests/test_inventory.py): one owner for it since 2b-repair-14, a finite syntax guard for review
and not the thing that makes the property so. What it cannot see: a use of `.raw` or `each` whose listed reason is wrong for the list it reads. Whether a given list is one record's own data
(`own(...)` in the schema) or a set of independent candidates (`members(...)`) is the schema author's declaration; the reason beside it is where a reviewer reads it, and
tests/test_schema_corruption.py corrupts every position the schema declares. The behaviour of the lists that ARE members is tested in tests/test_member_decoding.py.
"""
from __future__ import annotations

import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from research_gateway.adapters.base import first_member, members
from research_gateway.core import schema as S, sdmx
from research_gateway.core.canonical import make_record
from research_gateway.core.payload import MemberList, OMIT, PayloadError, Rec, Sealed, UndeclaredRead, Unreadable, plain
from tests.inventory import ROOT, door_sites, import_findings, literal_names, reflection_in_adapters

class Imports(unittest.TestCase):
    """R8-3 (Astra, 2b-repair-8): the inventory above names the doors by what a module imports, so an import it cannot read — a star, a
    name re-exported by the client, `__import__` — walks a door in unseen, and two such mutants of OpenCitations passed every structural test.
    The rule is now closed over import forms: what is not admitted by name is refused, and an import that cannot be analysed is refused.
    Each of the reviewer's two complete mutants is a regression below, each with a permitted-import control.

    R9-3 (Astra, 2b-repair-9; closed in 2b-repair-10b): a package module imported AS a module was admitted and not looked into, so
    `from ..core import cache as provider_helpers` reached `provider_helpers.json.loads` — a parser — with every structural test passing. A module
    import is now analysed through what is done with it (`module.name` where the module defines `name`; anything else is refused), and a name a
    module only assigns from something it imports is no more offered than a name it imports."""

    @staticmethod
    def tree(root: Path, **edits: list) -> Path:
        copy = root / "research_gateway"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for rel, pairs in edits.items():
            path = copy / rel.replace("__", "/", 1)
            text = path.read_text(encoding="utf-8")
            for old, new in pairs:
                assert text.count(old) == 1, f"{rel}: {old!r} is found {text.count(old)} times"
                text = text.replace(old, new)
            path.write_text(text, encoding="utf-8")
        return copy

    OC = "adapters__opencitations.py"
    OC_IMPORT = "from .base import OMIT, Client, check, decode, first_member, members"
    OC_READ = '    rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], resp)\n'
    OC_RETURN = '    return {"identity": f"doi:{doi}", "what": what, "items": members(SOURCE_ID, rows, lambda row: _link(key, row))}\n'
    # the reviewer's first mutant: the rows are filtered with plain() before the decoder runs; the checker saw no `plain` because nothing named it
    STAR = [(OC_IMPORT, "from .base import *"),
            (OC_READ + OC_RETURN, '    rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], [row for row in plain(resp.download()) if row.get(key)])\n' + OC_RETURN)]
    # the second: the body is parsed and filtered by a parser imported from the client, which uses no door at all
    PARSER = [(OC_IMPORT, OC_IMPORT + ", json as provider_json"),
              (OC_READ + OC_RETURN, '    rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], [row for row in provider_json.loads(resp.download()) if row.get(key)])\n' + OC_RETURN)]

    # the third (R9-3): the body is parsed by a parser that an admitted package module imports, reached as an attribute of that module
    CACHE_IMPORT = "from ..core import cache as provider_helpers"
    CACHE_MODULE = [(OC_IMPORT, OC_IMPORT + "\n" + CACHE_IMPORT),
                    (OC_READ + OC_RETURN, '    rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], [row for row in provider_helpers.json.loads(resp.download()) if row.get(key)])\n' + OC_RETURN)]
    # and what the same import does when it only uses what the module defines
    DOI_LINE = '    return normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)'
    MODULE_USE = [(OC_IMPORT, OC_IMPORT + "\nfrom ..core import identity as ids"),
                  (DOI_LINE, '    return ids.normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)')]

    def test_every_provider_data_module_imports_only_what_the_inventory_admits(self):
        self.assertEqual(import_findings(), [])

    def test_a_star_import_is_refused_and_so_is_the_reviewers_mutant(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = import_findings(self.tree(Path(tmp), **{self.OC: self.STAR}))
        self.assertEqual(findings, [("adapters/opencitations.py", "from .base import *")])

    def test_a_parser_re_exported_by_the_client_is_refused_and_so_is_the_reviewers_mutant(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = import_findings(self.tree(Path(tmp), **{self.OC: self.PARSER}))
        self.assertEqual(findings, [("adapters/opencitations.py", "from base import json (not in its __all__)")])

    def test_a_parser_an_admitted_module_imports_is_refused_and_so_is_the_reviewers_complete_mutant(self):
        """R9-3: `provider_helpers.json.loads` — the parser `core/cache.py` imports, reached through the module — and no structural test saw it."""
        with tempfile.TemporaryDirectory() as tmp:
            findings = import_findings(self.tree(Path(tmp), **{self.OC: self.CACHE_MODULE}))
        self.assertEqual(findings, [("adapters/opencitations.py", "provider_helpers.json (not defined in core/cache.py: a module's imports are not its exports)")])

    def test_control_a_module_used_for_what_it_defines_is_not_refused(self):
        """The same import, using `identity.normalize_doi` (a function that module defines): nothing is refused, and no door is used."""
        real = door_sites()
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(Path(tmp), **{self.OC: self.MODULE_USE})
            found = door_sites(root)
            self.assertEqual((import_findings(root), sorted(k for k in found if found[k] != real.get(k))), ([], []))

    def test_control_the_permitted_imports_are_not_refused(self):
        """What the same two edits do when they only use what the client exports: nothing is refused for the import — the one thing a name
        from `__all__` can still be is an unlisted door, which the inventory above catches by name, as it always did."""
        permitted = [(self.OC_IMPORT, self.OC_IMPORT + ", quote as q, identified")]   # a permitted re-export (quote), and a helper in __all__
        spelled_out = [(self.OC_IMPORT, self.OC_IMPORT + ", MemberList"),
                       (self.OC_READ + self.OC_RETURN, '    rows = MemberList([row for row in []])\n' + self.OC_RETURN)]
        real = door_sites()

        def changed(root: Path) -> list:
            found = door_sites(root)
            return sorted(k for k in found if found[k] != real.get(k))
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(Path(tmp), **{self.OC: permitted})
            self.assertEqual((import_findings(root), changed(root)), ([], []))
            root = self.tree(Path(tmp, "b"), **{self.OC: spelled_out})
            self.assertEqual(import_findings(root), [])
            self.assertEqual(changed(root), [("adapters/opencitations.py", "enrich")], "spelled out, the same body is an unlisted door the inventory reports")

    def test_every_other_form_an_import_can_take_is_refused_or_analysed(self):
        cases = {
            "an import of a parser": ("import json", [("adapters/new.py", "import json")]),
            "an aliased parser": ("import json as j", [("adapters/new.py", "import json")]),
            "a parser from a stdlib module": ("from json import loads", [("adapters/new.py", "from json import")]),
            "importlib": ("import importlib", [("adapters/new.py", "import importlib")]),
            "sys": ("import sys", [("adapters/new.py", "import sys")]),
            "the client's private parser": ("from .base import _parsed", [("adapters/new.py", "from .base import _parsed (a private name)")]),
            "the decoder's private opener": ("from ..core.schema import _open_json", [("adapters/new.py", "from ..core.schema import _open_json (a private name)")]),
            "a class's private storage": ("from ..core.payload import _same", [("adapters/new.py", "from ..core.payload import _same (a private name)")]),
            "a module of the client, by name": ("from .base import urllib", [("adapters/new.py", "from base import urllib (not in its __all__)")]),
            "the client as a module": ("from . import base", [("adapters/new.py", "from . import base (as a module: import what it exports by name)")]),
            "a part of the client, by a name its `__all__` does not offer": ("from ._transport import Transport", [("adapters/new.py", "from _transport import Transport (not in its __all__)")]),
            "a part of the client that declares no `__all__` offers nothing": ("from ._response import Response", [("adapters/new.py", "from _response import Response (not in its __all__)")]),
            "a part of the client as a module": ("from . import _links", [("adapters/new.py", "from . import _links (a private name)")]),
            "a star from another module": ("from ..core.canonical import *", [("adapters/new.py", "from ..core.canonical import *")]),
            "a name another module only re-exports": ("from ..core.canonical import PayloadError",
                                                      [("adapters/new.py", "from ..core.canonical import PayloadError (not defined there: a re-export)")]),
            "a module that is not there": ("from .nowhere import thing", [("adapters/new.py", "from .nowhere import thing (no such module)")]),
            "the byte openers, by name": ("from ..core.wire import open_json", [("adapters/new.py", "from ..core.wire import open_json (the byte openers are the decoder's)")]),
            "the byte openers, as a module": ("from ..core import wire", [("adapters/new.py", "from ..core import wire (the byte openers are the decoder's)")]),
            "inside a function": ("def f():\n    import json", [("adapters/new.py", "import json")]),
            "inside a try": ("try:\n    import json\nexcept ImportError:\n    json = None", [("adapters/new.py", "import json")]),
            "by __import__": ("j = __import__('json')", [("adapters/new.py", "__import__()")]),
            "by eval": ("j = eval('1')", [("adapters/new.py", "eval()")]),
            "a parser an admitted module imports, as its attribute": ("from ..core import cache\nrows = cache.json.loads('[]')",
                                                                     [("adapters/new.py", "cache.json (not defined in core/cache.py: a module's imports are not its exports)")]),
            "the same through an alias of the import": ("from ..core import cache as helpers\nrows = helpers.json.loads('[]')",
                                                        [("adapters/new.py", "helpers.json (not defined in core/cache.py: a module's imports are not its exports)")]),
            "a module's own import under another name": ("from ..core import canonical\nrows = canonical.PayloadError",
                                                         [("adapters/new.py", "canonical.PayloadError (not defined in core/canonical.py: a module's imports are not its exports)")]),
            "a module passed to getattr": ("from ..core import cache\nloads = getattr(cache, 'json')",
                                           [("adapters/new.py", "cache (a module, used as a value: what it reaches cannot be bounded)")]),
            "a module aliased by assignment": ("from ..core import cache\nhelpers = cache\nrows = helpers.json",
                                               [("adapters/new.py", "cache (a module, used as a value: what it reaches cannot be bounded)")]),
            "a module's name rebound": ("from ..core import cache\ncache = 5",
                                        [("adapters/new.py", "cache (a module, used as a value: what it reaches cannot be bounded)")]),
        }
        for name, (source, want) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                root = self.tree(Path(tmp))
                (root / "adapters" / "new.py").write_text(f"from __future__ import annotations\n{source}\n", encoding="utf-8")
                self.assertEqual([f for f in import_findings(root) if f[0] == "adapters/new.py"], want)   # what is found in the new file, whatever else the tree holds
        with tempfile.TemporaryDirectory() as tmp:   # and the forms that are admitted: the names the client exports, a stdlib module that is listed
            root = self.tree(Path(tmp))
            (root / "adapters" / "new.py").write_text("from __future__ import annotations\nimport re\nfrom .base import Client, members, quote as q\nfrom ._links import next_link, own_link\n"
                                                      "from ..core.canonical import make_record\nfrom . import crossref\n"
                                                      "from ..core import canonical, identity as ids\nbuilt = canonical.make_record\nnormal = ids.normalize_doi\n",
                                                      encoding="utf-8")
            self.assertEqual([f for f in import_findings(root) if f[0] == "adapters/new.py"], [])
        with tempfile.TemporaryDirectory() as tmp:   # a name that a module assigns from what it imports is no more offered than the import itself
            root = self.tree(Path(tmp))
            (root / "core" / "helper.py").write_text("import json\nloads = json.loads\nLIMIT = 5\n", encoding="utf-8")
            (root / "adapters" / "new.py").write_text("from __future__ import annotations\nfrom ..core.helper import loads, LIMIT\nfrom ..core import helper\n"
                                                      "x = helper.loads\ny = helper.LIMIT\n", encoding="utf-8")
            self.assertEqual([f for f in import_findings(root) if f[0] == "adapters/new.py"],
                             [("adapters/new.py", "from ..core.helper import loads (not defined there: a re-export)"),
                              ("adapters/new.py", "helper.loads (not defined in core/helper.py: a module's imports are not its exports)")])

    def test_the_client_has_no_parser_to_re_export_and_exports_no_module(self):
        from types import ModuleType

        from research_gateway.adapters import base
        parsers = {"json", "ast", "simplejson", "orjson", "ujson", "yaml", "tomllib", "pickle", "marshal", "csv", "plistlib", "configparser", "xml"}
        self.assertEqual({n for n, o in vars(base).items() if isinstance(o, ModuleType) and o.__name__.split(".")[0] in parsers}, set())
        self.assertFalse(hasattr(base, "json"))
        declared = literal_names(ROOT / "adapters" / "base.py", "__all__")
        self.assertEqual(sorted(declared), sorted(base.__all__), "the checker reads the same __all__ the module has")
        for name in base.__all__:
            self.assertFalse(isinstance(getattr(base, name), ModuleType), name)


BODY = [{"id": "a", "n": 1}, 7, {"id": "b", "n": 2}]
ROW = S.obj({"id": S.text(), "n": S.any_()})


def decoded(body):
    """A provider's list of members, as the decoder hands it to an adapter."""
    return S.decode("x", S.members(ROW), body)


def fixture(source: str):
    """A function `run(rows)` compiled from adapter-shaped source, with the names an adapter has in hand."""
    scope = {"members": members, "make_record": make_record, "OMIT": OMIT, "first_member": first_member, "build": build, "MemberList": MemberList}
    exec(textwrap.dedent(source), scope)
    return scope["run"]


def build(row):
    return make_record(identity=f"doi:10.1/{row['id']}", kind="citation", source_id="x")


# the shapes the old name scan missed (Astra, 2b-repair-7 review), and the forms it did catch
SHAPES = {
    "a filter comprehension before the decoder": '''
        def run(rows):
            rows = [r for r in rows if r["id"]]
            return members("x", MemberList(rows), build)''',
    "a while loop over an index": '''
        def run(rows):
            out, i = [], 0
            while i < len(rows):
                out.append(build(rows[i]))
                i += 1
            return out''',
    "a record builder under another name": '''
        def run(rows):
            make = make_record
            return [make(identity=f"doi:10.1/{r['id']}", kind="citation", source_id="x") for r in rows]''',
    "the first row, indexed directly": '''
        def run(rows):
            return [build(rows[0])]''',
    "a for loop that builds": '''
        def run(rows):
            out = []
            for r in rows:
                out.append(build(r))
            return out''',
    "a comprehension that builds": '''
        def run(rows):
            return [build(r) for r in rows]''',
    "a map over the rows": '''
        def run(rows):
            return list(map(build, rows))''',
    "a slice, then a loop": '''
        def run(rows):
            return [build(r) for r in rows[:2]]''',
    "a copy of the list": '''
        def run(rows):
            return members("x", MemberList(list(rows)), build)''',
    "a sorted copy": '''
        def run(rows):
            return members("x", MemberList(sorted(rows, key=lambda r: str(r))), build)''',
    "a membership test": '''
        def run(rows):
            return 7 in rows''',
    "a generator expression": '''
        def run(rows):
            return members("x", MemberList(list(r for r in rows)), build)''',
}


class Bypasses(unittest.TestCase):
    """Run, not scanned for: each shape fails against a provider's list as the decoder hands it over, whatever it is called and wherever it stands."""

    def test_each_shape_is_impossible_against_a_providers_list(self):
        for name, source in SHAPES.items():
            with self.subTest(name):
                with self.assertRaises(TypeError):
                    fixture(source)(decoded(BODY))

    def test_each_shape_is_impossible_even_on_a_list_of_readable_members_only(self):
        """It is not that the body is malformed: the operation does not exist, for any list a provider sends."""
        for name, source in SHAPES.items():
            with self.subTest(name):
                with self.assertRaises(TypeError):
                    fixture(source)(decoded([{"id": "a"}, {"id": "b"}]))

    def test_control_each_shape_is_a_real_bypass_on_the_plain_list_the_adapters_used_to_hold(self):
        """On a plain list the same source runs: the readable members only, it builds what the shape builds; with a malformed member in the list it loses the
        answer (the defect) or reads past it. This is what the member list takes away."""
        working = {"a filter comprehension before the decoder", "a for loop that builds", "a comprehension that builds",
                   "a map over the rows", "a slice, then a loop", "a while loop over an index", "a record builder under another name",
                   "the first row, indexed directly"}
        for name in working:
            with self.subTest(name):
                run = fixture(SHAPES[name])
                self.assertTrue(run([{"id": "a"}, {"id": "b"}]), "the shape works on readable members")
                with self.assertRaises(Exception):   # a member that is not an object loses what the shape would have built
                    run(BODY) if name != "the first row, indexed directly" else run([7, {"id": "a"}])

    def test_the_helpers_refuse_a_plain_list(self):
        with self.assertRaises(TypeError):
            members("x", [{"id": "a"}], build)
        with self.assertRaises(TypeError):
            first_member("x", [{"id": "a"}], build)

    def test_the_decoder_gives_a_list_of_members_as_a_member_list_and_a_record_s_own_list_as_a_list(self):
        answer = S.decode("x", S.obj({"results": S.members(ROW), "tags": S.own(S.text()), "meta": S.obj({"total": S.whole()})}),
                          {"results": [{"id": "a"}], "tags": ["x"], "meta": {"total": 1}})
        self.assertIsInstance(answer["results"], MemberList)
        self.assertEqual(answer["tags"], ["x"])
        self.assertIsInstance(answer["meta"], Rec)


class Views(unittest.TestCase):
    """The operations are absent; what is left reads each member alone."""

    def test_a_list_cannot_be_iterated_indexed_sliced_or_searched(self):
        rows = decoded([{"id": "a"}, 7])
        for what in (lambda: iter(rows), lambda: list(rows), lambda: rows[0], lambda: rows[:1], lambda: 7 in rows, lambda: sorted(rows),
                     lambda: next(iter(rows)), lambda: [*rows], lambda: tuple(rows), lambda: max(rows), lambda: dict(enumerate(rows)),
                     lambda: reversed(rows)):
            with self.assertRaises(TypeError):
                what()
        self.assertEqual((len(rows), bool(rows), bool(decoded([]))), (2, True, False), "its length and truth are all it shows")

    def test_an_object_holds_its_declared_fields_and_nothing_else(self):
        rec = S.decode("x", S.obj({"id": S.text(), "inner": S.obj({"n": S.whole()})}), {"id": "a", "inner": {"n": 1}, "undeclared": 5})
        self.assertEqual((rec["id"], rec["inner"]["n"], plain(rec.raw)["undeclared"]), ("a", 1, 5))
        for what in (lambda: rec["undeclared"], lambda: rec.get("undeclared"), lambda: rec["inner"]["m"]):
            with self.assertRaises(UndeclaredRead):
                what()
        for what in (lambda: iter(rec), lambda: list(rec)):
            with self.assertRaises(TypeError):
                what()
        self.assertFalse(issubclass(UndeclaredRead, (PayloadError, KeyError, AttributeError, TypeError, ValueError, IndexError)),
                         "an undeclared read is a failure, never a member's loss: no builder's net catches it")

    def test_a_keyed_container_hands_its_members_as_entries(self):
        entries = S.decode("x", S.entries(S.obj({"v": S.whole()})), {"a": {"v": 1}, "b": 7})
        self.assertEqual(entries.each(lambda e: (e["key"], e["value"]["v"])), [("a", 1), None])
        self.assertEqual(len(entries), 2)

    def test_a_list_inside_a_member_is_a_member_list_too(self):
        member = S.decode("x", S.obj({"siblings": S.members(ROW), "tags": S.own(S.text())}), {"siblings": [{"id": "a"}], "tags": ["x"]})
        self.assertIsInstance(member["siblings"], MemberList)

    def test_each_member_is_read_alone(self):
        rows = S.decode("x", S.members(S.obj({"id": S.text(), "boom": S.whole(), "skip": S.whole()})),
                        [{"id": "a"}, 7, {"id": "b"}, "x", {"boom": 1}, {"skip": 1}])

        def read(row):
            if row["boom"]:
                raise KeyError("id")
            if row["skip"]:
                return OMIT
            return row["id"]
        self.assertEqual(rows.each(read), ["a", None, "b", None, None])

    def test_the_first_member_is_read_like_any_other_and_never_replaced_by_the_next(self):
        self.assertIsNone(decoded([]).first(lambda r: r["id"]))
        self.assertEqual(decoded([{"id": "a"}, 7]).first(lambda r: r["id"]), "a")
        for rows in ([7], [7, {"id": "a"}]):
            with self.assertRaises(PayloadError) as why:
                decoded(rows).first(lambda r: r["id"], "src")
            self.assertEqual(str(why.exception), "src: the answer's first result cannot be read")
        def boom(row):
            raise KeyError("id")
        with self.assertRaises(PayloadError):   # the first cannot be built
            decoded([{"id": "a"}, {"id": "b"}]).first(boom)

    def test_members_held_by_members_unfold_with_each_unreadable_holder_one_loss(self):
        """Hugging Face's siblings and ECB's data sets: the container is a member too."""
        sets = S.decode("x", S.members(S.obj({"files": S.members(S.obj({"n": S.whole()}))})), [{"files": [{"n": 1}, {"n": 2}]}, 7, {"files": 5}, {"files": [{"n": 3}]}])
        flat = sets.expand(lambda s: s["files"])
        self.assertEqual((len(flat), flat.each(lambda f: f["n"])), (5, [1, 2, None, None, 3]),
                         "the two holders that cannot be unfolded are one loss each; the series of the others stand")

    def test_a_decoded_value_is_opaque_in_a_record_and_plain_data_where_it_leaves(self):
        answer = S.decode("x", S.obj({"tags": S.own(S.text()), "card": S.obj({"k": S.any_()})}), {"tags": ["x", "y"], "card": {"k": [1]}})
        self.assertEqual(plain(answer["tags"]), ["x", "y"])
        self.assertEqual(plain({"a": answer["tags"], "b": (answer["card"],)}), {"a": ["x", "y"], "b": ({"k": [1]},)})
        record = make_record(identity="doi:10.1/x", kind="citation", source_id="x", authors=answer["tags"], extra={"card": answer["card"]}, raw=answer)
        self.assertEqual((type(record["authors"]), type(record["card"]), type(record["raw"])), (list, Rec, Sealed), "a typed list is plain; the decoded object and the raw are not")
        leaving = plain(record)
        self.assertEqual((type(leaving["authors"]), type(leaving["card"]), type(leaving["raw"])), (list, dict, dict))
        self.assertEqual(leaving["raw"], {"tags": ["x", "y"], "card": {"k": [1]}})

    def test_an_unreadable_member_says_why_and_what_it_was(self):
        (bad,) = decoded([7]).unreadable()
        self.assertIsInstance(bad, Unreadable)
        self.assertEqual((plain(bad), bad.was_object), (7, False))
        self.assertIn("where an object belongs", bad.reason)


class Sdmx(unittest.TestCase):
    """core/sdmx.py is outside adapters/: its data sets flattened before the decoder ran (R7-2, ECB). Now a data set is a member too (series_members expands
    them), and every helper that reads the message takes the decoded message."""

    def test_the_helpers_take_and_give_decoded_values(self):
        message = sdmx.message("ecb", {"structure": {"dimensions": {"series": [{"id": "FREQ", "values": [{"id": "D"}]}],
                                                                    "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-01-01"}]}]}},
                                       "dataSets": [{"series": {"0": {"observations": {"0": [1.25]}}}}, 7, {"series": 5}, {"series": {"0": 9}}]})
        found = sdmx.series_members(message)
        self.assertEqual(len(found), 4, "one series, two data sets that cannot be unfolded, one series that is not an object")
        read = sdmx.series_reader(message)
        self.assertEqual(plain(found.each(read)), [{"key": {"FREQ": "D"}, "observations": [("2026-01-01", 1.25)], "observations_raw": {"0": [1.25]}}, None, None, None])

    def test_a_data_sets_that_is_not_a_list_is_an_unreadable_message_not_an_empty_one(self):
        for body in ({"dataSets": {"series": {}}}, {"dataSets": "x"}, {"data": {"dataSets": 5}}):
            with self.subTest(body=body):
                with self.assertRaises(PayloadError):
                    sdmx.message("ecb", body)
        for body in ({}, {"dataSets": None}, {"dataSets": []}, {"data": {"dataSets": []}}, {"data": {}}):
            with self.subTest(body=body):
                self.assertEqual(len(sdmx.datasets(sdmx.message("ecb", body))), 0)


if __name__ == "__main__":
    unittest.main()
