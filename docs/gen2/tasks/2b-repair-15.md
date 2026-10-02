# Task 2b-repair-15 — close the final 2b review: chunk framing, the DNS bound, readiness, test claims

**Source:** Astra's final 2b review, `~/work/research-loops-public/private/reviews/gen2-2b-final-astra-review-20261002.md`, with evidence in `~/work/research-loops-public/private/evidence/astra-2b-final/`: `gateway-probes.json`, the `wire-*.bin` files, `stdlib-chunk-reader.txt`, `engine-extra-probes.json` and `per-test-audit.md`. Read them in full.

**Everything else in 13d and 14 was ruled ROOT-CAUSE and stays as it is.** The operator rulings stay in force: trust model B and the frozen format policy. The oracle stays unedited. This is a **finite** list. Don't add sealing layers or widen scope.

## Required
1. **Chunked framing is owned by the transport (F1, gateway, HIGH).** `_read_body` checks Content-Length but delegates chunked decoding to `http.client`. That decoder parses sizes with a permissive `int(line, 16)` (accepting `+0`, `0x0` and signed sizes), doesn't check the CRLF after each chunk's data, and treats EOF as the end of the trailers. Make `Transport` own chunked framing per RFC 9112 §7.1:
   - **chunk-size syntax:** `1*HEXDIG`, with optional chunk extensions;
   - **the CRLF after each chunk's data;**
   - **the last chunk:** `0`, then the trailer section, then the final CRLF.

   Anything else, including EOF anywhere before the final CRLF, is `IncompleteRead`/invalid framing, and no load can succeed. Keep these unchanged:
   - valid extensions and trailers (trailer values are not interpreted);
   - the 256 MiB bound;
   - the accepted close-delimited policy.

   Reading the raw stream (`fp`) under the transport's control is fine. Don't write a whole second HTTP parser: keep `http.client` for the status line and headers.

   Tests on loopback, through the real DOAJ loader, using Astra's exact wire captures:
   - every row of the F1 table fails with no successful count: header-only + `\r\n0` + EOF; first row + `\r\n0` + EOF; `+0` and `0x0`; a signed size; `XX` in place of the CRLF; a cut trailer;
   - positive controls pass: ordinary chunks, valid extensions, a fully terminated trailer, and a deliberately complete header-only CSV that returns 0.

   **Rewrite the test that required success for a cut trailer.**
2. **The deadline covers name resolution (F2, engine, MEDIUM).** `_connect` calls a synchronous `getaddrinfo`, which can't be interrupted, so an exchange can overrun its deadline by the resolver's own time. Under the brief's constraints (no thread left running, no new spawn path in the client, supervisor owns child lifecycles), the root fix is: **an exchange never resolves names.**
   - An IP-literal endpoint needs no resolution.
   - For a hostname, resolve the configured gateway endpoint (`GEN2_GATEWAY_URL`, `http://gateway:8765` in DEPLOYMENT-CONTRACT) **outside any exchange**, at client construction or startup. Re-resolve only through an explicit, owned path, for example on a connection failure, recorded as an observation and done before the next exchange's deadline starts. Never inside an exchange's deadline.
   - Make clear which step owns the time spent resolving at startup or re-resolution. For example, if the supervisor's existing start or readiness deadline already bounds the process's startup, say so and cite where.
   - Keep TLS server-name checking correct, so the original hostname is used for SNI and certificate verification.
   - Test it: a substituted slow resolver (as in Astra's probe) no longer extends any exchange; an IP literal never resolves; a re-resolution doesn't happen inside an exchange.

   If you conclude that some unbounded resolution still has to sit on a deadline path, **stop and report it as a residual for the operator**. Don't present it as closed.
3. **Bounded readiness through the end of the line (F3, engine test helper, MEDIUM).** `gen2/tests/children.py` `await_line` does one bounded `select` and then an unbounded `readline`. Read the readiness line under **one deadline** until its newline arrives, and reject a line that completes late. Test:
   - a partial line followed by a delayed remainder (Astra's `r` … `eady\n` case) fails at the deadline;
   - a line that never completes fails at the deadline, with cleanup run;
   - a silent child fails;
   - a timely line passes.
4. **The 8 test claims and 1 contract test (F4, LOW).** Fix each item in `per-test-audit.md` as Astra specifies, either by asserting the claim or by narrowing the name or docstring:
   - `CloseDelimited…shorter_document`;
   - `TheRunner…returns_the_loaded_count`;
   - `ThroughTheIndexLoad…commits_without_a_rollback`;
   - `Inventory…exactly_the_ones_that_read_an_answer`;
   - `GuardsStayBounded…four_spellings`;
   - `ReadinessTest…even_when_the_handshake_failed`;
   - `TheTrustModel…relabelled_outcome`, whose docstring must match the corrected E-2 and 2e2;
   - `Bound…before_any_of_the_body_is_read`.

   The contract test is item 1's cut-trailer test.
5. **Keep Astra's two socket-mutant controls.** Astra supplied timely controls for the two deadline-socket mutants that had none in the package. Add them to the maintained mutation suite as their paired controls.

## Done means
- Astra's F1 wire captures, F2 resolver probe and F3 partial-line probe are rebuilt as regressions; they fail on `c0d963d` and pass now.
- `make gen2-check` and `make gen2-gateway` exit 0 when run unpiped.
- The oracle is unedited.

## Constraints
- Branch gen2.
- Gateway `Transport` for item 1, the engine client and test helpers for items 2–3, and tests anywhere for item 4.
- No provider API calls, no personal data.
- Never touch the live gen-1 gateway.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-15/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Completion report:
  - each root cause in one sentence;
  - how chunked completion and DNS are now bounded, and by whom;
  - net lines;
  - a literally-true Remaining section.
