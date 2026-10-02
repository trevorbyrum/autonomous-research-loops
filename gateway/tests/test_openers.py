"""Task 2b-repair-13c (Astra R13A-1): every byte opener is strict against its format's specification, and the inventory of openers is executable.

13a made the decoder total over the VALUES a lexer hands it. Astra then corrupted the serialized bytes instead of generating rows with a well-behaved writer, and found the layer
beneath: Python's `csv` at its default ended a quoted field at the end of the data and read text after a closing quote as part of the cell, so a DOAJ dump with one unterminated
quote loaded as ZERO journals — a successful empty result. The same layer resolved a name that occurs twice (JSON: the last; CSV: the last column), read `NaN`, `Infinity` and
`1e999`, read UTF-16 and encoded surrogates, and (XML) replaced invalid bytes with U+FFFD, ignored a declared encoding and accepted a declaration of version `2.0`.

core/wire.py holds the openers now (its docstring is the ruling for each, against RFC 8259, XML 1.0 and RFC 4180). This file has:

  * Inventory         every parse call in the gateway, by (file, function), each classified; a parse call that is not listed fails, and every PAYLOAD opener must be in wire.py
  * Rulings           what each opener accepts and refuses, as examples with their reasons (the accepted ones are as much the ruling as the refused)
  * ByteCorruption    the corruption family, run for every opener of the inventory THROUGH ITS REAL CONSUMER (the decoder, the DOAJ loader, the snapshot reader, the call log's
                      count): corrupted serialized bytes, each refused with the one channel, each beside a valid control; plus sweeps over every offset of a valid document
  * (tests/test_astra_13a.py  Astra's R13A-1 probes as regressions, byte for byte, including the load that returned a count of zero, written to run unchanged on 2d62753, where they fail)
  * AgainstTheCsvModule  the CSV opener against csv.reader(strict=True) on thousands of generated texts: it accepts nothing strict refuses, reads what both accept identically,
                      and refuses beyond strict only what RFC 4180 §2.5 forbids (a quote inside an unquoted field)
  * AgainstTheLibraries  a VALID document reads as json.loads and ElementTree read it, on generated documents: the strictness is all on the other side of the line
  * HeaderOpeners        the HTTP headers the gateway decides from (Link, Retry-After, Location ...), each with its ruling; Retry-After was `float()` and is `delay-seconds` now

What this does not show: that no other malformed input exists. The family is the formats' lexical rules, enumerated from their specifications (the rulings), not a proof about every
provider; and a truncation that ends at a record boundary is a well-formed shorter document (nothing in CSV marks the end).
"""
from __future__ import annotations

import ast
import csv
import gzip
import io
import json
import random
import tempfile
import unittest
from pathlib import Path

from research_gateway.adapters.base import Client, FakeTransport, Response, _count_of
from research_gateway.core import schema as S
from research_gateway.core import wire
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.core.payload import PayloadError
from research_gateway.harvest import index, openalex_snapshot, registries

ROOT = Path(__file__).resolve().parents[1] / "research_gateway"

# --------------------------------------------------------------------------------------------------------------------------------------- the inventory
PARSERS = {"json": {"loads", "load"}, "csv": {"reader", "DictReader"},
           "xml.etree.ElementTree": {"fromstring", "XML", "parse", "iterparse", "XMLParser", "XMLPullParser", "fromstringlist"},
           "xml.dom.minidom": {"parseString", "parse"}, "xml.sax": {"parseString", "parse", "make_parser"}, "tomllib": {"load", "loads"}, "ast": {"literal_eval"},
           "pickle": {"loads", "load"}, "marshal": {"loads", "load"}, "yaml": {"load", "safe_load"}, "plistlib": {"loads", "load"}, "configparser": {"ConfigParser"}}
OPENERS = ("open_json", "open_xml", "open_csv")   # core/wire.py: the one place a provider's bytes become structure

# (file, function) -> (parse calls, class, why). PAYLOAD: it opens a provider's bytes; it may stand only in core/wire.py. Every other class is input that is not a provider's answer.
CALLS = {
    ("core/wire.py", "open_json"): (1, "PAYLOAD", "a provider's JSON: UTF-8, no NaN/Infinity, finite numbers, each name once, nesting bounded"),
    ("core/wire.py", "open_xml"): (1, "PAYLOAD", "a provider's SDMX-ML: expat's well-formedness, UTF-8 read as UTF-8, a 1.x declaration, no DOCTYPE, nesting bounded"),
    ("api/http.py", "Handler._body"): (1, "CALLER", "a caller's request body to the gateway, checked at the front door (app.py: plain JSON, no NaN/Infinity)"),
    ("clients/cli.py", "payload_from"): (2, "CALLER", "the operator's own command-line arguments"),
    ("clients/http_client.py", "GatewayClient._call"): (2, "GATEWAY", "the gateway's own API answering its own command-line client"),
    ("clients/http_client.py", "raw_observation"): (1, "GATEWAY", "the gateway's own API answering its own command-line client"),
    ("clients/mcp_stdio.py", "main"): (1, "CALLER", "an MCP host's JSON-RPC message on standard input"),
    ("core/principals.py", "Grants.verify"): (1, "AUTH", "the claims of a token the gateway signed itself, read after its signature verified"),
    ("core/secrets.py", "VaultBackend._fetch"): (1, "AUTH", "the secret store's answer, which the operator runs: credentials, not provider data"),
    ("core/secrets.py", "VaultBackend._not_found"): (1, "AUTH", "the secret store's error document"),
    ("app.py", "load_settings"): (1, "CONFIG", "the operator's settings file"),
    ("registry/load.py", "read_seed"): (1, "CONFIG", "the operator's source registry file"),
}
# who calls an opener of core/wire.py, by (file, function): every provider payload reaches its bytes through these and nowhere else
CONSUMERS = {
    ("core/schema.py", "_open_json"): ("open_json", "the decoder: every provider's JSON answer"),
    ("core/schema.py", "parse_xml"): ("open_xml", "the decoder: SDMX-ML"),
    ("core/schema.py", "decode_csv"): ("open_csv", "the decoder: DOAJ's CSV dump"),
    ("adapters/base.py", "_count_of"): ("open_json", "the call log's count of results: bookkeeping, through the same opener"),
    ("harvest/openalex_snapshot.py", "read_snapshot"): ("open_json", "the OpenAlex snapshot's JSON lines"),
}


def functions(tree: ast.AST):
    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield ".".join((*scope, child.name)), child
                yield from visit(child, (*scope, child.name))
            elif isinstance(child, ast.ClassDef):
                yield from visit(child, (*scope, child.name))
            else:
                yield from visit(child, scope)
    return visit(tree, ())


def dotted(node) -> str | None:
    """`a.b.c` for a chain of attributes on a name, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) else None


def scan(root: Path = ROOT) -> tuple[dict, dict, list]:
    """(parse calls by (file, function), calls of wire's openers by (file, function), parsers reached by getattr) over every module of the package. A callee is resolved through the
    module's own imports, whatever they are spelled: `json.loads`, an alias of the module, a name imported from it, a dotted path."""
    calls: dict = {}
    consumers: dict = {}
    indirect: list = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases: dict = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    aliases[a.asname or a.name] = f"{node.module or ''}.{a.name}".lstrip(".")
        spans = sorted(((fn.lineno, fn.end_lineno, q) for q, fn in functions(tree)), key=lambda s: s[1] - s[0])

        def where(node) -> str:
            return next((q for a, b, q in spans if a <= node.lineno <= b), "<module>")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = dotted(node.func)
            if name:
                head, _, rest = name.partition(".")
                full = aliases[head] + ("." + rest if rest else "") if head in aliases else name
                module, _, attr = full.rpartition(".")
                if module in PARSERS and attr in PARSERS[module]:
                    calls.setdefault((rel, where(node)), []).append(full)
                if module.rpartition(".")[2] == "wire" or module == "wire":
                    if attr in OPENERS:
                        consumers.setdefault((rel, where(node)), []).append(attr)
            if isinstance(node.func, ast.Name) and node.func.id in ("getattr", "__import__") and any(
                    isinstance(a, ast.Constant) and a.value in ("loads", "load", "fromstring", "literal_eval") for a in node.args[1:2]):
                indirect.append((rel, where(node)))
    return calls, consumers, indirect


class Inventory(unittest.TestCase):
    def test_every_parse_call_in_the_gateway_is_listed_with_its_class(self):
        calls, _, indirect = scan()
        found = {k: len(v) for k, v in calls.items()}
        listed = {k: n for k, (n, _, _) in CALLS.items()}
        self.assertEqual(sorted(set(found) - set(listed)), [], "a parse call that is not in the inventory: is it a provider's bytes (then it belongs in core/wire.py), or not (then say so here)")
        self.assertEqual(sorted(set(listed) - set(found)), [], "a listed parse call that is no longer there")
        self.assertEqual({k: (found[k], n) for k, n in listed.items() if found[k] != n}, {}, "(calls found, calls listed)")
        self.assertEqual(indirect, [], "a parser reached by getattr")

    def test_a_providers_bytes_are_opened_in_wire_py_and_nowhere_else(self):
        payload = {k for k, (_, kind, _) in CALLS.items() if kind == "PAYLOAD"}
        self.assertEqual(sorted(payload), [("core/wire.py", "open_json"), ("core/wire.py", "open_xml")])
        self.assertTrue(all(file == "core/wire.py" for file, _ in payload))
        kinds = {kind for _, kind, _ in CALLS.values()}
        self.assertEqual(kinds, {"PAYLOAD", "CALLER", "GATEWAY", "AUTH", "CONFIG"})
        self.assertTrue(all(len(why.split()) >= 4 for _, _, why in CALLS.values()))

    def test_no_module_but_wire_parses_csv_or_xml_at_all(self):
        """The two formats whose default readers resolve malformed bytes: nothing outside core/wire.py imports a reader for them (core/payload.py and core/schema.py import ElementTree for its
        element TYPE, which opens nothing)."""
        for path in sorted(ROOT.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for name in names:
                    if name.split(".")[0] == "csv" or name.startswith(("xml.sax", "xml.dom", "xml.parsers", "lxml")):
                        self.fail(f"{rel} imports {name}")
                    if name == "xml.etree.ElementTree":
                        self.assertIn(rel, ("core/wire.py", "core/payload.py", "core/schema.py"), f"{rel} imports ElementTree")

    def test_every_consumer_of_an_opener_is_listed_and_each_opener_is_used(self):
        _, consumers, _ = scan()
        found = {k: sorted(set(v)) for k, v in consumers.items() if k[0] != "core/wire.py"}
        listed = {k: [opener] for k, (opener, _) in CONSUMERS.items()}
        self.assertEqual(found, listed)
        self.assertEqual({o for o, _ in CONSUMERS.values()}, {"open_json", "open_xml", "open_csv"})

    def test_control_the_scan_finds_a_parser_however_it_is_imported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "adapters").mkdir()
            (root / "adapters" / "new.py").write_text(
                "import json\nimport json as j\nfrom json import loads\nfrom json import loads as l\nimport xml.etree.ElementTree as ET\nimport xml.etree.ElementTree\nfrom xml.etree import ElementTree as ET2\nimport csv\nimport tomllib\n"
                "def a(x):\n    return json.loads(x)\ndef b(x):\n    return j.loads(x)\ndef c(x):\n    return loads(x)\ndef d(x):\n    return l(x)\n"
                "def e(x):\n    return ET.fromstring(x)\ndef e2(x):\n    return xml.etree.ElementTree.fromstring(x)\ndef e3(x):\n    return ET2.XML(x)\ndef f(x):\n    return list(csv.reader(x))\ndef g(x):\n    return tomllib.loads(x)\ndef h(x):\n    return getattr(json, 'loads')(x)\n"
                "def i(x):\n    return json.dumps(x)\n")
            calls, _, indirect = scan(root)
        self.assertEqual({fn: v for (_, fn), v in calls.items()},
                         {"a": ["json.loads"], "b": ["json.loads"], "c": ["json.loads"], "d": ["json.loads"], "e": ["xml.etree.ElementTree.fromstring"],
                          "e2": ["xml.etree.ElementTree.fromstring"], "e3": ["xml.etree.ElementTree.XML"], "f": ["csv.reader"], "g": ["tomllib.loads"]})
        self.assertEqual(indirect, [("adapters/new.py", "h")])


# --------------------------------------------------------------------------------------------------------------------------------------- the rulings
class Refusal(unittest.TestCase):
    def refused(self, opener, body, *, mentions: str = ""):
        with self.assertRaises(wire.Malformed) as caught:
            opener(body)
        self.assertIn(mentions, str(caught.exception))


class JsonRulings(Refusal):
    """RFC 8259, one clause at a time. Refused: what the library's default reading resolves. Accepted: what the grammar allows."""

    def test_the_refused(self):
        cases = {"a name twice (RFC 8259 §4)": (b'{"a": 1, "a": 2}', "occurs twice"), "a name twice, nested in a list of objects": (b'[{"x": {"a": 1, "b": 2, "a": 3}}]', "occurs twice"),
                 "a name twice, differing only in value kind": (b'{"a": null, "a": false}', "occurs twice"),
                 "NaN (§6)": (b'{"n": NaN}', "NaN"), "Infinity": (b'[Infinity]', "Infinity"), "-Infinity": (b'[-Infinity]', "-Infinity"),
                 "a number past a double": (b'[1e999]', "does not fit"), "a negative one": (b'[-1e999]', "does not fit"),
                 "UTF-16 (§8.1)": ('{"a": 1}'.encode("utf-16"), "UTF-8"), "UTF-16 without a mark (NUL bytes are not JSON)": ('{"a": 1}'.encode("utf-16-le"), "not JSON"), "UTF-32": ('{"a": 1}'.encode("utf-32"), "UTF-8"),
                 "an encoded surrogate (not UTF-8, RFC 3629)": (b'["\xed\xa0\x80"]', "UTF-8"), "a byte that is not UTF-8": (b'["\xff"]', "UTF-8"),
                 "nesting past the bound": (b"[" * 65 + b"]" * 65, "levels deep"), "nesting past the interpreter's own limit": (b"[" * 200_000, "levels deep"),
                 "empty": (b"", "not JSON"), "text after the value": (b'{"a": 1} x', "not JSON"), "a trailing comma": (b"[1,]", "not JSON"), "single quotes": (b"{'a': 1}", "not JSON"),
                 "an unterminated string": (b'{"a": "x', "not JSON"), "a leading zero": (b"[01]", "not JSON")}
        for name, (body, why) in cases.items():
            with self.subTest(name):
                self.refused(wire.open_json, body, mentions=why)

    def test_the_accepted(self):
        cases = {"an ordinary document": (b'{"a": [1, 2.5, {"b": null}], "c": "d"}', {"a": [1, 2.5, {"b": None}], "c": "d"}),
                 "a byte order mark, which §8.1 allows a parser to ignore": (b'\xef\xbb\xbf{"a": 1}', {"a": 1}),
                 "a lone surrogate escape: the grammar allows it (§8.2)": (b'["\\ud800"]', ["\ud800"]),
                 "a top-level scalar (§2)": (b"5", 5), "a minus zero": (b"[-0.0]", [-0.0]), "an exponent": (b"[1E3]", [1000.0]),
                 "the same name in two different objects": (b'[{"a": 1}, {"a": 2}]', [{"a": 1}, {"a": 2}]),
                 "names that differ in case": (b'{"a": 1, "A": 2}', {"a": 1, "A": 2}),
                 "an empty name, once": (b'{"": 1}', {"": 1}), "nesting at the bound": (b"[" * 64 + b"]" * 64, None)}
        for name, (body, want) in cases.items():
            with self.subTest(name):
                got = wire.open_json(body)
                if want is not None:
                    self.assertEqual(got, want)


class XmlRulings(Refusal):
    """XML 1.0. expat decides well-formedness; what is refused here is what expat reads that the specification does not, and what the old text path did to the bytes first."""

    DECL = b'<?xml version="1.0" encoding="UTF-8"?>'

    def test_the_refused(self):
        cases = {"a version that is not 1.x (§2.8, expat reads it)": (b'<?xml version="2.0"?><a/>', "version"), "a version of 1": (b'<?xml version="1"?><a/>', "version"),
                 "a version of abc": (b'<?xml version="abc"?><a/>', "version"),
                 "an invalid UTF-8 byte (was replaced by U+FFFD)": (b'<?xml version="1.0"?><a>\xff</a>', "UTF-8"),
                 "a declared Latin-1 document (was read as UTF-8, with replacements)": ('<?xml version="1.0" encoding="ISO-8859-1"?><a>é</a>'.encode("latin-1"), "UTF-8"),
                 "a declaration of another encoding over UTF-8 bytes": (b'<?xml version="1.0" encoding="ISO-8859-1"?><a>caf\xc3\xa9</a>', "encoding"),
                 "a declaration of an encoding nobody knows": (b'<?xml version="1.0" encoding="NOPE-9"?><a/>', "encoding"),
                 "UTF-16": ("<a/>".encode("utf-16"), "UTF-8"),
                 "a DOCTYPE with an internal entity": (b'<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>', "DOCTYPE"), "a DOCTYPE naming an external subset": (b'<!DOCTYPE a SYSTEM "x.dtd"><a/>', "DOCTYPE"),
                 "a parameter entity": (b'<!DOCTYPE a [<!ENTITY % p "x"> %p;]><a/>', "DOCTYPE"),
                 "nesting past the bound": (b"<a>" * 65 + b"</a>" * 65, "levels deep"), "nesting far past the bound": (b"<a>" * 20_000 + b"</a>" * 20_000, "levels deep"),
                 "a duplicate attribute": (b'<a x="1" x="2"/>', "not well-formed"), "mismatched tags": (b"<a><b></a></b>", "not well-formed"), "text after the root": (b"<a/>junk", "not well-formed"),
                 "two roots": (b"<a/><b/>", "not well-formed"), "an undefined entity": (b"<a>&nope;</a>", "not well-formed"), "a control character": (b"<a>\x01</a>", "not well-formed"),
                 "an unbound prefix": (b"<p:a/>", "not well-formed"), "empty": (b"", "not well-formed"), "a declaration that is not first": (b' <?xml version="1.0"?><a/>', "not well-formed"),
                 "a declaration without a version": (b'<?xml encoding="UTF-8"?><a/>', "not well-formed"), "a standalone that is neither yes nor no": (b'<?xml version="1.0" standalone="maybe"?><a/>', "not well-formed"),
                 "a character reference to NUL": (b"<a>&#0;</a>", "not well-formed"), "a lone ampersand": (b"<a>&</a>", "not well-formed")}
        for name, (body, why) in cases.items():
            with self.subTest(name):
                self.refused(wire.open_xml, body, mentions=why)

    def test_the_accepted(self):
        cases = {"an ordinary document": b"<a><b>x</b></a>", "a declaration, UTF-8 in any case": b"<?xml version='1.0' encoding='utf-8'?><a/>", "XML 1.1's version, which is 1.x": b'<?xml version="1.1"?><a/>',
                 "a byte order mark": b"\xef\xbb\xbf<a/>", "non-ASCII text, as UTF-8 bytes": self.DECL + b"<a>caf\xc3\xa9</a>", "a comment and a processing instruction before the root": b"<!-- c --><?pi x?><a/>",
                 "a stylesheet instruction, which starts with the letters xml": b'<?xml-stylesheet href="x"?><a/>', "CDATA": b"<a><![CDATA[<x>]]></a>", "nesting at the bound": b"<a>" * 64 + b"</a>" * 64,
                 "namespaces": b'<m:a xmlns:m="urn:x"><m:b/></m:a>'}
        for name, body in cases.items():
            with self.subTest(name):
                self.assertIsNotNone(wire.open_xml(body))
        self.assertEqual(wire.open_xml(self.DECL + b"<a>caf\xc3\xa9</a>").text, "café", "the bytes are read as UTF-8, not replaced")

    def test_text_is_read_as_text_but_still_checked(self):
        """The decoder's `parse_xml` also takes text a caller already holds (tests, helpers): the same declaration rules apply, and there are no bytes to decode."""
        self.assertEqual(wire.open_xml('<a>café</a>').text, "café")
        self.refused(wire.open_xml, '<?xml version="2.0"?><a/>', mentions="version")


class CsvRulings(Refusal):
    """RFC 4180, one clause at a time."""

    def test_the_refused(self):
        cases = {"a quoted field never closed, in the header (§2.7)": (b'a,"b\n1,2\n', "not closed"), "a quoted field never closed, in the first column": (b'a,b\n"1,2\n3,4\n', "not closed"),
                 "a quoted field never closed, in the last cell of the file": (b'a,b\n1,"2', "not closed"), "a quote that closes and is followed by text (§2.6)": (b'a,b\n"x"y,2\n', "after a closing quote"),
                 "...followed by a space": (b'a,b\n"x" ,2\n', "after a closing quote"), "a quote inside an unquoted field (§2.5)": (b'a,b\nx"y,2\n', "unquoted field"),
                 "a quote at the end of an unquoted field": (b'a,b\nxy",2\n', "unquoted field"), "a carriage return that is not half of CRLF (§2.1)": (b"a,b\r1,2\n", "carriage return"),
                 "...inside an unquoted field": (b"a,b\n1\r2,3\n", "carriage return"), "bytes that are not UTF-8": (b"a,b\n\xff,2\n", "UTF-8"),
                 "UTF-16": ("a,b\n1,2\n".encode("utf-16"), "UTF-8"), "a cell past the limit": (b"a\n" + b"x" * (wire.CELL_LIMIT + 1) + b"\n", "characters")}
        for name, (body, why) in cases.items():
            with self.subTest(name):
                self.refused(wire.open_csv, body, mentions=why)

    def test_the_accepted(self):
        cases = {"an ordinary document": (b"a,b\n1,2\n", [["a", "b"], ["1", "2"]]), "CRLF line ends": (b"a,b\r\n1,2\r\n", [["a", "b"], ["1", "2"]]),
                 "no line end on the last line": (b"a,b\n1,2", [["a", "b"], ["1", "2"]]), "a quoted field holding a line end (§2.6)": (b'a,b\n"x\ny",2\n', [["a", "b"], ["x\ny", "2"]]),
                 "a quoted field holding CRLF": (b'a\n"x\r\ny"\n', [["a"], ["x\r\ny"]]), "a quoted field holding a comma": (b'a,b\n"x,y",2\n', [["a", "b"], ["x,y", "2"]]),
                 "a doubled quote (§2.7)": (b'a\n"x""y"\n', [["a"], ['x"y']]), "an empty quoted field": (b'a\n""\n', [["a"], [""]]),
                 "a trailing comma: an empty last cell": (b"a,b\n1,\n", [["a", "b"], ["1", ""]]), "a blank line: no record, as the csv module reads it": (b"a\n\nb\n", [["a"], [], ["b"]]),
                 "empty": (b"", []), "non-ASCII text": ("a\ncafé\n".encode(), [["a"], ["café"]]), "a cell at the limit": (b"a\n" + b"x" * wire.CELL_LIMIT + b"\n", None),
                 "a short row and a long one, which the decoder's policy reads and this layer does not judge": (b"a,b\n1\n1,2,3\n", [["a", "b"], ["1"], ["1", "2", "3"]]),
                 "a tab and other control characters inside a cell": (b"a\nx\ty\x01\n", [["a"], ["x\ty\x01"]])}
        for name, (body, want) in cases.items():
            with self.subTest(name):
                got = wire.open_csv(body)
                if want is not None:
                    self.assertEqual(got, want)

    def test_the_error_names_the_line_a_reader_can_find(self):
        with self.assertRaises(wire.Malformed) as caught:
            wire.open_csv(b'a,b\n1,2\n"3,4\n5,6\n')
        self.assertIn("line 3", str(caught.exception))
        with self.assertRaises(wire.Malformed) as caught:
            wire.open_csv(b'a,b\n"x\ny",2\nbad"quote,1\n')   # a multi-line quoted field before it: the line count follows the file's lines
        self.assertIn("line 4", str(caught.exception))


# --------------------------------------------------------------------------------------------------------------------------------------- the corruption family, through the real consumers
def doaj_client(body: bytes) -> Client:
    t = FakeTransport()
    t.add("GET", registries.DOAJ_CSV, 200, body, headers={"Content-Type": "text/csv"})
    return Client(broker=Broker({"doaj": RatePolicy(per_second=100000)}), transport=t, sleep=lambda s: None)


def load_doaj(body: bytes | str):
    """(identities, error) of the real DOAJ loader over these bytes."""
    try:
        return [r["identity"] for r in registries.doaj_journals(doaj_client(body if isinstance(body, bytes) else body.encode()))], None
    except Exception as e:   # the test judges what comes out: a PayloadError is the channel, anything else is a failure of it
        return None, e


HEAD = "Journal title,Journal ISSN (print version),Publisher,Journal license\n"
THREE = HEAD + "First,9999-9991,P,CC-BY\nSecond,9999-9983,Q,CC-BY\nThird,9999-9975,R,CC-BY\n"
DUMP = {"Journal title": ("First", "Second", "Third"), "Journal ISSN (print version)": ("9999-9991", "9999-9983", "9999-9975"), "Publisher": ("P", "Q", "R"), "Journal license": ("CC-BY",) * 3}


def quoted_dump() -> str:
    """The same journals the way a dump that quotes every cell writes them: the document whose framing is all quotes."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerow(DUMP)
    writer.writerows(zip(*DUMP.values()))
    return out.getvalue()


class ByteCorruption(unittest.TestCase):
    """For every opener in the inventory, serialized bytes are edited — not rows generated by a writer — and the real consumer must refuse each with the one channel, while the
    uncorrupted control beside it is read."""

    def test_csv_every_corruption_of_the_dump_is_a_payload_error_and_never_a_load(self):
        self.assertEqual(load_doaj(THREE), (["issn:9999-9991", "issn:9999-9983", "issn:9999-9975"], None), "control")
        self.assertEqual(load_doaj(quoted_dump())[1], None, "control: the all-quoted form")
        corrupt = {
            "an unterminated quote in the header": THREE.replace("Journal ISSN", '"Journal ISSN', 1),
            "an unterminated quote in the first title": THREE.replace("First", '"First', 1),
            "an unterminated quote in the first publisher": THREE.replace(",P,", ',"P,', 1),
            "an unterminated quote in the last cell of the file": THREE.rstrip("\n").replace("R,CC-BY", 'R,"CC-BY'),
            "text after a closing quote": THREE.replace("First", '"First"junk', 1),
            "a quote in the middle of an unquoted cell": THREE.replace("Second", 'Sec"ond', 1),
            "a bare carriage return for a line end": THREE.replace("\n", "\r", 1),
            "a byte that is not UTF-8": None,
            "a column the schema reads, named twice": HEAD.replace("Publisher", "Journal title") + "First,9999-9991,P,CC-BY\n",
            "the licence column named twice": HEAD.replace("Publisher", "Journal license") + "First,9999-9991,P,CC-BY\n",
            "the title column named twice and nothing else": "Journal title,Journal title\nFirst,\nSecond,\n",
        }
        for name, text in corrupt.items():
            body = THREE.encode().replace(b"First", b"Fir\xffst") if text is None else text.encode()
            identities, error = load_doaj(body)
            with self.subTest(name):
                self.assertIsInstance(error, PayloadError, f"loaded {identities}")
                self.assertIsNone(identities)

    def test_csv_a_column_the_schema_does_not_read_may_be_named_twice(self):
        """The ruling's other half: a repeated column nothing reads cannot change a decision, so the dump loads (the later cell is the one `raw` keeps, as the csv module always did)."""
        text = HEAD.replace("Publisher", "Notes") + "First,9999-9991,x,CC-BY\n"
        self.assertEqual(load_doaj(text.replace("Journal license", "Notes")), (["issn:9999-9991"], None))

    def test_csv_every_single_quote_removed_from_an_all_quoted_dump_is_refused(self):
        """The framing of an all-quoted dump is its quotes: deleting any one of them at any offset must break it, and nothing may load."""
        text, loaded = quoted_dump(), 0
        offsets = [i for i, ch in enumerate(text) if ch == '"']
        self.assertEqual(len(offsets), 32, "four rows of four cells, two quotes each")
        for i in offsets:
            identities, error = load_doaj((text[:i] + text[i + 1:]).encode())
            loaded += error is None
            with self.subTest(removed_quote_at=i):
                self.assertIsInstance(error, PayloadError, f"loaded {identities}")
        self.assertEqual(loaded, 0)

    def test_csv_every_quote_inserted_into_a_dump_is_refused_or_read_as_the_text_it_is(self):
        """Inserting a quote at any offset of an all-quoted dump either breaks the framing (refused) or, only where it doubles an existing quote, is RFC 4180's escape and reads as a cell
        with a quote in it: never as a different row count, never as a load that lost a row."""
        text = quoted_dump()
        for i in range(len(text) + 1):
            mutated = text[:i] + '"' + text[i:]
            identities, error = load_doaj(mutated.encode())
            with self.subTest(inserted_at=i):
                if error is not None:
                    self.assertIsInstance(error, PayloadError)
                else:
                    self.assertEqual(len(identities), 3, "an escaped quote changed a cell, not the rows")

    def test_csv_a_truncation_never_alters_a_cell_it_keeps(self):
        """Cut a valid dump at EVERY offset. What loads is the original with its tail missing at a cell boundary — whole rows, and at most one short row — and never a cell that is not the original's
        (an unterminated quote is refused). A cut at a record or cell boundary is a well-formed shorter document: CSV has no end marker to say otherwise."""
        whole = wire.open_csv(quoted_dump())
        text = quoted_dump().encode()
        refused = shorter = 0
        for k in range(len(text)):
            try:
                got = wire.open_csv(text[:k])
            except wire.Malformed:
                refused += 1
                continue
            shorter += 1
            self.assertLessEqual(len(got), len(whole))
            for j, row in enumerate(got):
                kept = row[:-1] if j == len(got) - 1 else row   # the last cell of the cut itself may be empty: a cut right after a comma
                self.assertEqual(kept, whole[j][:len(kept)], f"cut at {k}: row {j} is not a prefix of the original")
                if kept is not row:
                    self.assertIn(row[-1], ("", whole[j][len(row) - 1] if len(row) <= len(whole[j]) else ""), f"cut at {k}: the last cell is neither empty nor the original's")
        self.assertGreater(refused, shorter, "most cuts fall inside a quoted cell")

    def test_json_every_corruption_is_a_payload_error_from_the_decoder_and_has_no_count(self):
        spec = S.obj({"results": S.members(S.obj({"id": S.key(), "n": S.any_()})), "total": S.soft(S.whole())})
        good = b'{"results": [{"id": "a", "n": 1}, {"id": "b", "n": 2}], "total": 2}'
        self.assertEqual(S.decode("t", spec, Response(200, {}, good, "u"))["total"], 2, "control")
        self.assertEqual(_count_of(Response(200, {}, good, "u")), 2, "control")
        corrupt = {"a name twice in the answer": b'{"results": [{"id": "a"}], "results": [], "total": 0}', "a name twice in a member": b'{"results": [{"id": "a", "id": "b"}], "total": 1}',
                   "a name twice in a metadata object": b'{"results": [{"id": "a", "n": {"k": 1, "k": 2}}], "total": 1}',
                   "NaN as the total": b'{"results": [{"id": "a"}], "total": NaN}', "Infinity in a member": b'{"results": [{"id": "a", "n": Infinity}], "total": 1}',
                   "an overflowing number in a member": b'{"results": [{"id": "a", "n": 1e999}], "total": 1}', "UTF-16": json.dumps(json.loads(good)).encode("utf-16"),
                   "an invalid byte in a string": good.replace(b'"a"', b'"\xff"'), "an encoded surrogate": good.replace(b'"a"', b'"\xed\xa0\x80"'),
                   "the document cut short": good[:-1], "text after the document": good + b" x", "nesting past the bound": b'{"results": ' + b"[" * 70 + b"]" * 70 + b"}"}
        for name, body in corrupt.items():
            with self.subTest(name):
                with self.assertRaises(PayloadError):
                    S.decode("t", spec, Response(200, {}, body, "u"))
                self.assertIsNone(_count_of(Response(200, {}, body, "u")), "an answer the decoder refuses has no count either")

    def test_json_every_proper_prefix_of_a_document_is_refused(self):
        document = json.dumps({"results": [{"id": "a", "n": [1, 2.5, None, True]}, {"id": "b", "n": {"k": "v"}}], "total": 2}).encode()
        wire.open_json(document)
        for k in range(len(document)):
            with self.subTest(cut_at=k), self.assertRaises(wire.Malformed):
                wire.open_json(document[:k])

    def test_xml_every_corruption_is_a_payload_error_from_parse_xml(self):
        good = b'<?xml version="1.0" encoding="UTF-8"?><m:Structure xmlns:m="urn:x"><m:Dataflow id="F" agencyID="A"><m:Name>caf\xc3\xa9</m:Name></m:Dataflow></m:Structure>'
        self.assertEqual(S.parse_xml(Response(200, {}, good, "u"), "Structure").tag.rsplit("}", 1)[-1], "Structure", "control")
        corrupt = {"a version of 2.0": good.replace(b'"1.0"', b'"2.0"'), "an invalid byte in the text": good.replace(b"caf\xc3\xa9", b"caf\xff"), "a declared encoding that is not the bytes'": good.replace(b"UTF-8", b"ISO-8859-1"),
                   "an encoding nobody knows": good.replace(b"UTF-8", b"NOPE-9"), "a DOCTYPE": good.replace(b"<m:Structure", b'<!DOCTYPE m:Structure [<!ENTITY e "x">]><m:Structure', 1),
                   "a duplicate attribute": good.replace(b'id="F"', b'id="F" id="G"'), "a mismatched tag": good.replace(b"</m:Name>", b"</m:Nam>"), "text after the root": good + b"junk",
                   "UTF-16": good.decode().replace("UTF-8", "UTF-16").encode("utf-16"), "nesting past the bound": b"<Structure>" + b"<a>" * 70 + b"</a>" * 70 + b"</Structure>"}
        for name, body in corrupt.items():
            with self.subTest(name), self.assertRaises(PayloadError):
                S.parse_xml(Response(200, {}, body, "u"), "Structure")

    def test_xml_every_proper_prefix_of_a_document_is_refused(self):
        document = b'<?xml version="1.0"?><m:Structure xmlns:m="urn:x"><m:Dataflow id="F"><m:Name>x</m:Name></m:Dataflow></m:Structure>'
        wire.open_xml(document)
        for k in range(len(document)):
            with self.subTest(cut_at=k), self.assertRaises(wire.Malformed):
                wire.open_xml(document[:k])

    def snapshot(self, lines: list[str], *, gz: bool = True):
        with tempfile.TemporaryDirectory() as tmp:
            part = Path(tmp) / "updated_date=2026-09-01" / ("part_000.gz" if gz else "part_000.jsonl")
            part.parent.mkdir()
            opener = gzip.open if gz else open
            with opener(part, "wt", encoding="utf-8") as f:
                f.write("".join(line + "\n" for line in lines))
            try:
                return [r["identity"] for r in openalex_snapshot.read_snapshot(Path(tmp))], None
            except Exception as e:
                return None, e

    def test_the_snapshot_reader_every_corruption_of_a_line_fails_the_load_naming_it(self):
        ok = ['{"id": "https://openalex.org/S1", "issn_l": "9999-9991", "issn": ["9999-9991"], "display_name": "J", "type": "journal"}',
              '{"id": "https://openalex.org/S2", "issn_l": "9999-9983", "issn": ["9999-9983"], "display_name": "K", "type": "journal"}']
        self.assertEqual(self.snapshot(ok), (["issn:9999-9991", "issn:9999-9983"], None), "control")
        self.assertEqual(self.snapshot(ok, gz=False), (["issn:9999-9991", "issn:9999-9983"], None), "control: plain JSON lines")
        corrupt = {"a line that is not JSON": "not json", "a line cut short": ok[1][:-9], "a name twice": ok[1].replace('"display_name": "K"', '"display_name": "K", "display_name": "L"'),
                   "NaN": ok[1].replace('"K"', "NaN"), "an overflowing number": ok[1].replace('"K"', "1e999"), "text after the object": ok[1] + " x"}
        for name, line in corrupt.items():
            identities, error = self.snapshot([ok[0], line, ok[0].replace("S1", "S3").replace("9991", "9975")])
            with self.subTest(name):
                self.assertIsInstance(error, PayloadError, f"loaded {identities}")
                self.assertIn("line 2", str(error))
        for line in ("[]", '"x"', "5", "null"):   # JSON that is not a source object is not malformed: record_from has no record to make of it, as it always had none
            self.assertEqual(self.snapshot([ok[0], line, ok[1]]), (["issn:9999-9991", "issn:9999-9983"], None), line)

    def test_every_opener_of_the_inventory_is_in_this_family(self):
        """The family's reach, derived from the inventory (not from this file's own list): each consumer of an opener has a test above that corrupts its bytes."""
        covered = {"open_json": {"test_json_every_corruption_is_a_payload_error_from_the_decoder_and_has_no_count", "test_the_snapshot_reader_every_corruption_of_a_line_fails_the_load_naming_it"},
                   "open_xml": {"test_xml_every_corruption_is_a_payload_error_from_parse_xml"}, "open_csv": {"test_csv_every_corruption_of_the_dump_is_a_payload_error_and_never_a_load"}}
        here = {name for name in dir(ByteCorruption) if name.startswith("test_")}
        for opener, tests in covered.items():
            self.assertTrue(tests <= here, opener)
        self.assertEqual({o for o, _ in CONSUMERS.values()}, set(covered))


# --------------------------------------------------------------------------------------------------------------------------------------- the CSV opener against the csv module
class Fake:
    """A database that records what it is asked (the index-zero probe's, tests/test_astra_13a.py)."""
    def __init__(self):
        self.statements, self.commits, self.rollbacks = [], 0, 0

    def cursor(self):
        db = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, args=None):
                db.statements.append((sql, args))

            def fetchone(self):
                return None   # no stored record: every journal is new
        return Cursor()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class AgainstTheCsvModule(unittest.TestCase):
    ALPHABET = ("a", "b", " ", "x", "é", '"', ",", "\n", "\r\n", '""', ",,", '","')

    def strict(self, text: str):
        try:
            return list(csv.reader(io.StringIO(text, newline="\n"), strict=True))
        except csv.Error:
            return None

    def test_on_thousands_of_texts_it_reads_what_strict_reads_and_refuses_more_only_where_the_rfc_does(self):
        rng = random.Random(13)
        both = refused_more = agreed_refusal = 0
        for _ in range(30_000):
            text = "".join(rng.choice(self.ALPHABET) for _ in range(rng.randint(0, 16)))
            reference = self.strict(text)
            try:
                mine = wire.open_csv(text)
            except wire.Malformed as e:
                if reference is None:
                    agreed_refusal += 1
                else:
                    refused_more += 1
                    self.assertIn("unquoted field", str(e), f"refused beyond strict for another reason: {text!r}")
                continue
            self.assertIsNotNone(reference, f"read what the strict reader refuses: {text!r}")
            self.assertEqual(mine, reference, repr(text))
            both += 1
        self.assertGreater(both, 3000)
        self.assertGreater(agreed_refusal, 3000)
        self.assertGreater(refused_more, 100)

    def test_it_reads_the_documents_a_csv_writer_writes(self):
        rng = random.Random(14)
        cells = ["", "plain", "with,comma", 'with "quote"', "multi\nline", "multi\r\nline", " spaced ", "é", "x" * 1000, "a\tb"]
        for quoting in (csv.QUOTE_MINIMAL, csv.QUOTE_ALL, csv.QUOTE_NONNUMERIC):
            for _ in range(300):
                rows = [[rng.choice(cells) for _ in range(rng.randint(1, 5))] for _ in range(rng.randint(1, 6))]
                out = io.StringIO()
                csv.writer(out, quoting=quoting, lineterminator=rng.choice(["\n", "\r\n"])).writerows(rows)
                self.assertEqual(wire.open_csv(out.getvalue()), rows, repr(out.getvalue()))


# --------------------------------------------------------------------------------------------------------------------------------------- the HTTP header openers
class HeaderOpeners(unittest.TestCase):
    """The openers that are not JSON, XML or CSV: the headers whose text the gateway decides from. Inventory, with the ruling for each:

      Link (RFC 8288 on RFC 9110's list syntax)   adapters/base.py `parse_links`/`next_link`: strict since 2b-repair-12 — a header that does not read through to its last character is
                                                  `LinkSyntax`, and the answer's next link is then neither a continuation nor an end; pinned by tests/test_link_header.py and the oracle's vectors
      Retry-After (RFC 9110 §10.2.3)              `Response.retry_after_seconds`: an HTTP-date or `delay-seconds` (ASCII digits). Before 2b-repair-13c it was `float()`, which reads `inf`
                                                  (a breaker open for ever), `nan`, `-5`, `1e3`, `1_0` and Arabic-Indic digits: tested here
      Location (redirects)                        `redirect_target`: urljoin, then scheme, downgrade and global-address checks; anything that does not parse is refused
      Content-Type / first bytes of a body        `check()`: a substring/prefix test that can only REFUSE (an HTML page wearing a success status); a heuristic by design, not an opener
      Content-Length, chunking, compression       the transport's (urllib/http.client): a short body is an error Response
    """

    def seconds(self, value):
        return Response(429, {"retry-after": value}, b"", "u").retry_after_seconds()

    def test_retry_after_is_delay_seconds_or_an_http_date_and_nothing_else(self):
        for value, want in (("30", 30.0), (" 30 ", 30.0), ("0", 0.0), ("3600", 3600.0), ("0030", 30.0)):
            self.assertEqual(self.seconds(value), want, value)
        for value in ("inf", "nan", "-5", "+5", "1e3", "1_0", "١٢", "5.5", ".5", "5 s", "abc", "", " ", "9" * 5000, "9" * 400, "infinity", "0x10"):
            with self.subTest(value=value[:12]):
                self.assertIsNone(self.seconds(value))
        self.assertIsNone(Response(429, {}, b"", "u").retry_after_seconds())
        later = self.seconds("Wed, 21 Oct 2099 07:28:00 GMT")
        self.assertGreater(later, 10 ** 9)

    def test_a_retry_after_that_is_not_a_delay_opens_no_breaker_of_its_own(self):
        """The consequence the strictness is for: `Retry-After: inf` on a 429 used to open the source's breaker for ever; it is no delay now, and the broker's own policy applies."""
        broker = Broker({"src": RatePolicy(per_second=100)})
        broker.record("src", 429, retry_after=Response(429, {"retry-after": "inf"}, b"", "u").retry_after_seconds())
        self.assertFalse(broker.breaker_open("src"), "one 429 with a Retry-After that is no delay is one limit error, not a breaker")
        broker.record("src", 429, retry_after=Response(429, {"retry-after": "75"}, b"", "u").retry_after_seconds())
        self.assertTrue(broker.breaker_open("src"))


class AgainstTheLibraries(unittest.TestCase):
    """What the openers do with a VALID document is what the libraries did: the strictness is all on the other side of the line. Generated documents, written by the libraries' own writers (so
    well-formed by construction), are read by the opener and by the library at its default, and must come out the same."""

    @staticmethod
    def structure(rng: random.Random, depth: int = 0):
        kinds = ["int", "float", "str", "bool", "null"] + (["list", "dict"] * 2 if depth < 6 else [])
        kind = rng.choice(kinds)
        if kind == "int":
            return rng.choice([0, 1, -1, 2 ** 63, -(2 ** 70), 10 ** 400, rng.randint(-10 ** 9, 10 ** 9)])
        if kind == "float":
            return rng.choice([0.0, -0.0, 1.5, 1e308, 5e-324, 2.2250738585072014e-308, 1e-7, 123456.789, rng.random() * 10 ** rng.randint(-20, 20)])
        if kind == "str":
            return "".join(rng.choice(["a", "é", "日", "😀", " ", '"', "\\", "\n", "\t", "/", "\u0001", "e999", "NaN"]) for _ in range(rng.randint(0, 8)))
        if kind == "bool":
            return rng.random() < .5
        if kind == "null":
            return None
        if kind == "list":
            return [AgainstTheLibraries.structure(rng, depth + 1) for _ in range(rng.randint(0, 4))]
        return {f"k{rng.randint(0, 99)}é{i}": AgainstTheLibraries.structure(rng, depth + 1) for i in range(rng.randint(0, 4))}

    def test_json_a_valid_document_reads_as_json_loads_reads_it(self):
        rng = random.Random(15)
        for n in range(2000):
            value = {"root": self.structure(rng)} if n % 2 else self.structure(rng)
            body = json.dumps(value, ensure_ascii=rng.random() < .5, indent=rng.choice([None, 1, 2]), sort_keys=rng.random() < .5, separators=rng.choice([None, (",", ":")])).encode("utf-8")
            if rng.random() < .1:
                body = b"\xef\xbb\xbf" + body
            mine, theirs = wire.open_json(body), json.loads(body.lstrip(b"\xef\xbb\xbf"))
            self.assertEqual(repr(mine), repr(theirs), body[:80])   # repr tells 1 from 1.0 from True and -0.0 from 0.0

    def test_json_the_integers_and_floats_at_the_edges_read_as_the_library_reads_them(self):
        for text in ("0", "-0", "1E3", "1e-7", "5e-324", "1.7976931348623157e308", "-1.7976931348623157e308", "123456789012345678901234567890", "-1" + "0" * 4000, "0.1", "100000000000000000000.5", "1e308"):
            self.assertEqual(repr(wire.open_json(f"[{text}]")), repr(json.loads(f"[{text}]")), text)

    def test_xml_a_valid_document_reads_as_elementtree_reads_it(self):
        import xml.etree.ElementTree as ET
        from tests.oracle import xml_ops
        docs = [xml_ops.structure_message("BIS", xml_ops.BIS_FLOWS), xml_ops.structure_message("ECB", xml_ops.ECB_FLOWS, dimensions=False), xml_ops.bis_data_message((("US", 4), ("XM", 2)))]
        rng = random.Random(16)
        alphabet = ["a", "é", "日", "😀", " ", "&amp;", "&lt;", "&#233;", "<![CDATA[x<y]]>", "\n"]
        for _ in range(300):
            def element(depth=0):
                tag = rng.choice(["a", "m:b", "c-d", "é"]).replace("m:b", "m:b") if depth else "m:root"
                attributes = "".join(f' x{i}="{"".join(rng.choice(["v", "é", "&amp;", "&quot;"]) for _ in range(3))}"' for i in range(rng.randint(0, 3)))
                inside = "".join(rng.choice(alphabet) if rng.random() < .5 or depth > 3 else element(depth + 1) for _ in range(rng.randint(0, 4)))
                return f"<{tag}{attributes}>{inside}</{tag}>" if depth else f'<m:root xmlns:m="urn:x"{attributes}>{inside}</m:root>'
            docs.append(rng.choice(["", '<?xml version="1.0" encoding="UTF-8"?>']) + rng.choice(["", "<!-- c -->"]) + element())
        for doc in docs:
            with self.subTest(doc=doc[:60]):
                self.assertEqual(ET.tostring(wire.open_xml(doc.encode("utf-8")), encoding="unicode"), ET.tostring(ET.fromstring(doc), encoding="unicode"))


if __name__ == "__main__":
    unittest.main()
