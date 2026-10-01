"""RFC 3986 / RFC 8288 conformance vectors for the `Link` header a find lane pages by (Hugging Face), written from the grammars.

Authorship: from the RFCs and docs/PROVIDER-PAGINATION.md (the Hugging Face section) only. The gateway's `base.parse_links` / `base.next_link` and
the harness's own reader (tests/invariant_links.py) were not consulted: the root cause of R9-1 was that one author wrote both, so both
accepted `%GG`, a trailing `%`, `https://[broken` and non-ASCII as part of a URI.

Every vector is a header value exactly as the transport hands it to the adapter (repeated lines already joined with a comma, RFC 9110 §5.3),
and the interpretation a conformant reader must reach:

  NEXT     a next URL: the header was read whole and names exactly one next page (and the gateway may follow it)
  ABSENT   a known absence: the header was read whole (or there is none) and names no next page
  UNKNOWN  neither: the header could not be read, names several different next pages, or names a next page the gateway may not follow.
           The lane is then a lower bound (`partial_pagination`); an end is never concluded from a failure to read.

`grade` says what decides the case:
  grammar    the ABNF alone (RFC 3986 Appendix A, RFC 8288 §3 and §3.3, RFC 9110 §5.6)
  contract   the repository's own documents (PROVIDER-PAGINATION.md, Hugging Face: the three outcomes; "Read includes the grammar of each part")
  policy     the Hub-only followability rule of PROVIDER-PAGINATION.md (`base.own_link`), not an RFC rule
  judgement  the specifications leave it open; `also` lists the other outcomes a conformant reader may reach. ABSENT is never among them: a
             case the documents leave open is never a licence to conclude that the listing ended.

Section numbers, quoted rules and every label were checked against the text of the three RFCs (fetched to private/evidence/2b-repair-10a/rfc/; corrections in
corrections-after-rfc-text.md there), and the URI grammar below was compiled a second time, mechanically, from the RFC 3986 Appendix A text and compared with it
on 240,000 strings (rfc/check_abnf.py): the first version of the citations was written from memory.

The reference grammar below (`URI_REFERENCE`, `read`, `interpret`) is an independent transcription of the ABNF. It labels nothing: the vectors'
`expect` is written by hand, and `tests/test_oracle.py` checks hand and grammar against each other so a typo in a label is found here, not in
the gateway.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NEXT, ABSENT, UNKNOWN = "next", "absent", "unknown"

# What the Hub lane asks, and a continuation that stays inside the search (PROVIDER-PAGINATION.md, Hugging Face: `https`, `huggingface.co`, the
# default port, path `/api/datasets`, no user info, no fragment, `search` = this query).
OWN = "https://huggingface.co/api/datasets?search=q&limit=3&full=true"
NEXT_URL = OWN + "&cursor=eyJfaWQiOiI2NTAwIn0"
OTHER = "https://example.org/p"                 # a valid, absolute, harmless target for links that are not the next page


@dataclass(frozen=True)
class Vector:
    name: str
    header: str | None                          # None: the answer carries no Link header at all
    expect: str
    rfc: str
    grade: str = "grammar"
    next_url: str | None = None                 # when NEXT: the continuation must be exactly this
    also: tuple = ()                            # judgement only: other conformant outcomes (never ABSENT)
    note: str = ""

    @property
    def allowed(self) -> frozenset:
        return frozenset((self.expect, *self.also))


# ------------------------------------------------------------------ the reference grammar (RFC 3986 Appendix A, transcribed)
_UNRES = r"A-Za-z0-9\-._~"
_SUB = r"!$&'()*+,;="
_PCT = r"%[0-9A-Fa-f]{2}"                                       # §2.1: "%" HEXDIG HEXDIG, ASCII hex digits only
_PCHAR = rf"(?:[{_UNRES}{_SUB}:@]|{_PCT})"
_H16 = r"[0-9A-Fa-f]{1,4}"
_DEC = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9][0-9]|[0-9])"
_IPV4 = rf"{_DEC}\.{_DEC}\.{_DEC}\.{_DEC}"
_LS32 = rf"(?:{_H16}:{_H16}|{_IPV4})"


def _hs(n: int) -> str:
    return rf"(?:{_H16}:){{{n}}}"


_IPV6 = "(?:" + "|".join([                                       # §3.2.2, the nine IPv6address forms
    rf"{_hs(6)}{_LS32}",
    rf"::{_hs(5)}{_LS32}",
    rf"(?:{_H16})?::{_hs(4)}{_LS32}",
    rf"(?:(?:{_H16}:){{0,1}}{_H16})?::{_hs(3)}{_LS32}",
    rf"(?:(?:{_H16}:){{0,2}}{_H16})?::{_hs(2)}{_LS32}",
    rf"(?:(?:{_H16}:){{0,3}}{_H16})?::{_H16}:{_LS32}",
    rf"(?:(?:{_H16}:){{0,4}}{_H16})?::{_LS32}",
    rf"(?:(?:{_H16}:){{0,5}}{_H16})?::{_H16}",
    rf"(?:(?:{_H16}:){{0,6}}{_H16})?::",
]) + ")"
_IPVFUTURE = rf"[vV][0-9A-Fa-f]+\.[{_UNRES}{_SUB}:]+"
_IPLITERAL = rf"\[(?:{_IPV6}|{_IPVFUTURE})\]"
_REGNAME = rf"(?:[{_UNRES}{_SUB}]|{_PCT})*"
_HOST = rf"(?:{_IPLITERAL}|{_IPV4}|{_REGNAME})"
_USERINFO = rf"(?:[{_UNRES}{_SUB}:]|{_PCT})*"
_AUTHORITY = rf"(?:{_USERINFO}@)?{_HOST}(?::[0-9]*)?"
_SEG, _SEGNZ = rf"{_PCHAR}*", rf"{_PCHAR}+"
_SEGNZNC = rf"(?:[{_UNRES}{_SUB}@]|{_PCT})+"
_ABEMPTY = rf"(?:/{_SEG})*"
_ABSOLUTE = rf"/(?:{_SEGNZ}(?:/{_SEG})*)?"
_NOSCHEME = rf"{_SEGNZNC}(?:/{_SEG})*"
_ROOTLESS = rf"{_SEGNZ}(?:/{_SEG})*"
_QUERY = rf"(?:{_PCHAR}|[/?])*"                                 # §3.4 and §3.5 (fragment is the same production)
_SCHEME = r"[A-Za-z][A-Za-z0-9+\-.]*"
_URI = rf"{_SCHEME}:(?://{_AUTHORITY}{_ABEMPTY}|{_ABSOLUTE}|{_ROOTLESS}|)(?:\?{_QUERY})?(?:#{_QUERY})?"
_RELREF = rf"(?://{_AUTHORITY}{_ABEMPTY}|{_ABSOLUTE}|{_NOSCHEME}|)(?:\?{_QUERY})?(?:#{_QUERY})?"
URI = re.compile(_URI)                                          # §3 (an extension relation type is a URI, RFC 8288 §3.3)
URI_REFERENCE = re.compile(rf"(?:{_URI}|{_RELREF})")            # §4.1 (a link target is a URI-Reference, RFC 8288 §3)

# RFC 9110 §5.6.2 (token), §5.6.4 (quoted-string); RFC 8288 §3 (link-value, link-param); §3.3 (relation types)
_TCHAR = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]"
_TOKEN = re.compile(rf"{_TCHAR}+")
_QUOTED = re.compile(r'"(?:[\t \x21\x23-\x5b\x5d-\x7e\x80-\xff]|\\[\t \x21-\x7e\x80-\xff])*"')
_RELTYPE = rf"(?:[a-z][a-z0-9.\-]*|{_URI})"                 # reg-rel-type = LOALPHA *( LOALPHA / DIGIT / "." / "-" ): lowercase ASCII (RFC 8288 §3.3, §6)
_REL_LIST = re.compile(rf"{_RELTYPE}(?: +{_RELTYPE})*")
_OWS = " \t"


class Unreadable(Exception):
    pass


def _unquote(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text[1:-1], flags=re.S)


def read(header: str) -> list:
    """RFC 8288 §3 `Link = #link-value`, read whole: [(target, [(name, value | None)])], or Unreadable."""
    i, n, links = 0, len(header), []
    while True:
        while i < n and header[i] in _OWS:
            i += 1
        if i >= n:
            return links
        if header[i] == ",":                                    # an empty list element (RFC 9110 §5.6.1.2: a recipient MUST accept them)
            i += 1
            continue
        if header[i] != "<":
            raise Unreadable("link-value does not start with <")
        end = header.find(">", i)
        if end < 0:
            raise Unreadable("unterminated target")
        target = header[i + 1:end]
        if not URI_REFERENCE.fullmatch(target):
            raise Unreadable("target is not a URI-Reference")
        i, params = end + 1, []
        while True:
            j = i
            while j < n and header[j] in _OWS:
                j += 1
            if j < n and header[j] == ";":
                j += 1
                while j < n and header[j] in _OWS:
                    j += 1
                m = _TOKEN.match(header, j)
                if not m:
                    raise Unreadable("link-param without a name")
                name, j = m.group(), m.end()
                k = j
                while k < n and header[k] in _OWS:
                    k += 1
                value = None
                if k < n and header[k] == "=":
                    k += 1
                    while k < n and header[k] in _OWS:
                        k += 1
                    m = _QUOTED.match(header, k) or _TOKEN.match(header, k)
                    if not m:
                        raise Unreadable("link-param value is neither token nor quoted-string")
                    value, j = m.group(), m.end()
                params.append((name, value))
                i = j
                continue
            break
        while i < n and header[i] in _OWS:
            i += 1
        if i < n and header[i] != ",":
            raise Unreadable("junk after a link-value")
        links.append((target, params))


def relations(params: list) -> list:
    """The first `rel` parameter counts (RFC 8288 §3.3); its decoded value is a space-separated list of relation types."""
    for name, value in params:
        if name.lower() == "rel":
            if value is None:
                raise Unreadable("rel without a value")
            text = _unquote(value) if value.startswith('"') else value
            if not _REL_LIST.fullmatch(text):
                raise Unreadable("rel is not a list of relation types")
            return text.split(" ")
    return []


def followable(url: str) -> bool:
    """PROVIDER-PAGINATION.md (Hugging Face), `base.own_link`: https, huggingface.co, default port, /api/datasets, no user info, no fragment,
    `search` present with this query."""
    m = re.fullmatch(r"https://huggingface\.co(/api/datasets)\?([^#]*)", url)
    return bool(m) and "search=q" in m.group(2).split("&")


def interpret(header: str | None) -> tuple:
    """(outcome, url) the reference reader reaches. Never used to build the gateway's answer: only to check the hand-written labels."""
    if header is None:
        return ABSENT, None
    try:
        nexts = {t for t, p in read(header) if any(r.lower() == "next" for r in relations(p))}
    except Unreadable:
        return UNKNOWN, None
    if not nexts:
        return ABSENT, None
    if len(nexts) > 1:
        return UNKNOWN, None
    (url,) = nexts
    return (NEXT, url) if followable(url) else (UNKNOWN, None)


# ------------------------------------------------------------------ targets: every one is a URI-Reference or is not (RFC 3986)
# (target, section, why it is valid). Each is used as the target of a link that is not the next page: `<T>; rel="prev"`.
VALID_TARGETS = (
    ("https://example.org/", "§3, §3.2.2 reg-name", "an ordinary absolute URI"),
    ("https://example.org", "§3.3 path-abempty", "the path may be empty"),
    ("//example.org/x", "§4.2 relative-ref", "a network-path reference"),
    ("/abs/path", "§4.2 path-absolute", "an absolute-path reference"),
    ("rel/path", "§4.2 path-noscheme", "a relative-path reference"),
    ("../up", "§4.2", "dot segments are segments"),
    ("?q=1", "§4.2, §3.4", "a query-only reference"),
    ("#frag", "§4.2, §3.5", "a fragment-only reference"),
    ("", "§4.2 path-empty; §4.4 (empty references are same-document references)", "the empty reference is a relative-ref (same-document)"),
    ("a:b", "§3.1, §3.3 path-rootless", "scheme and a rootless path"),
    ("mailto:x@example.org", "§3.3 path-rootless", "pchar admits ':' and '@'"),
    ("urn:isbn:0451450523", "§3.3 path-rootless", "colons in a rootless path"),
    ("https://u:p@h.example:8080/p?q#f", "§3.2.1-§3.2.3, §3.4, §3.5", "user info, host, port, path, query and fragment"),
    ("https://u:p:q@h.example/", "§3.2.1 userinfo", "user info may contain ':'"),
    ("https://example.org:/", "§3.2.3 port = *DIGIT", "an empty port"),
    ("https://example.org:65536/", "§3.2.3", "the grammar bounds no port number"),
    ("https:///p", "§3.2.2 reg-name = *(...); but §3.2.2 and §6.2.3 note that http(s) considers an empty host an error (scheme-specific, §3.1)", "an empty host is a reg-name"),
    ("https://[::1]/", "§3.2.2 IPv6address", "IP-literal"),
    ("https://[::1]:8080/", "§3.2.2, §3.2.3", "IP-literal with a port"),
    ("https://[2001:db8::1]/x", "§3.2.2 IPv6address", "compressed IPv6"),
    ("https://[2001:db8:0:0:0:0:0:1]/", "§3.2.2 IPv6address", "eight groups"),
    ("https://[::ffff:192.0.2.1]/", "§3.2.2 ls32 = IPv4address", "IPv6 with a dotted-quad tail"),
    ("https://[v7.fe80]/", "§3.2.2 IPvFuture", "IPvFuture"),
    ("https://192.0.2.1/", "§3.2.2 IPv4address", "dotted quad"),
    ("https://999.1.1.1/", "§3.2.2 (first-match-wins: a host that does not match IPv4address is a reg-name)", "an out-of-range 'octet' is not an IPv4address but is a reg-name"),
    ("https://01.2.3.4/", "§3.2.2 (first-match-wins: a leading zero is no dec-octet, so a reg-name)", "a leading zero is not a dec-octet but is a reg-name"),
    ("https://example.org/a%20b", "§2.1 pct-encoded", "percent-encoded space"),
    ("https://example.org/a%7e", "§2.1", "lowercase hex digits are equivalent to uppercase"),
    ("https://example.org/a%7E", "§2.1", "uppercase hex digits"),
    ("https://example.org/a%2Fb", "§2.1", "percent-encoded reserved character"),
    ("https://example.org/a%25b", "§2.1", "percent-encoded percent sign"),
    ("https://example.org/?q=%E2%82%AC", "§2.1 (any two HEXDIG; §2.5 only advises UTF-8 for the textual data of new schemes)", "percent-encoded UTF-8"),
    ("https://example.org/?q=%FF", "§2.1", "the grammar does not require the octets to be UTF-8"),
    ("https://example.org/?q=%00", "§2.1", "the grammar admits %00"),
    ("https://example.org/p;params", "§3.3 sub-delims", "';' is a sub-delim"),
    ("https://example.org/?a,b;c=d+e", "§3.4 sub-delims", "',' ';' '=' '+' in a query"),
    ("https://example.org/?a?b/c", "§3.4 query = *(pchar / '/' / '?')", "'/' and '?' in a query"),
    ("https://example.org/#a/b?c", "§3.5 fragment", "'/' and '?' in a fragment"),
    ("https://example.org/?", "§3.4", "an empty query"),
    ("https://example.org/#", "§3.5", "an empty fragment"),
    ("https://example.org/!$&'()*+,;=:@", "§3.3 pchar", "every sub-delim, ':' and '@' in a segment"),
    ("https://example.org/a:b", "§3.3 segment", "':' in a later segment"),
)

# (target, section violated). Each is NOT a URI-Reference.
INVALID_TARGETS = (
    ("https://example.org/a%GG", "§2.1 pct-encoded: 'G' is not a HEXDIG"),
    ("https://example.org/a%G1", "§2.1: first digit not hex"),
    ("https://example.org/a%1G", "§2.1: second digit not hex"),
    ("https://example.org/a%", "§2.1: a '%' must be followed by two HEXDIG"),
    ("https://example.org/a%1", "§2.1: one digit"),
    ("https://example.org/a%%41", "§2.1: '%' followed by '%'"),
    ("https://example.org/?q=%GG", "§2.1 in the query"),
    ("https://example.org/?q=%", "§2.1: trailing '%' in the query"),
    ("https://example.org/#%GG", "§2.1 in the fragment"),
    ("https://example.org/#%", "§2.1: trailing '%' in the fragment"),
    ("https://u%GG@example.org/", "§2.1 in the user info"),
    ("https://example.org%GG/", "§2.1 in the host (reg-name)"),
    ("https://example.org%/", "§2.1: trailing '%' in the host"),
    ("%", "§2.1: a lone '%'"),
    ("https://example.org/a%\u0663\u0663", "§2.1: HEXDIG is ASCII (core rule, §1.3; the ABNF terminals are US-ASCII code points, §2); ARABIC-INDIC DIGIT THREE is not a digit"),
    ("https://example.org/a%\uff14\uff11", "§2.1: HEXDIG is ASCII (core rule, §1.3; the ABNF terminals are US-ASCII code points, §2); FULLWIDTH DIGITS are not"),
    ("https://example.org/a\uff05\x34\x31", "§2, §2.1-§2.3, App. A: FULLWIDTH PERCENT SIGN is not '%'"),
    ("https://example.org/a b", "§2.2/§2.3: a space is neither reserved nor unreserved"),
    ("https://example.org/a\tb", "§2, §2.1-§2.3, App. A: a TAB is not a URI character"),
    ("https://example.org/a\x01b", "§2, §2.1-§2.3, App. A: a control character"),
    ("https://example.org/a\x7fb", "§2, §2.1-§2.3, App. A: DEL"),
    ("https://example.org/a\"b", "§2.1-§2.3, App. A (in neither reserved nor unreserved): '\"' must be percent-encoded"),
    ("https://example.org/a<b", "§2.1-§2.3, App. A (in neither reserved nor unreserved): '<' must be percent-encoded"),
    ("https://example.org/a\\b", "§2.1-§2.3, App. A (in neither reserved nor unreserved): '\\' must be percent-encoded"),
    ("https://example.org/a^b", "§2.1-§2.3, App. A (in neither reserved nor unreserved): '^'"),
    ("https://example.org/a`b", "§2.1-§2.3, App. A (in neither reserved nor unreserved): '`'"),
    ("https://example.org/a{b}", "§2.1-§2.3, App. A (in neither reserved nor unreserved): '{' '}'"),
    ("https://example.org/a|b", "§2.1-§2.3, App. A (in neither reserved nor unreserved): '|'"),
    ("https://example.org/\u00e9", "§2, §2.1, §2.4, App. A; RFC 8288 §3.1, §6: no non-ASCII character is in the RFC 3986 grammar (IRIs are RFC 3987)"),
    ("https://example.org/\u4e2d", "§2, §2.1, §2.4, App. A; RFC 8288 §3.1, §6: non-ASCII"),
    ("https://example.org/\U0001f600", "§2, §2.1, §2.4, App. A; RFC 8288 §3.1, §6: non-ASCII outside the BMP"),
    ("https://example.org/a\u00a0b", "§2, §2.1-§2.3, App. A: NO-BREAK SPACE"),
    ("https://example.org/a\u200bb", "§2, §2.1-§2.3, App. A: ZERO WIDTH SPACE"),
    ("https://example.org/a\u202eb", "§2, §2.1-§2.3, App. A: RIGHT-TO-LEFT OVERRIDE"),
    ("https://example.org/a\ufeffb", "§2, §2.1-§2.3, App. A: BYTE ORDER MARK"),
    ("https://\u00e9xample.org/", "§3.2.2: non-ASCII in a reg-name"),
    ("https://example.org/?q=\u00e9", "§3.4: non-ASCII in the query"),
    ("https://example.org/#\u00e9", "§3.5: non-ASCII in the fragment"),
    ("https://[broken", "§3.2.2 IP-literal: '[' without ']'"),
    ("https://broken]/", "§3.2.2: ']' is a gen-delim, not a reg-name character"),
    ("https://[::1", "§3.2.2: unclosed IP-literal"),
    ("https://[]/", "§3.2.2: an IP-literal holds an address"),
    ("https://[1:2:3]/", "§3.2.2: too few groups for IPv6address"),
    ("https://[::g]/", "§3.2.2: 'g' is not a HEXDIG"),
    ("https://[12345::]/", "§3.2.2 h16 = 1*4HEXDIG"),
    ("https://[1::2::3]/", "§3.2.2: '::' only once"),
    ("https://[:::1]/", "§3.2.2: ':::'"),
    ("https://[::1]x/", "§3.2.2: after an IP-literal only ':' port or the path"),
    ("https://[::1]:80a/", "§3.2.3 port = *DIGIT"),
    ("https://[v.x]/", "§3.2.2 IPvFuture needs 1*HEXDIG after 'v'"),
    ("https://[v1.]/", "§3.2.2 IPvFuture needs 1*( ... ) after '.'"),
    ("https://[::256.1.1.1]/", "§3.2.2 dec-octet <= 255"),
    ("https://[::1.2.3]/", "§3.2.2 IPv4address has four octets"),
    ("https://[1.2.3.4]/", "§3.2.2: an IP-literal is IPv6address or IPvFuture, not IPv4address"),
    ("https://a[b]c/", "§3.2.2: brackets inside a reg-name"),
    ("https://example.org:80a/", "§3.2.3 port = *DIGIT"),
    ("https://example.org:\u0663/", "§3.2.3: ARABIC-INDIC DIGIT is not a DIGIT"),
    ("https://example.org:80:80/", "§3.2.3: one port"),
    ("https://u@v@example.org/", "§3.2.1: '@' is not a user info or reg-name character"),
    ("https://example.org/a[0]", "§3.2.2: an IP-literal is 'the only place where square bracket characters are allowed in the URI syntax'; §2.2"),
    ("https://example.org/?x[0]=1", "§3.2.2: square brackets are allowed only in an IP-literal; §3.4 query = *( pchar / '/' / '?' )"),
    ("https://example.org/#a#b", "§3.5: '#' does not occur in a fragment"),
    ("1ab://example.org/", "§3.1 (a scheme starts with ALPHA), §4.1 (a prefix that is no scheme makes it a relative reference), §4.2 (a first segment holding ':' is no relative-path reference)"),
    ("h_t://example.org/", "§3.1 ('_' is not a scheme character), §4.1, §4.2 (a first segment holding ':' is no relative-path reference)"),
    ("://example.org/", "§3.1: an empty scheme"),
    (":x", "§3.1, §4.1, §4.2: no scheme, and a first segment may not hold ':'"),
    ("a b:c", "§3.1: a space in a scheme"),
)

# valid URI-References that violate a SCHEME-SPECIFIC restriction (RFC 3986 §3.1, §3.2.2, §6.2.3): a reader that checks them may decline the header
SCHEME_SPECIFIC = {"https:///p"}

# cursor values appended to the Hub's own search URL (the part a provider controls): valid ones leave a followable next link
VALID_CURSORS = (
    ("a1", "§3.4 unreserved"), ("b%2Bc", "§2.1"), ("b%2bc", "§2.1 lowercase hex"), ("x,y", "§3.4 sub-delims"), ("x;y", "§3.4 sub-delims"),
    ("x:y@z", "§3.4 pchar"), ("x/y", "§3.4"), ("x?y", "§3.4"), ("a+b", "§3.4"), ("a=b", "§3.4"), ("a'b", "§3.4"), ("(a)", "§3.4"), ("a*", "§3.4"),
    ("a!$", "§3.4"), ("%E2%82%AC", "§2.1 (any two HEXDIG; §2.5 only advises UTF-8 for the textual data of new schemes)"), ("%7E", "§2.1"), ("~-._", "§2.3 unreserved"), ("a%25b", "§2.1"), ("", "§3.4 an empty value"),
    ("eyJfaWQiOiI2NTAwIn0", "§2.3 base64url"),
)
INVALID_CURSORS = (
    ("%GG", "§2.1"), ("%G1", "§2.1"), ("%1G", "§2.1"), ("%", "§2.1"), ("%1", "§2.1"), ("a%", "§2.1"), ("%%41", "§2.1"),
    ("%\u0663\u0663", "§2.1 HEXDIG is ASCII (core rule, §1.3; the ABNF terminals are US-ASCII code points, §2)"), ("%\uff14\uff11", "§2.1 HEXDIG is ASCII (core rule, §1.3; the ABNF terminals are US-ASCII code points, §2)"), ("a b", "§2.2/§2.3"), ("\u00e9", "§2, §2.1, §2.4, App. A; RFC 8288 §3.1, §6"),
    ("\u4e2d", "§2, §2.1, §2.4, App. A; RFC 8288 §3.1, §6"), ("\U0001f600", "§2, §2.1, §2.4, App. A; RFC 8288 §3.1, §6"), ("a|b", "§2.1-§2.3, App. A"), ("a\\b", "§2.1-§2.3, App. A"), ("a^b", "§2.1-§2.3, App. A"), ("a`b", "§2.1-§2.3, App. A"), ("a{b}", "§2.1-§2.3, App. A"),
    ('a"b', "§2.1-§2.3, App. A"), ("a<b", "§2.1-§2.3, App. A"), ("a[0]", "§3.2.2: square brackets are allowed only in an IP-literal; §3.4"), ("a]", "§3.2.2: square brackets are allowed only in an IP-literal; §3.4"), ("a\x01b", "§2"), ("a\x7fb", "§2"),
    ("a\tb", "§2"), ("a\u00a0b", "§2"), ("a\u200bb", "§2"), ("a\ufeffb", "§2"),
)

# `rel` values, as the whole parameter text: (text, expect, section, grade, note)
RELS = (
    # --- a registered relation type, or a list of them (RFC 8288 §3.3: reg-rel-type = LOALPHA *( LOALPHA / DIGIT / "." / "-" ))
    ('rel="next"', NEXT, "§3.3", "grammar", "the quoted form"),
    ("rel=next", NEXT, "§3.3, RFC 9110 §5.6.2", "grammar", "the token form"),
    ('rel="prev next"', NEXT, "§3.3 relation-type *( 1*SP relation-type )", "grammar", "a list holding next"),
    ('rel="next prev"', NEXT, "§3.3", "grammar", "a list holding next"),
    ('rel="prev  next"', NEXT, "§3.3: 1*SP", "grammar", "more than one space between types"),
    ('rel="n\\ext"', NEXT, "RFC 9110 §5.6.4 quoted-pair", "grammar", "a recipient replaces each quoted-pair with the character it quotes"),
    ('rel = "next"', NEXT, "§3 link-param = token BWS [ '=' BWS ( token / quoted-string ) ]; RFC 9110 §5.6.3 (a recipient MUST parse bad whitespace)", "grammar", "whitespace around '='"),
    ('rel\t=\tnext', NEXT, "RFC 8288 §3 BWS; RFC 9110 §5.6.3 (a recipient MUST parse bad whitespace)", "grammar", "tabs around '='"),
    ('REL="next"', NEXT, "RFC 9110 §5.6.6: \"Parameter names are case-insensitive\"; RFC 8288 §3.3 itself writes REL=\"X\" and REV=\"X\"", "grammar",
     "the parameter name is case-insensitive"),
    ('rel="NEXT"', NEXT, "§2.1.1: registered relation types MUST be compared character by character, case-insensitively; but §3.3 reg-rel-type is LOALPHA and §6 requires lowercase names",
     "judgement", "uppercase registered name: compared as next, or not a conformant name; never the absence of a next page"),
    ('rel="Next"', NEXT, "§2.1.1 (case-insensitive comparison); §3.3 and §6 (lowercase names)", "judgement", "mixed case registered name"),
    ('rel="prev"', ABSENT, "§3.3", "grammar", ""),
    ('rel="first last"', ABSENT, "§3.3", "grammar", ""),
    ('rel="n ext"', ABSENT, "§3.3: two relation types, 'n' and 'ext'", "grammar", "a space separates two types; it does not glue 'n' to 'ext'"),
    ('rel="nex"', ABSENT, "§3.3", "grammar", "a relation type that is not next"),
    ('rel="next2"', ABSENT, "§3.3 reg-rel-type admits DIGIT", "grammar", "a different registered name"),
    ('rel="next.x"', ABSENT, "§3.3 reg-rel-type admits '.'", "grammar", "a different registered name"),
    ('rel="next-x"', ABSENT, "§3.3 reg-rel-type admits '-'", "grammar", "a different registered name"),
    ('rel="a.b-c1"', ABSENT, "§3.3", "grammar", ""),
    # --- extension relation types are absolute URIs (§3.3: ext-rel-type = URI), RFC 3986 §3
    ('rel="https://example.org/rels/next"', ABSENT, "§3.3 ext-rel-type, RFC 3986 §3", "grammar", "an extension type that is not the registered next"),
    ('rel="urn:example:next"', ABSENT, "§3.3, RFC 3986 §3.3 path-rootless", "grammar", ""),
    ('rel="a:"', ABSENT, "RFC 3986 §3 hier-part = path-empty", "grammar", "scheme, colon, nothing"),
    ('rel="https://[::1]/r"', ABSENT, "RFC 3986 §3.2.2 IP-literal", "grammar", "a well-formed IP-literal"),
    ('rel="https://[v7.fe80]/r"', ABSENT, "RFC 3986 §3.2.2 IPvFuture", "grammar", ""),
    ('rel="https://example.org/r%41"', ABSENT, "RFC 3986 §2.1", "grammar", "a valid percent-escape"),
    ('rel="https://example.org/r?x=1#f"', ABSENT, "RFC 3986 §3.4, §3.5", "grammar", ""),
    ('rel="HTTPS://EXAMPLE.ORG/R"', ABSENT, "RFC 3986 §3.1: schemes are case-insensitive", "grammar", ""),
    ('rel="http://u:p@h.example:1/"', ABSENT, "RFC 3986 §3.2", "grammar", ""),
    ('rel="https://exa mple.org"', ABSENT, "§3.3: two relation types, 'https://exa' (a URI) and 'mple.org' (a registered name)", "grammar",
     "the space ends the first type; both halves are well-formed"),
    ('rel="next https://example.org/r"', NEXT, "§3.3", "grammar", "next beside an extension type"),
    # --- not relation types (the decoded value must be a list of them; none empty, none with a quote or control character of its own)
    ('rel=""', UNKNOWN, "§3.3 (and PROVIDER-PAGINATION.md, R8-1)", "contract", "an empty value names no relation type"),
    ('rel=', UNKNOWN, "§3 link-param: '=' must be followed by a token or quoted-string", "grammar", "no value after '='"),
    ('rel', UNKNOWN, "§3.3: the rel parameter's value is a list of relation types", "judgement",
     "grammar-valid as a bare parameter, but it names no relation type; reading it as 'a link that is not next' is not allowed to end the listing"),
    ('rel=" "', UNKNOWN, "§3.3", "contract", "only a space"),
    ('rel=" next"', UNKNOWN, "§3.3: no leading space", "contract", ""),
    ('rel="next "', UNKNOWN, "§3.3: no trailing space", "contract", ""),
    ('rel="next\tprev"', UNKNOWN, "§3.3: the separator is 1*SP, not a TAB", "contract", ""),
    ('rel="next, prev"', UNKNOWN, "§3.3 (PROVIDER-PAGINATION.md)", "contract", "a comma is no separator inside the value"),
    ('rel="next;prev"', UNKNOWN, "§3.3", "contract", "a semicolon is no separator inside the value"),
    ('rel="\\"next\\""', UNKNOWN, "§3.3 (PROVIDER-PAGINATION.md)", "contract", "the decoded value holds quote characters"),
    ('rel="next\x01"', UNKNOWN, "RFC 9110 §5.6.4: a control character is no qdtext (PROVIDER-PAGINATION.md)", "contract", ""),
    ('rel="next\x7f"', UNKNOWN, "RFC 9110 §5.6.4: DEL is no qdtext", "grammar", ""),
    ('rel="next\\\x01"', UNKNOWN, "RFC 9110 §5.6.4: a quoted-pair quotes HTAB, SP, VCHAR or obs-text only", "grammar", ""),
    ('rel="next\\', UNKNOWN, "RFC 9110 §5.6.4: no closing quote", "grammar", "an unterminated quoted-string"),
    ('rel="next', UNKNOWN, "RFC 9110 §5.6.4", "grammar", "no closing quote"),
    ('rel="ne"xt"', UNKNOWN, "RFC 9110 §5.6.4: a quote inside a quoted-string must be escaped", "grammar", ""),
    ("rel='next'", UNKNOWN, "§3.3 (PROVIDER-PAGINATION.md)", "contract", "'next' with apostrophes is a token but not a relation type"),
    ("rel=next,prev", UNKNOWN, "RFC 9110 §5.6.1: a comma separates list elements, and 'prev' is no link-value", "grammar", ""),
    ('rel="1next"', UNKNOWN, "§3.3: a registered type starts with LOALPHA; it is not a URI either", "grammar", ""),
    ('rel="-next"', UNKNOWN, "§3.3", "grammar", ""),
    ('rel=".next"', UNKNOWN, "§3.3", "grammar", ""),
    ('rel="ne_xt"', UNKNOWN, "§3.3: '_' is not allowed", "grammar", ""),
    ('rel="next!"', UNKNOWN, "§3.3", "grammar", ""),
    ('rel="next/"', UNKNOWN, "§3.3: not a URI (no scheme) and not a registered name", "grammar", ""),
    ('rel="example.org/rels"', UNKNOWN, "§3.3: an extension type is an absolute URI; this has no scheme", "grammar", ""),
    ('rel="//example.org/rels"', UNKNOWN, "§3.3: a network-path reference is not an absolute URI", "grammar", ""),
    ('rel="/rels/next"', UNKNOWN, "§3.3", "grammar", ""),
    ('rel=":x"', UNKNOWN, "RFC 3986 §3.1: no scheme", "grammar", ""),
    ('rel="1http://x"', UNKNOWN, "RFC 3986 §3.1: a scheme starts with ALPHA", "grammar", ""),
    ("rel=https://example.org/r", UNKNOWN, "RFC 8288 §3.3: an extension type MUST be quoted (':' and '/' are not tchars)", "grammar", "an unquoted URI"),
    ("rel=urn:example:next", UNKNOWN, "RFC 8288 §3.3: ':' is not a tchar", "grammar", "an unquoted URI"),
    ('rel="n\u00e9xt"', UNKNOWN, "§3.3: LOALPHA is ASCII", "grammar", "non-ASCII in a registered name"),
    ('rel="\u212aeep"', UNKNOWN, "§3.3: KELVIN SIGN is not ASCII 'k' (it only case-folds to it)", "grammar", "a case-insensitive pattern that folds Unicode accepts this"),
    ('rel="\u017ftyle"', UNKNOWN, "§3.3: LATIN SMALL LETTER LONG S is not ASCII 's'", "grammar", "same trap"),
    ('rel="\uff4e\uff45\uff58\uff54"', UNKNOWN, "§3.3: FULLWIDTH LATIN letters are not LOALPHA", "grammar", "'next' spelled in fullwidth letters is not next"),
    ('rel="https://example.org/\u00e9"', UNKNOWN, "RFC 3986 §2, §2.1-§2.3, App. A: non-ASCII in an extension type (R9-1)", "grammar", ""),
    ('rel="https://example.org/\u4e2d"', UNKNOWN, "RFC 3986 §2 (R9-1)", "grammar", ""),
    ('rel="https://example.org/%GG"', UNKNOWN, "RFC 3986 §2.1 (R9-1)", "grammar", ""),
    ('rel="https://example.org/%G1"', UNKNOWN, "RFC 3986 §2.1", "grammar", ""),
    ('rel="https://example.org/%"', UNKNOWN, "RFC 3986 §2.1: trailing '%' (R9-1)", "grammar", ""),
    ('rel="https://example.org/%1"', UNKNOWN, "RFC 3986 §2.1", "grammar", ""),
    ('rel="https://example.org/?q=%"', UNKNOWN, "RFC 3986 §2.1 in the query", "grammar", ""),
    ('rel="https://example.org/#%"', UNKNOWN, "RFC 3986 §2.1 in the fragment", "grammar", ""),
    ('rel="https://[broken"', UNKNOWN, "RFC 3986 §3.2.2: '[' without ']' (R9-1)", "grammar", ""),
    ('rel="https://[::1"', UNKNOWN, "RFC 3986 §3.2.2", "grammar", ""),
    ('rel="https://[]/r"', UNKNOWN, "RFC 3986 §3.2.2", "grammar", ""),
    ('rel="https://[::g]/r"', UNKNOWN, "RFC 3986 §3.2.2", "grammar", ""),
    ('rel="https://[1:2:3]/r"', UNKNOWN, "RFC 3986 §3.2.2", "grammar", ""),
    ('rel="https://[::1]x/r"', UNKNOWN, "RFC 3986 §3.2.2", "grammar", ""),
    ('rel="https://broken]/r"', UNKNOWN, "RFC 3986 §3.2.2", "grammar", ""),
    ('rel="https://example.org:80a/r"', UNKNOWN, "RFC 3986 §3.2.3", "grammar", ""),
    ('rel="https://example.org/r#a#b"', UNKNOWN, "RFC 3986 §3.5", "grammar", "two fragments"),
    ('rel="https://example.org/a\\"b"', UNKNOWN, "RFC 3986 §2.1-§2.3, App. A (in neither reserved nor unreserved): a decoded quote is no URI character", "grammar", ""),
    ('rel="https://example.org/a\\\\b"', UNKNOWN, "RFC 3986 §2.1-§2.3, App. A (in neither reserved nor unreserved): a decoded backslash is no URI character", "grammar", ""),
    ('rel="https://example.org/a<b"', UNKNOWN, "RFC 3986 §2.1-§2.3, App. A (in neither reserved nor unreserved)", "grammar", ""),
    ('rel="https://example.org/a^b"', UNKNOWN, "RFC 3986 §2.1-§2.3, App. A (in neither reserved nor unreserved)", "grammar", ""),
    ('rel="https://example.org/a|b"', UNKNOWN, "RFC 3986 §2.1-§2.3, App. A (in neither reserved nor unreserved)", "grammar", ""),
    ('rel="https://u@v@example.org/"', UNKNOWN, "RFC 3986 §3.2.1", "grammar", ""),
    ('rel="next https://[broken"', UNKNOWN, "§3.3: one unreadable type makes the list unreadable", "contract", "next beside a malformed type is not a clean next"),
    ('rel="https://[broken next"', UNKNOWN, "§3.3", "contract", "same, the other way round"),
    ('rel="next https://example.org/%GG"', UNKNOWN, "§3.3, RFC 3986 §2.1", "contract", ""),
    ('rel="https://exa\u00e9mple.org/ next"', UNKNOWN, "§3.3, RFC 3986 §2", "contract", ""),
)

# other link parameters: (parameter text placed beside rel="next", expect, section, grade, note)
PARAMS = (
    ('title="next, page"', NEXT, "RFC 9110 §5.6.4: a comma inside a quoted-string belongs to it", "grammar", "R7-1: an earlier reader split on every comma"),
    ('title="a; rel=\\"prev\\", b"', NEXT, "RFC 9110 §5.6.4", "grammar", "a quoted rel inside a title is no relation"),
    ('title="x\\"y"', NEXT, "RFC 9110 §5.6.4 quoted-pair", "grammar", "an escaped quote"),
    ('title="x\\\\y"', NEXT, "RFC 9110 §5.6.4 quoted-pair", "grammar", "an escaped backslash"),
    ('title="x\ty"', NEXT, "RFC 9110 §5.6.4 qdtext includes HTAB", "grammar", "a raw tab inside a quoted-string"),
    ('title="x\\\ty"', NEXT, "RFC 9110 §5.6.4 quoted-pair quotes HTAB", "grammar", ""),
    ('title="caf\u00e9"', NEXT, "RFC 9110 §5.6.4 qdtext includes obs-text", "grammar", "a quoted-string may hold obs-text octets (U+0080-U+00FF as text)"),
    ('title="a>b"', NEXT, "RFC 9110 §5.6.4: '>' is ordinary qdtext", "grammar", "the target ended at the first '>'; a '>' later belongs to the title"),
    ('title="a<b"', NEXT, "RFC 9110 §5.6.4", "grammar", ""),
    ('title=""', NEXT, "RFC 9110 §5.6.4: an empty quoted-string", "grammar", ""),
    ('title=x', NEXT, "RFC 9110 §5.6.2 token", "grammar", ""),
    ("title*=UTF-8''n%20p", NEXT, "RFC 9110 §5.6.2: every character is a tchar", "grammar", "an RFC 8187 extended value is a token"),
    ('type="text/html"', NEXT, "RFC 9110 §5.6.4", "grammar", "'/' needs quotes, and has them"),
    ('hreflang=en', NEXT, "RFC 9110 §5.6.2", "grammar", ""),
    ('ext', NEXT, "RFC 8288 §3 link-param: the value is optional; §3.4.2: other link-params are link-extensions", "grammar", "an extension parameter without a value"),
    ('a=b; c=d; e', NEXT, "RFC 8288 §3", "grammar", "several parameters"),
    ('title="x', UNKNOWN, "RFC 9110 §5.6.4: no closing quote", "grammar", ""),
    ('title="x\\', UNKNOWN, "RFC 9110 §5.6.4", "grammar", "a trailing backslash escapes the closing quote"),
    ('title="x"y"', UNKNOWN, "RFC 9110 §5.6.4: an unescaped quote", "grammar", ""),
    ('title="x\x01y"', UNKNOWN, "RFC 9110 §5.6.4 (qdtext has no control character); §5.5 (other CTL characters make a field value invalid, though a recipient MAY retain them inside a quoted "
     "string); PROVIDER-PAGINATION.md (a quoted string holds only what §5.6.4 allows)", "contract", "the repository's contract reads it as unreadable; RFC 9110 §5.5 would let a recipient keep it"),
    ('title="x\x7fy"', UNKNOWN, "RFC 9110 §5.6.4 (qdtext excludes DEL); §5.5 (a recipient MAY retain other CTL characters); PROVIDER-PAGINATION.md", "contract", "as above"),
    ('title="x\\\x01y"', UNKNOWN, "RFC 9110 §5.6.4 (a quoted-pair quotes HTAB, SP, VCHAR or obs-text only); §5.5; PROVIDER-PAGINATION.md", "contract", "as above"),
    ('title=a b', UNKNOWN, "RFC 8288 §3: after the token value 'a' a space is not a delimiter", "grammar", "an unquoted value with a space"),
    ('title=a/b', UNKNOWN, "RFC 9110 §5.6.2: '/' is not a tchar", "grammar", "an unquoted media type"),
    ('type=text/html', UNKNOWN, "RFC 9110 §5.6.2: '/' is not a tchar", "grammar", "the commonest real-world violation; strictly, not a token"),
    ('title=a,b', UNKNOWN, "RFC 9110 §5.6.1: a comma starts the next list element, and 'b' is no link-value", "grammar", ""),
    ('a b=c', UNKNOWN, "RFC 8288 §3: a link-param name is one token", "grammar", ""),
    ('=x', UNKNOWN, "RFC 8288 §3: link-param starts with a token", "grammar", ""),
    ('title=', UNKNOWN, "RFC 8288 §3: '=' must be followed by a token or quoted-string", "grammar", ""),
    ('title=\x01', UNKNOWN, "RFC 9110 §5.6.2: a control character is no tchar", "grammar", ""),
    ('ti tle=x', UNKNOWN, "§3", "grammar", ""),
)

# Hub-only followability (PROVIDER-PAGINATION.md): a next link that is present is never the end, and one the gateway may not follow
# is neither a continuation nor an end. Each is `rel="next"` with this target. (target, expect, section or doc, grade, note)
FOLLOW = (
    (NEXT_URL, NEXT, "Hugging Face: https, huggingface.co, /api/datasets, search=q", "policy", "own search, with a cursor"),
    (OWN + "&cursor=a%2Bb,c", NEXT, "RFC 3986 §2.1, §3.4; Hugging Face", "policy", "a percent-escape and a comma in the cursor"),
    ("http://huggingface.co/api/datasets?search=q&cursor=x", UNKNOWN, "Hugging Face: https only", "policy", "plain http; the token must not travel"),
    ("https://huggingface.co.evil.example/api/datasets?search=q&cursor=x", UNKNOWN, "Hugging Face: on huggingface.co", "policy", "a look-alike host"),
    ("https://evilhuggingface.co/api/datasets?search=q&cursor=x", UNKNOWN, "Hugging Face: on huggingface.co", "policy", "a look-alike host"),
    ("https://huggingface.co@evil.example/api/datasets?search=q&cursor=x", UNKNOWN, "Hugging Face: no user info; RFC 3986 §3.2.1", "policy",
     "the host is evil.example, and 'huggingface.co' is user info"),
    ("https://user:pw@huggingface.co/api/datasets?search=q&cursor=x", UNKNOWN, "Hugging Face: no user info", "policy", ""),
    ("https://huggingface.co:444/api/datasets?search=q&cursor=x", UNKNOWN, "Hugging Face: the default port", "policy", "another port"),
    ("https://huggingface.co/api/models?search=q&cursor=x", UNKNOWN, "Hugging Face: path /api/datasets", "policy", "another listing"),
    ("https://huggingface.co/api/datasets/extra?search=q&cursor=x", UNKNOWN, "Hugging Face: path /api/datasets", "policy", "a deeper path"),
    ("https://huggingface.co/api/datasets?search=other&cursor=x", UNKNOWN, "Hugging Face: search is this query", "policy", "another search"),
    ("https://huggingface.co/api/datasets?limit=3&cursor=x", UNKNOWN, "Hugging Face: a continuation must name the search", "policy", "no search"),
    (NEXT_URL + "#frag", UNKNOWN, "Hugging Face: no fragment", "policy", ""),
    ("https://example.org/elsewhere", UNKNOWN, "Hugging Face", "policy", "another site"),
    ("https://HUGGINGFACE.CO/api/datasets?search=q&limit=3&full=true&cursor=a", NEXT, "RFC 3986 §3.1, §3.2.2: scheme and host are case-insensitive", "judgement",
     "the same site; declining is allowed"),
    ("https://huggingface.co:443/api/datasets?search=q&limit=3&full=true&cursor=a", NEXT, "RFC 3986 §6.2.3: an explicit default port is equivalent", "judgement",
     "the same site; declining is allowed"),
    ("//huggingface.co/api/datasets?search=q&limit=3&full=true&cursor=a", NEXT, "RFC 8288 §3.1: parsers MUST resolve a relative URI-Reference as per RFC 3986 §5 (§5.2.2, §5.4.1)",
     "judgement", "a network-path reference, resolved against the request; the Hub-only rule may still decline to follow it"),
    ("/api/datasets?search=q&limit=3&full=true&cursor=a", NEXT, "RFC 8288 §3.1; RFC 3986 §5.2.2", "judgement",
     "an absolute-path reference, resolved against the request; the Hub-only rule may still decline to follow it"),
    ("", NEXT, "RFC 8288 §3.1; RFC 3986 §5.2.2 and §5.4.1 (the empty reference resolves to the base URI)", "judgement",
     "resolved against the request it is the request's own URL; the Hub-only rule may still decline to follow it"),
)
# what the relative references of FOLLOW resolve to against the request (RFC 3986 §5.2.2); the gateway may follow them as that URL, or decline
RESOLVED = {
    "": OWN,
    "//huggingface.co/api/datasets?search=q&limit=3&full=true&cursor=a": "https://huggingface.co/api/datasets?search=q&limit=3&full=true&cursor=a",
    "/api/datasets?search=q&limit=3&full=true&cursor=a": "https://huggingface.co/api/datasets?search=q&limit=3&full=true&cursor=a",
}


def _vectors() -> list:
    out = []
    add = out.append

    add(Vector("no-header", None, ABSENT, "PROVIDER-PAGINATION.md: no header names no next link (the end the official clients stop on)", "contract"))
    for name, header, why in (("empty", "", "RFC 9110 §5.6.1.1 (`#element => [ 1#element ]`: no element at all), §5.6.1.2; RFC 8288 §3 (Link = #link-value)"),
                              ("spaces", "   ", "RFC 9110 §5.6.1.2, §5.5 (a field value has no leading or trailing whitespace)"), ("tab", "\t", "RFC 9110 §5.6.1.2, §5.5"),
                              ("one-comma", ",", "RFC 9110 §5.6.1.2: a recipient MUST accept `[ element ] *( OWS \",\" OWS [ element ] )`"),
                              ("commas", " , ,, ", "RFC 9110 §5.6.1.2")):
        add(Vector(f"empty-header:{name}", header, ABSENT, why, "grammar", note="a header read whole that holds no link names no next page"))
    add(Vector("plain-next", f'<{NEXT_URL}>; rel="next"', NEXT, "RFC 8288 §3", next_url=NEXT_URL))
    add(Vector("no-rel", f"<{OTHER}>", ABSENT, "RFC 8288 §3 (the ABNF allows a link-value with no parameter) but §3.3 (\"The rel parameter MUST be present\"): a non-conformant link, naming no relation",
               "judgement", also=(UNKNOWN,), note="read whole, relation unstated; the RFC does not say what a recipient does with it"))
    add(Vector("only-prev", f'<{OTHER}>; rel="prev"', ABSENT, "RFC 8288 §3.3"))
    add(Vector("no-spaces", f'<{NEXT_URL}>;rel="next";title="t"', NEXT, "RFC 8288 §3: OWS may be empty", next_url=NEXT_URL))
    add(Vector("param-before-rel", f'<{NEXT_URL}>; title="t"; rel="next"', NEXT, "RFC 8288 §3: parameters come in any order", next_url=NEXT_URL))
    add(Vector("first-rel-wins", f'<{NEXT_URL}>; rel="next"; rel="prev"', NEXT, "RFC 8288 §3.3: occurrences after the first rel are ignored", next_url=NEXT_URL))
    add(Vector("first-rel-is-prev", f'<{NEXT_URL}>; rel="prev"; rel="next"', ABSENT, "RFC 8288 §3.3: occurrences after the first rel are ignored",
               note="the only rel that counts is prev, so this link is not the next page"))
    add(Vector("trailing-ows", f'<{NEXT_URL}>; rel="next"   \t', NEXT, "RFC 9110 §5.6.1 (elements are separated by a comma and OWS), §5.5", next_url=NEXT_URL))
    add(Vector("leading-ows", f'  \t<{NEXT_URL}>; rel="next"', NEXT, "RFC 9110 §5.6.1", next_url=NEXT_URL))
    add(Vector("no-angle-brackets", f'{NEXT_URL}; rel="next"', UNKNOWN, "RFC 8288 §3: the target is delimited by '<' and '>'"))
    add(Vector("unclosed-angle", f'<{NEXT_URL}; rel="next"', UNKNOWN, "RFC 8288 §3"))
    add(Vector("unopened-angle", f'{NEXT_URL}>; rel="next"', UNKNOWN, "RFC 8288 §3"))
    add(Vector("empty-target-in-brackets", '<>; rel="prev"', ABSENT, "RFC 3986 §4.2: the empty reference is a URI-Reference", note="read whole, not next"))
    add(Vector("junk-before", f'junk <{NEXT_URL}>; rel="next"', UNKNOWN, "RFC 8288 §3: a list element is a link-value"))
    add(Vector("junk-after", f'<{NEXT_URL}>; rel="next" junk', UNKNOWN, "RFC 8288 §3"))
    add(Vector("no-comma-between-links", f'<{OTHER}>; rel="prev" <{NEXT_URL}>; rel="next"', UNKNOWN, "RFC 9110 §5.6.1: list elements are separated by a comma"))
    add(Vector("semicolon-between-links", f'<{OTHER}>; rel="prev"; <{NEXT_URL}>; rel="next"', UNKNOWN, "RFC 8288 §3: '<' cannot begin a link-param"))
    add(Vector("two-links", f'<{OTHER}>; rel="prev", <{NEXT_URL}>; rel="next"', NEXT, "RFC 9110 §5.6.1", next_url=NEXT_URL))
    add(Vector("two-links-reversed", f'<{NEXT_URL}>; rel="next", <{OTHER}>; rel="prev"', NEXT, "RFC 9110 §5.6.1", next_url=NEXT_URL))
    add(Vector("two-lines-joined", f'<{OTHER}>; rel="first",<{NEXT_URL}>; rel="next"', NEXT, "RFC 9110 §5.3: a recipient MAY combine repeated field lines, in order, separated by a comma", next_url=NEXT_URL))
    add(Vector("same-next-twice", f'<{NEXT_URL}>; rel="next", <{NEXT_URL}>; rel="next"', NEXT, "RFC 8288 §3.3: one next page, named twice", next_url=NEXT_URL))
    add(Vector("two-different-nexts", f'<{NEXT_URL}>; rel="next", <{NEXT_URL}2>; rel="next"', UNKNOWN, "PROVIDER-PAGINATION.md: several different next pages", "contract"))
    add(Vector("next-in-two-rels", f'<{NEXT_URL}>; rel="prev", <{NEXT_URL}2>; rel="next prev"', NEXT, "RFC 8288 §3.3", next_url=NEXT_URL + "2"))
    add(Vector("leading-trailing-empty-elements", f', ,<{NEXT_URL}>; rel="next",, ', NEXT, "RFC 9110 §5.6.1.2: a recipient MUST parse and ignore empty list elements", next_url=NEXT_URL))
    add(Vector("comma-in-target", f'<{OWN}&cursor=x,y>; rel="next"', NEXT, "RFC 3986 §3.4: ',' is a sub-delim inside a target", next_url=f"{OWN}&cursor=x,y",
               note="R7-1: a reader that splits on every comma loses the relation"))
    add(Vector("semicolon-in-target", f'<{OWN}&cursor=x;y>; rel="next"', NEXT, "RFC 3986 §3.4: ';' is a sub-delim inside a target", next_url=f"{OWN}&cursor=x;y"))
    add(Vector("target-with-percent-escapes", f'<{OWN}&cursor=b%2Bc>; rel="next"', NEXT, "RFC 3986 §2.1", next_url=f"{OWN}&cursor=b%2Bc"))
    add(Vector("comma-in-target-prev", f'<https://example.org/p?a,b>; rel="prev", <{NEXT_URL}>; rel="next"', NEXT, "RFC 3986 §3.4", next_url=NEXT_URL))
    add(Vector("extra-gt-after-target", f'<{NEXT_URL}>>; rel="next"', UNKNOWN, "RFC 8288 §3: after '>' only OWS, ';' or ',' may follow"))
    add(Vector("lt-in-target", f'<{OWN}&cursor=a<b>; rel="next"', UNKNOWN, "RFC 3986 §2.1-§2.3, App. A (in neither reserved nor unreserved): '<' is no URI character"))

    for text, expect, why, grade, note in RELS:
        target = NEXT_URL if expect == NEXT else OTHER
        also = (UNKNOWN,) if grade == "judgement" and expect == NEXT else ()
        add(Vector(f"rel:{text}", f"<{target}>; {text}", expect, f"RFC 8288 {why}" if why.startswith("§") else why, grade,
                   next_url=target if expect == NEXT else None, also=also, note=note))
    for text, expect, why, grade, note in PARAMS:
        header = f'<{NEXT_URL}>; rel="next"; {text}'
        cite = why if why.startswith("RFC") else f"RFC 8288 {why}"
        add(Vector(f"param:{text}", header, expect, cite, grade, next_url=NEXT_URL if expect == NEXT else None, note=note))
        add(Vector(f"param-first:{text}", f'<{NEXT_URL}>; {text}; rel="next"', expect, cite, grade, next_url=NEXT_URL if expect == NEXT else None, note=note))

    # RFC 8288 §3.2: `anchor` overrides the link context; "link applications MUST NOT process the link without applying the anchor". A next link whose context
    # is another resource (or a fragment of this one) is not this listing's next page. Not a next link, and not proof there is none: UNKNOWN (ABSENT also
    # conformant); following it as if it were this page's is not.
    ctx = "https://other.example/ctx"
    why = "RFC 8288 §3.2: the anchor overrides the link context, and a link MUST NOT be processed without applying it; §3.3: rel is relative to that context"
    for name, header in (("anchor-other-resource", f'<{NEXT_URL}>; rel="next"; anchor="{ctx}"'), ("anchor-first", f'<{NEXT_URL}>; anchor="{ctx}"; rel="next"'),
                         ("anchor-fragment", f'<{NEXT_URL}>; rel="next"; anchor="#foo"')):
        add(Vector(name, header, UNKNOWN, why, "judgement", also=(ABSENT,), note="the context of this link is not the listing"))
    add(Vector("anchor-same-context", f'<{NEXT_URL}>; rel="next"; anchor="{OWN}"', NEXT, why, "judgement", also=(UNKNOWN,), next_url=NEXT_URL,
               note="the anchor names the context the link has by default (the request), so applying it changes nothing"))
    # RFC 8288 §3.3: `rev` expresses the relationship in the reverse direction (a link from B to A with REV="X" is a link from A to B with REL="X"); it is deprecated
    # and is not a forward `next`
    why = "RFC 8288 §3.3: rev is the reverse direction (deprecated), not rel; rel MUST be present"
    add(Vector("rev-only", f'<{NEXT_URL}>; rev="next"', ABSENT, why, "judgement", also=(UNKNOWN,), note="no rel; the only relation is the reverse one"))
    add(Vector("rel-prev-rev-next", f'<{NEXT_URL}>; rel="prev"; rev="next"', ABSENT, why, "judgement", also=(UNKNOWN,), note="forward prev, reverse next: not a forward next"))

    for target, section in ((t, s) for t, s, _ in VALID_TARGETS):
        base = f"RFC 3986 {section}"
        grade, also = ("judgement", (UNKNOWN,)) if target in SCHEME_SPECIFIC else ("grammar", ())
        add(Vector(f"target-valid:{target!r}", f'<{target}>; rel="prev"', ABSENT, base, grade, also=also, note="a valid URI-Reference on a link that is not next"))
        add(Vector(f"target-valid-beside-next:{target!r}", f'<{NEXT_URL}>; rel="next", <{target}>; rel="prev"', NEXT, base, grade, next_url=NEXT_URL,
                   also=tuple(a for a in also if a != ABSENT)))
    for target, section in INVALID_TARGETS:
        base = f"RFC 3986 {section}"
        add(Vector(f"target-invalid:{target!r}", f'<{target}>; rel="prev"', UNKNOWN, base, note="not a URI-Reference: the header cannot be read, so it ends nothing"))
        add(Vector(f"target-invalid-beside-next:{target!r}", f'<{NEXT_URL}>; rel="next", <{target}>; rel="prev"', UNKNOWN, base, "contract",
                   also=(NEXT,), next_url=NEXT_URL, note="one unreadable link-value: all-or-nothing reading is documented; salvaging the clean next link is also conformant"))
        add(Vector(f"target-invalid-before-next:{target!r}", f'<{target}>; rel="prev", <{NEXT_URL}>; rel="next"', UNKNOWN, base, "contract",
                   also=(NEXT,), next_url=NEXT_URL, note="as above"))
        add(Vector(f"target-invalid-as-next:{target!r}", f'<{target}>; rel="next"', UNKNOWN, base, note="a next link that is no URI-Reference is no continuation"))
    for cursor, section in VALID_CURSORS:
        url = f"{OWN}&cursor={cursor}"
        add(Vector(f"cursor-valid:{cursor!r}", f'<{url}>; rel="next"', NEXT, f"RFC 3986 {section}", next_url=url))
    for cursor, section in INVALID_CURSORS:
        add(Vector(f"cursor-invalid:{cursor!r}", f'<{OWN}&cursor={cursor}>; rel="next"', UNKNOWN, f"RFC 3986 {section}",
                   note="a continuation made of an invalid URI is never followed (R9-1)"))
        add(Vector(f"cursor-invalid-prev:{cursor!r}", f'<{OWN}&cursor={cursor}>; rel="prev"', UNKNOWN, f"RFC 3986 {section}",
                   note="and a header that holds one cannot be read, so it is not the end"))
    for target, expect, why, grade, note in FOLLOW:
        resolved = RESOLVED.get(target)
        also = (UNKNOWN,) if expect == NEXT and grade == "judgement" else ()
        next_url = resolved if resolved is not None else (target if expect == NEXT and grade != "judgement" else None)
        add(Vector(f"follow:{target}", f'<{target}>; rel="next"', expect, why, grade, next_url=next_url, also=also, note=note))
    return out


VECTORS = tuple(_vectors())
assert len({v.name for v in VECTORS}) == len(VECTORS), "vector names must be unique"
