# Provider pagination: where each find lane's end rule comes from

A find lane is `exhausted` only when its adapter reports, from its source's own evidence, that
nothing remains (STATION-CONTRACT §2). This file records that evidence for every find adapter
(task 2b-repair-7). Each entry gives:

- the continuation the adapter hands back and the rule that produces `exhausted: true`;
- the primary evidence, meaning the provider's official API documentation or provider-owned
  source, with its location, the date it was read, and a short verbatim excerpt;
- what the evidence leaves unsaid, and how the adapter treats it.

Where no primary evidence establishes a terminal signal, the adapter never reports one. Its last
page then has neither a continuation nor an end, and the router makes it a lower bound
(`partial_pagination`).

The offline cases for every rule are in `tests/test_provider_pagination.py`. They use bodies shaped as
each provider documents them, with continuation, end, absent-metadata and cap cases. The evidence was
read on 2026-10-01 (UTC). No provider API was called to establish any of it: the sources are
documentation pages, published specification documents, the providers' documentation repositories, and
provider-owned packages. Whether a live provider still answers as documented is Phase 4 canary
qualification, not this file.

## Local index (`openalex_snapshot`)

The gateway's own store, so no provider is involved. The continuation is `<offset>:<digest>`,
where the digest covers every served match in its total order (rank, works count, year, identity).
The page, the counts and the digest are read in one statement, so they come from one snapshot. A
page whose population no longer has that digest reads nothing and ends nothing
(`ContinuationInvalid`: `provider_unavailable`, `unobserved`, `partial_pagination`). The lane
reports `exhausted` when the page reads fewer rows than `limit + 1`: its one-row lookahead found
nothing past this page, in the population its continuation names.

## Crossref (`crossref`)

- **Continuation:** `next-cursor`. The first request carries `cursor=*`.
- **End:** a page with fewer items than the `rows` requested. Nothing else ends the lane.
- **Evidence:**
  - CrossRef/rest-api-doc `README.md`
    (https://raw.githubusercontent.com/CrossRef/rest-api-doc/master/README.md, read 2026-10-01):
    > Clients should check the number of returned items. If the number of returned items is fewer than the number of expected rows then the end of the result set has been reached. Using `next-cursor` beyond this point will result in responses with an empty items list.

    > A `next-cursor` field will be provided in the JSON response. To get the next page of results, pass the value of `next-cursor` as the `cursor` parameter.
  - Crossref REST API specification (https://api.crossref.org/swagger-docs, read 2026-10-01):
    > Stop sending requests when the number of items in the response is less than the number of `rows` requested.

    > Cursors expire after 5 minutes if not used.
- **Caps:**
  - "The maximum number rows you can ask for in one query is `1000`." (README). The adapter asks
    for at most 100.
  - An expired cursor comes back as an error answer, so the lane is unavailable, never ended.
- **Unsaid:**
  - Whether `total-results` is exact. It ends nothing, so a full first page "holding" the total
    still continues.
  - Whether a short last page carries `next-cursor`. The tips page (crossref.org, read
    2026-10-01) says "Note that our REST API does not return a cursor if there are no further
    results." The short page ends the lane either way.

## DataCite (`datacite`)

- **Continuation:** page number. Page-number paging stops at the documented cap, after which the
  adapter hands back no continuation.
- **End:** the page that reaches `meta.total` (`page × page[size] ≥ total`). An empty page alone
  ends nothing.
- **Evidence:**
  - DataCite support docs, `api-get-lists.md` (https://raw.githubusercontent.com/datacite/support-docs/v1.8/docs/Services%20for%20Integrators%20and%20Harvesters/retrieve-metadata-with-an-api/rest-api/api-get-lists.md,
    read 2026-10-01). The `meta.total` field:
    > Total results count.

    The same description is in the published OpenAPI document (`assets/openapi.yaml`, v1.8).
  - DataCite support docs, `pagination.md` (https://raw.githubusercontent.com/datacite/support-docs/v1.8/docs/Services%20for%20Integrators%20and%20Harvesters/retrieve-metadata-with-an-api/rest-api/pagination.md;
    the same text is at https://support.datacite.org/docs/pagination, read 2026-10-01):
    > Page size can be changed using the `page[size]` query parameter (allowed values in range 0-1000).

    > Only the first 10,000 records (10 x 1000 per page) can be retrieved.
- **Cap:** a next page that would end past record 10,000 is not offered. The lane is then a lower
  bound, not ended. Cursor paging (`page[cursor]`) is documented as uncapped, but this adapter
  does not use it.
- **Unsaid:**
  - Whether `links.next` is absent on the last page. The adapter does not read it.
  - What answer comes past the cap.

## DOAJ (`doaj`)

- **Continuation:** page number, offered only while the next page starts below record 1,000.
- **End:** the page that reaches `total`.
- **Evidence:** DOAJ's narrative API documentation and its OpenAPI document
  (https://doaj.org/api/v4/swagger.json, read 2026-10-01) state the page size limit ("The page size
  limit is 100") but neither the cap nor the end rule. Both come from **provider-owned server
  source**: DOAJ publishes its code, rendered as coverage reports, in its official documentation
  repository, DOAJ/doaj-docs (https://raw.githubusercontent.com/DOAJ/doaj-docs/master/master/coverage/report/z_2f9f1d1c08445246_discovery_py.html
  and `z_53e1fd90b6635ca4_settings_py.html`, read 2026-10-01). This is server source, not client
  or SDK source.
  - The cap:
    > `fro = (page - 1) * page_size`

    > `max_records = app.config.get("DISCOVERY_MAX_RECORDS_SIZE", 1000)`

    > `if fro >= max_records:`

    > `# maximum number of records to return in total (a request for a page starting beyond this number will fail)`
  - The last page:
    > `page_count = ((total - 1) // page_size) + 1`

    > `if requested_page < last_page:`
- **Cap:** a page starting at or past record 1,000 is refused before it is asked, as a capability
  fact. A page whose successor would start at the cap has no continuation, so the lane is a lower
  bound.
- **Unsaid:**
  - Whether production overrides these defaults.
  - Neither the narrative documentation nor the specification states the cap.

## Europe PMC (`europepmc`)

- **Continuation:** `nextCursorMark`, while it differs from the cursor sent. The first request
  carries `cursorMark=*`.
- **End:** none. Europe PMC documents no last page, so this lane never reports `exhausted`. An
  unchanged or missing cursor ends the paging but not the search: the page is a lower bound.
- **Evidence:** the provider's REST specification, `swagger.json`. Europe PMC answers plain HTTP
  clients with a Cloudflare challenge, so these are **Internet Archive copies** of the provider's own
  documents:
  - The specification, capture 2026-04-07
    (https://web.archive.org/web/20260407224517id_/https://www.ebi.ac.uk/europepmc/webservices/api/swagger.json,
    read 2026-10-01):
    > Specify the cursorMark for pagination of the result list. For the first request you can omit the parameter or leave the cursorMark empty or use the default value * (asterisk sign). For every following page use the value of the returned nextCursorMark element.

    > The maximum allowable number of results per page is 1000.
  - The provider's REST release notes (capture 2025-06-27) point to "the Apache Wiki: Pagination of
    Results". That is a third party's description of Solr. The provider's own web service reference
    records "Repository migrated from Oracle/Solr to MongoDB.", so Solr's end-of-cursor rule is not
    taken as Europe PMC's.
- **Unsaid:**
  - What the last page looks like.
  - What `hitCount` counts. It ends nothing.

## GovInfo (`govinfo`)

- **Continuation:** `offsetMark`, while it differs from the mark sent. The first request carries
  `offsetMark: "*"`.
- **End:** none. GovInfo documents no last page, so this lane never reports `exhausted`.
- **Evidence:** GovInfo Search Service overview (https://www.govinfo.gov/features/search-service-overview,
  read 2026-10-01):
  > The starting record requested. For the first request, use * ; subsequent requests should use the value from the offsetMark key in the response.

  > The number of records to return per page. Maximum is 1000
- **Unsaid:**
  - What the last page looks like.
  - What `count` counts. The documented sample answers a two-record page with `"count": 15668`.
    It ends nothing.
  - The specification describes a 404 answer to a search as "No Content found for a given search
    criteria" (https://api.govinfo.gov/govinfoapi/api-docs, read 2026-10-01). It does not say whether
    that means no matches or a page past the end. A 404 therefore stays an unavailable answer, never "no results".

## Harvard Dataverse and QDR (`harvard_dataverse`, `qdr`)

QDR is a Dataverse installation and shares this implementation.

- **Continuation:** page number, translated to `start = (page − 1) × per_page`.
- **End:** the page that reaches `total_count` (`page × per_page ≥ total_count`). Without
  `total_count` there is neither a continuation nor an end.
- **Evidence:** the Dataverse Search API guide, source `doc/sphinx-guides/source/api/search.rst`
  (https://raw.githubusercontent.com/IQSS/dataverse/develop/doc/sphinx-guides/source/api/search.rst,
  rendered at https://guides.dataverse.org/en/latest/api/search.html, read 2026-10-01; the
  iteration text is unchanged in v4.20, v5.14, v6.0 and v6.5):
  > To iterate through many results, increase the ``start`` parameter on each iteration until you reach the ``total_count`` in the response.

  The guide's own loop, verbatim lines:
  > `total = data['data']['total_count']`

  > `start = start + rows`

  > `condition = start < total`
- **Cap:** `per_page` maximum 1000 ("The max is 1000."). The adapter asks for at most 100.
- **Unsaid:**
  - Any cap on `start`.
  - Which Dataverse version each installation runs.

## OpenAIRE (`openaire`)

- **Continuation:** `header.nextCursor`. The first request carries `cursor=*`.
- **End:** either of two conditions:
  - the `nextCursor` returned equals the cursor sent;
  - the first page holds `numFound` results.

  A missing `nextCursor` is neither a continuation nor an end.
- **Evidence:**
  - OpenAIRE Graph API V1 specification
    (https://api.openaire.eu/graph/v3/api-docs/OpenAIRE%20Graph%20API%20V1, schema `SearchHeader`, read
    2026-10-01):
    > nextCursor - to be used in the next request to get the next page of results. You can repeat this process until you’ve fetched as many results as you want, or until the nextCursor returned matches the current cursor you’ve already specified, indicating that there are no more results.
  - OpenAIRE Graph documentation, "Searching entities"
    (https://graph.openaire.eu/docs/apis/graph-api/searching-entities/, read 2026-10-01):
    > numFound : the total number of entities found

    The first-page rule follows from that definition: a page starting at the first result that
    holds `numFound` results holds them all.
- **Cap:** `pageSize` maximum 100 in the specification. The adapter uses cursor paging, which the
  documentation recommends for more than 10,000 records. Offset paging is limited to 10,000.
- **Unsaid:** whether `nextCursor` is ever absent.
- **Recorded, not acted on here:** the specification marks `/v1/researchProducts` **deprecated**
  ("Deprecated: Use version 3.0 instead. This version is no longer supported and will be removed in
  the future."). Moving the adapter to v3 is outside this task. See the task's completion report.

## Semantic Scholar (`semanticscholar`)

- **Continuation:** `next`, the offset of the next batch.
- **End:** `next` absent, short of the 1,000-result cap. At the cap an absent `next` is neither a
  continuation nor an end. `total` ends nothing.
- **Evidence:**
  - Semantic Scholar Academic Graph API specification
    (https://api.semanticscholar.org/graph/v1/swagger.json, read 2026-10-01). From
    `PaperRelevanceSearchBatch`:
    > Starting position of the next batch. Absent if no more data exists.

    > Approximate number of matching search results.

    From the `/paper/search` limitations:
    > Can only return up to 1,000 relevance-ranked results.
  - The provider's API release notes (https://raw.githubusercontent.com/allenai/s2-folks/main/API_RELEASE_NOTES.md,
    read 2026-10-01):
    > As planned, on October 31st we reduced the maximum sum of offset and limit from 10,000 to 1,000 results.
- **Cap:** offset plus returned rows reaching 1,000. `limit` maximum 100 ("Must be <= 100").
- **Unsaid:**
  - Whether `next` is present or absent exactly at the cap.
  - What a request past the cap returns.

## Hugging Face (`huggingface`)

- **Continuation:** the URL in the answer's `Link: <...>; rel="next"` header. It is handed back as the
  lane's continuation and asked verbatim, but only while it stays this search on the Hub's datasets
  listing (`base.own_link`):
  - `https`, on `huggingface.co` at the default port, with path `/api/datasets`;
  - no user info and no fragment;
  - no `search` other than this query.

  The adapter's token travels only in its own `Authorization` header. The first request carries
  `search`, `limit` and `full`, and never an offset.
- **End:** an answer without a next link. A next link that is present is never the end. One the
  gateway may not follow is neither a continuation nor an end, so the lane is a lower bound.
- **Evidence:**
  - Provider-owned client `huggingface_hub` 2.0.0, published by Hugging Face from
    github.com/huggingface/huggingface_hub (PyPI provenance). File `utils/_pagination.py`, read
    2026-10-01. Version 1.29.0, read by the 2b-repair-6 review, has the same logic.
    > This is using the same "Link" header format as GitHub.

    > # Next link already contains query params

    > while next_page is not None:

    > return response.links.get("next", {}).get("url")

    In `hf_api.py` (`list_datasets`), the `limit` only cuts what the client iterates:
    > items = islice(items, limit)  # Do not iterate over all pages
  - Provider-owned JavaScript client, huggingface/huggingface.js
    `packages/hub/src/lib/list-datasets.ts` at commit e016dde7, read 2026-10-01:
    > url = linkHeader ? parseLinkHeader(linkHeader).next : undefined;
  - Hub API documentation, hub-docs `docs/hub/api.md` at commit 4910c3c9
    (https://raw.githubusercontent.com/huggingface/hub-docs/4910c3c90009c5f906da11a89793bc9216f6ec7f/docs/hub/api.md,
    read 2026-10-01). This section was removed on 2025-12-10, when the docs moved to an OpenAPI
    playground that does not describe `/api/datasets`.
    > Get information from all datasets in the Hub. The response is paginated, use the [`Link` header](https://docs.github.com/en/rest/guides/using-pagination-in-the-rest-api?apiVersion=2022-11-28#link-header) to get the next pages. You can specify additional parameters to have more specific results.
- **Unsaid:**
  - The `limit` maximum. The adapter asks for at most 100.
  - The exact form of the next URL for `/api/datasets`. The JavaScript client's documented example
    is for a different endpoint and carries a `cursor` parameter.
