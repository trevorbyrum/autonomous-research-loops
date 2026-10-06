"""Task 2b-repair-13c: the gateway mutants of opaque provenance (Astra R13A-2).

A record's `raw`, its passive `extra` values and a download's bytes stay opaque from the moment an adapter builds the record until the router (or the index) serializes it; no adapter code can
read them, so no selection or coverage decision can depend on them. The mutants here remove ONE part of that construction in a temporary copy:

  Q-record-*   `make_record` materializes provenance again, aliases its input, accepts an opaque value in a typed field, unwraps a decoded object in one, or leaves a plain raw readable;
  Q-download-* `Response.download()` hands out the bytes;
  Q-router-*   the router does not materialize the answer at its boundary; Q-index-* / Q-cache-* the index load and the cache do not materialize what they store;
  Q-sealed-*   two Sealed objects compare (a literal an adapter passed as raw guesses a raw object), a decoded object compares with anything, `same_as` takes a value an adapter wrote, and a Sealed,
               a Passive or a Rec built in a provider module is no listed door.

A killer must FAIL in its assertions, not error (tools/gen2_gateway_mutations.py). A control takes the accepted path through the same code.
"""
from __future__ import annotations

CANON = "research_gateway/core/canonical.py"
PAYLOAD = "research_gateway/core/payload.py"
RESPONSE = "research_gateway/adapters/_response.py"
ROUTER = "research_gateway/core/router.py"
INDEX = "research_gateway/harvest/index.py"
OP = "tests.test_opaque_provenance."
COPY, EXIT, PLACE = OP + "TheCopyEscape.", OP + "EveryExit.", OP + "WhereItBecomesPlain."
MI = "tests.test_member_isolation."
SP = "tests.test_sealed_payload."
ASTRA = "tests.test_astra_13a.R13A2."
CC, TC = OP + "ConstructorCompositions.", OP + "TheOneComparison."
CONTROL = ASTRA + "test_the_unmodified_adapter_keeps_all_three_citations"


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("Q-record-materializes-its-provenance", "`make_record` returns `plain(record)` again: the raw object and the passive values are readable in the returned dictionary (Astra's copy escape)", CANON,
               ('    return rec\n\n\nPROVENANCE_SUMMARY_FIELDS', "from .payload import PayloadError, Sealed, detach, refuse_opaque"),
               ('    return plain(rec)\n\n\nPROVENANCE_SUMMARY_FIELDS', "from .payload import PayloadError, Sealed, detach, plain, refuse_opaque"),
               (ASTRA + "test_astras_mutant_cannot_read_the_copy_it_made_so_it_fails_loudly_instead_of_dropping_a_candidate", COPY + "test_the_variants_each_fail_where_the_value_is_read",
                COPY + "test_each_variant_run_through_the_real_adapter_and_router_is_never_a_complete_lane",
                EXIT + "test_a_record_is_a_plain_dict_with_plain_typed_fields_and_opaque_provenance", PLACE + "test_before_the_routers_boundary_every_operations_records_still_hold_a_sealed_raw",
                SP + "RawIsSealedAndLeavesAsACopy.test_a_records_raw_is_sealed_in_the_record_and_each_materialization_is_a_copy_independent_of_the_decoders"),
               (CONTROL, PLACE + "test_after_it_every_operations_answer_is_plain_json_with_no_sealed_passive_or_decoded_object_left")),
        Mutant("Q-record-a-plain-raw-is-left-readable", "a raw that is a plain value is stored as the (copied) dictionary instead of sealed", CANON,
               'Sealed(detach(raw))', 'detach(raw)',
               (EXIT + "test_a_raw_that_is_a_plain_value_is_sealed_too", CC + "test_a_raw_is_sealed_as_it_is_without_being_materialized_or_read"), (CONTROL, EXIT + "test_a_record_is_a_plain_dict_with_plain_typed_fields_and_opaque_provenance")),
        Mutant("Q-record-the-raw-is-not-the-member", "a record's raw is the sealed copy of an empty object, whatever member it was built from (raw-storage fidelity)", CANON,
               "    rec[\"raw\"] = raw if raw is None or isinstance(raw, Sealed) else Sealed(detach(raw))", "    rec[\"raw\"] = None if raw is None else Sealed({})",
               (OP + "RawIsTheMemberAsSent.test_crossref_a_works_raw_is_the_item", OP + "RawIsTheMemberAsSent.test_opencitations_each_citations_raw_is_its_row_both_through_the_adapter_and_the_router",
                OP + "RawIsTheMemberAsSent.test_a_doaj_dumps_raw_is_each_row_by_its_columns", OP + "RawIsTheMemberAsSent.test_unpaywall_each_locations_raw_is_the_location_object"),
               (CONTROL, PLACE + "test_after_it_every_operations_answer_is_plain_json_with_no_sealed_passive_or_decoded_object_left")),
        Mutant("Q-record-extra-is-materialized", "the values of `extra` are materialized in the record: a passive value is readable there", CANON,
               ("rec.update({k: detach(v) for k, v in extra.items() if k not in rec})", "from .payload import PayloadError, Sealed, detach, refuse_opaque"),
               ("rec.update({k: plain(v) for k, v in extra.items() if k not in rec})", "from .payload import PayloadError, Sealed, detach, plain, refuse_opaque"),
               (COPY + "test_the_variants_each_fail_where_the_value_is_read", COPY + "test_each_variant_run_through_the_real_adapter_and_router_is_never_a_complete_lane",
                EXIT + "test_a_record_is_a_plain_dict_with_plain_typed_fields_and_opaque_provenance",
                SP + "PassiveIsOnlyStored.test_plain_hands_out_a_copy_and_a_record_keeps_a_passive_value_passive_until_it_is_materialized"),
               (CONTROL,)),
        Mutant("Q-record-extra-aliases-the-adapters-structure", "the record's `extra` holds the adapter's own list, not a copy of its structure", CANON,
               "rec.update({k: detach(v) for k, v in extra.items() if k not in rec})", "rec.update({k: v for k, v in extra.items() if k not in rec})",
               (EXIT + "test_extra_is_a_copy_of_the_structure_and_never_an_alias_of_the_adapters_list",), (CONTROL,)),
        Mutant("Q-record-a-typed-field-accepts-an-opaque-value", "a title, venue, licence, author list, link list, identifiers or year that is not in its domain is only a wrong kind: an opaque value (a Passive, a Sealed) is no programming error", CANON,
               '    refuse_opaque(value, f"a record\'s {name}")\n    raise PayloadError(', "    raise PayloadError(",
               (COPY + "test_the_variants_each_fail_where_the_value_is_read", CC + "test_each_typed_field_takes_its_own_domain_and_never_unwraps_what_the_decoder_issued"),
               (CONTROL, EXIT + "test_a_record_is_a_plain_dict_with_plain_typed_fields_and_opaque_provenance", CC + "test_control_the_typed_domains_are_taken_whole")),
        Mutant("Q-record-identifiers-unwrap-a-decoded-object", "the identifiers of a record are `plain(value)` before they are checked: a decoded object whose fields are text is unwrapped into its original (Astra's second R13C-2 mutant)", CANON,
               ("def _identifiers(value) -> dict:\n    if value is None:", "from .payload import PayloadError, Sealed, detach, refuse_opaque"),
               ("def _identifiers(value) -> dict:\n    value = plain(value)\n    if value is None:", "from .payload import PayloadError, Sealed, detach, plain, refuse_opaque"),
               (CC + "test_a_decoded_object_passed_as_a_typed_container_is_not_unwrapped_into_its_original", CC + "test_each_typed_field_takes_its_own_domain_and_never_unwraps_what_the_decoder_issued"),
               (CONTROL, CC + "test_control_the_typed_domains_are_taken_whole")),
        Mutant("Q-record-text-unwraps-a-decoded-object", "a title, venue, licence or attribution is `plain(value)` before it is checked", CANON,
               ('    """A canonical text field: text, or nothing.', "from .payload import PayloadError, Sealed, detach, refuse_opaque"),
               ('    value = plain(value)\n    """A canonical text field: text, or nothing.', "from .payload import PayloadError, Sealed, detach, plain, refuse_opaque"),
               (CC + "test_each_typed_field_takes_its_own_domain_and_never_unwraps_what_the_decoder_issued",), (CONTROL, CC + "test_control_the_typed_domains_are_taken_whole")),
        Mutant("Q-record-text-lists-unwrap-a-decoded-object", "the authors and links of a record are `plain(value)` before they are checked", CANON,
               ('    """A canonical list of text (authors, links):', "from .payload import PayloadError, Sealed, detach, refuse_opaque"),
               ('    value = plain(value)\n    """A canonical list of text (authors, links):', "from .payload import PayloadError, Sealed, detach, plain, refuse_opaque"),
               (CC + "test_each_typed_field_takes_its_own_domain_and_never_unwraps_what_the_decoder_issued",), (CONTROL, CC + "test_control_the_typed_domains_are_taken_whole")),
        Mutant("Q-record-the-year-accepts-an-opaque-value", "a record's year may be built from a Passive, a Sealed or a decoded object", CANON,
               '    refuse_opaque(value, "a record\'s year")\n', "",
               (CC + "test_each_typed_field_takes_its_own_domain_and_never_unwraps_what_the_decoder_issued", COPY + "test_the_variants_each_fail_where_the_value_is_read"), (CONTROL, CC + "test_control_the_typed_domains_are_taken_whole")),
        Mutant("Q-record-the-identity-accepts-an-opaque-value", "a record's identity may be a Passive, a Sealed or a decoded object (it is not held to be text)", CANON,
               '    if not isinstance(identity, str):   # the identity is text: what the decoder issued is refused (a programming error), anything else is a member that cannot be named\n        _wrong("identity", identity, "text")\n', "",
               (COPY + "test_the_variants_each_fail_where_the_value_is_read", CC + "test_the_identity_takes_text_not_what_the_decoder_issued"), (CONTROL,)),
        Mutant("Q-download-is-readable", "`Response.download()` hands out the bytes", RESPONSE,
               "        return Sealed(self._body)\n", "        return self._body\n",
               (EXIT + "test_a_download_is_sealed_and_only_the_router_boundary_makes_it_bytes", PLACE + "test_a_downloads_bytes_are_sealed_until_the_router_boundary_and_bytes_after_it",
                SP + "ResponseIsSealed.test_the_responses_public_names_are_a_closed_list_none_of_them_a_payload_accessor_and_its_one_door_is_sealed"),
               (CONTROL,)),
        Mutant("Q-router-does-not-materialize-the-answer", "the router serializes records with provenance still sealed: raw, passive values and a download's bytes leave as the objects", ROUTER,
               "    out = plain(out)\n", "",
               (PLACE + "test_after_it_every_operations_answer_is_plain_json_with_no_sealed_passive_or_decoded_object_left", PLACE + "test_a_downloads_bytes_are_sealed_until_the_router_boundary_and_bytes_after_it"),
               (PLACE + "test_the_index_load_writes_plain_data_never_the_object_it_holds",)),
        Mutant("Q-index-does-not-materialize-what-it-stores", "the index load writes a record whose provenance is still sealed", INDEX,
               "    record = plain(record)   #", "    #",
               (PLACE + "test_the_index_load_writes_plain_data_never_the_object_it_holds", PLACE + "test_the_index_load_of_a_crossref_page_stores_the_passive_counts_as_plain_numbers"),
               (PLACE + "test_after_it_every_operations_answer_is_plain_json_with_no_sealed_passive_or_decoded_object_left",)),
        Mutant("Q-cache-does-not-materialize-what-it-stores", "the cache persists a record whose provenance is still sealed", "research_gateway/core/cache.py",
               '        record = plain(record)\n        key = ident.canonical(record["identity"])', '        key = ident.canonical(record["identity"])',
               (PLACE + "test_the_cache_is_a_storage_boundary_too_in_memory_and_in_the_database",), (PLACE + "test_the_index_load_writes_plain_data_never_the_object_it_holds",)),
        Mutant("Q-sealed-two-sealed-objects-compare", "two Sealed objects compare equal by value again: `make_record(raw=literal)[\"raw\"] == row.raw` reads the raw object by guessing it (Astra's first R13C-2 mutant)", PAYLOAD,
               "        if isinstance(other, Sealed):\n            raise SealedRead(", "        if isinstance(other, Sealed):\n            return _same(self._value, other._value)\n            raise SealedRead(",
               (EXIT + "test_no_two_sealed_objects_compare_whoever_made_them_and_a_sealed_equals_no_plain_value", CC + "test_a_literal_passed_as_raw_has_no_comparison_with_a_decoded_object",
                SP + "RawIsSealedAndLeavesAsACopy.test_a_sealed_object_is_stored_and_not_read_and_compares_with_no_other_sealed_object"),
               (TC + "test_the_same_object_twice_is_the_same_and_a_different_one_is_not", CONTROL)),
        Mutant("Q-sealed-a-decoded-object-compares-with-anything", "`Rec == x` compares a decoded object with anything again (the other side's raw, a literal)", PAYLOAD,
               '        raise SealedRead("a decoded object is compared with another by Rec.same_as, and with nothing else")\n', "        return isinstance(other, Rec) and self.same_as(other)\n",
               (EXIT + "test_a_decoded_object_compares_with_nothing_and_is_not_hashable",), (TC + "test_the_same_object_twice_is_the_same_and_a_different_one_is_not", CONTROL)),
        Mutant("Q-sealed-same-as-takes-a-value-an-adapter-wrote", "`Rec.same_as` accepts any object: a decoded object is compared with a literal an adapter chose", PAYLOAD,
               '        if not isinstance(other, Rec):\n            raise TypeError("same_as compares two decoded objects")\n        return _same(self._raw, other._raw)',
               '        return _same(self._raw, other._raw if isinstance(other, Rec) else getattr(other, "_value", other))',
               (TC + "test_it_takes_two_decoded_objects_and_nothing_else",), (TC + "test_the_same_object_twice_is_the_same_and_a_different_one_is_not", CONTROL)),
        Mutant("Q-sealed-construction-is-no-listed-door", "a Sealed, a Passive or a Rec built in a provider module is not listed by the inventory of doors", "tests/inventory.py",
               'CONSTRUCTORS = ("MemberList", "Sealed", "Passive", "Rec")', 'CONSTRUCTORS = ("MemberList",)',
               (EXIT + "test_constructing_a_sealed_a_passive_or_a_rec_in_a_provider_module_is_listed",), ("tests.test_inventory.Inventory.test_each_entry_has_a_known_role_that_may_stand_there_and_a_reason",)),
    ]
