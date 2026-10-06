# Architecture metrics ledger

Task 2q-a-repair-2 and 2q-a-repair-3; charter Architecture metrics and Root-cause fixes, not patches.

The baseline registry owns persistent identities. Each check accounts for every
identity as present, explicitly mapped, or explicitly retired. Missing identities
fail. New files, edges, reach pairs and collaboration/function budgets require
admission. Stable-target fan-in includes every dependent, including new files.
Normalised aggregates never authorise growth. Instability is judged by direction:
taking on dependencies differs from losing dependents (Stable Dependencies Principle).

Source outside the supported-source contract (docs/gen2/SOURCE-CONTRACT.md) is
refused before any measurement. Nothing in this ledger waives a refusal: an
unresolved or unsupported form is not classified here, it is changed.

`make gen2-metrics-admit` drafts what the current plan still lacks with reason: TODO;
drafts fail. Fill each reason and reviewing task, review the diff, and commit the
ledger before checking. The tool checks commitment, not the truth of the author's
review claim. Maps preserve the old identity and compare all old budgets at the new
location. A `move` entry states one explicit file move (or one directory prefix) and
expands deterministically to a map of every baseline identity that mentions the file;
nothing is inferred from similar bodies and nothing is admitted by a move. An identity
the move cannot map (it has no counterpart at the destination) needs its own `retire`
entry; an explicit `map` or `retire` always overrides the expansion for that identity.
Retirements require absence. Budget admissions name one metric/location and a bounded
limit. Exemptions remain temporary regressions and never loosen a recorded budget.
Identity loss and new population cannot be exempted.

Rebaseline consumes admitted, mapped, moved and retired transitions only after a passing
check, keeps persistent IDs, and clears those entries. Improved functions keep their
identity and both scores even below thresholds. An edge/reach/pair that disappears
requires retirement. Git retains consumed reasons in the committed ledger history. Initial
recording is the sole bootstrap; existing baselines can migrate only at their exact
production digest.

Entries are `### ML-...` sections with fields action (map, retire, admit, budget, move),
identity/target (as applicable), metric/location/limit (for budget), from/to (for move),
reason, and task. Targets use service|kind|location; file identities own fan-out and
fan-in; function IDs own both scores; edge, reach, self_calls, cycle, smell and aggregate
IDs own their respective budgets. Cross-service imports belong to repo.

### ML-0001
- action: retire
- identity: MI-000256
- reason: adapters/base.py no longer imports core/uri.py: its one user of the URI grammar, the Link reader, moved to adapters/_links.py with the split of adapters/base.py by responsibility (task 2q-b5)
- task: 2q-b5

### ML-0002
- action: map
- identity: MI-000535
- target: gateway|function|gateway/research_gateway/adapters/_links.py::parse_links
- reason: parse_links moved with the Link reader to adapters/_links.py and is decomposed along the RFC 8288 grammar steps (task 2q-b5), 22/57 -> 7/9 (cyclomatic/cognitive); the identity maps to its new place, so the old budgets carry there and the rebaseline tightens them
- task: 2q-b5

### ML-0003
- action: retire
- identity: MI-000572
- reason: adapters/base.py no longer reaches core/uri.py: the Link reader, the only code of the old base.py that used it, moved to adapters/_links.py, which only adapters/huggingface.py imports (task 2q-b5)
- task: 2q-b5

### ML-0004
- action: retire
- identity: MI-000582
- reason: gone with the edge it ran through (task 2q-b5): adapters/bea.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0005
- action: retire
- identity: MI-000593
- reason: gone with the edge it ran through (task 2q-b5): adapters/bis.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0006
- action: retire
- identity: MI-000603
- reason: gone with the edge it ran through (task 2q-b5): adapters/bls.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0007
- action: retire
- identity: MI-000613
- reason: gone with the edge it ran through (task 2q-b5): adapters/census.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0008
- action: retire
- identity: MI-000623
- reason: gone with the edge it ran through (task 2q-b5): adapters/core.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0009
- action: retire
- identity: MI-000633
- reason: gone with the edge it ran through (task 2q-b5): adapters/crossref.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0010
- action: retire
- identity: MI-000643
- reason: gone with the edge it ran through (task 2q-b5): adapters/datacite.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0011
- action: retire
- identity: MI-000653
- reason: gone with the edge it ran through (task 2q-b5): adapters/doaj.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0012
- action: retire
- identity: MI-000663
- reason: gone with the edge it ran through (task 2q-b5): adapters/doi_org.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0013
- action: retire
- identity: MI-000674
- reason: gone with the edge it ran through (task 2q-b5): adapters/ecb.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0014
- action: retire
- identity: MI-000684
- reason: gone with the edge it ran through (task 2q-b5): adapters/europepmc.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0015
- action: retire
- identity: MI-000694
- reason: gone with the edge it ran through (task 2q-b5): adapters/fred.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0016
- action: retire
- identity: MI-000704
- reason: gone with the edge it ran through (task 2q-b5): adapters/globe.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0017
- action: retire
- identity: MI-000714
- reason: gone with the edge it ran through (task 2q-b5): adapters/govinfo.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0018
- action: retire
- identity: MI-000725
- reason: gone with the edge it ran through (task 2q-b5): adapters/harvard_dataverse.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0019
- action: retire
- identity: MI-000746
- reason: gone with the edge it ran through (task 2q-b5): adapters/kaggle.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0020
- action: retire
- identity: MI-000756
- reason: gone with the edge it ran through (task 2q-b5): adapters/openaire.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0021
- action: retire
- identity: MI-000765
- reason: gone with the edge it ran through (task 2q-b5): adapters/openalex_snapshot.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0022
- action: retire
- identity: MI-000775
- reason: gone with the edge it ran through (task 2q-b5): adapters/opencitations.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0023
- action: retire
- identity: MI-000786
- reason: gone with the edge it ran through (task 2q-b5): adapters/openml.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0024
- action: retire
- identity: MI-000799
- reason: gone with the edge it ran through (task 2q-b5): adapters/qdr.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0025
- action: retire
- identity: MI-000809
- reason: gone with the edge it ran through (task 2q-b5): adapters/semanticscholar.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0026
- action: retire
- identity: MI-000820
- reason: gone with the edge it ran through (task 2q-b5): adapters/socrata.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0027
- action: retire
- identity: MI-000830
- reason: gone with the edge it ran through (task 2q-b5): adapters/unpaywall.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0028
- action: retire
- identity: MI-000843
- reason: gone with the edge it ran through (task 2q-b5): adapters/wms.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0029
- action: retire
- identity: MI-000868
- reason: gone with the edge it ran through (task 2q-b5): api/http.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0030
- action: retire
- identity: MI-000893
- reason: gone with the edge it ran through (task 2q-b5): app.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0031
- action: retire
- identity: MI-000982
- reason: gone with the edge it ran through (task 2q-b5): harvest/registries.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0032
- action: retire
- identity: MI-001011
- reason: gone with the edge it ran through (task 2q-b5): mcp/homelab_adapter.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0033
- action: retire
- identity: MI-001046
- reason: gone with the edge it ran through (task 2q-b5): smoke.py reached core/uri.py only through adapters/base.py, whose one user of it, the Link reader, is now adapters/_links.py (imported by adapters/huggingface.py alone)
- task: 2q-b5

### ML-0034
- action: admit
- target: gateway|edge|gateway/research_gateway/adapters/_links.py->gateway/research_gateway/adapters/_response.py
- reason: next_link takes the client's Response (its headers and URL); the type moved out of base.py with the split, so the Link reader imports it from its own module instead of base.py defining both (task 2q-b5)
- task: 2q-b5

### ML-0035
- action: admit
- target: gateway|edge|gateway/research_gateway/adapters/_links.py->gateway/research_gateway/core/__init__.py
- reason: `from ..core import uri`, the import base.py made for the same code (a package import is an edge to the package's __init__) (task 2q-b5)
- task: 2q-b5

### ML-0036
- action: admit
- target: gateway|edge|gateway/research_gateway/adapters/_links.py->gateway/research_gateway/core/uri.py
- reason: the Link reader's one dependency on the URI grammar (uri.is_uri_reference, is_uri, resolve, same_resource), moved from adapters/base.py with the code that uses it (task 2q-b5)
- task: 2q-b5

### ML-0037
- action: admit
- target: gateway|edge|gateway/research_gateway/adapters/_response.py->gateway/research_gateway/core/payload.py
- reason: Response subclasses SealedAnswer and returns Sealed (core/payload.py): the import base.py made for the same class, moved with it (task 2q-b5)
- task: 2q-b5

### ML-0038
- action: admit
- target: gateway|edge|gateway/research_gateway/adapters/_transport.py->gateway/research_gateway/adapters/_response.py
- reason: Transport and FakeTransport construct the client's Response: the dependency base.py had on its own definition, now between two modules (task 2q-b5)
- task: 2q-b5

### ML-0039
- action: admit
- target: gateway|edge|gateway/research_gateway/adapters/base.py->gateway/research_gateway/adapters/_response.py
- reason: the client builds and reads the Response it used to define (and re-exports it: tests and adapters import `Response` from base) (task 2q-b5)
- task: 2q-b5

### ML-0040
- action: admit
- target: gateway|edge|gateway/research_gateway/adapters/base.py->gateway/research_gateway/adapters/_transport.py
- reason: the client's default transport, its redirect rules and their constants: what base.py used to define it now imports (task 2q-b5)
- task: 2q-b5

### ML-0041
- action: admit
- target: gateway|edge|gateway/research_gateway/adapters/huggingface.py->gateway/research_gateway/adapters/_links.py
- reason: the one adapter that pages by Link header imports the Link reader directly, no longer through base.py (task 2q-b5: an adapter that uses only Link functions imports that module) (task 2q-b5)
- task: 2q-b5

### ML-0042
- action: admit
- target: gateway|file|gateway/research_gateway/adapters/_links.py
- reason: a new file of the split of adapters/base.py by responsibility (task 2q-b5): the RFC 8288 Link reader (parse_links, relation_types, next_link, own_link), moved from base.py; parse_links is decomposed into one function per grammar step (_space, _token, _quoted, _param, _target)
- task: 2q-b5

### ML-0043
- action: admit
- target: gateway|file|gateway/research_gateway/adapters/_response.py
- reason: a new file of the split of adapters/base.py by responsibility (task 2q-b5): the client's Response (status, headers, URL, error and the sealed answer bytes) and its Retry-After reader, moved unchanged, so that the transport, the Link reader and the client depend on it and not on one another
- task: 2q-b5

### ML-0044
- action: admit
- target: gateway|file|gateway/research_gateway/adapters/_transport.py
- reason: a new file of the split of adapters/base.py by responsibility (task 2q-b5): HTTP transport and message framing (Transport, FakeTransport, the framing checks, the redirect rules and their constants), moved unchanged; it knows nothing of the broker, the call log or the schema
- task: 2q-b5

### ML-0045
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/_links.py->gateway/research_gateway/adapters/_response.py
- reason: the reach of the admitted edge _links.py -> _response.py (task 2q-b5)
- task: 2q-b5

### ML-0046
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/_links.py->gateway/research_gateway/core/__init__.py
- reason: the reach of the admitted edge _links.py -> core/__init__.py (task 2q-b5)
- task: 2q-b5

### ML-0047
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/_links.py->gateway/research_gateway/core/payload.py
- reason: the reach of _links.py imports _response.py, which imports core/payload.py (task 2q-b5)
- task: 2q-b5

### ML-0048
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/_links.py->gateway/research_gateway/core/uri.py
- reason: the reach of the admitted edge _links.py -> core/uri.py (task 2q-b5)
- task: 2q-b5

### ML-0049
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/_response.py->gateway/research_gateway/core/payload.py
- reason: the reach of the admitted edge _response.py -> core/payload.py (task 2q-b5)
- task: 2q-b5

### ML-0050
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/_transport.py->gateway/research_gateway/adapters/_response.py
- reason: the reach of the admitted edge _transport.py -> _response.py (task 2q-b5)
- task: 2q-b5

### ML-0051
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/_transport.py->gateway/research_gateway/core/payload.py
- reason: the reach of _transport.py imports _response.py, which imports core/payload.py (task 2q-b5)
- task: 2q-b5

### ML-0052
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/base.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/base.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/base.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0053
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/base.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/base.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/base.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0054
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/bea.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/bea.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/bea.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0055
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/bea.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/bea.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/bea.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0056
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/bis.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/bis.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/bis.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0057
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/bis.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/bis.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/bis.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0058
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/bls.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/bls.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/bls.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0059
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/bls.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/bls.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/bls.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0060
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/census.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/census.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/census.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0061
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/census.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/census.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/census.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0062
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/core.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/core.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/core.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0063
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/core.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/core.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/core.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0064
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/crossref.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/crossref.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/crossref.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0065
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/crossref.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/crossref.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/crossref.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0066
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/datacite.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/datacite.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/datacite.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0067
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/datacite.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/datacite.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/datacite.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0068
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/doaj.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/doaj.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/doaj.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0069
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/doaj.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/doaj.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/doaj.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0070
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/doi_org.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/doi_org.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/doi_org.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0071
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/doi_org.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/doi_org.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/doi_org.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0072
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/ecb.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/ecb.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/ecb.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0073
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/ecb.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/ecb.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/ecb.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0074
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/europepmc.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/europepmc.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/europepmc.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0075
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/europepmc.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/europepmc.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/europepmc.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0076
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/fred.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/fred.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/fred.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0077
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/fred.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/fred.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/fred.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0078
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/globe.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/globe.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/globe.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0079
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/globe.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/globe.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/globe.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0080
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/govinfo.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/govinfo.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/govinfo.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0081
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/govinfo.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/govinfo.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/govinfo.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0082
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/harvard_dataverse.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/harvard_dataverse.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/harvard_dataverse.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0083
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/harvard_dataverse.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/harvard_dataverse.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/harvard_dataverse.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0084
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/huggingface.py->gateway/research_gateway/adapters/_links.py
- reason: the reach of the admitted edge huggingface.py -> _links.py (task 2q-b5)
- task: 2q-b5

### ML-0085
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/huggingface.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/huggingface.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/huggingface.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0086
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/huggingface.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/huggingface.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/huggingface.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0087
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/kaggle.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/kaggle.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/kaggle.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0088
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/kaggle.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/kaggle.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/kaggle.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0089
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/openaire.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/openaire.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/openaire.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0090
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/openaire.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/openaire.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/openaire.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0091
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/openalex_snapshot.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/openalex_snapshot.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/openalex_snapshot.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0092
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/openalex_snapshot.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/openalex_snapshot.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/openalex_snapshot.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0093
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/opencitations.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/opencitations.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/opencitations.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0094
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/opencitations.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/opencitations.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/opencitations.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0095
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/openml.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/openml.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/openml.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0096
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/openml.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/openml.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/openml.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0097
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/qdr.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/qdr.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/qdr.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0098
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/qdr.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/qdr.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/qdr.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0099
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/semanticscholar.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/semanticscholar.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/semanticscholar.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0100
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/semanticscholar.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/semanticscholar.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/semanticscholar.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0101
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/socrata.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/socrata.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/socrata.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0102
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/socrata.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/socrata.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/socrata.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0103
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/unpaywall.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/unpaywall.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/unpaywall.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0104
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/unpaywall.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/unpaywall.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/unpaywall.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0105
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/wms.py->gateway/research_gateway/adapters/_response.py
- reason: adapters/wms.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what adapters/wms.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0106
- action: admit
- target: gateway|reach|gateway/research_gateway/adapters/wms.py->gateway/research_gateway/adapters/_transport.py
- reason: adapters/wms.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what adapters/wms.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0107
- action: admit
- target: gateway|reach|gateway/research_gateway/api/http.py->gateway/research_gateway/adapters/_response.py
- reason: api/http.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what api/http.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0108
- action: admit
- target: gateway|reach|gateway/research_gateway/api/http.py->gateway/research_gateway/adapters/_transport.py
- reason: api/http.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what api/http.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0109
- action: admit
- target: gateway|reach|gateway/research_gateway/app.py->gateway/research_gateway/adapters/_response.py
- reason: app.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what app.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0110
- action: admit
- target: gateway|reach|gateway/research_gateway/app.py->gateway/research_gateway/adapters/_transport.py
- reason: app.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what app.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0111
- action: admit
- target: gateway|reach|gateway/research_gateway/harvest/registries.py->gateway/research_gateway/adapters/_response.py
- reason: harvest/registries.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what harvest/registries.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0112
- action: admit
- target: gateway|reach|gateway/research_gateway/harvest/registries.py->gateway/research_gateway/adapters/_transport.py
- reason: harvest/registries.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what harvest/registries.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0113
- action: admit
- target: gateway|reach|gateway/research_gateway/mcp/homelab_adapter.py->gateway/research_gateway/adapters/_response.py
- reason: mcp/homelab_adapter.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what mcp/homelab_adapter.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0114
- action: admit
- target: gateway|reach|gateway/research_gateway/mcp/homelab_adapter.py->gateway/research_gateway/adapters/_transport.py
- reason: mcp/homelab_adapter.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what mcp/homelab_adapter.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0115
- action: admit
- target: gateway|reach|gateway/research_gateway/smoke.py->gateway/research_gateway/adapters/_response.py
- reason: smoke.py imports or reaches adapters/base.py, which now imports adapters/_response.py where it used to define what that module holds: what smoke.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0116
- action: admit
- target: gateway|reach|gateway/research_gateway/smoke.py->gateway/research_gateway/adapters/_transport.py
- reason: smoke.py imports or reaches adapters/base.py, which now imports adapters/_transport.py where it used to define what that module holds: what smoke.py reached in base.py it now reaches through the two parts of the client (task 2q-b5)
- task: 2q-b5

### ML-0117
- action: admit
- target: gateway|smell_unstable_dependency|gateway/research_gateway/adapters/base.py->gateway/research_gateway/adapters/_transport.py
- reason: an unstable-dependency smell the split creates and nothing in it made worse: adapters/base.py (29 dependents, so stable) imports adapters/_transport.py to compose it into the Client (the default transport, the redirect rules); _transport.py's only dependent is base.py and its one dependency is _response.py, so it measures as the less stable by 26 points. The edge is the client's own composition, not an adapter's reach into the transport, and an adapter cannot import from it (tests/inventory.py `import_findings`: a client part admits only its `__all__`, and _transport.py has none) (task 2q-b5)
- task: 2q-b5

### ML-0118
- action: budget
- metric: fan_out
- location: gateway:gateway/research_gateway/adapters/base.py
- limit: 9
- reason: base.py now imports adapters/_response.py and adapters/_transport.py where it used to define Response and Transport (+2), and no longer imports core/uri.py (-1, the Link reader moved): 8 -> 9. Every dependency of the old base.py is held by it or by one of the three new modules; the code depends on nothing it did not (task 2q-b5)
- task: 2q-b5

### ML-0119
- action: budget
- metric: fan_out
- location: gateway:gateway/research_gateway/adapters/huggingface.py
- limit: 6
- reason: huggingface.py imports the Link reader (adapters/_links.py) directly and the rest of the client through base.py: 5 -> 6. This is the split's own instruction (an adapter that uses Link functions imports that module); it is the only adapter that pages by Link (task 2q-b5)
- task: 2q-b5

### ML-0120
- action: budget
- metric: fan_in
- location: gateway:gateway/research_gateway/core/__init__.py
- limit: 35
- reason: adapters/_links.py imports `from ..core import uri`, as base.py did for the same code; base.py keeps its own `from ..core import calllog`: 34 -> 35. The dependency moved with the code and was not added by it (task 2q-b5)
- task: 2q-b5

### ML-0121
- action: budget
- metric: fan_in
- location: gateway:gateway/research_gateway/core/payload.py
- limit: 11
- reason: adapters/_response.py imports from core/payload.py what the Response class needs (SealedAnswer, Sealed); base.py keeps the names it re-exports to adapters (AdapterError, PayloadError, MemberList ...): 10 -> 11 (task 2q-b5)
- task: 2q-b5

### ML-0122
- action: budget
- metric: smell_unstable_dependency
- location: gateway:gateway/research_gateway/adapters/base.py->gateway/research_gateway/adapters/_transport.py
- reason: the smell admitted above, counted once: one edge, base.py -> _transport.py, no other smell is added (task 2q-b5)
- task: 2q-b5
