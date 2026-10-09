"""2c-3b part 1: both G-11 boundaries and literal binding controls."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
TEST = "test_stopping_bindings."
STOP = "gen2/accounting/stopping.py"
AMD = "gen2/router/amendments.py"
SVC = "gen2/router/service.py"


def guard(name, target, killer, control, old, new):
    mid = "2C3B-" + name
    MUTATIONS.append(Mutation(mid, "2c-3b-part-1", name, (TEST + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [TEST + control], "why":
        "The literal retrieval or reviewed control passes the changed guard and asserts its declared binding or Router result."}


guard("admission-only", SVC, "ApprovalTest.test_each_unsupported_rule_at_approval", "ApprovalTest.test_control_supported_approval",
      'stopping_defect(revision["document"], self._schemas) or ', '')
guard("approval-only", AMD, "AdmissionTest.test_each_unsupported_rule_at_admission", "AdmissionTest.test_control_supported_admission",
      'defect = stopping_defect(req["document"], self._core._schemas)', 'defect = None')
guard("rule-schema", AMD, "ApprovalTest.test_each_unsupported_rule_at_approval", "ApprovalTest.test_control_supported_approval",
      'errors = schemas.errors(rule, "contract-v2.schema.json#/$defs/stopping_rule")', 'errors = []')
guard("profile-schema", AMD, "ApprovalTest.test_invalid_profile_at_approval", "ApprovalTest.test_control_supported_approval",
      'errors = schemas.errors(profile, "contract-v2.schema.json#/$defs/stopping_profile")', 'errors = []')
guard("support-unchecked", AMD, "ApprovalTest.test_each_unsupported_rule_at_approval", "ApprovalTest.test_control_supported_approval",
      '            bind_profile(profile)', '            pass')
guard("unknown-kind", STOP, "BindingTest.test_every_unsupported_binding", "BindingTest.test_control_reviewed_binding",
      'if family not in ("diminishing_returns",', 'if False and family not in ("diminishing_returns",')
guard("automatic-kind", STOP, "BindingTest.test_every_unsupported_binding", "BindingTest.test_control_retrieval_binding",
      'if family not in ("known_item", "descriptive", "coverage"):', 'if family not in ("known_item", "descriptive", "coverage", "statistical_target_recall"):')
guard("screening-reinterpreted", STOP, "BindingTest.test_every_unsupported_binding", "BindingTest.test_control_retrieval_binding",
      'if family == "known_item" and rule["params"]["tests"] != "retrieval":', 'if False:')
guard("unknown-mode", STOP, "BindingTest.test_every_unsupported_binding", "BindingTest.test_control_retrieval_binding",
      'elif mode != "reviewed_judgment":', 'elif False:')
guard("parameters-alias", STOP, "BindingTest.test_control_reviewed_binding", "BindingTest.test_control_retrieval_binding",
      'deepcopy(rule["params"])', 'rule["params"]')
guard("reference-unbound", STOP, "BindingTest.test_inventory_reference_and_reviewed_execution_are_refused", "BindingTest.test_control_retrieval_binding",
      'if declared.reference != EvidenceReference(**binding.params["sentinel_set"]):', 'if False:')
guard("reviewed-executed", STOP, "BindingTest.test_inventory_reference_and_reviewed_execution_are_refused", "BindingTest.test_control_retrieval_binding",
      'if binding.evaluator != "known_item":', 'if False:')
guard("expression-reinterpreted", STOP, "BindingTest.test_expression_and_parameters_are_retained", "BindingTest.test_control_retrieval_binding",
      'Expression(op=document["op"], operands=', 'Expression(op="all", operands=')
