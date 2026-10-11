"""Canonical fixture acquisition bindings with literal accepted controls."""
from .base import Mutation

TEST = "test_reaccess.ReaccessTest.test_"
TARGET = "gen2/router/reaccess.py"
MUTATIONS, CONTROLS = [], {}


def guard(name, expression, reason, killer=None):
    mid = "2D4B-" + name
    old = f'_require({expression}, "{reason}")'
    MUTATIONS.append(Mutation(mid, "2d-4b", reason, (TEST + (killer or name.replace("-", "_")),),
        target=TARGET, old=old, new=f'_require(True, "{reason}")'))
    CONTROLS[mid] = {"controls": [TEST + "producer_bytes_control"],
        "why": "Literal producer-acquired canonical response traverses this binding and keeps its exact immutable acquisition lineage."}


guard("topic", 'source["topic_id"] == observation["topic_id"] == event["topic_id"]', "acquisition topic")
guard("work", 'link["work_id"] == source["work_id"]', "acquisition work")
guard("work-link", 'link["event_id"] == event["event_id"]', "acquisition work link")
guard("observation", 'event["observation_id"] == observation["observation_id"]', "acquisition observation")
guard("source-identity", 'source["content_hash"] == artifact["content_hash"]', "source artifact identity")
guard("bytes-digest", 'canonical.bytes_digest(raw) == artifact["content_hash"]', "acquisition bytes digest")
guard("bytes-size", 'len(raw) == artifact["size_bytes"]', "acquisition bytes size")
guard("media", 'artifact["media_type"] == "application/json"', "canonical gateway media type")
guard("unobserved", 'observation["coverage_state"] in ("searched_ok", "metadata_only")\n             and observation["completeness"] in ("complete", "partial")',
      "observed acquisition", killer="completeness")
guard("request-identity", 'canonical.logical_hash(request) == observation["request_identity"]', "attempted request identity")
guard("request-lane", 'request["lane"] == observation["lane"]', "recorded request lane")
guard("request-type", 'request["request"]["request_type"] in ("find", "resolve", "enrich", "fetch", "data")', "recorded request type")
guard("summary", 'isinstance(capture, dict)', "gateway capture missing")
guard("capture", 'capture.get("captured") is True', "gateway capture unacknowledged")
guard("call-type", 'type(call) is int and call >= 1', "gateway capture call type")
guard("call-binding", 'observation["gateway_call_ref"] == f"gw-call:{call}"', "gateway capture call binding")
guard("invocation", 'capture.get("invocation_id") == observation["invocation_id"]', "gateway capture invocation")
guard("attempt", 'type(capture.get("attempt")) is int and capture["attempt"] == observation["attempt"]', "gateway capture attempt")
guard("route", 'document.get("request_type") == observation["request"]["request"]["request_type"]', "gateway request route")
guard("response-lists", 'isinstance(lanes, list) and isinstance(records, list)', "gateway response lists")
guard("lane", 'len(matching) == 1', "gateway acquisition lane", killer="duplicate_lane")
guard("availability", 'lane.get("coverage") == observation["coverage_state"]\n             and lane.get("completeness") == observation["completeness"]', "gateway lane availability")
guard("identity", 'isinstance(retrieved, list) and event["provider_record_id"] in retrieved', "gateway retrieved identity")
guard("canonical-record", 'any(isinstance(record, dict) and record.get("identity") == event["provider_record_id"]\n                 for record in records)',
      "gateway canonical record missing")
guard("envelope", 'isinstance(document, dict)', "canonical gateway envelope")

# Output attribution matters independently of whether admission refused.
MUTATIONS.append(Mutation("2D4B-acquirer", "2d-4b", "retain actual acquiring invocation",
    (TEST + "other_acquirer_control",), target=TARGET,
    old='observation["gateway_call_ref"], observation["invocation_id"],',
    new='observation["gateway_call_ref"], "inv_producer01",'))
CONTROLS["2D4B-acquirer"] = {"controls": [TEST + "producer_bytes_control"],
    "why": "Equal acquisition attribution is a literal accepted control for the substituted acquirer."}

MUTATIONS.append(Mutation("2D4B-json", "2d-4b", "duplicate JSON keys are not canonical transport",
    (TEST + "json",), target=TARGET, old='document = canonical.parse_json_strict(raw)', new='document = json.loads(raw)',
    also=(('from dataclasses import dataclass', 'from dataclasses import dataclass\nimport json'),)))
CONTROLS["2D4B-json"] = {"controls": [TEST + "producer_bytes_control"],
    "why": "A canonical response without duplicate keys traverses both parsers and retains the exact expected lineage."}
