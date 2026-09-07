"""Licence allow-list and redistribution policy (PLAN.md §6, docs/LICENSING.md).

`allow_listed(license)` says whether a per-item licence string permits
commercial reuse with attribution at most; `redistributable(source, record)`
says whether the gateway may keep and export what it retrieved.
"""
from __future__ import annotations

import re

# substrings (after normalisation) that identify an allow-listed licence
_ALLOW = ("cc0", "cc-by", "public domain", "publicdomain", "odc-by", "odbl", "pddl", "mit", "apache", "bsd",
          "us government", "u.s. government", "federal public domain", "17 u.s.c. 105")
# markers that withdraw the allowance even when an allow marker is present
_RESTRICT = ("-nc", " nc", "non-commercial", "noncommercial", "-nd", " nd ", "no derivatives", "gpl", "proprietary", "restricted")


def normalize(license: str | None) -> str:
    if not license:
        return ""
    s = license.strip().lower()
    s = s.replace("creative commons attribution", "cc-by").replace("creative commons zero", "cc0").replace("cc by", "cc-by")
    s = re.sub(r"\s+", " ", s)
    return s


def allow_listed(license: str | None) -> bool:
    """True only for licences that clearly permit commercial reuse (attribution at most)."""
    s = normalize(license)
    if not s:
        return False
    padded = f" {s} "
    if any(m in padded for m in _RESTRICT):
        return False
    return any(a in s for a in _ALLOW)


def redistributable(source: dict, record: dict | None = None) -> bool:
    """May the gateway persist/export this record? Full text is never kept (I-7);
    `allow` sources yes; `per-item` sources only for allow-listed records; else no."""
    if record and record.get("kind") in ("full_text",):
        return False
    verdict = source.get("use_commercial")
    if verdict == "allow":
        return True
    if verdict == "per-item":
        return allow_listed((record or {}).get("license"))
    return False
