"""Task 2b-repair-13a: the gateway mutants of the decoder's completed contract.

Repair-12 declared a schema per operation and one decoder; its review (Astra) and Gate D #1 found three gaps in the decoder's contract with the rest of the gateway, and 2b-repair-13a closes
each as a property of the decoder. The mutants here remove one guard of each property in a temporary copy, and name the tests that must notice:

  T-*  the failure channel is total: scalar conversions and consistency rules cannot raise past the member boundary, and the answer's bytes are opened inside the same channel;
  S-*  the payload is sealed and metadata is passive: the Response holds nothing to read, a decoded `any_()` cannot be read, the raw object leaves only as a copy, doi.org's whole answer crosses
       the decoder, DOAJ's CSV does too;
  D-*  declarations are complete for what decides: a field of Astra's three catalogue families declared `any_()` again, and a union branch's field declared loosely (the reach of the derived pass);
  N-*  per-operation null policy;
  X-*  the shape of a structure reference;
  I-*  deduplication by identity.

A mutant that needs two edits (a guard with two layers: the helper's own and the wrapper's) carries both. A killer must FAIL in its assertions, not error: the tests in tests/test_decoder_total.py
turn an exception that escapes the channel into an assertion failure for that reason.
"""
from __future__ import annotations

SCHEMA = "research_gateway/core/schema.py"
WIRE = "research_gateway/core/wire.py"
PAYLOAD = "research_gateway/core/payload.py"
RESPONSE = "research_gateway/adapters/_response.py"
DT, SP, DC = "tests.test_decoder_total.", "tests.test_sealed_payload.", "tests.test_declarations."
SC, NP, FB, CD, IO = "tests.test_schema.", "tests.test_null_policy.", "tests.test_flow_binding.", "tests.test_cache_dedup.", "tests.test_identity_only."
CORR = "tests.test_schema_corruption."
YEARS = DT + "YearsThroughRealOperations."
TOTAL = DT + "TheDecoderOnlyEverRaisesPayloadError."


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        # ---------------------------------------------------------------- the failure channel is total
        Mutant("T-year-conversion-unguarded", "`int()` of digits it refuses (a superscript, a 4,301-digit string) raises ValueError past the member boundary: both the helper's and the wrapper's catch removed", SCHEMA,
               ('        try:\n            value = int(value)\n        except ValueError:\n            raise PayloadError(f"a year is text that is not a number ({len(value)} characters)") from None\n',
                '    except Exception as e:   # a normalizer reads nothing but `v`: nothing it raises is a programming error of the caller\'s\n        raise PayloadError(f"{_where(at)}: {_kind(v)} cannot be read as a {kind} ({type(e).__name__})") from None\n'),
               ('        value = int(value)\n', '    except ZeroDivisionError:\n        raise\n'),
               (YEARS + "test_a_year_that_cannot_be_read_costs_its_member_and_nothing_beside_it", YEARS + "test_gate_ds_three_works_through_the_router",
                TOTAL + "test_a_malformed_answer_is_never_any_other_error_when_the_bytes_are_opened_by_the_decoder"),
               (YEARS + "test_control_numerals_that_int_reads_are_years",)),
        Mutant("T-normalizer-bypasses-the-wrapper", "the decoder calls a scalar normalizer directly instead of through `_normalized`", SCHEMA,
               '    if k in _NORMALIZERS:\n        return _normalized(at, k, v)\n', '    if k in _NORMALIZERS:\n        return _NORMALIZERS[k](v)\n',
               (DT + "ScalarNormalizers.test_every_normalizer_is_called_through_the_one_wrapper",),
               (YEARS + "test_control_numerals_that_int_reads_are_years",)),
        Mutant("T-rule-failure-escapes", "a consistency rule that fails on a provider's value raises out of the decoder instead of being the object's failure", SCHEMA,
               '    except MEMBER_ERRORS as e:\n        raise PayloadError(f"{_where(at)}: the rule could not read the answer ({type(e).__name__})") from None\n', '',
               (DT + "RulesAndProgrammingErrors.test_a_rule_that_fails_on_a_providers_value_is_the_objects_failure_not_an_escaping_exception",),
               (DT + "RulesAndProgrammingErrors.test_a_rule_that_reads_what_the_schema_does_not_declare_is_a_programming_error_and_passes",)),
        Mutant("T-member-errors-omit-arithmetic-and-recursion", "the errors a member's own reading may raise leave out ArithmeticError and RecursionError", PAYLOAD,
               'MEMBER_ERRORS = (PayloadError, KeyError, TypeError, AttributeError, ValueError, IndexError, ArithmeticError, RecursionError)',
               'MEMBER_ERRORS = (PayloadError, KeyError, TypeError, AttributeError, ValueError, IndexError)',
               (DT + "RulesAndProgrammingErrors.test_a_rule_that_fails_on_a_providers_value_is_the_objects_failure_not_an_escaping_exception",),
               (DT + "RulesAndProgrammingErrors.test_a_rule_that_reads_what_the_schema_does_not_declare_is_a_programming_error_and_passes",)),
        Mutant("T-nesting-recursion-escapes-the-parse", "JSON nested past the interpreter's own limit raises RecursionError out of the opener", WIRE,
               '    except RecursionError:   # nesting past the interpreter\'s own limit is not JSON any provider sends\n        raise Malformed(f"JSON nested more than {MAX_DEPTH} levels deep") from None\n', '',
               (TOTAL + "test_a_malformed_answer_is_never_any_other_error_when_the_bytes_are_opened_by_the_decoder",
                TOTAL + "test_nesting_past_the_gateways_operational_limit_is_refused_at_its_edge_and_nesting_within_it_is_read"),
               (TOTAL + "test_the_adapter_facing_decode_takes_the_clients_response_and_nothing_else",)),
        Mutant("T-nesting-unbounded", "an answer nested deeper than the gateway's limit is read", WIRE,
               '        if depth > limit:\n            raise Malformed(f"JSON nested more than {limit} levels deep")\n', '        if False:\n            raise Malformed(f"JSON nested more than {limit} levels deep")\n',
               (TOTAL + "test_nesting_past_the_gateways_operational_limit_is_refused_at_its_edge_and_nesting_within_it_is_read",),
               (TOTAL + "test_a_malformed_answer_is_never_any_other_error_when_the_bytes_are_opened_by_the_decoder",)),
        # ---------------------------------------------------------------- the payload is sealed and metadata is passive
        Mutant("S-the-response-exposes-its-parsed-payload", "the client's Response has a `json` property again", RESPONSE,
               '    def download(self) -> Sealed:\n',
               '    @property\n    def json(self):\n        import json\n        return json.loads(self._body)\n\n    def download(self) -> Sealed:\n',
               (SP + "ResponseIsSealed.test_the_responses_public_names_are_a_closed_list_none_of_them_a_payload_accessor_and_its_one_door_is_sealed",
                SP + "ResponseIsSealed.test_astras_prefilter_mutant_has_nothing_to_find_and_fails_loudly_instead_of_passing_quietly"),
               (SP + "ResponseIsSealed.test_decode_reads_the_payload_through_its_declared_schema_and_the_responses_other_names_do_not_show_it",)),
        Mutant("S-the-adapters-decode-takes-any-value", "an adapter may decode a value it parsed or copied out, not only the client's response", "research_gateway/adapters/base.py",
               '    if not isinstance(resp, Response):\n        raise TypeError(', '    if False:\n        raise TypeError(',
               (TOTAL + "test_the_adapter_facing_decode_takes_the_clients_response_and_nothing_else",),
               (SP + "ResponseIsSealed.test_decode_reads_the_payload_through_its_declared_schema_and_the_responses_other_names_do_not_show_it",)),
        Mutant("S-a-declared-any-is-readable", "an `any_()` field is handed over as the bare value, so anything may read it", SCHEMA,
               'def _passive(s: Spec, v, at: tuple):\n    return Passive(v)\n', 'def _passive(s: Spec, v, at: tuple):\n    return v\n',
               (DC + "EnforcedByTheDecoder.test_bea_dataset_names_declared_untyped", DC + "EnforcedByTheDecoder.test_bls_survey_abbreviations_declared_untyped",
                DC + "EnforcedByTheDecoder.test_fred_series_ids_declared_untyped", SP + "PassiveIsOnlyStored.test_the_listed_ways_of_reading_a_declared_any_field_raise"),
               (DC + "EnforcedByTheDecoder.test_control_the_typed_declarations_read_and_the_same_operations_are_complete",)),
        Mutant("S-a-field-left-out-is-readable", "an `any_()` field that is left out or null is handed over as a bare None", SCHEMA,
               '        return Passive(fs.default if missing else None)\n', '        return fs.default if missing else None\n',
               (SP + "PassiveIsOnlyStored.test_a_field_left_out_or_null_is_a_passive_too_and_is_none_cannot_tell_it_from_one_that_is_there",),
               (SC + "Leaves.test_text_is_text_or_nothing",)),
        Mutant("S-the-raw-object-is-readable", "`Rec.raw` hands out the provider's object itself, not a sealed one", PAYLOAD,
               '        """The object as the provider sent it, sealed: for a record\'s `raw=`, never for reading or comparing."""\n        return Sealed(self._raw)\n',
               '        """The object as the provider sent it, sealed: for a record\'s `raw=`, never for reading or comparing."""\n        return self._raw\n',
               (SP + "RawIsSealedAndLeavesAsACopy.test_a_sealed_object_is_stored_and_not_read_and_compares_with_no_other_sealed_object",),
               (SP + "RawIsSealedAndLeavesAsACopy.test_an_unreadable_member_is_sealed_too_and_says_only_whether_it_was_an_object",)),
        Mutant("S-the-raw-object-leaves-as-an-alias", "`plain()` hands out the object the decoder kept, not a copy of it", PAYLOAD,
               '    if isinstance(value, (Sealed, Passive)):\n        return plain(value._value)\n', '    if isinstance(value, (Sealed, Passive)):\n        return value._value\n',
               (SP + "RawIsSealedAndLeavesAsACopy.test_it_leaves_as_a_copy_at_every_level_and_each_exit_is_its_own", SP + "PassiveIsOnlyStored.test_plain_hands_out_a_copy_and_a_record_keeps_a_passive_value_passive_until_it_is_materialized"),
               (SP + "RawIsSealedAndLeavesAsACopy.test_without_takes_fields_out_of_the_copy_and_the_original_keeps_them",)),
        Mutant("S-doi-org-decides-before-the-whole-answer-is-decoded", "an unreadable doi.org answer is remembered as the prefix's `unknown`", "research_gateway/core/identity.py",
               '        rows = S.decode("doi.org", RA_ROWS, resp)\n',
               '        try:\n            rows = S.decode("doi.org", RA_ROWS, resp)\n        except PayloadError:\n            self._cache[prefix] = "unknown"\n            return "unknown"\n',
               ("tests.test_schema_corruption.LookupCorruptions.test_the_outer_shapes_that_skipped_the_decoder_and_cached_unknown", "tests.test_schema_corruption.LookupCorruptions.test_every_declared_position_every_wrong_kind"),
               ("tests.test_typed_fields.RegistrationAgency.test_control_text_is_the_agency_and_no_agency_is_unknown",)),
        Mutant("S-the-doaj-dump-is-opened-without-its-header-check", "a CSV without the title column is read as a dump of journals", SCHEMA,
               '    if missing:\n        raise PayloadError(f"{source_id}: the CSV shape changed:', '    if False:\n        raise PayloadError(f"{source_id}: the CSV shape changed:',
               (CORR + "CsvCorruptions.test_every_column_left_out_of_the_header_costs_the_load_only_when_the_loader_needs_it",),
               (CORR + "CsvCorruptions.test_the_valid_dump_loads_and_every_column_is_one_the_schema_declares",)),
        Mutant("S-the-csv-parse-error-escapes", "a CSV the opener refuses raises its own error out of the decoder", SCHEMA,
               '    except wire.Malformed as e:\n        raise PayloadError(f"{source_id}: the CSV does not parse ({e})") from None\n', '    except ZeroDivisionError:\n        raise\n',
               (CORR + "CsvCorruptions.test_a_cell_past_the_field_limit_and_a_file_with_no_usable_header_are_unreadable_not_empty",
                CORR + "CsvCorruptions.test_a_dump_whose_serialized_framing_is_broken_is_unreadable_not_shorter_or_empty"),
               (CORR + "CsvCorruptions.test_the_valid_dump_loads_and_every_column_is_one_the_schema_declares",)),
        # ---------------------------------------------------------------- declarations are complete for what decides
        Mutant("D-bea-dataset-name-declared-any", "BEA's catalogue declares the dataset name `any_()` again", "research_gateway/adapters/bea.py",
               '{"Dataset": _rows(S.obj({"DatasetName": S.maybe_key(), "DatasetDescription": S.text()}))}', '{"Dataset": _rows(S.obj({"DatasetName": S.any_(), "DatasetDescription": S.text()}))}',
               (DC + "DecisionFieldsAreKinds.test_each_is_a_concrete_kind_in_the_schema", DC + "DecisionFieldsAreKinds.test_a_catalogues_identifiers_and_selectors_are_refused_in_every_wrong_kind_and_the_falsy_ones_are_not_silently_dropped"),
               (DC + "AuditedInventory.test_every_role_is_passive_and_every_use_says_why",)),
        Mutant("D-bls-survey-abbreviation-declared-any", "BLS's catalogue declares the survey abbreviation `any_()` again", "research_gateway/adapters/bls.py",
               '"survey_abbreviation": S.maybe_key(), "survey_name": S.text(default="")', '"survey_abbreviation": S.any_(), "survey_name": S.text(default="")',
               (DC + "DecisionFieldsAreKinds.test_each_is_a_concrete_kind_in_the_schema", DC + "DecisionFieldsAreKinds.test_a_catalogues_identifiers_and_selectors_are_refused_in_every_wrong_kind_and_the_falsy_ones_are_not_silently_dropped"),
               (DC + "AuditedInventory.test_every_role_is_passive_and_every_use_says_why",)),
        Mutant("D-fred-series-id-declared-any", "FRED's catalogue declares the series id `any_()` again", "research_gateway/adapters/fred.py",
               'CATALOG = S.obj({"seriess": S.required(S.own(S.obj({"id": S.maybe_key(), "title": S.text(),', 'CATALOG = S.obj({"seriess": S.required(S.own(S.obj({"id": S.any_(), "title": S.text(),',
               (DC + "DecisionFieldsAreKinds.test_each_is_a_concrete_kind_in_the_schema", DC + "DecisionFieldsAreKinds.test_a_catalogues_identifiers_and_selectors_are_refused_in_every_wrong_kind_and_the_falsy_ones_are_not_silently_dropped"),
               (DC + "AuditedInventory.test_every_role_is_passive_and_every_use_says_why",)),
        Mutant("D-a-catalogue-label-declared-any", "FRED's catalogue declares the title it shows `any_()` again", "research_gateway/adapters/fred.py",
               '"id": S.maybe_key(), "title": S.text(), "units": S.text(),',
               '"id": S.maybe_key(), "title": S.any_(), "units": S.text(),',
               (DC + "DecisionFieldsAreKinds.test_each_is_a_concrete_kind_in_the_schema",),
               (DC + "AuditedInventory.test_every_role_is_passive_and_every_use_says_why",)),
        Mutant("D-a-union-branchs-field-declared-loosely", "Dataverse's licence object branch declares its `name` `any_()`: only the reach of the derived pass into the branch notices", "research_gateway/adapters/harvard_dataverse.py",
               'LICENSE = S.oneof(S.obj({"name": S.text()}), S.text())', 'LICENSE = S.oneof(S.obj({"name": S.any_()}), S.text())',
               (CORR + "ReachMatchesTheDeclarations.test_the_union_branches_that_hold_fields_are_in_the_inventory_and_were_reached",),
               (CORR + "ReachMatchesTheDeclarations.test_the_loaders_pages_and_the_direct_resolves_are_in_the_inventory_too",)),
        # ---------------------------------------------------------------- per-operation null policy
        Mutant("N-semanticscholar-null-data-is-left-out", "Semantic Scholar's `data` is declared like any list: a present null is an omitted field", "research_gateway/adapters/semanticscholar.py",
               '"data": S.never_null(S.members(PAPER, empty_when=("total",)))', '"data": S.members(PAPER, empty_when=("total",))',
               (NP + "SemanticScholarNull.test_the_four_cases_data_null_with_total_zero_are_unreadable_with_no_count", NP + "SemanticScholarNull.test_the_declaration_is_this_operations_alone"),
               (NP + "SemanticScholarNull.test_controls_an_omitted_data_and_an_empty_array_beside_total_zero_are_the_accepted_empty_answer",)),
        Mutant("N-the-decoder-erases-never-null", "the decoder reads a `never_null` field that is null as left out", SCHEMA,
               '    if raw is None and fs.never_null:\n', '    if False and fs.never_null:\n',
               (SC + "Containers.test_never_null_tells_a_field_that_is_left_out_from_one_that_is_sent_null", NP + "SemanticScholarNull.test_the_four_cases_data_null_with_total_zero_are_unreadable_with_no_count"),
               (NP + "SemanticScholarNull.test_controls_an_omitted_data_and_an_empty_array_beside_total_zero_are_the_accepted_empty_answer",)),
        # ---------------------------------------------------------------- the shape of a structure reference
        Mutant("X-references-counted-after-filtering", "the Refs of a flow are counted after those with no id are set aside", "research_gateway/core/sdmx.py",
               '    refs = [r["@*"] for st in structures for r in st["Ref"]]\n    urns', '    refs = [r["@*"] for st in structures for r in st["Ref"] if r["@*"].get("id")]\n    urns',
               (FB + "ReferenceShape.test_the_astra_cases_for_both_providers_are_unreadable_and_the_controls_read",),
               (FB + "ReferenceShape.test_a_lone_ref_that_names_nothing_and_a_urn_alone_stay_the_conservative_refusal_and_are_not_unreadable",)),
        Mutant("X-fixed-reference-attributes-unchecked", "a data structure reference may state `package` and `class` with any value", "research_gateway/core/sdmx.py",
               '            if name in ref and ref[name] != fixed:\n', '            if False:\n',
               (FB + "ReferenceShape.test_the_astra_cases_for_both_providers_are_unreadable_and_the_controls_read", FB + "ReferenceShape.test_the_fixed_attributes_are_checked_even_when_the_ref_names_nothing"),
               (FB + "ReferenceShape.test_the_fixed_attributes_may_be_stated_with_their_own_values",)),
        Mutant("X-a-nameless-ref-beside-a-urn-is-read-as-the-urn-alone", "a Ref that names no id beside a URN is treated as a URN alone", "research_gateway/core/sdmx.py",
               '        if urns:\n            raise PayloadError("a dataflow whose structure Ref names no id beside a URN: they cannot be shown to name the same structure")\n', '',
               (FB + "ReferenceShape.test_a_ref_that_names_nothing_beside_a_urn_cannot_be_shown_to_name_the_same_structure",),
               (FB + "ReferenceShape.test_a_lone_ref_that_names_nothing_and_a_urn_alone_stay_the_conservative_refusal_and_are_not_unreadable",)),
        # ---------------------------------------------------------------- deduplication by identity
        Mutant("I-a-fuzzy-match-merges", "records of different identities with a similar title, the same year and the same first author are merged", "research_gateway/core/dedup.py",
               '        hit = by_identity.get(key)\n        if hit is None:\n            merged = dict(rec)',
               '        hit = by_identity.get(key)\n        if hit is None:\n            hit = next((c for c in out if c.get("kind") == rec.get("kind") and _alike(c, rec, THRESHOLD) is not None), None)\n        if hit is None:\n            merged = dict(rec)',
               (CD + "Dedup.test_a_fuzzy_match_never_merges_anything", CD + "Dedup.test_distinct_dois_never_merge_whatever_else_they_share", IO + "IdentityOnly.test_two_distinct_dois_with_the_same_title_year_and_author_are_two_candidates"),
               (CD + "Dedup.test_exact_identity_merges_across_case_and_prefix", IO + "IdentityOnly.test_controls_a_different_year_is_two_candidates_and_no_suggestion_and_the_same_doi_is_one")),
        Mutant("I-the-look-alike-is-not-recorded", "the answer carries no linkage suggestion for candidates that look alike", "research_gateway/core/router.py",
               '        if linked:\n            out["linkage_suggestions"] = linked\n', '        if False:\n            out["linkage_suggestions"] = linked\n',
               (IO + "IdentityOnly.test_the_look_alike_is_recorded_as_a_suggestion_for_a_later_assessment_with_both_provenances",),
               (IO + "IdentityOnly.test_two_distinct_dois_with_the_same_title_year_and_author_are_two_candidates",)),
        Mutant("I-a-suggestion-forgets-the-differing-dois", "a linkage suggestion no longer names the identifiers its two sides state differently", "research_gateway/core/dedup.py",
               '                    "differing_identifiers": {k: [ids_a[k], ids_b[k]] for k in sorted(set(ids_a) & set(ids_b)) if ids_a[k] and ids_b[k] and ids_a[k] != ids_b[k]},',
               '                    "differing_identifiers": {},',
               (CD + "Dedup.test_what_looks_alike_is_a_linkage_suggestion_with_provenance_and_decides_nothing", IO + "IdentityOnly.test_the_look_alike_is_recorded_as_a_suggestion_for_a_later_assessment_with_both_provenances"),
               (CD + "Dedup.test_distinct_dois_never_merge_whatever_else_they_share",)),
    ]
