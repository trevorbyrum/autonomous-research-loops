"""Task 2b-repair-14 (Astra F2 / R13C-3): the gateway mutants of XML interpretation (core/schema.py `_read`, `_belongs`, `parse_xml`; core/sdmx.py).

An XML field has a lossless meaning and a name is an expanded name (core/schema.py's module docstring). The mutants here remove ONE rule in a temporary copy and name the tests that must notice
(tests/test_xml_interpretation.py, tests/test_schema.py):

  X-scalar-*   an element that holds a child element has a scalar text (its first chunk, or nothing);
  X-names-*    an element whose local name a field reads is read from any namespace; the same element in a foreign namespace is skipped as though absent; the root is not held to a namespace.

A killer must FAIL in its assertions, not error (tools/gen2_gateway_mutations.py). A control takes the accepted path through the same code.
"""
from __future__ import annotations

SCHEMA = "research_gateway/core/schema.py"
SDMX = "research_gateway/core/sdmx.py"
XI = "tests.test_xml_interpretation."
ST, EN, SV = XI + "ScalarText.", XI + "ExpandedNames.", XI + "SdmxVocabulary."
CONTROLS = (ST + "test_control_the_scalar_forms_that_hold_no_child_are_read_whole", EN + "test_the_approved_uri_passes_under_any_prefix_or_as_the_default_namespace",
            SV + "test_control_the_providers_messages_are_read", SV + "test_the_same_names_under_other_prefixes_are_the_same_names")


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("X-scalar-an-element-with-a-child-reads-its-first-chunk", "`<Name>x<b>y</b></Name>` reads as `x` and `<Name><b>y</b></Name>` as nothing: only a child's tail was ever looked at", SCHEMA,
               "        if len(v):   # `<a>x<b/>y</a>`", "        if False:   # `<a>x<b/>y</a>`",
               ("tests.test_schema.Xml.test_an_element_that_holds_a_child_has_no_scalar_text_whatever_the_child_holds", ST + "test_a_scalar_element_that_holds_a_child_is_refused_in_every_position_of_its_text",
                SV + "test_child_text_in_a_name_is_an_unreadable_catalogue_not_a_shortened_label"),
               (ST + "test_control_the_scalar_forms_that_hold_no_child_are_read_whole", "tests.test_schema.Xml.test_an_element_is_read_by_attribute_text_name_and_descendant", SV + "test_control_the_providers_messages_are_read")),
        Mutant("X-names-a-foreign-namespace-is-read", "an element of the right local name is read from whatever namespace it is in (the URI is thrown away): Astra's `urn:unrelated:` catalogue", SCHEMA,
               "    if uri not in ns:\n        listed = ", "    if False:\n        listed = ",
               (EN + "test_a_foreign_uri_is_refused_and_not_read_as_absent", EN + "test_the_root_is_held_to_it_too", SV + "test_every_namespace_of_the_vocabulary_is_checked_where_it_is_read",
                SV + "test_versions_other_than_sdmx_21_are_outside_the_vocabulary", SV + "test_a_dataflow_in_no_namespace_is_not_a_dataflow_of_the_message"), CONTROLS),
        Mutant("X-names-a-foreign-namespace-is-read-as-absent", "an element of the right local name in a foreign namespace is skipped as though the field were not there (a catalogue of nothing, not an unreadable one)", SCHEMA,
               "    if uri not in ns:\n        listed = ", "    if uri not in ns:\n        return False\n        listed = ",
               (EN + "test_a_foreign_uri_is_refused_and_not_read_as_absent", SV + "test_every_namespace_of_the_vocabulary_is_checked_where_it_is_read", SV + "test_a_dataflow_in_no_namespace_is_not_a_dataflow_of_the_message"),
               CONTROLS),
        Mutant("X-names-the-root-is-not-held-to-a-namespace", "a message whose root has the right local name in a foreign namespace is read", SCHEMA,
               "    _belongs(root, namespaces, ())\n    return root", "    return root",
               (EN + "test_the_root_is_held_to_it_too", SV + "test_every_namespace_of_the_vocabulary_is_checked_where_it_is_read"), CONTROLS),
        Mutant("X-names-a-descendant-is-matched-by-its-local-name", "`**name` matches every descendant of that local name, whatever its namespace", SCHEMA,
               "_local(d.tag) == name[2:] and _belongs(d, ns, at)]", "_local(d.tag) == name[2:]]",
               (EN + "test_descendants_and_all_children_are_held_to_the_same_rule", SV + "test_every_namespace_of_the_vocabulary_is_checked_where_it_is_read"), CONTROLS),
        Mutant("X-names-a-child-is-matched-by-its-local-name", "`name` matches every child of that local name, whatever its namespace", SCHEMA,
               "_local(c.tag) == name and _belongs(c, ns, at)]", "_local(c.tag) == name]",
               (EN + "test_a_foreign_uri_is_refused_and_not_read_as_absent", SV + "test_a_name_in_a_foreign_namespace_is_not_the_flows_name"), CONTROLS),
        Mutant("X-names-every-child-is-taken-whatever-its-namespace", "`*` takes every child, whatever its namespace (a header entry from another vocabulary is a header entry)", SCHEMA,
               "[c for c in v if _belongs(c, ns, at)] or MISSING", "list(v) or MISSING",
               (EN + "test_descendants_and_all_children_are_held_to_the_same_rule", SV + "test_the_bis_data_message_is_read_with_its_series_and_observations_unqualified"), CONTROLS),
    ]
