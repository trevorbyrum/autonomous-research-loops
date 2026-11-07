"""I02/A06/A08: fixed fresh-store, generation and offline-registry operations."""
import hashlib
import os
import re
import sys
from pathlib import Path

if __name__ == "__main__":
    operation = sys.argv[1]
    if operation == "store":
        from gen2.store.api import open_store
        if any(Path("/var/lib/gen2/control").iterdir()):
            raise ValueError("fresh control root required")
        open_store("/var/lib/gen2/control/store.sqlite3", create=True).close()
    elif operation == "generation":
        generation = sys.argv[2]
        if not re.fullmatch("[0-9a-f]{32}", generation) or os.geteuid() != 0:
            raise ValueError("original generation/root initializer required")
        for parent in ("/out-slot", "/relay-slot", "/input-slot", "/fixture-slot", "/source-slot"):
            target = Path(parent, generation + "-" + parent[1:-5])
            target.mkdir(mode=0o700)  # never adopt a partial generation
            os.chown(target, 10001, 10001)
        access = Path("/relay-slot", generation + "-relay", "access.jsonl")
        access.touch(mode=0o600, exist_ok=False)
        os.chown(access, 10001, 10001)
    elif operation == "build-registry":
        from research_gateway.registry.load import SEED
        disabled = b"".join(b"enabled = false\n" if line == b"enabled = true\n" else line for line in SEED.read_bytes().splitlines(keepends=True))
        if hashlib.sha256(disabled).hexdigest() != "b95efce7dea15e644f62f8b7a23770380f40a1274ca7dc9fb02e5164da84b81c":
            raise ValueError("disabled 27-source seed changed")
        SEED.write_bytes(disabled + Path("/opt/live/q-source.toml").read_bytes())
    else:
        raise ValueError("unknown fixed initializer operation")
