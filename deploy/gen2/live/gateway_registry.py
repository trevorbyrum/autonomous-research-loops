"""D3(a): derive the 28-row offline and live registry seeds from the two pinned public inputs."""
import hashlib
import os
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PINS = {ROOT / "gateway/research_gateway/registry/seed/sources.toml": "25ae8e226a2af847d6cfbdbed515de9cd210b38f280f48829cf83ccdbbb91a46",
        Path(__file__).with_name("q-source.toml"): "b0b0e8811088d7e2df4ed3a06245a4857cf6dba48c130fb6f1993ddcf8bede08"}
ENABLED = {"semanticscholar"}
OFFLINE = {"q_2e1"}


def read_inputs():
    blobs = [path.read_bytes() for path in PINS]
    if [hashlib.sha256(blob).hexdigest() for blob in blobs] != list(PINS.values()):
        raise ValueError("input pin changed")
    return blobs


def derive(public, q, enabled):
    out, row = [], None
    for line in (public + q).splitlines(keepends=True):
        if line.startswith(b'id = "'):
            row = line[6:].rstrip(b'"\n').decode()
        if line.startswith(b"enabled = "):
            line = b"enabled = %s\n" % (b"true" if row in enabled else b"false")
        out.append(line)
    return b"".join(out)


def check(public, q, seed, enabled):
    """Independent of derive: same 28 unique ids, exact enabled set, every other byte equal, loader-valid."""
    from gateway.research_gateway.registry.load import validate
    rows = tomllib.loads(seed.decode())["source"]
    ids = [r["id"] for r in rows]
    if len(ids) != 28 or len(set(ids)) != 28 or enabled - set(ids):
        raise ValueError("expected 28 unique ids including every enabled lane")
    if {r["id"] for r in rows if r["enabled"] is True} != enabled or any(type(r["enabled"]) is not bool for r in rows):
        raise ValueError("enabled set is not exactly the approved lane")
    strip = lambda blob: [x for x in blob.splitlines(keepends=True) if not x.startswith(b"enabled = ")]
    if strip(seed) != strip(public + q) or validate(rows):
        raise ValueError("non-flag bytes changed or loader refused the seed")
    return seed


def same(view, seed, *, flags_only=False):
    """Require exact equality to trusted seed rows, without exposing readback values."""
    expected = {row["id"]: row for row in seed}
    actual = {}
    for row in view:
        source = row.get("id")
        if type(source) is not str or source not in expected:
            raise ValueError("registry differs at <unexpected id>")
        if source in actual:
            raise ValueError(f"registry differs at {source}")
        actual[source] = row
    for source, row in expected.items():
        seen = actual.get(source, {})
        if seen.get("enabled") is not row["enabled"]:
            raise ValueError(f"registry differs at {source}")
        if not flags_only:
            rate, wanted = seen.get("rate"), row["rate"]
            if type(rate) is not dict or rate != wanted or any(type(rate[k]) is not type(v) for k, v in wanted.items()):
                raise ValueError(f"registry differs at {source}")


def publish(path):
    public, q = read_inputs()
    seed = check(public, q, derive(public, q, ENABLED), ENABLED)
    with tempfile.TemporaryDirectory(dir=path.parent) as staging:
        staged = Path(staging) / "seed"
        staged.write_bytes(seed)
        os.link(staged, path)  # atomic exclusive publication of the complete seed


if __name__ == "__main__":
    publish(Path(sys.argv[1]))
