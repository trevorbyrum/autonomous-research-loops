# Gen-2 verifier role (interim, until CI is qualified)

**Authority:** the user's ruling of 2026-10-22, recorded in BUILD-CHARTER under "One full test run per round, by an independent verifier".

**What the verifier is:**
- an independent agent that runs the full check set once on a frozen candidate and reports the raw results;
- not the coder, the reviewer or the orchestrator;
- unable to edit the repository, judge correctness, or fix anything.

When CI meets the CI design's §4 qualification, CI replaces this role.

Roots are environment variables: `$GEN2_EVIDENCE` (the evidence root, outside the repository) and `$GEN2_HEAVY_LOCK` (the heavy-suite lock file). The request names them.

## Inputs (the orchestrator puts them in the per-round request)
- The candidate commit SHA: the merged-tree SHA, which is the PR head after current `origin/gen2` has been merged into it.
- The acceptance comparison base, `GEN2_BASE` (default `origin/gen2`), and its SHA.
- The evidence directory: `$GEN2_EVIDENCE/<task>/verifier/`.
- The targets: `gen2-accept`, and `gen2-gateway` unless the request names a carried-forward gateway pin.
- A unique unit name, `gen2-verify-<task>`.

## Procedure
1. **Clone from GitHub at the pinned SHA.** Never clone a local checkout: its `origin/gen2` can be stale.
   - `git clone --no-hardlinks <github-url> /tmp/verify-<task>`;
   - `git fetch origin <SHA>` if the SHA is not on a branch, then `git checkout --detach <SHA>`;
   - verify `origin/gen2` against the base SHA in the request.
2. **Build the clone's own venv:** `make gen2-venv` inside the clone. Never copy or symlink another checkout's venv. Then `make gen2-schemas gen2-ddl gen2-catalog-check`. Stop and report if this fails.
3. **Wait for the host.** Take the heavy lock with `flock "$GEN2_HEAVY_LOCK"` around the run, and start only when the five-minute load average (`load5`) is below 8. Waiting on the lock is the queue; don't poll systemd units.
4. **Run each target unpiped**, one after another, under `flock "$GEN2_HEAVY_LOCK" systemd-run --user --wait --collect --unit=gen2-verify-<task> -p MemoryMax=20G`, passing the pinned `GEN2_BASE` to `gen2-accept` (`make gen2-accept GEN2_BASE=<merge-base>`):
   - write each target's full log to `$GEN2_EVIDENCE/<task>/verifier/<target>.log`;
   - write the script's own exit record, `{"target", "exit", "seconds", "sha"}`, to `<target>.exit.json` in the same directory. **That JSON is the result.** systemd's status is not.
5. **Report** the SHA, the clone path, each target's exit and seconds from the JSON, and the last 20 lines of each log. Also report any environment problem.
   - Record the base SHA. Trigger-order is retired (operator ruling S2-2, 2026-10-27): `gen2-accept` is gen2-check (sharded units). Mutation is not part of it (S4-8). Report the shard count and the unit test count.
   - Report only what you observed. Don't interpret failures or propose fixes.
6. **Remove the clone** after reporting, unless a target failed. A failed clone is kept for the reviewer.

## Limits
- No edits, commits or pushes to the repository.
- No provider calls.
- Never touch gen-1 runtime state or the live gateway port.
- Never run a migration against a real database.
- Look up AGENTS.md only inside the repository. Read nothing outside the clone, the evidence directory and this file.

## Campaign procedure (at phase gates, report-only)
1. Clone at the `origin/gen2` head as in Procedure step 1, build the venv as in step 2, and read `GEN2_BASE` from the header of `docs/gen2/MUTATION-LEDGER.md`.
2. Run `make gen2-mutation-report` unpiped, under `flock "$GEN2_HEAVY_LOCK" systemd-run --user --wait --collect --unit=gen2-campaign-<date> -p MemoryMax=20G`. (`make gen2-campaign GEN2_BASE=<last-campaign-sha>` is the manual form.)
3. Write the log, `<target>.exit.json` and `mutation-report.json` to `$GEN2_EVIDENCE/mutation-campaigns/<date>/`.
4. Report the head SHA and the survivors (file:line, operator). The orchestrator records them in the ledger.
