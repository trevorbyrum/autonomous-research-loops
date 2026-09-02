Run exactly one bounded DISCOVERY pass for the DRAFT research topic in ${TOPIC_DIR}. This is intake work, before any contract is approved: your job is to map the topic space and pressure-test the draft scope — NOT to research the topic's questions and NOT to edit the draft contract itself.

Read first: ${TOPIC_DIR}/QA-RECORD.md (the operator's intent, verbatim, and the QA mode), ${TOPIC_DIR}/DRAFT-AUTHORITY.md, ${TOPIC_DIR}/DRAFT-TOPIC.md.

Binding rules:
- Operator-fixed assumptions (the "Operator-fixed" list in DRAFT-AUTHORITY.md's Assumptions section, and in scoped mode the stated frame itself) are FIXED. Never question them, never propose alternatives to them, never let discovery drift into re-litigating them.
- You may not edit DRAFT-TOPIC.md, DRAFT-AUTHORITY.md, or DRAFT-SEMANTIC-STATE.json. Your outputs are SCOPE-PROPOSAL.md and appended sections of QA-RECORD.md only.
- Discovery legwork (searches, survey fetches) should go to the delegate when one is named.${AGENT_NOTE}

Do, in order:
1. TRACEABILITY: compare DRAFT-TOPIC.md's obligations against the operator's intent in QA-RECORD.md, both directions. Flag every intent element no obligation covers (narrowing) and every obligation that doesn't trace to intent (creep). The formatting of the draft must never be allowed to scope the research below what the operator actually asked for.
2. MAP THE SPACE: survey how this topic's territory is actually organized in the literature and practice — adjacent framings, standard subdivisions, system-level angles (processes, gates, pipelines, orchestration) as well as component-level ones, and areas the operator may not have known to ask about. Breadth over depth: this is a map, not the research itself.
3. SURFACE ASSUMPTIONS: list every assumption the draft silently encodes (about who/what/how many/at what layer) that is NOT operator-fixed, each phrased as a one-line question the operator can answer in a sentence.
4. WRITE ${TOPIC_DIR}/SCOPE-PROPOSAL.md with: "## Traceability findings", "## Topic-space map", "## Proposed obligations" (a concrete candidate set, each one sentence, marked keep/add/reword/drop relative to the draft), "## Proposed exclusions" (with one-line rationale each), and "## Open questions".
5. APPEND to ${TOPIC_DIR}/QA-RECORD.md: a "## Restated intent" body (your own words, one short paragraph), a "## Traceability review" body (summary of step 1), and your questions under "## Questions for the operator" (numbered).

Finish with compact JSON: {"traceability_flags": N, "proposed_obligations": N, "questions": N}.
