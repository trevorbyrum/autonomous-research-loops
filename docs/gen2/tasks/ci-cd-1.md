# Task ci-cd-1: the first platform change requests for gen2 (CI design §6 and §7 steps 2–3)

**Repo:** `trevorbyrum/ci-cd`, the CI trust root.
- Work in `/home/trevor/work/ci-cd-gen2`, a dedicated clone. **Never** touch `~/work/ci-cd`: another session owns it.
- Use one branch per PR, named `sol/gen2-<topic>`, and **open PRs only**. Trevor merges.
- Never push to `main`, never enable auto-merge, and never change repo settings, Jenkins, or the VMs.

**Sources:**
- `autonomous-research-loops` `docs/gen2/CI-DESIGN.md`: §3.1, §3.6, §3.8, §6 and §7, read at gen2 HEAD from `/home/trevor/work/autonomous-research-loops`.
- In ci-cd: `ARCHITECTURE.md`, `docs/agent-ci-guide.md`, `lib/vars/standardPipeline.groovy`, `infra/cim/casc/jenkins.yaml` and `images/py312-noble/Dockerfile`.

## Constraints you must design around
- The shared library loads implicitly from `main` with `allowVersionOverride: false`, so **library branches cannot be exercised on Jenkins before merge**. Every library change must be:
  - **backward compatible and opt-in per consumer.** Other repos, such as `sub-agent-router` and ci-cd itself, must see no behaviour change unless they set the new config key.
  - **verified as far as possible offline.** Use a Groovy parse/compile check, JenkinsPipelineUnit if it is cheap to add, or a documented manual dry-run plan. The PR must say exactly what was and wasn't verified, and give the first post-merge verification step.
- Images are built **locally on the cir worker**; there is no registry. Image PRs change the Dockerfile and docs only. Build the image locally to prove it builds and to record versions. Don't deploy it anywhere: the cir rebuild is Trevor's step, and its runbook is part of the PR.
- Under Docker `--network none` there is **no IPv6 loopback**. Note this wherever it affects tests.
- No GitHub Actions anywhere (operator ruling).

## The change requests (separate PRs, in this order)
1. **Image `ci-py312-noble:2`.**
   - Add PostgreSQL 16 server binaries (the gen2 gateway suite runs a throwaway cluster), libpq and openssl.
   - Pin apt package versions to the noble versions, and **pin the base image by digest**.
   - Keep the reference Python 3.12.3 and SQLite 3.45.1. Assert both in a build-time check, so a drifting base image fails the build.
   - Record the resulting image ID and digest procedure in the docs. The gen2 consumer repo pins its psycopg in its own lock; that's not your change.
2. **Identity and clean workspace (prerequisites).** In opt-in config:
   - start from a clean workspace (ws-cleanup before checkout);
   - record in `ci-results.json` the library commit SHA, the image ID/digest actually used, the checked-out commit **and** whether it is a PR merge commit or a head commit, plus the PR head SHA.
3. **C4: a sealed execution container.** In opt-in config:
   - run the lint/build/unit stages with `--network none`;
   - keep dependency provisioning in a separate step that does have network access (e.g. `build` with network on, `unit` sealed), or whatever split you can justify;
   - add an audit step that records the effective mounts, user, capabilities and network mode of the execution container in the evidence.
   - Document what `.inside()` mounts by default (workspace, the docker socket?) and whether anything sensitive is reachable.
4. **C5: durable evidence.** In opt-in config:
   - archive a consumer-declared evidence set (e.g. `cfg.evidence: 'build/ci-evidence/**'`, including a versioned `gen2-evidence.json` if present), with fingerprints;
   - write a controller-side manifest listing the final result, the per-stage status and incomplete/aborted states;
   - make it publish **even when the timeout or abort fires**: it has to happen outside the `timeout` block, or survive it. Show how.
   - Note retention.

Where a request is too large or the platform makes it unsafe, split it further or write it up as a design note PR instead. Do **not** implement the integration interlock or nightly mode; they come later.

## Rules
- Make no changes outside the ci-cd clone, and touch nothing on the tower. You may run read-only Jenkins API queries with the `jenkins-agent-ro` credential.
- Don't search `/home/trevor/work` recursively.
- Commits end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`. Each PR body states its scope, the backward-compatibility argument, the verification done and not done, the post-merge steps for Trevor, and ends with "Build-out: leave for Trevor to merge."

## Completion report
List the PR URLs, and for each PR give one line on what was verified and what remains Trevor's step. Include a literally true Remaining section.
