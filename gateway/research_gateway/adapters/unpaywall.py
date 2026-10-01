"""Unpaywall: open-access location for a DOI (enrichment only, never discovery)."""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import NO_MEMBERS, OMIT, Client, Members, PayloadError, check, members, need, optional, plain, preferred, text

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
    best_alone, best_unreadable = None, False
    try:   # read whether or not the listed locations make it unnecessary (R10-1): the listed locations are an answer of their own, so one that cannot be read costs completeness, not them
        best_alone = optional(SOURCE_ID, j, "best_oa_location", dict)
    except PayloadError:
        best_unreadable = True
    if not locations:   # none listed: the best location alone stands in, and nothing stands in for it when it cannot be read
        if best_unreadable:
            raise PayloadError(f"{SOURCE_ID}: no listed location, and the best location cannot be read")
        locations = Members([plain(best_alone)]) if best_alone else NO_MEMBERS
    best = j.get("best_oa_location")   # what each listed location is compared with, to say whether it is the best one

    def location(loc: dict):
        url = preferred(text(SOURCE_ID, loc.get("url_for_pdf")), text(SOURCE_ID, loc.get("url")))
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
    items = members(SOURCE_ID, locations, location)
    if best_unreadable:
        items.append(None)   # something the answer says that cannot be read, which the listed locations may not hold: dropped and counted, so the lane is partial
    return {"identity": f"doi:{doi}", "what": what, "items": items,
            "is_oa": plain(j.get("is_oa")), "oa_status": plain(j.get("oa_status"))}
