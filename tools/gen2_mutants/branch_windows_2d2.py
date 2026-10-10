"""2d-2 provenance guards, each with a separate accepted control."""
from .base import Mutation

TEST = "test_branch_windows.AdmissionTest."
TARGET = "gen2/router/assessments.py"
READER = "gen2/router/accounting.py"
SCHEMA = "gen2/schema/branch-window.schema.json"
MUTATIONS = []


def guard(name, killer, old, new="if False:", target=TARGET):
    MUTATIONS.append(Mutation("2D2-" + name, "2d-2", name, (TEST + killer,), target=target, old=old, new=new))


guard("actor", "test_actor", 'raise Refusal("kind_not_permitted", "branch/window associations require contract-admitted primary work")', 'return')
guard("branch", "test_branch", 'if branch is None or (branch["topic_id"], branch["registry_kind"], branch["registry_id"]) != (inv["topic_id"], "branch", record["registry_id"]):')
guard("window", "test_window", 'if window is None or (window["topic_id"], window["kind"], window["admission_context"]) != (inv["topic_id"], "research_pass", "contract/1"):', 'if window is None:')
guard("contract", "test_unverified_contract", 'if contract is None or contract["status"] not in ("approved", "superseded") or contract["approved_by_decision_id"] is None:')
guard("write", "test_control", 'for record in payload.get("branch_windows", []):\n            self._core._store.insert', 'for record in ():\n            self._core._store.insert')
guard("read-branch", "test_unverified_branch", 'if branch is None or branch.registry_id != record["registry_id"] or record["window_invocation_id"] not in windows:', target=READER)
guard("read-commit", "test_unverified_commit", 'if not receipts or (receipts[0]["topic_id"], receipts[0]["invocation_id"]) != (topic_id, record["invocation_id"]):', target=READER)
guard("read-contract", "test_unverified_contract", 'if not contracts or contracts[0]["status"] not in ("approved", "superseded") or contracts[0]["approved_by_decision_id"] is None:', 'if not contracts:', READER)
guard("pin-kind", "test_pin_kind", '{"topic_id": topic_id, "kind": "research_pass", "admission_context": "contract/1"}', '{"topic_id": topic_id, "admission_context": "contract/1"}', READER)
guard("historical-pin", "test_historical_pins", 'contracts[0]["revision"]))', 'max(r["revision"] for r in rows.select("contract_revisions", {"topic_id": topic_id}))))', READER)
guard("schema-attribution", "test_forged_pins_and_attribution", '"type": "object", "additionalProperties": false,', '"type": "object", "additionalProperties": true,', SCHEMA)
guard("schema-subjects", "test_required_subjects", '"association_id", "registry_id", "branch_disposition_id", "window_invocation_id"', '"association_id", "branch_disposition_id", "window_invocation_id"', SCHEMA)
guard("snapshot-history", "test_unknown_and_snapshot", '"""Capture admitted links and invocation-derived pins; compute views after returning."""\n        if history not in ("native", "legacy_unknown"):', '"""Capture admitted links and invocation-derived pins; compute views after returning."""\n        if False:', "gen2/router/service.py")
guard("snapshot-topic", "test_unknown_and_snapshot", 'if self._one("queue_entries", {"topic_id": topic_id}) is None:\n                raise Refusal("unknown_topic", topic_id)\n            return read_coverage_snapshot', 'if False:\n                raise Refusal("unknown_topic", topic_id)\n            return read_coverage_snapshot', "gen2/router/service.py")

for suffix in ("branch", "window", "commit", "immutable_u", "immutable_d"):
    trigger = "branch_windows_" + suffix
    MUTATIONS.append(Mutation("2D2-" + trigger, "2d-2", trigger, ("test_branch_windows.DDLTest.test_guards",), drop_trigger=trigger))

CONTROLS = {m.mid: {"controls": ["test_branch_windows.DDLTest.test_control" if m.target == "ddl" else TEST +
    ("test_noop_control" if m.mid == "2D2-write" else "test_schema_control" if m.target == SCHEMA else "test_control")],
    "why": "A literal admitted branch/window under its exact contract remains accepted; the no-record write and complete schema controls exercise their respective boundaries."}
    for m in MUTATIONS}
