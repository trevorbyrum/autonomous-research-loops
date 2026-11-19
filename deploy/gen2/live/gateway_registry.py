"""D3(a): derive the 28-row live registry seed (only semanticscholar enabled) from the two pinned public inputs."""
import hashlib
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PINS = {ROOT / "gateway/research_gateway/registry/seed/sources.toml": "25ae8e226a2af847d6cfbdbed515de9cd210b38f280f48829cf83ccdbbb91a46",
        Path(__file__).with_name("q-source.toml"): "b0b0e8811088d7e2df4ed3a06245a4857cf6dba48c130fb6f1993ddcf8bede08"}
ENABLED = {"semanticscholar"}


def read_inputs():
    blobs = [path.read_bytes() for path in PINS]
    if [hashlib.sha256(blob).hexdigest() for blob in blobs] != list(PINS.values()):
        raise ValueError("input pin changed")
    return blobs


def derive(public, q):
    out, row = [], None
    for line in (public + q).splitlines(keepends=True):
        if line.startswith(b'id = "'):
            row = line[6:].rstrip(b'"\n').decode()
        if line.startswith(b"enabled = "):
            line = b"enabled = %s\n" % (b"true" if row in ENABLED else b"false")
        out.append(line)
    return b"".join(out)


def check(public, q, seed):
    """Independent of derive: same 28 unique ids, flags exactly ENABLED, every other byte equal, loader-valid."""
    from gateway.research_gateway.registry.load import validate
    rows = tomllib.loads(seed.decode())["source"]
    ids = [r["id"] for r in rows]
    if len(ids) != 28 or len(set(ids)) != 28 or ENABLED - set(ids):
        raise ValueError("expected 28 unique ids including every enabled lane")
    if {r["id"] for r in rows if r["enabled"] is True} != ENABLED or any(type(r["enabled"]) is not bool for r in rows):
        raise ValueError("enabled set is not exactly the approved lane")
    strip = lambda blob: [x for x in blob.splitlines(keepends=True) if not x.startswith(b"enabled = ")]
    if strip(seed) != strip(public + q) or validate(rows):
        raise ValueError("non-flag bytes changed or loader refused the seed")
    return seed


if __name__ == "__main__":
    public, q = read_inputs()
    Path(sys.argv[1]).open("xb").write(check(public, q, derive(public, q)))  # exclusive create: never replace another attempt's seed
