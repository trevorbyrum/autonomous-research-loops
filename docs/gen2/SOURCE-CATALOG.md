# Gen-2 research source catalog

**GENERATED — do not edit by hand.** `tools/gen_source_catalog.py` derives this file and
`deploy/gen2.env.example` from the gateway source registry (`gateway/research_gateway/registry/seed/sources.toml`), which is the one source of
truth. `make gen2-catalog` regenerates both; `make gen2-check` fails if either disagrees with the
registry, so a new source without a regenerated catalog, and a hand edit of either artifact, both
break the build.

**Trace.** Task 0c deliverable 2. `docs/gen2/DEPLOYMENT-CONTRACT.md` §3 (secrets surface, both
backends, the two outage-hardening rules). Flow architecture §4.2 and `docs/gen2/INVARIANTS.md` H-2:
a failed secrets read is a dated `secrets backend failing` capability fact, never "no key
configured" — which is only possible if every secret the stack reads is named in one place.
`docs/gen2/BOUNDARIES.md` *Gateway* (the only door to external research sources; licensing and
provenance fields; coverage vocabulary). Design review §9. `docs/gen2/SOURCE-GOVERNANCE.md` covers
how a source gets *into* the registry.

## How this file is derived

- **Environment variable names** reproduce the gateway's own scheme
  (`gateway/research_gateway/core/secrets.py`, `EnvBackend`): `RESEARCH_GATEWAY_SECRET_<NAME>` with the logical
  secret name upper-cased and `-` replaced by `_`, plus a `_<FIELD>` suffix for the two multi-field
  credentials. The gen-2 stack runs the gateway's own service and keeps its scheme, so the gateway's
  names are the gen-2 names.
- **Which fields a credential has** comes from the registry's `auth` value, checked against the
  adapters that read it. An `auth` value the generator does not know is a build failure, not a
  source emitted without its key.
- **Credential and cost posture** come from `auth` and `rate.cost_cap_per_day`.
- **Lane placement** comes from `base_for` (queried for every request of that kind) and `domains`
  (added for those domains).

## What this catalog does not know

The registry records no **price** and no **paid-tier** field, so this catalog never claims a source
is free or paid. It reports whether a credential is required, optional or absent, and whether a
daily cost cap is recorded. Where a source's own key instructions say registration is free, that
is the source's wording, quoted under *How to get access*.

The registry also records no **redistribution** permission. That question is per record, not per
source (a CC0 metadata record can describe a copyrighted paper), and the gateway answers it per
record: `gateway.record_sources` carries a `redistributable` flag and the content licence beside
each contributing payload. Export bundles rely on that per-record answer, never on this file
(`docs/gen2/EXPORT-API.md`).

## Secrets index (15 variables across 13 secret names)

| Environment variable | Secret name | Requirement | Needed by |
|---|---|---|---|
| `RESEARCH_GATEWAY_SECRET_OPENAIRE_CLIENT_ID` | `openaire` field `client_id` | required | openaire |
| `RESEARCH_GATEWAY_SECRET_OPENAIRE_CLIENT_SECRET` | `openaire` field `client_secret` | required | openaire |
| `RESEARCH_GATEWAY_SECRET_SEMANTIC_SCHOLAR` | `semantic_scholar` | required | semanticscholar |
| `RESEARCH_GATEWAY_SECRET_API_DATA_GOV` | `api_data_gov` | required | govinfo |
| `RESEARCH_GATEWAY_SECRET_HARVARD_DATAVERSE` | `harvard_dataverse` | optional | harvard_dataverse |
| `RESEARCH_GATEWAY_SECRET_SOCRATA` | `socrata` | optional | socrata |
| `RESEARCH_GATEWAY_SECRET_KAGGLE_USERNAME` | `kaggle` field `username` | required | kaggle |
| `RESEARCH_GATEWAY_SECRET_KAGGLE_KEY` | `kaggle` field `key` | required | kaggle |
| `RESEARCH_GATEWAY_SECRET_HUGGINGFACE` | `huggingface` | optional | huggingface |
| `RESEARCH_GATEWAY_SECRET_QDR` | `qdr` | required | qdr |
| `RESEARCH_GATEWAY_SECRET_CORE` | `core` | required | core |
| `RESEARCH_GATEWAY_SECRET_FRED` | `fred` | required | fred |
| `RESEARCH_GATEWAY_SECRET_BEA` | `bea` | required | bea |
| `RESEARCH_GATEWAY_SECRET_CENSUS` | `census` | required | census |
| `RESEARCH_GATEWAY_SECRET_BLS` | `bls` | optional | bls |

11 required, 4 optional. A source whose required credential is absent is a
lane the gateway cannot call: it reports `auth_failed` coverage and a dated capability fact, never
`searched_empty` and never a zero in any count (INVARIANTS RG-4, RG-U).

## Article indexes

### Crossref (`crossref`)

- **Provides:** article records; gateway requests: find, resolve, enrich; identifiers: doi, issn, title
- **Lanes:** **base lane** for article — queried for every request of that kind
- **Credential:** no credential (a contact address in the request, not a secret)
- **How to get access:** No key. Send a contact email in the User-Agent/mailto parameter to join the polite pool.
- **Website:** https://www.crossref.org/ — **API documentation:** https://api.crossref.org/swagger-ui/index.html
- **Rate limit:** 50/s, burst 50 (verified) — Crossref REST API docs: polite pool, no daily cap (https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/)
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Metadata: no rights asserted (facts); reference lists as deposited by publishers.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- **Freshness:** origin registry (publishers deposit here first)
- **Substitution family:** doi-metadata
- **Enabled in the registry's default seed:** yes
- **Notes:** Base lane for articles. Also provides reference lists for citation enrichment fallback.

### Directory of Open Access Journals (DOAJ) (`doaj`)

- **Provides:** article records; gateway requests: find, resolve; identifiers: doi, issn, title
- **Lanes:** **base lane** for article — queried for every request of that kind
- **Credential:** no credential
- **How to get access:** No key for reads (keys are only issued to publishers writing data).
- **Website:** https://doaj.org/ — **API documentation:** https://doaj.org/api/v3/docs
- **Rate limit:** 2/s, burst 5 (verified) — DOAJ API docs: 2 requests/second, bursts of 5; search capped at 1,000 records per query (https://doaj.org/api/v3/docs)
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** CC0 for journal-level and article-level metadata.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://doaj.org/terms/
- **Freshness:** hours to days
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Always added for article discovery: 9-14% of open-access journal articles are in no Crossref-derived index.

### Europe PMC (`europepmc`)

- **Provides:** article records; gateway requests: find, resolve; identifiers: doi, pmid, title
- **Lanes:** **domain lane** added for biomed (an `other`-domain request includes every domain lane)
- **Credential:** no credential
- **How to get access:** No key.
- **Website:** https://europepmc.org/ — **API documentation:** https://europepmc.org/RestfulWebService
- **Rate limit:** 5/s (verified) — no documented limit; 5/s is a self-imposed ceiling. smoke 2026-09-07: one live call answered 200, no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Per article (Creative Commons variants); metadata/abstract reuse not separately stated.
- **Commercial posture:** **per-item** — the platform permits it, but each record carries its own licence; records without an allow-listed licence are dropped in commercial mode. Evidence: https://europepmc.org/Copyright
- **Freshness:** daily
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Biomedical is outside the current research scope; present for completeness. Enable after Phase 3 rate verification.

### OpenAIRE Graph (`openaire`)

- **Provides:** article records; gateway requests: find, resolve; identifiers: doi, title
- **Lanes:** neither a base nor a domain lane: reached through the fallback chain for its capabilities
- **Credential:** credential required (client id + secret, exchanged for bearer tokens); secret name `openaire`; environment `RESEARCH_GATEWAY_SECRET_OPENAIRE_CLIENT_ID`, `RESEARCH_GATEWAY_SECRET_OPENAIRE_CLIENT_SECRET`
- **How to get access:** Create an account at https://develop.openaire.eu, complete Personal Information, then Registered Services → + New Service → Basic → Create. Store the Client ID and Client Secret; the gateway exchanges them for hourly bearer tokens (POST https://aai.openaire.eu/oidc/token, grant_type=client_credentials).
- **Website:** https://graph.openaire.eu/ — **API documentation:** https://graph.openaire.eu/docs/apis/graph-api/
- **Rate limit:** 7200/h (verified) — OpenAIRE API terms: 60/hour unauthenticated, 7,200/hour authenticated (http://graph.openaire.eu/docs/apis/terms/); confirmed from x-ratelimit-limit header 2026-09-07
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** CC-BY; redistributable with attribution to OpenAIRE.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: http://graph.openaire.eu/docs/apis/terms/
- **Freshness:** days to weeks behind Crossref/DataCite
- **Substitution family:** doi-metadata
- **Enabled in the registry's default seed:** yes
- **Notes:** Not a discovery lane (96-99% overlap with Crossref). Fallback for DOI metadata and the only lane for identifier-less repository records.

### OpenAlex (local snapshot only) (`openalex_snapshot`)

- **Provides:** article records; gateway requests: find; identifiers: doi, issn, title
- **Lanes:** **base lane** for article, venue, repository — queried for every request of that kind
- **Credential:** no credential
- **How to get access:** No key. The gateway never calls the OpenAlex API (D-2); it loads the free quarterly S3 snapshot (s3://openalex, anonymous) into the local index.
- **Website:** https://openalex.org/ — **API documentation:** https://help.openalex.org/access/snapshot/
- **Rate limit:** no live calls (verified) — no live calls by decision D-2
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** CC0.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://help.openalex.org/access/snapshot/
- **Freshness:** quarterly (snapshot)
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Served from gateway.index_docs, not from any live call. The index holds the snapshot's VENUES and repositories (D-19), which is how the ~10% of works Crossref lacks are reached: through their venues, not a works index.

### Semantic Scholar (`semanticscholar`)

- **Provides:** article records; gateway requests: find, resolve, enrich; identifiers: doi, arxiv, title
- **Lanes:** **domain lane** added for ai-ml, software (an `other`-domain request includes every domain lane)
- **Credential:** credential required; secret name `semantic_scholar`; environment `RESEARCH_GATEWAY_SECRET_SEMANTIC_SCHOLAR`
- **How to get access:** Request a free API key at https://www.semanticscholar.org/product/api (form; key arrives by email). Send it as the x-api-key header.
- **Website:** https://www.semanticscholar.org/ — **API documentation:** https://api.semanticscholar.org/api-docs/
- **Rate limit:** 1/s (verified) — API docs: 1 request/second per key (https://www.semanticscholar.org/product/api); keyless shared pool throttles to 429
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Mixed: CC BY-NC and ODC-BY depending on the data; third-party content included.
- **Commercial posture:** **deny** — the source's terms forbid commercial use, or require a paid tier. Evidence: https://www.semanticscholar.org/product/api/license
- **Freshness:** daily per partner feed
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Full text (S2ORC) and crawl-discovered papers. Results are never persisted or redistributed (licence).

## Dataset and repository indexes

### DataCite (`datacite`)

- **Provides:** dataset records; gateway requests: find, resolve; identifiers: doi, title
- **Lanes:** **base lane** for dataset — queried for every request of that kind
- **Credential:** no credential
- **How to get access:** No key for reads.
- **Website:** https://datacite.org/ — **API documentation:** https://support.datacite.org/docs/api
- **Rate limit:** 5/s (verified) — no documented limit; 5/s is a self-imposed ceiling. smoke 2026-09-07: one live call answered 200, no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** CC0 (DataCite Data File Use Policy); the waiver does not extend to the linked datasets themselves.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://support.datacite.org/docs/datacite-data-file-use-policy
- **Freshness:** origin registry for dataset DOIs (Zenodo, figshare, institutional repositories)
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Base lane for datasets. Zenodo and figshare records are discovered here with their file links; the gateway returns those links but does not fetch from Zenodo/figshare hosts itself (no registry row owns them; links, not files — I-7).

### GLOBE Project (leadership and culture data) (`globe`)

- **Provides:** dataset records; gateway requests: fetch; identifiers: url
- **Lanes:** **domain lane** added for management (an `other`-domain request includes every domain lane)
- **Credential:** no credential
- **How to get access:** No key; static downloadable files on the data page.
- **Website:** https://globeproject.com/ — **API documentation:** https://globeproject.com/data/
- **Rate limit:** 1/s (**unverified — a conservative default until confirmed**) — static files; 1/s courtesy default
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** No licence text found on the data page.
- **Commercial posture:** **unknown** — no reuse terms could be located; fails closed for commercial-flagged requests. Evidence: https://globeproject.com/data/ (no terms located, 2026-09-07)
- **Freshness:** static release
- **Substitution family:** none
- **Enabled in the registry's default seed:** no — its rate limit is not verified, and the registry keeps unverified sources disabled
- **Notes:** Phase 2 (2004) aggregated societal/leadership scales. Unknown commercial verdict fails closed.

### GovInfo (U.S. Government Publishing Office) (`govinfo`)

- **Provides:** dataset records; gateway requests: find, resolve, fetch; identifiers: package_id, title
- **Lanes:** **domain lane** added for market, finance, management (an `other`-domain request includes every domain lane)
- **Credential:** credential required; secret name `api_data_gov`; environment `RESEARCH_GATEWAY_SECRET_API_DATA_GOV`
- **How to get access:** Get a free key at https://api.data.gov/signup/ (one key works across api.data.gov-hosted APIs). Send it as the X-Api-Key header.
- **Website:** https://www.govinfo.gov/ — **API documentation:** https://api.govinfo.gov/docs/
- **Rate limit:** 36000/h (verified) — X-Ratelimit-Limit: 36000 observed on api.govinfo.gov 2026-09-07 (api.data.gov default is 1,000/hour; GovInfo grants more)
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** U.S. federal public domain (17 U.S.C. 105).
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://www.govinfo.gov/about/policies
- **Freshness:** daily
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** 42 collections of primary federal documents (bills, budgets, reports, regulations).

### Harvard Dataverse (`harvard_dataverse`)

- **Provides:** dataset records; gateway requests: find, resolve, fetch; identifiers: doi, title
- **Lanes:** **domain lane** added for social, management, finance, market (an `other`-domain request includes every domain lane)
- **Credential:** credential optional (raises the documented limits); secret name `harvard_dataverse`; environment `RESEARCH_GATEWAY_SECRET_HARVARD_DATAVERSE`
- **How to get access:** No key needed for public data. An optional API token (account menu → API Token) raises limits and reaches restricted files.
- **Website:** https://dataverse.harvard.edu/ — **API documentation:** https://guides.dataverse.org/en/latest/api/
- **Rate limit:** 5/s (verified) — no documented limit; 5/s is a self-imposed ceiling. smoke 2026-09-07: one live call answered 200 (dataset lookup), no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** CC0 by default; depositors may set another licence per dataset.
- **Commercial posture:** **per-item** — the platform permits it, but each record carries its own licence; records without an allow-listed licence are dropped in commercial mode. Evidence: https://support.dataverse.harvard.edu/harvard-dataverse-general-terms-use (terms let each depositor pick the dataset licence, so commercial use is judged per record, not platform-wide)
- **Freshness:** immediate
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Also hosts the World Management Survey public data (DOI 10.7910/DVN/OY6CBK, CC0).

### Hugging Face Hub (`huggingface`)

- **Provides:** dataset records; gateway requests: find, resolve, fetch; identifiers: repo_id, title
- **Lanes:** **domain lane** added for ai-ml, software (an `other`-domain request includes every domain lane)
- **Credential:** credential optional (raises the documented limits); secret name `huggingface`; environment `RESEARCH_GATEWAY_SECRET_HUGGINGFACE`
- **How to get access:** Optional token: account → Settings → Access Tokens (read scope). Raises rate limits and reaches gated repositories.
- **Website:** https://huggingface.co/ — **API documentation:** https://huggingface.co/docs/hub/api
- **Rate limit:** 100/min (verified) — observed 2026-09-07 header ratelimit-policy: fixed window, 500 requests per 300 s (anonymous) = 100/min; a token raises it
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Per repository; the platform requires the attached licence to be preserved.
- **Commercial posture:** **per-item** — the platform permits it, but each record carries its own licence; records without an allow-listed licence are dropped in commercial mode. Evidence: https://huggingface.co/terms-of-service
- **Freshness:** immediate
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Datasets and models with declared licences.

### Kaggle datasets (`kaggle`)

- **Provides:** dataset records; gateway requests: find, fetch; identifiers: dataset_ref, title
- **Lanes:** **domain lane** added for ai-ml, market, software (an `other`-domain request includes every domain lane)
- **Credential:** credential required (username + key); secret name `kaggle`; environment `RESEARCH_GATEWAY_SECRET_KAGGLE_USERNAME`, `RESEARCH_GATEWAY_SECRET_KAGGLE_KEY`
- **How to get access:** Create an account, then https://www.kaggle.com/settings → API → Create New Token. Store the username and the token; the gateway uses HTTP basic auth.
- **Website:** https://www.kaggle.com/datasets — **API documentation:** https://www.kaggle.com/docs/api
- **Rate limit:** 2/s (verified) — no documented limit; 2/s is a self-imposed ceiling. smoke 2026-09-07: one live call answered 200 (dataset list, basic auth), no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Per dataset (CC, ODC, custom); platform terms restrict use of the service to non-commercial.
- **Commercial posture:** **deny** — the source's terms forbid commercial use, or require a paid tier. Evidence: https://www.kaggle.com/terms
- **Freshness:** immediate
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Personal research use only.

### OpenML (`openml`)

- **Provides:** dataset records; gateway requests: find, resolve, fetch; identifiers: dataset_id, title
- **Lanes:** **domain lane** added for ai-ml (an `other`-domain request includes every domain lane)
- **Credential:** no credential
- **How to get access:** No key for read access.
- **Website:** https://www.openml.org/ — **API documentation:** https://www.openml.org/apis
- **Rate limit:** 5/s (verified) — no documented limit; 5/s is a self-imposed ceiling. smoke 2026-09-07: one live call answered 200, no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Per dataset (declared in metadata); terms page not reachable at review time.
- **Commercial posture:** **per-item** — the platform permits it, but each record carries its own licence; records without an allow-listed licence are dropped in commercial mode. Evidence: https://www.openml.org/ (per-dataset licence field; https://docs.openml.org/terms/ returned 404 on 2026-09-07)
- **Freshness:** immediate
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Machine-learning benchmark datasets, tasks and runs.

### Qualitative Data Repository (QDR) (`qdr`)

- **Provides:** dataset records; gateway requests: find, resolve; identifiers: doi, title
- **Lanes:** **domain lane** added for social, management (an `other`-domain request includes every domain lane)
- **Credential:** credential required; secret name `qdr`; environment `RESEARCH_GATEWAY_SECRET_QDR`
- **How to get access:** Register at https://qdr.syr.edu/user/register, then on data.qdr.syr.edu open your account menu → API Token → Create Token. Sent as the X-Dataverse-key header. Catalog search works without a token.
- **Website:** https://qdr.syr.edu/ — **API documentation:** https://guides.dataverse.org/en/latest/api/
- **Rate limit:** 5/s (verified) — Dataverse instance; no documented limit; 5/s self-imposed. smoke 2026-09-07: one live call answered 200 (search, keyed), no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Per project; standard access terms default to non-commercial and no third-party redistribution.
- **Commercial posture:** **deny** — the source's terms forbid commercial use, or require a paid tier. Evidence: https://qdr.syr.edu/guides/standard-access (default access terms)
- **Freshness:** immediate
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** The only qualitative-data source in the set (interviews, field notes).

### Socrata Open Data Network (SODA) (`socrata`)

- **Provides:** dataset records; gateway requests: find, resolve, fetch; identifiers: dataset_id, title
- **Lanes:** **domain lane** added for market, finance (an `other`-domain request includes every domain lane)
- **Credential:** credential optional (raises the documented limits); secret name `socrata`; environment `RESEARCH_GATEWAY_SECRET_SOCRATA`
- **How to get access:** Optional app token: create an account on any Socrata-hosted portal (e.g. data.cityofchicago.org), Developer Settings → Create New App Token. Anonymous access is throttled.
- **Website:** https://dev.socrata.com/ — **API documentation:** https://dev.socrata.com/docs/endpoints
- **Rate limit:** 1000/h (verified) — dev.socrata.com documents throttling without an app token and 1,000 requests/hour with one. smoke 2026-09-07: one live call answered 200 (discovery API), no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Per publishing agency; many are public domain or Creative Commons.
- **Commercial posture:** **per-item** — the platform permits it, but each record carries its own licence; records without an allow-listed licence are dropped in commercial mode. Evidence: https://dev.socrata.com/ (per-dataset licensing; developer docs themselves CC BY-NC-SA)
- **Freshness:** per portal
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Federated government open-data portals.

### World Management Survey (public data) (`wms`)

- **Provides:** dataset records; gateway requests: fetch; identifiers: doi
- **Lanes:** **domain lane** added for management (an `other`-domain request includes every domain lane)
- **Credential:** no credential
- **How to get access:** No key. The public manufacturing dataset is published on Harvard Dataverse (DOI 10.7910/DVN/OY6CBK); fetched through the Dataverse API.
- **Website:** https://worldmanagementsurvey.org/ — **API documentation:** https://doi.org/10.7910/DVN/OY6CBK
- **Rate limit:** 5/s (verified) — served via Harvard Dataverse under its own row; 5/s self-imposed. smoke 2026-09-07: one live call answered 200 (3 files listed)
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** CC0 1.0 (Dataverse record).
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/OY6CBK (license field, read 2026-09-07)
- **Freshness:** static release
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Establishment-level management-practice scores, 2004-2015.

## Citation graph

### OpenCitations (`opencitations`)

- **Provides:** citation records; gateway requests: enrich; identifiers: doi
- **Lanes:** **base lane** for citation — queried for every request of that kind
- **Credential:** no credential
- **How to get access:** No key (an optional access token helps their usage statistics).
- **Website:** https://opencitations.net/ — **API documentation:** https://api.opencitations.net/
- **Rate limit:** 5/s (verified) — no documented limit; 5/s is a self-imposed ceiling. smoke 2026-09-07: one live call answered 200 (13 references, 6 s latency), no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** CC0.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://opencitations.net/about
- **Freshness:** periodic index builds
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Citation links only, never discovery. Fallback: Crossref reference lists.

## Resolvers and enrichment

### CORE (`core`)

- **Provides:** resolver records; gateway requests: resolve, enrich; identifiers: doi, title
- **Lanes:** neither a base nor a domain lane: reached through the fallback chain for its capabilities
- **Credential:** credential required; secret name `core`; environment `RESEARCH_GATEWAY_SECRET_CORE`
- **How to get access:** Register at https://core.ac.uk/services/api for a free key (personal / unfunded public research only). Sent as a Bearer token.
- **Website:** https://core.ac.uk/ — **API documentation:** https://api.core.ac.uk/docs/v3
- **Rate limit:** 0.5/s, 200/day (verified) — observed 2026-09-06/07: 429s after 50-250 keyed requests; 0.5/s and 200/day are the operating limits, not documented ones. smoke 2026-09-07 headers: x-ratelimit-limit 150 with a retry-after about one minute out (window not stated)
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Metadata under CORE terms; full text per source licence. Bulk datasets are ODC-By.
- **Commercial posture:** **deny** — the source's terms forbid commercial use, or require a paid tier. Evidence: https://core.ac.uk/faq and https://core.ac.uk/services/api: free API access is for individuals in a personal capacity and unfunded public research; commercial use needs a paid licence
- **Freshness:** harvest cadence per repository
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Repository full text. Observed keyed quota blocks after ~50-250 requests; kept as a low-volume personal-only lane (Q-3).

### DOI registration-agency lookup (doi.org) (`doi_org`)

- **Provides:** resolver records; gateway requests: resolve; identifiers: doi
- **Lanes:** neither a base nor a domain lane: reached through the fallback chain for its capabilities
- **Credential:** no credential
- **How to get access:** No key. GET https://doi.org/ra/<doi> returns which agency (Crossref, DataCite, mEDRA, ...) issued the DOI; the gateway caches the answer per DOI prefix.
- **Website:** https://www.doi.org/ — **API documentation:** https://www.doi.org/the-identifier/resources/factsheets/doi-resolution-documentation
- **Rate limit:** 5/s (verified) — public resolver with no published limit; 5/s is a courtesy ceiling and lookups are cached by prefix
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Resolution service; response is a fact (agency name), no content licence applies.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://www.doi.org/the-identifier/resources/factsheets/doi-resolution-documentation (public resolution service)
- **Freshness:** immediate
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Used only to route resolve requests to the registry that issued a DOI (R-1). Not a content source.

### Unpaywall (`unpaywall`)

- **Provides:** resolver records; gateway requests: enrich; identifiers: doi
- **Lanes:** **base lane** for oa-location — queried for every request of that kind
- **Credential:** no credential (a contact address in the request, not a secret)
- **How to get access:** No key; pass a contact email as the email query parameter.
- **Website:** https://unpaywall.org/ — **API documentation:** https://unpaywall.org/products/api
- **Rate limit:** 100000/day (verified) — 100,000 requests/day with an email parameter (Unpaywall API docs, mirrored by library guides)
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** CC0.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: Unpaywall FAQ (CC0), as mirrored by https://libguides.ucalgary.ca/c.php?g=732144&p=5260801 and CASRAI; unpaywall.org does not render to automated fetch
- **Freshness:** continuous
- **Substitution family:** doi-metadata
- **Enabled in the registry's default seed:** yes
- **Notes:** Open-access location resolution after discovery. Never a discovery lane (0 unique works measured).

## Statistical data APIs

### BIS Data Portal (SDMX) (`bis`)

- **Provides:** statistical records; gateway requests: data, catalog; identifiers: dataflow, series
- **Lanes:** **domain lane** added for finance (an `other`-domain request includes every domain lane)
- **Credential:** no credential
- **How to get access:** No key.
- **Website:** https://data.bis.org/ — **API documentation:** https://stats.bis.org/api-doc/v2/
- **Rate limit:** 5/s (verified) — no documented limit; 5/s is a self-imposed ceiling. smoke 2026-09-07: v2 API serves SDMX-ML XML only (JSON Accept variants return 406); adapter reads XML
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Free reuse with attribution (BIS terms and conditions).
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://data.bis.org/help/export
- **Freshness:** as published
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Cross-border banking and monetary statistics.

### ECB Data Portal (SDMX) (`ecb`)

- **Provides:** statistical records; gateway requests: data, catalog; identifiers: dataflow, series
- **Lanes:** **domain lane** added for finance (an `other`-domain request includes every domain lane)
- **Credential:** no credential
- **How to get access:** No key.
- **Website:** https://data.ecb.europa.eu/ — **API documentation:** https://data.ecb.europa.eu/help/api/overview
- **Rate limit:** 5/s (verified) — no documented limit; 5/s is a self-imposed ceiling. smoke 2026-09-07: one live call answered 200 (EXR daily USD/EUR), no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Free reuse with attribution (ECB disclaimer and copyright).
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://data.ecb.europa.eu/help/api/overview
- **Freshness:** as published
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Euro-area statistics.

### FRED (Federal Reserve Economic Data) (`fred`)

- **Provides:** statistical records; gateway requests: data, catalog; identifiers: series
- **Lanes:** **domain lane** added for finance, market (an `other`-domain request includes every domain lane)
- **Credential:** credential required; secret name `fred`; environment `RESEARCH_GATEWAY_SECRET_FRED`
- **How to get access:** Create a free account, then https://fred.stlouisfed.org/docs/api/api_key.html → Request API Key. Sent as the api_key query parameter.
- **Website:** https://fred.stlouisfed.org/ — **API documentation:** https://fred.stlouisfed.org/docs/api/fred/
- **Rate limit:** 120/min (verified) — FRED documentation states 120 requests per minute per key. smoke 2026-09-07: one live call answered 200 (keyed), no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Free with mandatory attribution; some series carry third-party restrictions — check per series.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://fred.stlouisfed.org/docs/api/terms_of_use.html
- **Freshness:** as published
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Macro and financial time series.

### U.S. Bureau of Economic Analysis (BEA) Data API (`bea`)

- **Provides:** statistical records; gateway requests: data, catalog; identifiers: dataset, table
- **Lanes:** **domain lane** added for finance, market (an `other`-domain request includes every domain lane)
- **Credential:** credential required; secret name `bea`; environment `RESEARCH_GATEWAY_SECRET_BEA`
- **How to get access:** Sign up at https://apps.bea.gov/api/signup/ (name + email). The key arrives by email and must be activated via the link in that email before it works. Sent as the UserID query parameter.
- **Website:** https://www.bea.gov/ — **API documentation:** https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf
- **Rate limit:** 100/min (verified) — BEA user guide: 100 requests per minute and 100 MB per minute per key; only the request count is broker-enforced (D-15). smoke 2026-09-07: one live call answered 200 (keyed GETDATASETLIST)
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Attribution requested; no-endorsement clause; U.S. federal data.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://apps.bea.gov/api/signup/ (terms shown at signup)
- **Freshness:** as published
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** National accounts, GDP by industry and region.

### U.S. Bureau of Labor Statistics API (`bls`)

- **Provides:** statistical records; gateway requests: data, catalog; identifiers: series
- **Lanes:** **domain lane** added for market, finance, social (an `other`-domain request includes every domain lane)
- **Credential:** credential optional (raises the documented limits); secret name `bls`; environment `RESEARCH_GATEWAY_SECRET_BLS`
- **How to get access:** Optional free registration key at https://data.bls.gov/registrationEngine/ raises the daily query limit. Sent in the request body as registrationkey.
- **Website:** https://www.bls.gov/developers/ — **API documentation:** https://www.bls.gov/developers/api_faqs.htm
- **Rate limit:** 500/day (verified) — BLS API v2 FAQ: 25 queries/day unregistered, 500/day registered. smoke 2026-09-07: one live call answered 200 (unregistered POST), no rate-limit headers
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** U.S. federal public domain; attribution requested.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://www.bls.gov/bls/linksite.htm
- **Freshness:** as published
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Consumer Expenditure Survey, CPI.

### U.S. Census Bureau Data API (`census`)

- **Provides:** statistical records; gateway requests: data, catalog; identifiers: dataset, variable
- **Lanes:** **domain lane** added for market, social, finance (an `other`-domain request includes every domain lane)
- **Credential:** credential required; secret name `census`; environment `RESEARCH_GATEWAY_SECRET_CENSUS`
- **How to get access:** Request at https://api.census.gov/data/key_signup.html; the key arrives by email and must be activated via the link in that email. Sent as the key query parameter.
- **Website:** https://www.census.gov/data/developers.html — **API documentation:** https://www.census.gov/data/developers/guidance/api-user-guide.html
- **Rate limit:** 5/s (verified) — 500/day per IP is the documented keyless limit; keyed access documents no cap, so 5/s is a self-imposed ceiling. smoke 2026-09-07: one live call answered 200 (keyed ACS query, 3.9 s latency)
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** U.S. federal public domain; attribution requested.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://www.census.gov/data/developers/about/terms-of-service.html
- **Freshness:** as published
- **Substitution family:** none
- **Enabled in the registry's default seed:** yes
- **Notes:** Economic Census, retail trade, American Community Survey.

## Manual-only sources (documented, never queried)

### Pew Research Center datasets (`pew`)

- **Provides:** manual records; gateway requests: none
- **Lanes:** not a lane: documented, never queried by the gateway
- **Credential:** manual only — the registry records no programmatic credential
- **How to get access:** No API. Create a free account on the datasets page to download files (SPSS/CSV) by hand.
- **Website:** https://www.pewresearch.org/datasets/ — **API documentation:** https://www.pewresearch.org/datasets/
- **Rate limit:** no live calls (verified) — no programmatic access exists
- **Cost:** no cost cap recorded in the registry, which has no price field (see *What this catalog does not know*)
- **Licence:** Public-domain dedication for datasets.
- **Commercial posture:** **allow** — the source's terms permit commercial use of what the gateway retrieves. Evidence: https://www.pewresearch.org/datasets/ (terms shown at download)
- **Freshness:** static releases
- **Substitution family:** none
- **Enabled in the registry's default seed:** no
- **Notes:** Manual download only; listed so the documentation is complete.
