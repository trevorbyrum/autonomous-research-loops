"""Mutants of task 2b-repair-17 (Gate D #3 checklist 6): the one endpoint owner of the engine's gateway client, its serial instances, and its closed routing surface.

Each removes or weakens one guard of gen2/gateway_client/client.py alone. The four the checklist names are among them: remove ownership (2B17-an-overlapping-call-is-allowed, and one for each
operation that no longer takes it), restore proxy dispatch (2B17-proxy-dispatch-is-restored), re-add a non-HTTP handler (the ftp, file, data and unknown ones), and share state across instances
(2B17-instances-share-a-lock, 2B17-instances-share-their-addresses: killed by the concurrency tests, whose server holds every reply until it has seen all N clients in flight). Their killers are
test_gateway_ownership.py and test_gateway_routes.py; a killer fails by assertion (a call a mutant lets through is caught and failed, never left to raise), and the controls are chosen by
tools/gen2_mutation_controls.py from a traced run, as for every mutant here.

The 2B15 mutants (task 2b-repair-15/16, tools/gen2_mutants/gateway_client_2b.py) that kept a stale flag set beside retained addresses are gone with the state they mutated: the flag is read off the
addresses now (the endpoint is one fact), so `2B15-a-failed-lookup-is-not-stale` mutates that reading and `2B15-a-failed-lookup-keeps-the-last-good-addresses-in-use` the publication.
"""
from __future__ import annotations

from .base import Mutation

OW, RT, CLI = "test_gateway_ownership.", "test_gateway_routes.", "gen2/gateway_client/client.py"
OP, FACT, LIFE, CONC = OW + "OneOperationAtATime.", OW + "TheEndpointIsOneFact.", OW + "ConnectionLifetimes.", OW + "SeparateClientsRunConcurrently."
DIRECT, HTTPS, FORMS = RT + "DirectHttpOnly.", RT + "DirectHttpsOnly.", RT + "TheEndpointForms."

OVERLAP = OP + "test_an_overlapping_call_is_refused_before_connect_and_before_send_whatever_the_operation_and_whatever_it_would_have_done"
DURING_POLL = OP + "test_a_call_during_a_poll_is_refused_too"
DURING_RESOLVE = OP + "test_a_call_during_a_resolution_is_refused_before_any_lookup_or_byte"
REENTRY = OP + "test_a_call_from_inside_an_operation_is_refused_too"
AFTER_ERROR = OP + "test_an_operation_that_ended_in_an_error_leaves_the_client_usable"
NOT_AN_OBSERVATION = OP + "test_the_refusal_is_the_callers_error_and_never_an_observation"
BETWEEN = OP + "test_a_call_between_a_searchs_pages_and_between_its_polls_is_refused_too"
R161 = FACT + "test_astras_r16_1_probe_a_search_held_before_its_connect_cannot_be_overtaken_by_a_withdrawal"
R161_POLL = FACT + "test_astras_r16_1_probe_the_same_for_a_poll"
MATRIX = DIRECT + "test_a_hostile_environment_changes_nothing_about_where_a_search_goes"
TLS_MATRIX = HTTPS + "test_a_hostile_environment_changes_nothing_about_where_a_tls_search_goes"
HANDLERS = DIRECT + "test_the_opener_has_the_http_handlers_and_nothing_else"
FORM_REFUSALS = FORMS + "test_an_endpoint_that_is_not_an_http_or_https_host_without_credentials_is_refused_before_any_io"
HANDLER_LINE = "urllib.request.HTTPErrorProcessor()):"
LEASE_LINE = "        self._lease, self._holder = threading.Lock(), None   # per instance: no lock is shared between clients\n"
RELEASE = "            self._holder = None\n            self._lease.release()\n"

MUTATIONS: list[Mutation] = [
    # ownership: the instance is serial
    Mutation("2B17-an-overlapping-call-is-allowed", "2b-17", "a call that finds the client running another operation is not refused: it runs beside it, from any door",
             (OVERLAP, DURING_POLL, DURING_RESOLVE, BETWEEN, REENTRY, NOT_AN_OBSERVATION, R161, R161_POLL), target=CLI,
             old="        if not self._lease.acquire(blocking=False):", new="        if False and not self._lease.acquire(blocking=False):",
             also=((RELEASE, "            self._holder = None\n"),)),
    Mutation("2B17-a-call-from-inside-an-operation-is-allowed", "2b-17", "the client's lease is re-entrant: a hook the operation calls can start another on its own client",
             (REENTRY,), target=CLI, old=LEASE_LINE, new=LEASE_LINE.replace("threading.Lock()", "threading.RLock()")),
    Mutation("2B17-an-exchange-ignores-the-owner", "2b-17", "the private exchange takes no part in ownership, so a second thread can send through it while an operation runs (Astra's R16-1 probe)",
             (OVERLAP, R161, R161_POLL), target=CLI, old='    @_serial("exchange", within=True)\n    def _exchange(', new="    def _exchange("),
    Mutation("2B17-a-search-is-not-an-operation", "2b-17", "a search does not own the client: another call, and its own hooks, run beside it",
             (OVERLAP, DURING_POLL, BETWEEN, REENTRY), target=CLI, old='    @_serial("search")\n    def search(', new="    def search("),
    Mutation("2B17-a-grant-is-not-an-operation", "2b-17", "a grant does not own the client", (OVERLAP,), target=CLI, old='    @_serial("grant")\n    def grant(', new="    def grant("),
    Mutation("2B17-a-resolve-is-not-an-operation", "2b-17", "a resolve does not own the client: a second lookup, and any other call, runs beside it",
             (DURING_RESOLVE, REENTRY), target=CLI, old='    @_serial("resolve")\n    def resolve(', new="    def resolve("),
    Mutation("2B17-a-failed-operation-keeps-the-client", "2b-17", "an operation that ended in an error does not release the client",
             (AFTER_ERROR,), target=CLI,
             old="        try:\n            yield\n        finally:\n            self._holder = None\n            self._lease.release()\n", new="        yield\n        self._holder = None\n        self._lease.release()\n"),
    # separate instances share nothing
    Mutation("2B17-instances-share-a-lock", "2b-17", "every client's lease is one module-level lock: a client running an operation refuses every other client",
             (CONC + "test_clients_against_one_gateway_have_requests_in_flight_together", CONC + "test_clients_resolve_at_the_same_time",
              CONC + "test_an_operation_running_on_one_client_does_not_refuse_another_client"), target=CLI,
             old=LEASE_LINE, new="        self._lease, self._holder = _SHARED, None\n",
             also=(('DEFAULT_PORTS = {"http": 80, "https": 443}', '_SHARED = threading.Lock()\nDEFAULT_PORTS = {"http": 80, "https": 443}'),)),
    Mutation("2B17-instances-share-their-addresses", "2b-17", "the addresses a lookup found are kept in one module-level table keyed by the endpoint, so one client's withdrawal is every client's",
             (CONC + "test_one_clients_withdrawal_reaches_no_other_client", CONC + "test_operations_write_no_module_state"), target=CLI,
             old="        self._found: tuple = ()\n", new="        self._key = (self.host, self.port)\n",
             also=(("        return self.literal or self._found", "        return self.literal or _FOUND.get(self._key, ())"),
                   ("        self._found = tuple(found)", "        _FOUND[self._key] = tuple(found)"),
                   ('DEFAULT_PORTS = {"http": 80, "https": 443}', '_FOUND: dict = {}\nDEFAULT_PORTS = {"http": 80, "https": 443}'))),
    # bounded lifetimes
    Mutation("2B17-a-timeout-withdraws-the-endpoint", "2b-17", "a timeout withdraws the endpoint like a refused connection (the accepted policy: a slow answer is not a gone gateway)",
             (LIFE + "test_a_timeout_does_not_withdraw_and_a_timely_reply_follows",), target=CLI,
             old='            if self._real and (error or "transport_failure") == "transport_failure":', new="            if self._real:"),
    Mutation("2B17-failover-stops-at-the-first-address", "2b-17", "an address that refuses ends the exchange: the later addresses are never tried",
             (LIFE + "test_a_later_address_is_tried_when_an_earlier_one_refuses_and_the_endpoint_stays_authorized",), target=CLI,
             old="            sock.close()\n            error = e\n    raise error\n", new="            sock.close()\n            error = e\n            break\n    raise error\n"),
    Mutation("2B17-a-failed-connect-leaves-its-socket-open", "2b-17", "a socket whose connect failed is not closed",
             (LIFE + "test_no_socket_outlives_its_exchange",), target=CLI,
             old="            sock.close()\n            error = e\n    raise error\n", new="            error = e\n    raise error\n"),
    # the routing surface: direct http/https only
    Mutation("2B17-proxy-dispatch-is-restored", "2b-17", "the opener has the proxy handler again: the environment's proxy variables, in any case, choose where an exchange goes",
             (MATRIX, DIRECT + "test_a_grant_goes_the_same_way", TLS_MATRIX, HANDLERS), target=CLI,   # not Astra's R16-2 probe since 2b-repair-18: a proxy no longer chooses where the connection goes (an admitted address does), so that probe's withdrawn origin has none to be sent to
             old=HANDLER_LINE, new="urllib.request.HTTPErrorProcessor(), urllib.request.ProxyHandler()):"),
    *(Mutation(f"2B17-the-{kind}-handler-is-back", "2b-17", f"the opener has the {kind} handler again", (HANDLERS,), target=CLI,
               old=HANDLER_LINE, new=f"urllib.request.HTTPErrorProcessor(), urllib.request.{handler}()):")
      for kind, handler in (("ftp", "FTPHandler"), ("file", "FileHandler"), ("data", "DataHandler"), ("unknown-scheme", "UnknownHandler"))),
    Mutation("2B17-the-global-opener-is-used", "2b-17", "an exchange goes through urllib's process-wide opener (whatever is installed there, or its defaults)",
             (DIRECT + "test_no_global_opener_is_used_or_installed",), target=CLI,
             old="        with _opener(_Deadline(timeout), admitted).open(req, timeout=timeout) as resp:",
             new="        with urllib.request.urlopen(req, timeout=timeout) as resp:"),
    Mutation("2B17-the-scheme-gate-is-gone", "2b-17", "the transport hands a URL of any scheme to the opener",
             (DIRECT + "test_a_url_that_is_not_http_or_https_is_refused_before_anything_is_built_or_opened",), target=CLI, old="    if not supported:\n", new="    if False:\n"),
    # the endpoint forms
    Mutation("2B17-another-scheme-is-an-endpoint", "2b-17", "a base URL of any scheme is accepted", (FORM_REFUSALS,), target=CLI, old='r"(https?)://(?:\\[', new='r"([a-z]+)://(?:\\['),
    Mutation("2B17-credentials-in-the-url-are-accepted", "2b-17", "a base URL with credentials in it is accepted (2b-repair-18: the origin form takes a userinfo it then ignores)", (FORM_REFUSALS,), target=CLI,
             old='r"(https?)://(?:\\[', new='r"(https?)://(?:[^/@]*@)?(?:\\['),
    Mutation("2B17-a-url-without-a-host-is-an-endpoint", "2b-17", "a base URL with no host is accepted (2b-repair-18: an empty host, which is an empty label, is a name)", (FORM_REFUSALS,), target=CLI,
             old='|([a-z0-9.-]+))(?::', new='|([a-z0-9.-]*))(?::',
             also=(("all(_LABEL.fullmatch(label) for label in labels)", 'all(label == "" or _LABEL.fullmatch(label) for label in labels)'),)),
    Mutation("2B17-the-endpoint-can-be-changed", "2b-17", "the client's base URL can be assigned after construction, so its requests and its addresses can name different hosts",
             (FORMS + "test_the_supported_forms_are_accepted_and_fixed",), target=CLI,
             old="    @property\n    def base_url(self) -> str:\n        return self._base_url\n",
             new='    base_url = property(lambda self: self._base_url, lambda self, value: setattr(self, "_base_url", value))\n'),
]
