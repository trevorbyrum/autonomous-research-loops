"""Lossless mapper guards and closed additive /2 schema controls."""
import json
from pathlib import Path
from .base import Mutation

CODE = "gen2/accounting/reconciliation.py"
SCHEMA = "gen2/schema/export-bundle-v2.schema.json"
TEST = "test_reconciliation_bundle.BundleTest."
MUTATIONS, CONTROLS = [], {}


def guard(name, target, old, new, killer="test_exact_fixture_and_inverse", control="test_control_supported"):
    mid = "2C4A3-" + name
    MUTATIONS.append(Mutation(mid, "2c-4a3", name, (TEST + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [TEST + control], "why":
        "A separate literal accepted case exercises the mapped field or schema guard and remains accepted with its exact original values."}


guard("contradicted-collapsed", CODE, 'data.pop("obligations")', '[{**x, "disposition": "not_supported"} if x.get("disposition") == "contradicted" else x for x in data.pop("obligations")]')
guard("deferred-dropped", CODE, 'data.pop("obligations")', '[x for x in data.pop("obligations") if x.get("disposition") != "deferred"]')
guard("open-unresolved", CODE, 'data.pop("obligations")', '[{**{k: v for k, v in x.items() if k != "state"}, "disposition": "unresolved"} if "state" in x else x for x in data.pop("obligations")]')
guard("outcome-null", CODE, '    return bundle\n', '    bundle["completion"]["outcome"] = None\n    return bundle\n', control="test_control_absent_outcome")
guard("confidence-unchecked", CODE, '        check_confidence(record, approved_contracts[record.contract_revision])', '        pass', "test_mapper_guards")
guard("topic-unchecked", CODE, 'if record.topic_id != operands.topic_id:', 'if False:', "test_mapper_guards")
guard("assembly-overlap", CODE, 'if MAPPED_FIELDS.intersection(assembly_fields):', 'if False:', "test_mapper_guards")
guard("inverse-version", CODE, 'if bundle["bundle_version"] != "export-bundle/2":', 'if False:', "test_mapper_guards")
document = json.loads((Path(__file__).resolve().parents[2] / SCHEMA).read_text())
for name, node in (("bundle", document), *document["$defs"].items()):
    if node.get("type") != "object": continue
    header = '\n  "type": "object", "additionalProperties": false,' if name == "bundle" else '    "' + name + '": {\n' + ('      "description": "Scientific completion status and recorded G-9 outcome are independent facts; an absent outcome is explicit null.",\n' if name == "completion" else '') + '      "type": "object", "additionalProperties": false,'
    guard(name + "-closed", SCHEMA, header, header.replace('false', 'true'), "test_schema_guards", "test_exact_fixture_and_inverse")
    guard(name + "-required", SCHEMA, '"required": ' + json.dumps(node["required"]), '"required": []', "test_schema_guards", "test_exact_fixture_and_inverse")
    if name != "obligation":
        guard(name + "-object", SCHEMA, header, header.replace('"type": "object", ', ''), "test_schema_guards", "test_exact_fixture_and_inverse")
guard("disposition-vocabulary", SCHEMA, '["supported", "contradicted", "unresolved", "deferred"]', '["supported", "contradicted", "unresolved", "deferred", "not_supported"]', "test_schema_guards", "test_exact_fixture_and_inverse")
guard("open-confidence", SCHEMA, '"confidence": {"properties": {"basis": {"const": "unknown"}}}', '"confidence": {}', "test_schema_guards", "test_exact_fixture_and_inverse")
