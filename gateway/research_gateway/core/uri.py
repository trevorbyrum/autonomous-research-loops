"""RFC 3986 URI syntax, resolution and comparison: what a link target or a relation type is allowed to be, and where a relative one points.

A target is valid when it matches the grammar of Appendix A, not when it avoids a list of characters: `%GG`, a trailing `%`, an unclosed
`[`, a non-ASCII letter and a space are each outside it for a different production, and a list of exceptions finds the next one late.
`split` is the decomposition of Appendix B (it accepts any string); the pieces are then each held to their production. Every character
class is spelled out in ASCII, and every match is a `fullmatch`: no `\\d` (it reads Arabic-Indic digits as digits), no `$` (it ignores a
final newline), no case folding (it reads U+212A as `k`).

`resolve` is §5.2 (transform references, merge, remove_dot_segments) and `same_resource` is §6.2.2 and §6.2.3 (syntax- and scheme-based
normalisation), both on the split pieces, so that a relative reference means what RFC 8288 §3.1 says it means, and a reference that
names the request itself is recognised as that however it is spelled.
"""
from __future__ import annotations

import re
from typing import NamedTuple

_UNRESERVED = r"A-Za-z0-9\-._~"
_SUB_DELIMS = r"!$&'()*+,;="
_PCT = r"%[0-9A-Fa-f]{2}"
_PCHAR = rf"(?:[{_UNRESERVED}{_SUB_DELIMS}:@]|{_PCT})"
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+\-.]*")
_USERINFO = rf"(?:[{_UNRESERVED}{_SUB_DELIMS}:]|{_PCT})*"
_REG_NAME = rf"(?:[{_UNRESERVED}{_SUB_DELIMS}]|{_PCT})*"
_AUTHORITY = re.compile(rf"(?:{_USERINFO}@)?(?P<host>\[[^\]]*\]|{_REG_NAME})(?::[0-9]*)?")
_IPV_FUTURE = re.compile(rf"[vV][0-9A-Fa-f]+\.[{_UNRESERVED}{_SUB_DELIMS}:]+")
_H16 = re.compile(r"[0-9A-Fa-f]{1,4}")
_IPV4 = re.compile(r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9][0-9]|[0-9])(?:\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9][0-9]|[0-9])){3}")
_SEGMENT = re.compile(rf"{_PCHAR}*")
_SEGMENT_NZ = re.compile(rf"{_PCHAR}+")
_SEGMENT_NZ_NC = re.compile(rf"(?:[{_UNRESERVED}{_SUB_DELIMS}@]|{_PCT})+")
_QUERY = re.compile(rf"(?:{_PCHAR}|[/?])*")   # the fragment is the same production
_PARTS = re.compile(r"(?:([^:/?#]+):)?(?://([^/?#]*))?([^?#]*)(?:\?([^#]*))?(?:#(.*))?", re.S)   # RFC 3986 Appendix B


class Parts(NamedTuple):
    """A reference's five components; None is a component whose delimiter is not there (the path is never None)."""
    scheme: str | None
    authority: str | None
    path: str
    query: str | None
    fragment: str | None


def split(reference: str) -> Parts:
    """Appendix B: any string breaks down into the five components, well formed or not. Nothing is checked."""
    return Parts(*_PARTS.fullmatch(reference).groups())


def _ipv6(text: str) -> bool:
    """IPv6address: eight groups of one to four hex digits, the last two of which may be an IPv4address; or fewer than eight with one `::`."""
    head, compressed, tail = text.partition("::")
    left = head.split(":") if head else []
    right = tail.split(":") if tail else []
    if not compressed:
        right, left = left, []
    count = len(left) + len(right)
    if right and _IPV4.fullmatch(right[-1]):
        count += 1                                      # an IPv4address stands for two groups, and only at the very end
        right = right[:-1]
    if not all(_H16.fullmatch(g) for g in (*left, *right)):
        return False
    return count <= 7 if compressed else count == 8


def _host(authority_match: re.Match) -> bool:
    host = authority_match.group("host")
    return not host.startswith("[") or bool(_IPV_FUTURE.fullmatch(host[1:-1]) or _ipv6(host[1:-1]))


def _path(path: str, *, authority: bool, scheme: bool) -> bool:
    """path-abempty after an authority; otherwise path-absolute, path-rootless (after a scheme) or path-noscheme (after none), or empty."""
    if authority:
        return path == "" or (path.startswith("/") and all(_SEGMENT.fullmatch(s) for s in path[1:].split("/")))
    if path == "":
        return True
    if path.startswith("/"):
        return not path.startswith("//") and all(_SEGMENT.fullmatch(s) for s in path[1:].split("/"))
    first, *rest = path.split("/")
    return bool((_SEGMENT_NZ if scheme else _SEGMENT_NZ_NC).fullmatch(first)) and all(_SEGMENT.fullmatch(s) for s in rest)


def _valid(text: str, *, absolute: bool) -> bool:
    scheme, authority, path, query, fragment = split(text)
    if scheme is None and absolute:
        return False
    if scheme is not None and not _SCHEME.fullmatch(scheme):
        return False
    if authority is not None:
        a = _AUTHORITY.fullmatch(authority)
        if a is None or not _host(a):
            return False
    return (_path(path, authority=authority is not None, scheme=scheme is not None)
            and (query is None or bool(_QUERY.fullmatch(query))) and (fragment is None or bool(_QUERY.fullmatch(fragment))))


def is_uri_reference(text: str) -> bool:
    """URI-reference = URI / relative-ref (Appendix A): what a link target and an `anchor` value must be."""
    return _valid(text, absolute=False)


def is_uri(text: str) -> bool:
    """URI = scheme ":" hier-part [ "?" query ] [ "#" fragment ] (Appendix A): what an extension relation type must be (RFC 8288 §3.3)."""
    return _valid(text, absolute=True)


def _remove_dot_segments(path: str) -> str:
    """§5.2.4, as written: input and output buffers, one rule applied per pass."""
    out, rest = [], path
    while rest:
        if rest.startswith("../"):
            rest = rest[3:]
        elif rest.startswith("./"):
            rest = rest[2:]
        elif rest.startswith("/./"):
            rest = rest[2:]
        elif rest == "/.":
            rest = "/"
        elif rest.startswith("/../"):
            rest = rest[3:]
            out = out[:-1]
        elif rest == "/..":
            rest = "/"
            out = out[:-1]
        elif rest in (".", ".."):
            rest = ""
        else:
            end = rest.find("/", 1)
            end = len(rest) if end < 0 else end
            out.append(rest[:end])
            rest = rest[end:]
    return "".join(out)


def _recompose(p: Parts) -> str:
    """§5.3."""
    return ((f"{p.scheme}:" if p.scheme is not None else "") + (f"//{p.authority}" if p.authority is not None else "") + p.path
            + (f"?{p.query}" if p.query is not None else "") + (f"#{p.fragment}" if p.fragment is not None else ""))


def resolve(base: str, reference: str) -> str:
    """The target URI of `reference` against `base` (§5.2.2, strict: a reference with a scheme keeps it). `base` is an absolute URI; its
    own fragment plays no part."""
    r, b = split(reference), split(base)
    if r.scheme is not None:
        return _recompose(Parts(r.scheme, r.authority, _remove_dot_segments(r.path), r.query, r.fragment))
    if r.authority is not None:
        return _recompose(Parts(b.scheme, r.authority, _remove_dot_segments(r.path), r.query, r.fragment))
    if r.path == "":
        return _recompose(Parts(b.scheme, b.authority, b.path, r.query if r.query is not None else b.query, r.fragment))
    if r.path.startswith("/"):
        path = _remove_dot_segments(r.path)
    else:   # §5.2.3: the reference's path after all but the last segment of the base's, or after "/" if the base has an authority and no path
        merged = "/" + r.path if b.authority is not None and b.path == "" else b.path[:b.path.rfind("/") + 1] + r.path
        path = _remove_dot_segments(merged)
    return _recompose(Parts(b.scheme, b.authority, path, r.query, r.fragment))


_DEFAULT_PORTS = {"http": "80", "https": "443"}
_PLAIN = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _pct(text: str) -> str:
    """§6.2.2.1 and §6.2.2.2: percent-escapes in upper case, and an escaped unreserved character as the character itself."""
    def one(m: re.Match) -> str:
        ch = chr(int(m.group(1), 16))
        return ch if ch in _PLAIN else "%" + m.group(1).upper()
    return re.sub(r"%([0-9A-Fa-f]{2})", one, text)


def _normal(url: str) -> tuple:
    """The parts of a URI that name a resource, normalised by §6.2.2 and §6.2.3 in the RFC's order: scheme and host lower-cased, escapes as `_pct`, then dot
    segments removed, the default port and an empty path made explicit; the fragment last."""
    scheme, authority, path, query, fragment = split(url)
    scheme = (scheme or "").lower()
    userinfo, _, hostport = (authority or "").rpartition("@")
    end = hostport.find("]") + 1 if hostport.startswith("[") else len(hostport.split(":")[0])   # an IP-literal holds colons of its own
    host, port = hostport[:end], hostport[end:].lstrip(":")
    path = _remove_dot_segments(_pct(path)) or ("/" if authority is not None and scheme in _DEFAULT_PORTS else "")   # §6.2.2.2 before §6.2.2.3: `%2e%2e` is `..`
    return (scheme, _pct(userinfo), _pct(host).lower(), "" if port == _DEFAULT_PORTS.get(scheme) else port, path, None if query is None else _pct(query),
            None if fragment is None else _pct(fragment))


def same_resource(a: str, b: str, *, fragment: bool = False) -> bool:
    """Whether two URIs name one resource by the normalisation of §6.2.2 and §6.2.3. A fragment is not sent in a request, so it does not
    distinguish two requests; it does distinguish two contexts (`fragment=True`: RFC 8288 §3.2, a fragment of a resource is not the resource)."""
    na, nb = _normal(a), _normal(b)
    return na == nb if fragment else na[:-1] == nb[:-1]
