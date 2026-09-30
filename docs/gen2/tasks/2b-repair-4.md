# Task 2b-repair-4 — replace the two 2b MITIGATIONS with root-cause fixes

Read first, in full: `~/work/research-loops-public/private/reviews/gen2-2b-repair-3-astra-review-20260930.md` (findings F1 and F2, the root-cause classification table, and the Gate C REJECT), with evidence under `/tmp/gen2-2b-repair-3-astra-review-20260930/` (`supplement.py`, `supplement.json`, `probes.json`). Then read the charter section **"Root-cause fixes, not patches"** in `docs/gen2/BUILD-CHARTER.md`. It applies to this task directly.

**Operator ruling (2026-09-30): both mitigations get a proper fix; neither is accepted as debt.** Everything else in 2b is classified ROOT-CAUSE and accepted. Don't touch it except where F1/F2 require. The cross-lifetime revision ordering (gateway restart, multiple gateway processes) is assigned to Phase 3; don't solve it here, but don't make it harder.

## F1 — the late-snapshot store rule must enforce its meaning, not just its shape
2b-repair-3 relaxed 0a's A9 insert rule so a delayed snapshot can be stored behind the current fact. The trigger (`gen2/store/schema/02-invocations-and-records.sql`, ~line 873) checks graph shape only. Astra's direct-SQL probes show it accepts a fact behind the current one from an earlier or later episode, with a different state at the same onset, with an equal or higher revision (leaving the lower one current), with no revision, and for non-gateway facts. The router blocks these on its normal path, but the database contract must hold on its own.

**Required:** the database admits a non-current insertion only when it is exactly a late snapshot: a gateway fact, the same capability, the same episode (onset) and state as the current fact it sits behind, a valid revision, and a revision strictly lower than that current fact's. Keep every existing graph and transaction protection (Astra found those sound). Add direct-SQL negatives for each case in Astra's table beside a permitted lower-revision control, including continued supersession after a late insertion. This replaces the REJECTed test `a_delayed_snapshot_is_kept_directly_behind_the_current_fact` as acceptance evidence.

**Third-round rule:** this is the fourth correction in the gateway-fact family (A6 → R2 → R2 residual → F1). If enforcing the exact relation in the existing supersession chain gets awkward, stop and redesign rather than add conditions. For example, keep one current row per capability plus an append-only snapshot history, so late snapshots never enter the supersession graph at all. Choose whichever design removes the cause, and say why in your report.

## F2 — convert old rows once; delete the read-time reinterpretation
`Cache.get_record` (`gateway/research_gateway/core/cache.py`, ~line 83) reconstructs restriction inputs for rows marked `restriction_inputs=false` every time they are read. It never converts them, and nothing ever removes that branch. Astra confirmed all old rows still read as unconverted after repeated reads.

**Required:**
- A bounded, idempotent migration that rewrites old rows into the current representation, preserving each member's own restrictions without spreading them to another member. It must have a verifiable completion condition: zero unconverted rows.
- Then **remove the legacy read path**. There must be no window in which new code serves an unconverted row: the gateway must refuse to serve, or must migrate first, while any unconverted row exists. Test that refusal or ordering.
- Don't present an inferred cause as an observed fact. Where the old data only shows *that* a member was restricted, not *why*, record the restriction as inferred from legacy data, not as `third_party_restricted=True` stated by the source. Current writers keep producing the full representation.
- Tests: the actual pre-repair writer (`e7856a9`, as the existing old-writer tests do), then migration, then a fresh-process read with the legacy path gone. Cover prohibition and third-party members, lead and non-lead, the unrestricted controls, re-running the migration (idempotent), and the refuse-or-migrate-first check.
- **Never run the migration against any real database.** Disposable ones only. Running it on real data is a release step the operator approves separately. Never touch `~/work/staging/research-gateway-wt`, its database, or `research-gateway.service`.

## Completion report (charter rule)
For each of F1 and F2, state the **root cause in one sentence and why your change removes it rather than the symptom**. List every limitation that remains, where it lives, and which phase owns it. "Remaining: NONE" must be literally true. The last report omitted the single-gateway-lifetime limit.

## Budget and constraints
Engine 9,708, gateway 9,173. Keep it narrow; report net lines for both separately. Branch gen2 only; never main, never gen-1. Small commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with final unpiped `make gen2-check` and `make gen2-gateway`. Don't end your turn waiting on a background run.
