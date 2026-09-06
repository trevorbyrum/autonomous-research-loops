# Sources

Registries of research databases, and the research databases themselves, as known to this
project. Compiled 2026-09-06 from the search-breadth topic's verified corpus (SB-01/08/09/10)
plus same-day live endpoint checks; the SB-11 obligation (registry census, marginal-value
long-tail hunt, student-access tiers) is actively extending this list. Counts marked with `~`
are approximate or provider-claimed; unmarked counts were read live from the registry's own
API on the compile date. Access values: **Free** (no gate), **Free (reg.)** (free account/
registration/key), **Student** (paywalled, but typically free through student/institutional
access), **Paywalled**.

## Registries of research databases

| Registry | Key needed | Access | Sources listed | Link |
|---|---|---|---|---|
| OpenAlex `sources` entity | No (courtesy email for polite pool) | Free | 256,342 | https://openalex.org / https://api.openalex.org/sources |
| OpenAIRE Graph data sources | No (higher limits if registered) | Free | 157,198 | https://graph.openaire.eu / https://api.openaire.eu/graph/v1/dataSources |
| OpenDOAR (Sherpa v2) | Yes — free API key via Jisc account | Free (reg.) | ~6,000 | https://v2.sherpa.ac.uk/opendoar/ |
| ROAR | No | Free | ~5,000 (unverified) | https://roar.eprints.org/ |
| DataCite repositories | No | Free | 4,483 | https://api.datacite.org/repositories |
| re3data | No | Free | 3,522 | https://www.re3data.org/ |
| FAIRsharing | Yes — free account, JWT auth | Free (reg.) | ~4,000 (unverified) | https://fairsharing.org/ |
| ISSN ROAD | No | Free | ~60,000 (unverified; no machine route confirmed) | https://road.issn.org/ |
| dataportals.org | No | Free (human-only; JSON routes dead) | ~600 | https://dataportals.org/ |
| Search Smart | No | Free (human-facing evaluations) | ~100 | https://www.searchsmart.org/ |
| Wikidata (database entities) | No | Free | thousands (query-dependent) | https://query.wikidata.org/ |
| OAI-PMH ListFriends | — | **Discontinued 2025-07-18** | — | https://www.openarchives.org/ |

Registry-metadata licenses where established: re3data entries CC0; OpenAlex CC0; Wikidata CC0;
FAIRsharing CC BY-SA 4.0 (share-alike — annotate from it, do not redistribute its records);
OpenAIRE states CC BY for graph data (not independently confirmed); OpenDOAR/ROAR/ROAD
licenses not yet confirmed.

## Research databases

| Name | Key needed | Access | Link |
|---|---|---|---|
| OpenAlex | No (courtesy email) | Free | https://openalex.org/ |
| Crossref | No (courtesy mailto) | Free | https://www.crossref.org/ |
| Unpaywall | No (email parameter) | Free | https://unpaywall.org/ |
| Semantic Scholar | Optional (free key raises limits) | Free | https://www.semanticscholar.org/ |
| OpenCitations | No | Free | https://opencitations.net/ |
| DataCite | No | Free | https://datacite.org/ |
| arXiv | No | Free | https://arxiv.org/ |
| Zenodo | Optional (free token raises limits) | Free | https://zenodo.org/ |
| DOAJ | No | Free | https://doaj.org/ |
| DOAB | No | Free | https://www.doabooks.org/ |
| CORE | Yes — free API key | Free (reg.) | https://core.ac.uk/ |
| BASE | Yes — free registration (IP whitelist) for API | Free (reg.) | https://www.base-search.net/ |
| PubMed / NCBI E-utilities | Optional (free key raises limits) | Free | https://pubmed.ncbi.nlm.nih.gov/ |
| Lens.org | Yes — account; API by application | Free (reg.) for scholarly use; API tiered | https://www.lens.org/ |
| Google Scholar | No API; scraping blocked | Free (web only) | https://scholar.google.com/ |
| Google Dataset Search | No API | Free (web only) | https://datasetsearch.research.google.com/ |
| OSF Preprints / SocArXiv family | Optional (free token) | Free | https://osf.io/preprints/ |
| SSRN | No (account for downloads) | Free (reg.) | https://www.ssrn.com/ |
| RePEc / IDEAS | API approval-gated; rsync open | Free (reg.) | https://ideas.repec.org/ |
| NBER working papers | No | Free | https://www.nber.org/ |
| Software Heritage | Optional (free token raises limits) | Free | https://www.softwareheritage.org/ |
| SEC EDGAR | No | Free | https://www.sec.gov/edgar |
| Eurostat | No | Free | https://ec.europa.eu/eurostat |
| EPA ECHO | No | Free | https://echo.epa.gov/ |
| World Bank WDI | No | Free | https://data.worldbank.org/ |
| FAOSTAT | No | Free | https://www.fao.org/faostat/ |
| FRED | Yes — free API key | Free (reg.) | https://fred.stlouisfed.org/ |
| O*NET Web Services | Yes — free key | Free (reg.) | https://www.onetonline.org/ |
| World Values Survey | Registration | Free (reg.; non-profit use only, no redistribution) | https://www.worldvaluessurvey.org/ |
| Arab Barometer | Registration | Free (reg.) | https://www.arabbarometer.org/ |
| WERS (UK Data Service) | Registration | Free (reg.; UK secure tier restricted) | https://ukdataservice.ac.uk/ |
| DTIC | No API | Free (web only; machine routes currently broken) | https://discover.dtic.mil/ |
| Google Trends | No usable API (invite-only alpha) | Free (web only) | https://trends.google.com/ |
| ResearchGate | No API | Free (reg.; web only) | https://www.researchgate.net/ |
| Academia.edu | No API | Free (reg.; web only) | https://www.academia.edu/ |
| Web of Science | Institutional | Student | https://www.webofscience.com/ |
| Scopus | Institutional | Student | https://www.scopus.com/ |
| ScienceDirect (Elsevier) | Institutional | Student | https://www.sciencedirect.com/ |
| ACM Digital Library | Institutional | Student | https://dl.acm.org/ |
| IEEE Xplore | Institutional | Student | https://ieeexplore.ieee.org/ |
| JSTOR | Institutional | Student | https://www.jstor.org/ |
| ProQuest | Institutional | Student | https://www.proquest.com/ |
| EBSCO | Institutional | Student | https://www.ebsco.com/ |
| Statista | Institutional | Student | https://www.statista.com/ |
| Dun & Bradstreet | Commercial contract | Paywalled | https://www.dnb.com/ |
| Data Axle (InfoUSA) | Commercial contract | Paywalled | https://www.data-axle.com/ |

Notes anchored in the verified corpus: arXiv full text carries mixed submitter-chosen licenses
(metadata-only mirroring is the safe public posture); Software Heritage forbids bulk extraction
via API (use the S3 graph dataset); ResearchGate/Academia.edu have no API and independently
measured high rates of copyright-noncompliant content — discovery surfaces only; Google
Scholar blocks automation (~2-day IP blocks measured). The Student rows are the priority
targets for SB-11 Part C (student-access tier verification), including the venues holding the
reranking topic's three access-blocked papers (ScienceDirect, ACM DL, IEEE Xplore).
