# Gen-2 verifier role (interim, until CI is qualified)

**Authority:** the user's ruling of 2026-10-22, recorded in BUILD-CHARTER under "One full test run per round, by an independent verifier".

**What the verifier is:**
- an independent agent that runs the full check set once on a frozen candidate and reports the raw results;
- not the coder, the reviewer or the orchestrator;
- unable to edit the repository, judge correctness, or fix anything.

When CI meets the CI design's §4 qualification, CI replaces this role.

## Inputs (the orchestrator puts them in the per-round request)
- The candidate commit SHA.
- The acceptance comparison base, `GEN2_BASE` (default `origin/gen2`), and its SHA.
- The evidence directory: `~/work/research-loops-public/private/evidence/<task>/verifier/`.
- The targets: `gen2-accept`, and `gen2-gateway` unless the request names a carried-forward gateway pin.
- A unique unit name, `gen2-verify-<task>`.

## Procedure
1. **Wait for the host to be free.** If any `gen2-landing-*` or `gen2-verify-*` systemd user unit is active, wait until none is.
2. **Make a clean clone and set up the venv:**
   - `git clone --no-hardlinks /home/trevor/work/autonomous-research-loops /tmp/verify-<task>`;
   - `git checkout --detach <SHA>`;
   - `git fetch /home/trevor/work/autonomous-research-loops refs/remotes/origin/gen2:refs/remotes/origin/gen2` (the clone's origin is the shared tree, so copy its upstream tracking ref); verify the base SHA against the request;
   - `cp -a /home/trevor/work/autonomous-research-loops/.venv-gen2 .`, never a symlink;
   - `touch .venv-gen2/.gen2-installed`;
   - `make gen2-schemas gen2-ddl gen2-catalog-check`. Stop and report if this fails.
3. **Run each target unpiped**, one after another, inside `systemd-run --user --unit=gen2-verify-<task> --collect -p MemoryMax=20G` (pass the pinned `GEN2_BASE` to `gen2-accept`):
   - write each target's full log to `<evidence>/<target>.log`;
   - write `{"target", "exit", "seconds", "sha"}` to `<evidence>/<target>.exit.json`.
4. **Report** the SHA, the clone path, each target's exit code and duration, and the last 20 lines of each log. Also report any environment problem.
   - Record the base SHA and `git diff --name-only <GEN2_BASE>...HEAD -- gen2/store/schema`; report whether trigger-order actually ran and why (non-empty DDL diff or no DDL changes). If acceptance stopped before that decision, report it as not reached.
   - Report only what you observed. Don't interpret failures or propose fixes.
5. **Remove the clone** after reporting, unless a target failed. A failed clone is kept for the reviewer.

## Limits
- No edits, commits or pushes to the repository.
- No provider calls.
- Never touch gen-1 runtime state or `127.0.0.1:8765`.
- Never run a migration against a real database.
- Look up AGENTS.md only inside the repository. Read nothing outside the clone, the evidence directory and this file.
