"""C's operand packer for B's qualification-record/1 contract.

The operator/verifier supplies the record and attests native witnesses before
publication. This pure packer neither sets qualification state nor grants it.
"""
from gen2.core import canonical

PROVIDER_FILES = {"provider_auth": "/home/trevor/.config/gen2-2e1/provider-auth.conf",
                  "provider_ca": "/home/trevor/.config/gen2-2e1/provider-ca.pem"}


def pack(view):
    """Hash only carried bytes; refuse stale manifest/receipt pins before serialization."""
    record = view["record"]
    if record["route"] == "real" and any(record["plan"].get(key) != path for key, path in PROVIDER_FILES.items()):
        raise ValueError("provider file operand")
    if canonical.bytes_digest(view["manifest"]) != record["manifest_pin"]:
        raise ValueError("stale manifest operand")
    for witness in record["witnesses"]:
        pin = witness["receipt"]
        if canonical.bytes_digest(view["receipts"][pin]) != pin:
            raise ValueError("stale witness operand")
    data = canonical.canonical_bytes(record)
    return data, canonical.bytes_digest(data)
