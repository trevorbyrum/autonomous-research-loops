"""Task 2b-repair-13a (Gate D #1, Astra R12-4): the decoder's failure channel is TOTAL.

Repair-12 made validation eager, and then a conversion raised an ordinary exception through it: `year_value` tests `str.isdigit()` and calls `int()`, and `"²"`, `"①"` and a string of 4,301
digits pass the one and make the other raise ValueError. The decoder's member boundary caught only PayloadError, so one such year beside two readable Crossref works lost the whole lane
(unobserved, no count) where the code before repair-12 kept the two as a partial lower bound. Patching `year_value` alone would have fixed that one conversion; the property that was missing is that
whatever a provider's value makes ANY conversion or consistency rule do surfaces through the one channel, at the narrowest member boundary. It is a property of the decoder (core/schema.py: `_normalized`,
`_ruled`, the opening of the answer's bytes), and this file states it as one:

  * the scalar normalizers, directly, and through every real operation that has one at a member position — derived from the schemas, not listed (Unicode numerics, numbers past the interpreter's conversion
    limit, beside readable peers);
  * the decoder over every declared position of every operation's schema with a corpus of hostile values: it returns, or it raises PayloadError — nothing else comes out of `decode`;
  * a consistency rule that fails on a provider's value is the object's failure, and one that reads what its schema does not declare is a programming error that still passes (UndeclaredRead, PassiveRead);
  * the opening of the answer's bytes: empty, unparseable, absurdly nested.

What this cannot show: that no other exception can come out of a value nobody has thought of. The corpus is finite; `_normalized` and `_ruled` are what make the channel total by construction (every call out of the
decoder into code that reads a provider's value goes through one of them), and the corpus checks that construction on the values that broke it.
"""
from __future__ import annotations

import copy
import unittest

from research_gateway import adapters
from research_gateway.adapters.base import PayloadError, Response, decode as adapter_decode
from research_gateway.core import schema as S
from research_gateway.core import sdmx
from research_gateway.core.payload import MEMBER_ERRORS, PassiveRead, UndeclaredRead, Unreadable, plain
from tests import invariant_ops as ops
from tests.invariant_ops import corrupt_route
from tests.test_invariants import ALL, MISSING, run
import collections

from tests.test_schema_corruption import fixtures, grow, lost_by, operation_members, prepared, schema_of, walk

# what `str.isdigit()` takes for digits and `int()` refuses, and what it takes and `int()` reads (and the interpreter's limit on how many)
NOT_A_NUMBER = ("²", "①", "⑤", "²⁰²¹", "２²", "9" * 4301, "7" * 10_000, "٠" * 5_000)
READS_AS_A_YEAR = {"2021": 2021, "٢٠٢١": 2021, "２０２１": 2021, 2021: 2021, 2021.0: 2021}
HOSTILE = (*NOT_A_NUMBER, "", " ", "x" * 100_000, "\x00", "\ud800", "٢٠٢١", 0, -1, 2 ** 63, 10 ** 4299, 1e308, -0.0, float("nan"), float("inf"), -float("inf"), True, False, None, [], {}, [[]], [{}], {"a": {"b": {}}},
           [[[[[["deep"]]]]]], {"id": "²"}, ["²"], 1.5)


class ScalarNormalizers(unittest.TestCase):
    def test_a_year_that_is_no_number_is_a_payload_error_and_never_any_other_exception(self):
        for value in NOT_A_NUMBER:
            with self.subTest(value=value[:12] + f"…({len(value)})"):
                with self.assertRaises(PayloadError):
                    S.year_value(value)
        for value, year in READS_AS_A_YEAR.items():
            self.assertEqual(S.year_value(value), year, value)

    def test_the_decoder_alone_isolates_the_member_without_any_adapter(self):
        """Astra's direct probe: no provider fixture, no router."""
        spec = S.members(S.obj({"id": S.key(), "year": S.year()}))
        for value in NOT_A_NUMBER + ("bad",):
            with self.subTest(value=value[:12]):
                got = S.decode("review", spec, [{"id": "bad", "year": value}, {"id": "good", "year": 2021}])
                self.assertEqual(got.each(lambda row: row["id"]), [None, "good"])
                (lost,) = got.unreadable()
                self.assertIn("year", lost.reason)
                self.assertTrue(lost.was_object)
        for value in READS_AS_A_YEAR:
            got = S.decode("review", spec, [{"id": "a", "year": value}, {"id": "good", "year": 2021}])
            self.assertEqual(got.each(lambda row: (row["id"], row["year"])), [("a", 2021), ("good", 2021)], value)

    def test_every_normalizer_is_called_through_the_one_wrapper(self):
        """A normalizer that is added raises however it likes and still costs its member only: that is the construction, so it is tested with a normalizer that raises everything."""
        for error in (ValueError("x"), OverflowError("x"), TypeError("x"), ZeroDivisionError("x"), RecursionError("x"), KeyError("x"), IndexError("x"), AttributeError("x"), RuntimeError("x"), OSError("x")):
            def boom(v, error=error):
                raise error
            spec = S.members(S.obj({"n": S.Spec("boom")}))
            S._NORMALIZERS["boom"] = boom
            try:
                got = S.decode("t", spec, [{"n": 1}, {}])
            finally:
                del S._NORMALIZERS["boom"]
            with self.subTest(error=type(error).__name__):
                self.assertEqual([isinstance(m, Unreadable) for m in got.unreadable()], [True], "the one member that has the value is lost, with a reason")
                self.assertEqual(len(got), 2)

    def test_a_number_that_is_not_finite_or_not_a_number_is_unreadable(self):
        for value in (float("nan"), float("inf"), "3", True, [], {}):
            with self.assertRaises(PayloadError):
                S.decode("t", S.obj({"n": S.number()}), {"n": value})
        self.assertEqual(S.decode("t", S.obj({"n": S.number()}), {"n": 3599.5})["n"], 3599.5)


class YearsThroughRealOperations(unittest.TestCase):
    """Gate D's probe, derived: every position of kind `year` (or any normalizer) that sits inside a member of a real operation, with the hostile values, beside readable peers — through the real adapter
    and the router. Where the old gateway (before repair-12) kept the peers, this one does too."""

    def positions(self):
        for name, op, body in fixtures():
            sid, key, spec = schema_of(name)
            for pos in walk(spec, body, (), (), ("answer",)):
                if pos.spec.kind in S._NORMALIZERS and pos.boundary[0] == "member":
                    yield name, op, body, pos

    def test_the_derivation_reaches_the_operations_gate_d_and_astra_named(self):
        reached = {name for name, *_ in self.positions()}
        self.assertTrue({"crossref.find", "semanticscholar.find", "datacite.find"} <= {n.split(" (")[0] for n in reached}, sorted(reached))

    def test_a_year_that_cannot_be_read_costs_its_member_and_nothing_beside_it(self):
        runs = 0
        for name, op, body, pos in self.positions():
            what, lost = lost_by(op, operation_members(op, body), pos, body)
            if what != "lost":   # a member no operation member holds (a lookup reads only the first of its results): nothing of the lane's to lose
                continue
            ids, gone = collections.Counter(op.ids), collections.Counter(m.ident for m in lost)
            for value in NOT_A_NUMBER + ("bad", "20x1", [], {}, False):
                runs += 1
                out, lane = run(op, grow(prepared(body, pos), pos.path, value))
                with self.subTest(op=name, position=repr(pos), value=repr(value)[:20]):
                    self.assertNotIn("ValueError", lane.get("error", ""), "an exception that came out of the decoder")
                    self.assertEqual(lane.get("error_class"), "payload_invalid")
                    if not (ids - gone):
                        self.assertEqual((lane["coverage"], lane["completeness"], "count" in lane), ("provider_unavailable", "unobserved", False))
                    else:
                        self.assertEqual((lane["completeness"], collections.Counter(lane["retrieved"]), lane["count"]), ("partial", ids - gone, sum((ids - gone).values())),
                                         "the readable peers stand as a partial lower bound")
        self.assertGreater(runs, 100)

    def test_control_numerals_that_int_reads_are_years(self):
        for name, op, body, pos in self.positions():
            what, lost = lost_by(op, operation_members(op, body), pos, body)
            if what != "lost":
                continue
            for value in ("2021", "٢٠٢١", "２０２１"):
                out, lane = run(op, grow(prepared(body, pos), pos.path, value))
                with self.subTest(op=name, value=value):
                    self.assertEqual((lane["completeness"], lane.get("error_class")), ("complete", None), lane)

    def test_gate_ds_three_works_through_the_router(self):
        """Valid / ordinary invalid / `²` / 4,301 digits: three Crossref works, the middle one's year changed. Three, two, two and two records; never a lane lost."""
        from tests.test_identity_only import routed, work
        for label, year, want in (("valid", 2021, 3), ("ordinary invalid", "x", 2), ("unicode digit", "²", 2), ("oversized", "2" * 4301, 2), ("circled", "①", 2), ("arabic-indic", "٢٠٢١", 3)):
            answer = routed([work("10.1000/a", "First study"), work("10.1000/b", "Other study", year), work("10.1000/c", "Third different study")])
            (lane,) = answer["lanes"]
            with self.subTest(label):
                self.assertEqual((len(answer["records"]), lane["coverage"], lane["completeness"], lane.get("count")),
                                 (want, "searched_ok", "complete" if want == 3 else "partial", want))
                self.assertEqual(lane.get("error_class"), None if want == 3 else "payload_invalid")


class TheDecoderOnlyEverRaisesPayloadError(unittest.TestCase):
    """Every operation's schema, at every declared position, with every hostile value: `decode` returns or raises PayloadError."""

    def test_every_declared_position_with_every_hostile_value(self):
        runs = 0
        for name, op, body in fixtures():
            sid, key, spec = schema_of(name)
            for pos in walk(spec, body, (), (), ("answer",)):
                for value in HOSTILE:
                    runs += 1
                    try:
                        S.decode("t", spec, grow(prepared(body, pos), pos.path, value))
                    except PayloadError:
                        pass
                    except Exception as e:   # the failure is the exception's own type: the whole point
                        self.fail(f"{name}: {pos!r} <- {value!r:.40}: {type(e).__name__}: {e}")
        self.assertGreater(runs, 50_000)

    def test_the_loaders_the_lookup_and_the_xml_schemas_too(self):
        from research_gateway.core.identity import SCHEMAS as lookup
        from research_gateway.harvest import registries
        specs = {**{f"registries.{k}": v for k, v in registries.SCHEMAS.items() if k != "doaj journals (csv)"}, "identity.lookup": lookup["lookup"], "sdmx.json": sdmx.JSON_MESSAGE}
        for name, spec in specs.items():
            for value in HOSTILE:
                with self.subTest(schema=name, value=repr(value)[:20]):
                    try:
                        S.decode("t", spec, value)
                        S.decode("t", spec, {"data": value, "message": value, "results": value, "structure": value, "dataSets": value, "meta": {"total": value}})
                    except PayloadError:
                        pass

    def test_a_malformed_answer_is_never_any_other_error_when_the_bytes_are_opened_by_the_decoder(self):
        spec = S.obj({"a": S.members(S.obj({"n": S.year()}))})
        bodies = (b"", b" ", b"{", b"\xff\xfe\x00", b'{"a": [{"n": "' + b"9" * 6000 + b'"}]}', b"[" * 200_000, b'{"a":' * 150 + b"1" + b"}" * 150, b"NaN", b"1" * 5000, b"\xef\xbb\xbf{}", b"null", b"[]")
        for body in bodies:
            with self.subTest(body=body[:16], size=len(body)):
                try:
                    S.decode("t", spec, Response(200, {}, body, "u"))
                except PayloadError:
                    pass
        got = S.decode("t", spec, Response(200, {}, b'{"a": [{"n": "' + b"9" * 6000 + b'"}, {"n": 2021}]}', "u"))
        self.assertEqual(got["a"].each(lambda m: m["n"]), [None, 2021], "an oversized number in a member costs that member, from the bytes up")

    def test_nesting_deeper_than_any_supported_answer_is_unreadable_and_nesting_within_it_is_read(self):
        within = b'{"a":' * 60 + b"1" + b"}" * 60
        beyond = b'{"a":' * 80 + b"1" + b"}" * 80
        any_ = S.obj({"a": S.any_()})
        self.assertIsNotNone(S.decode("t", any_, Response(200, {}, within, "u")))
        with self.assertRaises(PayloadError):
            S.decode("t", any_, Response(200, {}, beyond, "u"))

    def test_the_adapter_facing_decode_takes_the_clients_response_and_nothing_else(self):
        for value in ({}, [], "x", b"{}", None, 5):
            with self.subTest(value=repr(value)), self.assertRaises(TypeError):
                adapter_decode("t", S.obj({}), value)
        self.assertIsNotNone(adapter_decode("t", S.obj({}), Response(200, {}, b"{}", "u")))


class RulesAndProgrammingErrors(unittest.TestCase):
    def test_a_rule_that_fails_on_a_providers_value_is_the_objects_failure_not_an_escaping_exception(self):
        for error in (TypeError, KeyError, IndexError, ValueError, AttributeError, ZeroDivisionError, OverflowError, RecursionError):
            def rule(rec, error=error):
                raise error("the provider's value broke it")
            spec = S.members(S.obj({"a": S.text()}, rule=rule))
            got = S.decode("t", spec, [{"a": "x"}])
            with self.subTest(error=error.__name__):
                self.assertEqual([m.reason.startswith("[0]: the rule could not read the answer") for m in got.unreadable()], [True])
        listed = S.own(S.text(), rule=lambda items: items[5])   # IndexError on a list that is shorter than the rule assumes
        with self.assertRaises(PayloadError):
            S.decode("t", S.obj({"l": listed}), {"l": ["a"]})

    def test_a_rule_that_reads_what_the_schema_does_not_declare_is_a_programming_error_and_passes(self):
        spec = S.members(S.obj({"a": S.text()}, rule=lambda rec: rec["undeclared"]))
        with self.assertRaises(UndeclaredRead):
            S.decode("t", spec, [{"a": "x"}])
        with self.assertRaises(UndeclaredRead):
            S.decode("t", S.obj({"o": S.obj({"a": S.any_()}, rule=lambda rec: bool(rec["a"]))}), {"o": {"a": 1}})   # a rule that decides on metadata: PassiveRead is an UndeclaredRead

    def test_a_builder_that_reads_an_undeclared_or_passive_field_is_not_a_dropped_member(self):
        rows = S.decode("t", S.members(S.obj({"id": S.text(), "meta": S.any_()})), [{"id": "a", "meta": 1}, {"id": "b", "meta": 2}])
        with self.assertRaises(UndeclaredRead):
            rows.each(lambda r: r["nope"])
        with self.assertRaises(PassiveRead):
            rows.each(lambda r: r["meta"] == 1)
        with self.assertRaises(PassiveRead):
            rows.each(lambda r: bool(r["meta"]))
        self.assertEqual(rows.each(lambda r: (r["id"], plain(r["meta"]))), [("a", 1), ("b", 2)], "metadata leaves through plain(), copied, and nothing else")
        self.assertTrue(all(not issubclass(UndeclaredRead, e) for e in MEMBER_ERRORS if e is not RecursionError), "none of the member errors is a programming error")
        self.assertFalse(issubclass(UndeclaredRead, RecursionError))


if __name__ == "__main__":
    unittest.main()
