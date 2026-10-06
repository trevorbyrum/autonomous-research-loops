"""The RFC 8288 `Link` header: what an answer says about the next page (task 2q-b5; moved out of base.py).

`parse_links` reads the list syntax of RFC 9110 to its last character (one function per step of the grammar: `_target`, `_param`, `_quoted`, `_token`), `relation_types` reads a `rel`
value, `next_link` says what the header tells of the next page, and `own_link` says whether a provider's link may be followed as a continuation. Nothing here makes a request or reads
a body: it takes the response's headers and URL. The module name starts with `_` because it is a part of the client, not an adapter (the loader in `adapters/__init__.py` skips such names);
an adapter that pages by link (`huggingface`) imports `next_link` and `own_link` from here, not through base.py.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import NamedTuple

from ..core import uri
from ._response import Response


class LinkSyntax(ValueError):
    """A `Link` header (RFC 8288) that cannot be read to its last character, or whose relations cannot be told."""


_TCHAR = frozenset("!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
_QDTEXT = frozenset("\t !") | frozenset(chr(c) for c in (*range(0x23, 0x5C), *range(0x5D, 0x7F), *range(0x80, 0x100)))   # RFC 9110 §5.6.4
_QUOTABLE = frozenset("\t") | frozenset(chr(c) for c in (*range(0x20, 0x7F), *range(0x80, 0x100)))                        # what a `\` may precede
# RFC 8288 §3.3: a relation type is a registered name (`LOALPHA *( LOALPHA / DIGIT / "." / "-" )`, compared without regard to case) or an
# absolute URI (an extension relation, core/uri.py); the `rel` value is one, or several separated by spaces
_REGISTERED_REL = re.compile(r"[A-Za-z][A-Za-z0-9.\-]*")


def _space(header: str, at: int) -> int:
    """`at`, moved past optional whitespace (RFC 9110 §5.6.3)."""
    while at < len(header) and header[at] in " \t":
        at += 1
    return at


def _token(header: str, at: int) -> tuple[int, str]:
    """The token (RFC 9110 §5.6.2) that starts at `at`: where it ends, and it."""
    start = at
    while at < len(header) and header[at] in _TCHAR:
        at += 1
    if at == start:
        raise LinkSyntax(f"Link header: expected a token at character {start}")
    return at, header[start:at]


def _quoted(header: str, at: int) -> tuple[int, str]:
    """The quoted-string (RFC 9110 §5.6.4) whose opening quote stands at `at`: where it ends, and its text with the backslash escapes undone."""
    chars, at = [], at + 1
    while at < len(header) and header[at] != '"':
        if header[at] == "\\":
            at += 1
            if at == len(header) or header[at] not in _QUOTABLE:
                raise LinkSyntax(f"Link header: a quoted-pair that is not one, at character {at}")
        elif header[at] not in _QDTEXT:
            raise LinkSyntax(f"Link header: a character a quoted string cannot hold, at character {at}")
        chars.append(header[at])
        at += 1
    if at == len(header):
        raise LinkSyntax("Link header: a quoted string is not closed")
    return at + 1, "".join(chars)


def _param(header: str, at: int) -> tuple[int, tuple[str, str | None]]:
    """The link parameter (RFC 8288 §3) whose `;` stands at `at`: where it ends, and (name lower-cased, value or None)."""
    at, name = _token(header, _space(header, at + 1))
    at, value = _space(header, at), None
    if at < len(header) and header[at] == "=":
        at = _space(header, at + 1)
        at, value = _quoted(header, at) if at < len(header) and header[at] == '"' else _token(header, at)
    return _space(header, at), (name.lower(), value)


def _target(header: str, at: int) -> tuple[int, str]:
    """The `<` URI-reference `>` that starts at `at` (RFC 8288 §3.1): where it ends, and the target."""
    end = header.find(">", at + 1) if header[at] == "<" else -1
    if end < 0:
        raise LinkSyntax(f"Link header: no <target> at character {at}")
    target = header[at + 1:end]
    if not uri.is_uri_reference(target):
        raise LinkSyntax(f"Link header: a target that is no URI-reference (RFC 3986), at character {end}")
    return _space(header, end + 1), target


def parse_links(header: str) -> list[tuple[str, list[tuple[str, str | None]]]]:
    """Every link-value of a `Link` header as (target, [(parameter name lower-cased, value)]), RFC 8288 §3 on the
    list syntax of RFC 9110: `<` target `>` and then `;` parameters in any order, each a token with an optional token
    or quoted-string value (backslash escapes undone; a quoted string holds only what RFC 9110 §5.6.4 allows). A comma
    or semicolon inside `<...>` or a quoted string belongs to it, and empty list elements are ignored. LinkSyntax for
    anything else, wherever it stands: nothing is guessed from a header that does not read through, because the one
    thing a reader cannot do with it is call it free of a next link."""
    n, i, out = len(header), _space(header, 0), []
    while i < n:
        if header[i] == ",":
            i = _space(header, i + 1)
            continue
        i, target = _target(header, i)
        params = []
        while i < n and header[i] == ";":
            i, param = _param(header, i)
            params.append(param)
        out.append((target, params))
        if i < n and header[i] != ",":
            raise LinkSyntax(f"Link header: unexpected {header[i]!r} at character {i}")
    return out


def relation_types(value: str | None) -> list[str]:
    """The relation types a `rel` value names, lower-cased: one or more, each a registered name or an absolute URI, separated by
    spaces (RFC 8288 §3.3). LinkSyntax for a value that is anything else — none at all, empty, a quote character or a control
    character of its own, a comma, a space at either end, another quoting — because a relation that cannot be told is not a relation
    that names no next page."""
    parts = value.split(" ") if value else [""]
    if "" in (parts[0], parts[-1]) or not all(_REGISTERED_REL.fullmatch(p) or uri.is_uri(p) for p in parts if p):
        raise LinkSyntax("Link header: a relation that is not a list of relation types")
    return [p.lower() for p in parts if p]


class NextLink(NamedTuple):
    """What a `Link` header says about the next page: `url` and `known`. A url is the continuation; no url with
    `known` is the header read whole and naming no next link (the absence a provider's own client treats as the end);
    no url and not `known` is a header that could not be read or names several different next pages — nothing is
    established, so it is neither a continuation nor an end."""
    url: str | None
    known: bool


def next_link(resp: Response) -> NextLink:
    """The answer's `Link: <...>; rel="next"` (RFC 8288), its target resolved against the URL asked (§3.1: RFC 3986 §5). Only the first
    `rel` of a link counts (§3.3), and its value must be a list of relation types (`relation_types`): a header that does not
    parse, a `rel` with no value or one that is no such list (`rel='next'`, `rel="\\"next\\""`, `rel=""`, `rel="next, prev"`), or two
    different next targets is not `known`. A link with no `rel` names no relation. A next link is no continuation, and no end either,
    when it is not this listing's: its `anchor` puts its context at another resource (§3.2), or its target is the request itself (a
    continuation that does not move on: asking it again is the same page again)."""
    lines = [v for k, v in resp.headers.items() if k.lower() == "link"]
    try:
        targets, unusable = set(), False
        for target, params in parse_links(", ".join(lines)):
            rel, anchor = (next(((v,) for k, v in params if k == name), None) for name in ("rel", "anchor"))   # the first of each counts; (None,) is one with no value
            if anchor is not None and (anchor[0] is None or not uri.is_uri_reference(anchor[0])):
                raise LinkSyntax("Link header: an anchor that is no URI-reference")
            if rel is None or "next" not in relation_types(rel[0]):
                continue
            url = uri.resolve(resp.url, target)
            if (anchor is not None and not uri.same_resource(uri.resolve(resp.url, anchor[0]), resp.url, fragment=True)) or uri.same_resource(url, resp.url):
                unusable = True
            else:
                targets.add(url)
    except ValueError:   # LinkSyntax
        return NextLink(None, False)
    return NextLink(targets.pop() if len(targets) == 1 and not unusable else None, len(targets) <= 1 and not unusable)


def own_link(url, endpoint: str, **same: str) -> str | None:
    """`url` when a request may follow it as a continuation of `endpoint`, else None. It must keep
    the endpoint's scheme, host, port and path, and carry no user info or fragment, so a continuation
    can never send a request elsewhere or carry credentials of its own: the adapter's credentials
    travel only in its own headers. Each `same` parameter must be named by the URL, with the given value: a continuation that
    leaves one out is some other listing's."""
    if not isinstance(url, str):
        return None
    try:
        u, e = urllib.parse.urlsplit(url), urllib.parse.urlsplit(endpoint)
        if (u.scheme, u.hostname, u.port, u.path) != (e.scheme, e.hostname, e.port, e.path):
            return None
    except ValueError:   # a malformed port
        return None
    if u.username is not None or u.password is not None or u.fragment:
        return None
    named = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    return url if all(named.get(k) == [v] for k, v in same.items()) else None


__all__ = ("next_link", "own_link")   # what an adapter may import from here (tests/inventory.py `import_findings` reads it, as it reads base.py's)
