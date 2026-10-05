"""Task 2q-a-repair-3: the gateway mutants of the explicit refusals of `Sealed` and `Passive` (core/payload.py `_Unread`, `_refusal`).

The class decorator `_no_reading` installed 43 special methods, `__getattr__` and `__setattr__` with `setattr`; the supported-source contract cannot model that, so
they are explicit methods now, with one shared refusal. The mutants here remove or weaken ONE part of that code in a temporary copy:

  U-refusal-*     the shared dispatch gives both classes one error and one wording;
  U-getattr-*     a dunder an introspecting library probes for stops being an AttributeError;
  U-write-*       an instance can be changed, or its refusal says it was read;
  U-hash-*        a class's hash is `None` (a TypeError) instead of a refusal, as the decorator left it;
  U-method-*      four of the 43 special methods are no longer refused (the closed list is asserted whole in tests/test_payload_refusals.py; four are enough to show a
                  missing method is seen, and the rest are the table's);
  U-compare-*     a Passive value or two Sealed objects compare;
  U-slots-*       the shared base gains an instance dictionary.

A killer must FAIL in its assertions, not error (tools/gen2_gateway_mutations.py): tests/test_payload_refusals.py reports what a mutant makes a read raise as a failure.
A control takes the accepted path through the same code (the construction, `plain`, `without`).
"""
from __future__ import annotations

PAYLOAD = "research_gateway/core/payload.py"
PR = "tests.test_payload_refusals."
CLOSED = PR + "SpecialMethodsTest.test_every_listed_method_refuses_with_the_way_it_was_read_in_the_message"
CONTROLS = (PR + "AttributesTest.test_the_construction_still_stores_the_value_and_plain_still_hands_out_a_copy", PR + "EqualityAndShapeTest.test_without_still_works_on_an_object_and_refuses_anything_else")


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    hash_sealed = '    def __hash__(self, *args, **kwargs):\n        raise _refusal(self, "__hash__")\n\n    def __eq__(self, other) -> bool:\n        if isinstance(other, Sealed):'
    hash_passive = '    def __hash__(self, *args, **kwargs):\n        raise _refusal(self, "__hash__")\n\n    def __eq__(self, other) -> bool:\n        raise PassiveRead('
    return [
        Mutant("U-refusal-is-always-sealed", "every refusal is a SealedRead with the sealed wording, a Passive's included", PAYLOAD,
               "    if isinstance(held, Sealed):", "    if True:", (CLOSED,), CONTROLS),
        Mutant("U-refusal-is-always-passive", "every refusal is a PassiveRead with the passive wording, a Sealed's included", PAYLOAD,
               "    if isinstance(held, Sealed):", "    if False:", (CLOSED,), CONTROLS),
        Mutant("U-refusal-is-by-exact-type", "a subclass of Sealed is refused as a Passive", PAYLOAD,
               "    if isinstance(held, Sealed):", "    if type(held) is Sealed:", (PR + "SharedRefusalTest.test_a_subclass_is_refused_with_its_parents_error_and_words",), CONTROLS),
        Mutant("U-getattr-dunders-refused-as-errors", "a dunder probe raises the class's error, not an AttributeError", PAYLOAD,
               '        if name.startswith("__") and name.endswith("__"):\n            raise AttributeError(name)', '        if False:\n            raise AttributeError(name)',
               (PR + "AttributesTest.test_a_dunder_an_introspecting_library_probes_for_is_an_attribute_error_as_for_any_object",), CONTROLS),
        Mutant("U-getattr-names-no-attribute", "an attribute refusal does not name the attribute", PAYLOAD,
               '        raise _refusal(self, f"attribute {name!r}")', '        raise _refusal(self, "attribute")', (PR + "AttributesTest.test_an_attribute_that_is_not_the_objects_own_refuses_naming_it",), CONTROLS),
        Mutant("U-write-allowed", "an instance can be changed", PAYLOAD, "    def __setattr__(self, name, value):\n        raise _refusal(self)", "    def __setattr__(self, name, value):\n        object.__setattr__(self, name, value)",
               (PR + "AttributesTest.test_a_write_is_refused_as_a_change_in_both_classes",), CONTROLS),
        Mutant("U-write-says-it-was-read", "a write is refused as if it were a read", PAYLOAD,
               '    return error(f"{what} is not changed" if how is None else f"{what} ({how}); {readable}")', '    return error(f"{what} ({how}); {readable}")',
               (PR + "AttributesTest.test_a_write_is_refused_as_a_change_in_both_classes",), CONTROLS),
        Mutant("U-hash-of-a-sealed-is-none", "hashing a Sealed raises TypeError instead of a refusal", PAYLOAD,
               hash_sealed, '    def __eq__(self, other) -> bool:\n        if isinstance(other, Sealed):', (CLOSED, PR + "SpecialMethodsTest.test_each_is_a_method_the_class_has_and_the_hash_is_not_none"), CONTROLS),
        Mutant("U-hash-of-a-passive-is-none", "hashing a Passive raises TypeError instead of a refusal", PAYLOAD,
               hash_passive, '    def __eq__(self, other) -> bool:\n        raise PassiveRead(', (CLOSED, PR + "SpecialMethodsTest.test_each_is_a_method_the_class_has_and_the_hash_is_not_none"), CONTROLS),
        Mutant("U-method-bool-is-not-refused", "the truth of a Sealed or a Passive is True", PAYLOAD,
               '    def __bool__(self, *args, **kwargs):\n        raise _refusal(self, "__bool__")', '    def __bool__(self, *args, **kwargs):\n        return True', (CLOSED,), CONTROLS),
        Mutant("U-method-str-is-not-refused", "a Sealed or a Passive has a text", PAYLOAD,
               '    def __str__(self, *args, **kwargs):\n        raise _refusal(self, "__str__")', '    def __str__(self, *args, **kwargs):\n        return "x"', (CLOSED,), CONTROLS),
        Mutant("U-method-contains-is-not-refused", "a Sealed or a Passive can be searched", PAYLOAD,
               '    def __contains__(self, *args, **kwargs):\n        raise _refusal(self, "__contains__")', '    def __contains__(self, *args, **kwargs):\n        return False', (CLOSED,), CONTROLS),
        Mutant("U-method-call-is-not-refused", "a Sealed or a Passive can be called", PAYLOAD,
               '    def __call__(self, *args, **kwargs):\n        raise _refusal(self, "__call__")', '    def __call__(self, *args, **kwargs):\n        return None', (CLOSED,), CONTROLS),
        Mutant("U-method-names-the-wrong-way", "a refusal names another special method than the one that was used", PAYLOAD,
               '    def __add__(self, *args, **kwargs):\n        raise _refusal(self, "__add__")', '    def __add__(self, *args, **kwargs):\n        raise _refusal(self, "__radd__")', (CLOSED,), CONTROLS),
        Mutant("U-compare-two-sealed", "two Sealed objects compare", PAYLOAD, "        if isinstance(other, Sealed):\n            raise SealedRead(", "        if False:\n            raise SealedRead(",
               (PR + "EqualityAndShapeTest.test_a_sealed_object_equals_no_plain_value_and_refuses_another_sealed",), CONTROLS),
        Mutant("U-compare-a-passive", "a Passive value compares equal to another", PAYLOAD,
               '    def __eq__(self, other) -> bool:\n        raise PassiveRead("this value is declared any_(): metadata carried as sent, stored and never read (comparison)")',
               '    def __eq__(self, other) -> bool:\n        return self is other', (PR + "EqualityAndShapeTest.test_a_passive_value_refuses_every_comparison",), CONTROLS),
        Mutant("U-slots-the-base-has-a-dict", "the shared base gives its instances a dictionary", PAYLOAD,
               '    __slots__ = ()\n\n    def __bool__', '    def __bool__', (PR + "AttributesTest.test_a_dunder_an_introspecting_library_probes_for_is_an_attribute_error_as_for_any_object",),
               (*CONTROLS, PR + "EqualityAndShapeTest.test_the_storage_is_one_slot_in_each_class_and_there_is_no_instance_dict")),
    ]
