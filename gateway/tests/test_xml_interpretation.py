"""Task 2b-repair-14 (Astra F2 / R13C-3): an XML field has a lossless meaning, and a name is an expanded name.

Astra found two well-formed documents the supported contract does not describe, both read as a complete answer:

  * `<a>x<b>y</b></a>` was `x` and `<a><b>hidden</b></a>` was nothing: the scalar reader refused a child's TAIL, not a child. In the BIS catalogue `Policy <b>rates</b>` became the label
    `Policy `, the lane complete, count three.
  * the SDMX namespace URIs replaced by `urn:unrelated:` returned the same complete catalogue: every element was matched by its local name, the URI thrown away.

core/schema.py now holds both rules in the decoder (its module docstring), core/sdmx.py names the vocabulary: SDMX-ML 2.1, with the four elements the standard itself declares unqualified.
What is covered here: the rules on small documents (ScalarText, ExpandedNames); the same two defects through the real BIS and ECB routes, beside controls — the oracle's own messages, and the same
messages with their prefixes renamed, which are the same names (SdmxVocabulary); and the list of unqualified forms, held (UnqualifiedForms). What it does not claim: that every SDMX-ML document
a provider could send is in the vocabulary — SDMX-ML 2.0 and 3.0 are outside it, and a message that is outside it is an unreadable answer, never a shorter one (STATION-CONTRACT) — nor that an
element the schemas do not read is valid; there is no XSD engine, and nothing is validated that no field reads.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

from research_gateway.core import schema as S
from research_gateway.core import sdmx
from research_gateway.core.payload import PayloadError
from tests import invariant_ops
from tests.oracle import xml_ops
from tests.test_invariants import run

NAME = S.obj({"Name": S.own(S.obj({"#": S.text()}))})


def names(text: str, spec: S.Spec = NAME, read: str = "#") -> list:
    return [n[read] for n in S.decode("t", spec, S.parse_xml(text, "a"))["Name"]]


class ScalarText(unittest.TestCase):
    """`"#"` is the text of an element that holds no child element. Anything else is not a scalar and is refused, wherever the child's text or tail stands."""

    def test_a_scalar_element_that_holds_a_child_is_refused_in_every_position_of_its_text(self):
        for label, text in {"text, a child, a tail": "<a><Name>x<b/>y</Name></a>", "text, then a child with text": "<a><Name>x<b>y</b></Name></a>",
                            "only a child with text": "<a><Name><b>hidden</b></Name></a>", "text, then a nested child": "<a><Name>x<b><c>y</c></b></Name></a>",
                            "only an empty child": "<a><Name><b/></Name></a>", "a child between blanks": "<a><Name>  <b/>  </Name></a>", "text, then an empty child": "<a><Name>x<b/></Name></a>",
                            "a child, then a tail": "<a><Name><b/>tail</Name></a>", "a child with attributes only": '<a><Name><b k="v"/></Name></a>',
                            "a foreign child": '<a><Name xmlns:z="urn:z"><z:b>y</z:b></Name></a>'}.items():
            with self.subTest(label):
                with self.assertRaises(PayloadError) as why:
                    names(text)
                self.assertIn("holds child elements", str(why.exception))

    def test_control_the_scalar_forms_that_hold_no_child_are_read_whole(self):
        for text, want in (("<a><Name>First</Name></a>", ["First"]), ("<a><Name/></a>", [None]), ("<a><Name></Name></a>", [None]), ("<a><Name>  </Name></a>", ["  "]),
                           ("<a><Name>a &amp; b &lt; c &#233;</Name></a>", ["a & b < c é"]), ("<a><Name><![CDATA[x<y]]></Name></a>", ["x<y"]),
                           ("<a><Name>First<!-- a comment is not content --> Second</Name></a>", ["First Second"]), ('<a><Name k="v">First</Name></a>', ["First"]),
                           ("<a><Name><?pi x?>First</Name></a>", ["First"])):
            with self.subTest(text=text):
                self.assertEqual(names(text), want)

    def test_the_refusal_is_the_one_channel_and_costs_what_the_schema_says_it_costs(self):
        """It is the PayloadError of the nearest boundary: a listing's one bad name makes an `own` list unreadable (a catalogue is never a shorter one); under `members` it costs one member."""
        spec = S.obj({"Item": S.members(S.obj({"Name": S.own(S.obj({"#": S.text()}))}))})
        got = S.decode("t", spec, S.parse_xml("<a><Item><Name>one</Name></Item><Item><Name>x<b>y</b></Name></Item><Item><Name>three</Name></Item></a>", "a"))
        self.assertEqual(got["Item"].each(lambda m: m["Name"][0]["#"]), ["one", None, "three"])

    def test_a_field_that_means_only_the_elements_own_leading_text_says_so_by_name(self):
        """`"#own"`: the text before the first child, the children being no part of what the field says (a header entry kept as its text or its attributes). It is declared; it is not what `"#"` does."""
        own = S.obj({"Name": S.own(S.obj({"#own": S.text()}))})
        for text, want in (("<a><Name>x<b>y</b>z</Name></a>", ["x"]), ("<a><Name><b>y</b></Name></a>", [None]), ("<a><Name>x</Name></a>", ["x"]), ("<a><Name/></a>", [None])):
            with self.subTest(text=text):
                self.assertEqual(names(text, own, "#own"), want)
        with self.assertRaises(PayloadError):
            names("<a><Name>x<b>y</b>z</Name></a>")


class ExpandedNames(unittest.TestCase):
    """An element is its namespace URI and its local name. A field names the namespaces it reads from; the default is none (unqualified)."""

    ITEM = S.obj({"Item": S.in_ns(S.own(S.obj({"@id": S.text()})), "urn:a")})

    def ids(self, text: str, spec: S.Spec | None = None, roots=("r",), namespaces=(S.UNQUALIFIED,)) -> list:
        return [i["@id"] for i in S.decode("t", spec or self.ITEM, S.parse_xml(text, *roots, namespaces=namespaces))["Item"]]

    def test_the_approved_uri_passes_under_any_prefix_or_as_the_default_namespace(self):
        for label, text in {"a prefix": '<r xmlns:p="urn:a"><p:Item id="1"/></r>', "another prefix": '<r xmlns:q="urn:a"><q:Item id="1"/></r>',
                            "the default namespace": '<r><Item xmlns="urn:a" id="1"/></r>', "the prefix declared on the element": '<r><z:Item xmlns:z="urn:a" id="1"/></r>',
                            "declared far above": '<r xmlns:p="urn:a"><w><p:Item id="1"/></w><p:Item id="1"/></r>'}.items():
            with self.subTest(label):
                self.assertEqual(self.ids(text)[0], "1")

    def test_a_foreign_uri_is_refused_and_not_read_as_absent(self):
        for label, text in {"another URI": '<r xmlns:p="urn:b"><p:Item id="1"/></r>', "a URI that differs by case": '<r xmlns:p="URN:A"><p:Item id="1"/></r>',
                            "a URI that differs by a slash": '<r xmlns:p="urn:a/"><p:Item id="1"/></r>', "no namespace where one is declared": '<r><Item id="1"/></r>',
                            "the right one beside a foreign one": '<r xmlns:p="urn:a" xmlns:q="urn:b"><p:Item id="1"/><q:Item id="2"/></r>',
                            "the default namespace of another vocabulary": '<r><Item xmlns="urn:b" id="1"/></r>'}.items():
            with self.subTest(label):
                with self.assertRaises(PayloadError) as why:
                    self.ids(text)
                self.assertIn("another vocabulary", str(why.exception))

    def test_an_element_of_another_local_name_is_not_read_whatever_its_namespace(self):
        """Not validating what nothing reads: an extension element in a foreign namespace is not this decoder's concern, and the field it is not is simply not there."""
        self.assertEqual(self.ids('<r xmlns:q="urn:b"><q:Other id="2"/><Other/></r>'), [])

    def test_the_default_is_no_namespace_and_a_qualified_element_is_then_refused(self):
        plain = S.obj({"Item": S.own(S.obj({"@id": S.text()}))})
        self.assertEqual(self.ids('<r><Item id="1"/></r>', plain), ["1"])
        with self.assertRaises(PayloadError):
            self.ids('<r xmlns:p="urn:a"><p:Item id="1"/></r>', plain)

    def test_descendants_and_all_children_are_held_to_the_same_rule(self):
        deep = S.obj({"**Item": S.in_ns(S.own(S.obj({"@id": S.text()})), "urn:a")})
        self.assertEqual([i["@id"] for i in S.decode("t", deep, S.parse_xml('<r xmlns:p="urn:a"><w><x><p:Item id="1"/></x></w></r>', "r"))["**Item"]], ["1"])
        with self.assertRaises(PayloadError):
            S.decode("t", deep, S.parse_xml('<r xmlns:p="urn:a" xmlns:q="urn:b"><w><x><q:Item id="1"/></x></w></r>', "r"))
        every = S.obj({"*": S.in_ns(S.own(S.obj({"%": S.text()})), "urn:a")})
        self.assertEqual([c["%"] for c in S.decode("t", every, S.parse_xml('<r xmlns:p="urn:a"><p:one/><p:two/></r>', "r"))["*"]], ["one", "two"])
        with self.assertRaises(PayloadError):
            S.decode("t", every, S.parse_xml('<r xmlns:p="urn:a" xmlns:q="urn:b"><p:one/><q:two/></r>', "r"))

    def test_the_root_is_held_to_it_too(self):
        self.assertEqual(self.ids('<p:r xmlns:p="urn:r"><i:Item xmlns:i="urn:a" id="1"/></p:r>', roots=("r",), namespaces=("urn:r",)), ["1"])
        for label, text, namespaces in (("a foreign root", '<p:r xmlns:p="urn:other"/>', ("urn:r",)), ("an unqualified root where one is declared", "<r/>", ("urn:r",)),
                                        ("a qualified root where none is", '<p:r xmlns:p="urn:r"/>', (S.UNQUALIFIED,)), ("the right namespace, another name", '<p:s xmlns:p="urn:r"/>', ("urn:r",))):
            with self.subTest(label), self.assertRaises(PayloadError):
                S.parse_xml(text, "r", namespaces=namespaces)
        self.assertEqual(S.parse_xml('<q:r xmlns:q="urn:r"/>', "r", namespaces=("urn:x", "urn:r")).tag, "{urn:r}r")

    def test_a_declaration_names_at_least_one_uri_and_each_is_text(self):
        for bad in ((), (None,), (5,), (S.obj({}),)):
            with self.subTest(bad=repr(bad)[:20]), self.assertRaises(ValueError):
                S.in_ns(S.text(), *bad)

    def test_an_attribute_is_named_without_a_namespace_and_a_prefixed_one_is_another_attribute(self):
        spec = S.obj({"Item": S.in_ns(S.own(S.obj({"@id": S.text()})), "urn:a")})
        self.assertEqual(self.ids('<r xmlns:p="urn:a"><p:Item p:id="9" id="1"/></r>', spec), ["1"])
        self.assertEqual(self.ids('<r xmlns:p="urn:a"><p:Item p:id="9"/></r>', spec), [None])


MESSAGE = "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/"
CASES = xml_ops.build(invariant_ops)


def lane_of(case: str, text: str) -> tuple[dict, dict]:
    op = CASES[case]["op"]
    return run(replace(op, routes=tuple(replace(r, body=text, corrupt=False) for r in op.routes)), None)


class SdmxVocabulary(unittest.TestCase):
    """The same defects through the real BIS and ECB catalogue routes and the BIS data route: the oracle's own messages (xml_ops, unedited), then each corrupted one way."""

    LISTING = {"bis": "bis.catalog (the dataflows)", "ecb": "ecb.catalog (the dataflows)"}
    BROWSE = {"bis": "bis.catalog (a dataflow's dimensions)", "ecb": "ecb.catalog (a dataflow's dimensions)"}
    FLOWS = {"bis": ("BIS", xml_ops.BIS_FLOWS), "ecb": ("ECB", xml_ops.ECB_FLOWS)}

    def message(self, source: str, structures: bool = False) -> str:
        agency, flows = self.FLOWS[source]
        return xml_ops.structure_message(agency, flows, structures=structures)

    def entries(self, source: str, text: str) -> tuple[list, dict]:
        out, lane = lane_of(self.LISTING[source], text)
        return [e["id"] for e in out.get("entries") or []], lane

    def assert_read(self, source: str, text: str):
        ids, lane = self.entries(source, text)
        self.assertEqual((lane.get("coverage"), lane.get("completeness"), lane.get("count"), ids), ("searched_ok", "complete", 3, [f[0] for f in self.FLOWS[source][1]]), lane)

    def assert_unreadable(self, source: str, text: str):
        ids, lane = self.entries(source, text)
        self.assertEqual((lane.get("coverage"), lane.get("error_class"), lane.get("completeness"), ids), ("provider_unavailable", "payload_invalid", "unobserved", []), lane)
        self.assertNotIn("count", lane)

    def test_control_the_providers_messages_are_read(self):
        for source in self.LISTING:
            with self.subTest(source):
                self.assert_read(source, self.message(source))

    def test_child_text_in_a_name_is_an_unreadable_catalogue_not_a_shortened_label(self):
        """Astra's BIS case: `Policy <b>rates</b>` was the label `Policy `, complete, count three."""
        for source in self.LISTING:
            name = self.FLOWS[source][1][0][1]
            for label, name_xml in {"child text": f"{name[:3]}<b>{name[3:]}</b>", "only a child": f"<b>{name}</b>", "a nested child": f"{name[:3]}<b><c>{name[3:]}</c></b>",
                                    "a tail": f"{name[:3]}<b/>{name[3:]}"}.items():
                with self.subTest(source=source, how=label):
                    self.assert_unreadable(source, self.message(source).replace(f">{name}<", f">{name_xml}<", 1))

    def test_every_namespace_of_the_vocabulary_is_checked_where_it_is_read(self):
        """Astra's foreign-namespace case, one URI at a time and all together: the message, structure and common namespaces each carry names the lane reads."""
        for source in self.LISTING:
            for which in ("message", "structure", "common"):
                with self.subTest(source=source, replaced=which):
                    self.assert_unreadable(source, self.message(source).replace(f"{MESSAGE}{which}", f"urn:unrelated:{which}"))
            with self.subTest(source=source, replaced="all"):
                self.assert_unreadable(source, self.message(source).replace(MESSAGE, "urn:unrelated:"))

    def test_versions_other_than_sdmx_21_are_outside_the_vocabulary(self):
        """The documented compatibility limit (STATION-CONTRACT): SDMX-ML 2.0 and 3.0 name their elements in other namespaces and describe a flow's structure differently; they are refused,
        visibly, until a provider needs them and the reader has been checked against them."""
        text = self.message("bis")
        for version in ("v2_0", "v3_0"):
            with self.subTest(version=version):
                self.assert_unreadable("bis", text.replace("v2_1", version))
        self.assert_unreadable("bis", text.replace("http://www.sdmx.org/resources/sdmxml/schemas/v2_1/", "http://www.SDMX.org/resources/SDMXML/schemas/v2_0/"))

    def test_the_same_names_under_other_prefixes_are_the_same_names(self):
        """A prefix is only a spelling: the messages with `message:`, `structure:` and `common:` renamed read as the originals do (the entries, not only the count)."""
        for source in self.LISTING:
            text = self.message(source)
            renamed = (text.replace("xmlns:message=", "xmlns:m1=").replace("<message:", "<m1:").replace("</message:", "</m1:")
                       .replace("xmlns:structure=", "xmlns:s_t=").replace("<structure:", "<s_t:").replace("</structure:", "</s_t:")
                       .replace("xmlns:common=", "xmlns:c.1=").replace("<common:", "<c.1:").replace("</common:", "</c.1:"))
            self.assertNotEqual(renamed, text)
            with self.subTest(source=source):
                self.assert_read(source, renamed)
                self.assertEqual(self.entries(source, renamed), self.entries(source, text))

    def test_the_vocabulary_may_be_the_default_namespace(self):
        text = self.message("bis")
        default = (text.replace('xmlns:message="', 'xmlns="').replace("<message:", "<").replace("</message:", "</")
                   .replace("xmlns:structure=", "xmlns:str=").replace("<structure:", "<str:").replace("</structure:", "</str:"))
        self.assert_read("bis", default)

    def test_a_dataflow_in_no_namespace_is_not_a_dataflow_of_the_message(self):
        self.assert_unreadable("bis", self.message("bis").replace("<structure:Dataflow ", "<Dataflow ").replace("</structure:Dataflow>", "</Dataflow>"))

    def test_a_name_in_a_foreign_namespace_is_not_the_flows_name(self):
        text = self.message("bis")
        self.assert_unreadable("bis", text.replace("<common:Name xml:lang=\"en\">Policy rates</common:Name>", '<x:Name xmlns:x="urn:unrelated:common" xml:lang="en">Policy rates</x:Name>'))

    def test_the_browse_route_holds_the_same_names(self):
        """The flow's own binding (`Name`, `Structure`, `Ref`) and the data structure's `Dimension`s are read by the same rule."""
        for source in self.BROWSE:
            agency, flows = self.FLOWS[source]
            text = xml_ops.structure_message(agency, flows[:1])
            out, lane = lane_of(self.BROWSE[source], text)
            self.assertEqual((lane.get("coverage"), lane.get("completeness"), [e.get("dimensions_in_key_order") for e in out.get("entries") or []]), ("searched_ok", "complete", [list(flows[0][3])]), lane)
            for label, broken in {"a foreign structure namespace": text.replace(f"{MESSAGE}structure", "urn:unrelated:structure"),
                                  "a foreign common namespace": text.replace(f"{MESSAGE}common", "urn:unrelated:common"),
                                  "a dimension in no namespace": text.replace("<structure:Dimension ", "<Dimension ").replace("</structure:Dimension>", "</Dimension>")}.items():
                with self.subTest(source=source, how=label):
                    out, lane = lane_of(self.BROWSE[source], broken)
                    self.assertEqual(lane.get("coverage"), "provider_unavailable", lane)
                    self.assertNotIn("count", lane)

    def test_the_bis_data_message_is_read_with_its_series_and_observations_unqualified(self):
        text = xml_ops.bis_data_message((("US", 4), ("XM", 2)))
        out, lane = lane_of("bis.data (two series)", text)
        self.assertEqual((lane.get("coverage"), lane.get("completeness"), lane.get("count")), ("searched_ok", "complete", 2), lane)
        for label, broken in {"a foreign message namespace": text.replace(f"{MESSAGE}message", "urn:unrelated:message"),
                              "series in a foreign namespace": text.replace("<Series ", '<Series xmlns="urn:unrelated:data" '),
                              "a header entry in a foreign namespace": text.replace("<message:ID>1</message:ID>", '<x:ID xmlns:x="urn:unrelated:message">1</x:ID>')}.items():
            with self.subTest(how=label):
                out, lane = lane_of("bis.data (two series)", broken)
                self.assertEqual(lane.get("coverage"), "provider_unavailable", lane)
                self.assertNotIn("count", lane)

    def test_a_data_message_roots_both_sdmx_21_data_kinds(self):
        for root in ("StructureSpecificData", "GenericData"):
            with self.subTest(root=root):
                msg = sdmx.data_xml("bis", f'<message:{root} xmlns:message="{MESSAGE}message"><message:Header><message:ID>1</message:ID></message:Header></message:{root}>')
                self.assertEqual(len(msg["**Series"]), 0)
        with self.assertRaises(PayloadError):
            sdmx.data_xml("bis", f'<message:Structure xmlns:message="{MESSAGE}message"/>')

    def test_a_header_entry_is_kept_as_its_text_or_its_attributes_whatever_it_holds(self):
        """The one declared lossy read (`#own`): a Sender with a Name child is its id; the child is no part of the context."""
        text = (f'<message:StructureSpecificData xmlns:message="{MESSAGE}message" xmlns:common="{MESSAGE}common"><message:Header><message:ID>7</message:ID>'
                '<message:Sender id="BIS"><common:Name>Bank</common:Name></message:Sender><message:Prepared>2026-10-01T00:00:00</message:Prepared></message:Header>'
                '</message:StructureSpecificData>')
        self.assertEqual(sdmx.context_xml(sdmx.data_xml("bis", text))["header"],
                         {"ID": "7", "Sender": {"id": "BIS"}, "Prepared": "2026-10-01T00:00:00"})


class UnqualifiedForms(unittest.TestCase):
    """`intentionally supported unqualified forms are kept, explicitly`: every field of the SDMX-ML schemas that accepts an element in no namespace is on this list, with its reason in
    core/sdmx.py (SDMXCommonReferences.xsd declares `Ref` and `URN` `form="unqualified"`; a structure-specific data message's `Series` and `Obs` are local elements). Every other field that
    reads an element names the namespaces it reads it from."""

    UNQUALIFIED_FIELDS = {"Ref", "URN", "Obs", "**Series"}

    def walk(self, spec: S.Spec, path=()):
        if spec.kind == "obj":
            for name, field in spec.of.items():
                yield (*path, name), field
                yield from self.walk(field, (*path, name))
        elif isinstance(spec.of, S.Spec):
            yield from self.walk(spec.of, path)

    def element_fields(self):
        for schema in (sdmx.XML_MESSAGE, sdmx.FLOW_NAMES, sdmx.FLOW_BINDING, sdmx.DATA_STRUCTURES):
            for path, field in self.walk(schema):
                if not path[-1].startswith(("@", "%", "#")):   # attributes are unqualified by SDMX's own rule; `%` and `#` read the element they are in
                    yield path, field

    def test_the_fields_that_accept_no_namespace_are_exactly_the_listed_ones(self):
        accepted = {path[-1] for path, field in self.element_fields() if S.UNQUALIFIED in field.ns}
        self.assertEqual(accepted, self.UNQUALIFIED_FIELDS, "an element accepted in no namespace is a reviewed decision: add it here and to core/sdmx.py with its reason")

    def test_every_other_field_that_reads_an_element_names_a_namespace(self):
        for path, field in self.element_fields():
            if path[-1] not in self.UNQUALIFIED_FIELDS:
                self.assertNotIn(S.UNQUALIFIED, field.ns, ".".join(path))
                self.assertTrue(all(ns.startswith("http://www.sdmx.org/resources/sdmxml/schemas/v2_1/") for ns in field.ns), ".".join(path))


if __name__ == "__main__":
    unittest.main()
