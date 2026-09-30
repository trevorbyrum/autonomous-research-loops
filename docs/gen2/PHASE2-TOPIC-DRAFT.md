# Phase 2 live-run topic — draft intake brief

**Status: DRAFT.** This is preparation for task 2f, not an actual gen-2 intake. Gen-2's real S1 intake conversation runs on real executors, which don't exist until task 2e lands. This document is the input for that conversation when it becomes available; the operator confirms the real Intake Brief v1 through the real router operation (`open_brief` / `apply_operator_decision`) at that time, per flow doc S1. Nothing here binds the actual run.

Shaped per flow doc S1's required Intake Brief v1 fields: objective in the operator's words, the decision/build it feeds, what evidence would change it, constraints, operator hypotheses (as testables), surfaced assumptions.

## Objective (operator's words)

Survey the frameworks and methodologies for translating a body of research findings into software/product/system design decisions — including how to run and evaluate parallel design paths — and produce a dossier of what's actually supported by evidence versus commonly asserted.

## Decision this feeds

Two, stated honestly as different scopes:
1. **Immediate, narrow:** how gen-2's own S2→S3 step (scoping → contract/design) should incorporate research findings into design decisions, informing later Phase 3 work (e.g. how the engine picks between competing design options for its own decision-layer/provider choices).
2. **Broader:** general operator practice for research-informed product/system design, beyond gen-2 itself. This is a pure-survey/dossier topic — it does not commit to producing an applicable playbook. If a playbook later proves useful, that is a separate, explicitly scoped follow-on obligation, not part of this topic's done-when.

## What evidence would change the operator's mind

- Evidence that a named framework (design science research, C-K theory, evidence-based software engineering, etc.) is validated beyond its originating case studies, versus evidence it's asserted but not empirically supported.
- Evidence on when parallel design exploration measurably outperforms early commitment (and by how much, under what conditions), versus contexts where it's overhead.
- Evidence on how practitioners actually resolve contradictory research inputs when designing (not just what methodologists recommend).
- Evidence on failure modes: cases where research-driven design went wrong (overfit to one study, stale evidence, authority laundering) and what would have caught it earlier.

## Constraints

- Scope: product/system design broadly, not software-design-only (operator's call, widened from the orchestrator's narrower software-only suggestion). Expect overlap with the existing gen-1 topics "Agentic Product Discourse, Requirements, and Validation" and "Opportunity Recognition" — cross-cite rather than duplicate; the S2 scoping pass should flag and resolve the boundary explicitly, not silently re-cover the same ground.
- Deliverable: survey/dossier only. No playbook, no applicability claims to gen-2 specifically, beyond noting where a finding is directly relevant.
- Sources: no new research lanes required — CS/SE-relevant academic sources (arXiv/alphaXiv, Semantic Scholar, Crossref) already cover this territory through the existing gateway.
- This is the Phase 2f live-run topic: one topic, through the real workflow, to prove the engine — not a race to depth. Facet count and obligation count should stay small enough that the run can actually complete S1–S8 once.

## Operator hypotheses (as testables)

- H1: most named "research-to-design" frameworks (design science research, C-K theory, etc.) have more citations asserting their value than studies empirically validating design outcomes under them.
- H2: parallel design exploration's benefit is contingent (task uncertainty, cost of a wrong early commit), not universal — the evidence should show boundary conditions, not a blanket "parallel wins."
- H3: methods for handling *contradictory* research inputs during design are much less developed in the literature than methods for handling *convergent* inputs.

## Surfaced assumptions

- That "software design" and "product design" draw on a shared-enough literature to treat as one topic rather than two — the operator explicitly chose to widen scope to test this; if S2 scoping finds the literatures don't actually overlap well, that's itself a finding, not a reason to silently narrow.
- That this topic doesn't need real provider qualification or automated decision authority to run — it's exercised under Phase 2's disabled/unqualified decision layer, same as every other Phase 2 work.

## Why this topic, mechanically (not part of the brief; orchestrator's note for 2f sequencing)

Dense literature in gateway-covered lanes, quotable/verifiable claims (exercises the verification tier), and a facet map that decomposes into genuinely disagreeing threads (exercises checkpoints, contradiction handling, and the counterevidence challenge pass for real, not trivially). Also self-referential in a useful way: gen-2 itself is a research-to-design artifact, so this topic's dossier is something the operator can judge firsthand against known ground truth.
