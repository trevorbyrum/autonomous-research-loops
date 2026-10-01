"""Unpaywall: open-access location for a DOI (enrichment only, never discovery)."""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import NO_MEMBERS, OMIT, Client, Members, check, members, need, optional, plain, text

SOURCE_ID = "unpaywall"
SMOKE = {'capability': 'enrich', 'identity': 'doi:10.1038/nature12373', 'what': 'oa_location'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("enrich",)
ENRICHES = ("oa_location",)
BASE = "https://api.unpaywall.org/v2"


def enrich(client: Client, identity: str, what: str = "oa_location") -> dict:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi or what != "oa_location":
        return {"identity": identity, "what": what, "items": []}
    resp = client.get(SOURCE_ID, "enrich", f"{BASE}/{doi}", params={"email": client.contact_email},
                      identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    j = need(SOURCE_ID, resp.json, kind=dict)
    locations = need(SOURCE_ID, j, "oa_locations")
    if not locations:   # none listed: the best location alone — read only now, for it is the one place its being unreadable costs anything
        best_alone = optional(SOURCE_ID, j, "best_oa_location", dict)
        locations = Members([plain(best_alone)]) if best_alone else NO_MEMBERS
    best = j.get("best_oa_location")   # what each listed location is compared with, to say whether it is the best one

    def location(loc: dict):
        url = text(SOURCE_ID, loc.get("url_for_pdf")) or text(SOURCE_ID, loc.get("url"))
        if not url:   # a location that links nowhere is nothing to report
            return OMIT
        return make_record(
            identity=f"doi:{doi}", kind="oa_location", source_id=SOURCE_ID, title=j.get("title"),
            year=j.get("year"), venue=j.get("journal_name"), identifiers={"doi": doi}, links=[url],
            license=loc.get("license"),
            extra={"is_oa": j.get("is_oa"), "oa_status": j.get("oa_status"), "host_type": loc.get("host_type"),
                   "version": loc.get("version"), "is_best": loc is best or loc == best},
            raw=loc,
        )
    return {"identity": f"doi:{doi}", "what": what, "items": members(SOURCE_ID, locations, location),
            "is_oa": plain(j.get("is_oa")), "oa_status": plain(j.get("oa_status"))}
