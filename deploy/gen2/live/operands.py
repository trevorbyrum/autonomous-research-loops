"""C's operand packer for B's qualification-record/1 contract.

The operator/verifier supplies the record and attests native witnesses before
publication. This pure packer neither sets qualification state nor grants it.
"""
import os
from pathlib import Path

from gen2.core import canonical



def root(name):
    """Operator-set host root (GEN2_CONFIG_ROOT or GEN2_DATA_ROOT); no default, refuse unset or relative."""
    value = os.environ.get(name, "")
    if not os.path.isabs(value):
        raise ValueError(name + " must be set to an absolute path")
    return Path(value)


def provider_files():
    return {"provider_auth": str(root("GEN2_CONFIG_ROOT") / "provider-auth.conf"),
            "provider_ca": str(root("GEN2_CONFIG_ROOT") / "provider-ca.pem")}


def _check_experiment(view, record_pin):
    record, authorization = view["record"], view.get("authorization")
    if not isinstance(authorization, bytes) or canonical.bytes_digest(authorization) != view.get("authorization_pin"):
        raise ValueError("stale authorization operand")
    scope = record.get("experiment")
    if (not isinstance(scope, dict) or scope.keys() != {"invocation_id", "topic_id", "config_bundle_hash", "not_before"}
            or not all(isinstance(value, str) and value for value in scope.values())):
        raise ValueError("invalid experiment scope")
    approval = canonical.parse_json_strict(authorization)
    pair = {"record_pin": record_pin, "manifest_pin": record["manifest_pin"], "experiment": scope}
    if (not isinstance(approval, dict) or approval.keys() != pair.keys() | {"authorization_version", "ruling_ref", "approved_at"}
            or approval["authorization_version"] != "rejection-experiment-authorization/1"
            or not all(isinstance(approval[key], str) and approval[key] for key in ("ruling_ref", "approved_at"))
            or any(approval[key] != value for key, value in pair.items())):
        raise ValueError("authorization operand does not bind experiment pair")
    manifest = canonical.parse_json_strict(view["manifest"])
    if (not isinstance(manifest, dict) or manifest.get("qualification_state") != record["state"]
            or manifest.get("route") != record["route"] or manifest.get("credential_ref") != record["credential_ref"]):
        raise ValueError("manifest operand does not match experiment record")
    pending = [w for w in record["witnesses"] if isinstance(w, dict) and w.get("name") == "DEBT-004"]
    if pending != [{"name": "DEBT-004", "passed": False}] or pending[0]["passed"] is not False:
        raise ValueError("invalid pending DEBT-004 witness")


def pack(view):
    """Hash only carried bytes; refuse stale manifest, receipt or authorization pins."""
    record = view["record"]
    if record["route"] == "real" and any(record["plan"].get(key) != path for key, path in provider_files().items()):
        raise ValueError("provider file operand")
    if canonical.bytes_digest(view["manifest"]) != record["manifest_pin"]:
        raise ValueError("stale manifest operand")
    data = canonical.canonical_bytes(record)
    record_pin = canonical.bytes_digest(data)
    experiment = record.get("state") == "rejection_experiment"
    if experiment:
        _check_experiment(view, record_pin)
    elif "authorization" in view or "authorization_pin" in view:
        raise ValueError("authorization operand requires an experiment record")
    for witness in record["witnesses"]:
        if experiment and witness["name"] == "DEBT-004":
            continue
        pin = witness["receipt"]
        if canonical.bytes_digest(view["receipts"][pin]) != pin:
            raise ValueError("stale witness operand")
    return data, record_pin
