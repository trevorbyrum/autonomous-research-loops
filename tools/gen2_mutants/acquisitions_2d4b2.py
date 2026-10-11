"""Trusted acquisition admission guards; literal independent accepted controls."""
from .base import Mutation

TARGET, TEST = "gen2/router/acquisitions.py", "test_reaccess_admission.AdmissionTest.test_"
MUTATIONS, CONTROLS = [], {}


def change(name, killer, old, new, target=TARGET, control=None):
    mid = "2D4B2-" + name
    MUTATIONS.append(Mutation(mid, "2d-4b2", name, (TEST + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [control or TEST + "control"],
        "why": "A separately asserted literal retained exchange admits, preserves exact lineage/octets, and replays without another row or audit."}


def guard(name, expression, reason, killer):
    old = f'require({expression}, "{reason}")'
    change(name, killer, old, f'require(True, "{reason}")')


for field, operand in (("topic_id", 'inv["topic_id"]'), ("invocation_id", 'obs["invocation_id"]'),
        ("gateway_call_ref", 'obs["gateway_call_ref"]')):
    guard(field, f"capture.{field} == {operand}", "trusted capture " + {"topic_id": "topic", "invocation_id": "invocation", "gateway_call_ref": "call"}[field], "capture_attribution")
guard("attempt", 'type(capture.attempt) is int and capture.attempt == obs["attempt"]', "trusted capture attempt", "capture_attribution")
guard("request", 'capture.request_bytes == canonical.canonical_bytes(obs["request"])', "trusted capture request", "coherent_request_forgery")
guard("operands", 'self._operands(req, inv) == operands', "acquisition operands changed", "operand_fence")
guard("conflict", 'all(existing[k] == v for k, v in row.items())', "acquisition replay conflict", "conflict")
guard("role", 'inv["kind"] == "verification" and inv["admission_context"] == "contract/1"', "contract-admitted verifier required", "authority")
guard("live", 'inv["state"] == "running" and inv["cancel_requested_at"] is None', "live verifier required", "cancel_fence")
guard("state", 'inv["state"] == "running" and inv["cancel_requested_at"] is None', "live verifier required", "state")
guard("paused", 'topic["paused_at"] is None', "topic paused", "paused")
change("lease", "fences", 'self._core._require_current_lease(inv, now)', 'pass')
change("pins", "pins", 'self._core._require_current_pins(inv)', 'pass')
change("response-type", "response_type", 'type(capture.response_bytes) is bytes', 'isinstance(capture.response_bytes, (bytes, bytearray))')
change("request-type", "request_bytes", 'type(capture.request_bytes) is bytes', 'isinstance(capture.request_bytes, (bytes, bytearray))')
# Shape guards establish the specified refusal diagnostics; dropping them would
# merely dereference absent operands. Do not claim unsafe-evidence admission kills.
for name, reason, killer in (("reader", "trusted capture reader unavailable", "missing_reader"),
        ("capture", "trusted capture missing", "missing_capture"), ("operand", "recorded acquisition operand missing: ", "missing_operand")):
    change(name, killer, '"' + reason + '"', '"wrong refusal"')
change("validator", "response_binding", 'raw=capture.response_bytes', 'raw=self._core._gateway_captures.raw')
change("wiring", "control", 'return self._acquisitions.admit(request)', 'return self._acquisitions.admit({**request, "event_id": "rev_other0001"})',
    target="gen2/router/service.py", control="test_reaccess_admission.OtherAcquirerTest.test_control")
change("write", "control", 'self._core._store.insert("source_acquisitions", {**row, "admitted_at": now})',
    'self._core._store.insert("source_acquisitions", {**row, "admitted_at": now}) if row["acquired_by_invocation_id"] != "inv_capture001" else None',
    control="test_reaccess_admission.OtherAcquirerTest.test_control")
for suffix, killer in (("binding", "binding"), ("verifier", "verifier"), ("immutable_u", "immutable"), ("immutable_d", "immutable")):
    mid = "2D4B2-ddl-" + suffix
    MUTATIONS.append(Mutation(mid, "2d-4b2", suffix, ("test_store_acquisitions.DDLTest.test_" + killer,), drop_trigger="source_acquisitions_" + suffix))
    CONTROLS[mid] = {"controls": ["test_store_acquisitions.DDLTest.test_control"],
        "why": "Raw literal acquisition inserts with exact source/retrieval/verifier operands under the same DDL; SQL does not authenticate transport octets."}
for expression in ("o.gateway_call_ref = NEW.gateway_call_ref", "o.attempt = NEW.attempt", "o.lane = NEW.lane",
        "o.invocation_id = NEW.acquired_by_invocation_id", "json_extract(o.request, '$.request.request_type') = NEW.request_type",
        "e.provider_record_id = NEW.provider_record_id", "e.captured_at = NEW.retrieved_at", "o.request_identity = NEW.request_identity",
        "o.request = CAST(NEW.request_bytes AS TEXT)", "a.size_bytes = length(NEW.response_bytes)"):
    mid = "2D4B2-ddl-field-" + expression.split("NEW.")[1].split()[0].rstrip(")")
    MUTATIONS.append(Mutation(mid, "2d-4b2", expression, ("test_store_acquisitions.DDLTest.test_binding",),
        old=" AND " + expression, new="", scope="source_acquisitions_binding"))
    CONTROLS[mid] = CONTROLS["2D4B2-ddl-binding"]
