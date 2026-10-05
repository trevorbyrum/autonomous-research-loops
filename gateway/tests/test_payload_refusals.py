"""Task 2q-a-repair-3: `Sealed` and `Passive` refuse every read through explicit, statically written methods (core/payload.py `_Unread`), exactly as the class
decorator `_no_reading` that installed them with `setattr` did.

The supported-source contract (docs/gen2/SOURCE-CONTRACT.md; Gate D #4) cannot model a class namespace that is changed at run time, so the one transformation
that did it was replaced, with behaviour unchanged (the operator's ruling of 2026-10-05). The oracle that nothing changed is the existing payload suite
(tests/test_sealed_payload.py, tests/test_opaque_provenance.py, tests/test_decoder_total.py ...), which passes unedited; that suite asserts the exception CLASS of the
listed reads. This module adds what it did not state: the closed list of the 43 special methods the old decorator installed, each refused with the exact
words it used (the way it was read, then what the object is and what to do instead), the attribute and write rules, `__hash__` (a refusal, not `None`), and the shared
dispatch between the two classes. The expected texts are written out here, never read from the implementation.

What this cannot show: that no other behaviour of the two classes differs (the differential run recorded with the repair compares every listed operation of the old and
the new implementation, 734 comparisons, in evidence/2q-a-repair-3/payload-differential.py).
"""
from __future__ import annotations

import math
import operator
import unittest

from research_gateway.core import payload
from research_gateway.core.payload import Passive, PassiveRead, Sealed, SealedRead, UndeclaredRead

SEALED_WHAT = "the provider's raw object"
SEALED_READABLE = "it is for storing (a record's `raw=`); declare the field and read it decoded"
PASSIVE_WHAT = "this value is declared any_(): metadata carried as sent, stored and never read"
PASSIVE_READABLE = "a value that decides anything is declared a kind in the schema"

# the special methods the decorator installed, each with a way of reading that reaches it through Python's own protocol
READS = {
    "__bool__": bool, "__iter__": iter, "__reversed__": reversed, "__len__": len, "__getitem__": lambda x: x[0], "__contains__": lambda x: 1 in x,
    "__lt__": lambda x: x < 1, "__le__": lambda x: x <= 1, "__gt__": lambda x: x > 1, "__ge__": lambda x: x >= 1, "__str__": str, "__format__": lambda x: format(x, ""),
    "__int__": int, "__float__": float, "__index__": operator.index, "__bytes__": bytes, "__add__": lambda x: x + 1, "__radd__": lambda x: 1 + x, "__mul__": lambda x: x * 2,
    "__rmul__": lambda x: 2 * x, "__neg__": operator.neg, "__abs__": abs, "__mod__": lambda x: x % 2, "__sub__": lambda x: x - 1, "__rsub__": lambda x: 1 - x,
    "__truediv__": lambda x: x / 2, "__floordiv__": lambda x: x // 2, "__and__": lambda x: x & 1, "__or__": lambda x: x | 1, "__xor__": lambda x: x ^ 1, "__hash__": hash,
    "__call__": lambda x: x(), "__round__": round, "__floor__": math.floor, "__ceil__": math.ceil, "__trunc__": math.trunc, "__matmul__": lambda x: x @ 1,
    "__pow__": lambda x: x ** 2, "__lshift__": lambda x: x << 1, "__rshift__": lambda x: x >> 1, "__invert__": operator.invert, "__pos__": operator.pos,
    "__complex__": complex,
}


class RefusalCase(unittest.TestCase):
    def refused(self, error: type, read) -> str:
        """The message of the refusal `read` raises, or a FAILURE: another exception or none is the assertion, never an error, so that a mutant that changes what is raised is killed."""
        try:
            read()
        except error as exc:
            return str(exc)
        except BaseException as exc:   # noqa: BLE001 (what a mutant makes it raise instead is the point)
            self.fail(f"raised {type(exc).__name__}: {exc}, not {error.__name__}")
        self.fail(f"nothing was raised, not {error.__name__}")


CLASSES = {"Sealed": (Sealed, SealedRead, SEALED_WHAT, SEALED_READABLE, lambda: Sealed({"a": 1})), "Passive": (Passive, PassiveRead, PASSIVE_WHAT, PASSIVE_READABLE, lambda: Passive([1, 2]))}


class SpecialMethodsTest(RefusalCase):
    def test_the_closed_list_is_forty_three_names(self) -> None:
        self.assertEqual(len(READS), 43)

    def test_every_listed_method_refuses_with_the_way_it_was_read_in_the_message(self) -> None:
        for label, (cls, error, what, readable, make) in CLASSES.items():
            for name, read in READS.items():
                with self.subTest(cls=label, method=name):
                    self.assertEqual(self.refused(error, lambda: read(make())), f"{what} ({name}); {readable}")
                    self.assertTrue(issubclass(error, UndeclaredRead), "a programming error: no builder's net catches it")

    def test_each_is_a_method_the_class_has_and_the_hash_is_not_none(self) -> None:
        for label, (cls, *_rest) in CLASSES.items():
            for name in READS:
                with self.subTest(cls=label, method=name):
                    self.assertTrue(callable(getattr(cls, name)), "a refusal is a method, not None")
        self.assertIsNotNone(Sealed.__hash__)
        self.assertIsNotNone(Passive.__hash__)

    def test_called_directly_with_any_arguments_each_refuses_the_same_way(self) -> None:
        """A special method called as a method (`x.__add__(1, 2, key=3)`, `x.__round__()`) refuses with the same words, whatever the arguments."""
        for label, (cls, error, what, readable, make) in CLASSES.items():
            for name in READS:
                with self.subTest(cls=label, method=name):
                    self.assertEqual(self.refused(error, lambda: getattr(make(), name)(1, 2, key=3)), f"{what} ({name}); {readable}")


class AttributesTest(RefusalCase):
    def test_an_attribute_that_is_not_the_objects_own_refuses_naming_it(self) -> None:
        for label, (cls, error, what, readable, make) in CLASSES.items():
            for attribute in ("get", "startswith", "_private", "anything"):
                with self.subTest(cls=label, attribute=attribute):
                    self.assertEqual(self.refused(error, lambda: getattr(make(), attribute)), f"{what} (attribute {attribute!r}); {readable}")

    def test_a_dunder_an_introspecting_library_probes_for_is_an_attribute_error_as_for_any_object(self) -> None:
        for label, (cls, error, what, readable, make) in CLASSES.items():
            value = make()
            with self.subTest(cls=label):
                self.assertEqual(self.refused(AttributeError, lambda: value.__nothing_at_all__), "__nothing_at_all__")
                self.assertFalse(hasattr(value, "__nothing_at_all__"))
                self.assertFalse(hasattr(value, "__dict__"), "slotted: there is no instance dictionary to look at")
                self.assertEqual(getattr(value, "__nothing_at_all__", "default"), "default")

    def test_a_write_is_refused_as_a_change_in_both_classes(self) -> None:
        for label, (cls, error, what, readable, make) in CLASSES.items():
            for attribute in ("a", "_value"):
                with self.subTest(cls=label, attribute=attribute):
                    self.assertEqual(self.refused(error, lambda: setattr(make(), attribute, 1)), f"{what} is not changed")

    def test_the_construction_still_stores_the_value_and_plain_still_hands_out_a_copy(self) -> None:
        sealed = Sealed({"a": [1]})
        copied = payload.plain(sealed)
        self.assertEqual(copied, {"a": [1]})
        copied["a"].append(2)
        self.assertEqual(payload.plain(sealed), {"a": [1]})   # the object kept is never the one handed out
        self.assertEqual(payload.plain(Passive(None)), None)


class EqualityAndShapeTest(RefusalCase):
    def test_a_sealed_object_equals_no_plain_value_and_refuses_another_sealed(self) -> None:
        sealed = Sealed({"a": 1})
        self.assertIs(sealed == {"a": 1}, False)
        self.assertIs(sealed != {"a": 1}, True)
        self.assertIs(sealed == None, False)  # noqa: E711
        self.assertEqual(self.refused(SealedRead, lambda: sealed == Sealed({"a": 1})),
                         "two sealed objects are not compared: a comparison of provider objects is Rec.same_as, between two decoded objects")
        self.refused(SealedRead, lambda: Sealed(1) != Sealed(1))

    def test_a_passive_value_refuses_every_comparison(self) -> None:
        passive = Passive("x")
        for compare in (lambda: passive == 1, lambda: passive != 1, lambda: 1 == passive, lambda: passive == passive):
            self.assertEqual(self.refused(PassiveRead, compare), f"{PASSIVE_WHAT} (comparison)")

    def test_repr_shows_nothing_of_the_value(self) -> None:
        self.assertEqual((repr(Sealed({"secret": 1})), repr(Passive("secret"))), ("<Sealed>", "<Passive>"))

    def test_the_storage_is_one_slot_in_each_class_and_there_is_no_instance_dict(self) -> None:
        self.assertEqual((Sealed.__slots__, Passive.__slots__), (("_value",), ("_value",)))
        for instance in (Sealed({"a": 1}), Passive("x")):
            with self.subTest(cls=type(instance).__name__):
                # the slot declaration alone does not say there is no dictionary (a base without `__slots__` would give one): ask the object itself, past its own refusing `__getattr__`
                with self.assertRaises(AttributeError):
                    object.__getattribute__(instance, "__dict__")
                self.assertFalse(hasattr(instance, "__dict__"))
                self.assertFalse(any("__dict__" in vars(klass) for klass in type(instance).__mro__ if klass is not object), msg="no class in the order contributes an instance dictionary")

    def test_without_still_works_on_an_object_and_refuses_anything_else(self) -> None:
        self.assertEqual(payload.plain(Sealed({"a": 1, "b": 2}).without("a")), {"b": 2})
        self.assertEqual(self.refused(SealedRead, lambda: Sealed([1]).without("a")), "without() takes fields out of an object")


class SharedRefusalTest(RefusalCase):
    def test_a_subclass_is_refused_with_its_parents_error_and_words(self) -> None:
        class Mine(Sealed):
            __slots__ = ()

        self.assertEqual(self.refused(SealedRead, lambda: bool(Mine(1))), f"{SEALED_WHAT} (__bool__); {SEALED_READABLE}")

    def test_the_two_classes_do_not_share_an_error(self) -> None:
        self.refused(SealedRead, lambda: len(Sealed([1])))
        self.refused(PassiveRead, lambda: len(Passive([1])))
        self.assertFalse(issubclass(SealedRead, PassiveRead) or issubclass(PassiveRead, SealedRead))

    def test_the_decorator_that_installed_the_methods_is_gone(self) -> None:
        self.assertFalse(hasattr(payload, "_no_reading"))
        self.assertFalse(hasattr(payload, "_READS"))
        for cls in (Sealed, Passive):
            self.assertIn("_Unread", [c.__name__ for c in cls.__mro__])


if __name__ == "__main__":
    unittest.main()
