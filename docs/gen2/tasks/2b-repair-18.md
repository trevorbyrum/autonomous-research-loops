# Task 2b-repair-18 — engine: the endpoint owner is the only source of a connection target

**Source:** Astra's 2b-repair-17 review, `~/work/research-loops-public/private/reviews/gen2-2b-repair-17-astra-review-20261003.md` (R17-1), with evidence in `private/evidence/astra-2b-repair-17/`: `encoded_withdrawal.py`, `stdlib-authority-source.txt`. Read them in full.

**Everything else in 17 is accepted:** the operation lease, serial instances, concurrency across instances, and the closed handler surface. The gateway contract stays closed. Change only what R17-1 needs.

## Root cause (R17-1)
Connection authority still has two interpretations:
- `_Endpoint` classifies the host that `urlsplit` returns, so it reads `127.0.0.%31` as a *name*;
- `urllib.request.Request._parse` unquotes the host to `127.0.0.1`;
- `_connect` independently tries `_literal(host, port)` on the decoded host *before* it consults the owner's mapping.

Result: a withdrawn endpoint still connects. In Astra's probe, after a connection refusal and an NXDOMAIN, a search and a grant both reached a replacement listener with the bearer token, and the search recorded `searched_empty/complete/0/exhausted`.

## Required
1. **One validated origin representation, fixed at construction.**
   - Accept only:
     - an `http` or `https` scheme;
     - a host that is either a DNS name of LDH labels (RFC 1123; ASCII; no percent-encoding; no empty labels; IDNs only in their ASCII A-label form) or an IP literal parsed by `ipaddress` (IPv6 in brackets);
     - an optional decimal port;
     - no userinfo, query or fragment, and no path beyond an optional trailing `/`.
   - Refuse anything else with `ValueError` before any I/O. That includes percent-encoded hosts, alternate numeric spellings (`0x7f.1`, `2130706433`, octal), and anything `urlsplit` and urllib would read differently.
   - Store the canonical origin.
2. **The owner is the only source of a connection target.**
   - `_connect` gets its targets **only** from the endpoint owner's admitted addresses:
     - for a literal endpoint, the literal admitted at construction;
     - for a name, the published mapping.
   - It never derives a target from urllib's `Request` host, and never runs `_literal` on any host string at connect time.
   - A withdrawn name endpoint has no targets, whatever its spelling.
   - Keep ordinary literal behaviour: literals never go stale.
3. **Tests.**
   - Rebuild Astra's `encoded_withdrawal.py` as a regression: it fails on `4c360d0` and passes now. Cover search, grant, and a poll in progress across the representation change and withdrawal.
   - Controls:
     - an ordinary name withdraws and sends nothing;
     - an ordinary literal still connects;
     - the move to B works.
   - A table of refused endpoint spellings, including each alternate numeric form, percent-encoding and userinfo.
   - A mutant that restores connect-time `_literal` on the request host, with a paired control.
4. **Contract text.** State in INVARIANTS H-6 that the canonical origin and the owner's admitted addresses are the only connection authority.

## Done means
- `make gen2-check` and `make gen2-gateway` exit 0, run unpiped.
- `gateway/` and the oracle are unchanged.

## Constraints
- Branch gen2. Engine (`gen2/`), its tests and tooling only.
- No provider calls, no personal data.
- Never touch the live gen-1 gateway (its worktree, database, service, or 127.0.0.1:8765). Don't search `/home/trevor/work` recursively.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-18/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- The completion report gives the root cause in one sentence, net lines, and a literally true Remaining section.
