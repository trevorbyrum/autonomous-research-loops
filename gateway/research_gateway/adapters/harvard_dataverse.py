"""Harvard Dataverse (also the shared Dataverse client used by qdr and wms)."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi
from ..core.licenses import allow_listed
from .base import AdapterError, Client, PayloadError, check, members, need

SOURCE_ID = "harvard_dataverse"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.7910/DVN/OY6CBK'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "fetch")
SCHEMES = ("doi",)
BASE = "https://dataverse.harvard.edu"


def headers(client: Client, secret_name: str | None) -> dict:
    tok = client.secret(secret_name) if secret_name else None
    return {"X-Dataverse-key": tok} if tok else {}


def _doi(target: str) -> str | None:
    return normalize_doi(target.split(":", 1)[-1] if target.startswith("doi:") else target)


def _field(fields: list, name: str):
    return next((f.get("value") for f in fields if f.get("typeName") == name), None)


def search_record(base: str, source_id: str, item: dict) -> dict:
    doi = normalize_doi((item.get("global_id") or "").replace("doi:", ""))
    return make_record(identity=f"doi:{doi}" if doi else f"{source_id}:{item.get('entity_id')}", kind="dataset", source_id=source_id,
                       title=item.get("name"), authors=item.get("authors") or [], year=year_from(item.get("published_at")),
                       venue=item.get("name_of_dataverse"), identifiers={"doi": doi} if doi else {},
                       links=[item.get("url") or f"{base}/dataset.xhtml?persistentId=doi:{doi}"],
                       license=item.get("license"),   # some Dataverse search hits state it; commercial use of the rest needs a resolve (D-25)
                       extra={"description": (item.get("description") or "")[:1000], "subjects": item.get("subjects") or [],
                              "file_count": item.get("fileCount")},
                       raw=item)


def dataset_record(base: str, source_id: str, d: dict) -> dict:
    v = d.get("latestVersion") or {}
    fields = ((v.get("metadataBlocks") or {}).get("citation") or {}).get("fields") or []
    doi = normalize_doi(f"{d.get('authority')}/{d.get('identifier')}") if d.get("identifier") else None
    authors = [(a.get("authorName") or {}).get("value") for a in (_field(fields, "author") or []) if isinstance(a, dict)]
    lic = v.get("license")
    lic_name = lic.get("name") if isinstance(lic, dict) else lic
    files = v.get("files") or []
    return make_record(identity=f"doi:{doi}" if doi else f"{source_id}:{d.get('id')}", kind="dataset", source_id=source_id,
                       title=_field(fields, "title"), authors=[a for a in authors if a], year=year_from(v.get("releaseTime")),
                       venue=d.get("publisher"), identifiers={"doi": doi} if doi else {},
                       links=[d.get("persistentUrl") or f"{base}/dataset.xhtml?persistentId=doi:{doi}"], license=lic_name,
                       extra={"version": f"{v.get('versionNumber')}.{v.get('versionMinorNumber')}", "file_count": len(files),
                              "terms_of_use": v.get("termsOfUse")},
                       raw=d)


def _file(base: str, source_id: str, dataset: dict, f: dict) -> dict:
    df = f.get("dataFile") or {}
    return make_record(identity=f"{dataset['identity']}#{df.get('id')}", kind="file", source_id=source_id,
                       title=f.get("label") or df.get("filename"), license=dataset.get("license"),
                       links=[f"{base}/api/access/datafile/{df.get('id')}"],
                       extra={"file_id": df.get("id"), "content_type": df.get("contentType"), "size": df.get("filesize"),
                              "restricted": f.get("restricted", False), "description": df.get("description")},
                       raw=df)


def file_records(base: str, source_id: str, dataset: dict, d: dict) -> list:
    """The dataset's files, each decoded alone (base.members): None where a file member is unreadable."""
    version = d.get("latestVersion") or {}
    files = need(source_id, version, "files") if version.get("files") else []   # a dataset without files has none
    return members(source_id, files, lambda f: _file(base, source_id, dataset, f))


def find_in(client: Client, base: str, source_id: str, secret_name: str | None, query: str, *, limit: int = 20, page: int = 1,
            subtree: str | None = None) -> dict:
    per_page = min(limit, 100)
    params = {"q": query, "type": "dataset", "per_page": per_page, "start": (page - 1) * per_page, "subtree": subtree}
    resp = client.get(source_id, "find", f"{base}/api/search", params=params, headers=headers(client, secret_name), query=query)
    check(source_id, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    data = need(source_id, resp.json, "data", kind=dict)
    items, total = need(source_id, data, "items"), data.get("total_count")
    # the Dataverse guide pages by moving `start` on by the page size "until you reach the total_count"
    # (its loop: `condition = start < total`); a missing total neither continues nor ends (docs/PROVIDER-PAGINATION.md)
    reached = type(total) is int and page * per_page >= total
    return {"records": members(source_id, items, lambda i: search_record(base, source_id, i)), "total": total,
            "next_page": page + 1 if type(total) is int and not reached else None, "exhausted": reached}


def get_dataset(client: Client, base: str, source_id: str, secret_name: str | None, target: str, request_type: str) -> dict | None:
    doi = _doi(target)
    if not doi:
        raise AdapterError(f"{source_id}: target must be a DOI")
    resp = client.get(source_id, request_type, f"{base}/api/datasets/:persistentId/", params={"persistentId": f"doi:{doi}"},
                      headers=headers(client, secret_name), identity=f"doi:{doi}")
    if not check(source_id, resp):
        return None
    return need(source_id, resp.json, "data", kind=dict)


def fetch_in(client: Client, base: str, source_id: str, secret_name: str | None, target: str, *, file_id=None, download: bool = False) -> dict:
    """List a dataset's files; with download=True and file_id, return that file's bytes (never persisted)."""
    if download:
        if not file_id:
            raise AdapterError(f"{source_id}.fetch download needs file_id")
        # membership and licence first: the file must belong to THIS dataset, and the download
        # carries the dataset's licence so the executor can authorize it (R-6, R-8, D-23)
        d = get_dataset(client, base, source_id, secret_name, target, "fetch")
        if d is None:
            return {"identity": target, "records": [], "capability_fact": "dataset not found"}
        ds = dataset_record(base, source_id, d)
        files = file_records(base, source_id, ds, d)
        wanted = [f for f in files if f and f["file_id"] == int(file_id)]
        if not wanted:
            if None in files:   # a file member that cannot be read might be this one: its membership is not established
                raise PayloadError(f"{source_id}: {files.count(None)} file member(s) unreadable; file {file_id} cannot be shown to belong to {ds['identity']}")
            raise AdapterError(f"{source_id}: file {file_id} does not belong to {ds['identity']}")
        if client.commercial:
            file_restricted = any(f["restricted"] for f in wanted)
            if not allow_listed(ds.get("license")) or ds.get("terms_of_use") or file_restricted:
                # a CC0 label with extra terms of use, or a restricted member file, is not CC0 (D-25)
                why = ("restricted file" if file_restricted else
                       "additional terms of use" if ds.get("terms_of_use") else
                       f"licence {ds.get('license') or 'unknown'}")
                return {"identity": ds["identity"], "records": [],
                        "capability_fact": f"download refused before fetching: {why} is not usable commercially (R-8)"}
        resp = client.get(source_id, "fetch", f"{base}/api/access/datafile/{int(file_id)}", headers={**headers(client, secret_name), "Accept": "*/*"},
                          identity=f"{ds['identity']}#{file_id}")
        if not check(source_id, resp, allow_html=True):  # raw file download: an HTML document can be legitimate content here
            return {"identity": ds["identity"], "records": []}
        return {"identity": ds["identity"], "records": [], "content": resp.body,
                "content_type": resp.headers.get("content-type"), "license": ds.get("license")}
    d = get_dataset(client, base, source_id, secret_name, target, "fetch")
    if d is None:
        return {"identity": target, "records": []}
    ds = dataset_record(base, source_id, d)
    return {"identity": ds["identity"], "records": file_records(base, source_id, ds, d)}


def find(client: Client, query: str, *, limit: int = 20, page: int = 1, subtree: str | None = None) -> dict:
    return find_in(client, BASE, SOURCE_ID, SOURCE_ID, query, limit=limit, page=page, subtree=subtree)


def resolve(client: Client, identity: str) -> dict | None:
    d = get_dataset(client, BASE, SOURCE_ID, SOURCE_ID, identity, "resolve")
    return dataset_record(BASE, SOURCE_ID, d) if d else None


def fetch(client: Client, target: str, *, file_id=None, download: bool = False) -> dict:
    return fetch_in(client, BASE, SOURCE_ID, SOURCE_ID, target, file_id=file_id, download=download)


def download_request(record: dict, target: str) -> dict | None:
    """The COMPLETE research_download call for one listed file (D-31a): the PARENT dataset
    target (never the #file fragment — the membership check resolves the dataset DOI)
    plus the file's own id."""
    file_id = record.get("file_id", (record.get("extra") or {}).get("file_id"))
    return {"target": target, "params": {"file_id": file_id}} if file_id is not None else None
