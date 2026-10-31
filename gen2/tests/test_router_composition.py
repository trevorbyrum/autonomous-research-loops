"""Router composition (task 2q-b2; registries.py, 2q-b3; lifecycle.py, 2q-b6; scheduling.py, 2q-b7; amendments.py, 2q-b8; evidence_writer.py, 2q-b10): status.py, capabilities.py, registries.py, lifecycle.py, scheduling.py, amendments.py and evidence_writer.py are explicit collaborators the Router composes (it inherits no mixin), each declaring in its own
module the interface it takes of the core (a `typing.Protocol` the Router implements without inheriting it; BOUNDARIES.md, "Router
composition"). A protocol is not enforced at run time, so these keep it true: every member a collaborator reads off `self._core` is
declared, every declared member is one the collaborator uses and the Router has, the collaborator reaches the store only through the
core, and the Router's public methods are the ones it had when they were mixins. Direct sibling paths name a declared concrete
collaborator and a callable member on it. Shared handle parameter surfaces and capture variance are literal checks; sibling signatures,
aliases, argument/return types and full Protocol conformance remain outside these checks."""
import ast
import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

from gen2.router import acquisitions, amendments, assessments, capabilities, evidence_writer, lifecycle, observations, registries, scheduling, service, status, verification
from gen2.router import accounting, gates, detailed_checks, extractor_registry, extractions, history, protocols, support
from gen2.core.instants import utc_instant_ns
from gen2.tests.router_fixtures import RouterTestCase
from gen2.tests.test_capability_probe import observation

COLLABORATORS = ((accounting, accounting.Accounting, accounting.AccountingCore, "_accounting"),
                 (status, status.Status, status.StatusCore, "_status"), (capabilities, capabilities.Capabilities, capabilities.CapabilityCore, "_capabilities"),
                 (registries, registries.Registries, registries.RegistriesCore, "_registries"), (lifecycle, lifecycle.Lifecycle, lifecycle.LifecycleCore, "_lifecycle"),
                 (scheduling, scheduling.Scheduling, scheduling.SchedulingCore, "_scheduling"), (amendments, amendments.Amendments, amendments.AmendmentsCore, "_amendments"),
                 (evidence_writer, evidence_writer.EvidenceWriter, evidence_writer.EvidenceCore, "_evidence_writer"),
                 (assessments, assessments.Assessments, assessments.AssessmentCore, "_assessments"),
                 (verification, verification.Verification, verification.VerificationCore, "_verification"),
                 (acquisitions, acquisitions.AcquisitionAdmission, acquisitions.AcquisitionCore, "_acquisitions"),
                 (observations, observations.Observations, observations.ObservationCore, "_observations"),
                 (extractor_registry, extractor_registry.ExtractorRegistry, extractor_registry.ExtractorRegistryCore, "_extractor_registry"),
                 (extractions, extractions.ExtractionRecords, extractions.ExtractionCore, "_extractions"),
                 (detailed_checks, detailed_checks.DetailedChecks, detailed_checks.DetailedChecksCore, "_detailed_checks"))
PUBLIC_API = {  # Router's public methods at be5b2f1 plus intentional additions (evidence_inventory, task 2c-2a)
    "ack_delivery", "activate_config_bundle", "admit_reaccess", "apply_operator_decision", "claim", "close", "close_brief", "commit_outcome", "config_bundle", "create_topic", "draft_contract",
    "record_dossier", "candidate_units", "coverage_snapshot", "evidence_inventory", "healthy", "invocation_status", "is_qualified", "mark_brief_overdue", "open", "open_brief", "open_reservation", "open_review", "propose_amendment", "raise_signal",
    "receipt", "reconcile", "record_capability_probe", "record_gateway_facts", "record_observation", "record_qualification", "record_transition", "register_works",
    "request_cancel", "requeue", "restore_config_bundle", "revoke_qualification", "status", "version_brief", "register_extractor_registry"}


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

    def test_only_read_adapters_take_the_core_snapshot(self):
        """Status and acquisition operand reads name the core snapshot. Body purity
        remains reviewed separately; capture reads must finish before the writer fence."""
        for module, _, _, _ in COLLABORATORS:
            with self.subTest(module=module.__name__):
                self.assertEqual("_snapshot" in used(module), module in (status, acquisitions))

    def check_siblings(self, module, core, syntax):
        registry = {attribute: cls for _, cls, _, attribute in COLLABORATORS}
        imports = {a.asname or a.name: (n.module, a.name) for block in tree(module).body
                   if isinstance(block, ast.If) and isinstance(block.test, ast.Name) and block.test.id in ("TYPE_CHECKING",)
                   for n in block.body if isinstance(n, ast.ImportFrom) for a in n.names}
        for node in ast.walk(syntax):
            if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) and is_core(node.value.value)):
                continue
            attribute = node.value.attr
            if attribute in ("_store", "_schemas", "_spool", "_gateway_captures"):
                continue
            self.assertIn(attribute, declared(core))
            target = registry[attribute]
            annotation = core.__annotations__[attribute].strip("\"'")
            self.assertEqual(annotation, target.__name__)
            self.assertIn(annotation, imports)
            self.assertEqual(imports[annotation], (target.__module__, target.__name__))
            self.assertIs(type(getattr(self.router, attribute)), target)
            self.assertTrue(callable(getattr(target, node.attr, None)), f"{attribute}.{node.attr}")

    def test_sibling_members_exist_on_the_declared_concrete_target(self):
        for module, _, core, _ in COLLABORATORS:
            with self.subTest(module=module.__name__):
                self.check_siblings(module, core, tree(module))

    def test_sibling_check_rejects_undeclared_wrong_and_missing_targets(self):
        for expression in ("self._core._lifecycle.reconcile", "self._core._registries.missing", "self._core._registries.__module__"):
            with self.subTest(expression=expression), self.assertRaises(AssertionError):
                self.check_siblings(status, status.StatusCore, ast.parse(expression))
        with patch.dict(status.StatusCore.__annotations__, {"_registries": "Lifecycle"}), self.assertRaises(AssertionError):
            self.check_siblings(status, status.StatusCore, ast.parse("self._core._registries._active_bundle"))

    def test_capability_hold_uses_the_composed_registry_policy(self):
        with patch.object(self.router._registries, "_router_policy", return_value={"hold_window_s": 123}) as policy:
            reply = self.router.record_capability_probe(observation("05", "unusable_credential", "2026-09-27T10:00:05Z"))
            self.assertEqual(reply["status"], "recorded")
            policy.assert_called_once_with(self.router._registries._active_bundle()["bundle_hash"])
        deadline, created = self.rows("SELECT deadline_at,created_at FROM holds WHERE capability_fact_id = ?", reply["fact"]["fact_id"])[0]
        self.assertEqual(utc_instant_ns(deadline) - utc_instant_ns(created), 123_000_000_000)

    def test_registry_covers_every_constructed_collaborator(self):
        constructed = {n.targets[0].attr: vars(service)[n.value.func.id] for n in ast.walk(tree(service))
                       if isinstance(n, ast.Assign) and len(n.targets) in (1,) and isinstance(n.targets[0], ast.Attribute)
                       and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                       and len(n.value.args) in (1,) and isinstance(n.value.args[0], ast.Name) and n.value.args[0].id in ("self",)}
        self.assertEqual(constructed, {attribute: cls for _, cls, _, attribute in COLLABORATORS})

    def test_shared_handles_have_one_origin_and_restricted_members(self):
        for module in [m for m, _, _, _ in COLLABORATORS] + [history, support]:
            for name in ("Rows", "Schemas", "Spool"):
                if hasattr(module, name):
                    self.assertIs(getattr(module, name), getattr(protocols, name))
        for handle, members in ((protocols.Rows, {"select", "insert", "update", "capture_topic"}),
                                (protocols.Schemas, {"errors"}), (protocols.Spool, {"read", "media_type"})):
            self.assertEqual(declared(handle), members)
        self.assertEqual([n.module if isinstance(n, ast.ImportFrom) else None for n in ast.walk(tree(protocols))
                          if isinstance(n, (ast.Import, ast.ImportFrom))], ["typing"])

    def test_shared_handle_parameter_surfaces_and_capture_variance(self):
        empty = inspect.Parameter.empty
        expected = {
            protocols.Rows.select: (("self", "table", "where"), ("POSITIONAL_OR_KEYWORD",) * 3, (empty, empty, None)),
            protocols.Rows.insert: (("self", "table", "row"), ("POSITIONAL_OR_KEYWORD",) * 3, (empty, empty, empty)),
            protocols.Rows.update: (("self", "table", "key", "changes"), ("POSITIONAL_OR_KEYWORD",) * 4, (empty, empty, empty, empty)),
            protocols.Rows.capture_topic: (("self", "topic_id"), ("POSITIONAL_OR_KEYWORD",) * 2, (empty, empty)),
            protocols.Schemas.errors: (("self", "instance", "target"), ("POSITIONAL_OR_KEYWORD",) * 3, (empty, empty, empty)),
            protocols.Spool.read: (("self", "content_hash", "topic_id"), ("POSITIONAL_OR_KEYWORD", "POSITIONAL_OR_KEYWORD", "KEYWORD_ONLY"), (empty, empty, empty)),
            protocols.Spool.media_type: (("self", "content_hash", "topic_id"), ("POSITIONAL_OR_KEYWORD", "POSITIONAL_OR_KEYWORD", "KEYWORD_ONLY"), (empty, empty, empty)),
        }
        for method, (names, kinds, defaults) in expected.items():
            with self.subTest(method=method.__qualname__):
                parameters = tuple(inspect.signature(method).parameters.values())
                self.assertEqual(tuple(p.name for p in parameters), names)
                self.assertEqual(tuple(p.kind.name for p in parameters), kinds)
                self.assertEqual(tuple(p.default for p in parameters), defaults)
        self.assertIs(protocols.CaptureT_co.__covariant__, True)
        self.assertIs(protocols.CaptureT_co.__contravariant__, False)

    def test_private_forwarders_are_removed(self):
        deleted = {"_dossier_inputs", "_require_extractor_tool", "_active_bundle", "_bundle", "_router_policy", "_templates",
                   "_evidence", "_bind_evidence", "_record_artifact", "_require_delegates_ended", "_release_capacity",
                   "_open_unknown_hold", "_cancel_in_transaction", "_lane_last", "_admit_lane", "_draw", "_open_topic",
                   "_pin_status", "_brief_standing", "_record_impact", "_record_replacements", "_recorded_references",
                   "_require_current_pins", "_require_detailed_support", "_write_verification_holds"}
        self.assertFalse(deleted.intersection(vars(service.Router)))

    def test_the_router_composes_its_collaborators_and_keeps_its_public_methods(self):
        self.assertFalse(isinstance(self.router, (status.Status, capabilities.Capabilities, registries.Registries, lifecycle.Lifecycle, scheduling.Scheduling, amendments.Amendments, evidence_writer.EvidenceWriter, assessments.Assessments)))
        self.assertEqual(service.Router.__bases__, (object,))  # the last mixin is gone
        self.assertEqual({n for n in dir(service.Router) if not n.startswith("_")}, PUBLIC_API)

    def test_the_production_evaluator_is_the_default_and_fixed_per_router(self):
        self.assertIs(inspect.signature(service.Router.__init__).parameters["evaluate"].default, gates.evaluate)
        self.assertIs(self.router._evaluate, gates.evaluate)


if __name__ == "__main__":
    unittest.main()
