Run exactly one bounded CONTRACT REVIEW pass for the APPROVED research topic in ${TOPIC_DIR}. This is an operator-ordered quality review of a binding contract — NOT research, NOT a scope renegotiation, and NOT an edit pass. You may not modify TOPIC.md, AUTHORITY.md, SEMANTIC-STATE.json, or any ledger. Your outputs are SCOPE-PROPOSAL.md and appended sections of QA-RECORD.md only; any change you propose will be applied by the operator via the sanctioned scope-change path (edit + rehash + relock), or not at all.

Read first: ${TOPIC_DIR}/TOPIC.md (the binding contract), ${TOPIC_DIR}/AUTHORITY.md (ground truth and assumptions), ${TOPIC_DIR}/QA-RECORD.md if present, and skim SEMANTIC-STATE.json's obligation ids/dispositions for context (via `python3 ${CHASSIS}/semantic-state.py select ${TOPIC_DIR}` — do not read or rewrite the file directly).

Binding rules:
- Operator-fixed assumptions in AUTHORITY.md are FIXED; never question them.
- Anything already dispositioned stays dispositioned — reviewing the contract is not re-litigating completed research.
- Review legwork goes to the delegate when one is named.${AGENT_NOTE}

CONTRACT CRITERIA (this engine produces research, nothing else):
1. Every obligation is a checkable claim or question that evidence can drive to supported/contradicted/unresolved/deferred. Headers, narrative fragments, framing statements, and constraints are NOT obligations — flag each one, with where its content should live instead.
2. Deliverables are research artifacts only: synthesis, reports, catalogs of evidence. A prescriptive or deterministic artifact — playbook, runbook, design, plan, template, implementation, tool — is a category error; flag it.
3. Binding constraints and fixed premises live in AUTHORITY.md's Assumptions → Operator-fixed list, not as obligations.
4. Exclusions are explicit and top-level — never buried mid-sentence where a research agent could miss them.
5. Evidence rules the operator has ruled on (source precedence, recency windows) are recorded in AUTHORITY.md; flag their absence as an open question, never invent them.
6. Obligations trace to the operator intent recorded in AUTHORITY.md/QA-RECORD.md — no silent narrowing by formatting, no invented scope.
7. Obligation bundling: an obligation packing several independent sub-areas into one disposition is flagged (a partial finding on one sub-area could force a premature disposition on the whole).

Do, in order:
1. Evaluate TOPIC.md and AUTHORITY.md against every criterion; record pass/flag per criterion with specifics (obligation ids, quoted fragments).
2. WRITE ${TOPIC_DIR}/SCOPE-PROPOSAL.md with: "## Contract criteria findings" (every criterion, pass or flagged), "## Proposed remediations" (each one sentence, marked reword/move/split/drop with the affected id and a one-line rationale; propose nothing the criteria don't require), and "## Open questions".
3. APPEND to ${TOPIC_DIR}/QA-RECORD.md: a "## Contract review" body (dated summary of findings) and your questions under "## Questions for the operator" (numbered; each answerable in a sentence).

Finish with compact JSON: {"criteria_flags": N, "proposed_remediations": N, "questions": N}.
