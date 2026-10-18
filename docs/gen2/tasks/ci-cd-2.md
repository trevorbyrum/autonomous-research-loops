# Task ci-cd-2: std v1.2, per-mode executions (platform gap-analysis step 4)

**Operator, 2026-10-18:** "Review/merge #12; Sol drafts v1.2 PR."
- Trevor reviews and merges ci-cd PR #12 (std v1.1).
- Sol drafts **std v1.2 (modes)** as an opt-in, backward-compatible PR, which Trevor reviews and merges.
- gen2 needs this so its full acceptance workload can run in Jenkins as separate executions. See ci-2: `private/evidence/ci-2/PLATFORM-REQUEST-v1.2-final.md` gives the measured modes, commands, durations and per-execution limits.

**Repo:** `trevorbyrum/ci-cd`, the CI trust root.
- **Work only in the dedicated clone `/home/trevor/work/ci-cd-gen2`.** Never touch `~/work/ci-cd`, which another session owns.
- **Branch `sol/std-v1.2`, based on `origin/lib/v1.1`** (PR #12, not yet merged). State the stacking in the PR. If #12 changes or merges before you finish, rebase onto it.
- **Open the PR only.** The base is `lib/v1.1` while #12 is open, and `main` once #12 merges. Trevor merges.
- Never push to `main`, never enable auto-merge, and never change repo settings, Jenkins, cir/cim or the VMs.

**Scope** (`docs/platform-gap-analysis.md` on `lib/v1.1`, "Step 4: v1.2 modes, schedules and integration interlock", and the sequence item 2):
- `CI_MODE`, derived as push/pr/integration/nightly and exported to every command. Distinguish scheduled runs from ordinary pushes.
- `modes`: per-mode commands and per-mode images, as a validated mode-aware config. **Scalar `lint`/`build`/`unit`/`image` keep working unchanged.**
- **Multiple executions for one mode.** gen2 needs its acceptance modes as separate executions, sequential or parallel, **each under its own timeout**. Use the gap analysis's mode/per-mode-command design. If true sharding is required beyond that, note that the platform defers it, and propose the smallest addition consistent with the plan. Don't invent a different architecture.
- `schedules: [[branch:, cron:]]` (nightly).
- `integrationBranches`: queued concurrency (`disableConcurrentBuilds`). Ordinary branch and PR jobs keep `abortPrevious`.
- **The PR integration interlock:** a PR needs a completed, passing result at the current target HEAD.
- **Each execution publishes its own evidence** under v1.1's `ci-results.json`, the identity block and the original-failure reporting.

**Constraints** (the same as ci-cd-1):
- **The shared library loads implicitly from `main`** (`allowVersionOverride: false`), so library branches can't be exercised on Jenkins before merge. Every change must be:
  - opt-in per consumer, with no behaviour change for other repos (`sub-agent-router`, ci-cd itself) unless they set a new key;
  - verified offline as far as possible, using the repo's existing Groovy/JenkinsPipelineUnit tests and mocks.
- **The PR must say exactly** what was and wasn't verified, and give the first post-merge verification step: a gen2 consumer change on a branch.
- **Size:** about 500 hand-written lines per PR. If v1.2 is bigger, split it into stacked PRs in the plan's order: modes and per-mode commands first.
- **No GitHub Actions** (operator ruling).
- **No provider calls.**
- **Reading:** never search /home/trevor or /home/trevor/work outside this clone, the gen2 repo and `~/work/research-loops-public/private/evidence/`.
- **Commits** end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
- **Evidence:** `~/work/research-loops-public/private/evidence/ci-cd-2/`, with a COMPLETION.md covering:
  - the PR URL(s);
  - offline verification;
  - the backward-compatibility argument;
  - the gen2 consumer config that the operator's merge would enable.
