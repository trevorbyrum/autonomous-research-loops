"""C's operand packer for B's qualification-record/1 contract.

The operator/verifier supplies the record and attests native witnesses before
publication. This pure packer neither sets qualification state nor grants it.
"""
from gen2.core import canonical


def pack(view):
    """Hash only carried bytes; refuse stale manifest/receipt pins before serialization."""
    record = view["record"]
    if canonical.bytes_digest(view["manifest"]) != record["manifest_pin"]:
        raise ValueError("stale manifest operand")
    for witness in record["witnesses"]:
        pin = witness["receipt"]
        if canonical.bytes_digest(view["receipts"][pin]) != pin:
            raise ValueError("stale witness operand")
    data = canonical.canonical_bytes(record)
    return data, canonical.bytes_digest(data)
