"""Task 2q-b4: the gateway mutants of the decoder's dispatch (core/schema.py `_decode`, its three kind tables and `_keyed`).

`_decode` is a dispatch on the spec's kind to one decoder per kind; the branches of the chain it replaced were mutated where they stood (tools/gen2_gateway_schema_mutants.py, re-anchored
to the decoders they became), and the dispatch itself is new: what it does with a kind it has no decoder for, which decoder each row names, and the keyed containers' own check. Each mutant
breaks ONE of those in a temporary copy:

  K-an-unknown-kind-reads-as-metadata                 a kind no table names is carried as sent (`Passive`) instead of refused as a programming error;
  K-members-are-read-as-an-own-list, K-entries-are-read-as-a-table, K-a-soft-kind-is-read-as-isolated, K-an-isolated-kind-is-read-as-soft, K-a-maybe-kind-is-read-as-soft
                                                      a table row names the wrong decoder (what a failure inside a list, a keyed container or a field costs);
  K-a-number-is-read-as-a-year, K-a-year-is-read-as-a-number
                                                      the normalizing branch is given the wrong kind;
  K-a-keyed-container-of-any-kind-is-one              a value that is not an object reads as an empty keyed container.

A killer fails in its assertion and the controls take the accepted path through the same code (tests/test_decoder_families.py).
"""
from __future__ import annotations

SCHEMA = "research_gateway/core/schema.py"
DF = "tests.test_decoder_families."
DI, CT, PO = DF + "Dispatch.", DF + "ContainersReachTheirOwnDecoder.", DF + "PoliciesAndScalarsReachTheirOwnDecoder."
KINDS_READ = DI + "test_control_every_kind_a_constructor_builds_for_a_value_decodes_one"
READABLE_CONTAINERS = CT + "test_control_a_list_of_members_and_a_keyed_container_that_are_readable_hold_what_was_sent"
READABLE_POLICIES = PO + "test_control_a_soft_and_an_isolated_kind_that_can_be_read_are_the_value"
READABLE_NUMBERS = PO + "test_control_a_whole_number_is_a_number_and_a_year_alike"


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("K-an-unknown-kind-reads-as-metadata", "a kind that no decoder reads is carried as sent instead of refused", SCHEMA,
               '    raise ValueError(f"unknown schema kind {k!r}")\n', "    return Passive(v)\n",
               (DI + "test_a_kind_no_decoder_reads_is_a_programming_error_and_never_a_value",), (KINDS_READ,)),
        Mutant("K-members-are-read-as-an-own-list", "a list of independent members is read as one record's own list: one member that cannot be read costs the whole list", SCHEMA,
               '"members": _members,', '"members": _own,',
               (CT + "test_a_list_of_members_loses_only_the_member_that_cannot_be_read",), (READABLE_CONTAINERS,)),
        Mutant("K-entries-are-read-as-a-table", "the entries of a keyed container are read as one record's own table: one entry that cannot be read costs the whole container", SCHEMA,
               '"entries": _entries,', '"entries": _table,',
               (CT + "test_the_entries_of_a_keyed_container_are_each_read_alone",), (READABLE_CONTAINERS,)),
        Mutant("K-a-soft-kind-is-read-as-isolated", "a soft kind that cannot be read leaves an unreadable stand-in where it should say nothing", SCHEMA,
               '"soft": _soft,', '"soft": _isolated,',
               (PO + "test_a_soft_kind_says_nothing_and_an_isolated_one_is_unreadable_in_its_place",), (READABLE_POLICIES,)),
        Mutant("K-an-isolated-kind-is-read-as-soft", "an isolated kind that cannot be read says nothing where it should be unreadable in its place", SCHEMA,
               '"isolated": _isolated,', '"isolated": _soft,',
               (PO + "test_a_soft_kind_says_nothing_and_an_isolated_one_is_unreadable_in_its_place",), (READABLE_POLICIES,)),
        Mutant("K-a-maybe-kind-is-read-as-soft", "a `maybe` kind that is there and malformed says nothing instead of failing", SCHEMA,
               '"maybe": _maybe,', '"maybe": _soft,',
               (PO + "test_a_maybe_kind_fails_where_a_soft_one_says_nothing",), (PO + "test_control_a_maybe_kind_that_can_be_read_is_the_value_or_nothing",)),
        Mutant("K-a-number-is-read-as-a-year", "a number is normalized by the year's rule", SCHEMA,
               "        return _normalized(at, k, v)\n", '        return _normalized(at, "year", v)\n',
               (PO + "test_a_number_is_read_as_a_number_and_a_year_as_a_year",), (READABLE_NUMBERS,)),
        Mutant("K-a-year-is-read-as-a-number", "a year is normalized by the number's rule", SCHEMA,
               "        return _normalized(at, k, v)\n", '        return _normalized(at, "number", v)\n',
               (PO + "test_a_number_is_read_as_a_number_and_a_year_as_a_year",), (READABLE_NUMBERS,)),
        Mutant("K-a-keyed-container-of-any-kind-is-one", "a value that is not an object reads as an empty keyed container", SCHEMA,
               '    if not isinstance(v, dict):\n        raise _bad(at, v, "an object")\n    return v\n', "    if not isinstance(v, dict):\n        v = {}\n    return v\n",
               (CT + "test_a_keyed_container_is_an_object_whatever_else_it_is_sent_as",), (READABLE_CONTAINERS,)),
    ]
