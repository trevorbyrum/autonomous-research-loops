"""Router composition (task 2q-b2; registries.py, 2q-b3): status.py, capabilities.py and registries.py are explicit collaborators the Router composes, each declaring in its own
module the interface it takes of the core (a `typing.Protocol` the Router implements without inheriting it; BOUNDARIES.md, "Router
composition"). A protocol is not enforced at run time, so these keep it true: every member a collaborator reads off `self._core` is
declared, every declared member is one the collaborator uses and the Router has, the collaborator reaches the store only through the
core, and the Router's public methods are the ones it had when they were mixins."""
import ast
import inspect
import unittest
from pathlib import Path

from gen2.router import capabilities, registries, service, status
from gen2.tests.router_fixtures import RouterTestCase

COLLABORATORS = ((status, status.Status, status.StatusCore, "_status"), (capabilities, capabilities.Capabilities, capabilities.CapabilityCore, "_capabilities"),
                 (registries, registries.Registries, registries.RegistriesCore, "_registries"))
PUBLIC_API = {  # Router's public methods at be5b2f1, before status.py, capabilities.py and registries.py stopped being mixins
    "ack_delivery", "activate_config_bundle", "apply_operator_decision", "claim", "close", "close_brief", "commit_outcome", "config_bundle", "create_topic", "draft_contract",
    "healthy", "invocation_status", "is_qualified", "mark_brief_overdue", "open", "open_brief", "open_reservation", "open_review", "propose_amendment", "raise_signal",
    "receipt", "reconcile", "record_capability_probe", "record_gateway_facts", "record_observation", "record_qualification", "record_transition", "register_works",
    "request_cancel", "requeue", "restore_config_bundle", "revoke_qualification", "status", "version_brief"}


def is_core(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "_core" and isinstance(node.value, ast.Name) and node.value.id == "self"


def tree(module) -> ast.Module:
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def used(module) -> set[str]:
    """What the module reads off `self._core`."""
    return {n.attr for n in ast.walk(tree(module)) if isinstance(n, ast.Attribute) and is_core(n.value)}


def declared(core) -> set[str]:
    return set(core.__annotations__) | {n for n, v in vars(core).items() if inspect.isfunction(v) and not (n.startswith("__") and n.endswith("__"))}


class CollaboratorInterfaceTest(RouterTestCase):
    def test_every_core_member_a_collaborator_uses_is_declared(self):
        for module, _, core, _ in COLLABORATORS:
            with self.subTest(module=module.__name__):
                self.assertEqual(sorted(used(module) - declared(core)), [], f"{module.__name__} uses a member of the core that {core.__name__} does not declare")

    def test_every_declared_member_is_one_the_collaborator_uses(self):
        for module, _, core, _ in COLLABORATORS:
            with self.subTest(module=module.__name__):
                self.assertEqual(sorted(declared(core) - used(module)), [], f"{core.__name__} declares a member {module.__name__} does not use")

    def test_control_every_declared_member_is_one_the_router_has(self):
        for module, _, core, _ in COLLABORATORS:
            with self.subTest(module=module.__name__):
                self.assertEqual(sorted(m for m in declared(core) if not hasattr(self.router, m)), [], f"{core.__name__} declares a member the Router does not have")

    def test_a_collaborator_holds_only_the_core_and_reaches_the_store_through_it(self):
        for module, cls, _, attribute in COLLABORATORS:
            with self.subTest(module=module.__name__):
                collaborator = getattr(self.router, attribute)
                self.assertIsInstance(collaborator, cls)
                self.assertEqual(vars(collaborator), {"_core": self.router})
                stray = [n.lineno for n in ast.walk(tree(module)) if isinstance(n, ast.Attribute) and ((n.attr == "_store" and not is_core(n.value)) or n.attr == "transaction")]
                self.assertEqual(stray, [], f"{module.__name__} reaches the store, or a transaction, other than as self._core._store (lines {stray})")

    def test_only_the_status_read_takes_the_core_snapshot(self):
        """`_snapshot` is the core's read transaction for status and health; it is the Store's own writable transaction, so what keeps a write out of it is this, not a type."""
        for module, _, _, _ in COLLABORATORS:
            with self.subTest(module=module.__name__):
                self.assertEqual("_snapshot" in used(module), module is status)

    def test_the_router_composes_its_collaborators_and_keeps_its_public_methods(self):
        self.assertFalse(isinstance(self.router, (status.Status, capabilities.Capabilities, registries.Registries)))
        self.assertEqual({n for n in dir(service.Router) if not n.startswith("_")}, PUBLIC_API)


if __name__ == "__main__":
    unittest.main()
