"""A second reader for `Link` headers (RFC 8288 §3, RFC 9110 §5.6.1 and §5.6.4), and a generator of headers for it to read.

The harness compares the gateway's reader with this one on generated headers. The two read differently: the gateway's (adapters/base.parse_links) steps
through the header character by character; this one is written from the grammars' productions as regular expressions, and never calls it. That is a
second implementation by the same authors, and it is NOT an independent oracle: 2b-repair-9's review (R9-1) found both accepting `%GG`, a trailing `%`
and `https://[broken` as a URI, because they shared the rule for what a URI is. The URI productions are therefore not written here any more: they are
the oracle's transcription of RFC 3986 Appendix A (tests/oracle/link_vectors.py: `URI`, `URI_REFERENCE`, checked there against the RFC text). What
holds the gateway's reading to the RFCs is tests/test_oracle.py's vectors, hand-labelled from the RFC text by an author who had not read the gateway;
this reader only keeps the generated headers honest against each other.

    Link         = #link-value                                     (RFC 9110: empty list elements are ignored)
    link-value   = "<" URI-Reference ">" *( OWS ";" OWS link-param )
    link-param   = token [ BWS "=" BWS ( token / quoted-string ) ]
    quoted-string = DQUOTE *( qdtext / quoted-pair ) DQUOTE        qdtext = HTAB / SP / %x21 / %x23-5B / %x5D-7E / obs-text
    rel          = relation-type / DQUOTE relation-type *( 1*SP relation-type ) DQUOTE        (RFC 8288 §3.3)
    relation-type = reg-rel-type / ext-rel-type
    reg-rel-type = LOALPHA *( LOALPHA / DIGIT / "." / "-" )        ext-rel-type = URI

What a header says is `("unknown",)` — it does not read through, a `rel` is not a relation-type list, or it names two different
next pages — or `("known", the set of targets whose first `rel` lists `next`)`: known, with no next link, is the end. (A next link to the request itself
or one whose `anchor` is another resource is the gateway's to leave out: the generated headers carry neither.)
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from tests.oracle import link_vectors as oracle

TCHAR = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]"
TOKEN = rf"{TCHAR}+"
QUOTED = r'"(?:[\t \x21\x23-\x5b\x5d-\x7e\x80-\xff]|\\[\t \x21-\x7e\x80-\xff])*"'
OWS = r"[ \t]*"
PARAM = rf"{OWS};{OWS}({TOKEN})(?:{OWS}={OWS}({TOKEN}|{QUOTED}))?"
URI_REFERENCE = oracle.URI_REFERENCE.pattern   # RFC 3986 Appendix A, not a list of characters
LINK_VALUE = re.compile(rf"<({URI_REFERENCE})>((?:{PARAM})*){OWS}")
PARAMS = re.compile(PARAM)
REL_TYPE = rf"(?:[A-Za-z][A-Za-z0-9.\-]*|{oracle.URI.pattern})"
REL_LIST = re.compile(rf"{REL_TYPE}(?: +{REL_TYPE})*")
SEPARATORS = re.compile(r"[ \t]*(?:,[ \t]*)*")


def unquote(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text[1:-1], flags=re.S)


def read(header: str) -> tuple:
    """What `header` says, as ("unknown",) or ("known", frozenset of next targets)."""
    at, nexts = 0, set()
    while True:
        at = SEPARATORS.match(header, at).end()
        if at == len(header):
            break
        link = LINK_VALUE.match(header, at)
        if link is None:
            return ("unknown",)
        at = link.end()
        if at < len(header) and header[at] != ",":
            return ("unknown",)
        first = next(((n.lower(), v) for n, v in PARAMS.findall(link.group(2)) if n.lower() == "rel"), None)
        if first is None:
            continue
        value = first[1]
        if value == "":
            return ("unknown",)          # `rel` with no value at all
        text = unquote(value) if value.startswith('"') else value
        if REL_LIST.fullmatch(text) is None:
            return ("unknown",)
        if "next" in text.lower().split(" "):
            nexts.add(link.group(1))
    return ("known", frozenset(nexts)) if len(nexts) <= 1 else ("unknown",)


def stays_in_the_search(url: str) -> bool:
    """Whether a next link may be followed as this search's continuation: the Hub's own listing, this search, nothing else."""
    u = urlsplit(url)
    return (u.scheme, u.netloc, u.path) == ("https", "huggingface.co", "/api/datasets") and parse_qs(u.query).get("search") == ["q"] and not u.fragment


# ------------------------------------------------------------------ headers to read
OWN = "https://huggingface.co/api/datasets?search=q&limit=3&full=true"
TARGETS_NEXT = [OWN + "&cursor=a1", OWN + "&cursor=b%2Bc", OWN + "&cursor=x,y", OWN + "&cursor=eyJfaWQiOiI2NTAwIn0"]
TARGETS_OTHER = [OWN + "&cursor=prev", "https://huggingface.co/api/datasets?search=q&limit=3&full=true&cursor=first", "https://example.org/elsewhere"]
DESCRIPTIVE = ['title="next, page"', 'title="a; rel=\\"prev\\", b"', 'title="x"', 'type="text/html"', "hreflang=en", "ext", "title*=UTF-8''n%20p",
               'title="\\\\"', 'title=""', 'title="rel=next"', 'title="a\x01b"', 'title="\x7f"', 'title="tab\there"', 'title="caf\xe9"']
RELATIONS = ['rel="next"', "rel=next", 'rel="prev next"', 'rel="next prev"', 'rel="NEXT"', "rel=prev", 'rel="prev"', 'rel="first last"',
             'rel="https://example.org/rels/next"', 'rel="nextpage"', 'rel="https://example.org/rel next"', 'rel="a.b-c1 next"', 'rel="next  prev"',
             # what is not a relation-type list: stray quotes, nothing, a comma, a control character, another quoting, a space too many
             'rel="\\"next\\""', 'rel=""', 'rel="next, prev"', 'rel="next\x01"', "rel='next'", 'rel=" next"', 'rel="next "', "rel", 'rel="a\\"b"',
             'rel="next\\\x01"', 'rel="http://x y"', 'rel="1next"', 'rel="ne;xt"', 'rel="next"junk', 'rel="next', 'rel=next/page', 'rel="-next"', 'rel="next"x']
# damage to a header, character by character; the URI-grammar ones (`%`, a bad escape, a bracket, a non-ASCII letter) are the corruption class R9-1 found
# the generator never made: a `%` and a `[` left where they are not allowed, wherever they fall — in a target, in a `rel`, in a parameter
EDITS = list('<>;,="\\\' \t\x01\x7f') + ["next", "rel=", ", ", ";;", "%", "%G", "%1", "[", "]", "\u00e9", "^", "{", "|"]


def generate(rng) -> str:
    """One header, made by choosing links, a `rel` for each, descriptive parameters around it, and sometimes damaging it."""
    links = []
    for _ in range(1 + rng.below(3)):
        target = rng.pick(TARGETS_NEXT + TARGETS_OTHER)
        params = [rng.pick(DESCRIPTIVE) for _ in range(rng.below(3))]
        params.insert(rng.below(len(params) + 1), rng.pick(RELATIONS))
        links.append(f"<{target}>" + "".join(rng.pick(["; ", ";", " ; "]) + p for p in params))
    header = rng.pick([", ", ",", " , ", ",, "]).join(links)
    for _ in range(rng.below(3) if rng.chance(0.5) else 0):
        at, edit = rng.below(len(header) + 1), rng.pick(EDITS)
        header = header[:at] + (edit if rng.chance(0.5) else "") + header[at + (1 if rng.chance(0.5) else 0):]
    return header
