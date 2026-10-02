"""DOAJ: open-access journal articles (always added to article discovery)."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi, normalize_issn
from .base import Client, Rec, check, decode, first_member, identity_from, members, quote, total

SOURCE_ID = "doaj"
SMOKE = {'capability': 'find', 'query': 'management', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi", "issn")
BASE = "https://doaj.org/api"
MAX_RECORDS_PER_QUERY = 1000  # DOAJ refuses a page that starts at or past record 1,000 (docs/PROVIDER-PAGINATION.md)

# What an answer must be. An article is named by the DOI among its identifiers (every one it lists is decoded), else by its own id.
ARTICLE = S.obj({"id": S.maybe_key(),
                 "bibjson": S.obj({"identifier": S.own(S.obj({"type": S.text(), "id": S.text()})), "title": S.text(), "year": S.text(),
                                   "author": S.own(S.obj({"name": S.text()})), "link": S.own(S.obj({"url": S.text()})),
                                   "journal": S.obj({"issns": S.own(S.text()), "title": S.text(), "license": S.own(S.obj({"type": S.text()}))})})},
                alts=(("bibjson.identifier", "id"),))
# A journal's `publisher` is an object that names it (DOAJ's schema) or the name itself; each `ref` is a URL as text, or (as an earlier reading of the schema had
# it) an object that carries it as `url` — one that is an object with no `url` is a URL that is not there, not one the journal leaves out.
JOURNAL = S.obj({"bibjson": S.obj({"title": S.text(), "publisher": S.oneof(S.obj({"name": S.text()}), S.text()),
                                   "ref": S.table(S.oneof(S.obj({"url": S.required(S.text())}), S.text())),
                                   "license": S.own(S.obj({"type": S.text()})), "subject": S.own(S.obj({"term": S.text()}))})})
FIND = S.obj({"results": S.required(S.members(ARTICLE)), "total": S.soft(S.whole())})
RESOLVE_ARTICLE = S.obj({"results": S.required(S.members(ARTICLE))})
RESOLVE_JOURNAL = S.obj({"results": S.required(S.members(JOURNAL))})
SCHEMAS = {"find": FIND, "resolve:article": RESOLVE_ARTICLE, "resolve:journal": RESOLVE_JOURNAL}


def _record(a) -> dict:
    b = a["bibjson"]
    dois = [normalize_doi(i["id"]) for i in b["identifier"] if (i["type"] or "").lower() == "doi"]   # every DOI it lists is read
    doi = dois[0] if dois else None
    journal = b["journal"]
    issns = [normalize_issn(i) for i in journal["issns"] if normalize_issn(i)]
    ids = {"doi": doi} if doi else {}
    if issns:
        ids["issn"] = issns[0]
    links = [u for u in (l["url"] for l in b["link"]) if u]
    licenses = journal["license"]
    return make_record(
        identity=identity_from(SOURCE_ID, ("doi", doi), ("doaj", a["id"])),
        kind="article", source_id=SOURCE_ID, title=b["title"],
        authors=[n for n in (x["name"] for x in b["author"]) if n],
        year=year_from(b["year"]), venue=journal["title"], identifiers=ids, links=links,
        license=licenses[0]["type"] if licenses else None,
        extra={"open_access": True, "doaj_id": a["id"]},
        raw=a.raw,
    )


def find(client: Client, query: str, *, limit: int = 20, page: int = 1) -> dict:
    page_size = min(limit, 100)
    if (page - 1) * page_size >= MAX_RECORDS_PER_QUERY:
        return {"records": [], "total": None, "next_page": None,
                "capability_fact": f"DOAJ caps a query at {MAX_RECORDS_PER_QUERY} records"}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/search/articles/{quote(query)}",
                      params={"page": page, "pageSize": page_size, "sort": "created_date:desc"}, query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = decode(SOURCE_ID, FIND, resp.json)
    results = j["results"]
    count = total(j["total"], (page - 1) * page_size + len(results))
    # DOAJ's own code: the last page is the one reaching `total` (page_count = ((total - 1) // page_size) + 1),
    # and the next page exists only while it starts below record 1,000 — the cap ends nothing
    reached = count is not None and page * page_size >= count
    nxt = page + 1 if count is not None and not reached and page * page_size < MAX_RECORDS_PER_QUERY else None
    return {"records": members(SOURCE_ID, results, _record), "total": count, "next_page": nxt, "exhausted": reached}


def _journal(issn: str, a) -> dict:
    b = a["bibjson"]
    stated, licenses = b["publisher"], b["license"]
    publisher = stated["name"] if isinstance(stated, Rec) else stated   # an object that names it (DOAJ's schema), or the name itself
    return make_record(identity=f"issn:{issn}", kind="venue", source_id=SOURCE_ID, title=b["title"],
                       venue=publisher,
                       identifiers={"issn": issn},
                       links=[u for u in ((r["url"] if isinstance(r, Rec) else r) for r in b["ref"].values()) if u],
                       license=(licenses[0] if licenses else {"type": None})["type"],
                       extra={"publisher": publisher, "in_doaj": True, "subjects": [t for t in (s["term"] for s in b["subject"]) if t]},
                       raw=a.raw)


def resolve(client: Client, identity: str) -> dict | None:
    """A DOI resolves to its article; an ISSN resolves to its journal (both declared in SCHEMES)."""
    value = identity.split(":", 1)[-1] if ":" in identity else identity
    issn = normalize_issn(value) if identity.lower().startswith("issn:") or normalize_issn(value) else None
    if issn and not normalize_doi(value):
        resp = client.get(SOURCE_ID, "resolve", f"{BASE}/search/journals/" + quote(f'issn:"{issn}"'),
                          params={"pageSize": 1}, identity=f"issn:{issn}")
        if not check(SOURCE_ID, resp):
            return None
        return first_member(SOURCE_ID, decode(SOURCE_ID, RESOLVE_JOURNAL, resp.json)["results"], lambda a: _journal(issn, a))
    doi = normalize_doi(value)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/search/articles/" + quote(f'doi:"{doi}"'),
                      params={"pageSize": 1}, identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    return first_member(SOURCE_ID, decode(SOURCE_ID, RESOLVE_ARTICLE, resp.json)["results"], _record)
