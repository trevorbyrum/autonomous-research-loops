"""Part 1 declaration and protocol guards; mapping guards await part 2."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
SCHEMA = "gen2/schema/contract-v2.schema.json"
FIX = "test_schema_counterfactuals.FixtureCounterfactualTest."
REQ = '"required": ["scheme_id", "version", "labels"]'


def guard(name, target, killer, control, old, new):
    mid = "2C4A-" + name
    MUTATIONS.append(Mutation(mid, "2c-4a-part-1", name, (killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [control], "why":
        "A separate literal valid scheme or compatible amendment executes the changed declaration/protocol guard and remains accepted under the mutant."}


for name, test, old, new in (
    ("closed", "closed", '"additionalProperties": false,\n      ' + REQ, '"additionalProperties": true,\n      ' + REQ),
    ("object", "closed", '"type": "object",\n      "additionalProperties": false,\n      ' + REQ, '"additionalProperties": false,\n      ' + REQ),
    ("id-required", "required_members", REQ, '"required": ["version", "labels"]'),
    ("version-required", "required_members", REQ, '"required": ["scheme_id", "labels"]'),
    ("labels-required", "required_members", REQ, '"required": ["scheme_id", "version"]'),
    ("id", "identity_version", '"scheme_id": {"$ref": "common.schema.json#/$defs/local_id"}', '"scheme_id": {"type": "string"}'),
    ("version", "identity_version", '"version": {"$ref": "common.schema.json#/$defs/revision"},\n        "labels": {', '"version": {"type": "integer"},\n        "labels": {'),
    ("labels-object", "labels_and_rubrics", '"type": "object", "minProperties": 1, "maxProperties": 50', '"minProperties": 1, "maxProperties": 50'),
    ("labels-nonempty", "labels_and_rubrics", '"type": "object", "minProperties": 1, "maxProperties": 50', '"type": "object", "maxProperties": 50'),
    ("labels-bounded", "labels_and_rubrics", '"type": "object", "minProperties": 1, "maxProperties": 50', '"type": "object", "minProperties": 1'),
    ("label", "labels_and_rubrics", '"propertyNames": {"$ref": "common.schema.json#/$defs/short_text"}', '"propertyNames": {}'),
    ("rubric", "labels_and_rubrics", '"propertyNames": {"$ref": "common.schema.json#/$defs/short_text"},\n          "additionalProperties": {"$ref": "common.schema.json#/$defs/long_text"}',
        '"propertyNames": {"$ref": "common.schema.json#/$defs/short_text"},\n          "additionalProperties": {}'),
):
    guard(name, SCHEMA, FIX + "test_confidence_scheme_" + test, FIX + "test_control_confidence_scheme", old, new)

guard("protocol-content", "gen2/router/amendments.py",
      "test_confidence_contract.SchemeClassificationTest.test_every_scheme_change_is_protocol_content",
      "test_confidence_contract.SchemeClassificationTest.test_control_unchanged_scheme",
      '"applicability_rules", "confidence_scheme")', '"applicability_rules")')
