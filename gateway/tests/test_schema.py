"""Task 2b-repair-12: the decoder (core/schema.py) states, for every kind of field and every container, what is missing, what is null and what is malformed.

This is the one place the accepted contracts about a provider's answer are written as the rules of a reader: a field a provider leaves out (or sends null) is the empty value
of its kind; one that is there and is not its kind is unreadable — `false`, `0`, `""`, `[]` and `{}` included, which a truthiness test takes for "nothing" (R8-2, R9-2); an
unreadable value costs what the nearest boundary around it costs (a member, an isolated field, nothing for a soft one, the answer otherwise). The adapters declare schemas
with these constructors and have no readers of their own; tests/test_schema_corruption.py walks every schema they declare, and tests/test_member_isolation.py states what
an adapter can reach.
"""
from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from research_gateway.core import schema as S
from research_gateway.core.payload import MemberList, Passive, PassiveRead, PayloadError, Rec, UndeclaredRead, Unreadable, plain

WRONG_TEXT = (False, True, 0, 5, 1.5, [], {}, ["x"], {"a": 1})


def one(spec: S.Spec, value, name: str = "f"):
    """The field `name` of an object that holds `value` there."""
    return S.decode("t", S.obj({name: spec}), {name: value})[name]


def absent(spec: S.Spec):
    return S.decode("t", S.obj({"f": spec}), {})["f"]


class Leaves(unittest.TestCase):
    def refuses(self, spec, wrong, value_ok=()):
        for value in wrong:
            with self.subTest(value=repr(value)), self.assertRaises(PayloadError):
                one(spec, value)

    def test_text_is_text_or_nothing(self):
        self.assertEqual([one(S.text(), v) for v in ("x", "", None)], ["x", "", None])
        self.assertIsNone(absent(S.text()))
        self.refuses(S.text(), WRONG_TEXT)

    def test_a_key_is_what_a_provider_names_a_member_by_as_sent(self):
        self.assertEqual((one(S.key(), "S1"), one(S.key(), 61), one(S.key(), " x ")), ("S1", 61, " x "))
        self.refuses(S.key(), (None, "", "  ", False, True, 0.5, [], {}, ["a"]))
        with self.assertRaises(PayloadError):
            absent(S.key())

    def test_a_maybe_key_may_name_nothing_but_not_the_wrong_kind(self):
        self.assertEqual([one(S.maybe_key(), v) for v in ("S1", 61, None, "", "  ")], ["S1", 61, None, "", "  "])
        self.refuses(S.maybe_key(), (False, True, 0.5, [], {}, ["a"]))
        self.assertEqual([one(S.maybe_key(only_empty=True), v) for v in ("S1", 61, None, "")], ["S1", 61, None, ""])
        self.refuses(S.maybe_key(only_empty=True), ("  ", False, [], {}))

    def test_a_flag_is_true_or_false_and_false_when_left_out(self):
        self.assertEqual([one(S.flag(), v) for v in (True, False, None)], [True, False, False])
        self.assertIs(absent(S.flag()), False)
        self.refuses(S.flag(), (0, 1, "", "no", "false", [], {}, 0.0, [True]))

    def test_a_whole_number_is_not_a_boolean_a_float_or_text(self):
        self.assertEqual([one(S.whole(), v) for v in (0, 7, None)], [0, 7, None])
        self.refuses(S.whole(), (False, True, 1.5, "7", [], {}))

    def test_a_year_is_a_whole_number_the_digits_of_one_or_an_integral_float(self):
        self.assertEqual([one(S.year(), v) for v in (2021, "2021", 2021.0, None)], [2021, 2021, 2021, None])
        self.refuses(S.year(), (False, True, [], {}, "x", "20x1", 1.5, "2021-03"))

    def test_a_token_is_a_non_blank_string(self):
        self.assertEqual([one(S.token(), v) for v in ("AoE", "x y")], ["AoE", "x y"])
        self.refuses(S.token(), (0, 3, -1, True, False, 1.5, "", "  ", [], {}, ["a"]))
        self.assertIsNone(one(S.token(), None), "left out or null, a cursor is none")
        self.assertIsNone(absent(S.token()))

    def test_any_is_carried_as_sent_and_its_default_is_for_a_field_that_is_left_out_not_null(self):
        for value in (False, 0, "", [], {}, [1], {"a": 1}, 1.5):
            got = one(S.any_(), value)
            self.assertIsInstance(got, Passive, "metadata is handed over passive: it can be stored and nothing else (tests/test_declarations.py)")
            self.assertEqual(plain(got), value)
        self.assertEqual((plain(absent(S.any_(default=False))), plain(one(S.any_(default=False), None))), (False, None))

    def test_text_may_name_what_it_is_when_it_is_left_out_and_only_then(self):
        self.assertEqual((absent(S.text(default="")), one(S.text(default=""), None), one(S.text(default=""), "x")), ("", None, "x"))
        self.refuses(S.text(default=""), WRONG_TEXT)

    def test_a_number_is_finite_and_not_a_boolean(self):
        self.assertEqual([one(S.number(), v) for v in (0, 7, 3599.5, -1, None)], [0, 7, 3599.5, -1, None])
        self.refuses(S.number(), (False, True, "7", [], {}, float("nan"), float("inf"), -float("inf")))

    def test_the_counts_a_provider_may_leave_a_list_out_for_is_the_whole_number_zero_only(self):
        self.assertTrue(S.counts_nothing(0))
        for other in (False, 0.0, "0", None, [], {}, 1, -1):
            self.assertFalse(S.counts_nothing(other), repr(other))


class WhatAFailureCosts(unittest.TestCase):
    ITEM = S.obj({"id": S.key(), "n": S.whole()})

    def test_a_malformed_member_is_that_members_loss_and_the_others_stand(self):
        items = S.decode("t", S.members(self.ITEM), [{"id": "a"}, 7, {"id": "b", "n": "x"}, {"id": False}, {"id": "c", "n": 3}])
        self.assertIsInstance(items, MemberList)
        self.assertEqual(items.each(lambda m: m["id"]), ["a", None, None, None, "c"])
        self.assertEqual([plain(u) for u in items.unreadable()], [7, {"id": "b", "n": "x"}, {"id": False}])
        self.assertEqual([u.was_object for u in items.unreadable()], [False, True, True])
        self.assertTrue(all(isinstance(u, Unreadable) and u.reason for u in items.unreadable()))

    def test_a_failure_nested_in_a_member_is_the_members_even_inside_its_own_lists(self):
        spec = S.members(S.obj({"id": S.key(), "tags": S.own(S.text())}))
        got = S.decode("t", spec, [{"id": "a", "tags": ["x", 5]}, {"id": "b", "tags": ["y"]}])
        self.assertEqual(got.each(lambda m: m["id"]), [None, "b"])

    def test_a_failure_outside_every_member_is_the_answers(self):
        spec = S.obj({"meta": S.obj({"total": S.whole()}), "items": S.members(self.ITEM)})
        with self.assertRaises(PayloadError) as why:
            S.decode("src", spec, {"meta": {"total": "x"}, "items": [{"id": "a"}]})
        self.assertTrue(str(why.exception).startswith("src: "), "the message names the source")
        self.assertIn("meta.total", str(why.exception), "and where")

    def test_an_isolated_field_is_unreadable_in_its_place_and_costs_nothing_else(self):
        spec = S.obj({"best": S.isolated(S.obj({"url": S.text()})), "listed": S.members(S.obj({"url": S.text()}))})
        got = S.decode("t", spec, {"best": {"url": False}, "listed": [{"url": "u"}]})
        self.assertIsInstance(got["best"], Unreadable)
        self.assertEqual(got["listed"].each(lambda m: m["url"]), ["u"])
        self.assertEqual(S.decode("t", spec, {"listed": []})["best"]["url"], None, "left out, it is an empty location and not an unreadable one")

    def test_a_soft_field_says_nothing_when_it_cannot_be_read(self):
        spec = S.obj({"total": S.soft(S.whole()), "next": S.soft(S.token()), "items": S.members(self.ITEM)})
        got = S.decode("t", spec, {"total": "many", "next": ["c"], "items": [{"id": "a"}]})
        self.assertEqual((got["total"], got["next"], got["items"].each(lambda m: m["id"])), (None, None, ["a"]))
        got = S.decode("t", spec, {"total": 9, "next": "c"})
        self.assertEqual((got["total"], got["next"]), (9, "c"))

    def test_a_deep_field_is_read_through_containers_that_may_themselves_be_unreadable(self):
        spec = S.obj({"meta.total": S.deep(("meta", "total"), S.whole())})
        for body, want in (({"meta": {"total": 7}}, 7), ({"meta": 5}, None), ({"meta": []}, None), ({}, None), ({"meta": {"total": "x"}}, None), ({"meta": None}, None)):
            self.assertEqual(S.decode("t", spec, body)["meta.total"], want, body)


class Containers(unittest.TestCase):
    def test_an_object_must_be_one_and_holds_exactly_its_declared_fields(self):
        spec = S.obj({"a": S.text(), "inner": S.obj({"b": S.whole()})})
        for wrong in (False, 0, "", "x", [], [1], None, 5):
            with self.subTest(wrong=repr(wrong)), self.assertRaises(PayloadError):
                S.decode("t", spec, wrong)
        rec = S.decode("t", spec, {"a": "x", "inner": {"b": 1}, "extra": 9})
        self.assertEqual((rec["a"], rec["inner"]["b"], plain(rec.raw)["extra"], rec.declared), ("x", 1, 9, ("a", "inner")))
        with self.assertRaises(UndeclaredRead):
            rec["extra"]
        for wrong in (False, 0, "", [], "x", 5):
            with self.subTest(inner=repr(wrong)), self.assertRaises(PayloadError):
                one(spec, wrong, "x") if False else S.decode("t", spec, {"inner": wrong})

    def test_an_object_left_out_or_null_is_an_object_of_nothing(self):
        spec = S.obj({"inner": S.obj({"b": S.whole(), "c": S.flag(), "l": S.members(S.obj({})), "o": S.own(S.text()), "t": S.table(S.text())})})
        for body in ({}, {"inner": None}):
            inner = S.decode("t", spec, body)["inner"]
            self.assertEqual((inner["b"], inner["c"], len(inner["l"]), inner["o"], inner["t"], plain(inner.raw), inner.empty), (None, False, 0, [], {}, {}, True))

    def test_required_means_there_and_not_null(self):
        spec = S.obj({"f": S.required(S.own(S.text()))})
        self.assertEqual(S.decode("t", spec, {"f": []})["f"], [])
        for body in ({}, {"f": None}):
            with self.subTest(body=body), self.assertRaises(PayloadError):
                S.decode("t", spec, body)

    def test_a_list_left_out_or_null_is_empty_and_any_other_kind_is_unreadable(self):
        for spec, empty in ((S.own(S.text()), []), (S.members(S.obj({})), MemberList([]))):
            self.assertEqual((absent(spec), one(spec, None), one(spec, [])), (empty, empty, empty)) if isinstance(empty, list) else \
                self.assertEqual((len(absent(spec)), len(one(spec, None)), len(one(spec, []))), (0, 0, 0))
            for wrong in (False, True, 0, 1.5, "", "x", {}, {"a": 1}):
                with self.subTest(kind=spec.kind, wrong=repr(wrong)), self.assertRaises(PayloadError):
                    one(spec, wrong)

    def test_never_null_tells_a_field_that_is_left_out_from_one_that_is_sent_null(self):
        """Where an operation's accepted contract distinguishes the two, the schema says so (2b-repair-13a, R12-3): the generic rule — null is left out — is wrong for it, and `_absent` may not erase the difference."""
        spec = S.obj({"data": S.never_null(S.members(S.obj({}), empty_when=("total",))), "total": S.soft(S.whole())})
        for body in ({"total": 0}, {"data": [], "total": 0}, {"data": [], "total": 9}, {"data": [{}], "total": 9}):
            self.assertEqual(len(S.decode("t", spec, body)["data"]) in (0, 1), True, body)
        for body in ({"data": None, "total": 0}, {"data": None}, {"data": None, "total": 9}, {"total": 9}, {}):
            with self.subTest(body=body), self.assertRaises(PayloadError) as why:
                S.decode("t", spec, body)
            if body.get("data", 1) is None:
                self.assertIn("null", str(why.exception))
        plain_null = S.obj({"data": S.members(S.obj({}), empty_when=("total",)), "total": S.soft(S.whole())})
        self.assertEqual(len(S.decode("t", plain_null, {"data": None, "total": 0})["data"]), 0, "control: without the declaration null is left out, as everywhere")
        with self.assertRaises(PayloadError):   # never_null reads through the failure wrappers, and the field is the answer's
            S.decode("t", S.obj({"d": S.never_null(S.own(S.text()))}), {"d": None})
        self.assertEqual(S.decode("t", S.obj({"d": S.never_null(S.own(S.text()))}), {})["d"], [])

    def test_an_own_list_is_all_or_nothing(self):
        spec = S.own(S.obj({"n": S.whole()}))
        self.assertEqual([r["n"] for r in one(spec, [{"n": 1}, {"n": 2}])], [1, 2])
        for body in ([{"n": 1}, 7], [{"n": 1}, {"n": "x"}], [None]):
            with self.subTest(body=body), self.assertRaises(PayloadError):
                one(spec, body)

    def test_a_bare_object_stands_for_a_list_of_one_only_where_the_schema_says_so_and_only_when_it_holds_something(self):
        bare = S.own(S.obj({"n": S.whole()}), bare=True)
        self.assertEqual([r["n"] for r in one(bare, {"n": 1})], [1])
        for wrong in ({}, False, 0, "", "x"):
            with self.subTest(wrong=repr(wrong)), self.assertRaises(PayloadError):
                one(bare, wrong)
        with self.assertRaises(PayloadError):
            one(S.own(S.obj({"n": S.whole()})), {"n": 1})

    def test_a_list_holds_at_most_what_the_schema_allows(self):
        spec = S.own(S.obj({}), at_most=1)
        self.assertEqual(len(one(spec, [{}])), 1)
        with self.assertRaises(PayloadError):
            one(spec, [{}, {}])

    def test_a_list_may_be_left_out_only_when_the_provider_counts_nothing(self):
        spec = S.obj({"data": S.members(S.obj({}), empty_when=("header", "total")), "header": S.any_()})
        for body in ({"header": {"total": 0}}, {"data": None, "header": {"total": 0}}, {"data": [], "header": {"total": 9}}):
            self.assertEqual(len(S.decode("t", spec, body)["data"]), 0, body)
        for body in ({}, {"header": {"total": 9}}, {"header": {"total": "0"}}, {"header": {"total": 0.0}}, {"header": {"total": False}}, {"header": {"total": None}},
                     {"header": 5}, {"header": {}}):
            with self.subTest(body=body), self.assertRaises(PayloadError):
                S.decode("t", spec, body)

    def test_entries_are_a_keyed_containers_members_and_a_table_is_one_records_own_data(self):
        entries = one(S.entries(S.obj({"v": S.whole()})), {"a": {"v": 1}, "b": 7, "c": {"v": "x"}})
        self.assertEqual(entries.each(lambda e: (e["key"], e["value"]["v"])), [("a", 1), None, None])
        table = one(S.table(S.text()), {"a": "x", "b": None})
        self.assertEqual(table, {"a": "x", "b": None})
        with self.assertRaises(PayloadError):
            one(S.table(S.text()), {"a": "x", "b": 5})
        for spec in (S.entries(S.any_()), S.table(S.any_())):
            for wrong in (False, 0, "", "x", [], [1]):
                with self.subTest(kind=spec.kind, wrong=repr(wrong)), self.assertRaises(PayloadError):
                    one(spec, wrong)

    def test_a_lookup_reads_its_first_element_whole_and_nothing_after_it(self):
        spec = S.lookup(S.obj({"n": S.whole()}))
        self.assertEqual(one(spec, [{"n": 1}, 7, {"n": "x"}])["n"], 1)
        self.assertIsNone(one(spec, []))
        self.assertIsNone(absent(spec))
        for wrong in ([7], [{"n": "x"}], [False], False, 0, "", "x", {}):
            with self.subTest(wrong=repr(wrong)), self.assertRaises(PayloadError):
                one(spec, wrong)

    def test_maybe_tells_a_field_that_is_left_out_from_one_that_is_empty(self):
        spec = S.maybe(S.own(S.text()))
        self.assertEqual((absent(spec), one(spec, None), one(spec, []), one(spec, ["x"])), (None, None, [], ["x"]))
        with self.assertRaises(PayloadError):
            one(spec, "x")

    def test_oneof_is_the_first_kind_that_reads_and_unreadable_when_none_does(self):
        spec = S.oneof(S.obj({"name": S.text()}), S.text())
        self.assertEqual((one(spec, "n"), one(spec, {"name": "n"})["name"]), ("n", "n"))
        self.assertIsInstance(absent(spec), Rec)
        for wrong in (False, 0, [], ["x"], {"name": 5}):
            with self.subTest(wrong=repr(wrong)), self.assertRaises(PayloadError):
                one(spec, wrong)

    def test_a_field_that_depends_on_a_sibling_is_read_as_the_sibling_says(self):
        spec = S.obj({"typeName": S.text(), "value": S.by("typeName", {"title": S.text(), "author": S.own(S.text())})})
        self.assertEqual(S.decode("t", spec, {"typeName": "title", "value": "T"})["value"], "T")
        self.assertEqual(S.decode("t", spec, {"typeName": "author", "value": ["A"]})["value"], ["A"])
        self.assertEqual(plain(S.decode("t", spec, {"typeName": "other", "value": {"x": 1}})["value"]), {"x": 1}, "a kind no variant names is carried as sent, passive")
        for body in ({"typeName": "title", "value": 5}, {"typeName": "author", "value": "A"}, {"typeName": "author", "value": [5]}):
            with self.subTest(body=body), self.assertRaises(PayloadError):
                S.decode("t", spec, body)

    def test_fields_a_provider_names_by_a_prefix_are_each_read(self):
        spec = S.obj({"span": S.matching(("First", "Last"), S.text())})
        self.assertEqual(S.decode("t", spec, {"FirstYear": "1", "LastYear": "2", "TableName": "x"})["span"], {"FirstYear": "1", "LastYear": "2"})
        with self.assertRaises(PayloadError):
            S.decode("t", spec, {"FirstYear": 1})

    def test_a_rule_ties_fields_together_and_its_refusal_is_the_objects(self):
        def rule(rec):
            if rec["a"] and rec["b"]:
                raise PayloadError("a and b together")
        spec = S.members(S.obj({"a": S.text(), "b": S.text()}, rule=rule))
        got = S.decode("t", spec, [{"a": "x"}, {"a": "x", "b": "y"}, {"b": "y"}])
        self.assertEqual(got.each(lambda m: m["a"] or m["b"]), ["x", None, "y"])

    def test_alternatives_must_name_fields_the_object_declares(self):
        S.obj({"a": S.text(), "b": S.obj({"c": S.text()})}, alts=(("a", "b.c"),))
        with self.assertRaises(ValueError):
            S.obj({"a": S.text()}, alts=(("a", "nope"),))


class Xml(unittest.TestCase):
    TEXT = ('<m:Structure xmlns:m="x" xmlns:s="y"><s:Flows><s:Flow id="F1" agencyID="A"><s:Name>One</s:Name><s:Name>Uno</s:Name><s:Ref id="S1"/></s:Flow>'
            '<s:Flow id="F2"/></s:Flows></m:Structure>')

    def test_a_message_that_is_not_xml_or_not_of_the_kind_asked_for_is_unreadable(self):
        for text in ("<not xml", "", "<html><body/></html>"):
            with self.subTest(text=text), self.assertRaises(PayloadError):
                S.parse_xml(text, "Structure")
        self.assertEqual(S.parse_xml(self.TEXT, "Structure", "Other").tag.rsplit("}", 1)[-1], "Structure")

    def test_an_element_is_read_by_attribute_text_name_and_descendant(self):
        spec = S.obj({"@*": S.table(S.text()), "**Flow": S.own(S.obj({"%": S.text(), "@id": S.text(), "@agencyID": S.text(), "Name": S.own(S.obj({"#": S.text()})),
                                                                   "Ref": S.own(S.obj({"@*": S.table(S.text())})), "*": S.own(S.obj({"%": S.text()}))}))})
        got = S.decode("t", spec, S.parse_xml(self.TEXT, "Structure"))
        flows = got["**Flow"]
        self.assertEqual([(f["%"], f["@id"], f["@agencyID"]) for f in flows], [("Flow", "F1", "A"), ("Flow", "F2", None)])
        self.assertEqual([n["#"] for n in flows[0]["Name"]], ["One", "Uno"])
        self.assertEqual([r["@*"] for r in flows[0]["Ref"]], [{"id": "S1"}])
        self.assertEqual([c["%"] for c in flows[0]["*"]], ["Name", "Name", "Ref"])
        self.assertEqual((flows[1]["Name"], flows[1]["*"]), ([], []), "no such child: an empty list")

    def test_a_list_of_elements_is_bounded_like_any_list(self):
        spec = S.obj({"**Flow": S.own(S.obj({"@id": S.text()}), at_most=1)})
        with self.assertRaises(PayloadError):
            S.decode("t", spec, S.parse_xml(self.TEXT, "Structure"))


class Records(unittest.TestCase):
    def test_a_record_is_read_by_its_declared_names_and_is_not_a_collection(self):
        rec = S.decode("t", S.obj({"a": S.text()}), {"a": "x", "b": 1})
        for what in (lambda: iter(rec), lambda: list(rec), lambda: [*rec], lambda: dict(rec)):
            with self.assertRaises(TypeError):
                what()
        self.assertEqual((rec["a"], rec.get("a")), ("x", "x"))
        with self.assertRaises(UndeclaredRead):
            rec.get("b")

    def test_an_undeclared_read_is_not_any_error_a_member_builder_swallows(self):
        for error in (PayloadError, KeyError, AttributeError, TypeError, ValueError, IndexError):
            self.assertFalse(issubclass(UndeclaredRead, error), error.__name__)


if __name__ == "__main__":
    unittest.main()
