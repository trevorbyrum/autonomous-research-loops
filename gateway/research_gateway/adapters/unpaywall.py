"""Unpaywall: open-access location for a DOI (enrichment only, never discovery)."""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_doi
from ..core import schema as S
from .base import OMIT, Client, MemberList, PayloadError, check, decode, is_unreadable, members

SOURCE_ID = "unpaywall"
SMOKE = {'capability': 'enrich', 'identity': 'doi:10.1038/nature12373', 'what': 'oa_location'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("enrich",)
ENRICHES = ("oa_location",)
BASE = "https://api.unpaywall.org/v2"

# What an answer must be (R11-1). `oa_locations` and `best_oa_location` are alternatives: the best location stands in when nothing is listed, so BOTH
# are decoded, nested contents included, before either is chosen. A listed location that cannot be read costs that location only; so does the best
# one, which the listed ones may not hold: it is `isolated`, and the adapter says what that loses.
LOCATION = S.obj({"url_for_pdf": S.text(), "url": S.text(), "host_type": S.any_(), "version": S.any_(), "license": S.text()})
SCHEMA = S.obj({"oa_locations": S.required(S.members(LOCATION)), "best_oa_location": S.isolated(LOCATION), "title": S.text(), "year": S.year(),
                "journal_name": S.text(), "is_oa": S.soft(S.maybe(S.flag())), "oa_status": S.soft(S.text())},   # both are returned to the caller as facts: kinds; one that cannot be read says nothing (None) and costs no location
               alts=(("oa_locations", "best_oa_location"),))


def enrich(client: Client, identity: str, what: str = "oa_location") -> dict:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi or what != "oa_location":
        return {"identity": identity, "what": what, "items": []}
    resp = client.get(SOURCE_ID, "enrich", f"{BASE}/{doi}", params={"email": client.contact_email},
                      identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    j = decode(SOURCE_ID, SCHEMA, resp)
    locations, best = j["oa_locations"], j["best_oa_location"]
    best_unreadable = is_unreadable(best)
    if not locations:   # none listed: the best location alone stands in, and nothing stands in for it when it cannot be read
        if best_unreadable:
            raise PayloadError(f"{SOURCE_ID}: no listed location, and the best location cannot be read")
        locations = MemberList([best] if not best.empty else [])
    best_raw = None if best_unreadable else best.raw   # what each listed location is compared with, to say whether it is the best one

    def location(loc):
        url = loc["url_for_pdf"] or loc["url"]
        if not url:   # a location that links nowhere is nothing to report
            return OMIT
        return make_record(
            identity=f"doi:{doi}", kind="oa_location", source_id=SOURCE_ID, title=j["title"],
            year=j["year"], venue=j["journal_name"], identifiers={"doi": doi}, links=[url],
            license=loc["license"],
            extra={"is_oa": j["is_oa"], "oa_status": j["oa_status"], "host_type": loc["host_type"],
                   "version": loc["version"], "is_best": loc.raw == best_raw},
            raw=loc.raw,
        )
    items = members(SOURCE_ID, locations, location)
    if best_unreadable:
        items.append(None)   # something the answer says that cannot be read, which the listed locations may not hold: dropped and counted, so the lane is partial
    return {"identity": f"doi:{doi}", "what": what, "items": items,
            "is_oa": j["is_oa"], "oa_status": j["oa_status"]}
