"""Staged dedup (PLAN.md §6): identity normalise → exact identity → fuzzy
(title ≥ 0.92 AND same year AND same first author, all three present) → clusters
with full provenance. Clustering is greedy in lane order: a record joins the
first cluster it matches, so the base lane's record is the canonical one."""
from __future__ import annotations

from difflib import SequenceMatcher

from . import identity as ident

THRESHOLD = 0.92


def _surname(author: str | None) -> str:
    if not author:
        return ""
    a = author.strip()
    if "," in a:
        return ident.normalize_title(a.split(",", 1)[0])
    parts = ident.normalize_title(a).split()
    return parts[-1] if parts else ""


def _fuzzy_same(a: dict, b: dict, threshold: float) -> bool:
    """Only records that carry a title, a year and a first author can merge fuzzily;
    anything less would merge different works that merely share a title."""
    ta, tb = ident.normalize_title(a.get("title")), ident.normalize_title(b.get("title"))
    if not ta or not tb or not a.get("year") or not b.get("year") or a["year"] != b["year"]:
        return False
    sa, sb = _surname((a.get("authors") or [None])[0]), _surname((b.get("authors") or [None])[0])
    if not sa or not sb or sa != sb:
        return False
    return SequenceMatcher(None, ta, tb).ratio() >= threshold


def _provenance_of(rec: dict) -> list[dict]:
    """A record already carrying provenance (a prior merge, a cache hit) contributes ALL its
    members, never a single collapsed entry that would forget one of them (D-25)."""
    if rec.get("provenance"):
        return [dict(p) for p in rec["provenance"]]
    return [{"source_id": rec["source_id"], "identity": rec["identity"], "raw": rec.get("raw"),
             "license": rec.get("license")}]


def _merge(into: dict, other: dict) -> None:
    members = _provenance_of(other)
    into["sources"].extend(m["source_id"] for m in members if m["source_id"] not in into["sources"])
    into["provenance"].extend(members)
    for k, v in (other.get("identifiers") or {}).items():
        into["identifiers"].setdefault(k, v)
    for link in other.get("links") or []:
        if link not in into["links"]:
            into["links"].append(link)
    for k in ("title", "year", "venue", "license", "attribution"):
        if not into.get(k) and other.get(k):
            into[k] = other[k]
    if not into.get("authors") and other.get("authors"):
        into["authors"] = list(other["authors"])


def cluster(records: list[dict], threshold: float = THRESHOLD) -> list[dict]:
    """Merge duplicates in lane order: the first record of a cluster is canonical,
    later members contribute identifiers/links/missing fields and provenance."""
    out: list[dict] = []
    by_identity: dict[str, dict] = {}
    for rec in records:
        key = ident.canonical(rec["identity"])
        hit = by_identity.get(key)
        if hit is None:
            for cand in out:
                if cand["kind"] == rec.get("kind") and _fuzzy_same(cand, rec, threshold):
                    hit = cand
                    break
        if hit is None:
            merged = dict(rec)
            merged["identity"] = key
            merged["identifiers"] = dict(rec.get("identifiers") or {})
            merged["links"] = list(rec.get("links") or [])
            merged["provenance"] = _provenance_of(rec)
            merged["sources"] = list(dict.fromkeys(m["source_id"] for m in merged["provenance"]))
            merged.pop("raw", None)
            out.append(merged)
            by_identity[key] = merged
        else:
            _merge(hit, rec)
            by_identity.setdefault(key, hit)
    return out
