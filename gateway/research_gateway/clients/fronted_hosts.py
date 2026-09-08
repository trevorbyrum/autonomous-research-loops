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
_HOST_SHAPE = re.compile(r"^[a-z0-9.-]+$")   # a REAL hostname: an f-string template segment ({domain}) is not one
# hosts adapters mention that the gateway does NOT front (loopback, examples, doc links)
_EXCLUDED = ("127.0.0.1", "localhost", "example.org", "example.com", "gateway.local")
# fronted endpoints that never appear as URL literals in the adapter sources: Socrata
# portals are vouched dynamically through the discovery catalog (R-6), so the discovery
# endpoints are pinned here and individual portal hosts remain a documented residual —
# the hook cannot enumerate hosts the gateway itself only learns at runtime.
_EXTRA = ("api.us.socrata.com", "api.eu.socrata.com")


def fronted_hosts() -> list[str]:
    hosts: set[str] = set(_EXTRA)
    for path in sorted((Path(__file__).resolve().parent.parent / "adapters").glob("*.py")):
        if path.name in ("base.py", "__init__.py"):
            continue
        for match in _URL.findall(path.read_text(encoding="utf-8")):
            host = (urlsplit(match).hostname or "").lower().strip(".")
            if (host and _HOST_SHAPE.fullmatch(host) and "." in host
                    and not any(host == e or host.endswith("." + e) for e in _EXCLUDED)):
                hosts.add(host)
    return sorted(hosts)


def main() -> int:
    print(json.dumps(fronted_hosts(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
