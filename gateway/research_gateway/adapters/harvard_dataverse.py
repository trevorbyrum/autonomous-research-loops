"""Harvard Dataverse (also the shared Dataverse client used by qdr and wms)."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi
from ..core.licenses import allow_listed
from .base import AdapterError, Client, PayloadError, Rec, check, decode, identity_from, members, total

SOURCE_ID = "harvard_dataverse"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.7910/DVN/OY6CBK'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "fetch")
SCHEMES = ("doi",)
BASE = "https://dataverse.harvard.edu"

# What an answer must be. A search hit is named by its DOI, else its entity id; a dataset by its `authority`/`identifier`, else its id (every alternative decoded
# before the record picks one). A dataset's licence is an object that names it, or the name itself. The citation block is a list of {typeName, value} whose value is
# text for `title` and a list of authors for `author`. The dataset's files are its latest version's members: the listing needs the dataset's identity, licence and
# terms of use and nothing else of it (R8), so it has a schema of its own, and a field no file needs cannot cost them.
HIT = S.obj({"global_id": S.text(), "entity_id": S.maybe_key(), "name": S.text(), "authors": S.own(S.text()), "published_at": S.text(), "name_of_dataverse": S.text(),
             "url": S.text(), "license": S.text(), "publisher": S.text(), "description": S.text(), "subjects": S.own(S.any_()), "fileCount": S.any_()},
            alts=(("global_id", "entity_id"),))
SEARCH = S.obj({"data": S.required(S.obj({"items": S.required(S.members(HIT)), "total_count": S.soft(S.whole())}))})
LICENSE = S.oneof(S.obj({"name": S.text()}), S.text())
CITATION_FIELD = S.obj({"typeName": S.text(), "value": S.by("typeName", {"title": S.text(), "author": S.own(S.obj({"authorName": S.obj({"value": S.text()})}))})})
FILE = S.obj({"label": S.text(), "restricted": S.flag(),
              "dataFile": S.obj({"id": S.key(), "filename": S.text(), "contentType": S.any_(), "filesize": S.any_(), "description": S.any_()})})
_DATASET = {"id": S.maybe_key(), "identifier": S.text(), "authority": S.text()}
DATASET = S.obj({**_DATASET, "publisher": S.text(), "persistentUrl": S.text(),
                 "latestVersion": S.obj({"license": LICENSE, "termsOfUse": S.text(), "releaseTime": S.text(), "versionNumber": S.any_(), "versionMinorNumber": S.any_(),
                                         "metadataBlocks": S.obj({"citation": S.obj({"fields": S.own(CITATION_FIELD)})}),
                                         "files": S.soft(S.own(S.any_()))})},   # only counted here: a list that cannot be read is a count that is unknown
                alts=(("identifier", "id"),))
FILES = S.obj({**_DATASET, "latestVersion": S.obj({"license": LICENSE, "termsOfUse": S.text(), "files": S.members(FILE)})}, alts=(("identifier", "id"),))
SCHEMAS = {"find": SEARCH, "resolve": S.obj({"data": S.required(DATASET)}), "fetch": S.obj({"data": S.required(FILES)})}


def headers(client: Client, secret_name: str | None) -> dict:
    tok = client.secret(secret_name) if secret_name else None
    return {"X-Dataverse-key": tok} if tok else {}


def _doi(target: str) -> str | None:
    return normalize_doi(target.split(":", 1)[-1] if target.startswith("doi:") else target)


def search_record(base: str, source_id: str, item) -> dict:
    doi = normalize_doi((item["global_id"] or "").replace("doi:", ""))
    return make_record(identity=identity_from(source_id, ("doi", doi), (source_id, item["entity_id"])), kind="dataset", source_id=source_id,
                       title=item["name"], authors=item["authors"], year=year_from(item["published_at"]),
                       venue=item["name_of_dataverse"], identifiers={"doi": doi} if doi else {},
                       links=[item["url"] or f"{base}/dataset.xhtml?persistentId=doi:{doi}"],
                       license=item["license"],   # some Dataverse search hits state it; commercial use of the rest needs a resolve (D-25)
                       extra={"publisher": item["publisher"], "description": (item["description"] or "")[:1000],
                              "subjects": item["subjects"],
                              "file_count": item["fileCount"]},
                       raw=item.raw)


def _dataset_doi(d) -> str | None:
    """The dataset's DOI, from its `authority` and `identifier`: none when it states no identifier (missing, null, empty)."""
    identifier, authority = d["identifier"], d["authority"]
    return normalize_doi(f"{authority}/{identifier}") if identifier else None


def dataset_context(source_id: str, d) -> dict:
    """What every file of a dataset takes from it, and nothing else: its identity, its licence, and the terms of use that limit a download.
    The files are listed from the version's `files`, so a field no file needs (the title, the authors) cannot cost them (R8)."""
    version = d["latestVersion"]
    lic = version["license"]
    doi = _dataset_doi(d)
    return {"identity": identity_from(source_id, ("doi", doi), (source_id, d["id"])),
            "license": lic["name"] if isinstance(lic, Rec) else lic,
            "terms_of_use": version["termsOfUse"]}


def _field(fields: list, name: str):
    return next((f["value"] for f in fields if f["typeName"] == name), None)


def dataset_record(base: str, source_id: str, d) -> dict:
    v = d["latestVersion"]
    context = dataset_context(source_id, d)
    fields = v["metadataBlocks"]["citation"]["fields"]
    doi = _dataset_doi(d)
    authors = [a["authorName"]["value"] for a in _field(fields, "author") or []]
    publisher = d["publisher"]
    return make_record(identity=context["identity"], kind="dataset", source_id=source_id,
                       title=_field(fields, "title"), authors=[a for a in authors if a], year=year_from(v["releaseTime"]),
                       venue=publisher, identifiers={"doi": doi} if doi else {},
                       links=[d["persistentUrl"] or f"{base}/dataset.xhtml?persistentId=doi:{doi}"], license=context["license"],
                       extra={"publisher": publisher, "version": f"{v['versionNumber']}.{v['versionMinorNumber']}",
                              "file_count": None if v["files"] is None else len(v["files"]),
                              "terms_of_use": context["terms_of_use"]},
                       raw=d.raw)


def _file(base: str, source_id: str, dataset: dict, f) -> dict:
    df = f["dataFile"]
    return make_record(identity=f"{dataset['identity']}#{df['id']}", kind="file", source_id=source_id,
                       title=f["label"] or df["filename"], license=dataset.get("license"),
                       links=[f"{base}/api/access/datafile/{df['id']}"],
                       extra={"file_id": df["id"], "content_type": df["contentType"], "size": df["filesize"],
                              "restricted": f["restricted"], "description": df["description"]},
                       raw=df.raw)


def file_records(base: str, source_id: str, dataset: dict, d) -> list:
    """The dataset's files, each decoded alone (base.members): None where a file member is unreadable."""
    return members(source_id, d["latestVersion"]["files"], lambda f: _file(base, source_id, dataset, f))


def find_in(client: Client, base: str, source_id: str, secret_name: str | None, query: str, *, limit: int = 20, page: int = 1,
            subtree: str | None = None) -> dict:
    per_page = min(limit, 100)
    params = {"q": query, "type": "dataset", "per_page": per_page, "start": (page - 1) * per_page, "subtree": subtree}
    resp = client.get(source_id, "find", f"{base}/api/search", params=params, headers=headers(client, secret_name), query=query)
    check(source_id, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    data = decode(source_id, SEARCH, resp.json)["data"]
    items = data["items"]
    count = total(data["total_count"], (page - 1) * per_page + len(items))
    # the Dataverse guide pages by moving `start` on by the page size "until you reach the total_count"
    # (its loop: `condition = start < total`); a missing total neither continues nor ends (docs/PROVIDER-PAGINATION.md)
    reached = count is not None and page * per_page >= count
    return {"records": members(source_id, items, lambda i: search_record(base, source_id, i)), "total": count,
            "next_page": page + 1 if count is not None and not reached else None, "exhausted": reached}


def get_dataset(client: Client, base: str, source_id: str, secret_name: str | None, target: str, request_type: str, schema: str = "resolve"):
    """The dataset as the `schema` operation ("resolve": the record; "fetch": the listing of its files) decodes it; None when there is no such dataset."""
    doi = _doi(target)
    if not doi:
        raise AdapterError(f"{source_id}: target must be a DOI")
    resp = client.get(source_id, request_type, f"{base}/api/datasets/:persistentId/", params={"persistentId": f"doi:{doi}"},
                      headers=headers(client, secret_name), identity=f"doi:{doi}")
    if not check(source_id, resp):
        return None
    return decode(source_id, SCHEMAS[schema], resp.json)["data"]


def fetch_in(client: Client, base: str, source_id: str, secret_name: str | None, target: str, *, file_id=None, download: bool = False) -> dict:
    """List a dataset's files; with download=True and file_id, return that file's bytes (never persisted)."""
    if download:
        if not file_id:
            raise AdapterError(f"{source_id}.fetch download needs file_id")
        # membership and licence first: the file must belong to THIS dataset, and the download
        # carries the dataset's licence so the executor can authorize it (R-6, R-8, D-23)
        d = get_dataset(client, base, source_id, secret_name, target, "fetch", "fetch")
        if d is None:
            return {"identity": target, "records": [], "capability_fact": "dataset not found"}
        ds = dataset_context(source_id, d)
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
    d = get_dataset(client, base, source_id, secret_name, target, "fetch", "fetch")
    if d is None:
        return {"identity": target, "records": []}
    ds = dataset_context(source_id, d)
    return {"identity": ds["identity"], "records": file_records(base, source_id, ds, d)}


def find(client: Client, query: str, *, limit: int = 20, page: int = 1, subtree: str | None = None) -> dict:
    return find_in(client, BASE, SOURCE_ID, SOURCE_ID, query, limit=limit, page=page, subtree=subtree)


def resolve(client: Client, identity: str) -> dict | None:
    d = get_dataset(client, BASE, SOURCE_ID, SOURCE_ID, identity, "resolve")
    return dataset_record(BASE, SOURCE_ID, d) if d is not None else None


def fetch(client: Client, target: str, *, file_id=None, download: bool = False) -> dict:
    return fetch_in(client, BASE, SOURCE_ID, SOURCE_ID, target, file_id=file_id, download=download)


def download_request(record: dict, target: str) -> dict | None:
    """The COMPLETE research_download call for one listed file (D-31a): the PARENT dataset
    target (never the #file fragment — the membership check resolves the dataset DOI)
    plus the file's own id."""
    file_id = record.get("file_id", (record.get("extra") or {}).get("file_id"))
    return {"target": target, "params": {"file_id": file_id}} if file_id is not None else None
