# Task 2b-repair-20 — engine: project-owned canonical address serialization (CI design D5)

**Sources:**
- `docs/gen2/CI-DESIGN.md` §8 and D5 (operator-approved 2026-10-05).
- Astra's CI design review finding 9: `~/work/research-loops-public/private/reviews/gen2-ci-design-astra-review-20261004.md`. Its evidence is `private/evidence/astra-ci-design/gha-job-111365686308.log` around line 2954, which shows the Python 3.12.14 failure.

## Defect
`gen2/gateway_client/client.py:195` builds the canonical host with `str(ip)`. CPython 3.12.14 changed `IPv6Address.__str__` for IPv4-mapped addresses: 3.12.3 gives `::ffff:7f00:1`, while 3.12.14 gives `::ffff:127.0.0.1`. The engine's canonical origin, host and admitted-address representation therefore depend on the exact patch release. The 2b acceptance holds only on 3.12.3.

Severity: this is a representation/acceptance defect only. It causes no wrong-destination connection and no token leak.

## Required
1. **Root fix: a project-owned canonical serialization** of a parsed address's *value and family*.
   - Use it consistently for the origin, the host and the admitted-address representation, including whatever `_literal` and the endpoint owner store and compare.
   - Keep the **accepted spelling**: the 3.12.3 forms the accepted tests and docs (H-6, DEPLOYMENT-CONTRACT) use. Change it only through an explicit contract amendment, and none is requested here.
   - `.compressed` is **not** acceptable, because it also delegates to the library's string rendering. Don't just change the expected strings to the newer output either.
2. **Tests.**
   - Cover equivalent dotted and hex IPv4-mapped inputs (`::ffff:127.0.0.1`, `::ffff:7f00:1`), together with the other accepted and refused forms. All of them must canonicalize identically **regardless of interpreter**.
   - Make the test independent of the running interpreter's `ipaddress.__str__`: for example, assert against literal expected strings, and add a unit test that monkeypatches or simulates the newer rendering to prove the serializer doesn't use it.
   - If a Python 3.12.14 or newer interpreter is available locally (e.g. `uv python install 3.12.14`, offline if cached), run the affected test class on it too. If none is available, say so. Don't download anything that needs provider calls; fetching Python itself is fine.
3. **Pin the reference precisely.** ENVIRONMENT.md should state the reference interpreter's patch version exactly (3.12.3) and the SQLite version. Say that the pin is for reproducibility, and that portability is covered by the serializer and the planned nightly drift job (CI design D4: Jenkins nightly, not GitHub Actions).
4. **Mutants.** Add a mutant that restores `str(ip)` or `.compressed`, killed under the simulated newer rendering, with a paired control.
5. **Make targets.** Run `make gen2-check` and `make gen2-gateway` unpiped; both must exit 0. Leave `gateway/` and the oracle unchanged.

## Constraints
- Branch `gen2`. Commit directly; the PR workflow isn't live yet, per the charter amendment.
- Change only engine code (`gen2/`), its tests and tooling, and ENVIRONMENT.md.
- No provider calls.
- Never touch the live gen-1 gateway or 127.0.0.1:8765. Don't search `/home/trevor/work` recursively.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-20/`.
- Commit messages end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
- The completion report gives the root cause in one sentence, the net line count, and a literally true Remaining section.
