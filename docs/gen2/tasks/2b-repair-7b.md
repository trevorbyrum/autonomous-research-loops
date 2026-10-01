# Task 2b-repair-7b — finish 2b-repair-7 after the host reboot

The 2b-repair-7 coder (Opus) completed seven commits, `ef39cd6`..`cadd62e`: F3-R1 stable local paging, F3-R2 Hugging Face next-link, provider-grounded end rules in `gateway/docs/PROVIDER-PAGINATION.md`, and the Socrata malformed-member fix. A host reboot then ended its session before its final `make gen2-check` and completion report. The reboot also wiped `/tmp`, including its raw provider captures in `/tmp/gen2-2b-repair-7-evidence/`. Read `docs/gen2/tasks/2b-repair-7.md` (the brief this finishes), `~/work/research-loops-public/private/reviews/gen2-2b-repair-6-astra-review-20261001.md`, those seven commits, and the charter rules "Root-cause fixes, not patches", "Evidence is durable" and the no-personal-data rule.

## 1. Restore the provider evidence durably
Re-capture the primary documentation and provider-owned client source that `PROVIDER-PAGINATION.md` cites into `~/work/research-loops-public/private/evidence/2b-repair-7/`, with a manifest (URL or package+version, date fetched, SHA-256). Update any reference in `PROVIDER-PAGINATION.md` that pointed at `/tmp`. Public documentation pages and provider client packages only. No live calls to provider APIs, and no personal data in any request.

## 2. OpenCitations malformed-member defect, fixed at the chokepoint
The previous coder confirmed offline that OpenCitations' enrich path loses the whole answer when one row is a non-object, the same A4-class bug as the Socrata one fixed in `f64d20c`. That makes two adapters with the same defect, so per the charter's redesign rule don't patch a second adapter. Make "every provider member is decoded individually through the shared member decoder before anything iterates it" the property of one place, plus a check (a test or the boundary tooling) that fails if an adapter iterates raw provider members outside it. Audit every adapter, find, enrich and resolve paths alike, and report which ones you changed. Regressions and controls for OpenCitations and any other adapter you find.

## 3. Final checks and the completion report
Run final unpiped `make gen2-check` and `make gen2-gateway` and wait for both in your turn. Then write the completion report 2b-repair-7.md specifies, covering all of 2b-repair-7 including the seven earlier commits: each root cause in one sentence and why its change removes it.

The **Remaining** section must be literally true, with actual owners. Two items found by the previous coder are outside this brief; list them with what you observe and a proposed owner, and don't fix them:
- the OpenAIRE adapter calls an endpoint version OpenAIRE marks deprecated and slated for removal;
- Kaggle's current official client no longer uses the listing endpoint the adapter calls.

## Constraints
Branch gen2 only. Never run a migration against a real database, and never touch `~/work/staging/research-gateway-wt`, its database, or `research-gateway.service`. Small commits with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Report net lines for the engine and gateway separately.
