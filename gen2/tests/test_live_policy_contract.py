"""Literal normalized vocabulary; neither examples nor labels grant admission."""
import copy
import json
import unittest
from pathlib import Path

from gen2.router.schemas import SchemaSet
from gen2.tests import router_fixtures as rf

EXAMPLES = Path(__file__).resolve().parents[1] / "schema/examples/live-vocabulary"
TARGET = "live-vocabulary.schema.json#/$defs/"


class LiveVocabulary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = SchemaSet()

    def test_literal_examples_and_one_bad_value_per_closed_field(self):
        cases = {
            "policy": {"run_id": "", "topic_id": "bad", "accounting_owner": "", "deadline_at": "2026-02-31T12:00:00Z",
                "max_attempts": 0, "max_concurrent_attempts": 0, "ceiling_minor_units": 0.5, "currency": "usd",
                "ceiling_scope": ["model"], "policy_version": ""},
            "attempt": {"run_id": "", "attempt": 0},
            "exchange": {"invocation_id": "bad", "live_attempt": {"run_id": "trial-1", "attempt": 0},
                "exchange_number": 0, "policy_hash": "bad"},
            "reported": {"state": "unknown", "value": -1},
            "unknown": {"state": "reported", "reason": ""},
            "cost": {"minor_units": 0.5, "currency": "usd"},
            "usage": {"input_tokens": None, "output_tokens": None, "cached_tokens": None, "cost": None,
                "elapsed_seconds": None, "gateway_credits": None},
        }
        for name, bad_fields in cases.items():
            fixture = json.loads((EXAMPLES / f"valid-{name}.json").read_text())
            target, valid = fixture["fixture"]["schema"], fixture["instance"]
            self.assertEqual(self.schemas.errors(valid, target), [], name)
            for field, value in bad_fields.items():
                with self.subTest(fragment=name, field=field):
                    invalid = {**copy.deepcopy(valid), field: value}
                    self.assertIn("/" + field, " ".join(self.schemas.errors(invalid, target)), (name, "bad value admitted"))
                    missing = copy.deepcopy(valid)
                    del missing[field]
                    self.assertEqual(self.schemas.errors(missing, target), [f"/: missing required '{field}'"])
            self.assertTrue(self.schemas.errors({**valid, "fixture": True}, target), (name, "extra field admitted"))

    def test_reported_zero_unknown_and_normalized_labels(self):
        for definition, valid, refused in (
            ("count_measurement", {"state": "reported", "value": 0}, {"state": "unknown", "reason": "missing", "value": 0}),
            ("cost_measurement", {"state": "reported", "value": {"minor_units": 0, "currency": "USD"}}, {"state": "reported", "value": 0}),
            ("quantity_measurement", {"state": "reported", "value": 0.5}, {"state": "reported", "value": -0.5}),
            ("gateway_call_ref", "gw-call-1", ""),
            ("disposition", "credentials_rejected", "401"),
            ("charge_state", "worst_case", "adjusted"),
        ):
            with self.subTest(definition=definition):
                self.assertEqual(self.schemas.errors(valid, TARGET + definition), [])
                self.assertTrue(self.schemas.errors(refused, TARGET + definition), "literal refusal admitted")
        for disposition in ("succeeded", "credentials_rejected", "transport_failed", "interrupted", "unknown"):
            self.assertEqual(self.schemas.errors(disposition, TARGET + "disposition"), [])
        self.assertEqual(self.schemas.errors("actual", TARGET + "charge_state"), [])
        for definition in ("cost_measurement", "quantity_measurement", "count_measurement"):
            self.assertEqual(self.schemas.errors({"state": "unknown", "reason": "not reported"}, TARGET + definition), [])
            for invalid in ({"state": "estimated", "value": 0}, {"state": "unknown", "reason": ""},
                            {"state": "unknown", "reason": "not reported", "value": 0}):
                self.assertTrue(self.schemas.errors(invalid, TARGET + definition), (definition, invalid))

    def test_fragments_cannot_activate_a_live_policy(self):
        self.assertEqual(self.schemas.errors(rf.BUNDLE, "config-bundle.schema.json"), [])
        policy = json.loads((EXAMPLES / "valid-policy.json").read_text())["instance"]
        bundle = copy.deepcopy(rf.BUNDLE)
        bundle["policy"]["live_trial"] = policy
        self.assertIn("live_trial", " ".join(self.schemas.errors(bundle, "config-bundle.schema.json")))
        self.assertTrue(self.schemas.errors(policy, "live-vocabulary.schema.json"))
