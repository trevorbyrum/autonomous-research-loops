"""Task 2b-repair-14 (Gate D #2, checklist 6): the one owned inventory of the gateway's provider-input discipline, held equal to the source, and the controls of its scans.

tests/inventory.py is the inventory: five scans of the package's own source and one table, each site with a role and a reason (its module docstring says what it is, and what it is not). This file
holds it:

  Inventory   every site the scans find is listed and every listed site is there; each entry's role may stand where it stands (RULES); the sanctioned predicates (`Rec.empty`, `Rec.same_as`) and the
              one materialization (`plain`) stand exactly where the operator's ruling of 2026-10-02 puts them; no CSV/XML reader is imported outside core/wire.py; the real tree passes the import guard
  Scans       a CONTROL for each scan: the spellings it finds are found, the ones it is not written to find are not, and both are stated — a finite syntax guard, not an analysis of Python. The spelling
              the 13c review found the old parser scan missed, `json.JSONDecoder().decode(...)`, is among the found ones.

What the table shows: that a reviewer classified every place the package opens provider bytes, reads a decoded answer past the decoder, materializes it or reads a response's bytes. What it does not:
that no other place could (the scans are syntax over this package's source), that a role was the right one (the review's), or that the independent oracle's behaviours hold (tests/test_oracle.py).
This replaces tests/test_openers.py's `Inventory`, tests/test_member_isolation.py's `Reads` and tests/test_opaque_provenance.py's `BytesAreOpenedOnlyWhere`, whose claims the Gate C audit of 13c narrowed.
"""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from collections import Counter
from pathlib import Path

from tests import inventory as INV
from tests.inventory import ROLES, RULES, SITES


class Inventory(unittest.TestCase):
    def test_every_site_the_scans_find_is_listed_and_every_listed_site_is_there(self):
        found, listed = INV.scan(), {k: n for k, (n, _, _) in SITES.items()}
        self.assertEqual(sorted(set(found) - set(listed)), [], "a site the scans find that is not in the table: classify it (a role and a reason), or take it out of the code")
        self.assertEqual(sorted(set(listed) - set(found)), [], "a listed site that is no longer there")
        self.assertEqual({k: (found[k], n) for k, n in listed.items() if found[k] != n}, {}, "(sites found, sites listed): read the new site, and update the entry's count and reason")

    def test_each_entry_has_a_known_role_that_may_stand_there_and_a_reason(self):
        for (kind, file, function, what), (count, role, why) in SITES.items():
            with self.subTest(site=(kind, file, function, what)):
                self.assertGreaterEqual(count, 1)
                self.assertIn(role, ROLES, "a role the inventory does not define")
                self.assertIn(role, RULES, "a role with no rule for where it may stand")
                self.assertTrue(RULES[role](file, function, what), f"the role {role} may not stand at {file} {function} ({what}): {ROLES[role]}")
                self.assertGreaterEqual(len(why.split()), 4, "a site is classified with a reason, not a label")
        self.assertEqual(sorted(set(ROLES) - set(RULES)), [], "every role has a rule")
        self.assertEqual(sorted(set(ROLES) - {role for _, role, _ in SITES.values()}), [], "a role no site has is a classification nobody uses: take it out")

    def test_the_sanctioned_predicates_stand_exactly_where_the_ruling_puts_them(self):
        """Operator ruling 2 (2026-10-02): `Rec.empty` is used only at the reviewed provider-shape predicates; equality between decoded provider objects only for the intended comparisons
        (Unpaywall's best-location check), never for a value an adapter minted. Held by the scan of every provider-data module, not only the ones listed here."""
        found = INV.door_sites()
        empty = {key for key, whats in found.items() if "method empty" in whats}
        same_as = {key for key, whats in found.items() if "method same_as" in whats}
        self.assertEqual(empty, INV.SANCTIONED_EMPTY)
        self.assertEqual(same_as, INV.SANCTIONED_SAME_AS)
        self.assertEqual({(f, fn) for (kind, f, fn, what), (_, role, _) in SITES.items() if role == "SANCTIONED-PREDICATE"}, INV.SANCTIONED_EMPTY)
        self.assertEqual({(f, fn) for (kind, f, fn, what), (_, role, _) in SITES.items() if role == "SANCTIONED-COMPARISON"}, INV.SANCTIONED_SAME_AS)

    def test_plain_the_one_materialization_is_called_at_the_reviewed_sinks_alone(self):
        sinks = {(f, fn) for (kind, f, fn, what) in SITES if kind == "materialize"}
        self.assertEqual(sinks, {("core/router.py", "execute"), ("core/cache.py", "Cache.put_record"), ("harvest/index.py", "upsert")})
        self.assertEqual({(f, fn) for (f, fn, what) in INV.materializer_sites()}, sinks)
        for (kind, f, fn, what), (_, role, _) in SITES.items():
            self.assertEqual(kind == "materialize", role == "MATERIALIZER", (kind, f, fn))

    def test_only_core_wire_py_opens_a_providers_bytes_by_a_library_parser(self):
        """What is asserted is the TABLE's classification of the parser references in the package: every one outside core/wire.py is classified as something that is not a provider's answer (a caller's
        request, the gateway's own API, a token it signed, the operator's files). It does not trace a provider's bytes through the code: a parse of provider bytes that the scans' spellings do not
        reach would not be here, and the runtime evidence is separate (tests/test_sealed_payload.py, tests/test_opaque_provenance.py: nothing but the decoder holds a payload)."""
        parse = {k: role for k, (_, role, _) in SITES.items() if k[0] == "parse"}
        openers = {k for k, role in parse.items() if role == "PAYLOAD-OPENER"}
        self.assertEqual(sorted({k[1] for k in openers}), ["core/wire.py"])
        self.assertEqual({k[1] for k, role in parse.items() if k[1] == "core/wire.py"}, {"core/wire.py"})
        self.assertEqual(sorted({role for role in parse.values()}), ["AUTH", "CALLER", "CONFIG", "GATEWAY", "PAYLOAD-OPENER"])

    def test_no_csv_or_xml_reader_is_imported_outside_wire(self):
        """The two formats whose default readers resolve malformed bytes: nothing outside core/wire.py imports a reader for them (core/payload.py and core/schema.py import ElementTree for its
        element TYPE, which opens nothing)."""
        self.assertEqual(INV.parser_imports_outside_wire(), [])

    def test_every_consumer_of_an_opener_is_listed_and_each_opener_is_used(self):
        consumers = {(f, fn): what for (kind, f, fn, what) in SITES if kind == "opener"}
        self.assertEqual({(f, fn): what for (kind, f, fn, what) in INV.scan() if kind == "opener"}, consumers)
        self.assertEqual(set(consumers.values()), set(INV.OPENERS))

    def test_the_decoders_reads_of_bytes_are_the_decoders_alone_and_the_clients_are_the_listed_ones(self):
        body = {k: role for k, (_, role, _) in SITES.items() if k[0] == "body"}
        self.assertEqual({k[2] for k, role in body.items() if role == "DECODER"}, {"_open_json", "_bytes_or_text"})
        self.assertTrue(all(k[1] == "core/schema.py" for k, role in body.items() if role == "DECODER"))
        provider = {p.relative_to(INV.ROOT).as_posix() for p in INV.provider_modules()}
        self.assertEqual([k for k in body if k[1] in provider], [], "no provider module reads a response's bytes")

    def test_nothing_reaches_the_storage_or_parses_json_itself(self):
        doors = INV.door_sites()
        self.assertEqual({k: v for k, v in doors.items() if any(w.startswith("private ") for w in v)}, {})
        self.assertEqual({k: v for k, v in doors.items() if "answer ._parsed" in v}, {})
        self.assertEqual(INV.reflection_in_adapters(), [])

    def test_every_provider_data_module_imports_only_what_the_inventory_admits(self):
        self.assertEqual(INV.import_findings(), [])

    def test_the_provider_data_modules_are_exactly_the_ones_that_read_an_answer(self):
        names = [p.relative_to(INV.ROOT).as_posix() for p in INV.provider_modules()]
        for expected in ("adapters/crossref.py", "core/sdmx.py", "core/identity.py", "harvest/registries.py", "harvest/openalex_snapshot.py"):
            self.assertIn(expected, names)
        self.assertNotIn("adapters/base.py", names)


def tree(files: dict) -> tempfile.TemporaryDirectory:
    """A synthetic package: these files (relative path -> source) under a temporary root, with the empty modules the provider-module list expects."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for rel in ("adapters/__init__.py", "core/schema.py", "core/sdmx.py", "core/identity.py", "core/payload.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("")
    for rel, source in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(textwrap.dedent(source), encoding="utf-8")
    return tmp


def sites(scan, files: dict) -> dict:
    with tree(files) as tmp:
        found = scan(Path(tmp))
    return {(function, what): n for (_, function, what), n in found.items()} if isinstance(found, Counter) else found


class Scans(unittest.TestCase):
    """For each scan: the spellings it is written to find, found; the ones it is not, not — said here, so that no one reads the table as more than it is."""

    PARSE = '''
        import json
        import json as j
        import json.decoder
        import xml.etree.ElementTree
        import xml.etree.ElementTree as ET
        import csv
        import tomllib
        from json import loads, JSONDecoder as Decoder
        from json import loads as l
        from json.decoder import JSONDecoder as Deep
        from xml.etree import ElementTree as ET2
        def a(x): return json.loads(x)
        def b(x): return j.loads(x)
        def c(x): return loads(x)
        def d(x): return l(x)
        def e(x): return ET.fromstring(x)
        def e2(x): return xml.etree.ElementTree.fromstring(x)
        def e3(x): return ET2.XML(x)
        def f(x): return list(csv.reader(x))
        def g(x): return tomllib.loads(x)
        def i(x): return json.dumps(x)
        def k(x): return ET.tostring(x)
    '''

    def test_control_the_parse_scan_finds_a_parser_however_it_is_imported(self):
        found = sites(INV.parse_sites, {"adapters/new.py": self.PARSE})
        self.assertEqual(found, {("a", "json.loads"): 1, ("b", "json.loads"): 1, ("c", "json.loads"): 1, ("d", "json.loads"): 1, ("e", "xml.etree.ElementTree.fromstring"): 1,
                                 ("e2", "xml.etree.ElementTree.fromstring"): 1, ("e3", "xml.etree.ElementTree.XML"): 1, ("f", "csv.reader"): 1, ("g", "tomllib.loads"): 1})

    def test_control_the_parse_scan_finds_a_parser_object_and_a_parser_that_is_not_called(self):
        """The known gap of the 13c review: `json.JSONDecoder().decode(data)` in a new module produced no finding, because only calls of the listed functions were looked at. A parser OBJECT is a
        site where it is made, a parser held without being called is one where it is named, and a parser reached under an alias of its module, of its class or by its dotted path is one."""
        spellings = {
            "a public parser object, called": "import json\ndef f(x):\n    return json.JSONDecoder().decode(x)\n",
            "a parser object held, then used": "import json\ndef f(x):\n    d = json.JSONDecoder()\n    return d.raw_decode(x)\n",
            "the class imported by name": "from json import JSONDecoder\ndef f(x):\n    return JSONDecoder().decode(x)\n",
            "the class imported under another name": "from json import JSONDecoder as D\ndef f(x):\n    return D().decode(x)\n",
            "the class by its dotted path": "import json.decoder\ndef f(x):\n    return json.decoder.JSONDecoder().decode(x)\n",
            "the class from its submodule": "from json.decoder import JSONDecoder\ndef f(x):\n    return JSONDecoder().decode(x)\n",
            "the module under an alias": "import json as j\ndef f(x):\n    return j.JSONDecoder().decode(x)\n",
            "a parser function held, not called": "import json\ndef f():\n    return json.loads\n",
            "a parser function held in a variable": "import json\ndef f(x):\n    p = json.loads\n    return p(x)\n",
            "a parser function passed on": "import json\ndef f(xs):\n    return list(map(json.loads, xs))\n",
            "an XML parser object": "import xml.etree.ElementTree as ET\ndef f(x):\n    p = ET.XMLParser()\n    p.feed(x)\n    return p.close()\n",
            "an expat parser": "import xml.parsers.expat as expat\ndef f():\n    return expat.ParserCreate()\n",
            "a CSV sniffer": "import csv\ndef f(x):\n    return csv.Sniffer().sniff(x)\n",
        }
        for label, source in spellings.items():
            with self.subTest(label):
                found = sites(INV.parse_sites, {"adapters/new.py": source})
                self.assertEqual(list(found.values()), [1], found)
                self.assertEqual({fn for fn, _ in found}, {"f"})

    def test_the_parse_scan_limits_stated_what_a_syntax_guard_does_not_follow(self):
        """Each of these is a way to a parser the scan does not find. They are stated as limits, not defended: the guard is for review, and a reviewer reads the module's imports and its dynamic sites."""
        not_found = {
            "a module held in a variable": "import json\ndef f(x):\n    m = json\n    return m.loads(x)\n",
            "a module returned by a call": "import json\ndef pick():\n    return json\ndef f(x):\n    return pick().loads(x)\n",
            "a name built as a string": "import json\ndef f(x):\n    return getattr(json, 'lo' + 'ads')(x)\n",
            "a parser reached through a container": "import json\nTABLE = {'p': json}\ndef f(x):\n    return TABLE['p'].loads(x)\n",
        }
        for label, source in not_found.items():
            with self.subTest(label):
                self.assertEqual(sites(INV.parse_sites, {"adapters/new.py": source}), {}, "the parse scan does not follow values")
        # ... and what is refused outright instead: the dynamic sites are found, for a person to read
        dynamic = {"__import__": "def f():\n    return __import__('json')\n", "importlib": "import importlib\ndef f():\n    return importlib.import_module('json')\n",
                   "eval": "def f(x):\n    return eval(x)\n", "exec": "def f(x):\n    exec(x)\n", "getattr of a parser's name": "import json\ndef f(x):\n    return getattr(json, 'loads')(x)\n"}
        for label, source in dynamic.items():
            with self.subTest(label):
                self.assertEqual(list(sites(INV.dynamic_sites, {"adapters/new.py": source}).values()), [1])

    def test_control_the_opener_scan_finds_a_reference_to_wire_however_it_is_imported(self):
        files = {"adapters/new.py": "from ..core import wire\nfrom ..core.wire import open_csv as csv_opener\nfrom ..core import wire as w\n"
                                    "def a(x): return wire.open_json(x)\ndef b(x): return csv_opener(x)\ndef c(): return w.open_xml\ndef d(x): return wire.Malformed\n"}
        self.assertEqual(sites(INV.opener_sites, files), {("a", "open_json"): 1, ("b", "open_csv"): 1, ("c", "open_xml"): 1})

    def test_control_the_materializer_scan_finds_plain_however_it_is_imported(self):
        files = {"adapters/new.py": "from ..core.payload import plain, Sealed\nfrom ..core.payload import plain as unwrap\nfrom ..core import payload\n"
                                    "def a(rows): return plain(rows)\ndef b(rows):\n    out = plain\n    return out(rows)\ndef c(rows): return list(map(plain, rows))\n"
                                    "def d(rows): return unwrap(rows)\ndef e(rows): return payload.plain(rows)\ndef f(rows): return Sealed(rows)\ndef g(rows): return rows.plain()\n",
                 "core/payload.py": "def plain(x):\n    return plain(x)\n"}
        self.assertEqual(sites(INV.materializer_sites, files), {("a", "plain"): 1, ("b", "plain"): 1, ("c", "plain"): 1, ("d", "plain"): 1, ("e", "plain"): 1})

    def test_control_the_body_scan_finds_a_read_of_a_responses_bytes(self):
        files = {"adapters/new.py": "def a(resp): return resp._body\ndef b(resp): return len(resp._body) + len(resp._body)\ndef c(resp): return resp.body\n", "api/http.py": "def d(self): return self._body\n"}
        self.assertEqual(sites(INV.body_sites, files), {("a", "_body"): 1, ("b", "_body"): 2})

    def test_control_the_door_scan_finds_each_spelling_it_lists_and_no_other(self):
        """The check's own oracle, for a FINITE SYNTAX GUARD: each spelling it enumerates is found, and what is not one is not. It finds nothing it was not written to find: a decision made from
        the copy a record builder returns was invisible to it (Astra, R13A-2), and is closed by what the constructors do instead (tests/test_opaque_provenance.py ConstructorCompositions runs the
        mutants the scan cannot see)."""
        source = '''
            import json
            from .base import decode, MemberList, Rec
            from .base import MemberList as Wrap
            from ..core import schema as S

            def a_constructor(items):
                return MemberList(items)

            def an_alias(items):
                return Wrap(items)

            def a_reference(items):
                make = MemberList
                return make(items)

            def storage(rows):
                return rows._items

            def reflection(rows):
                return getattr(rows, "_items")

            def an_isinstance(rows):
                return isinstance(rows, MemberList), isinstance(rows, Rec)

            def an_identity_pass(rows):
                return [build(r) for r in rows.each(lambda member: member)]

            def a_position(table):
                return table.at(0)

            def a_decoded_object(rec, other):
                return rec.empty, rec.same_as(other), rec.without

            def by_the_back_door(rows):
                return object.__getattribute__(rows, "_items")

            def storing(w, make):
                return make(raw=w.raw)

            def reading_the_raw(w):
                return w.raw["x"]

            def decoding(resp):
                return decode("x", S.obj({"a": S.text()}), resp.json)

            def reading_by_hand(resp):
                return resp.json["results"]

            def reading_the_text(resp):
                return resp.text.split()

            def downloading(resp):
                return resp.download()

            def a_rec_built_by_hand():
                return Rec({}, {"skip": True})

            def a_schema_constructor():
                return S.text()
        '''
        with tree({"adapters/new_lane.py": source}) as tmp:
            found = {fn: sorted(v) for (_, fn), v in INV.door_sites(Path(tmp)).items() if fn != "<module>"}
            findings = INV.reflection_in_adapters(Path(tmp))
        self.assertEqual(found, {"a_constructor": ["call MemberList"], "an_alias": ["call MemberList"], "a_reference": ["reference MemberList"], "storage": ["private _items"],
                                 "an_identity_pass": ["method each"], "a_position": ["method at"], "a_decoded_object": ["method empty", "method same_as", "method without"],
                                 "reading_the_raw": ["raw"], "reading_by_hand": ["answer .json"], "reading_the_text": ["answer .text"], "downloading": ["answer .download"],
                                 "a_rec_built_by_hand": ["call Rec"]})
        self.assertEqual(findings, [("adapters/new_lane.py", "import json"), ("adapters/new_lane.py", "getattr() of a private name"), ("adapters/new_lane.py", "__getattribute__")])


if __name__ == "__main__":
    unittest.main()
