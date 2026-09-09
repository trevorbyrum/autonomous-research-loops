import unittest
import json
from pathlib import Path

from research_loops.input_schema import InterfaceError, validate_checkpoint_decision
from research_loops.intake import IntakeService, _validate_discovery, _validate_intake_decision
from research_loops.checkpoints.runner import validate_checkpoint_result


class InterfaceContractTests(unittest.TestCase):
    def test_documented_examples_pass_the_runtime_validators(self):
        root = Path(__file__).parents[1] / "research_loops" / "schema"
        validators = {"intake-brief.schema.json": IntakeService._brief,
                      "intake-discovery-result.schema.json": _validate_discovery,
                      "intake-decision.schema.json": _validate_intake_decision,
                      "interface-checkpoint-decision.schema.json": validate_checkpoint_decision,
                      "checkpoint-result.schema.json": validate_checkpoint_result}
        for name, validator in validators.items():
            schema = json.loads((root / name).read_text())
            for example in schema["examples"]:
                with self.subTest(schema=name):
                    validator(example)
                    with self.assertRaises(ValueError):
                        validator(example | {"undocumented_field": True})
    def test_checkpoint_actions_are_closed_and_edits_conditional(self):
        base = {"schema_version": 1, "request_id": "d1", "expected_revision": 1, "topic_id": "t", "episode_id": "e", "decisions": [{"proposal_id": "p", "proposal_version": 1, "action": "reject", "reason": "covered"}]}
        self.assertEqual(validate_checkpoint_decision(base)["decisions"][0]["action"], "reject")
        with self.assertRaises(InterfaceError) as raised:
            validate_checkpoint_decision(base | {"decisions": [base["decisions"][0] | {"action": "defer"}]})
        self.assertEqual(raised.exception.path, "$.decisions[0].action")
        with self.assertRaises(InterfaceError):
            validate_checkpoint_decision(base | {"decisions": [base["decisions"][0] | {"action": "approve_with_edits"}]})

    def test_discovery_requires_broad_fields_only_for_discovery(self):
        base = {"schema_version": 1, "request_id": "r", "expected_revision": 1, "topic_id": "t", "draft_revision": 1, "draft_hash": "a" * 64, "pass_kind": "criteria", "restated_intent": "intent", "criteria": [{"id": str(i), "status": "pass", "explanation": "checked"} for i in range(1, 7)], "traceability": [], "questions": []}
        self.assertEqual(_validate_discovery(base)["pass_kind"], "criteria")
        with self.assertRaises(InterfaceError): _validate_discovery(base | {"pass_kind": "discovery"})
        with self.assertRaises(InterfaceError): _validate_discovery(base | {"criteria": base["criteria"] + [base["criteria"][0]]})

    def test_intake_decision_reject_forbids_edits(self):
        value = {"schema_version": 1, "request_id": "x", "expected_revision": 1, "topic_id": "t", "draft_revision": 1, "result_id": "r", "action": "reject", "rationale": "no"}
        self.assertEqual(_validate_intake_decision(value)["action"], "reject")
        with self.assertRaises(InterfaceError): _validate_intake_decision(value | {"edits": {}})
