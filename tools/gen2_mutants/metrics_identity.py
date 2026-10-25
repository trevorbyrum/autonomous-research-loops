"""Remaining debt, locator and tool-execution mutations after S3 retirement."""
from __future__ import annotations

from .base import Mutation

C = 'tools/check_gen2_locators.py'
Q = 'test_locators.QualifiedScopeTest.'

MUTATIONS: list[Mutation] = [
    Mutation("2QI-qualified-short-name", "2q-repair-2", "a qualified locator uses flattened short names", (Q + "test_a_module_function_moved_into_a_closure_no_longer_satisfies_its_qualified_locator",),
             target=C, old='        if qualified or "." in name:\n            return None if name in index[1] else ', new='        if False:\n            return None if name in index[1] else '),
]
