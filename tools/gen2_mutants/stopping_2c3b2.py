"""2c-3b2: closed vocabulary, exact bindings and recorded G-1 reuse."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
STOP = "gen2/accounting/stopping.py"
SCHEMA = "gen2/schema/contract-v2.schema.json"
BIND = "test_stopping_protocol.BindingTest."
PROTO = "test_stopping_protocol.ProtocolTest."
FIX = "test_schema_counterfactuals.FixtureCounterfactualTest."


def guard(name, target, killer, control, old, new):
    mid = "2C3B2-" + name
    MUTATIONS.append(Mutation(mid, "2c-3b2", name, (killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [control], "why":
        "The separate literal valid declaration/evaluation or compatible Router reuse control traverses the changed guard and remains accepted."}


guard("descriptive-closed", SCHEMA, FIX + "test_descriptive_has_no_threshold_parameters", FIX + "test_control_stopping_families_and_old_document",
      '"params": {"type": "object", "additionalProperties": false, "properties": {}}',
      '"params": {"type": "object", "additionalProperties": true, "properties": {}}')
for name, old, new in (
    ("coverage-closed", '"type": "object", "additionalProperties": false,\n                "required": ["minimum_windows", "scope"]',
                        '"type": "object", "additionalProperties": true,\n                "required": ["minimum_windows", "scope"]'),
    ("minimum-required", '"required": ["minimum_windows", "scope"]', '"required": ["scope"]'),
    ("scope-required", '"required": ["minimum_windows", "scope"]', '"required": ["minimum_windows"]'),
    ("minimum-positive", '"minimum_windows": {"type": "integer", "minimum": 1}', '"minimum_windows": {"type": "integer", "minimum": 0}'),
    ("minimum-integer", '"minimum_windows": {"type": "integer", "minimum": 1}', '"minimum_windows": {"type": "number", "minimum": 1}'),
    ("scope-array", '"scope": {"type": "array", "uniqueItems": true,', '"scope": {"uniqueItems": true,'),
    ("scope-unique", '"scope": {"type": "array", "uniqueItems": true,', '"scope": {"type": "array", "uniqueItems": false,'),
    ("scope-identity", '"scope": {"type": "array", "uniqueItems": true, "items": {"$ref": "common.schema.json#/$defs/invocation_id"}}',
                       '"scope": {"type": "array", "uniqueItems": true, "items": {"type": "string"}}'),
):
    guard(name, SCHEMA, FIX + "test_coverage_has_closed_required_parameters", FIX + "test_control_stopping_families_and_old_document", old, new)

guard("descriptive-binding", STOP, BIND + "test_control_descriptive", BIND + "test_control_coverage",
      'if binding.evaluator == "descriptive":', 'if False:')
guard("coverage-binding", STOP, BIND + "test_control_coverage", BIND + "test_control_descriptive",
      'if binding.evaluator == "coverage":', 'if False:')
guard("declared-minimum", STOP, BIND + "test_declared_minimum_and_scope", BIND + "test_control_coverage",
      'pins, binding.params["minimum_windows"], scope=', 'pins, 1, scope=')
guard("declared-scope", STOP, BIND + "test_declared_minimum_and_scope", BIND + "test_control_coverage_evaluation",
      'scope=frozenset(binding.params["scope"])', 'scope=None')
guard("dated-descriptive", STOP, BIND + "test_required_runtime_operands", BIND + "test_control_descriptive",
      'if as_of is None:', 'if as_of is None:\n            as_of = "2026-10-09T00:00:00Z"\n        if False:')
guard("sentinel-required", STOP, BIND + "test_required_runtime_operands", 'test_stopping_bindings.BindingTest.test_control_retrieval_binding',
      'if declared is None:', 'if declared is None:\n        declared = KnownItems(EvidenceReference(**binding.params["sentinel_set"]), frozenset())\n    if False:')
guard("incompatible-reused", STOP, BIND + "test_recorded_invalidation_with_same_protocol", PROTO + "test_control_compatible_reuse",
      'and label_standing(inventory, original.contract_revision) in ("current", "compatible")', 'and True')
for name, old, new in (
    ("snapshot-current", 'inventory.current_contract_revision == current.contract_revision', 'True'),
    ("topic-pin", 'original.topic_id == current.topic_id', 'True'),
    ("protocol-pin", 'original.protocol_revision == current.protocol_revision', 'True'),
):
    guard(name, STOP, BIND + "test_reuse_requires_current_snapshot_and_exact_context", PROTO + "test_control_compatible_reuse", old, new)
guard("compatibility-refused", STOP, PROTO + "test_control_compatible_reuse", BIND + "test_control_current_profile",
      'in ("current", "compatible"))', 'in ("current",))')
guard("old-gates-reused", STOP, PROTO + "test_control_compatible_reuse", BIND + "test_control_current_profile",
      'g.state if g.context == context else "unknown"', 'g.state')
guard("sentinel-hash-unbound", STOP, 'test_stopping_bindings.BindingTest.test_inventory_reference_and_reviewed_execution_are_refused',
      'test_stopping_bindings.BindingTest.test_control_retrieval_binding',
      'if declared.reference != EvidenceReference(**binding.params["sentinel_set"]):',
      'if (declared.reference.size_bytes, declared.reference.media_type) != (binding.params["sentinel_set"]["size_bytes"], binding.params["sentinel_set"]["media_type"]):')
