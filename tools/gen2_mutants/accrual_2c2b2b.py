"""Pure selection guards with independent hand-written positive controls."""
from .base import Mutation

TARGET = "gen2/accounting/__init__.py"
TEST = "test_accrual.AccrualTest."
SNAPSHOT = "test_accrual.SnapshotTest."
MUTATIONS = []
CONTROLS = {}


def guard(name, killer, control, old, new, target=TARGET):
    mid = "2C2B2B-" + name
    MUTATIONS.append(Mutation(mid, "2c-2b2b", name, (killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [control], "why": "Hand-written accepted operand fixture exercises the changed selection path; original judgments and dispositions remain available."}


def pure(name, killer, control, old, new):
    guard(name, TEST + killer, TEST + control, old, new)


pure("invalidation", "test_invalid_and_cycling", "test_control_compatible",
     'if any(c not in ("compatible", "lineage_only") for c in listed):', 'if False:')
pure("revision-standing", "test_missing_standing", "test_control_compatible",
     'listed = tuple(s.classification for impact in inventory.amendment_impacts\n                   for s in impact.standing if s.revision == revision)',
     'listed = tuple(s.classification for impact in inventory.amendment_impacts\n                   for s in impact.standing)')
pure("cycling", "test_invalid_and_cycling", "test_control_compatible",
     'for c in listed):', 'for c in listed[-1:]):')
pure("missing-current", "test_missing_standing", "test_control_current",
     'if inventory.current_contract_revision is None:\n        return "unknown"', 'if inventory.current_contract_revision is None:\n        return "current"')
pure("current-pin", "test_missing_standing", "test_control_current",
     'if revision == inventory.current_contract_revision:', 'if True:')
pure("current-impact", "test_missing_standing", "test_control_compatible",
     'if impact.current_revision == inventory.current_contract_revision', 'if True')
pure("compatible-revision", "test_missing_standing", "test_control_compatible",
     'for s in impact.standing if s.revision == revision)\n    return', 'for s in impact.standing)\n    return')
pure("missing-standing", "test_missing_standing", "test_control_compatible",
     'return "compatible" if current else "unknown"', 'return "compatible"')
pure("effective-labels", "test_invalid_and_cycling", "test_control_current",
     'if self.standing not in ("current", "compatible"):', 'if False:')
pure("lifecycle-work", "test_exact_joins_and_lifecycle_reversal", "test_control_current",
     'if (r.work_id, r.source_version) == (work_id, source_version))', 'if r.source_version == source_version)')
pure("lifecycle-version", "test_exact_joins_and_lifecycle_reversal", "test_control_current",
     'if (r.work_id, r.source_version) == (work_id, source_version))', 'if r.work_id == work_id)')
pure("lineage-join", "test_exact_joins_and_lifecycle_reversal", "test_control_current",
     'if l.assessment_id == r.assessment_id)', 'if True)')
pure("lifecycle-standing", "test_lifecycle_standing", "test_control_current",
     'LifecycleOperand(r, label_standing(inventory, r.contract_revision))', 'LifecycleOperand(r, "current")')
pure("semantic-work", "test_exact_joins_and_lifecycle_reversal", "test_control_current",
     'if (r.work_id, r.source_version) == (work_id, source_version) and', 'if r.source_version == source_version and')
pure("semantic-version", "test_exact_joins_and_lifecycle_reversal", "test_control_current",
     'if (r.work_id, r.source_version) == (work_id, source_version) and', 'if r.work_id == work_id and')
pure("semantic-date", "test_exact_joins_and_lifecycle_reversal", "test_control_current",
     'source_version) and utc_instant_ns(r.created_at) <= instant)', 'source_version) and True)')
pure("branch-empty", "test_missing_standing", "test_control_current", 'if not self.active or any(', 'if any(')
pure("branch-standing", "test_invalid_and_cycling", "test_control_current",
     'if not self.active or any(r.standing not in ("current", "compatible") for r in self.active):', 'if not self.active:')
pure("branch-kind", "test_disagreement_and_unrelated", "test_control_current", 'r.registry_kind == "branch" and ', '')
pure("branch-identity", "test_disagreement_and_unrelated", "test_control_current", 'r.registry_id == registry_id and ', '')
pure("branch-date", "test_control_branch_reversal", "test_control_current", 'and utc_instant_ns(r.created_at) <= instant),', 'and True),')
pure("branch-replacement", "test_control_branch_reversal", "test_control_current", 'for record in history if record.disposition_id not in replaced)', 'for record in history if True)')
pure("branch-disagreement", "test_disagreement_and_unrelated", "test_control_current",
     'for record in history if record.disposition_id not in replaced)', 'for record in history[:1] if record.disposition_id not in replaced)')
pure("reopened-id", "test_rescreening_recorded_only", "test_control_reopened", 'r.assessment_id in reopened and ', '')
pure("reopened-exclusion", "test_rescreening_recorded_only", "test_control_reopened", 'and r.decision == "exclude"', '')
for name, old, new in (
    ("read-current", 'approved = [r for r in records(rows, "contract_revisions") if r["status"] == "approved"]\n    current = approved[0]["revision"] if approved else None', 'approved = [r for r in records(rows, "contract_revisions") if r["status"] == "approved"]\n    current = None'),
    ("read-approved", 'records(rows, "contract_revisions") if r["status"] == "approved"', 'records(rows, "contract_revisions") if r["status"] == "draft"'),
    ("read-kind", 'r["kind"] == "contract"', 'r["kind"] == "brief"'),
    ("read-topic", '{predicate} ORDER BY', "{predicate if name != 'amendment_impacts' else '1=1'} ORDER BY"),
    ("read-standing", 'tuple(a.RevisionStanding(**s) for s in doc.get("standing", ()))', '()'),
    ("read-reopened", 'tuple(doc.get("reopened_exclusions", ()))', '()')):
    guard(name, SNAPSHOT + "test_reframe_inventory", SNAPSHOT + ("test_control_empty_topic" if name in ("read-current", "read-approved") else "test_control_initial" if name == "read-kind" else "test_control_context"), old, new,
          "gen2/store/capture.py" if name == "read-topic" else "gen2/router/accounting.py")
