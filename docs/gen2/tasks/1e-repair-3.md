# Task 1e-repair-3: redaction covers the serialized representation (single finding; final 1e round)

Read: `~/work/research-loops-public/private/reviews/gen2-1e-repair-2-astra-review-20260928.md`, finding 1 (the only open item; it is original finding 2, refined). Evidence: `/tmp/gen2-1e-repair-2-rereview-20260928/`. Recovery resumption and startup-log coverage are CLOSED; original findings 4/5/6/8 are closed; don't touch any of it.

## The defect
`Credentials.redact` checks semantic values against the token and one `json.dumps` spelling plus percent decoding; the HTTP writer then serializes without re-checking. JSON escaping can therefore *reconstruct* a configured token at the output boundary. Astra's reproductions, all with synthetic tokens accepted by the config rules:
- token `credential-\"-12345` (one backslash + quote) reassembled from an ID containing only the quote;
- a token starting with `"` completed by the serializer's own opening quote (token spanning the data/serialization boundary);
- backslash-count and literal-`\n` variants;
- an ID carrying `%5Cu0022` (percent-encoding of a JSON escape), where percent-decode *then* JSON-unescape reconstructs the token; literal `"` and mixed `\u00%32%32` variants likewise.

## Required repair (per the review, follow it exactly)
- Keep the pre-nesting semantic redaction.
- Make the credential check cover **the actual serialized representation** and the supported JSON/percent combinations — i.e., after (or against) final serialization, a configured token must not appear in the emitted bytes.
- Refuse unsafe IDs with a null ID **before dispatch**; an accepted request's correlation ID must not change.
- The final emitted JSON must remain valid: blind byte replacement can corrupt JSON when a match spans serialization structure — handle that.
- Astra's already-passing cases must stay passing: ordinary prefixes and nonsecret encoded IDs usable; the 199/200/201 length behavior preserved.

## Tests
One per reproduction above (each asserting the token's absence from the raw wire bytes, and command non-execution where the ID is refused), plus valid-JSON assertions on redacted output, plus controls that ordinary IDs and replies are untouched. Bind mutants: one that drops the serialized-representation check, one that redacts after dispatch instead of refusing before.

## Constraints
Branch gen2 only. Never touch `gateway/`, gen-1, running services or main. Commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with the completion report as your final message (what changed, each reproduction now handled, mutant evidence, final unpiped `make gen2-check` result). Don't end your turn waiting on a background run.
