"""Populated optional-field variants of the harness fixtures (task 2b-repair-10a, R9-2).

The minimal fixtures of tests/invariant_ops.py leave out most optional fields a provider documents, so the corruption pass never reached
them: R9-2 (OpenML `licence or license` erasing a present wrong-kind value) lived in a field no fixture held. Each variant here is the same
operation with every documented optional field of its provider's record populated with a valid value. `build(ops)` returns them, and
tests/invariant_ops.py appends them to its own operation tuples, so the harness corrupts every one of their positions exactly as it does the
minimal ones. They also run through `test_oracle.ExpectedCanonicalFields` with the base operation's expectations: adding fields the
fixture did not carry must not change what the gateway says about the fields it did.

Where the fields come from (provider documentation, never the adapters):
  Crossref       swagger `Work` (private/evidence/2b-repair-7/docs/crossref-swagger-docs.json)
  DataCite       OpenAPI `DoiPropertiesMetadata`, `RepositoryResponse` (datacite-openapi.yaml)
  DOAJ           swagger `bibjson` of an article and of a journal, including journal `ref` (doaj-swagger.json)
  OpenAIRE       Graph API V1 `GraphResult`, `Instance` (openaire-graph-v1-spec.json)
  OpenML         the description example of `Api_data.php` (`licence`, `description`, `default_target_attribute`, ...); the US spelling
                 `license` is not in that document: a variant carries it ALONE, one carries it BESIDE `licence`
  Kaggle         the provider-owned client's `ApiDataset` (kagglesdk 0.1.37: `licenseName`, `creatorName`, ...)
  Semantic Scholar / Europe PMC / GovInfo / Socrata / Dataverse / Hugging Face: each provider's published response schema or API guide
Values are valid, ordinary, and chosen not to alter any field the base fixture's expectations assert (a creator keeps its `name`, a licence
keeps its identifier).
"""
from __future__ import annotations

import copy
from dataclasses import replace


def merge(base: dict, extra: dict) -> dict:
    """`base` with `extra` added; a key both hold is kept as `base` has it, except maps, which merge."""
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if k not in out:
            out[k] = copy.deepcopy(v)
        elif isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge(out[k], v)
    return out


def each(body, path: tuple, fn):
    """`body` with `fn` applied to every element of the list at `path` (a path of keys; `()` is the body itself)."""
    body = copy.deepcopy(body)
    holder = body
    for key in path:
        holder = holder[key]
    for i, member in enumerate(holder):
        holder[i] = fn(member)
    return body


def at(body, path: tuple, fn):
    """`body` with `fn` applied to the one object at `path`."""
    if not path:
        return fn(body)
    body = copy.deepcopy(body)
    holder = body
    for key in path[:-1]:
        holder = holder[key]
    holder[path[-1]] = fn(holder[path[-1]])
    return body


DATE = {"date-parts": [[2021, 3, 1]], "date-time": "2021-03-01T00:00:00Z", "timestamp": 1614556800000}

# ------------------------------------------------------------------ Crossref (swagger Work)
CROSSREF_EXTRA = {
    "abstract": "<jats:p>An abstract.</jats:p>", "subject": ["Economics"], "funder": [{"name": "F", "DOI": "10.13039/100000001", "award": ["A1"]}],
    "link": [{"URL": "https://example.org/a.pdf", "content-type": "application/pdf", "content-version": "vor", "intended-application": "text-mining"}],
    "alternative-id": ["alt1"], "ISBN": ["9780000000002"], "page": "1-10", "volume": "5", "issue": "2", "language": "en", "short-container-title": ["J."],
    "subtitle": ["S"], "published-print": {"date-parts": [[2021, 3, 1]]}, "published-online": {"date-parts": [[2021, 2]]},
    "issn-type": [{"value": "1234-5679", "type": "print"}], "member": "78", "prefix": "10.1000", "created": DATE, "deposited": DATE, "indexed": DATE,
    "resource": {"primary": {"URL": "https://example.org/a"}}, "editor": [{"given": "E", "family": "D", "sequence": "first", "affiliation": []}],
    "container-title": ["J"], "score": 1.0, "source": "Crossref", "archive": ["Portico"], "update-policy": "https://doi.org/10.1000/up",
    "content-domain": {"domain": ["example.org"], "crossmark-restriction": False}, "journal-issue": {"issue": "2", "published-print": {"date-parts": [[2021, 3]]}},
    "free-to-read": {"start-date": {"date-parts": [[2021, 3, 1]]}}, "relation": {}, "subtype": "preprint",
}


def crossref_work(w: dict) -> dict:
    w = merge(w, CROSSREF_EXTRA)
    w["author"] = [merge(a, {"sequence": "first", "affiliation": [{"name": "U"}], "ORCID": "https://orcid.org/0000-0002-1825-0097",
                              "authenticated-orcid": False}) for a in w["author"]]
    w["license"] = [merge(x, {"start": DATE, "delay-in-days": 0, "content-version": "vor"}) for x in w["license"]]
    return w


def crossref_reference(r: dict) -> dict:
    return merge(r, {"key": "ref1", "doi-asserted-by": "publisher", "author": "A", "journal-title": "J", "volume": "1", "first-page": "10"})


# ------------------------------------------------------------------ DataCite
def datacite_attributes(a: dict) -> dict:
    a = merge(a, {
        "subjects": [{"subject": "S", "subjectScheme": "Fields of Science"}], "dates": [{"date": "2021-05-01", "dateType": "Issued"}], "language": "en",
        "version": "1", "descriptions": [{"description": "d", "descriptionType": "Abstract", "lang": "en"}], "sizes": ["1 MB"], "formats": ["text/csv"],
        "geoLocations": [{"geoLocationPlace": "P"}], "fundingReferences": [{"funderName": "F", "awardNumber": "A1"}],
        "container": {"type": "Series", "title": "C", "identifier": "c-1", "identifierType": "Other"},
        "relatedIdentifiers": [{"relatedIdentifier": "10.1000/other", "relatedIdentifierType": "DOI", "relationType": "References"}],
        "contributors": [{"name": "C", "nameType": "Personal", "contributorType": "Editor"}],
        "alternateIdentifiers": [{"alternateIdentifier": "alt", "alternateIdentifierType": "Other"}],
    })
    a["creators"] = [merge(c, {"nameType": "Personal", "affiliation": [{"name": "U"}], "nameIdentifiers": [
        {"nameIdentifier": "https://orcid.org/0000-0002-1825-0097", "nameIdentifierScheme": "ORCID", "schemeUri": "https://orcid.org"}]}) for c in a["creators"]]
    # 2b-repair-11a (R10-1): BOTH documented ways of stating the rights are populated, `rightsIdentifier` (already in the fixture) beside `rights` and `rightsUri`
    a["rightsList"] = [merge(r, {"rights": "CC0 1.0 Universal", "rightsUri": "https://creativecommons.org/publicdomain/zero/1.0/", "rightsIdentifierScheme": "SPDX",
                                 "lang": "en"}) for r in a["rightsList"]]
    return a


def datacite_item(item: dict) -> dict:
    return merge({**item, "attributes": datacite_attributes(item["attributes"])}, {"type": "dois"})


# ------------------------------------------------------------------ DOAJ
def doaj_article(a: dict) -> dict:
    b = merge(a["bibjson"], {
        "abstract": "An abstract.", "keywords": ["k"], "month": "3", "subject": [{"scheme": "LCC", "term": "Economics", "code": "HB"}],
        "link": [{"type": "fulltext", "url": "https://example.org/j/full", "content_type": "HTML"}],
        "journal": {"country": "GB", "language": ["EN"], "number": "2", "publisher": "P", "start_page": "1", "end_page": "9", "volume": "5"},
    })
    b["author"] = [merge(x, {"affiliation": "U", "orcid_id": "https://orcid.org/0000-0002-1825-0097"}) for x in b["author"]]
    return {**a, "bibjson": b, "created_date": "2021-03-01T00:00:00Z", "last_updated": "2021-03-02T00:00:00Z"}


def doaj_journal(j: dict) -> dict:
    b = merge(j["bibjson"], {
        "eissn": "2345-6786", "pissn": "1234-5679", "alternative_title": "Alt", "keywords": ["k"], "language": ["EN"], "boai": True, "oa_start": 2010,
        "publication_time_weeks": 4, "labels": ["l"], "replaces": [], "is_replaced_by": [],
        "ref": {"journal": "https://example.org/journal", "aims_scope": "https://example.org/aims", "author_instructions": "https://example.org/authors",
                "license_terms": "https://example.org/terms", "oa_statement": "https://example.org/oa"},
        "institution": {"country": "GB", "name": "Inst"}, "apc": {"has_apc": True, "max": [{"currency": "USD", "price": 100}], "url": "https://example.org/apc"},
        "copyright": {"author_retains": True, "url": "https://example.org/copyright"}, "waiver": {"has_waiver": False},
        "other_charges": {"has_other_charges": False}, "editorial": {"review_process": ["Peer review"], "review_url": "https://example.org/review"},
        "plagiarism": {"detection": True, "url": "https://example.org/plagiarism"}, "preservation": {"has_preservation": True, "service": ["Portico"]},
        "deposit_policy": {"has_policy": True, "service": ["Sherpa Romeo"]}, "pid_scheme": {"has_pid_scheme": True, "scheme": ["DOI"]},
    })
    b["publisher"] = merge(b["publisher"], {"country": "GB"})
    b["subject"] = [merge(s, {"scheme": "LCC", "code": "HB"}) for s in b["subject"]]
    return {**j, "bibjson": b, "created_date": "2021-03-01T00:00:00Z", "last_updated": "2021-03-02T00:00:00Z"}


# ------------------------------------------------------------------ Europe PMC (lite result), GovInfo, Dataverse, Hugging Face, Kaggle, Socrata
def epmc_record(r: dict) -> dict:
    return merge(r, {"pmcid": "PMC1", "journalIssn": "1234-5679", "journalVolume": "5", "issue": "2", "pageInfo": "1-10", "pubType": "journal article",
                     "isOpenAccess": "Y", "inEPMC": "Y", "inPMC": "Y", "hasPDF": "Y", "hasBook": "N", "hasSuppl": "N", "citedByCount": 3,
                     "hasReferences": "Y", "hasTextMinedTerms": "N", "hasDbCrossReferences": "N", "hasLabsLinks": "N", "license": "cc by",
                     "firstIndexDate": "2021-03-01", "firstPublicationDate": "2021-03-01"})


def govinfo_package(p: dict) -> dict:
    return merge(p, {"governmentAuthor2": "Senate", "dateIngested": "2023-02-02", "lastModified": "2023-02-03T00:00:00Z", "documentType": "Report",
                     "resultLink": "https://api.govinfo.gov/packages/x/summary", "congress": "118", "docClass": "CRPT",
                     "download": {"txtLink": "https://api.govinfo.gov/packages/x/txt", "xmlLink": "https://api.govinfo.gov/packages/x/xml",
                                  "premisLink": "https://api.govinfo.gov/packages/x/premis", "modsLink": "https://api.govinfo.gov/packages/x/mods"}})


def govinfo_summary(p: dict) -> dict:
    return merge(p, {"governmentAuthor1": "House", "governmentAuthor2": "Senate", "dateIngested": "2023-02-02", "lastModified": "2023-02-03T00:00:00Z",
                     "category": "Reports", "congress": "118", "docClass": "CRPT", "branch": "legislative", "publisher": "GPO", "pages": "10",
                     "suDocClassNumber": "Y 1.1/8:118-1", "documentType": "Report", "committees": [{"committeeName": "C", "chamber": "HOUSE"}]})


def dataverse_hit(h: dict) -> dict:
    return merge(h, {"type": "dataset", "description": "d", "publisher": "Harvard Dataverse", "citation": "c", "identifier_of_dataverse": "d",
                     "name_of_dataverse": "D", "storageIdentifier": "s3://x", "versionId": 1, "versionState": "RELEASED", "createdAt": "2021-05-01T00:00:00Z",
                     "updatedAt": "2021-05-02T00:00:00Z", "contacts": [{"name": "C", "affiliation": "U"}], "publications": [{"citation": "p", "url": "https://example.org/p"}]})


def dataverse_dataset(d: dict) -> dict:
    out = merge(d, {"data": {"protocol": "doi", "publicationDate": "2021-05-01", "storageIdentifier": "s3://x",
                             "latestVersion": {"datasetId": 42, "datasetPersistentId": "doi:10.7910/DVN/X1", "versionState": "RELEASED", "createTime": "2021-05-01T00:00:00Z",
                                               "lastUpdateTime": "2021-05-02T00:00:00Z", "termsOfUse": "CC0 Waiver", "fileAccessRequest": False}}})
    return out


def dataverse_file(f: dict) -> dict:
    return merge(f, {"description": "d", "version": 1, "datasetVersionId": 7, "categories": ["Data"], "directoryLabel": "dir",
                     "dataFile": {"persistentId": "", "description": "d", "originalFileFormat": "text/csv", "originalFileSize": 12, "md5": "d41d8cd98f00b204e9800998ecf8427e",
                                  "checksum": {"type": "MD5", "value": "d41d8cd98f00b204e9800998ecf8427e"}, "tabularData": False, "rootDataFileId": -1,
                                  "creationDate": "2021-05-01", "publicationDate": "2021-05-01"}})


def hf_dataset(d: dict) -> dict:
    return merge(d, {"_id": "abc", "sha": "0" * 40, "private": False, "disabled": False, "downloads": 5, "likes": 1, "createdAt": "2026-01-01T00:00:00Z",
                     "description": "d", "citation": "c", "paperswithcode_id": None,
                     "cardData": {"language": ["en"], "pretty_name": "Pretty", "size_categories": ["n<1K"], "task_categories": ["text-classification"],
                                  "tags": ["t"], "annotations_creators": ["found"]}})


def kaggle_dataset(d: dict) -> dict:
    return merge(d, {"id": 1, "subtitle": "s", "creatorName": "C", "creatorUrl": "c", "url": "https://www.kaggle.com/datasets/o/d", "downloadCount": 5,
                     "isPrivate": False, "isFeatured": False, "licenseName": "CC0: Public Domain", "description": "d", "ownerRef": "o", "kernelCount": 0,
                     "topicCount": 0, "viewCount": 9, "voteCount": 1, "currentVersionNumber": 1, "usabilityRating": 0.9, "tags": [{"ref": "t", "name": "T"}]})


def kaggle_file(f: dict) -> dict:
    return merge(f, {"ref": "o/d/f", "creationDate": "2026-01-01T00:00:00Z", "description": "d"})


def socrata_hit(h: dict) -> dict:
    return merge(h, {"resource": {"description": "d", "attribution": "A", "attribution_link": "https://example.org/a", "createdAt": "2020-01-01T00:00:00Z",
                                  "metadata_updated_at": "2026-01-04T00:00:00Z", "data_updated_at": "2026-01-04T00:00:00Z", "download_count": 5,
                                  "columns_name": ["a"], "columns_field_name": ["a"], "columns_datatype": ["Text"], "columns_description": [""], "page_views": {"page_views_total": 1}},
                     "classification": {"categories": ["C"], "tags": ["t"], "domain_category": "D", "domain_tags": ["t"]},
                     "link": "https://data.example.gov/d/abcd", "owner": {"id": "xxxx-yyyy", "user_type": "interactive", "display_name": "O"}})


def socrata_view(v: dict) -> dict:
    return merge(v, {"category": "C", "tags": ["t"], "createdAt": 1600000000, "viewCount": 5, "downloadCount": 2, "attributionLink": "https://example.org/a",
                     "licenseId": "PDDL", "publicationDate": 1600000001, "owner": {"id": "xxxx-yyyy", "displayName": "O"}})


# ------------------------------------------------------------------ OpenAIRE, OpenML, Semantic Scholar, citations, OA locations
def openaire_product(p: dict) -> dict:
    out = merge(p, {"subTitle": "S", "descriptions": ["d"], "publisher": "P", "language": {"code": "eng", "label": "English"}, "openAccessColor": "gold",
                    "publiclyFunded": False, "isGreen": False, "isInDiamondJournal": False, "version": "1", "size": "1MB", "formats": ["pdf"], "sources": ["s"],
                    "countries": [{"code": "GB", "label": "United Kingdom"}], "subjects": [{"subject": {"scheme": "keyword", "value": "k"}}],
                    "bestAccessRight": {"code": "c_abf2", "label": "OPEN", "scheme": "http://vocabularies.coar-repositories.org/documentation/access_rights/"},
                    "container": {"name": "J", "issnPrinted": "1234-5679", "vol": "5", "iss": "2", "sp": "1", "ep": "9"},
                    "originalIds": ["o1"], "dateOfCollection": "2024-05-02", "lastUpdateTimeStamp": 1714600000,
                    "indicators": {"citationImpact": {"citationCount": 2}, "usageCounts": {"downloads": "5", "views": "7"}}})
    out["authors"] = [merge(a, {"name": "A", "surname": "Z", "rank": 1}) for a in out["authors"]]
    out["instances"] = [merge(i, {"accessRight": {"code": "c_abf2", "label": "OPEN"}, "type": "Article", "refereed": "peerReviewed", "publicationDate": "2024-05-01"})
                        for i in out["instances"]]
    return out


def openml_description(d: dict) -> dict:
    """The documented fields (Api_data.php example). The licence stays as it was: the variants below decide how it is spelled."""
    return merge(d, {"data_set_description": {"description": "d", "file_id": "61", "default_target_attribute": "class", "version_label": "1",
                                              "tag": ["study_1", "uci"], "visibility": "public", "original_data_url": "https://www.openml.org/d/61", "status": "active",
                                              "md5_checksum": "d01f6ccd68c88b749b20bbe897de3713", "language": "English", "collection_date": "1936",
                                              "citation": "Fisher, R.A.", "contributor": "C", "row_id_attribute": "row", "ignore_attribute": ["x"]}})


def openml_both_spellings(d: dict) -> dict:
    return merge(openml_description(d), {"data_set_description": {"license": "CC0-1.0"}})


def openml_us_spelling_only(d: dict) -> dict:
    body = openml_description(d)
    desc = body["data_set_description"]
    desc["license"] = desc.pop("licence")
    return body


def openml_listing_item(m: dict) -> dict:
    """The listing's documented fields (Api_data.php, data/list: did, name, status, format, quality) and `licence`, the spelling OpenML uses in a
    dataset's description. The list example omits it; the adapter reads it from the item (R9-2)."""
    return merge(m, {"version": 1, "status": "active", "md5_checksum": "d01f6ccd68c88b749b20bbe897de3713", "format": "ARFF", "licence": "Public",
                     "quality": [{"name": "NumberOfInstances", "value": "150"}, {"name": "NumberOfFeatures", "value": "5"}]})


def openml_listing_both(m: dict) -> dict:
    return merge(openml_listing_item(m), {"license": "CC0-1.0"})


def openml_listing_us_only(m: dict) -> dict:
    out = openml_listing_item(m)
    out["license"] = out.pop("licence")
    return out


def s2_paper(p: dict) -> dict:
    out = merge(p, {"corpusId": 1, "url": "https://www.semanticscholar.org/paper/p", "abstract": "a", "referenceCount": 1, "citationCount": 2,
                    "influentialCitationCount": 0, "isOpenAccess": True, "openAccessPdf": {"url": "https://example.org/p.pdf", "status": "GREEN"},
                    "fieldsOfStudy": ["Economics"], "s2FieldsOfStudy": [{"category": "Economics", "source": "external"}], "publicationTypes": ["JournalArticle"],
                    "publicationDate": "2021-03-01", "journal": {"name": "V", "pages": "1-10", "volume": "5"},
                    "publicationVenue": {"id": "v1", "name": "V", "type": "journal", "alternate_names": ["Vv"], "url": "https://example.org/v"},
                    "tldr": {"model": "tldr@v2.0.0", "text": "t"}})
    out["externalIds"] = merge(out["externalIds"], {"ArXiv": "2101.00001", "PubMed": "1", "CorpusId": 1})
    out["authors"] = [merge(a, {"authorId": "a1"}) for a in out["authors"]]
    return out


def s2_link(link: dict) -> dict:
    return {k: s2_paper_lite(v) if isinstance(v, dict) else v for k, v in {**link, "contexts": ["c"], "intents": ["background"], "isInfluential": False}.items()}


def s2_paper_lite(p: dict) -> dict:
    return merge(p, {"corpusId": 2, "url": "https://www.semanticscholar.org/paper/c", "referenceCount": 1, "citationCount": 2, "isOpenAccess": False,
                     "authors": [{"authorId": "a1", "name": "A"}]})


def oc_row(r: dict) -> dict:
    return merge(r, {"journal_sc": "no", "author_sc": "no"})


def oc_meta(r: dict) -> dict:
    return merge(r, {"id": "doi:10.1000/a1 omid:br/1", "issue": "2", "volume": "5", "page": "1-10", "type": "journal article", "publisher": "P",
                     "editor": "", "venue": "V"})


def unpaywall_location(loc: dict) -> dict:
    return merge(loc, {"evidence": "oa journal (via doaj)", "host_type": "publisher", "is_best": True, "oa_date": "2021-03-01", "pmh_id": None, "repository_institution": None,
                       "updated": "2021-03-02T00:00:00", "url_for_landing_page": "https://example.org/landing", "license": "cc-by", "version": "publishedVersion"})


def unpaywall_record(r: dict) -> dict:
    out = merge(r, {"doi_url": "https://doi.org/10.1000/a1", "genre": "journal-article", "has_repository_copy": False, "journal_is_in_doaj": True, "journal_is_oa": True,
                    "journal_issns": "1234-5679", "journal_issn_l": "1234-5679", "published_date": "2021-03-01", "publisher": "P", "updated": "2021-03-02T00:00:00",
                    "z_authors": [{"given": "A", "family": "B"}]})
    out["oa_locations"] = [unpaywall_location(x) for x in out["oa_locations"]]
    out["best_oa_location"] = unpaywall_location(out["best_oa_location"])
    return out


def core_work(w: dict) -> dict:
    return merge(w, {"abstract": "a", "createdDate": "2021-03-01T00:00:00", "updatedDate": "2021-03-02T00:00:00", "language": {"code": "en", "name": "English"},
                     "documentType": "research", "citationCount": 2, "fieldOfStudy": "Economics", "journals": [{"title": "J", "identifiers": ["issn:1234-5679"]}],
                     "links": [{"type": "download", "url": "https://example.org/a1.pdf"}], "publishedDate": "2021-03-01T00:00:00", "tags": ["t"]})


# ------------------------------------------------------------------ statistical sources and their catalogues
def bls_series(s: dict) -> dict:
    out = merge(s, {"catalog": {"area": "US", "item": "All items", "seasonality": "Not Seasonally Adjusted", "periodicity": "Monthly"}})
    out["data"] = [merge(x, {"periodName": "July", "latest": "true", "footnotes": [{}]}) for x in out["data"]]
    return out


def fred_series(b: dict) -> dict:
    return merge(b, {"realtime_start": "2026-01-01", "realtime_end": "2026-01-01", "observation_start": "1947-01-01", "observation_end": "2026-01-01",
                     "frequency_short": "Q", "units_short": "B", "seasonal_adjustment": "Seasonally Adjusted Annual Rate", "seasonal_adjustment_short": "SAAR",
                     "last_updated": "2026-01-01 08:00:00-06", "popularity": 90})


def fred_observations(b: dict) -> dict:
    out = merge(b, {"realtime_start": "2026-01-01", "realtime_end": "2026-01-01", "units": "lin", "output_type": 1, "file_type": "json", "count": 2})
    out["observations"] = [merge(o, {"realtime_start": "2026-01-01", "realtime_end": "2026-01-01"}) for o in out["observations"]]
    return out


def bea_results(b: dict) -> dict:
    out = copy.deepcopy(b)
    res = out["BEAAPI"]["Results"]
    res.setdefault("Statistic", "NIPA Table")
    res.setdefault("UTCProductionTime", "2026-01-01T00:00:00.000")
    res.setdefault("Dimensions", [{"Ordinal": "1", "Name": "TableName", "DataType": "string", "IsValue": "0"}])
    out["BEAAPI"]["Request"] = {"RequestParam": [{"ParameterName": "RESULTFORMAT", "ParameterValue": "JSON"}]}
    for row in res.get("Data", []):
        row.update({"CL_UNIT": "Level", "UNIT_MULT": "6", "LineNumber": "1", "METRIC_NAME": "Current Dollars", "NoteRef": "T10101"})
    return out


def sdmx_structure_attributes(body: dict) -> dict:
    out = copy.deepcopy(body)
    out["header"] = {"id": "1", "test": False, "prepared": "2026-09-01T00:00:00.000+00:00", "sender": {"id": "ECB"}}
    out["structure"]["attributes"] = {"dataSet": [], "series": [{"id": "UNIT", "name": "Unit", "values": [{"id": "USD"}]}],
                                     "observation": [{"id": "OBS_STATUS", "name": "Status", "values": [{"id": "A"}]}]}
    out["structure"]["name"] = "Exchange Rates"
    return out


def bea_dataset_entry(e: dict) -> dict:
    return merge(e, {"DatasetDescription": "d", "Note": "n"})


def census_dataset_entry(e: dict) -> dict:
    return merge(e, {"c_isAggregate": True, "c_isMicrodata": False, "c_isTimeseries": False, "c_isAvailable": True, "identifier": "https://api.census.gov/data/2022/acs",
                     "description": "d", "distribution": [{"accessURL": "https://api.census.gov/data/2022/acs/acs1"}], "contactPoint": {"fn": "C", "hasEmail": "mailto:c@example.gov"},
                     "publisher": {"name": "Census"}, "spatial": "United States", "temporal": "2022/2022", "vintage": "2022", "bureauCode": ["006:07"],
                     "programCode": ["006:004"], "accessLevel": "public", "modified": "2023-09-01", "keyword": ["acs"], "license": "https://creativecommons.org/publicdomain/zero/1.0/"})


def bea_parameter(p: dict) -> dict:
    return merge(p, {"ParameterIsRequiredFlag": "1", "ParameterDefaultValue": "", "MultipleAcceptedFlag": "0", "AllValue": "", "ParameterDataType": "string"})


def bea_value_entry(v: dict) -> dict:
    """GetParameterValues: `Key` and `Desc` (BEA API user guide, p.10-12). `Description` is the alternative the gateway reads beside `Desc` (R10-1)."""
    return merge(v, {"Description": v["Desc"]})


def census_variable(v: dict) -> dict:
    return merge(v, {"concept": "SEX BY AGE", "group": "B01001", "limit": 0, "attributes": "B01001_001EA,B01001_001M", "predicateType": "int", "required": "false"})


# ------------------------------------------------------------------ assembling the variants
BASE_OF: dict = {}          # variant name -> the name of the operation it populates


def populated(op, fn, suffix: str = "populated", **changes):
    """`op` with the answer it corrupts passed through `fn` (the other routes stay as they were)."""
    variant = replace(op, name=f"{op.name} ({suffix})", routes=tuple(replace(r, body=fn(r.body)) if r.corrupt else r for r in op.routes), **changes)
    BASE_OF[variant.name] = op.name
    return variant


def build(ops) -> dict:
    """`ops` is tests.invariant_ops. Returns {"find": (...), "resolve": (...), "enrich": (...), "data": (...), "fetch": (...), "catalog": (...)}."""
    find = (
        populated(ops.CROSSREF_FIND_MORE, lambda b: at(each(b, ("message", "items"), crossref_work), ("message",), lambda m: merge(m, {"items-per-page": 3, "query": {"start-index": 0, "search-terms": "q"}}))),
        populated(ops.CROSSREF_FIND_END, lambda b: each(b, ("message", "items"), crossref_work)),
        populated(ops.DATACITE_FIND_MORE, lambda b: each(b, ("data",), datacite_item)),
        populated(ops.DATACITE_FIND_END, lambda b: each(b, ("data",), datacite_item)),
        populated(ops.DOAJ_FIND_MORE, lambda b: each(b, ("results",), doaj_article)),
        populated(ops.DOAJ_FIND_END, lambda b: each(b, ("results",), doaj_article)),
        populated(ops.EPMC_FIND, lambda b: each(b, ("resultList", "result"), epmc_record)),
        populated(ops.GOVINFO_FIND, lambda b: each(b, ("results",), govinfo_package)),
        populated(ops.DV_FIND_MORE, lambda b: each(b, ("data", "items"), dataverse_hit)),
        populated(ops.DV_FIND_END, lambda b: each(b, ("data", "items"), dataverse_hit)),
        populated(ops.HF_FIND_MORE, lambda b: each(b, (), hf_dataset)),
        populated(ops.HF_FIND_END, lambda b: each(b, (), hf_dataset)),
        populated(ops.KAGGLE_FIND, lambda b: each(b, (), kaggle_dataset)),
        populated(ops.OPENAIRE_FIND_MORE, lambda b: each(b, ("results",), openaire_product)),
        populated(ops.OPENAIRE_FIND_END, lambda b: each(b, ("results",), openaire_product)),
        populated(ops.OPENML_FIND_MORE, lambda b: each(b, ("data", "dataset"), openml_listing_item)),
        populated(ops.OPENML_FIND_MORE, lambda b: each(b, ("data", "dataset"), openml_listing_both), "licence and license"),
        populated(ops.OPENML_FIND_MORE, lambda b: each(b, ("data", "dataset"), openml_listing_us_only), "license only"),
        populated(ops.OPENML_FIND_END, lambda b: each(b, ("data", "dataset"), openml_listing_item)),
        populated(ops.S2_FIND_MORE, lambda b: each(b, ("data",), s2_paper)),
        populated(ops.S2_FIND_END, lambda b: each(b, ("data",), s2_paper)),
        populated(ops.SOCRATA_FIND_MORE, lambda b: each(b, ("results",), socrata_hit)),
        populated(ops.SOCRATA_FIND_END, lambda b: each(b, ("results",), socrata_hit)),
    )
    resolve = (
        populated(ops.CROSSREF_RESOLVE, lambda b: at(b, ("message",), crossref_work)),
        populated(ops.DATACITE_RESOLVE, lambda b: at(b, ("data",), datacite_item)),
        populated(ops.OPENAIRE_RESOLVE, lambda b: each(b, ("results",), openaire_product)),
        populated(ops.DOAJ_RESOLVE, lambda b: each(b, ("results",), doaj_journal)),
        populated(ops.EPMC_RESOLVE, lambda b: each(b, ("resultList", "result"), epmc_record)),
        populated(ops.HF_RESOLVE, hf_dataset),
        populated(ops.OPENML_RESOLVE, openml_description, "populated"),
        populated(ops.OPENML_RESOLVE, openml_both_spellings, "licence and license"),
        populated(ops.OPENML_RESOLVE, openml_us_spelling_only, "license only"),
        populated(ops.S2_RESOLVE, s2_paper),
        populated(ops.SOCRATA_RESOLVE, socrata_view),
        populated(ops.GOVINFO_RESOLVE, govinfo_summary),
    )
    enrich = (
        populated(ops.CROSSREF_REFERENCES, lambda b: each(b, ("message", "reference"), crossref_reference)),
        populated(ops.S2_CITATIONS, lambda b: each(b, ("data",), s2_link)),
        populated(ops.S2_REFERENCES, lambda b: each(b, ("data",), s2_link)),
        populated(ops.OC_CITATIONS, lambda b: each(b, (), oc_row)),
        populated(ops.OC_REFERENCES, lambda b: each(b, (), oc_row)),
        populated(ops.OC_METADATA, lambda b: each(b, (), oc_meta)),
        populated(ops.UNPAYWALL, unpaywall_record),
        populated(ops.CORE_FULL_TEXT, lambda b: each(b, ("results",), core_work)),
    )
    data = (
        populated(ops.BLS_DATA, lambda b: each(b, ("Results", "series"), bls_series)),
        populated(ops.ECB_DATA, sdmx_structure_attributes),
        populated(ops.ECB_DATA_ONE, sdmx_structure_attributes),
        populated(ops.FRED_OBS, fred_observations),
        populated(ops.FRED_META, lambda b: each(b, ("seriess",), fred_series)),
        populated(ops.BEA_GETDATA, bea_results),
        populated(ops.BEA_LIST, bea_results),
    )
    fetch = (
        populated(ops.DV_FETCH, lambda b: at(at(b, ("data", "latestVersion", "files"), lambda fl: [dataverse_file(f) for f in fl]), (), dataverse_dataset)),
        populated(ops.HF_FETCH, hf_dataset),
        populated(ops.KAGGLE_FETCH, lambda b: each(b, ("datasetFiles",), kaggle_file)),
        populated(ops.GOVINFO_FETCH, govinfo_summary),
    )
    # Not in the harness's tuples: the harness's seeded mixed-member case (MixedMembers) fails for `openml.fetch` at most seeds and passes at its committed one by
    # the luck of the draw, and the gateway's mutation run needs that case green on the unmutated tree. These run through tests/test_oracle.py instead
    # (`MixedMembersOtherSeeds` is where the disagreement is reported).
    outside = (
        populated(ops.OPENML_FETCH, openml_description, "populated"),
        populated(ops.OPENML_FETCH, openml_both_spellings, "licence and license"),
        populated(ops.OPENML_FETCH, openml_us_spelling_only, "license only", shared=(("data_set_description", "id"),)),
    )
    catalog = (
        populated(ops.BEA_CATALOG, lambda b: each(b, ("BEAAPI", "Results", "Dataset"), bea_dataset_entry)),
                populated(ops.CENSUS_CATALOG, lambda b: each(b, ("dataset",), census_dataset_entry)),
        populated(ops.FRED_CATALOG, lambda b: each(b, ("seriess",), fred_series)),
        populated(ops.FRED_SERIES_ENTRY, lambda b: each(b, ("seriess",), fred_series)),
        populated(ops.BEA_PARAMETERS, lambda b: each(b, ("BEAAPI", "Results", "Parameter"), bea_parameter)),
        populated(ops.BEA_VALUES, lambda b: each(b, ("BEAAPI", "Results", "ParamValue"), bea_value_entry)),
        populated(ops.CENSUS_VARIABLES, lambda b: {**b, "variables": {k: census_variable(v) for k, v in b["variables"].items()}}),
    )
    return {"find": find, "resolve": resolve, "enrich": enrich, "data": data, "fetch": fetch, "catalog": catalog, "outside the harness": outside}


# What a populated variant adds to its base operation's expectations (expected_records.EXPECTED, by the base's name): nothing a base field depends on,
# plus the licence a documented field carries. {variant name: {identity: {field: (value, source tag)}}}
# and what it does not inherit: {variant name: {identity: (fields)}}: the base's field rests on a source that does not cover the variant's spelling
NOT_INHERITED = {
    "openml.resolve (license only)": {"openml:61": ("license",)},
}
LISTING_LICENCE = ("licence", "Public", "judgement: `licence` is OpenML's spelling (Api_data.php, a dataset's description); the list example omits it, the listing item can carry it")
EXTRA_EXPECTED = {
    **{name: {f"openml:{60 + i}": {"license": ("Public", LISTING_LICENCE[2])} for i in range(1, n + 1)}
       for name, n in (("openml.find (a full page) (populated)", 3), ("openml.find (a full page) (licence and license)", 3), ("openml.find (a short page) (populated)", 2))},
    **{f"kaggle.find (populated)": {f"kaggle:o/d{i}": {"license": ("CC0: Public Domain", "schema: ApiDataset.licenseName (kagglesdk)")} for i in (1, 2, 3)}},
    "openml.resolve (licence and license)": {"openml:61": {"license": ("Public", "contract: OpenML documents `licence` (Api_data.php); the US spelling is beside it, not instead")}},
}
