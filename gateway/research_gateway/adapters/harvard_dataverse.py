"""Harvard Dataverse (also the shared Dataverse client used by qdr and wms)."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi
from .base import AdapterError, Client, check

SOURCE_ID = "harvard_dataverse"
CAPABILITIES = ("find", "resolve", "fetch")
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
                       extra={"description": (item.get("description") or "")[:1000], "subjects": item.get("subjects") or [],
                              "file_count": item.get("fileCount")},
                       raw={k: item.get(k) for k in ("global_id", "name", "authors", "published_at", "subjects", "fileCount", "url")})


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
                       raw={"id": d.get("id"), "persistentUrl": d.get("persistentUrl"), "license": lic, "versionState": v.get("versionState"),
                            "files": [{"id": (f.get("dataFile") or {}).get("id"), "label": f.get("label")} for f in files]})


def file_records(base: str, source_id: str, dataset: dict, d: dict) -> list[dict]:
    out = []
    for f in ((d.get("latestVersion") or {}).get("files") or []):
        df = f.get("dataFile") or {}
        out.append(make_record(identity=f"{dataset['identity']}#{df.get('id')}", kind="file", source_id=source_id,
                               title=f.get("label") or df.get("filename"), license=dataset.get("license"),
                               links=[f"{base}/api/access/datafile/{df.get('id')}"],
                               extra={"file_id": df.get("id"), "content_type": df.get("contentType"), "size": df.get("filesize"),
                                      "restricted": f.get("restricted", False), "description": df.get("description")},
                               raw={k: df.get(k) for k in ("id", "filename", "contentType", "filesize", "persistentId", "md5")}))
    return out


def find_in(client: Client, base: str, source_id: str, secret_name: str | None, query: str, *, limit: int = 20, page: int = 1,
            subtree: str | None = None) -> dict:
    per_page = min(limit, 100)
    params = {"q": query, "type": "dataset", "per_page": per_page, "start": (page - 1) * per_page, "subtree": subtree}
    resp = client.get(source_id, "find", f"{base}/api/search", params=params, headers=headers(client, secret_name), query=query)
    if not check(source_id, resp):
        return {"records": [], "total": 0, "next_page": None}
    data = (resp.json or {}).get("data") or {}
    items, total = data.get("items") or [], data.get("total_count") or 0
    return {"records": [search_record(base, source_id, i) for i in items], "total": total,
            "next_page": page + 1 if items and page * per_page < total else None}


def get_dataset(client: Client, base: str, source_id: str, secret_name: str | None, target: str, request_type: str) -> dict | None:
    doi = _doi(target)
    if not doi:
        raise AdapterError(f"{source_id}: target must be a DOI")
    resp = client.get(source_id, request_type, f"{base}/api/datasets/:persistentId/", params={"persistentId": f"doi:{doi}"},
                      headers=headers(client, secret_name), identity=f"doi:{doi}")
    if not check(source_id, resp):
        return None
    return (resp.json or {}).get("data")


def fetch_in(client: Client, base: str, source_id: str, secret_name: str | None, target: str, *, file_id=None, download: bool = False) -> dict:
    """List a dataset's files; with download=True and file_id, return that file's bytes (never persisted)."""
    if download:
        if not file_id:
            raise AdapterError(f"{source_id}.fetch download needs file_id")
        resp = client.get(source_id, "fetch", f"{base}/api/access/datafile/{int(file_id)}", headers={**headers(client, secret_name), "Accept": "*/*"},
                          identity=f"{target}#{file_id}")
        if not check(source_id, resp):
            return {"identity": target, "records": []}
        return {"identity": target, "records": [], "content": resp.body, "content_type": resp.headers.get("content-type")}
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
