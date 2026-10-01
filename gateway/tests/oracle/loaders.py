"""Registry-loader records: valid provider pages and the venue and repository records the Tier 0 index must receive (task 2b-repair-10a, R9-4).

The loaders (`harvest/registries.py`, `harvest/openalex_snapshot.py`) turn a registry's rows into canonical venue and repository records. The
harness corrupts their PAGING (RegistryLoaders); nothing ever said what a valid row must become. Written from:

  * PLAN.md §8 and D-19: one record per identity: `issn:<ISSN-L>` when there is one, else `issn:<first ISSN>`, else `venue:` / `repository:<registry>:<id>`;
    `venue` and `repository` are record kinds; the index holds names, publisher, identifiers, subjects and country;
  * the providers' schemas: Crossref swagger `Journal`, DataCite OpenAPI `RepositoryResponse` (captured in private/evidence/2b-repair-7/docs), and the
    OpenAlex `Source` entity (https://docs.openalex.org/api-entities/sources: NOT captured in the evidence folder, written from the published entity
    description, flagged here and in the report).

A venue record's field for its NAME, its PUBLISHER, its identifiers, subjects and country is documented nowhere I may read (the index text lists "names,
publisher, identifiers, subjects, country" as what the index SEES, which is not a field list), so those are asserted with `Somewhere`: the value must appear in
some field of the record. The kind and the identity are asserted by name (PLAN.md §8). The first version of this file asserted `publisher` by name; that
overclaimed its basis and was corrected after the first comparison (evidence/2b-repair-10a/corrections-after-observation.md).

Left out, with the reason:
  * the DOAJ journals loader: it reads DOAJ's CSV dump (`https://doaj.org/csv`); the CSV's column names are in no document I may read;
  * a Crossref journal with no ISSN: its `venue:` identity's id is undocumented.
ISSNs here are synthetic and valid (checksum): 1234-5679, 2345-6787, 3456-7895.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .expected_records import Somewhere

CROSSREF_FIRST_URL = "https://api.crossref.org/journals?rows=1000&cursor=%2A"     # what the loader asks first (read from the request it makes, not from its code)
DATACITE_FIRST_URL = "https://api.datacite.org/repositories?page%5Bsize%5D=1000&page%5Bnumber%5D=1"

CROSSREF_JOURNALS = {
    "status": "ok", "message-type": "journal-list", "message-version": "1.0.0",
    "message": {"total-results": 2, "items-per-page": 1000, "query": {"start-index": 0, "search-terms": None}, "items": [
        {"title": "Journal of Oracle Studies", "publisher": "Oracle Press", "ISSN": ["1234-5679", "2345-6787"],
         "issn-type": [{"value": "1234-5679", "type": "print"}, {"value": "2345-6787", "type": "electronic"}],
         "subjects": [{"name": "Economics", "ASJC": 2002}], "counts": {"current-dois": 5, "backfile-dois": 10, "total-dois": 15},
         "breakdowns": {"dois-by-issued-year": [[2021, 5], [2020, 10]]}, "flags": {"deposits-articles": True, "deposits": True},
         "coverage": {"licenses-current": 0.5}, "last-status-check-time": 1727740800000},
        {"title": "Annals of Test Science", "publisher": "Test Society", "ISSN": ["3456-7895"], "issn-type": [{"value": "3456-7895", "type": "print"}],
         "subjects": [], "counts": {"current-dois": 1, "backfile-dois": 0, "total-dois": 1}, "breakdowns": {"dois-by-issued-year": [[2021, 1]]},
         "flags": {"deposits-articles": True, "deposits": True}, "coverage": {"licenses-current": 0.0}, "last-status-check-time": 1727740800000}]}}

DATACITE_REPOSITORIES = {
    "data": [
        {"id": "test.repo", "type": "repositories", "attributes": {
            "name": "Example Data Repository", "symbol": "TEST.REPO", "re3data": "10.17616/R3TEST", "opendoar": "1234", "alternateName": "EDR",
            "description": "A repository of example data.", "language": ["en"], "clientType": "repository", "repositoryType": ["disciplinary"],
            "domains": "repo.example.org", "url": "https://repo.example.org", "software": "Dataverse", "subjects": [{"subject": "Economics"}],
            "created": "2020-01-01T00:00:00.000Z", "updated": "2026-01-01T00:00:00.000Z", "isActive": True, "hasPassword": True}},
        {"id": "test.two", "type": "repositories", "attributes": {
            "name": "Second Test Repository", "symbol": "TEST.TWO", "description": "Another.", "language": ["en"], "clientType": "repository",
            "url": "https://two.example.org", "created": "2021-01-01T00:00:00.000Z", "updated": "2026-01-01T00:00:00.000Z", "isActive": True, "hasPassword": True}}],
    "meta": {"total": 2, "totalPages": 1, "page": 1}}

OPENALEX_SOURCES = (
    {"id": "https://openalex.org/S1", "issn_l": "1234-5679", "issn": ["1234-5679", "2345-6787"], "display_name": "Journal of Oracle Studies",
     "abbreviated_title": "J. Oracle Stud.", "alternate_titles": ["JOS"], "host_organization": "https://openalex.org/P1", "host_organization_name": "Oracle Press",
     "type": "journal", "country_code": "GB", "homepage_url": "https://example.org/jos", "works_count": 10, "cited_by_count": 20, "is_oa": True, "is_in_doaj": False,
     "updated_date": "2026-01-01T00:00:00.000000", "created_date": "2020-01-01"},
    {"id": "https://openalex.org/S2", "issn_l": None, "issn": None, "display_name": "Open Test Repository", "type": "repository", "country_code": "US",
     "homepage_url": "https://repo.example.org/open", "works_count": 3, "cited_by_count": 0, "is_oa": True, "is_in_doaj": False,
     "updated_date": "2026-01-01T00:00:00.000000", "created_date": "2020-01-01"},
    {"id": "https://openalex.org/S3", "issn_l": None, "issn": None, "display_name": "Proceedings of the Oracle Conference", "type": "conference",
     "country_code": "DE", "homepage_url": "https://conf.example.org", "works_count": 7, "cited_by_count": 1, "is_oa": False, "is_in_doaj": False,
     "updated_date": "2026-01-01T00:00:00.000000", "created_date": "2020-01-01"},
)


@dataclass(frozen=True)
class Venue:
    name: str                                   # a text the record must carry somewhere; it also finds the record
    kind: str
    identity: str | None = None                 # exact
    identity_prefix: str | None = None          # when the id part is undocumented
    fields: dict = field(default_factory=dict)  # field -> expected (a str, or Somewhere for a field name that is not documented)
    src: str = ""


EXPECTED = {
    "crossref journals": (
        Venue("Journal of Oracle Studies", "venue", "issn:1234-5679", fields={"_publisher": Somewhere("Oracle Press"), "_electronic ISSN": Somewhere("2345-6787"), "_subject": Somewhere("Economics")},
              src="PLAN §8 (issn:<first ISSN>), Crossref swagger Journal.title/publisher/ISSN/subjects"),
        Venue("Annals of Test Science", "venue", "issn:3456-7895", fields={"_publisher": Somewhere("Test Society")}, src="PLAN §8, Crossref swagger Journal"),
    ),
    "datacite repositories": (
        Venue("Example Data Repository", "repository", "repository:datacite:test.repo",
              fields={"_re3data": Somewhere("10.17616/R3TEST"), "_url": Somewhere("https://repo.example.org")},
              src="PLAN §8 (repository:<registry>:<id>; re3data arrives through DataCite's identifiers), DataCite OpenAPI RepositoryResponse"),
        Venue("Second Test Repository", "repository", "repository:datacite:test.two", fields={"_url": Somewhere("https://two.example.org")}, src="PLAN §8, DataCite OpenAPI"),
    ),
    "openalex sources": (
        Venue("Journal of Oracle Studies", "venue", "issn:1234-5679", fields={"_publisher": Somewhere("Oracle Press"), "_electronic ISSN": Somewhere("2345-6787"), "_country": Somewhere("GB")},
              src="PLAN §8 (issn:<ISSN-L>), OpenAlex Source.display_name/host_organization_name/issn/issn_l/country_code"),
        Venue("Open Test Repository", "repository", identity_prefix="repository:", fields={"_country": Somewhere("US")}, src="PLAN §8: no ISSN, a repository"),
        Venue("Proceedings of the Oracle Conference", "venue", identity_prefix="venue:", fields={"_country": Somewhere("DE")}, src="PLAN §8: no ISSN, a conference series is a venue"),
    ),
}


# loaders no case here runs, and why (the coverage registry asserts they did not run, so an exclusion cannot go stale)
NOT_RUN = {
    "doaj_journals": "DOAJ's journals are read from its CSV dump (https://doaj.org/csv); the CSV's column names are in no document the oracle author may read, so no fixture "
                     "was written from documentation; the harness's RegistryLoaders corrupts its paging only",
}
