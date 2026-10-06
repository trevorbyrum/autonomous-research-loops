"""Task 2q-b4: the decoder's dispatch (core/schema.py `_decode`) reads each kind with its own decoder, and a kind no decoder reads is not a value.

`_decode` used to be one chain of branches (cyclomatic 64). It is now a dispatch on the spec's kind to one decoder per kind, in three families: scalars, policies (what a failure
costs) and containers. What the dispatch itself decides is tested here: that a kind in no family is a programming error and never a value (the answer's, a member's or a field's),
and that a kind reaches ITS decoder — a list of members loses only the member that cannot be read, a keyed container's entries are each read alone and it is an object, a soft kind says nothing
where an isolated or a maybe one is unreadable or fails, and a number is read as a number where a year is read as a year.
What each decoder decides is tested where it always was (tests/test_schema.py, tests/test_member_decoding.py).
"""
from __future__ import annotations

import unittest

from research_gateway.core import schema as S
from research_gateway.core.payload import MemberList, PayloadError


class Decoders(unittest.TestCase):
    def decoded(self, spec, value):
        """The decoder's answer; the test fails (an assertion, not an error) when it refuses the whole answer."""
        try:
            return S.decode("t", spec, value)
        except PayloadError as e:
            self.fail(f"the decoder refused the whole answer: {e}")


class Dispatch(Decoders):
    def test_a_kind_no_decoder_reads_is_a_programming_error_and_never_a_value(self):
        unknown = S.Spec("nonsense")
        for where, spec, value in (("the answer", unknown, 1), ("a member", S.members(unknown), [1]), ("a field", S.obj({"f": unknown}), {"f": 1}),
                                   ("an entry", S.entries(unknown), {"k": 1}), ("an alternative", S.oneof(S.flag(), unknown), 1)):
            with self.subTest(where=where):
                try:
                    got = S.decode("t", spec, value)
                except PayloadError as e:   # a PayloadError is a ValueError: a member, an isolated or a soft field would take it for its own loss
                    self.fail(f"an unknown kind was taken for the provider's failure: {e}")
                except ValueError as e:
                    self.assertEqual(str(e), "unknown schema kind 'nonsense'")
                else:
                    self.fail(f"an unknown kind decoded to {got!r}")

    def test_control_every_kind_a_constructor_builds_for_a_value_decodes_one(self):
        wrapped = S.obj({"a": S.whole()})
        for spec, value in ((S.text(), "x"), (S.key(), "k"), (S.maybe_key(), None), (S.flag(), True), (S.whole(), 1), (S.number(), 1.5), (S.year(), "2020"), (S.token(), "c"), (S.any_(), {"a": 1}),
                            (S.soft(S.text()), 1), (S.isolated(S.text()), 1), (S.maybe(S.text()), None), (S.oneof(S.flag(), S.text()), "x"), (wrapped, {"a": 1}), (S.own(S.whole()), [1]),
                            (S.members(S.whole()), [1]), (S.grid(S.text(), S.whole()), [["h"], [1]]), (S.lookup(S.whole()), [1]), (S.entries(S.whole()), {"a": 1}), (S.table(S.whole()), {"a": 1})):
            with self.subTest(kind=spec.kind):
                self.decoded(spec, value)


class ContainersReachTheirOwnDecoder(Decoders):
    def test_a_list_of_members_loses_only_the_member_that_cannot_be_read(self):
        got = self.decoded(S.members(S.whole()), [1, "x", 3])
        self.assertIsInstance(got, MemberList)
        self.assertEqual(got.each(lambda m: m), [1, None, 3])

    def test_the_entries_of_a_keyed_container_are_each_read_alone(self):
        got = self.decoded(S.entries(S.whole()), {"a": 1, "b": "x", "c": 3})
        self.assertIsInstance(got, MemberList)
        self.assertEqual(got.each(lambda e: (e["key"], e["value"])), [("a", 1), None, ("c", 3)])

    def test_control_a_list_of_members_and_a_keyed_container_that_are_readable_hold_what_was_sent(self):
        self.assertEqual(len(self.decoded(S.members(S.whole()), [1, 2])), 2)
        self.assertEqual(len(self.decoded(S.entries(S.whole()), {"a": 1})), 1)

    def test_a_keyed_container_is_an_object_whatever_else_it_is_sent_as(self):
        for spec in (S.entries(S.whole()), S.table(S.whole())):
            for wrong in ([], [1], "x", 5, True):
                with self.subTest(kind=spec.kind, wrong=repr(wrong)):
                    try:
                        got = S.decode("t", spec, wrong)
                    except PayloadError as e:
                        self.assertIn("where an object belongs", str(e))
                    else:
                        self.fail(f"a keyed container was read from {wrong!r}: {got!r}")


class PoliciesAndScalarsReachTheirOwnDecoder(Decoders):
    def test_a_soft_kind_says_nothing_and_an_isolated_one_is_unreadable_in_its_place(self):
        soft = self.decoded(S.members(S.soft(S.whole())), [1, "x"])
        isolated = self.decoded(S.members(S.isolated(S.whole())), [1, "x"])
        self.assertEqual((len(soft.unreadable()), len(isolated.unreadable())), (0, 1))

    def test_control_a_soft_and_an_isolated_kind_that_can_be_read_are_the_value(self):
        self.assertEqual(self.decoded(S.members(S.soft(S.whole())), [1]).each(lambda m: m), [1])
        self.assertEqual(self.decoded(S.members(S.isolated(S.whole())), [1]).each(lambda m: m), [1])

    def test_a_maybe_kind_fails_where_a_soft_one_says_nothing(self):
        got = self.decoded(S.members(S.maybe(S.whole())), [1, "x", None])
        self.assertEqual((len(got.unreadable()), got.each(lambda m: m)), (1, [1, None, None]))

    def test_control_a_maybe_kind_that_can_be_read_is_the_value_or_nothing(self):
        self.assertEqual(self.decoded(S.members(S.maybe(S.whole())), [1, None]).each(lambda m: m), [1, None])

    def test_a_number_is_read_as_a_number_and_a_year_as_a_year(self):
        self.assertEqual(self.decoded(S.number(), 2.5), 2.5)
        self.assertEqual(self.decoded(S.year(), "2021"), 2021)

    def test_control_a_whole_number_is_a_number_and_a_year_alike(self):
        self.assertEqual((self.decoded(S.number(), 7), self.decoded(S.year(), 7)), (7, 7))
