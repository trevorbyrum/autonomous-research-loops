"""Licence recognition and redistribution policy (PLAN.md §6, docs/LICENSING.md, D-22/D-23).

Recognition is exact, not substring: a licence string is reduced to a canonical
identifier by matching known SPDX ids, names and canonical URLs. Anything
unrecognised — and any recognised licence accompanied by extra free text that
could carry additional conditions — fails closed. `allow_listed()` says whether
the identified licence permits commercial reuse with attribution at most
(share-alike, non-commercial and no-derivatives variants do not).
"""
from __future__ import annotations

import re
import urllib.parse

_CC_TAIL = re.compile(r"([1-4]\.[05]|2\.5)?/?(deed(\.[a-z_]+)?|legalcode(\.[a-z_]+)?)?/?")

# canonical id -> allow-listed? (commercial reuse, attribution at most)
KNOWN: dict[str, bool] = {
    "cc0": True, "cc-by": True, "public-domain": True, "us-government-work": True,
    "odc-by": True, "pddl": True, "mit": True, "apache": True, "bsd": True, "isc": True,
    "zlib": True, "unlicense": True,
    # recognised but NOT allow-listed: share-alike, non-commercial, no-derivatives, copyleft
    "cc-by-sa": False, "cc-by-nc": False, "cc-by-nd": False, "cc-by-nc-sa": False, "cc-by-nc-nd": False,
    "odbl": False, "gpl": False, "lgpl": False, "agpl": False,
}

# exact-match aliases (lower-cased, punctuation/version tolerant via _reduce) -> canonical id
_ALIASES: dict[str, str] = {
    "cc0": "cc0", "cc zero": "cc0", "creative commons zero": "cc0", "cc0 1 0": "cc0",
    "cc0 1 0 universal": "cc0", "creative commons zero v1 0 universal": "cc0",
    "public domain": "public-domain", "public domain dedication": "public-domain",
    "publicdomain": "public-domain", "pd": "public-domain",
    "us government work": "us-government-work", "u s government work": "us-government-work",
    "us federal public domain": "us-government-work", "u s federal public domain": "us-government-work",
    "united states government work": "us-government-work", "17 u s c 105": "us-government-work",
    "u s federal public domain 17 u s c 105": "us-government-work",
    "us government work public domain": "us-government-work",
    "cc by": "cc-by", "cc attribution": "cc-by", "creative commons attribution": "cc-by",
    "attribution": "cc-by",
    "cc by sa": "cc-by-sa", "creative commons attribution sharealike": "cc-by-sa",
    "creative commons attribution share alike": "cc-by-sa", "attribution sharealike": "cc-by-sa",
    "cc by nc": "cc-by-nc", "creative commons attribution noncommercial": "cc-by-nc",
    "creative commons attribution non commercial": "cc-by-nc", "attribution noncommercial": "cc-by-nc",
    "cc by nd": "cc-by-nd", "creative commons attribution noderivatives": "cc-by-nd",
    "creative commons attribution no derivatives": "cc-by-nd",
    "cc by nc sa": "cc-by-nc-sa", "creative commons attribution noncommercial sharealike": "cc-by-nc-sa",
    "cc by nc nd": "cc-by-nc-nd", "creative commons attribution noncommercial noderivatives": "cc-by-nc-nd",
    "odc by": "odc-by", "open data commons attribution": "odc-by", "open data commons attribution license": "odc-by",
    "odbl": "odbl", "open database license": "odbl", "open data commons open database license": "odbl",
    "pddl": "pddl", "open data commons public domain dedication and license": "pddl",
    "mit": "mit", "mit license": "mit", "expat": "mit",
    "apache": "apache", "apache license": "apache", "apache 2": "apache",
    "bsd": "bsd", "bsd license": "bsd", "bsd 2 clause": "bsd", "bsd 3 clause": "bsd", "bsd clause": "bsd",
    "isc": "isc", "isc license": "isc",
    "zlib": "zlib", "zlib license": "zlib",
    "unlicense": "unlicense", "the unlicense": "unlicense",
    "gpl": "gpl", "gnu general public license": "gpl", "lgpl": "lgpl", "agpl": "agpl",
}

# canonical URL routes: (exact host, path prefix) -> canonical id. The HOST must match exactly
# (or with a www. prefix) — a canonical path on someone else's domain identifies nothing (D-24).
_URL_ROUTES: list[tuple[str, str, str]] = [
    ("creativecommons.org", "/publicdomain/zero/", "cc0"),
    ("creativecommons.org", "/publicdomain/mark/", "public-domain"),
    ("creativecommons.org", "/licenses/by/", "cc-by"),
    ("creativecommons.org", "/licenses/by-sa/", "cc-by-sa"),
    ("creativecommons.org", "/licenses/by-nc/", "cc-by-nc"),
    ("creativecommons.org", "/licenses/by-nd/", "cc-by-nd"),
    ("creativecommons.org", "/licenses/by-nc-sa/", "cc-by-nc-sa"),
    ("creativecommons.org", "/licenses/by-nc-nd/", "cc-by-nc-nd"),
    ("opendatacommons.org", "/licenses/by", "odc-by"),
    ("opendatacommons.org", "/licenses/odbl", "odbl"),
    ("opendatacommons.org", "/licenses/pddl", "pddl"),
    ("opensource.org", "/licenses/mit", "mit"),
    ("opensource.org", "/license/mit", "mit"),
    ("opensource.org", "/licenses/isc", "isc"),
    ("opensource.org", "/license/isc", "isc"),
    ("apache.org", "/licenses/", "apache"),
    ("www.apache.org", "/licenses/", "apache"),
    ("unlicense.org", "", "unlicense"),
    ("gnu.org", "/licenses/", "gpl"),
]

# only versions these licences actually have are stripped: "CC-BY-99.0" identifies nothing (D-24)
_VERSION_RE = re.compile(r"\b(v\.?\s?)?([1-4](\s[05])?|2\s5)\b|\binternational\b|\buniversal\b|\bgeneric\b|\bonly\b|\bor later\b|\blicense\b$")
_SPDX_SHAPE = re.compile(r"^[a-z0-9][a-z0-9 ]*$")


def _reduce(text: str) -> str:
    """Lower-case, drop URLs' scheme noise, punctuation → spaces, strip version tails."""
    s = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    # strip trailing version/qualifier words repeatedly ("apache license 2 0" -> "apache")
    while True:
        t = _VERSION_RE.sub("", s).strip()
        t = re.sub(r"\s+", " ", t)
        if t == s:
            return s
        s = t


def identify(license: str | None) -> str | None:
    """The canonical licence id for a string, or None when it cannot be identified exactly.
    A lone URL matches by canonical URL; anything else must reduce to a known alias whole —
    extra words ('MIT plus restrictions', 'see disclaimer') mean no identification."""
    if not license:
        return None
    s = license.strip()
    if not s:
        return None
    if re.fullmatch(r"https?://\S+", s, re.IGNORECASE):
        try:
            parts = urllib.parse.urlsplit(s)
            host = (parts.hostname or "").lower()   # urlsplit handles userinfo: creativecommons.org:x@evil is evil
        except ValueError:
            return None
        path = (parts.path or "/").lower()
        if parts.query or parts.fragment or "/../" in path or path.endswith("/.."):
            return None   # annotated, parameterised or traversal-shaped URLs identify nothing (D-25)
        for want_host, prefix, cid in _URL_ROUTES:
            if host in (want_host, f"www.{want_host}") and path.startswith(prefix or "/"):
                tail = path[len(prefix):] if prefix else path.lstrip("/")
                if want_host == "creativecommons.org" and not _CC_TAIL.fullmatch(tail):
                    return None   # only versions the deed actually has, then deed/legalcode pages
                return cid
        return None
    if any(ch in s for ch in "<>{}") or "http" in s.lower():
        return None  # markup or embedded URLs alongside text: not a bare licence name
    plain = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()
    if plain in _ALIASES:                      # exact alias before version-stripping ("17 u s c 105", "bsd 3 clause")
        return _ALIASES[plain]
    reduced = _reduce(s)
    if not reduced or not _SPDX_SHAPE.match(reduced):
        return None
    return _ALIASES.get(reduced)


def allow_listed(license: str | None) -> bool:
    """True only for exactly-identified licences that permit commercial reuse with attribution at most."""
    cid = identify(license)
    return bool(cid and KNOWN.get(cid, False))


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


def commercially_usable(source: dict, record: dict | None, payload: dict) -> bool:
    """R-8 applied to one record: with commercial=true, allow sources pass, per-item sources
    pass only with accept_per_item and an allow-listed licence, everything else fails."""
    if not payload.get("commercial"):
        return True
    verdict = source.get("use_commercial")
    if verdict == "allow":
        return True
    if verdict == "per-item":
        return bool(payload.get("accept_per_item")) and allow_listed((record or {}).get("license"))
    return False
