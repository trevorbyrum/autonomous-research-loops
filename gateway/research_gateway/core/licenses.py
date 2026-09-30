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

# only versions the deeds actually have: 1.0/2.0/2.5/3.0/4.0 for licences, 1.0 alone for CC0/mark (D-26)
_CC_LICENSE_TAIL = re.compile(r"(1\.0|2\.0|2\.5|3\.0|4\.0)?/?(deed(\.[a-z_]+)?|legalcode(\.[a-z_]+)?)?/?")
_CC_ZERO_TAIL = re.compile(r"(1\.0)?/?(deed(\.[a-z_]+)?|legalcode(\.[a-z_]+)?)?/?")

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

# canonical URL routes: (exact host, path prefix, id, version segments the route ACTUALLY has).
# The HOST must match exactly (or with a www. prefix) — a canonical path on someone else's domain
# identifies nothing (D-24). Versions are an explicit whitelist per route: MIT has none, the Open
# Data Commons deeds have 1.0, and an invented '/9.9/' identifies nothing (D-27 pass-6 fix).
_URL_ROUTES: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("creativecommons.org", "/publicdomain/zero/", "cc0", ()),          # CC tails handled by their own regexes
    ("creativecommons.org", "/publicdomain/mark/", "public-domain", ()),
    ("creativecommons.org", "/licenses/by/", "cc-by", ()),
    ("creativecommons.org", "/licenses/by-sa/", "cc-by-sa", ()),
    ("creativecommons.org", "/licenses/by-nc/", "cc-by-nc", ()),
    ("creativecommons.org", "/licenses/by-nd/", "cc-by-nd", ()),
    ("creativecommons.org", "/licenses/by-nc-sa/", "cc-by-nc-sa", ()),
    ("creativecommons.org", "/licenses/by-nc-nd/", "cc-by-nc-nd", ()),
    ("opendatacommons.org", "/licenses/by", "odc-by", ("1.0",)),
    ("opendatacommons.org", "/licenses/odbl", "odbl", ("1.0",)),
    ("opendatacommons.org", "/licenses/pddl", "pddl", ("1.0",)),
    ("opensource.org", "/licenses/mit", "mit", ()),
    ("opensource.org", "/license/mit", "mit", ()),
    ("opensource.org", "/licenses/isc", "isc", ()),
    ("opensource.org", "/license/isc", "isc", ()),
    ("apache.org", "/licenses/", "apache", ()),
    ("www.apache.org", "/licenses/", "apache", ()),
    ("unlicense.org", "", "unlicense", ()),
    ("gnu.org", "/licenses/", "gpl", ()),
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
        path = urllib.parse.unquote(parts.path or "/").lower()   # %2e-encoded traversal decodes before checks (D-26)
        if parts.query or parts.fragment or "/../" in path or path.endswith("/..") or "\\" in path:
            return None   # annotated, parameterised or traversal-shaped URLs identify nothing (D-25)
        for want_host, prefix, cid, versions in _URL_ROUTES:
            if host not in (want_host, f"www.{want_host}") or not path.startswith(prefix or "/"):
                continue
            tail = path[len(prefix):] if prefix else path.lstrip("/")
            if want_host == "creativecommons.org":
                tail_re = _CC_ZERO_TAIL if "/publicdomain/" in prefix else _CC_LICENSE_TAIL
                return cid if tail_re.fullmatch(tail) else None
            if prefix.endswith("/") or not prefix:
                # directory routes (apache /licenses/, gnu /licenses/, the unlicense root):
                # exactly one filename segment (LICENSE-2.0, gpl-3.0.html), never a sub-path
                return cid if re.fullmatch(r"[-a-z0-9._+]*/?", tail) else None
            # exact-id routes: the id must END here ('mit-noncommercial' is a different id, D-27)
            # and the only thing after it is a version segment the route ACTUALLY has
            if tail in ("", "/"):
                return cid
            # exactly '/<version>' or '/<version>/': rstrip would collapse '/1.0//'
            # onto '/1.0' and re-open paths pass 6 rejected (pass-7 finding)
            if any(tail in (f"/{v}", f"/{v}/") for v in versions):
                return cid
            return None
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


def storable(source: dict, record: dict | None = None) -> bool:
    """May the GATEWAY keep this record (persist it, serve it from its cache beyond an hour)?
    Full text is never kept (I-7); `allow` sources yes; `per-item` sources only for
    allow-listed records; else no. This is the storage fact only — it says nothing about
    whether the record's content may be redistributed downstream (task 2b: the two were
    one flag, `redistributable`, and are now separate facts; see permissions())."""
    if record and record.get("kind") in ("full_text",):
        return False
    verdict = source.get("use_commercial")
    if verdict == "allow":
        return True
    if verdict == "per-item":
        return allow_listed((record or {}).get("license"))
    return False


REDISTRIBUTION = ("permitted", "conditional", "prohibited", "unknown")
CONTENT_KINDS = ("full_text", "file")


def content_redistribution(license: str | None, adapter_flag=None) -> str:
    """May the record's CONTENT travel downstream (an export bundle, a quote)? Decided by
    the content licence the source reported for the work — never by the source's metadata
    licence or its commercial verdict (a CC0 metadata record can describe a copyrighted
    paper, LICENSING.md). `permitted`: an exactly identified allow-listed licence
    (attribution at most); `conditional`: identified, with conditions (share-alike,
    non-commercial, no-derivatives, copyleft); `unknown`: absent or not identifiable —
    never read as permitted; `prohibited`: the adapter says the source's terms forbid it."""
    if adapter_flag is False:
        return "prohibited"
    cid = identify(license)
    if cid is None:
        return "unknown"
    return "permitted" if KNOWN.get(cid) else "conditional"


def permissions(source: dict, member: dict, *, kind: str | None, has_content: bool = False) -> dict:
    """The four facts about one contributing source's part of a record (task 2b; design
    review §9: availability, content licence and permission to store/transmit are separate
    facts, never collapsed into one flag):
      availability   `content` when the gateway delivered the item's content (full text,
                     rows, file bytes), `metadata` when it delivered a description of it;
      access         `commercial_use` when the source's verdict and this member's own
                     licence let it be used commercially (with per-item acceptance),
                     `personal_use` otherwise — the personal-research baseline;
      storage        `persist` when the gateway may keep it, `transient` when it is only
                     delivered to the caller (and held in memory for at most an hour);
      redistribution content_redistribution() of the member's content licence."""
    record = {"kind": kind, "license": member.get("license")}
    commercial = commercially_usable(source, record, {"commercial": True, "accept_per_item": True}) \
        and not member.get("third_party_restricted")
    return {"availability": "content" if has_content or kind in CONTENT_KINDS else "metadata",
            "access": "commercial_use" if commercial else "personal_use",
            "storage": "persist" if storable(source, record) else "transient",
            "redistribution": content_redistribution(member.get("license"), member.get("redistributable"))}


def combined(per_member: list[dict]) -> dict:
    """A merged record's facts: each the most restrictive of its members' (one member that
    may not be kept, used commercially or redistributed caps the record)."""
    if not per_member:
        return {}
    order = {"redistribution": ("prohibited", "unknown", "conditional", "permitted"),
             "storage": ("transient", "persist"), "access": ("personal_use", "commercial_use"),
             "availability": ("metadata", "content")}
    return {fact: min((p[fact] for p in per_member), key=values.index) for fact, values in order.items()}


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
