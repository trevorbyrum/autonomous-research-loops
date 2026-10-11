"""Pure fixture acquisition hand-off (flow S4 step 8; V-1/V-3).

Operands are retained source/artifact/observation/event/work-link rows and
gateway response bytes. The future Router adapter must select and authenticate
these operands: consistency alone cannot authenticate caller-supplied records.
This module grants no tier, extraction-validation or support authority.
"""
from dataclasses import dataclass

from gen2.core import canonical


class ReaccessRefused(ValueError):
    pass


@dataclass(frozen=True)
class Acquisition:
    topic_id: str
    work_id: str
    source_version: str
    content_hash: str
    observation_id: str
    event_id: str
    gateway_call_ref: str
    acquired_by_invocation_id: str
    attempt: int
    lane: str
    request_type: str
    provider_record_id: str
    retrieved_at: str


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ReaccessRefused(reason)


def _rows(source: dict, artifact: dict, observation: dict, event: dict, link: dict, raw: bytes) -> None:
    _require(source["topic_id"] == observation["topic_id"] == event["topic_id"], "acquisition topic")
    _require(link["work_id"] == source["work_id"], "acquisition work")
    _require(link["event_id"] == event["event_id"], "acquisition work link")
    _require(event["observation_id"] == observation["observation_id"], "acquisition observation")
    _require(source["content_hash"] == artifact["content_hash"], "source artifact identity")
    _require(canonical.bytes_digest(raw) == artifact["content_hash"], "acquisition bytes digest")
    _require(len(raw) == artifact["size_bytes"], "acquisition bytes size")
    _require(artifact["media_type"] == "application/json", "canonical gateway media type")
    _require(observation["coverage_state"] in ("searched_ok", "metadata_only")
             and observation["completeness"] in ("complete", "partial"), "observed acquisition")
    request = observation["request"]
    _require(canonical.logical_hash(request) == observation["request_identity"], "attempted request identity")
    _require(request["lane"] == observation["lane"], "recorded request lane")
    _require(request["request"]["request_type"] in ("find", "resolve", "enrich", "fetch", "data"), "recorded request type")


def _capture(document: dict, observation: dict) -> None:
    capture = document.get("observation")
    _require(isinstance(capture, dict), "gateway capture missing")
    _require(capture.get("captured") is True, "gateway capture unacknowledged")
    call = capture.get("call_ref")
    _require(type(call) is int and call >= 1, "gateway capture call type")
    _require(observation["gateway_call_ref"] == f"gw-call:{call}", "gateway capture call binding")
    _require(capture.get("invocation_id") == observation["invocation_id"], "gateway capture invocation")
    _require(type(capture.get("attempt")) is int and capture["attempt"] == observation["attempt"], "gateway capture attempt")
    _require(document.get("request_type") == observation["request"]["request"]["request_type"], "gateway request route")


def _retrieved(document: dict, observation: dict, event: dict) -> None:
    lanes, records = document.get("lanes"), document.get("records")
    _require(isinstance(lanes, list) and isinstance(records, list), "gateway response lists")
    matching = [lane for lane in lanes if isinstance(lane, dict) and lane.get("source") == observation["lane"]]
    _require(len(matching) == 1, "gateway acquisition lane")
    lane = matching[0]
    _require(lane.get("coverage") == observation["coverage_state"]
             and lane.get("completeness") == observation["completeness"], "gateway lane availability")
    retrieved = lane.get("retrieved")
    _require(isinstance(retrieved, list) and event["provider_record_id"] in retrieved, "gateway retrieved identity")
    _require(any(isinstance(record, dict) and record.get("identity") == event["provider_record_id"]
                 for record in records), "gateway canonical record missing")


def check_reaccess(*, source: dict, artifact: dict, observation: dict, event: dict, link: dict, raw: bytes) -> Acquisition:
    """Bind canonical response bytes, whoever acquired them; never accept labels.

    Only inline retained fixture responses are supported here. Queued/job and
    record-cache envelopes without lane capture need their own retained bindings
    in the later admission slice. Partial retrieval is real but proves no coverage
    exhaustion, full-text access or table availability.
    """
    _rows(source, artifact, observation, event, link, raw)
    try:
        document = canonical.parse_json_strict(raw)
    except canonical.CanonicalizationError as exc:
        raise ReaccessRefused("canonical gateway JSON") from exc
    _require(isinstance(document, dict), "canonical gateway envelope")
    _capture(document, observation)
    _retrieved(document, observation, event)
    return Acquisition(source["topic_id"], source["work_id"], source["source_version"], artifact["content_hash"],
        observation["observation_id"], event["event_id"], observation["gateway_call_ref"], observation["invocation_id"],
        observation["attempt"], observation["lane"], observation["request"]["request"]["request_type"],
        event["provider_record_id"], event["captured_at"])
