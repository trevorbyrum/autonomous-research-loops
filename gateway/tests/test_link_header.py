"""Task 2b-repair-8 R7-1: a Link header that cannot be read is never an end.

Hugging Face pages by its `Link: <url>; rel="next"` header (RFC 8288); no next link is the end. The reader
that preceded this one split every header on commas, quoted ones included, so a valid header
(`<...>; title="next, page"; rel="next"`) lost its relation, and the adapter read the missing link as the end of
the listing. The cause was that "no next link was found" meant two things at once: the header was read and
names none (an established absence), and the header was not read. Reading now has three outcomes
(base.NextLink): a next URL; a header read whole that names none, which is the end; and a header that could
not be read, or names several different next pages, which is neither.

Oracles are written by hand from RFC 8288 §3 (the grammar, "rel" first-occurrence-wins, relation types as a
space-separated list) and RFC 9110 §5.3 (repeated field lines are one list-valued field). What these cases
cannot show: that the Hub still sends what its own client expects (Phase 4's canary).
"""
from __future__ import annotations

import email.message
import http.server
import threading
import unittest

from research_gateway import adapters
from research_gateway.adapters import huggingface
from research_gateway.adapters.base import Client, FakeTransport, LinkSyntax, NextLink, Response, Transport, header_map, next_link, parse_links
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.registry.load import read_seed
from tests import test_adapters_datasets as datasets

ASKED = "https://huggingface.co/api/datasets?search=q&limit=2&full=true"
NEXT = "https://huggingface.co/api/datasets?search=q&limit=2&full=true&cursor=eyJfaWQiOiI2NTAwIn0"
PREV = "https://huggingface.co/api/datasets?search=q&limit=2&full=true&cursor=prev"


def read(header: str | None) -> NextLink:
    return next_link(Response(200, {} if header is None else {"link": header}, b"[]", ASKED))


class Reading(unittest.TestCase):
    def test_a_next_link_is_found_however_the_header_is_written(self):
        cases = {
            "the plain form": f'<{NEXT}>; rel="next"',
            "a comma inside a quoted parameter, before rel (the reported header)": f'<{NEXT}>; title="next, page"; rel="next"',
            "a comma inside a quoted parameter, after rel": f'<{NEXT}>; rel="next"; title="next, page"',
            "a semicolon and an escaped quote inside a quoted parameter": f'<{NEXT}>; title="a; rel=\\"prev\\", b"; rel="next"',
            "an unquoted relation": f"<{NEXT}>; rel=next",
            "no space after the semicolon": f'<{NEXT}>;rel="next"',
            "spaces around the equals sign": f'<{NEXT}> ; rel = "next"',
            "a parameter name in capitals and a relation in capitals": f'<{NEXT}>; REL="Next"',
            "next among several relation types": f'<{NEXT}>; rel="prev next"',
            "next after another link": f'<{PREV}>; rel="prev", <{NEXT}>; rel="next"',
            "next before another link": f'<{NEXT}>; rel="next", <{PREV}>; rel="prev"',
            "next after another link whose parameter holds a comma": f'<{PREV}>; title="x, y"; rel="prev", <{NEXT}>; rel="next"',
            "three links, next in the middle": f'<{PREV}>; rel="first", <{NEXT}>; rel="next", <{PREV}>; rel="last"',
            "the same next link twice": f'<{NEXT}>; rel="next", <{NEXT}>; rel="next"',
            "an extended parameter": f"<{NEXT}>; title*=UTF-8''next%20page; rel=\"next\"",
            "several spaces between relation types": f'<{NEXT}>; rel="prev   next"',
            "an extension relation beside next": f'<{NEXT}>; rel="https://example.org/rels/other next"',
            "a quoted-pair in a descriptive parameter": f'<{NEXT}>; title="a \\"quoted\\" \\\\ word"; rel="next"',
            "a tab inside a quoted string, which RFC 9110 allows": f'<{NEXT}>; title="a\tb"; rel="next"',
            "empty list elements": f',, <{NEXT}>; rel="next",',
            "the first rel only counts, and it says next": f'<{NEXT}>; rel="next"; rel="prev"',
            "an extension parameter with no value": f'<{NEXT}>; ext; rel="next"',
        }
        for name, header in cases.items():
            with self.subTest(name):
                self.assertEqual(read(header), NextLink(NEXT, True))

    def test_a_comma_inside_the_target_belongs_to_the_target(self):
        self.assertEqual(read(f'<{NEXT},more>; rel="next"'), NextLink(NEXT + ",more", True))

    def test_a_relative_target_is_resolved_against_the_url_asked(self):
        self.assertEqual(read('</api/datasets?search=q&cursor=n>; rel="next"'),
                         NextLink("https://huggingface.co/api/datasets?search=q&cursor=n", True))

    def test_a_header_read_whole_that_names_no_next_link_is_an_established_end(self):
        cases = {
            "no Link header": None,
            "an empty header": "",
            "only empty list elements": ", ,",
            "only a back link": f'<{PREV}>; rel="prev"',
            "a link with no parameters": f"<{NEXT}>",
            "a title that merely says next": f'<{NEXT}>; title="next"',
            "a relation that only starts with next": f'<{NEXT}>; rel="nextpage"',
            "next said only by a later rel, which does not count (RFC 8288 §3.3)": f'<{NEXT}>; rel="prev"; rel="next"',
            "next said by another parameter": f'<{NEXT}>; type="rel=next"',
            "an extension relation, which is a URI (RFC 8288 §2.1.2)": f'<{NEXT}>; rel="https://example.org/rels/next"',
            "relations that only contain next": f'<{NEXT}>; rel="a.next next-page"',
            "a relation that is a registered name, in capitals": f'<{NEXT}>; rel="PREV"',
        }
        for name, header in cases.items():
            with self.subTest(name):
                self.assertEqual(read(header), NextLink(None, True))

    def test_a_header_that_cannot_be_read_is_neither_a_next_link_nor_the_end(self):
        cases = {
            "a target that is not closed": f'<{NEXT}; rel="next"',
            "no angle brackets": f'{NEXT}; rel="next"',
            "a quoted string that is not closed": f'<{NEXT}>; title="next; rel="next"',
            "junk after a link": f'<{NEXT}>; rel="next" junk',
            "junk between links": f'<{PREV}>; rel="prev" ; <{NEXT}>; rel="next"',
            "an empty parameter": f'<{NEXT}>;; rel="next"',
            "a trailing semicolon": f'<{NEXT}>; rel="next";',
            "a parameter value that is not a token or a quoted string": f"<{NEXT}>; rel=next/page",
            "a relation with no value": f"<{NEXT}>; rel",
            "a relation quoted with apostrophes, which no grammar here reads": f"<{NEXT}>; rel='next'",
            "a relation with quote characters of its own (R8-1)": f'<{NEXT}>; rel="\\"next\\""',
            "an empty relation (R8-1)": f'<{NEXT}>; rel=""',
            "a comma in a relation (R8-1)": f'<{NEXT}>; rel="next, prev"',
            "a control character in a relation (R8-1)": f'<{NEXT}>; rel="next\x01"',
            "a control character in a parameter that is not the relation": f'<{NEXT}>; title="a\x01b"; rel="prev"',
            "a space at either end of the relation list": f'<{NEXT}>; rel=" next"',
            "a relation that starts with a digit": f'<{NEXT}>; rel="1next"',
            "a relation that is neither a name nor a URI": f'<{NEXT}>; rel="ne;xt"',
            "a quoted-pair with nothing to quote": f'<{NEXT}>; title="a\\',
            "a target that is no URI reference": f"<{NEXT} x>; rel=\"next\"",
            "two different next pages": f'<{NEXT}>; rel="next", <{PREV}>; rel="next"',
            "a next page whose target is no URL": '<http://[bad>; rel="next"',
            "an unreadable link after a readable next one": f'<{NEXT}>; rel="next", <{PREV}',
        }
        for name, header in cases.items():
            with self.subTest(name):
                self.assertEqual(read(header), NextLink(None, False))

    def test_the_parser_hands_back_every_link_with_its_parameters(self):
        self.assertEqual(parse_links(f'<{PREV}>; Rel="prev"; title="a, \\"b\\""; hreflang=en, <{NEXT}>;rel=next'),
                         [(PREV, [("rel", "prev"), ("title", 'a, "b"'), ("hreflang", "en")]), (NEXT, [("rel", "next")])])
        with self.assertRaises(LinkSyntax):
            parse_links('<x>; title="open')


class Uris(unittest.TestCase):
    """Task 2b-repair-10b, R9-1 (Astra): a target and a URI-form relation type are what RFC 3986's grammar says, not what avoids a list of characters. The
    grammar itself is tests/test_uri.py's; what is stated here is what the reading of a header does with it. Independent vectors for the whole reading are
    tests/test_oracle.py's."""
    BROKEN = ("https://example.org/%GG", "https://example.org/%", "https://[broken", "https://example.org/\u00e9", "https://[::1]x/", "https://example.org:80a/",
              "https://example.org/#a#b")   # (a space is no part of a relation type: it separates two, so `https://example.org/a b` is two valid ones)

    def test_a_relation_type_that_is_not_a_uri_is_unreadable_not_another_relation(self):
        for target in self.BROKEN:
            with self.subTest(target):
                self.assertEqual(read(f'<{NEXT}>; rel="{target}"'), NextLink(None, False))
                self.assertEqual(read(f'<{PREV}>; rel="prev", <{NEXT}>; rel="next {target}"'), NextLink(None, False))

    def test_a_target_that_is_not_a_uri_reference_is_unreadable_wherever_it_stands(self):
        for target in (*self.BROKEN, "https://example.org/a b"):
            with self.subTest(target):
                self.assertEqual(read(f'<{target}>; rel="prev"'), NextLink(None, False))
                self.assertEqual(read(f'<{target}>; rel="next"'), NextLink(None, False))
                with self.assertRaises(LinkSyntax):
                    parse_links(f"<{target}>; rel=prev")

    def test_control_the_relation_types_and_targets_that_are_uris_are_read(self):
        for rel in ("https://example.org/rels/next", "urn:example:next", "https://example.org/r%41", "https://[::1]/r", "https://example.org/r?x#f", "a:"):
            with self.subTest(rel):
                self.assertEqual(read(f'<{PREV}>; rel="{rel}"'), NextLink(None, True))
                self.assertEqual(read(f'<{NEXT}>; rel="next {rel}"'), NextLink(NEXT, True))
        for target in ("https://example.org/a%7e", "https://[2001:db8::1]/x", "//example.org/x", "../up", "?q=1", "#frag", "mailto:x@example.org"):
            with self.subTest(target):
                self.assertEqual(read(f'<{target}>; rel="prev"'), NextLink(None, True))


class Context(unittest.TestCase):
    """RFC 8288 §3.1 (a relative target is resolved as RFC 3986 §5 says), §3.2 (an `anchor` puts a link's context elsewhere), and a continuation that does not
    move on: asking the request's own URL again is the same page, which is a lower bound and not an end."""
    ITSELF = ("", ASKED, "?search=q&limit=2&full=true", "/api/datasets?search=q&limit=2&full=true", "//huggingface.co/api/datasets?search=q&limit=2&full=true",
              ASKED + "#frag", "HTTPS://HUGGINGFACE.CO:443/api/datasets?search=q&limit=2&full=true", "datasets?search=q&limit=2&full=true")

    def test_a_relative_target_is_resolved_the_way_the_rfc_says(self):
        for target, want in (("/api/datasets?search=q&cursor=n", "https://huggingface.co/api/datasets?search=q&cursor=n"),
                             ("//huggingface.co/api/datasets?search=q&cursor=n", "https://huggingface.co/api/datasets?search=q&cursor=n"),
                             ("datasets?search=q&cursor=n", "https://huggingface.co/api/datasets?search=q&cursor=n"),
                             ("?search=q&cursor=n", "https://huggingface.co/api/datasets?search=q&cursor=n"),
                             ("./datasets?search=q&cursor=n", "https://huggingface.co/api/datasets?search=q&cursor=n"),
                             ("../api/datasets?search=q&cursor=n", "https://huggingface.co/api/datasets?search=q&cursor=n")):
            with self.subTest(target):
                self.assertEqual(read(f'<{target}>; rel="next"'), NextLink(want, True))

    def test_a_next_link_that_is_the_request_itself_is_neither_followed_nor_an_end(self):
        for target in self.ITSELF:
            with self.subTest(target):
                self.assertEqual(read(f'<{target}>; rel="next"'), NextLink(None, False))
                self.assertEqual(read(f'<{NEXT}>; rel="next", <{target}>; rel="next"'), NextLink(None, False), "two next pages, one of which goes nowhere")
        self.assertEqual(read(f'<{ASKED}>; rel="prev"'), NextLink(None, True), "a link to itself that is not a next link is nothing")

    def test_a_next_link_whose_context_is_another_resource_is_neither_followed_nor_an_end(self):
        for anchor in ("https://other.example/ctx", "#foo", "https://huggingface.co/api/models", ASKED + "#foo", "other"):
            for header in (f'<{NEXT}>; rel="next"; anchor="{anchor}"', f'<{NEXT}>; anchor="{anchor}"; rel="next"'):
                with self.subTest(header):
                    self.assertEqual(read(header), NextLink(None, False))

    def test_an_anchor_that_is_the_request_changes_nothing_and_one_that_is_not_a_uri_makes_the_header_unreadable(self):
        for anchor in (ASKED, "", "?search=q&limit=2&full=true", "/api/datasets?search=q&limit=2&full=true"):
            with self.subTest(anchor):
                self.assertEqual(read(f'<{NEXT}>; rel="next"; anchor="{anchor}"'), NextLink(NEXT, True))
        for header in (f'<{NEXT}>; rel="next"; anchor', f'<{NEXT}>; rel="next"; anchor="%GG"', f'<{PREV}>; rel="prev"; anchor="https://[broken"',
                       f"<{NEXT}>; rel=next; anchor=a b"):
            with self.subTest(header):
                self.assertEqual(read(header), NextLink(None, False))

    def test_an_anchor_on_a_link_that_is_not_next_is_not_this_listings_end_or_beginning(self):
        self.assertEqual(read(f'<{PREV}>; rel="prev"; anchor="https://other.example/"'), NextLink(None, True))

    def test_a_next_link_to_itself_is_a_lower_bound_through_the_router(self):
        c, _ = HuggingFace().client(f'<{ASKED}>; rel="next"', items=2)
        out = R.execute(R.Router(read_seed(), adapters.load_all()), HuggingFace.FIND, c)
        lane = out["lanes"][0]
        self.assertEqual((lane["coverage"], lane["completeness"], lane.get("error_class"), lane.get("next"), lane.get("exhausted")),
                         ("searched_ok", "partial", "partial_pagination", None, None))
        self.assertNotIn("huggingface", out.get("next") or {})


class RepeatedFieldLines(unittest.TestCase):
    """A provider may send its links as several `Link` lines. They are one field (RFC 9110 §5.3): a transport that
    kept the last line dropped the others, and with them a next link the header did carry."""

    def test_repeated_lines_are_joined_in_order(self):
        message = email.message.Message()
        message["Link"] = f'<{PREV}>; rel="prev"'
        message["Link"] = f'<{NEXT}>; rel="next"'
        message["Content-Type"] = "application/json"
        self.assertEqual(header_map(message), {"link": f'<{PREV}>; rel="prev", <{NEXT}>; rel="next"', "content-type": "application/json"})

    def test_the_real_transport_keeps_every_link_line(self):
        class Serves(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                for line in self.server.lines:
                    self.send_header("Link", line)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"[]")

            def log_message(self, *args):
                pass

        for lines, want in (([f'<{PREV}>; rel="prev"', f'<{NEXT}>; rel="next"'], NextLink(NEXT, True)),
                            ([f'<{NEXT}>; rel="next"', f'<{PREV}>; rel="prev"'], NextLink(NEXT, True)),
                            ([f'<{PREV}>; rel="prev"'], NextLink(None, True))):
            with self.subTest(lines=lines):
                server = http.server.HTTPServer(("127.0.0.1", 0), Serves)   # loopback: no provider, no network
                server.lines = lines
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    resp = Transport().request("GET", f"http://127.0.0.1:{server.server_port}/", {}, None, 5)
                finally:
                    server.shutdown()
                    server.server_close()
                self.assertEqual(next_link(Response(resp.status, resp.headers, resp.body, ASKED)), want)


class HuggingFace(unittest.TestCase):
    """The adapter and the router on the same headers."""
    FIND = {"request_type": "find", "query": "q", "kind": "dataset", "domain": "ai-ml", "lanes": ["huggingface"],
            "accept_per_item": True, "limit": 2}
    UNREADABLE = (f'<{NEXT}; rel="next"', f'<{NEXT}>; rel="next" junk', f'<{NEXT}>; title="open; rel="next"', f"<{NEXT}>; rel='next'",
                  f'<{NEXT}>; rel="next", <{PREV}>; rel="next"', f'<{NEXT}>; rel',
                  # R8-1 (Astra): relations that are no relation-type list, decoded from a quoted string that itself reads
                  f'<{NEXT}>; rel="\\"next\\""', f'<{NEXT}>; rel=""', f'<{NEXT}>; rel="next, prev"', f'<{NEXT}>; rel="next\x01"')

    def client(self, link: str | None, items: int = 1) -> tuple[Client, FakeTransport]:
        t = FakeTransport()
        t.add("GET", ASKED.split("?")[0], body=[datasets.HF_DATASET] * items, headers={"Link": link} if link is not None else None)
        return Client(broker=Broker({"huggingface": RatePolicy(per_second=1000)}), transport=t, secrets=lambda name, field=None: None), t

    def lane(self, link: str | None, items: int = 1) -> tuple[dict, dict]:
        c, _ = self.client(link, items)
        out = R.execute(R.Router(read_seed(), adapters.load_all()), self.FIND, c)
        return out, {k: out["lanes"][0].get(k) for k in ("coverage", "completeness", "count", "error_class", "next", "exhausted")}

    def test_a_next_link_with_a_quoted_comma_continues_through_the_router(self):
        """Astra's reproduction (R7-1): the page was called complete and exhausted, count one."""
        for link in (f'<{NEXT}>; title="next, page"; rel="next"', f'<{PREV}>; rel="prev", <{NEXT}>; title="x, y"; rel="next"'):
            with self.subTest(link):
                out, lane = self.lane(link)
                self.assertEqual(lane, {"coverage": "searched_ok", "completeness": "complete", "count": 1, "error_class": None,
                                        "next": NEXT, "exhausted": None})
                self.assertEqual(out["next"], {"huggingface": NEXT})

    def test_the_next_page_of_a_header_with_a_quoted_comma_is_asked_at_that_url(self):
        c, _ = self.client(f'<{NEXT}>; title="next, page"; rel="next"', items=2)
        first = huggingface.find(c, "q", limit=2)
        c, t = self.client(None)
        t.routes.clear()
        t.add("GET", NEXT, body=[datasets.HF_DATASET])
        huggingface.find(c, "q", limit=2, cursor=first["next_cursor"])
        self.assertEqual([call[1] for call in t.calls], [NEXT])

    def test_a_header_that_cannot_be_read_never_ends_the_lane(self):
        """The assertion that fails when a parse failure is taken for an absence: no header here may be called
        the end, and none is a continuation either — a lower bound, the page's records kept."""
        for link in self.UNREADABLE:
            with self.subTest(link):
                c, _ = self.client(link, items=2)
                out = huggingface.find(c, "q", limit=2)
                self.assertEqual((out["exhausted"], out["next_cursor"], len(out["records"])), (False, None, 2))
                routed, lane = self.lane(link)
                self.assertEqual(lane, {"coverage": "searched_ok", "completeness": "partial", "count": 1,
                                        "error_class": "partial_pagination", "next": None, "exhausted": None})
                self.assertNotIn("huggingface", routed.get("next") or {}, "no sentinel: nothing says the lane returned everything")

    def test_control_a_header_read_whole_with_no_next_link_is_the_end(self):
        for link in (None, "", f'<{PREV}>; rel="prev"', f'<{PREV}>; rel="https://example.org/rels/next"', f'<{PREV}>; rel="prev   first"'):
            with self.subTest(link):
                out, lane = self.lane(link)
                self.assertEqual(lane, {"coverage": "searched_ok", "completeness": "complete", "count": 1, "error_class": None,
                                        "next": None, "exhausted": True})
                self.assertEqual(out["next"], {"huggingface": R.EXHAUSTED_CURSOR})

    def test_a_next_link_that_names_no_search_is_not_the_continuation(self):
        """A continuation must name the search it continues (found by the invariant harness's generated headers): a next link without the `search`
        parameter would list some other population, so it is neither followed as a continuation nor taken for the end, and a cursor like it is never asked."""
        target = "https://huggingface.co/api/datasets?limit=2&full=true&cursor=x"
        c, t = self.client(f'<{target}>; rel="next"', items=2)
        out = huggingface.find(c, "q", limit=2)
        self.assertEqual((out["exhausted"], out["next_cursor"], len(out["records"])), (False, None, 2))
        with self.assertRaises(ValueError):
            huggingface.find(c, "q", limit=2, cursor=target)
        self.assertEqual(len(t.calls), 1, "the second request was never made")

    def test_a_next_link_that_leaves_the_search_is_still_refused_with_a_quoted_comma(self):
        """URL and credential validation is kept: the parser reads the link, own_link decides whether it is followed."""
        for target in ("https://evil.example/api/datasets?search=q&cursor=x", "https://user:pw@huggingface.co/api/datasets?search=q&cursor=x"):
            with self.subTest(target):
                c, _ = self.client(f'<{target}>; title="next, page"; rel="next"', items=2)
                out = huggingface.find(c, "q", limit=2)
                self.assertEqual((out["exhausted"], out["next_cursor"]), (False, None))


if __name__ == "__main__":
    unittest.main()
