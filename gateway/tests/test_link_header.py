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
            "empty list elements": f',, <{NEXT}>; rel="next",',
            "the first rel only counts, and it says next": f'<{NEXT}>; rel="next"; rel="prev"',
            "a parameter with no value": f'<{NEXT}>; anchor; rel="next"',
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
                  f'<{NEXT}>; rel="next", <{PREV}>; rel="next"', f'<{NEXT}>; rel')

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
        for link in (None, "", f'<{PREV}>; rel="prev"'):
            with self.subTest(link):
                out, lane = self.lane(link)
                self.assertEqual(lane, {"coverage": "searched_ok", "completeness": "complete", "count": 1, "error_class": None,
                                        "next": None, "exhausted": True})
                self.assertEqual(out["next"], {"huggingface": R.EXHAUSTED_CURSOR})

    def test_a_next_link_that_leaves_the_search_is_still_refused_with_a_quoted_comma(self):
        """URL and credential validation is kept: the parser reads the link, own_link decides whether it is followed."""
        for target in ("https://evil.example/api/datasets?search=q&cursor=x", "https://user:pw@huggingface.co/api/datasets?search=q&cursor=x"):
            with self.subTest(target):
                c, _ = self.client(f'<{target}>; title="next, page"; rel="next"', items=2)
                out = huggingface.find(c, "q", limit=2)
                self.assertEqual((out["exhausted"], out["next_cursor"]), (False, None))


if __name__ == "__main__":
    unittest.main()
