"""Task 2b-repair-13c: the gateway mutants of opaque provenance (Astra R13A-2).

A record's `raw`, its passive `extra` values and a download's bytes stay opaque from the moment an adapter builds the record until the router (or the index) serializes it; no adapter code can
read them, so no selection or coverage decision can depend on them. The mutants here remove ONE part of that construction in a temporary copy:

  Q-record-*   `make_record` materializes provenance again, aliases its input, accepts an opaque value in a typed field, or leaves a plain raw readable;
  Q-download-* `Response.download()` hands out the bytes;
  Q-router-*   the router does not materialize the answer at its boundary; Q-index-* / Q-cache-* the index load and the cache do not materialize what they store;
  Q-sealed-*   a Sealed an adapter constructs can be compared with (guessing a raw object), and a Sealed or a Passive built in a provider module is no listed door.

A killer must FAIL in its assertions, not error (tools/gen2_gateway_mutations.py). A control takes the accepted path through the same code.
"""
from __future__ import annotations

CANON = "research_gateway/core/canonical.py"
PAYLOAD = "research_gateway/core/payload.py"
BASE = "research_gateway/adapters/base.py"
ROUTER = "research_gateway/core/router.py"
INDEX = "research_gateway/harvest/index.py"
OP = "tests.test_opaque_provenance."
COPY, EXIT, PLACE = OP + "TheCopyEscape.", OP + "EveryExit.", OP + "WhereItBecomesPlain."
MI = "tests.test_member_isolation."
SP = "tests.test_sealed_payload."
ASTRA = "tests.test_astra_13a.R13A2."
CONTROL = ASTRA + "test_the_unmodified_adapter_keeps_all_three_citations"


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("Q-record-materializes-its-provenance", "`make_record` returns `plain(record)` again: the raw object and the passive values are readable in the returned dictionary (Astra's copy escape)", CANON,
               '    rec["raw"] = raw if raw is None or isinstance(raw, Sealed) else Sealed(plain(raw), _issued=True)\n    return rec\n',
               '    rec["raw"] = raw if raw is None or isinstance(raw, Sealed) else Sealed(plain(raw), _issued=True)\n    return plain(rec)\n',
               (ASTRA + "test_astras_mutant_cannot_read_the_copy_it_made_so_it_fails_loudly_instead_of_dropping_a_candidate", COPY + "test_the_variants_each_fail_where_the_value_is_read",
                COPY + "test_each_variant_run_through_the_real_adapter_and_router_is_never_a_complete_lane",
                EXIT + "test_a_record_is_a_plain_dict_with_plain_typed_fields_and_opaque_provenance", PLACE + "test_before_the_routers_boundary_every_operations_records_still_hold_a_sealed_raw",
                SP + "RawIsSealedAndLeavesAsACopy.test_a_records_raw_is_sealed_in_the_record_and_each_materialization_is_a_copy_independent_of_the_decoders"),
               (CONTROL, PLACE + "test_after_it_every_operations_answer_is_plain_json_with_raw_as_what_the_provider_sent")),
        Mutant("Q-record-a-plain-raw-is-left-readable", "a raw that is a plain value is stored as the (copied) dictionary instead of sealed", CANON,
               'Sealed(plain(raw), _issued=True)', 'plain(raw)',
               (EXIT + "test_a_raw_that_is_a_plain_value_is_sealed_too",), (CONTROL, EXIT + "test_a_record_is_a_plain_dict_with_plain_typed_fields_and_opaque_provenance")),
        Mutant("Q-record-extra-is-materialized", "the values of `extra` are materialized in the record: a passive value is readable there", CANON,
               "rec.update({k: detach(v) for k, v in extra.items() if k not in rec})", "rec.update({k: plain(v) for k, v in extra.items() if k not in rec})",
               (COPY + "test_the_variants_each_fail_where_the_value_is_read", COPY + "test_each_variant_run_through_the_real_adapter_and_router_is_never_a_complete_lane",
                EXIT + "test_a_record_is_a_plain_dict_with_plain_typed_fields_and_opaque_provenance",
                SP + "PassiveIsOnlyStored.test_plain_hands_out_a_copy_and_a_record_keeps_a_passive_value_passive_until_it_is_materialized"),
               (CONTROL,)),
        Mutant("Q-record-extra-aliases-the-adapters-structure", "the record's `extra` holds the adapter's own list, not a copy of its structure", CANON,
               "rec.update({k: detach(v) for k, v in extra.items() if k not in rec})", "rec.update({k: v for k, v in extra.items() if k not in rec})",
               (EXIT + "test_extra_is_a_copy_of_the_structure_and_never_an_alias_of_the_adapters_list",), (CONTROL,)),
        Mutant("Q-record-a-typed-field-accepts-an-opaque-value", "a title, venue, licence, author list, link list, identifiers or year may be built from a Passive or a Sealed: the value comes back readable", CANON,
               '    refuse_opaque(value, f"a record\'s {name}")\n    return plain(value)\n', "    return plain(value)\n",
               (COPY + "test_the_variants_each_fail_where_the_value_is_read",), (CONTROL, EXIT + "test_a_record_is_a_plain_dict_with_plain_typed_fields_and_opaque_provenance")),
        Mutant("Q-record-the-identity-accepts-an-opaque-value", "a record's identity may be a Passive or a Sealed", CANON,
               '    refuse_opaque(identity, "a record\'s identity")\n', "",
               (COPY + "test_the_variants_each_fail_where_the_value_is_read",), (CONTROL,)),
        Mutant("Q-download-is-readable", "`Response.download()` hands out the bytes", BASE,
               "        return Sealed(self._body, _issued=True)\n", "        return self._body\n",
               (EXIT + "test_a_download_is_sealed_and_only_the_router_boundary_makes_it_bytes", PLACE + "test_a_downloads_bytes_are_sealed_until_the_router_boundary_and_bytes_after_it",
                SP + "ResponseIsSealed.test_the_responses_public_names_are_a_closed_list_none_of_them_a_payload_accessor_and_its_one_door_is_sealed"),
               (CONTROL,)),
        Mutant("Q-router-does-not-materialize-the-answer", "the router serializes records with provenance still sealed: raw, passive values and a download's bytes leave as the objects", ROUTER,
               "    out = plain(out)\n", "",
               (PLACE + "test_after_it_every_operations_answer_is_plain_json_with_raw_as_what_the_provider_sent", PLACE + "test_a_downloads_bytes_are_sealed_until_the_router_boundary_and_bytes_after_it"),
               (PLACE + "test_the_index_load_writes_plain_data_never_the_object_it_holds",)),
        Mutant("Q-index-does-not-materialize-what-it-stores", "the index load writes a record whose provenance is still sealed", INDEX,
               "    record = plain(record)   #", "    #",
               (PLACE + "test_the_index_load_writes_plain_data_never_the_object_it_holds", PLACE + "test_the_index_load_of_a_crossref_page_stores_the_passive_counts_as_plain_numbers"),
               (PLACE + "test_after_it_every_operations_answer_is_plain_json_with_raw_as_what_the_provider_sent",)),
        Mutant("Q-cache-does-not-materialize-what-it-stores", "the cache persists a record whose provenance is still sealed", "research_gateway/core/cache.py",
               '        record = plain(record)\n        key = ident.canonical(record["identity"])', '        key = ident.canonical(record["identity"])',
               (PLACE + "test_the_cache_is_a_storage_boundary_too_in_memory_and_in_the_database",), (PLACE + "test_the_index_load_writes_plain_data_never_the_object_it_holds",)),
        Mutant("Q-sealed-any-two-can-be-compared", "a Sealed an adapter constructs compares like one the decoder issued: `row.raw == Sealed({...})` reads the raw object by guessing it", PAYLOAD,
               "        if not (self._issued and other._issued):\n", "        if False:\n",
               (EXIT + "test_equality_is_not_a_way_to_read_a_sealed_object_by_guessing_it",), (SP + "RawIsSealedAndLeavesAsACopy.test_a_sealed_object_the_decoder_issued_can_be_compared_with_another_and_stored_and_not_read",)),
        Mutant("Q-sealed-construction-is-no-listed-door", "a Sealed or a Passive built in a provider module is not listed by the inventory of doors", MI.replace("tests.", "tests/").rstrip(".") + ".py",
               'CONSTRUCTORS = ("MemberList", "Sealed", "Passive")', 'CONSTRUCTORS = ("MemberList",)',
               (EXIT + "test_constructing_a_sealed_or_passive_in_a_provider_module_is_listed_and_so_is_the_issuing_flag",), (MI + "Reads.test_no_use_is_unexplained",)),
    ]
