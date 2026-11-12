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


def pack(view):
    """Hash only carried bytes; refuse stale manifest/receipt pins before serialization."""
    record = view["record"]
    if record["route"] == "real" and any(record["plan"].get(key) != path for key, path in provider_files().items()):
        raise ValueError("provider file operand")
    if canonical.bytes_digest(view["manifest"]) != record["manifest_pin"]:
        raise ValueError("stale manifest operand")
    for witness in record["witnesses"]:
        pin = witness["receipt"]
        if canonical.bytes_digest(view["receipts"][pin]) != pin:
            raise ValueError("stale witness operand")
    data = canonical.canonical_bytes(record)
    return data, canonical.bytes_digest(data)
