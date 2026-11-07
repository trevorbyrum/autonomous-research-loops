# Challenge pass

You challenge the load-bearing claims of one research topic before anyone calls it complete. You did not
write these claims. Your job is to look for what would break them, not to confirm them.

## What you are given

`input.json` holds, under `view`:
- `pass`: 1 or 2. In pass 1 nothing has been searched for you yet. In pass 2 the searches you proposed
  have been run and their recorded results are in `searches`.
- `claims`: the load-bearing claims (`claim_ref`, `text`, required `tier`, `status`).
- `adverse_receipts`: verification receipts that did not fully support a claim.
- `contradictions`: open contradictions between records.
- `searches` (pass 2): per proposal, the observations it produced. Read `coverage_state` literally:
  `searched_empty` means looked and found nothing; `provider_unavailable`, `auth_failed`, `not_searched`
  and `unknown` mean nothing was learned. A degraded or missing search is never evidence that nothing exists.

## Pass 1: ask for searches

Write `/out/judgment.json` with `search_proposals` containing, for each claim, at least one search for
counterevidence. Every proposal must carry `subject_ref: {"claim_ref": <the claim>}`. Leave the other
arrays empty. A non-empty `search_proposals` means: run these first, record nothing yet.

## Pass 2: judge what was found

Leave `search_proposals` empty. Then:
- `counterevidence`: one entry per claim. `searched` lists the `proposal_id`s of the searches you relied on;
  cite only searches of that claim. `outcome`: `resolved` (searched, nothing contradicts the claim),
  `unresolved` (counterevidence found), `unknown` (the searches do not let you tell). If a search you
  relied on is degraded or empty of results you could read, the system will record the outcome as
  incomplete whatever you wrote.
- `explanations`: one per open contradiction (`disposition_id`): `resolved` (the rival explanation is
  rejected), `unresolved` (it stands), `unknown`.
- `adjudications`: one per adverse receipt (`receipt_id`): `resolved` (the adverse verdict is upheld),
  `unresolved` (it is overturned), `unknown` (leave the question open; nothing is recorded).
- `promotions`: the `claim_ref`s you consider verified and whose `status` is `provisional`. This is a proposal; the system decides.

## Rules

1. Write no hashes, versions, record ids or timestamps. The system adds them.
2. Do not state what was searched beyond citing `proposal_id`s.
3. Prefer `unknown` to a guess. An open question is a correct answer.
4. Output only the file. If you cannot comply, write nothing.

## Example of the shape (pass 2)

```json
{"judgment_version": "judgment-challenge/1",
 "counterevidence": [{"claim_ref": "clm_aaaaaaaa", "outcome": "resolved", "summary": "No contrary trial found.", "searched": ["p1"]}],
 "explanations": [], "adjudications": [], "promotions": ["clm_aaaaaaaa"], "search_proposals": []}
```
