"""Mutants of task 2b-repair-18 (Astra's 2b-repair-17 review, R17-1): the endpoint owner is the only source of a connection target, and the one origin it holds is validated at construction.

R17-1 was two guards missing at once: the owner held `127.0.0.%31` as a name, and the connection read the host urllib had decoded from it (`127.0.0.1`) as an address before it consulted the owner.
Each guard is mutated alone, and both together (`2B18-the-r17-1-reading-is-restored`), because the guards double each other on the wire: with the validation gone, a withdrawn endpoint still
connects nowhere (the owner admits nothing); with the connection reading the request host but the validation intact, no request host can spell an address the owner did not admit. A killer
therefore goes through the OTHER layer of each: the transport called with nothing admitted for the connect-time reading, the table of refused spellings for each validation rule, and Astra's
sequence over the real client for the pair. The rules of the validation are mutated one at a time, each killed by an input that only that rule refuses (a rule that a second rule also enforces is
mutated together with it). Killers fail by assertion; their controls are chosen by tools/gen2_mutation_controls.py from a traced run, as for every mutant here.
"""
from __future__ import annotations

from .base import Mutation

OW, RT, CLI = "test_gateway_ownership.", "test_gateway_routes.", "gen2/gateway_client/client.py"
AUTH, FACT = OW + "TheOriginIsTheOnlyAuthority.", OW + "TheEndpointIsOneFact."
DIRECT, FORMS = RT + "DirectHttpOnly.", RT + "TheEndpointForms."

REQUEST_HOST = DIRECT + "test_a_request_hosts_spelling_is_never_a_connection_target"
SPELLINGS = FORMS + "test_every_spelling_a_reader_could_take_another_way_is_refused_before_any_io"
CANONICAL = FORMS + "test_the_forms_that_are_accepted_are_one_canonical_origin_that_urllib_and_the_owner_read_alike"
REBIND = AUTH + "test_astras_r17_1_probe_a_withdrawn_endpoint_reaches_nothing_whatever_its_spelling"
REBIND_POLL = FACT + "test_astras_r17_1_probe_the_same_for_a_poll_in_progress"

CONNECT = (("def _connect(deadline: _Deadline, admitted: Sequence) -> _DeadlineSocket:", "def _connect(address: tuple, deadline: _Deadline, admitted: Sequence) -> _DeadlineSocket:"),
           ("    for family, kind, proto, _, target in admitted:\n", "    for family, kind, proto, _, target in _literal(*address) or admitted:\n"),
           ("        self._create_connection = lambda address, timeout, source_address: _connect(deadline, admitted)\n\n\nclass _DeadlineHTTPSConnection(",
            "        self._create_connection = lambda address, timeout, source_address: _connect(address, deadline, admitted)\n\n\nclass _DeadlineHTTPSConnection("),
           ("        self._create_connection = lambda address, timeout, source_address: _connect(deadline, admitted)\n        self._context.sslsocket_class",
            "        self._create_connection = lambda address, timeout, source_address: _connect(address, deadline, admitted)\n        self._context.sslsocket_class"))
HOST_CHARS = ("|([a-z0-9.-]+))(?::", "|([a-z0-9.%-]+))(?::")
LABEL = ('_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"', '_LABEL = re.compile(r"[a-z0-9%](?:[a-z0-9%-]{0,61}[a-z0-9%])?"')

MUTATIONS: list[Mutation] = [
    # the owner is the only source of a connection target
    Mutation("2B18-connect-reads-the-request-host-as-an-address", "2b-18",
             "the connection tries the host the request names, as urllib decoded it, as an IP literal before it looks at what the owner admitted (the connect-time reading of R17-1)",
             (REQUEST_HOST,), target=CLI, old=CONNECT[0][0], new=CONNECT[0][1], also=CONNECT[1:]),
    # the one origin, validated at construction
    Mutation("2B18-a-percent-encoded-host-is-a-name", "2b-18", "a percent-encoded host is accepted as a name (the owner's reading of R17-1: `127.0.0.%31` is a name)",
             (SPELLINGS,), target=CLI, old=HOST_CHARS[0], new=HOST_CHARS[1], also=(LABEL,)),
    Mutation("2B18-the-r17-1-reading-is-restored", "2b-18", "both: a percent-encoded host is a name to the owner and the address urllib decodes it to is a target at connect time (Astra's R17-1 as it was)",
             (REBIND, REBIND_POLL), target=CLI, old=HOST_CHARS[0], new=HOST_CHARS[1], also=(LABEL, *CONNECT)),
    Mutation("2B18-an-alternate-numeric-spelling-is-a-name", "2b-18", "a name whose last label is a number (`2130706433`, `0x7f.1`, `0177.0.0.1`, `127.1`), which a resolver reads as an address, is accepted",
             (SPELLINGS,), target=CLI, old=" or _NUMBER.fullmatch(labels[-1])", new=""),
    Mutation("2B18-a-zone-id-is-an-address", "2b-18", "an IPv6 literal may carry a zone (`[fe80::1%31]`), which urllib unquotes into another address",
             (SPELLINGS,), target=CLI, old="\\[([0-9a-f:.]+)\\]", new="\\[([0-9a-z:.%]+)\\]"),
    Mutation("2B18-a-label-need-not-be-ldh", "2b-18", "the labels of a name are not checked: a leading or trailing hyphen, an empty label and a trailing dot are accepted",
             (SPELLINGS,), target=CLI, old="not all(_LABEL.fullmatch(label) for label in labels) or ", new=""),
    Mutation("2B18-a-name-may-be-any-length", "2b-18", "a name over 253 characters is accepted", (SPELLINGS,), target=CLI, old="len(name) > 253 or ", new=""),
    Mutation("2B18-the-port-is-unchecked", "2b-18", "a port of 0, or over 65535, is accepted", (SPELLINGS,), target=CLI, old="not 0 < port < 65536 or ", new=""),
    Mutation("2B18-a-path-query-or-fragment-is-accepted", "2b-18", "a path, query or fragment after the origin is accepted and dropped", (SPELLINGS,), target=CLI,
             old="(?::([0-9]{1,5}))?/?\"", new="(?::([0-9]{1,5}))?(?:[/?#].*)?\""),
    Mutation("2B18-the-host-is-not-lower-cased", "2b-18", "the owner holds the host as it was spelled (`GATEWAY` and `gateway` are two origins)", (CANONICAL,), target=CLI,
             old="host = str(ip) if ip is not None else name.lower()", new="host = str(ip) if ip is not None else name"),
    Mutation("2B18-the-request-is-built-from-the-callers-spelling", "2b-18", "requests are built from the URL as given, not from the canonical origin the owner holds", (CANONICAL,), target=CLI,
             old="        self._base_url = self._endpoint.origin\n", new='        self._base_url = base_url.rstrip("/")\n'),
]
