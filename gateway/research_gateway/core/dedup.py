"""Deduplication by IDENTITY, and nothing else (PLAN.md §6; gen-2 INVARIANTS E-3, task 2b-repair-13a).

Two records are one candidate here only when they carry the same identity once it is normalised (`identity.canonical`: the DOI without its resolver prefix and lower-cased,
the same ISSN, the same arXiv id ...). That is an explicit equivalence a provider stated, and it is the whole of what this module decides: it merges their provenance, in lane
order, so the base lane's record is canonical and every contributing source keeps its own raw payload and licence.

Whether two DIFFERENT identities are the same work — a preprint and its published version, a dataset and its paper, one study reported twice — is not decided here. That is a work/study
judgement, which the evidence layer makes later, by a governed assessment (the methodology: "deduplication removes identity duplicates only; it does not decide semantic novelty or
independent experimental origin"). The gateway used to settle it silently, by a fuzzy title/year/first-author match that merged two works with distinct DOIs into one record whose canonical
identity was the first DOI. It no longer does: a similar title never merges anything, never sets a canonical identity, and never lets one record's identifiers stand for another's.

What a retrieval helper CAN honestly say is that two candidates look alike. `suggestions` records that as a LINKAGE SUGGESTION — the two identities, why they look alike, which sources
retrieved each, and that nothing has been decided (`disposition: unassessed`) — for the later assessment to take up or ignore, and to dispose of reversibly. Records, retrieved identities and the lane's
count are never touched by it.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from . import identity as ident

THRESHOLD = 0.92   # the similarity of two titles (difflib ratio, over their normalised text) at which they are suggested as possibly one work


def _surname(author: str | None) -> str:
    if not author:
        return ""
    a = author.strip()
    if "," in a:
        return ident.normalize_title(a.split(",", 1)[0])
    parts = ident.normalize_title(a).split()
    return parts[-1] if parts else ""


def _provenance_of(rec: dict) -> list[dict]:
    """A record already carrying provenance (a prior merge, a cache hit) contributes ALL its
    members, never a single collapsed entry that would forget one of them (D-25). A record with
    only a `sources` list expands to one member per source, mirroring the router's member view,
    so a denied source named there is never lost in a re-merge (D-26)."""
    if rec.get("provenance"):
        return [dict(p) for p in rec["provenance"]]
    own = rec.get("source_id")
    return [{"source_id": s, "identity": rec["identity"],
             "raw": rec.get("raw") if s == own else None,
             "license": rec.get("license") if s == own else None,
             "retrieved_at": rec.get("retrieved_at") if s == own else None,
             "attribution": rec.get("attribution") if s == own else None,
             "link": (rec.get("links") or [None])[0] if s == own else None,
             # the source's own statements about THIS record (task 2b): its terms forbid
             # redistribution, or it carries third-party restrictions — kept per member
             **({k: rec[k] for k in ("redistributable", "third_party_restricted") if k in rec} if s == own else {})}
            for s in rec.get("sources") or [own]]


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


def cluster(records: list[dict]) -> list[dict]:
    """Merge records of the same identity, in lane order: the first record of an identity is canonical, later ones of that identity contribute identifiers, links, missing
    fields and provenance. Records of different identities are never merged, whatever else they share."""
    out: list[dict] = []
    by_identity: dict[str, dict] = {}
    for rec in records:
        key = ident.canonical(rec["identity"])
        hit = by_identity.get(key)
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
    return out


def _alike(a: dict, b: dict, threshold: float) -> float | None:
    """How alike two candidates are, or None when they are not alike enough to suggest. Only candidates that carry a title, a year and a first author can be: anything less would pair
    different works that merely share a title."""
    if a.get("kind") != b.get("kind") or not a.get("year") or a["year"] != b.get("year"):
        return None
    ta, tb = ident.normalize_title(a.get("title")), ident.normalize_title(b.get("title"))
    sa, sb = _surname((a.get("authors") or [None])[0]), _surname((b.get("authors") or [None])[0])
    if not ta or not tb or not sa or sa != sb:
        return None
    ratio = SequenceMatcher(None, ta, tb).ratio()
    return ratio if ratio >= threshold else None


def suggestions(candidates: list[dict], threshold: float = THRESHOLD) -> list[dict]:
    """The pairs of DIFFERENT candidates (as `cluster` returns them) that look alike — same kind, same year, same first-author surname, a title at or above `threshold` — each as a
    linkage suggestion, in the order the candidates came. A suggestion decides nothing: it names the two identities and what they share, carries each side's provenance (the identities
    and sources that retrieved it), and notes the identifiers they state differently (two distinct DOIs are the case a later assessment most needs to see). Nothing is merged, dropped
    or re-identified, and a candidate pairs with every other it looks like."""
    groups: dict[tuple, list[dict]] = {}
    for rec in candidates:   # only candidates that agree on kind, year and first author can be alike: compare within those groups
        groups.setdefault((rec.get("kind"), rec.get("year"), _surname((rec.get("authors") or [None])[0])), []).append(rec)
    order = {id(rec): n for n, rec in enumerate(candidates)}
    found = []
    for group in groups.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                ratio = _alike(a, b, threshold)
                if ratio is None:
                    continue
                ids_a, ids_b = a.get("identifiers") or {}, b.get("identifiers") or {}
                found.append((min(order[id(a)], order[id(b)]), max(order[id(a)], order[id(b)]), {
                    "type": "possible_same_work",
                    "identities": [a["identity"], b["identity"]],
                    "basis": {"title_similarity": round(ratio, 3), "year": a["year"], "first_author": _surname((a.get("authors") or [None])[0]), "kind": a.get("kind")},
                    "differing_identifiers": {k: [ids_a[k], ids_b[k]] for k in sorted(set(ids_a) & set(ids_b)) if ids_a[k] and ids_b[k] and ids_a[k] != ids_b[k]},
                    "provenance": [{"identity": r["identity"], "sources": list(r.get("sources") or []),
                                    "retrieved_at": sorted({p["retrieved_at"] for p in r.get("provenance") or [] if p.get("retrieved_at")})}
                                   for r in (a, b)],
                    "disposition": "unassessed"}))
    return [s for _, _, s in sorted(found, key=lambda f: f[:2])]
