"""2e1 v7 §4-§5 (traces A, U): access-log rejection classifier and per-attempt usage record.

Pure functions over bytes already collected and staged (docker_cli.EvidenceBatch);
nothing here launches, reads files or grants Router authority. Oracle: the
conjunction of v7 §4 ("negative oracle"), never runner text. Anything missing,
extra, malformed or conflicting is `unknown`, which the caller treats as fixed
U / permanent stop. Limits: no claim that every silently lost log row is
detected; a real route is attested by deployment provenance, not by this file.

Interface for the fixture (T6): `fixture.json` is
`{"v": 1, "requests": [{"id", "route", "model", "credential"}]}` with
`credential` "rejected" or "accepted"; it holds no key.
"""
import json

from gen2.supervisor.isolation import LiveProfileRefused

LOG_KEYS = ("v", "id", "src", "port", "conn", "ordinal", "listener", "server_port", "method", "route",
            "upstream", "status", "upstream_status", "complete", "at")
MODEL_ROW = {"v": 3, "src": "172.31.254.3", "ordinal": "1", "listener": "model", "server_port": "8080",
             "method": "POST", "route": "model", "upstream": "172.31.252.3:8081", "complete": "OK"}
EVENTS = frozenset({"thread.started", "turn.started", "error", "turn.failed"})
TRANSPORT = frozenset({"429", "502", "503", "504"})


class Unknown(Exception):
    """Evidence cannot support a disposition; the message is the reason."""


def _object(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise Unknown("duplicate_key")
    return dict(pairs)


def _jsonl(data, name, line=64 << 10, total=4 << 20, rows=1024):
    """Strict newline-terminated JSONL of objects, bounded."""
    if not isinstance(data, bytes) or len(data) > total or (data and not data.endswith(b"\n")):
        raise Unknown(name + "_framing")
    lines = data.split(b"\n")[:-1]
    if len(lines) > rows or any(len(text) > line for text in lines):
        raise Unknown(name + "_bound")
    try:
        parsed = [json.loads(text, object_pairs_hook=_object, parse_constant=_refuse) for text in lines]
    except (ValueError, RecursionError) as error:
        raise Unknown(name + "_malformed") from error
    if not all(isinstance(row, dict) for row in parsed):
        raise Unknown(name + "_shape")
    return parsed


def _refuse(_):
    raise ValueError("constant")


def _rows(access):
    rows = _jsonl(access, "access")
    ids = [row.get("id") for row in rows]
    for row in rows:
        if set(row) != set(LOG_KEYS):
            raise Unknown("access_keys")
        if type(row["v"]) is not int or row["v"] != 3 or not all(isinstance(row[k], str) and len(row[k]) <= 256 for k in LOG_KEYS[1:]):
            raise Unknown("access_types")
    if len(set(ids)) != len(ids):
        raise Unknown("access_duplicate_id")
    return rows


def _fixture(data, row, model):
    record = json.loads(data, object_pairs_hook=_object) if isinstance(data, bytes) and len(data) <= 1 << 20 else None
    sent = record.get("requests") if isinstance(record, dict) and record.get("v") == 1 and len(record) == 2 else None
    if not (isinstance(sent, list) and len(sent) == 1 and isinstance(sent[0], dict)):
        raise Unknown("fixture_requests")
    return sent[0] == {"id": row["id"], "route": "/v1/responses", "model": model, "credential": "rejected"}


def classify(access, events, fixture, exit_code, *, model, route="fixture", upstream=None):
    """Return {"disposition", "reason"} from log, fixture record, runner events and exit code. A fixture route's single row is checked against the
    fixture's own upstream and the fixture's request record; a real route's against the PLAN's upstream and with NO fixture (a fixture label can
    never stand for real provenance: the real route's attestation is deployment provenance, not a file the job can write)."""
    try:
        if (route == "real") != (fixture is None) or route not in ("fixture", "real") or (route == "real" and not upstream):
            raise Unknown("route_evidence")
        rows = _rows(access)
        failed = _jsonl(events, "events")
        if len(rows) != 1:
            raise Unknown("access_missing" if not rows else "access_extra_request")
        row = rows[0]
        wanted = {**MODEL_ROW, **({"upstream": upstream} if route == "real" else {})}
        if any(row[key] != value for key, value in wanted.items()):
            raise Unknown("access_tuple")
        types = [event.get("type") for event in failed]
        if not set(types) <= EVENTS or types.count("turn.failed") != 1 or exit_code != 1:
            raise Unknown("runner_not_failed_turn")
        if row["upstream_status"] in TRANSPORT:
            return {"disposition": "transport_failed", "reason": "upstream_" + row["upstream_status"]}
        if row["status"] != "401" or row["upstream_status"] != "401":
            raise Unknown("access_status")
        if route == "fixture" and not _fixture(fixture, row, model):
            raise Unknown("fixture_disagrees")
        return {"disposition": "credentials_rejected", "reason": "relay_401"}
    except (Unknown, ValueError, RecursionError) as error:
        return {"disposition": "unknown", "reason": str(error)}


def _count(value):
    ok = type(value) is int and value > 0  # a zero may be the runner's own missing-field projection
    return {"state": "reported", "value": value} if ok else {"state": "unknown", "reason": "absent_or_zero_not_evidence"}


def usage_record(identity, events, *, elapsed, gateway_refs, raw_refs, observed_model, configured_model, observed=True):
    """Per-attempt immutable record: reported-or-unknown, raw refs kept, no invented cost. `observed=False` (the real route, where nothing observes
    the model: the model-observation amendment) retains the configured string AS configured and records the model as unknown; a known mismatch
    still refuses."""
    if (observed or observed_model is not None) and observed_model != configured_model:
        raise LiveProfileRefused("usage_model_mismatch")
    try:
        done = [event for event in _jsonl(events, "events") if event.get("type") == "turn.completed"]
    except Unknown:
        done = []
    counts = done[0].get("usage") if len(done) == 1 and isinstance(done[0].get("usage"), dict) else {}
    seconds = {"state": "reported", "value": elapsed} if type(elapsed) in (int, float) and elapsed >= 0 else {"state": "unknown", "reason": "not_measured"}
    unknown = {"state": "unknown", "reason": "not reported"}
    model = observed_model if observed else {"state": "unknown", "configured": configured_model}
    return {**identity, "model": model, "raw_refs": list(raw_refs), "gateway_refs": list(gateway_refs),
            "usage": {"input_tokens": _count(counts.get("input_tokens")), "output_tokens": _count(counts.get("output_tokens")),
                      "cached_tokens": _count(counts.get("cached_input_tokens")), "cost": unknown,
                      "elapsed_seconds": seconds, "gateway_credits": unknown}}
