"""The hosts the gateway fronts — derived from the adapter sources, never hand-kept.

`python3 -m research_gateway.clients.fronted_hosts` prints a sorted JSON list of every
hostname the adapters talk to. The research-loops station hook denies direct Bash/
WebFetch network access to these hosts (plan phase 8c bypass lockdown): an agent with
the research tools mounted has no reason to curl api.crossref.org itself, and a live
iteration doing exactly that is what motivated this. Derivation keeps the list honest —
a new adapter extends the deny list on the next regeneration, no second registry.

This is a raised bar, not a security boundary (an agent that can edit files could
disable the hook); the real below-tool-layer boundary is a ROADMAP item.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

_URL = re.compile(r"https?://[^\s\"')>]+")
# hosts adapters mention that the gateway does NOT front (loopback, examples, doc links)
_EXCLUDED = ("127.0.0.1", "localhost", "example.org", "example.com", "gateway.local")


def fronted_hosts() -> list[str]:
    hosts: set[str] = set()
    for path in sorted((Path(__file__).resolve().parent.parent / "adapters").glob("*.py")):
        if path.name in ("base.py", "__init__.py"):
            continue
        for match in _URL.findall(path.read_text(encoding="utf-8")):
            host = (urlsplit(match).hostname or "").lower().strip(".")
            if host and not any(host == e or host.endswith("." + e) for e in _EXCLUDED):
                hosts.add(host)
    return sorted(hosts)


def main() -> int:
    print(json.dumps(fronted_hosts(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
