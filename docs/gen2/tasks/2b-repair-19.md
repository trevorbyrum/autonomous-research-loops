# Task 2b-repair-19 — engine: the gateway port is validated by value, not by text width

**Source:** Astra's 2b-repair-18 review, `~/work/research-loops-public/private/reviews/gen2-2b-repair-18-astra-review-20261003.md` (R18-1). Evidence is in `private/evidence/astra-2b-repair-18/`: `decimal_port_regression.py`, `decimal-port-results.json`, and the logs.

Everything else in 18 is accepted. Change only what R18-1 needs.

## Required
1. `_ORIGIN` in `gen2/gateway_client/client.py` limits the port to `[0-9]{1,5}`. That refuses valid zero-padded ports such as `:000080`, `:065535` and `:000443`, even though H-6 specifies "an optional decimal port from 1 to 65535" and `:08765` is already accepted. RFC 3986 `port = *DIGIT`.
   - **Fix:** accept a run of ASCII decimal digits and validate the integer value (1–65535), canonicalizing as now. Keep refusing:
     - zero;
     - values above 65535;
     - signs, hexadecimal and non-digits;
     - an empty port after `:`;
     - non-ASCII digits.
   - Cap the digit run at a generous, documented length (for example 32) so a pathological string can't cost unbounded work. State the cap in H-6 as part of the contract. It mustn't be an unstated textual rule.
2. **Tests:**
   - Astra's five cases (`:00080`, `:000080`, `https://GATEWAY.TEST:000443/`, `:065535`, `https://[0:0:0:0:0:0:0:1]:000443/`) are accepted and canonicalized.
   - The wire case (`127.0.0.1:037433`) reaches its listener.
   - Adjacent refusals still hold.
   - Add a mutant that re-imposes the five-digit limit, with a paired control.
3. Run `make gen2-check` and `make gen2-gateway` unpiped; both must exit 0. `gateway/` and the oracle stay unchanged.

## Constraints
- Branch gen2, `gen2/` only.
- No provider calls.
- Never touch the live gen-1 gateway or 127.0.0.1:8765.
- Don't search `/home/trevor/work` recursively.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-19/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- The completion report gives the root cause in one sentence, net lines, and Remaining.
