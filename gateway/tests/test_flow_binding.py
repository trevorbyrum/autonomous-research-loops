"""Task 2b-repair-11b, R10-2: a dataflow browse is bound to the flow asked for, and a flow that cannot be bound yields nothing.

Astra (2b-repair-10, R10-2): BIS and ECB read the structure reference from `flows[0]` and labelled the template with the caller's `within`, so a request for
the second flow of a message got the first flow's dimensions under the second flow's name, and a flow the message did not hold got an executable template.
The independent oracle (tests/oracle/flow_cases.py) holds the browse in every position of a message, in rotated flow orders, with the structures in either
order, a flow absent, defined twice and with its structure missing. This file states, through the real adapters, what the oracle's cases do not reach:

  * a flow another agency maintains is not the flow asked for (a flow that states no agency is still read: SDMX-ML written without one);
  * the same flow defined twice identically is one flow; two definitions that differ in any way that is bound (version, agency, name, structure) are not;
  * a flow's own `Structure` child names its structure: a `Ref` anywhere else under the flow is no reference, and a flow whose reference names no structure id
    names none: no template, and the structure is never guessed from the flow's own id (the old `structure_ref or within`);
  * a reference that more than one structure of the message answers to, with different dimensions, is ambiguous; with the same dimensions it is not;
  * (2b-repair-12, R11-2) the references a flow states are decoded and checked together, never reduced to the first: SDMX 2.1 gives a Dataflow ONE structure reference,
    a `Ref` with an optional `URN`, or a `URN` alone (DataflowType, ReferenceType); two of them, or a `Ref` and a `URN` that name different structures, are a flow
    that does not say which structure it has: unreadable, no template. A `Ref` with a matching `URN` is one reference; a `URN` alone is not followed (no template).
"""
from __future__ import annotations

import unittest

from research_gateway import adapters
from research_gateway.adapters.base import Client, FakeTransport, PayloadError
from research_gateway.core import router as R, sdmx
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.registry.load import read_seed

HOSTS = {"ecb": "https://data-api.ecb.europa.eu/service", "bis": "https://stats.bis.org/api/v2/structure"}


def flow(id_: str, name: str, ref: str, agency: str | None = None, version: str | None = None) -> str:
    attrs = "".join(f' {k}="{v}"' for k, v in (("id", id_), ("agencyID", agency), ("version", version)) if v is not None)
    return f"<str:Dataflow{attrs}><str:Name>{name}</str:Name><str:Structure>{ref}</str:Structure></str:Dataflow>"


def dsd(id_: str, dims: tuple, agency: str = "X", version: str = "1.0") -> str:
    body = "".join(f'<str:Dimension id="{d}" position="{n}"/>' for n, d in enumerate(dims, 1))
    return (f'<str:DataStructure id="{id_}" agencyID="{agency}" version="{version}"><str:DataStructureComponents><str:DimensionList>{body}'
            "</str:DimensionList></str:DataStructureComponents></str:DataStructure>")


def message(*parts: str) -> str:
    flows = "".join(p for p in parts if "Dataflow" in p)
    structures = "".join(p for p in parts if "DataStructure" in p and "Dataflow" not in p)
    return f'<mes:Structure xmlns:mes="x" xmlns:str="y"><str:Dataflows>{flows}</str:Dataflows><str:DataStructures>{structures}</str:DataStructures></mes:Structure>'


def ref(id_: str, agency: str = "X", version: str = "1.0") -> str:
    return f'<Ref id="{id_}" agencyID="{agency}" version="{version}"/>'


def browse(source: str, text: str, within: str = "F1", structures: str | None = None):
    """The adapter's catalogue answer for a browse of `within`: the message the provider answers a dataflow request with, and `structures` (the message the
    structure request is answered with; the same message when None)."""
    t = FakeTransport()
    agency = source.upper()
    t.add("GET", f"{HOSTS[source]}/dataflow/{agency}/{within}", body=text)
    for sid in ("S0", "S1", "S2", "F1"):
        t.add("GET", f"{HOSTS[source]}/datastructure/{agency}/{sid}", body=structures if structures is not None else text)
    c = Client(broker=Broker({source: RatePolicy(per_second=1000)}), transport=t)
    return adapters.load_all()[source].catalog(c, within=within)


def routed(source: str, text: str, within: str = "F1") -> dict:
    t = FakeTransport()
    t.add("GET", f"{HOSTS[source]}/", body=text)
    c = Client(broker=Broker({source: RatePolicy(per_second=1000)}), transport=t)
    out = R.execute(R.Router(read_seed(), adapters.load_all()), {"request_type": "catalog", "source": source, "within": within}, c)
    return next(e for e in out["lanes"] if e["source"] == source)


class SelectionOfTheFlow(unittest.TestCase):
    def read(self, *parts: str):
        return sdmx.flows("ecb", message(*parts))

    @staticmethod
    def named(flows, wanted, agency):
        return sdmx.dataflow_named("ecb", flows, wanted, agency)

    def test_the_flow_asked_for_is_the_one_found_by_its_id(self):
        flows = self.read(flow("F0", "Zero", ref("S0"), "ECB"), flow("F1", "One", ref("S1"), "ECB"), flow("F2", "Two", ref("S2"), "ECB"))
        self.assertEqual([self.named(flows, w, "ECB")["label"] for w in ("F2", "F0", "F1")], ["Two", "Zero", "One"])
        self.assertIsNone(self.named(flows, "F9", "ECB"))
        self.assertEqual(self.named(flows, "F1", "ECB")["structure"]["id"], "S1")

    def test_a_flow_another_agency_maintains_is_not_the_flow_asked_for(self):
        flows = self.read(flow("F1", "Other", ref("S1"), "OTHER"))
        self.assertIsNone(self.named(flows, "F1", "ECB"))
        self.assertIsNotNone(self.named(self.read(flow("F1", "No agency", ref("S1"))), "F1", "ECB"), "a flow that states no agency is read")
        flows = self.read(flow("F1", "Other", ref("S1"), "OTHER"), flow("F1", "Ours", ref("S1"), "ECB"))
        self.assertEqual(self.named(flows, "F1", "ECB")["label"], "Ours")

    def test_the_same_definition_twice_is_one_flow_and_a_different_one_is_ambiguous(self):
        twice = self.read(flow("F1", "One", ref("S1"), "ECB", "1.0"), flow("F1", "One", ref("S1"), "ECB", "1.0"))
        self.assertEqual(self.named(twice, "F1", "ECB")["label"], "One")
        for other in (flow("F1", "One", ref("S1"), "ECB", "2.0"), flow("F1", "Renamed", ref("S1"), "ECB", "1.0"), flow("F1", "One", ref("S2"), "ECB", "1.0"),
                      flow("F1", "One", ref("S1"), None, "1.0")):
            with self.subTest(other=other[:90]):
                with self.assertRaises(PayloadError):
                    self.named(self.read(flow("F1", "One", ref("S1"), "ECB", "1.0"), other), "F1", "ECB")

    def test_only_the_structure_child_of_the_flow_names_its_structure(self):
        stray = ('<str:Dataflow id="F1" agencyID="ECB"><str:Name>One</str:Name><str:Annotations><str:Annotation><str:AnnotationText>x</str:AnnotationText>'
                 '<Ref id="NOT_A_STRUCTURE"/></str:Annotation></str:Annotations></str:Dataflow>')
        self.assertEqual(self.named(self.read(stray), "F1", "ECB")["structure"], {}, "a Ref that is not under the Structure child is no reference")
        nameless = '<str:Dataflow id="F1"><str:Structure><Ref id="S1"/></str:Structure></str:Dataflow>'
        found = self.named(self.read(nameless), "F1", "ECB")
        self.assertEqual((found["label"], found["structure"]["id"]), ("F1", "S1"), "a flow with no name is labelled by its id")

    def test_a_reference_that_more_than_one_structure_answers_to_is_ambiguous_unless_they_agree(self):
        reference = {"id": "S1", "agencyID": "X"}
        two = message(dsd("S1", ("A", "B"), "X", "1.0"), dsd("S1", ("A", "C"), "X", "2.0"))
        with self.assertRaises(PayloadError):
            sdmx.dimensions_xml("ecb", two, reference)
        self.assertEqual(sdmx.dimensions_xml("ecb", two, {**reference, "version": "2.0"}), ["A", "C"])
        same = message(dsd("S1", ("A", "B"), "X", "1.0"), dsd("S1", ("A", "B"), "X", "2.0"))
        self.assertEqual(sdmx.dimensions_xml("ecb", same, reference), ["A", "B"])
        self.assertEqual(sdmx.dimensions_xml("ecb", message(dsd("S2", ("A",))), reference), [], "none of the structure in the message: no dimensions, no template")


class BrowseOfTheFlowAskedFor(unittest.TestCase):
    def test_the_entry_is_the_flows_own_in_every_position_for_both_providers(self):
        for source, agency in (("ecb", "ECB"), ("bis", "BIS")):
            flows = [flow(f"F{i}", f"Name {i}", ref(f"S{i}", agency), agency) for i in (0, 1, 2)]
            structures = [dsd(f"S{i}", tuple(f"D{i}{k}" for k in range(i + 2)), agency) for i in (0, 1, 2)]
            for within, want in (("F0", 2), ("F1", 3), ("F2", 4)):
                with self.subTest(source=source, within=within):
                    entry = browse(source, message(*flows, *structures), within, structures=message(*structures))["entries"][0]
                    self.assertEqual((entry["id"], entry["label"], len(entry["dimensions_in_key_order"])), (within, f"Name {within[1]}", want))
                    self.assertEqual(entry["data_request"]["arguments"]["params"], {"dataflow": within, "key": ".".join("?" * want)})

    def test_a_flow_that_names_no_structure_yields_no_template_and_is_not_guessed_from_its_own_id(self):
        for source in ("ecb", "bis"):
            for text in (message('<str:Dataflow id="F1"><str:Name>One</str:Name></str:Dataflow>', dsd("F1", ("A", "B"))),
                         message('<str:Dataflow id="F1"><str:Name>One</str:Name><str:Structure><Ref/></str:Structure></str:Dataflow>', dsd("F1", ("A", "B")))):
                with self.subTest(source=source, text=text[:80]):
                    out = browse(source, text)
                    self.assertEqual(out["entries"], [])
                    self.assertIn("names no data structure", out["capability_fact"])

    def test_a_flow_the_message_does_not_hold_yields_no_template_even_beside_flows_that_it_does(self):
        for source in ("ecb", "bis"):
            out = browse(source, message(flow("F0", "Zero", ref("S1")), dsd("S1", ("A",))), within="F1")
            self.assertEqual((out["entries"], "no such dataflow" in out["capability_fact"]), ([], True), source)

    def test_an_ambiguous_flow_or_structure_is_an_unreadable_answer_and_not_the_first_of_them(self):
        for source in ("ecb", "bis"):
            agency = source.upper()
            ambiguous_flow = message(flow("F1", "One", ref("S1"), agency, "1.0"), flow("F1", "One", ref("S1"), agency, "2.0"), dsd("S1", ("A", "B")))
            ambiguous_structure = message(flow("F1", "One", '<Ref id="S1" agencyID="X"/>'), dsd("S1", ("A", "B"), "X", "1.0"), dsd("S1", ("A", "C"), "X", "2.0"))   # no version stated
            for text in (ambiguous_flow, ambiguous_structure):
                with self.subTest(source=source):
                    lane = routed(source, text)
                    self.assertEqual((lane["coverage"], lane["completeness"], lane.get("error_class"), "count" in lane), ("provider_unavailable", "unobserved", "payload_invalid", False))

    def test_control_the_same_message_without_the_second_definition_is_read(self):
        for source in ("ecb", "bis"):
            lane = routed(source, message(flow("F1", "One", ref("S1"), source.upper(), "1.0"), dsd("S1", ("A", "B"))))
            self.assertEqual((lane["coverage"], lane["completeness"], lane["retrieved"]), ("searched_ok", "complete", ["F1"]), source)


def urn(id_: str, agency: str, version: str = "1.0") -> str:
    return f"<URN>urn:sdmx:org.sdmx.infomodel.datastructure.DataStructure={agency}:{id_}({version})</URN>"


class ReferencesInTheRequestedFlow(unittest.TestCase):
    """R11-2 (Astra, 2b-repair-11): a requested flow with S1 = [A, B] and S2 = [C, D, E] states its structure reference in every way SDMX 2.1 allows or forbids."""

    def flow_with(self, source: str, references: str) -> str:
        agency = source.upper()
        return message(flow("F1", "One", references, agency), dsd("S1", ("A", "B"), agency), dsd("S2", ("C", "D", "E"), agency))

    def dimensions(self, source: str, references: str):
        return [e["dimensions_in_key_order"] for e in browse(source, self.flow_with(source, references))["entries"]]

    def test_one_reference_is_the_flows_structure(self):
        for source in ("bis", "ecb"):
            agency = source.upper()
            for label, references in (("a Ref", ref("S1", agency)), ("a Ref with the URN that names it", ref("S1", agency) + urn("S1", agency)),
                                      ("a Ref that states no agency or version, with its URN", '<Ref id="S1"/>' + urn("S1", agency))):
                with self.subTest(source=source, references=label):
                    self.assertEqual(self.dimensions(source, references), [["A", "B"]])
                    self.assertEqual((routed(source, self.flow_with(source, references))["completeness"]), "complete")

    def test_two_references_are_not_reduced_to_the_first_in_either_order(self):
        for source in ("bis", "ecb"):
            agency = source.upper()
            for label, references in (("S1 then S2", ref("S1", agency) + ref("S2", agency)), ("S2 then S1", ref("S2", agency) + ref("S1", agency)),
                                      ("the same twice", ref("S1", agency) + ref("S1", agency))):
                with self.subTest(source=source, references=label):
                    lane = routed(source, self.flow_with(source, references))
                    self.assertEqual((lane["coverage"], lane["completeness"], lane.get("error_class"), "count" in lane), ("provider_unavailable", "unobserved", "payload_invalid", False))
                    with self.assertRaises(PayloadError):
                        browse(source, self.flow_with(source, references))

    def test_a_ref_beside_a_urn_that_names_something_else_is_a_flow_that_does_not_say_which(self):
        for source in ("bis", "ecb"):
            agency = source.upper()
            for label, references in (("another structure", ref("S1", agency) + urn("S2", agency)), ("another agency", ref("S1", agency) + urn("S1", "OTHER")),
                                      ("another version", ref("S1", agency) + urn("S1", agency, "2.0")), ("a URN that cannot be read", ref("S1", agency) + "<URN>not a urn</URN>"),
                                      ("two URNs", ref("S1", agency) + urn("S1", agency) + urn("S1", agency))):
                with self.subTest(source=source, references=label):
                    lane = routed(source, self.flow_with(source, references))
                    self.assertEqual((lane["coverage"], lane["completeness"], lane.get("error_class"), "count" in lane), ("provider_unavailable", "unobserved", "payload_invalid", False))

    def test_a_urn_alone_is_the_disclosed_unsupported_case_and_yields_no_template(self):
        for source in ("bis", "ecb"):
            with self.subTest(source=source):
                out = browse(source, self.flow_with(source, urn("S1", source.upper())))
                self.assertEqual(out["entries"], [])
                self.assertIn("names no data structure", out["capability_fact"])

    def test_two_structure_children_are_two_references(self):
        """The reference is one `Structure` child of the flow; a flow with two of them states two."""
        for source in ("bis", "ecb"):
            agency = source.upper()
            text = message(f'<str:Dataflow id="F1" agencyID="{agency}"><str:Name>One</str:Name><str:Structure>{ref("S1", agency)}</str:Structure>'
                           f'<str:Structure>{ref("S1", agency)}</str:Structure></str:Dataflow>', dsd("S1", ("A", "B"), agency))
            with self.subTest(source=source), self.assertRaises(PayloadError):
                browse(source, text)

    def test_a_flow_nobody_asked_for_is_not_asked_for_its_references(self):
        """Another flow of the message may state a reference that contradicts itself: the requested flow is still read."""
        for source in ("bis", "ecb"):
            agency = source.upper()
            text = message(flow("F0", "Zero", ref("S1", agency) + ref("S2", agency), agency), flow("F1", "One", ref("S1", agency), agency),
                           dsd("S1", ("A", "B"), agency), dsd("S2", ("C", "D", "E"), agency))
            with self.subTest(source=source):
                self.assertEqual([e["dimensions_in_key_order"] for e in browse(source, text)["entries"]], [["A", "B"]])


class ReferenceShape(unittest.TestCase):
    """R12-2 (Astra, 2b-repair-12): the shape of a flow's structure reference is checked over EVERYTHING the flow states, before any of it is filtered or chosen.

    Repair-12 refused two named Refs and a Ref beside a conflicting URN, but counted the Refs AFTER discarding every one with no id, and never looked at the fixed attributes of a data structure reference
    — so a valid Ref followed by `<Ref/>` (or `<Ref id=""/>`), or one stating `package="codelist"` or `class="Codelist"`, still returned a complete template. SDMX 2.1 (SDMXCommonReferences.xsd,
    DataStructureReferenceType and DataStructureRefType): one `Ref` with an optional `URN`, or a `URN` alone, and `class` and `package` optional with FIXED values `DataStructure` and `datastructure`. A
    lone Ref that names no id, and a URN alone, stay the accepted conservative refusal (no template, a capability fact)."""

    def flow_with(self, source: str, references: str) -> str:
        agency = source.upper()
        return message(flow("F1", "One", references, agency), dsd("S1", ("A", "B"), agency), dsd("S2", ("C", "D", "E"), agency))

    def unreadable(self, source: str, references: str):
        lane = routed(source, self.flow_with(source, references))
        self.assertEqual((lane["coverage"], lane["completeness"], lane.get("error_class"), "count" in lane), ("provider_unavailable", "unobserved", "payload_invalid", False), references)
        with self.assertRaises(PayloadError):
            browse(source, self.flow_with(source, references))

    def test_the_astra_cases_for_both_providers_are_unreadable_and_the_controls_read(self):
        for source in ("bis", "ecb"):
            agency = source.upper()
            good = ref("S1", agency)
            self.assertEqual([e["dimensions_in_key_order"] for e in browse(source, self.flow_with(source, good))["entries"]], [["A", "B"]], f"{source}: control")
            self.assertEqual(routed(source, self.flow_with(source, good))["completeness"], "complete")
            for label, references in (("a valid Ref, then an empty Ref", good + "<Ref/>"), ("an empty Ref, then a valid Ref", "<Ref/>" + good),
                                      ("a valid Ref, then a Ref with an empty id", good + '<Ref id=""/>'), ("a valid Ref, then a Ref of blanks", good + '<Ref id="  "/>'),
                                      ("a Ref that says package=codelist", good.replace("/>", ' package="codelist"/>')), ("a Ref that says class=Codelist", good.replace("/>", ' class="Codelist"/>')),
                                      ("a Ref that says the wrong case", good.replace("/>", ' package="DataStructure"/>')), ("two nameless Refs", "<Ref/><Ref/>")):
                with self.subTest(source=source, references=label):
                    self.unreadable(source, references)

    def test_the_fixed_attributes_may_be_stated_with_their_own_values(self):
        for source in ("bis", "ecb"):
            agency = source.upper()
            for label, extra in (("both", ' package="datastructure" class="DataStructure"'), ("package", ' package="datastructure"'), ("class", ' class="DataStructure"')):
                references = ref("S1", agency).replace("/>", extra + "/>")
                with self.subTest(source=source, stated=label):
                    self.assertEqual([e["dimensions_in_key_order"] for e in browse(source, self.flow_with(source, references))["entries"]], [["A", "B"]])
                    self.assertEqual(routed(source, self.flow_with(source, references))["completeness"], "complete")

    def test_the_fixed_attributes_are_checked_even_when_the_ref_names_nothing(self):
        for source in ("bis", "ecb"):
            for references in ('<Ref class="Codelist"/>', '<Ref package="codelist"/>', '<Ref id="" class="Codelist"/>'):
                with self.subTest(source=source, references=references):
                    self.unreadable(source, references)

    def test_a_lone_ref_that_names_nothing_and_a_urn_alone_stay_the_conservative_refusal_and_are_not_unreadable(self):
        for source in ("bis", "ecb"):
            agency = source.upper()
            for label, references in (("a lone empty Ref", "<Ref/>"), ("a lone Ref with an empty id", '<Ref id=""/>'), ("a lone Ref with only attributes", '<Ref agencyID="X" version="1.0"/>'),
                                      ("a URN alone", urn("S1", agency))):
                with self.subTest(source=source, references=label):
                    out = browse(source, self.flow_with(source, references))
                    self.assertEqual(out["entries"], [])
                    self.assertIn("names no data structure", out["capability_fact"])

    def test_a_ref_that_names_nothing_beside_a_urn_cannot_be_shown_to_name_the_same_structure(self):
        for source in ("bis", "ecb"):
            for label, references in (("an empty Ref and a URN", "<Ref/>" + urn("S1", source.upper())), ("a Ref of blanks and a URN", '<Ref id=" "/>' + urn("S1", source.upper()))):
                with self.subTest(source=source, references=label):
                    self.unreadable(source, references)

    def test_what_is_counted_is_every_ref_and_every_urn_wherever_they_stand_in_the_one_structure_child(self):
        agency = "ECB"
        for label, references in (("three Refs", ref("S1", agency) * 3), ("one Ref and two URNs", ref("S1", agency) + urn("S1", agency) * 2), ("a nameless Ref, a Ref and a URN", "<Ref/>" + ref("S1", agency) + urn("S1", agency))):
            with self.subTest(references=label):
                self.unreadable("ecb", references)


if __name__ == "__main__":
    unittest.main()
