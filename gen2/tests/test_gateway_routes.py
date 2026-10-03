"""The gateway client goes directly to its endpoint over http or https and nowhere else (task 2b-repair-17; Gate D #3 checklist 2, and the route inventory §3).

The standard library's default opener has routes of its own: a proxy handler that reads the environment (any case of `http_proxy`/`https_proxy`, `no_proxy`, and the CGI `REQUEST_METHOD` rule),
redirects, authentication and cookie handlers, FTP, file and data handlers, and a process-wide opener. Astra's R16-2 reproduced the first carrying a withdrawn origin's search, and token, to an
unrelated listener through a proxy; the Gate D #3 inventory found an FTP-valued proxy re-dispatching into the FTP handler, which resolved a name inside a 0.02 s exchange for 0.151 s.
The client now builds its own opener from the HTTP handlers alone; these tests are what make that a claim about behaviour and not about one line of code. The witnesses are listeners the test owns:
what each was sent (the exact request line, so a proxy's absolute-form request is visible; the bearer token; how many requests), and a spy on every way a name could be looked up or a file opened.
"""
from __future__ import annotations

import http.client
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from gen2.gateway_client import client as gateway
from gen2.gateway_client.client import GatewayClient, http_transport
from gen2.tests.gateway_wire import (EMPTY_AND_EXHAUSTED, EMPTY_LANE, FIND, INV, STAMP, TOKEN, Recorder, admitted, gateway_script, job, lookup, observed, queued_answer,
                                     reply, unobserved)
from gen2.tests.loopback import ThreadsJoined

SEARCH = dict(invocation_id=INV, attempt=1, policy_version="gw-policy/1")
FAST = dict(clock=lambda: STAMP, sleep=lambda s: None)
WHERE = "{port}"   # the proxy's port, in an environment value

# every way an environment can name a proxy, and every way it can say not to use one: none of them is a route for this client
HOSTILE = (
    ("no proxy variable at all (the control)", {}),
    ("lower-case http_proxy", {"http_proxy": "http://127.0.0.1:" + WHERE}),
    ("upper-case HTTP_PROXY", {"HTTP_PROXY": "http://127.0.0.1:" + WHERE}),
    ("mixed-case Http_Proxy", {"Http_Proxy": "http://127.0.0.1:" + WHERE}),
    ("both cases", {"http_proxy": "http://127.0.0.1:" + WHERE, "HTTP_PROXY": "http://127.0.0.1:" + WHERE}),
    ("CGI: REQUEST_METHOD set, the lower-case one survives", {"http_proxy": "http://127.0.0.1:" + WHERE, "REQUEST_METHOD": "GET"}),
    ("CGI: REQUEST_METHOD set, the upper-case one is ignored", {"HTTP_PROXY": "http://127.0.0.1:" + WHERE, "REQUEST_METHOD": "GET"}),
    ("no_proxy naming another host", {"http_proxy": "http://127.0.0.1:" + WHERE, "no_proxy": "elsewhere.example"}),
    ("no_proxy naming the gateway", {"http_proxy": "http://127.0.0.1:" + WHERE, "no_proxy": "gateway.test,127.0.0.1"}),
    ("NO_PROXY=*", {"http_proxy": "http://127.0.0.1:" + WHERE, "NO_PROXY": "*"}),
    ("all_proxy", {"all_proxy": "http://127.0.0.1:" + WHERE, "ALL_PROXY": "http://127.0.0.1:" + WHERE}),
    ("ftp_proxy", {"ftp_proxy": "http://127.0.0.1:" + WHERE}),
    ("an FTP-valued http_proxy", {"http_proxy": "ftp://127.0.0.1:" + WHERE}),
    ("a proxy with credentials in its URL", {"http_proxy": "http://user:secret@127.0.0.1:" + WHERE}),
    ("a SOCKS-valued http_proxy", {"http_proxy": "socks5://127.0.0.1:" + WHERE}),
)


def environment(env: dict, port: int):
    """Exactly this environment, and nothing else in it."""
    return mock.patch.dict(os.environ, {name: value.replace(WHERE, str(port)) for name, value in env.items()}, clear=True)


class NoNameIsLookedUp:
    """The ways a name could be looked up by the standard library during an exchange (`socket.gethostbyname` is what its FTP handler calls; getaddrinfo what everything else does): each raises at
    once, so that an exchange that tries is a failed test, and each call is recorded."""

    def __enter__(self):
        self.calls: list = []

        def forbidden(name):
            def look(*args, **kw):
                self.calls.append((name, args))
                raise AssertionError(f"socket.{name}{args}: a name was looked up during an exchange")
            return look
        self.patches = [mock.patch.object(socket, name, forbidden(name)) for name in ("gethostbyname", "getaddrinfo")]
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self.patches:
            patch.stop()


class RouteTest(ThreadsJoined):
    def searching(self, c: GatewayClient) -> dict:
        """`c`'s search. One that raises (a mutant that reaches a handler the client has no business with can raise from deep in urllib) is a failed test, not an error in it."""
        try:
            return c.search(FIND, **SEARCH)
        except BaseException as e:
            self.fail(f"the search raised {e!r}")


class DirectHttpOnly(RouteTest):
    """What the environment says about proxies is not read; what a reply says about where to go is not followed; and the client's one door is the endpoint it was configured with."""

    def search_through(self, env: dict, *, named: bool, poll: bool, proxy: Recorder, destination: Recorder):
        """One search by a fresh client in exactly this environment: (what it observed, the requests the destination was sent by it)."""
        before = destination.count
        with environment(env, proxy.port), NoNameIsLookedUp() as names:
            if named:
                c = GatewayClient(f"http://gateway.test:{destination.port}", TOKEN, resolver=lookup("127.0.0.1", port=destination.port), **FAST)
            else:
                c = GatewayClient(f"http://127.0.0.1:{destination.port}", TOKEN, **FAST)
            out = self.searching(c)
        self.assertEqual(names.calls, [], "nothing was looked up by an exchange")
        return observed(out), destination.hits[before:]

    def test_a_hostile_environment_changes_nothing_about_where_a_search_goes(self):
        """Astra's R16-2 as a matrix: for every environment above, a search over a name and over an IP literal, straight and queued (its poll too), reaches the destination listener directly (its origin-form
        request line, not a proxy's absolute form, with the Host header the endpoint's own and the bearer token), exactly once per request, and the proxy the environment names is never so much as
        connected to. The `no proxy variable` rows are the positive controls: the same assertions with nothing hostile in the environment."""
        proxy = Recorder(self)
        destinations = {False: Recorder(self, gateway_script()), True: Recorder(self, gateway_script(poll=True))}
        for label, env in HOSTILE:
            for named in (True, False):
                for poll in (False, True):
                    with self.subTest(environment=label, named=named, poll=poll):
                        destination, proxied = destinations[poll], proxy.count
                        observation, hits = self.search_through(env, named=named, poll=poll, proxy=proxy, destination=destination)
                        lines = [head.split(b"\r\n")[0].decode() for head, _ in hits]
                        self.assertEqual(lines, ["POST /v1/find HTTP/1.1"] + (["GET /v1/jobs/1 HTTP/1.1"] if poll else []), "the exact destination, and one request for each")
                        host = f"Host: gateway.test:{destination.port}" if named else f"Host: 127.0.0.1:{destination.port}"
                        self.assertTrue(all(host.encode() in head and f"Authorization: Bearer {TOKEN}".encode() in head for head, _ in hits), "the endpoint's own Host, and the token")
                        self.assertEqual(observation, EMPTY_AND_EXHAUSTED)
                        self.assertEqual(proxy.count - proxied, 0, "the proxy the environment names was never connected to")

    def test_a_grant_goes_the_same_way(self):
        proxy, destination = Recorder(self), Recorder(self, gateway_script())
        with environment({"http_proxy": "http://127.0.0.1:" + WHERE, "HTTP_PROXY": "http://127.0.0.1:" + WHERE}, proxy.port):
            try:
                token = GatewayClient(f"http://127.0.0.1:{destination.port}", TOKEN, **FAST).grant(topic_id="topic_1", commercial=False, accept_per_item=False, invocation_id=INV)["token"]
            except BaseException as e:
                self.fail(f"the grant raised {e!r}")
        self.assertEqual((token, destination.request_lines, destination.carrying(), proxy.count), ("gwg1.synthetic", ["POST /v1/grants HTTP/1.1"], 1, 0))

    def test_a_zero_padded_port_reaches_the_listener_it_names(self):
        """Astra's R18-1 on the wire: `http://127.0.0.1:037433` and `http://127.0.0.1:37433` are one endpoint. Each searches its own test-owned listener, once, with the canonical Host (no padding)."""
        for padded in (False, True):
            with self.subTest(padded=padded):
                destination = Recorder(self, gateway_script())
                url = f"http://127.0.0.1:{str(destination.port).zfill(6) if padded else destination.port}"
                try:
                    c = GatewayClient(url, TOKEN, **FAST)
                except ValueError as e:
                    self.fail(f"{url} names port {destination.port} and was refused: {e}")
                self.assertEqual(observed(self.searching(c)), EMPTY_AND_EXHAUSTED)
                self.assertEqual((destination.request_lines, destination.carrying(), f"Host: 127.0.0.1:{destination.port}".encode() in destination.hits[0][0]), (["POST /v1/find HTTP/1.1"], 1, True))

    def test_a_redirect_is_never_followed_whatever_the_status_and_wherever_it_points(self):
        """Same-origin as well as cross-origin, absolute and relative, for each of the five statuses, on a request and on a poll: the Location is never requested, the other listener is sent nothing,
        and the answer is no answer (a redirect is no gateway answer). A request is made exactly once (a POST that was redirected is not repeated at its destination, which would carry the token)."""
        elsewhere = Recorder(self, gateway_script())
        state = {"code": 302, "location": "", "poll": False}

        def redirect(server, conn, head, body, index):
            if state["poll"] and head.startswith(b"POST"):
                server.send(conn, [(0, queued_answer())])
                return
            server.send(conn, [(0, f"HTTP/1.1 {state['code']} Redirect\r\nLocation: {state['location']}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())])
        for code in (301, 302, 303, 307, 308):
            for label in ("same-origin, absolute", "same-origin, relative", "same-origin, scheme-relative", "another origin"):
                for poll in (False, True):
                    with self.subTest(code=code, location=label, poll=poll):
                        origin = Recorder(self, redirect)   # one for each case: a poll that gave up leaves its last request to arrive late, and that must not be read as the next case's
                        location = {"same-origin, absolute": f"http://127.0.0.1:{origin.port}/v1/other", "same-origin, relative": "/v1/other",
                                    "same-origin, scheme-relative": f"//127.0.0.1:{origin.port}/v1/other", "another origin": f"http://127.0.0.1:{elsewhere.port}/v1/find"}[label]
                        state.update(code=code, location=location, poll=poll)
                        c = GatewayClient(f"http://127.0.0.1:{origin.port}", TOKEN, deadline=0.2, **FAST)
                        out = self.searching(c)
                        lines = origin.request_lines
                        self.assertEqual(observed(out), unobserved("timeout" if poll else "transport_failure"))
                        self.assertEqual([line for line in lines if "/v1/other" in line], [], "the destination of a redirect was never requested")
                        self.assertEqual(elsewhere.count, 0, "and nothing went to another origin")
                        self.assertEqual(lines[0], "POST /v1/find HTTP/1.1")
                        if not poll:
                            self.assertEqual(lines, ["POST /v1/find HTTP/1.1"], "once")
                        else:
                            self.assertTrue(all(line in ("POST /v1/find HTTP/1.1", "GET /v1/jobs/1 HTTP/1.1") for line in lines), lines)

    def test_an_authentication_challenge_is_not_answered_and_a_cookie_is_not_sent_back(self):
        """401 with a Basic challenge and 407 with a proxy challenge are one request each, never repeated with credentials; a Set-Cookie is not replayed to the next exchange, or to the poll of the same
        search; and no request carries a credential but the bearer token."""
        def raw(status, body, extra=""):
            return (f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nX-Research-Gateway: result\r\nContent-Length: {len(body)}\r\n{extra}Connection: close\r\n\r\n").encode() + body
        mode = {"now": "401"}

        def script(server, conn, head, body, index):
            if mode["now"] == "401":
                server.send(conn, [(0, raw("401 Unauthorized", b'{"error": "no"}', 'WWW-Authenticate: Basic realm="gateway"\r\n'))])
            elif mode["now"] == "407":
                server.send(conn, [(0, raw("407 Proxy Authentication Required", b'{"error": "no"}', 'Proxy-Authenticate: Basic realm="proxy"\r\n'))])
            elif head.startswith(b"POST"):
                server.send(conn, [(0, raw("200 OK", queued_answer().split(b"\r\n\r\n", 1)[1], "Set-Cookie: session=synthetic; Path=/\r\n"))])
            else:
                server.send(conn, [(0, raw("200 OK", job("done", [EMPTY_LANE]), "Set-Cookie: second=synthetic\r\n"))])
        listener = Recorder(self, script)
        c = GatewayClient(f"http://127.0.0.1:{listener.port}", TOKEN, **FAST)
        for status, expected in (("401", ("auth_failed", "unobserved", None, "failed", "credentials_rejected")), ("407", unobserved("transport_failure"))):
            with self.subTest(status=status):
                mode["now"], before = status, listener.count
                self.assertEqual(observed(self.searching(c)), expected)
                self.assertEqual(listener.count - before, 1, "no second request: the challenge was not answered")
        mode["now"], before = "cookie", listener.count
        self.assertEqual(observed(self.searching(c)), EMPTY_AND_EXHAUSTED)
        self.assertEqual(observed(self.searching(c)), EMPTY_AND_EXHAUSTED)
        sent = listener.hits[before:]
        self.assertEqual(len(sent), 4, "two searches, each its request and its poll")
        for head, _ in sent:
            self.assertNotIn(b"Cookie:", head)
            self.assertEqual([line for line in head.split(b"\r\n") if line.lower().startswith((b"authorization", b"proxy-authorization"))], [f"Authorization: Bearer {TOKEN}".encode()])

    def test_no_global_opener_is_used_or_installed(self):
        """A process-wide opener (urllib.request.install_opener, or urlopen's default) would carry its own handlers. A sentinel installed as the global one is never asked, and what is installed is untouched."""
        asked = []

        class Sentinel(urllib.request.OpenerDirector):
            def open(self, *args, **kw):
                asked.append(args)
                raise OSError("the global opener must not be used")
        sentinel, saved = Sentinel(), urllib.request._opener
        urllib.request.install_opener(sentinel)
        self.addCleanup(urllib.request.install_opener, saved)
        listener = Recorder(self, gateway_script())
        self.assertEqual(observed(self.searching(GatewayClient(f"http://127.0.0.1:{listener.port}", TOKEN, **FAST))), EMPTY_AND_EXHAUSTED)
        self.assertEqual((asked, urllib.request._opener is sentinel, listener.count), ([], True, 1))

    def test_the_opener_has_the_http_handlers_and_nothing_else(self):
        """The fixed handler inventory: HTTP and HTTPS, the default error handler (a status that is not a success is an HTTPError) and the error processor. Nothing that reads the environment,
        follows, authenticates, keeps cookies, or speaks FTP, file, data or an unknown scheme."""
        with environment({"http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9", "ftp_proxy": "http://127.0.0.1:9"}, 9):   # a proxy handler registers itself only for what the environment names
            handlers = gateway._opener(gateway._Deadline(1), ()).handlers
        self.assertEqual(sorted(type(h).__name__ for h in handlers), ["HTTPDefaultErrorHandler", "HTTPErrorProcessor", "Http", "Https"])
        for kind in (urllib.request.ProxyHandler, urllib.request.HTTPRedirectHandler, urllib.request.UnknownHandler, urllib.request.FTPHandler, urllib.request.FileHandler,
                     urllib.request.DataHandler, urllib.request.HTTPCookieProcessor, urllib.request.AbstractBasicAuthHandler, urllib.request.AbstractDigestAuthHandler):
            self.assertFalse([h for h in handlers if isinstance(h, kind)], kind.__name__)
        for attribute in ("proxies", "cookiejar", "passwd"):
            self.assertFalse([h for h in handlers if hasattr(h, attribute)], attribute)

    def test_a_url_that_is_not_http_or_https_is_refused_before_anything_is_built_or_opened(self):
        """The transport's own scheme gate: an FTP, file, data, gopher or schemeless URL is a transport failure at once. No name is looked up for it, no file is read, and no listener is connected to."""
        secret = Path(tempfile.mkdtemp(prefix="gen2-routes-")) / "secret.txt"
        self.addCleanup(shutil.rmtree, secret.parent, True)
        secret.write_text("synthetic file content")
        listener = Recorder(self)
        real_open, opened = open, []

        def spying_open(file, *args, **kw):
            opened.append(str(file))
            return real_open(file, *args, **kw)
        failure = (None, {}, b"", "transport_failure")
        urls = (f"ftp://127.0.0.1:{listener.port}/x", f"file://{secret}", "data:text/plain;base64,c3ludGhldGlj", "gopher://127.0.0.1/x", "gateway:8765/v1/find", "//127.0.0.1/x", "", "http://[::1/")
        with NoNameIsLookedUp() as names, mock.patch("builtins.open", spying_open):
            for url in urls:
                with self.subTest(url=url):
                    try:
                        got = http_transport("GET", url, {}, None, 1.0)
                    except BaseException as e:   # a mutant that lets it through raises from deep in urllib: that is a failure, not an error
                        self.fail(f"raised {e!r}")
                    self.assertEqual(got, failure)
        self.assertEqual((names.calls, [path for path in opened if str(secret) in path], listener.count), ([], [], 0))
        port = Recorder(self, gateway_script()).port
        self.assertEqual(http_transport("GET", f"HTTP://127.0.0.1:{port}/v1/jobs/1", {"Accept": "application/json"}, None, 1.0, admitted=admitted(port))[0], 200,
                         "the control: an http URL, in any case, is the transport's business")

    def test_a_request_hosts_spelling_is_never_a_connection_target(self):
        """Astra's R17-1, at the transport. urllib unquotes the host of a request (`127.0.0.%31` is `127.0.0.1` to it), and the transport once tried that decoded host as an address before it looked at what
        its caller admitted: with the endpoint withdrawn, a listener there was sent the request and the bearer token. The target is only ever an admitted address, so with none admitted, or with only
        one that goes nowhere, a request whose host urllib reads as the listener's own address reaches the listener not at all, whatever it is spelled."""
        listener = Recorder(self, gateway_script())
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))
        elsewhere = dead.getsockname()[1]
        dead.close()
        failure = (None, {}, b"", "transport_failure")
        with NoNameIsLookedUp():
            for spelling in ("127.0.0.%31", "%31%32%37.0.0.1", "127.%30.0.%31", "127.0.0.1", "[::ffff:127.0.0.1]", "localhost", "%6c%6f%63%61%6c%68%6f%73%74"):
                for where, addresses in (("nothing admitted", ()), ("only an address that goes nowhere", admitted(elsewhere))):
                    with self.subTest(host=spelling, admitted=where):
                        try:
                            got = http_transport("GET", f"http://{spelling}:{listener.port}/v1/jobs/1", {"Authorization": f"Bearer {TOKEN}"}, None, 1.0, admitted=addresses)
                        except BaseException as e:   # a mutant that connects somewhere unexpected is caught here, by assertion
                            self.fail(f"raised {e!r}")
                        self.assertEqual((got, listener.count), (failure, 0), "no connection, no request and no token reached the listener the request's host spells")

    def test_control_the_admitted_address_is_connected_to_whatever_host_the_request_names(self):
        """The same transport, an address admitted: it connects there and the request keeps its own host (the Host header; over TLS, the server name). A name, a literal and an encoded literal as the
        request's host all go to the admitted address, which is the listener, not to where the host reads."""
        listener = Recorder(self, gateway_script())
        with NoNameIsLookedUp():
            for spelling in ("gateway.test", "127.0.0.1", "127.0.0.%31", "%67ateway.test"):
                with self.subTest(host=spelling):
                    before = listener.count
                    status, headers, raw, error = http_transport("GET", f"http://{spelling}:{listener.port}/v1/jobs/1", {"Authorization": f"Bearer {TOKEN}"}, None, 1.0,
                                                                  admitted=admitted(listener.port))
                    self.assertEqual((status, error, listener.count - before), (200, None, 1))
        self.assertEqual(listener.carrying(), 4)


class TheEndpointForms(ThreadsJoined):
    """`base_url` is an http or https URL whose host is a name or an IP literal, with no credentials; anything else is refused when the client is built, before any I/O, and the endpoint never changes."""

    def test_an_endpoint_that_is_not_an_http_or_https_host_without_credentials_is_refused_before_any_io(self):
        resolver = mock.Mock(side_effect=AssertionError("a lookup was made"))

        def refuses(url, transport):
            try:
                GatewayClient(url, TOKEN, resolver=resolver, transport=transport)
            except ValueError:
                return
            except BaseException as e:   # a mutant that lets the URL through fails somewhere else: that is a failure of this test, not an error in it
                self.fail(f"{url!r}: {e!r}, not a ValueError")
            self.fail(f"{url!r} was accepted")
        refused = ("ftp://gateway:8765", "file:///etc/hosts", "data:text/plain,x", "gopher://gateway", "ws://gateway:8765", "gateway:8765", "gateway", "", "//gateway:8765",
                   "http://", "https://:8443", "http://user@gateway:8765", "http://user:secret@gateway:8765", "http://gateway:99999", "http://gateway:eight", "https://gateway.test:8443/api/")
        with mock.patch.object(gateway._DeadlineSocket, "connect", side_effect=AssertionError("a connection was made")) as connect, NoNameIsLookedUp():
            for url in refused:
                for transport in (None, lambda *a: (200, {}, b"", None)):
                    with self.subTest(url=url, transport=bool(transport)):
                        refuses(url, transport)
        resolver.assert_not_called()
        connect.assert_not_called()

    def test_the_supported_forms_are_accepted_and_fixed(self):
        for url, base in (("http://gateway:8765", "http://gateway:8765"), ("HTTP://GATEWAY:8765/", "http://gateway:8765"), ("https://gateway.test:8443/", "https://gateway.test:8443"),
                          ("http://127.0.0.1:1", "http://127.0.0.1:1"), ("http://[::1]:8765", "http://[::1]:8765"), ("http://gateway", "http://gateway")):
            with self.subTest(url=url):
                c = GatewayClient(url, TOKEN, resolver=lookup("10.0.0.5"), **FAST)
                self.assertEqual(c.base_url, base)
                with self.assertRaises(AttributeError):
                    c.base_url = "http://elsewhere:1"   # a client's endpoint is fixed for its life: its addresses are this one's
                self.assertEqual(c.base_url, base)

    # Every spelling below is one that the standard library, a resolver or a person could read as a different host, or a different place, than another reader of the same string does; the endpoint
    # forms are the ones all of them read alike. Task 2b-repair-18 (Astra's R17-1: `127.0.0.%31`, accepted as a name, was the address 127.0.0.1 to urllib).
    REFUSED_SPELLINGS = {
        "percent-encoding": ("http://127.0.0.%31:8765", "http://%31%32%37.0.0.1:8765", "http://127.%30.0.%31", "http://gate%77ay:8765", "http://gateway%2etest:8765", "http://gateway%00:8765",
                             "http://%67ateway", "http://gateway%", "http://[::%31]:8765", "http://127.0.0.1%2f@gateway"),
        "an alternate numeric spelling of an address": ("http://0x7f.1:8765", "http://0x7f.0.0.1:8765", "http://0x7f000001:8765", "http://0X7F000001", "http://2130706433:8765", "http://017700000001:8765",
                                                          "http://0177.0.0.1:8765", "http://0177.0.0.01", "http://127.1:8765", "http://127.0.1:8765", "http://127.000.000.001:8765",
                                                          "http://127.0.0.01:8765", "http://1.2.3:8765", "http://1.2.3.4.5:8765", "http://0x:8765", "http://0:8765", "http://4294967295",
                                                          "http://256.0.0.1:8765", "http://127.0.0.1.:8765", "http://127.0.0.0x1:8765"),
        "credentials": ("http://user@127.0.0.1:8765", "http://user:secret@gateway:8765", "http://127.0.0.1@gateway:8765", "http://gateway:80@127.0.0.1:8765", "http://:@gateway", "http://@gateway",
                        "http://gateway@", "http://user@[::1]:8765", "http://gateway\\@127.0.0.1"),
        "a port that is not a decimal number from 1 to 65535": ("http://gateway:0", "http://gateway:65536", "http://gateway:99999", "http://gateway:123456", "http://gateway:eight", "http://gateway:",
                                                                "http://gateway:-1", "http://gateway:+80", "http://gateway:0x50", "http://gateway: 80", "http://gateway:8765:8765",
                                                                "http://gateway:\uff18\uff10", "http://127.0.0.1:",
                                                                "http://gateway:000000", "http://gateway:" + "0" * 32, "http://gateway:065536", "http://gateway:" + "0" * 27 + "65536", "http://gateway:" + "0" * 32 + "80",
                                                                "http://gateway:00x80", "http://gateway:-00080", "http://gateway:\u0668\u0660", "http://gateway:00\uff18\uff10"),
        "a path, query or fragment": ("http://gateway:8765/api", "http://gateway:8765/api/", "http://gateway:8765//", "http://gateway:8765/?x=1", "http://gateway:8765?x=1", "http://gateway:8765#frag",
                                      "http://gateway:8765/#", "http://gateway/%2e%2e/", "http://gateway:8765;params"),
        "a host that is not a DNS name of LDH labels": ("http://gate_way:8765", "http://-gateway:8765", "http://gateway-:8765", "http://gate way:8765", "http://a..b:8765", "http://.gateway:8765",
                                                          "http://gateway.:8765", "http://gateway..test", "http://." , "http://gat\u00e9way.example", "http://b\u00fccher.example",
                                                          "http://\uff47ateway", "http://\uff11\uff12\uff17.0.0.1", "http://gateway$", "http://gateway*", "http://gate!way", "http://gateway\\x",
                                                          "http://" + "a" * 64 + ".example", "http://" + ".".join(["a" * 63] * 4), "http://xn--:8765", "http://x\u200bgateway"),
        "an IPv6 literal that is not one, or not in brackets": ("http://::1", "http://::1:8765", "http://[::1", "http://::1]", "http://[::1]x", "http://[::1]:", "http://[]", "http://[::g]",
                                                                 "http://[1::2::3]", "http://[127.0.0.1]", "http://[gateway]", "http://[::1%25eth0]:8765", "http://[fe80::1%31]:8765",
                                                                 "http://[fe80::1%eth0]", "http://[::1]/x", "http://[[::1]]", "http://[1:2:3:4:5:6:7:8:9]", "http://[::ffff:127.0.0.256]"),
        "a scheme that is not http or https, or not a scheme at all": ("ftp://gateway:8765", "ftps://gateway", "file:///etc/hosts", "data:text/plain,x", "ws://gateway:8765", "gopher://gateway",
                                                                    "httpx://gateway", "http:gateway", "http:/gateway", "http:///gateway", "http:\\\\gateway", "http//gateway", "://gateway", "gateway:8765"),
        "whitespace or a control character": (" http://gateway:8765", "http://gateway:8765 ", "http://gateway:8765\n", "http://gateway:8765\r\n", "http://gate\tway", "http://gate\nway", "http://gate\rway",
                                              "\thttp://gateway", "http://gateway:8765\x00", "http://gateway:87\t65", "\x00http://gateway"),
        "nothing, or no host": ("", "http://", "https://", "http://:8765", "https://:8443", "http:///", "//gateway:8765", "/"),
    }

    def refuses(self, url: str, transport) -> None:
        try:
            GatewayClient(url, TOKEN, resolver=self.resolver, transport=transport)
        except ValueError:
            return
        except BaseException as e:   # a mutant that lets the URL through fails somewhere else: that is a failure of this test, not an error in it
            self.fail(f"{url!r}: {e!r}, not a ValueError")
        self.fail(f"{url!r} was accepted")

    def test_every_spelling_a_reader_could_take_another_way_is_refused_before_any_io(self):
        """Each, with the real transport and with a stand-in one, is a ValueError at construction with no lookup made and no socket asked to connect; so is the same spelling with a path after it."""
        self.resolver = mock.Mock(side_effect=AssertionError("a lookup was made"))
        with mock.patch.object(gateway._DeadlineSocket, "connect", side_effect=AssertionError("a connection was made")) as connect, NoNameIsLookedUp():
            for kind, spellings in self.REFUSED_SPELLINGS.items():
                for url in spellings:
                    for transport in (None, lambda *a: (200, {}, b"", None)):
                        with self.subTest(kind=kind, url=url, transport=bool(transport)):
                            self.refuses(url, transport)
        self.resolver.assert_not_called()
        connect.assert_not_called()

    def test_the_forms_that_are_accepted_are_one_canonical_origin_that_urllib_and_the_owner_read_alike(self):
        """The other half of the one-representation claim. Each accepted spelling comes out as its canonical origin (lower case; an IPv6 literal compressed; the scheme's default port left off; a number
        for the port; no trailing slash), and for each, the standard library's own reading of a request URL built from it (urlsplit's hostname and port, and the host urllib's Request hands the
        connection after it unquotes it) is what the owner holds: nothing in it for urllib to decode into another host. A literal's address is admitted at construction; a name admits none until its lookup."""
        accepted = (("http://gateway:8765", "http://gateway:8765", "gateway", 8765, ()), ("HTTP://GATEWAY:8765/", "http://gateway:8765", "gateway", 8765, ()),
                    ("https://Gateway.Test:8443", "https://gateway.test:8443", "gateway.test", 8443, ()), ("http://gateway", "http://gateway", "gateway", 80, ()),
                    ("https://gateway:443/", "https://gateway", "gateway", 443, ()), ("http://gateway:80", "http://gateway", "gateway", 80, ()), ("http://gateway:08765", "http://gateway:8765", "gateway", 8765, ()),
                    ("http://localhost:1", "http://localhost:1", "localhost", 1, ()), ("http://xn--bcher-kva.example:9", "http://xn--bcher-kva.example:9", "xn--bcher-kva.example", 9, ()),
                    ("http://1gateway.example", "http://1gateway.example", "1gateway.example", 80, ()), ("http://127.0.0.1.nip.example:7", "http://127.0.0.1.nip.example:7", "127.0.0.1.nip.example", 7, ()),
                    ("http://0x7f.example", "http://0x7f.example", "0x7f.example", 80, ()), ("http://a-b.c-d:65535", "http://a-b.c-d:65535", "a-b.c-d", 65535, ()),
                    ("http://" + ".".join(["a" * 63] * 3 + ["b" * 61]) + ":3", "http://" + ".".join(["a" * 63] * 3 + ["b" * 61]) + ":3", ".".join(["a" * 63] * 3 + ["b" * 61]), 3, ()),
                    ("http://127.0.0.1:1", "http://127.0.0.1:1", "127.0.0.1", 1, (("127.0.0.1", 1),)), ("http://255.255.255.255", "http://255.255.255.255", "255.255.255.255", 80, (("255.255.255.255", 80),)),
                    ("http://[::1]:8765", "http://[::1]:8765", "::1", 8765, (("::1", 8765, 0, 0),)), ("https://[0:0:0:0:0:0:0:1]:443/", "https://[::1]", "::1", 443, (("::1", 443, 0, 0),)),
                    ("http://[FE80::ABCD]:2", "http://[fe80::abcd]:2", "fe80::abcd", 2, (("fe80::abcd", 2, 0, 0),)), ("http://[::ffff:127.0.0.1]:5", "http://[::ffff:7f00:1]:5", "::ffff:7f00:1", 5, (("::ffff:7f00:1", 5, 0, 0),)))
        for url, base, host, port, targets in accepted:
            with self.subTest(url=url):
                c = GatewayClient(url, TOKEN, resolver=lookup(), **FAST)   # a lookup that finds nothing: a name has no address until one is found
                self.assertEqual((c.base_url, c._endpoint.host, c._endpoint.port, tuple(info[4] for info in c._endpoint.addresses)), (base, host, port, targets))
                self.assertEqual(c.endpoint_stale, not targets, "a literal is its own address, authorized from construction; a name has none until a lookup finds some")
                request = urllib.request.Request(c.base_url + "/v1/find")
                connection = (http.client.HTTPSConnection if c._endpoint.scheme == "https" else http.client.HTTPConnection)(request.host)
                split = urllib.parse.urlsplit(c.base_url + "/v1/find")
                self.assertEqual(((split.hostname, split.port or connection.default_port), (connection.host, connection.port), urllib.parse.unquote(request.host) == request.host),
                                 ((host, port), (host, port), True), "urlsplit and http.client read the host and port the owner holds, and urllib has nothing to decode")

    def test_a_decimal_port_is_checked_by_its_value_not_by_its_width(self):
        """Astra's R18-1: H-6 specifies a decimal port from 1 to 65535 (RFC 3986 `port = *DIGIT`), and `:08765` was already accepted, but a regex of at most five digits refused `:000080`, `:065535` and
        `:000443`, the same ports. Each of her five cases, and the longest run the contract allows (32 digits), is accepted as its canonical origin; a construction that raises is a failed test here."""
        for url, base, host, port in (("http://gateway.test:00080", "http://gateway.test", "gateway.test", 80), ("http://gateway.test:000080", "http://gateway.test", "gateway.test", 80),
                                      ("https://GATEWAY.TEST:000443/", "https://gateway.test", "gateway.test", 443), ("http://gateway.test:065535", "http://gateway.test:65535", "gateway.test", 65535),
                                      ("https://[0:0:0:0:0:0:0:1]:000443/", "https://[::1]", "::1", 443), ("http://127.0.0.1:000001", "http://127.0.0.1:1", "127.0.0.1", 1),
                                      ("http://127.0.0.1:037433", "http://127.0.0.1:37433", "127.0.0.1", 37433), ("http://gateway:" + "0" * 30 + "80", "http://gateway", "gateway", 80),
                                      ("http://gateway:" + "0" * 27 + "65535", "http://gateway:65535", "gateway", 65535)):
            with self.subTest(url=url):
                try:
                    c = GatewayClient(url, TOKEN, resolver=lookup(), **FAST)
                except ValueError as e:
                    self.fail(f"port {port} is in 1..65535 and was refused: {e}")
                self.assertEqual((c.base_url, c._endpoint.host, c._endpoint.port), (base, host, port))


@unittest.skipUnless(shutil.which("openssl"), "a TLS server needs a certificate, which the openssl command line makes")
class DirectHttpsOnly(RouteTest):
    """The same for TLS: an https_proxy would be a CONNECT tunnel to a host the withdrawn endpoint no longer controls. The environment names one and the proxy is never connected to; the TLS exchange
    goes straight to the endpoint, and the certificate is still checked against, and the server name still is, the hostname."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = Path(tempfile.mkdtemp(prefix="gen2-routes-tls-"))
        cls.cert, cls.key = str(cls.dir / "cert.pem"), str(cls.dir / "key.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-days", "1", "-subj", "/CN=gateway.test",
                        "-addext", "subjectAltName=DNS:gateway.test", "-keyout", cls.key, "-out", cls.cert], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_a_hostile_environment_changes_nothing_about_where_a_tls_search_goes(self):
        proxy = Recorder(self)
        destination = Recorder(self, gateway_script(), tls=(self.cert, self.key))
        names = []
        destination.server._tls.sni_callback = lambda sock, name, context: names.append(name)
        cases = (("no proxy variable at all (the control)", {}), ("https_proxy", {"https_proxy": "http://127.0.0.1:" + WHERE}), ("HTTPS_PROXY", {"HTTPS_PROXY": "http://127.0.0.1:" + WHERE}),
                 ("both cases", {"https_proxy": "http://127.0.0.1:" + WHERE, "HTTPS_PROXY": "http://127.0.0.1:" + WHERE}),
                 ("CGI, lower-case", {"https_proxy": "http://127.0.0.1:" + WHERE, "REQUEST_METHOD": "GET"}),
                 ("no_proxy naming the gateway", {"https_proxy": "http://127.0.0.1:" + WHERE, "no_proxy": "gateway.test"}),
                 ("an FTP-valued https_proxy", {"https_proxy": "ftp://127.0.0.1:" + WHERE}), ("a proxy with credentials", {"https_proxy": "http://user:secret@127.0.0.1:" + WHERE}))
        for label, env in cases:
            with self.subTest(environment=label):
                before, proxied = destination.count, proxy.count
                with environment({**env, "SSL_CERT_FILE": self.cert}, proxy.port), NoNameIsLookedUp() as lookups:
                    c = GatewayClient(f"https://gateway.test:{destination.port}", TOKEN, resolver=lookup("127.0.0.1", port=destination.port), **FAST)
                    out = self.searching(c)
                self.assertEqual((observed(out), destination.request_lines[before:], destination.carrying(), proxy.count - proxied, lookups.calls),
                                 (EMPTY_AND_EXHAUSTED, ["POST /v1/find HTTP/1.1"], len(destination.hits), 0, []))
                self.assertEqual(names[-1], "gateway.test", "the server name sent is the hostname")


if __name__ == "__main__":
    unittest.main()
