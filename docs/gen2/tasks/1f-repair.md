# Task 1f-repair — correct the (d) evidence brief, the concurrency oracle, and two doc claims (narrow)

Read: `~/work/research-loops-public/private/reviews/gen2-1f-astra-review-20260929.md`, findings 1–3, with evidence under `/var/tmp/gen2-1f-astra-20260929/`. Demonstrations (a), (b), (d1), the characterization, and the authority/hygiene checks are accepted — don't disturb them. **Do not decide or reword DEPLOYMENT-CONTRACT §4(d)** — that stays with the operator; your job is to make the evidence in front of the operator factually exact.

## Finding 1 (HIGH): F1's premise is overstated — fix the brief, and extend the probe with the offline signal that does exist
Astra proved three distinct facts your F1 conflated:
- the pinned CLIs' status commands don't reject expired tokens (true, reproduced);
- **locally declared expiry IS readable offline**: the JWT `exp` claims in the fixtures decode to their declared expiries (RFC 7519 §4.1.4), and the other CLI's credential JSON exposes `expiresAt` directly;
- reading a claim is not authentication, ID-token vs access-token expiry differ, an expired access token can coexist with a usable refresh credential, opaque credentials may expose no expiry, and **provider-side revocation changes nothing locally** — that part of your claim stands.

Repair:
1. Rewrite AUTH-DEMO.md F1 to present exactly these distinctions (selected-command behavior / locally visible declared expiry / refreshability / unseen revocation), so the operator decides on correct facts.
2. Extend the capability probe to read locally declared expiry where the credential format exposes it (JWT `exp`, `expiresAt`), recording a past declared expiry as a dated failing/degraded capability fact with the typed hold — clearly labeled as *declared* expiry, not provider acceptance. Handle: opaque credentials (no claim → no verdict from this signal), ID vs access token distinction, refresh-credential presence noted structurally. No network, no quota, deterministic.
3. Split (d2) accordingly: a declared-expired fixture must now produce the fact+hold (demonstrable offline); an *undeclared*/revocation-style case remains the honestly-failing residual for the operator's disposition.
4. Tests + mutants for the new probe logic, paired controls included.

## Finding 2 (MEDIUM, Gate C): the concurrency oracle admits serial executions
The overlap assertion measures whole-probe windows, not runner-process execution. Repair per the review: retain evidence of overlapping *actual status-process execution* (distinct from whole-probe duration), and add a negative control that serializes runner execution after the outer start timestamp — that control must fail the overlap assertion. Keep the 20-round structure and the unchanged-credential assertion.

## Finding 3 (LOW): the shutdown note's SIGKILL claim
With `init: true`, the engine stops on SIGTERM (exit 143, ~0.12 s) within the grace period. Correct the note. Also correct the evidence doc's exit-code shorthand: the driver exits 1, GNU make exits 2.

## Constraints
Branch gen2 only. Never touch `gateway/`, gen-1's services or main; demo isolation rules unchanged (project `gen2-authdemo`, throwaway credentials only). Commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask exit statuses. Finish with the completion report as your final message (per finding: what changed, the reproduction/control now behaving, mutant evidence, final unpiped `make gen2-check` and the demo runs' exits). Don't end your turn waiting on a background run.
