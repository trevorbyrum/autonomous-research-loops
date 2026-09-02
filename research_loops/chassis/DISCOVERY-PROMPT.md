Run exactly one bounded DISCOVERY pass for the DRAFT research topic in ${TOPIC_DIR}. QA mode: ${QA_MODE}. This is intake work, before any contract is approved: your job is to check the draft contract against the intake criteria, and (in broad mode only) map the topic space and pressure-test the draft scope — NOT to research the topic's questions and NOT to edit the draft contract itself.

Read first: ${TOPIC_DIR}/QA-RECORD.md (the operator's intent, verbatim, and the QA mode), ${TOPIC_DIR}/DRAFT-AUTHORITY.md, ${TOPIC_DIR}/DRAFT-TOPIC.md.

Binding rules:
- Operator-fixed assumptions (the "Operator-fixed" list in DRAFT-AUTHORITY.md's Assumptions section, and in focused mode the stated frame itself) are FIXED. Never question them, never propose alternatives to them, never let discovery drift into re-litigating them.
- You may not edit DRAFT-TOPIC.md, DRAFT-AUTHORITY.md, or DRAFT-SEMANTIC-STATE.json. Your outputs are SCOPE-PROPOSAL.md and appended sections of QA-RECORD.md only.
- Discovery legwork (searches, survey fetches) should go to the delegate when one is named.${AGENT_NOTE}

CONTRACT CRITERIA (check in every mode — this engine produces research, nothing else):
1. Every obligation is a checkable claim or question that evidence can drive to supported/contradicted/unresolved/deferred. Headers, narrative fragments, framing statements, and constraints are NOT obligations — flag each one, with where its content should live instead.
2. Deliverables are research artifacts only: synthesis, reports, catalogs of evidence. A prescriptive or deterministic artifact — playbook, runbook, design, plan, template, implementation, tool — is a category error; flag it. (Approval will mechanically refuse such deliverables.)
3. Binding constraints and fixed premises live in AUTHORITY.md's Assumptions → Operator-fixed list, not as obligations.
4. Exclusions are explicit and top-level — never buried mid-sentence where a research agent could miss them.
5. Evidence rules the operator has ruled on (source precedence, recency windows) are recorded in AUTHORITY.md; flag their absence as an open question, never invent them.
6. Scope traces to the operator's stated intent (in focused mode: only check the contract renders the fixed frame faithfully — never whether the frame is right).

Do, in order:
1. CRITERIA CHECK: evaluate DRAFT-TOPIC.md and DRAFT-AUTHORITY.md against every criterion above; record findings.
2. If QA mode is `focused` (or its legacy name `scoped`), STOP HERE and write outputs (step 5–6) with only the criteria findings and your questions: the operator's frame is fixed; no topic-space mapping, no scope proposals beyond what the criteria require.
3. TRACEABILITY (broad mode): compare DRAFT-TOPIC.md's obligations against the operator's intent in QA-RECORD.md, both directions. Flag every intent element no obligation covers (narrowing) and every obligation that doesn't trace to intent (creep). The formatting of the draft must never be allowed to scope the research below what the operator actually asked for.
4. MAP THE SPACE (broad mode): survey how this topic's territory is actually organized in the literature and practice — adjacent framings, standard subdivisions, system-level angles (processes, gates, pipelines, orchestration) as well as component-level ones, and areas the operator may not have known to ask about. Breadth over depth: this is a map, not the research itself. Then SURFACE ASSUMPTIONS: list every assumption the draft silently encodes (about who/what/how many/at what layer) that is NOT operator-fixed, each phrased as a one-line question the operator can answer in a sentence.
5. WRITE ${TOPIC_DIR}/SCOPE-PROPOSAL.md with: "## Contract criteria findings" (every criterion, pass or flagged, with specifics), then in broad mode "## Traceability findings", "## Topic-space map", "## Proposed obligations" (a concrete candidate set, each one sentence, marked keep/add/reword/drop relative to the draft), "## Proposed exclusions" (with one-line rationale each), and "## Open questions".
6. APPEND to ${TOPIC_DIR}/QA-RECORD.md: a "## Restated intent" body (your own words, one short paragraph), a "## Traceability review" body (criteria summary; in broad mode also step 3's summary), and your questions under "## Questions for the operator" (numbered).

Finish with compact JSON: {"criteria_flags": N, "traceability_flags": N, "proposed_obligations": N, "questions": N}.
