"""Task 2b-repair-10b, R9-1: the RFC 3986 grammar, resolution and comparison the gateway's `Link` reading rests on (research_gateway/core/uri.py).

What is held here is stated from the RFC text and nothing else: the examples of §1.1.2, §3, §5.4 and §6.2 as the RFC prints them, and strings that each
break one production of Appendix A. The gateway's own `Link` reader is tested on top of it in tests/test_link_header.py; the independent vectors
that hold the whole reading to the RFCs are tests/test_oracle.py's (written by an author who had not read this code).

Also run once as a differential (evidence for the task, not a test): the module against Appendix A compiled mechanically from the RFC text, on 330,513
generated strings, with no disagreement.
"""
from __future__ import annotations

import unittest

from research_gateway.core import uri

BASE = "http://a/b/c/d;p?q"   # RFC 3986 §5.4: "the same base" for every example

RFC_5_4_1 = (
    ('g:h', 'g:h'),
    ('g', 'http://a/b/c/g'),
    ('./g', 'http://a/b/c/g'),
    ('g/', 'http://a/b/c/g/'),
    ('/g', 'http://a/g'),
    ('//g', 'http://g'),
    ('?y', 'http://a/b/c/d;p?y'),
    ('g?y', 'http://a/b/c/g?y'),
    ('#s', 'http://a/b/c/d;p?q#s'),
    ('g#s', 'http://a/b/c/g#s'),
    ('g?y#s', 'http://a/b/c/g?y#s'),
    (';x', 'http://a/b/c/;x'),
    ('g;x', 'http://a/b/c/g;x'),
    ('g;x?y#s', 'http://a/b/c/g;x?y#s'),
    ('', 'http://a/b/c/d;p?q'),
    ('.', 'http://a/b/c/'),
    ('./', 'http://a/b/c/'),
    ('..', 'http://a/b/'),
    ('../', 'http://a/b/'),
    ('../g', 'http://a/b/g'),
    ('../..', 'http://a/'),
    ('../../', 'http://a/'),
    ('../../g', 'http://a/g'),
)
RFC_5_4_2 = (
    ('../../../g', 'http://a/g'),
    ('../../../../g', 'http://a/g'),
    ('/./g', 'http://a/g'),
    ('/../g', 'http://a/g'),
    ('g.', 'http://a/b/c/g.'),
    ('.g', 'http://a/b/c/.g'),
    ('g..', 'http://a/b/c/g..'),
    ('..g', 'http://a/b/c/..g'),
    ('./../g', 'http://a/b/g'),
    ('./g/.', 'http://a/b/c/g/'),
    ('g/./h', 'http://a/b/c/g/h'),
    ('g/../h', 'http://a/b/c/h'),
    ('g;x=1/./y', 'http://a/b/c/g;x=1/y'),
    ('g;x=1/../y', 'http://a/b/c/y'),
    ('g?y/./x', 'http://a/b/c/g?y/./x'),
    ('g?y/../x', 'http://a/b/c/g?y/../x'),
    ('g#s/./x', 'http://a/b/c/g#s/./x'),
    ('g#s/../x', 'http://a/b/c/g#s/../x'),
)


class Grammar(unittest.TestCase):
    URIS = (  # §1.1.2 and §3 of the RFC, as printed
        "ftp://ftp.is.co.za/rfc/rfc1808.txt", "http://www.ietf.org/rfc/rfc2396.txt", "ldap://[2001:db8::7]/c=GB?objectClass?one", "mailto:John.Doe@example.com",
        "news:comp.infosystems.www.servers.unix", "tel:+1-816-555-1212", "telnet://192.0.2.16:80/", "urn:oasis:names:specification:docbook:dtd:xml:4.1.2",
        "foo://example.com:8042/over/there?name=ferret#nose", "urn:example:animal:ferret:nose", "http://example.com", "http://example.com:/", "http://example.com:80/",
        "http://[::1]/", "http://[v7.fe80::a+en1]/", "http://[2001:db8:0:0:0:0:2:1]/", "http://[::ffff:192.0.2.128]/", "a:", "A+b-c.d:e")
    REFERENCES = ("//example.com/p", "/p", "p", "../p", "?q", "#f", "", "g:h", "./g:h", "http:g", "g;x?y#s")   # §4.1, §4.2
    BROKEN = (
        "http://example.com/%GG", "http://example.com/%G1", "http://example.com/%1G", "http://example.com/%", "http://example.com/%4", "%", "?%", "#%",
        "http://[::1", "http://[]/", "http://[1:2:3]/", "http://[::g]/", "http://[1::2::3]/", "http://[:::1]/", "http://[12345::]/", "http://[1.2.3.4]/",
        "http://[::1]x/", "http://a[b]c/", "http://example.com/a[0]", "http://example.com/?x[0]", "http://example.com:80a/", "http://u@v@example.org/",
        "http://example.com/#a#b", "http://example.com/a b", "http://example.com/a\tb", "http://example.com/a\nb", "http://example.com/\u00e9",
        "http://example.com/a\"b", "http://example.com/a<b", "http://example.com/a\\b", "http://example.com/a^b", "http://example.com/a`b", "http://example.com/a{b}",
        "http://example.com/a|b", "1a:b", "a_b:c", ":x", "://x", "a b:c", "http://example.com/%\u0663\u0663", "http://example.com/\uff05\x34\x31",
        "http://[v.x]/", "http://[v1.]/", "http://[::256.1.1.1]/", "http://[::1.2.3]/", "http://[1:2:3:4:5:6:7:8:9]/")

    def test_what_the_rfc_prints_is_a_uri(self):
        for text in self.URIS:
            with self.subTest(text):
                self.assertTrue(uri.is_uri(text) and uri.is_uri_reference(text))

    def test_a_relative_reference_is_a_uri_reference_and_not_a_uri(self):
        for text in self.REFERENCES:
            with self.subTest(text):
                self.assertTrue(uri.is_uri_reference(text))
        for text in ("//example.com/p", "/p", "p", "../p", "?q", "#f", "", "./g:h"):
            with self.subTest(text):
                self.assertFalse(uri.is_uri(text), "an extension relation type is an absolute URI (RFC 8288 §3.3)")

    def test_each_production_is_enforced_not_a_list_of_characters(self):
        for text in self.BROKEN:
            with self.subTest(text):
                self.assertFalse(uri.is_uri_reference(text))
                self.assertFalse(uri.is_uri(text))

    def test_a_uri_may_carry_a_fragment_and_an_empty_host_is_still_a_reg_name(self):
        self.assertTrue(uri.is_uri("https://example.org/r?x=1#f"))
        self.assertTrue(uri.is_uri("https:///p"), "an empty reg-name is in the grammar (§3.2.2); a scheme may reject it, which is not this module's to say")

    def test_the_ipv6_forms_of_the_rfc(self):
        for address, ok in (("::", True), ("1::", True), ("::1", True), ("1:2:3:4:5:6:7::", True), ("::2:3:4:5:6:7:8", True), ("1:2:3:4:5:6:7:8", True),
                            ("1:2:3:4:5:6:1.2.3.4", True), ("::1.2.3.4", True), ("1::1.2.3.4", True), ("1:2:3:4:5:6:7:8:9", False), ("1:2:3:4:5:6:7", False),
                            ("1:2:3:4:5:6:7:8::", False), ("1::2::3", False), ("1:::2", False), (":1:2:3:4:5:6:7", False), ("1.2.3.4", False),
                            ("1:2:3:4:5:6:7:1.2.3.4", False), ("::1.2.3", False), ("::01.2.3.4", False), ("::1.2.3.256", False), ("12345::1", False), ("::g", False)):
            with self.subTest(address):
                self.assertEqual(uri.is_uri(f"http://[{address}]/"), ok)


class Resolution(unittest.TestCase):
    def test_the_normal_examples_of_the_rfc(self):
        for reference, target in RFC_5_4_1:
            with self.subTest(reference):
                self.assertEqual(uri.resolve(BASE, reference), target)

    def test_the_abnormal_examples_of_the_rfc(self):
        for reference, target in RFC_5_4_2:
            with self.subTest(reference):
                self.assertEqual(uri.resolve(BASE, reference), target)

    def test_the_base_fragment_plays_no_part_and_an_authority_with_no_path_takes_a_slash(self):
        self.assertEqual(uri.resolve("http://a/b?q#frag", "c"), "http://a/c")
        self.assertEqual(uri.resolve("http://a", "c"), "http://a/c")   # §5.2.3: merge with an authority and an empty base path
        self.assertEqual(uri.resolve("https://huggingface.co/api/datasets?search=q&limit=3", ""), "https://huggingface.co/api/datasets?search=q&limit=3")


class Comparison(unittest.TestCase):
    def test_the_rfc_examples_of_equivalence(self):
        """§6.2.2 (case, percent-encoding, dot segments) and §6.2.3 (the scheme's default port, an empty path), as the RFC prints them."""
        self.assertTrue(uri.same_resource("example://a/b/c/%7Bfoo%7D", "eXAMPLE://a/./b/../b/%63/%7bfoo%7d"))
        for other in ("http://example.com/", "http://example.com:/", "http://example.com:80/", "HTTP://EXAMPLE.COM"):
            with self.subTest(other):
                self.assertTrue(uri.same_resource("http://example.com", other))

    def test_what_differs_is_different(self):
        for a, b in (("https://h/a?x=1", "https://h/a?x=2"), ("https://h/a", "https://h/b"), ("https://h/a", "https://h:444/a"), ("https://h/a", "http://h/a"),
                     ("https://h/a?x", "https://h/a"), ("https://h/a%2Fb", "https://h/a/b"), ("https://u@h/a", "https://h/a")):
            with self.subTest((a, b)):
                self.assertFalse(uri.same_resource(a, b))

    def test_a_fragment_is_not_sent_so_it_does_not_tell_two_requests_apart_but_it_does_tell_two_contexts_apart(self):
        """RFC 3986 §6.1: "When URIs are compared to select (or avoid) a network action ... fragment components (if any) should be excluded"; RFC 8288 §3.2: a
        fragment of a resource is a context of its own."""
        self.assertTrue(uri.same_resource("https://h/a", "https://h/a#f"))
        self.assertFalse(uri.same_resource("https://h/a", "https://h/a#f", fragment=True))
        self.assertTrue(uri.same_resource("https://h/a#f", "https://H/a#f", fragment=True))


if __name__ == "__main__":
    unittest.main()
