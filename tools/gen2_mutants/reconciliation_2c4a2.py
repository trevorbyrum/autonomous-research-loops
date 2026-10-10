"""First-slice confidence guards; bundle mapping guards belong to the next slice."""
from .base import Mutation

TARGET = "gen2/accounting/reconciliation.py"
TEST = "test_reconciliation_operands.ConfidenceOperandTest."
MUTATIONS, CONTROLS = [], {}


def guard(name, killer, old, new, control="test_control_recorded"):
    mid = "2C4A2-" + name
    MUTATIONS.append(Mutation(mid, "2c-4a2-first-slice", name, (TEST + killer,), target=TARGET, old=old, new=new))
    CONTROLS[mid] = {"controls": [TEST + control], "why":
        "An independently specified accepted confidence reaches the changed line or its immediate guard and remains accepted with the exact original value."}


guard("scheme-id", "test_off_scheme_refused", 'confidence.scheme.scheme_id != scheme["scheme_id"]', 'False')
guard("scheme-version", "test_off_scheme_refused", 'confidence.scheme.version != scheme["version"]', 'False')
guard("scheme-label", "test_off_scheme_refused", 'confidence.label not in scheme["labels"]', 'False')
guard("version-bool", "test_off_scheme_refused", 'type(confidence.scheme.version) is not int', 'False')
guard("unknown-defaulted", "test_control_unknown", '        return confidence\n    if not isinstance',
      '        return RecordedConfidence("recorded_assessment", SchemePin("default", 1), "high", record.invocation_id)\n    if not isinstance')
guard("unknown-reason", "test_unknown_requires_reason", ' or not confidence.reason.strip()', '', "test_control_unknown")
guard("unknown-basis", "test_explicit_basis_required", 'confidence.basis != "unknown"', 'False', "test_control_unknown")
guard("recorded-basis", "test_explicit_basis_required", 'confidence.basis != "recorded_assessment"', 'False')
guard("contract-pins", "test_exact_pins_required", 'if pins != declared:', 'if False:')
guard("open-assessed", "test_open_cannot_have_recorded_confidence",
      'if isinstance(record, OpenObligation) and not isinstance(confidence, UnknownConfidence):', 'if False:', "test_control_open")
guard("missing-scheme", "test_missing_scheme_refused", 'raise ValueError("contract declares no confidence scheme")',
      'return confidence')
