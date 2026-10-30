"""The Observations collaborator's `_audit` declaration against the Router's member of the same name.

The Router implements `ObservationCore` without inheriting it, so nothing else checks that the declared signature is one the
Router honours; the expected parameter lists below are literals, not read from either side.
"""
from __future__ import annotations

import inspect
import unittest

from gen2.router.observations import ObservationCore
from gen2.router.service import Router

POSITIONAL, KEYWORD = inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY
DECLARED_AUDIT = [("self", POSITIONAL), ("kind", POSITIONAL), ("at", POSITIONAL), ("detail", POSITIONAL),
                  ("topic_id", KEYWORD), ("invocation_id", KEYWORD)]


def parameters(function) -> list[tuple[str, object]]:
    return [(name, p.kind) for name, p in inspect.signature(function).parameters.items()]


class AuditSignatureTest(unittest.TestCase):
    def test_the_declaration_takes_topic_and_invocation_by_keyword_only(self):
        self.assertEqual(parameters(ObservationCore._audit), DECLARED_AUDIT)

    def test_the_router_takes_the_declared_parameters_the_same_way(self):
        self.assertEqual(parameters(Router._audit)[:len(DECLARED_AUDIT)], DECLARED_AUDIT)
        self.assertEqual(parameters(Router._audit)[len(DECLARED_AUDIT):], [("operation_id", KEYWORD)])


if __name__ == "__main__":
    unittest.main()
