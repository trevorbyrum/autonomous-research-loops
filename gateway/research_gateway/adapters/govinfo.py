"""GovInfo (api.data.gov key): primary federal documents — bills, budgets, reports, regulations."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record, year_from
from .base import OMIT, AdapterError, Client, PayloadError, check, decode, members, quote, total

SOURCE_ID = "govinfo"
SMOKE = {'capability': 'find', 'query': 'artificial intelligence', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "fetch")
BASE = "https://api.govinfo.gov"
FORMATS = ("pdf", "htm", "xml", "txt", "zip")

# What an answer must be. A package lists no formats when it has no `download`; one whose is not an object is unreadable. `results` may be left out only when the
# answer's `count` is 0. A package's files are the formats its summary's `download` lists, each entry its own member, and they need the package's title and nothing
# else of it: its authors and dates cannot cost them.
PACKAGE = S.obj({"packageId": S.key(), "title": S.text(), "governmentAuthor1": S.text(), "governmentAuthor2": S.text(), "dateIssued": S.text(),
                 "collectionCode": S.text(), "lastModified": S.any_(), "docClass": S.any_(), "download": S.table(S.text())})
FIND = S.obj({"results": S.members(PACKAGE, empty_when=("count",)), "count": S.soft(S.whole()), "offsetMark": S.soft(S.token())})
FORMATS_OF = S.obj({"packageId": S.key(), "title": S.text(), "download": S.entries(S.any_())})   # the summary must name its package (a decision); a link's value is never read: its key selects the format
SCHEMAS = {"find": FIND, "resolve": PACKAGE, "fetch": FORMATS_OF}


def _headers(client: Client) -> dict | None:
    key = client.secret("api_data_gov")
    return {"X-Api-Key": key} if key else None


def _package_id(target: str) -> str:
    return target.split(":", 1)[-1] if target.startswith("govinfo:") else target


def _record(p) -> dict:
    pid = p["packageId"]
    dl = p["download"]   # a package that lists no formats has no `download`
    links = [f"https://www.govinfo.gov/app/details/{pid}"] + [u for u in dl.values() if u]
    return make_record(identity=f"govinfo:{pid}", kind="document", source_id=SOURCE_ID, title=p["title"],
                       authors=[a for a in (p["governmentAuthor1"], p["governmentAuthor2"]) if a],
                       year=year_from(p["dateIssued"]), venue=p["collectionCode"],
                       identifiers={"package_id": str(pid)}, links=links, license="US Government work (public domain)",
                       extra={"date_issued": p["dateIssued"], "last_modified": p["lastModified"],
                              "doc_class": p["docClass"],
                              "formats": sorted(k[:-4] for k in dl if k.endswith("Link") and k[:-4] in FORMATS)},
                       raw=p.raw)


def find(client: Client, query: str, *, limit: int = 20, offset_mark: str = "*", collection: str | None = None) -> dict:
    hdrs = _headers(client)
    if not hdrs:
        return {"records": [], "total": 0, "next_offset_mark": None, "capability_fact": "no api.data.gov key configured"}
    q = f"{query} collection:({collection})" if collection else query
    body = {"query": q, "pageSize": min(limit, 100), "offsetMark": offset_mark,
            "sorts": [{"field": "score", "sortOrder": "DESC"}]}
    resp = client.post(SOURCE_ID, "find", f"{BASE}/search", body=body, headers=hdrs, query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = decode(SOURCE_ID, FIND, resp)
    results = j["results"]   # an answer may leave `results` out only when it counts nothing
    # GovInfo documents only the continuation — `*` first, then the answer's offsetMark — and no last
    # page, nor what `count` counts: a mark that moves continues, and nothing here ever ends the lane
    # (docs/PROVIDER-PAGINATION.md); a mark handed back unchanged would only repeat this page
    mark = j["offsetMark"]
    nxt = mark if mark not in (None, offset_mark) else None
    return {"records": members(SOURCE_ID, results, _record), "total": total(j["count"], len(results)), "next_offset_mark": nxt,
            "exhausted": False}


def _summary(client: Client, pid: str, hdrs: dict, request_type: str, schema: str = "resolve"):
    """The package's summary as the `schema` operation decodes it, None when there is no such package; an answer that is not one is unreadable."""
    resp = client.get(SOURCE_ID, request_type, f"{BASE}/packages/{quote(pid, safe='')}/summary", headers=hdrs, identity=f"govinfo:{pid}")
    if not check(SOURCE_ID, resp):
        return None
    summary = decode(SOURCE_ID, SCHEMAS[schema], resp)
    if not summary["packageId"]:
        raise PayloadError(f"{SOURCE_ID}: the package summary carries no packageId")
    return summary


def resolve(client: Client, identity: str) -> dict | None:
    hdrs = _headers(client)
    if not hdrs:   # an unconfigured key is an auth fact, never "no such package"
        return {"capability_fact": "no api.data.gov key configured"}
    summary = _summary(client, _package_id(identity), hdrs, "resolve")
    return _record(summary) if summary is not None else None


def fetch(client: Client, target: str, *, fmt: str = "pdf", download: bool = False) -> dict:
    """List a package's download links; with download=True return the bytes of one format (never persisted)."""
    if fmt not in FORMATS:
        raise AdapterError(f"govinfo.fetch fmt must be one of {FORMATS}")
    pid = _package_id(target)
    identity = f"govinfo:{pid}"
    hdrs = _headers(client)
    if not hdrs:
        return {"identity": identity, "records": [], "capability_fact": "no api.data.gov key configured"}
    if not download:
        # the files are the formats the summary's `download` lists, each entry its own member, and need the package's title and nothing else of
        # it: its authors and dates cannot cost them
        summary = _summary(client, pid, hdrs, "resolve", "fetch")
        if summary is None:
            return {"identity": identity, "records": []}
        title = summary["title"]

        def file(entry):
            name = entry["key"]
            if not (name.endswith("Link") and name[:-4] in FORMATS):   # a link that is not one of the formats a download is asked for
                return OMIT
            f = name[:-4]
            return make_record(identity=f"{identity}#{f}", kind="file", source_id=SOURCE_ID, title=f"{title} ({f})" if title else f,
                               links=[f"{BASE}/packages/{pid}/{f}"], license="US Government work (public domain)", extra={"format": f}, raw=None)
        files = members(SOURCE_ID, summary["download"], file)
        return {"identity": identity, "records": sorted(files, key=lambda r: (r is None, r["identity"] if r else ""))}
    resp = client.get(SOURCE_ID, "fetch", f"{BASE}/packages/{quote(pid, safe='')}/{fmt}", headers={**hdrs, "Accept": "*/*"}, identity=identity)
    if not check(SOURCE_ID, resp, allow_html=True):  # raw file download: an HTML document can be legitimate content here
        return {"identity": identity, "records": []}
    return {"identity": identity, "records": [], "content": resp.download(), "content_type": resp.headers.get("content-type"),
            "format": fmt, "license": "US Government Work"}


def download_request(record: dict, target: str) -> dict | None:
    """The COMPLETE research_download call for one listed format (D-31a): the PARENT
    target plus this adapter's own selector — never a fragment-mangled identity."""
    fmt = record.get("format") or (record.get("extra") or {}).get("format")
    return {"target": target, "params": {"fmt": fmt}} if fmt else None
