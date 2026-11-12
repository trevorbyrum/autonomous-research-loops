# First topic: research findings to design decisions

These are **proposed operator inputs**, generated from T18's `offline_world`/`router_fixtures` helpers and [the topic draft](PHASE2-TOPIC-DRAFT.md). They are not an approved scientific contract or research findings. Review the brief, all three facets, importance ratings, eligibility, method design and stopping profile after the actual scope report. Adapt both drafts consistently before submitting them. The deliverable is a survey/dossier, with no playbook or automatic applicability claim to gen-2.

The draft's broad lane list is historical: this first walk uses Semantic Scholar alone. Its old qualification assumption does not authorize live dispatch. The decision layer stays disabled; model-route qualification, retained configuration, credentials, approved gateway configuration/egress, DEBT-053 remediation where required, and an operator present remain prerequisites. Follow [OPERATIONS](../../deploy/gen2/live/OPERATIONS.md); these instructions perform no host setup.

`examples/gen2/first-topic/sentinel.json` is **NOT FOR STAGING**: the stopping-rule ruling and named works are pending. The known-item profile is a conditional template, not the ruling. Stop before contract drafting until the operator chooses the rule and an authorized procedure stages its operand. There is currently no `stage_operand` CLI command; do not invent one or write the store. If another rule is selected, revise both contracts and revalidate instead of using these known-item instructions.

**Operator protocol choices pending** (not ruled; the files only propose them):
- The stopping-rule ruling and the named sentinel works (above).
- The `confidence_scheme` labels both contracts inherit from the fixture (low = one source or disagreement; high = two or more independent agreeing sources): Astra's concern is that agreement or count alone does not measure study quality, relevance or strength of validation, so agreement among unvalidated methodological assertions could be labelled high confidence. Revise or accept it explicitly before contract approval; the rubric is unchanged here.

Preparation timestamps describe file preparation, not model outputs or operator approvals. Decisions have no `operator_id`: identity comes from the listener token. Null decision subjects/times, the brief owner/deadline and sentinel must be filled locally. Read expanded JSON with `python -m json.tool FILE` before approving content. Regenerate proposed files, without activation, with `python -m gen2.tests.first_topic_files DESTINATION` if prompt bytes change.

## Prepare local copies and the brief

Use the existing authenticated `GEN2_OPERATOR_URL`/`GEN2_OPERATOR_TOKEN` environment. Choose the brief owner and an actual review deadline (UTC timestamp). All files written below stay in an operator-chosen temporary directory, outside the repository.

```sh
set -e
export GEN2_FIRST_TOPIC_DIR="$(mktemp -d)"
cp examples/gen2/first-topic/*.json "$GEN2_FIRST_TOPIC_DIR/"
: "${GEN2_OPERATOR_NAME:?Set the brief owner principal name}"
: "${GEN2_BRIEF_REVIEW_DEADLINE:?Set the actual brief review deadline}"
python -m gen2.app.cli status > "$GEN2_FIRST_TOPIC_DIR/station-status.json"
python - <<'PY'
import json, os
from pathlib import Path
from gen2.core import canonical
from gen2.core.instants import utc_now
p = Path(os.environ['GEN2_FIRST_TOPIC_DIR'])
def read(n): return json.loads((p / (n + '.json')).read_text())
def write(n, d): (p / (n + '.json')).write_text(json.dumps(d, indent=2) + '\n')
bundle = read('bundle')
bundle['version'] = read('station-status')['config_bundles']['active']['version'] + 1
write('bundle', bundle)
brief = read('brief')
brief.update(owner_operator_id=os.environ['GEN2_OPERATOR_NAME'], review_deadline=os.environ['GEN2_BRIEF_REVIEW_DEADLINE'])
brief['document']['created_at'] = utc_now()
brief['document']['content_hash'] = canonical.content_hash(brief['document'])
write('brief', brief)
PY
python -m gen2.app.cli call activate_config_bundle "$GEN2_FIRST_TOPIC_DIR/bundle.json"
python -m gen2.app.cli call create_topic "$GEN2_FIRST_TOPIC_DIR/topic.json"
python -m gen2.app.cli call open_brief "$GEN2_FIRST_TOPIC_DIR/brief.json"
```

Stop on any refusal. Keep the exact request bytes for replay if a reply is lost; inspect status before retrying, and replay the saved decision file rather than regenerating its timestamp. Bundle activation is station-wide; existing jobs retain their original pins.

## Build each decision only after reviewing its subject

Save this helper outside the repository. It prepares one explicit decision, sends nothing and never reads a store. Scope/completion subjects come from the exact saved status the operator reviewed. A later change causes refusal; reread and review rather than silently substituting a new subject.

```sh
cat > "$GEN2_FIRST_TOPIC_DIR/decision.py" <<'PY'
import json, os, sys
from pathlib import Path
from gen2.core.instants import utc_now
p = Path(os.environ['GEN2_FIRST_TOPIC_DIR'])
def read(n): return json.loads((p / (n + '.json')).read_text())
kind = sys.argv[1]
d = read('decisions')[kind]
topic = read('topic')['topic_id']
ref, revision, payload = topic, 'revision', None
if kind == 'brief_confirmation':
    doc = read('brief')['document']; ref = doc['brief_id']; revision = 'version'
elif kind in ('scope_approval', 'completion_approval'):
    shown = json.loads(Path(sys.argv[2]).read_text())['topics'][0]
    assert shown['topic_id'] == topic
    if kind == 'scope_approval':
        doc = shown['scoping_report']; ref = doc['report_id']; revision = 'version'
    else:
        assert shown['review']['approvable']; doc = shown['review']['dossier']
else:
    doc = read('contract-r1' if kind == 'rating_approval' else 'contract-r2')['document']
    if kind == 'rating_approval': payload = read('ratings')
d.update(subject={'kind': d['subject']['kind'], 'ref': ref, 'revision': doc[revision], 'hash': doc['content_hash']}, decided_at=utc_now(), payload=payload)
print(json.dumps(d, indent=2))
PY
python "$GEN2_FIRST_TOPIC_DIR/decision.py" brief_confirmation > "$GEN2_FIRST_TOPIC_DIR/brief-confirmation.json"
python -m gen2.app.cli call apply_operator_decision "$GEN2_FIRST_TOPIC_DIR/brief-confirmation.json"
```

## Walk to scope and review the report

**Walk permission:** `live=true` (the CLI's `--live`) selects the network-capable discovery entry for newly issued discovery jobs. This choice persists per job: later non-live ticks neither revoke it nor stop a deferred start. This is distinct from the model per-call live gate. Use explicit cancellation to stop existing work: read its invocation id from status and call `request_cancel` with `invocation_id` and `reason`, then observe the confirmed end. Omitting `--live` is not cancellation. Submit the reviewed cancellation body with `python -m gen2.app.cli call request_cancel FILE`; it carries no caller authority fields.

```sh
export GEN2_FIRST_TOPIC_ID="$(python -c 'import json,os; print(json.load(open(os.environ["GEN2_FIRST_TOPIC_DIR"]+"/topic.json"))["topic_id"])')"
python -m gen2.app.run_topic "$GEN2_FIRST_TOPIC_ID" --live
python -m gen2.app.cli status --topic "$GEN2_FIRST_TOPIC_ID" > "$GEN2_FIRST_TOPIC_DIR/scope-status.json"
python -m json.tool "$GEN2_FIRST_TOPIC_DIR/scope-status.json"
# Only after reading scoping_report.document and approving that exact subject:
python "$GEN2_FIRST_TOPIC_DIR/decision.py" scope_approval "$GEN2_FIRST_TOPIC_DIR/scope-status.json" > "$GEN2_FIRST_TOPIC_DIR/scope-approval.json"
python -m gen2.app.cli call apply_operator_decision "$GEN2_FIRST_TOPIC_DIR/scope-approval.json"
```

Each `run_topic` invokes repeated single listener `walk` ticks and stops at the next operator wait or failure. A failed fixture judgment is a failed step, not scope approval. Do not automatically apply canned follow-up approvals to actual model output. Holds, unknown ends and rejection blockers require their existing operator procedures.

## Stop for the ruling, then draft, rate, redraft and approve

After the stopping-rule ruling, replace the placeholder with the operator-selected nonempty JSON array of canonical work ids. Use the existing `gen2.router.boundary.work_id(identity_scheme, identity_value)` with the same normalized identity used at registration (for example scheme `doi`); a bare DOI is not a canonical work id. Do not seed the sentinel identities into prompts. Obtain a topic-bound artifact reference through the authorized staging procedure for those **exact bytes**, then set `GEN2_SENTINEL_REFERENCE` to that reference's JSON file. No staging procedure is supplied by this runbook while change 9 is unassigned.

Review/edit both contracts against the real scope and confirm `ratings.json`; the following binds the staged reference, selected ratings and actual brief confirmation, and recomputes both content hashes. No missing gate or unimplemented stopping rule is replaced by an assumed success. Known-item retrieval tests only whether named works were retrieved, not recall over undiscovered literature or substantive sufficiency.

```sh
: "${GEN2_SENTINEL_REFERENCE:?An authorized staged reference is required}"
python - <<'PY'
import json, os, re
from pathlib import Path
from gen2.core import canonical
from gen2.core.instants import utc_now
p = Path(os.environ['GEN2_FIRST_TOPIC_DIR'])
raw = (p / 'sentinel.json').read_bytes(); ids = canonical.parse_json_strict(raw)
assert isinstance(ids, list) and ids and all(isinstance(i, str) and re.fullmatch(r'wrk_[0-9a-f]{64}', i) for i in ids) and len(set(ids)) == len(ids)
ref = json.loads(Path(os.environ['GEN2_SENTINEL_REFERENCE']).read_text())
assert ref == dict(content_hash=canonical.bytes_digest(raw), size_bytes=len(raw), media_type='application/json')
ratings = json.loads((p / 'ratings.json').read_text())
brief = json.loads((p / 'brief.json').read_text())['document']
decisions = json.loads((p / 'decisions.json').read_text()); now = utc_now()
for name in ('contract-r1', 'contract-r2'):
    wrapper = json.loads((p / (name + '.json')).read_text()); doc = wrapper['document']
    doc['created_at'] = now
    doc['decision_record']['objective']['confirmed_brief'] = dict(brief_id=brief['brief_id'], version=brief['version'], confirmed_by=decisions['brief_confirmation']['decision_id'])
    doc['stopping_profiles'][0]['rules'][0]['params']['sentinel_set'] = ref
    for group, entries in (('facets', doc['facet_map']['facets']), ('obligations', doc['obligations'])):
        for entry in entries:
            selected = ratings[group][entry['facet_id' if group == 'facets' else 'obligation_id']]
            entry['importance']['operator_rating'] = None if name == 'contract-r1' else {**{k: v for k, v in selected.items() if v is not None}, 'operator_decision_id': decisions['rating_approval']['decision_id']}
    doc['content_hash'] = canonical.content_hash(doc)
    (p / (name + '.json')).write_text(json.dumps(wrapper, indent=2) + '\n')
PY
python -m gen2.app.cli call draft_contract "$GEN2_FIRST_TOPIC_DIR/contract-r1.json"
python "$GEN2_FIRST_TOPIC_DIR/decision.py" rating_approval > "$GEN2_FIRST_TOPIC_DIR/rating-approval.json"
python -m gen2.app.cli call apply_operator_decision "$GEN2_FIRST_TOPIC_DIR/rating-approval.json"
python -m gen2.app.cli call draft_contract "$GEN2_FIRST_TOPIC_DIR/contract-r2.json"
python "$GEN2_FIRST_TOPIC_DIR/decision.py" contract_approval > "$GEN2_FIRST_TOPIC_DIR/contract-approval.json"
python -m gen2.app.cli call apply_operator_decision "$GEN2_FIRST_TOPIC_DIR/contract-approval.json"
```

## Research, fresh review, exact-dossier completion

```sh
python -m gen2.app.run_topic "$GEN2_FIRST_TOPIC_ID" --live
# At open_review, inspect status, then explicitly open the fresh review episode:
python -m gen2.app.cli call open_review <<EOF
{"topic_id":"$GEN2_FIRST_TOPIC_ID","episode_id":"rev_ft_review01","kind":"fixed_cadence"}
EOF
python -m gen2.app.run_topic "$GEN2_FIRST_TOPIC_ID" --live
python -m gen2.app.cli status --topic "$GEN2_FIRST_TOPIC_ID" > "$GEN2_FIRST_TOPIC_DIR/completion-status.json"
python -m json.tool "$GEN2_FIRST_TOPIC_DIR/completion-status.json"
# Only after reviewing the exact dossier, gates, fresh sufficiency review and its retained evidence:
python "$GEN2_FIRST_TOPIC_DIR/decision.py" completion_approval "$GEN2_FIRST_TOPIC_DIR/completion-status.json" > "$GEN2_FIRST_TOPIC_DIR/completion-approval.json"
python -m gen2.app.cli call apply_operator_decision "$GEN2_FIRST_TOPIC_DIR/completion-approval.json"
python -m gen2.app.cli status --topic "$GEN2_FIRST_TOPIC_ID"
```

Completion still requires challenge completion, coverage integrity, load-bearing verification tiers, a fresh scientific review and operator approval of that exact dossier revision/hash. Unknown evidence is not empty success; missing required access is not upgraded. Expect qualified conclusions only under the stated framing/coverage; `export_delivery` remains `not_attempted`, and `currency` remains `unknown`. Reuse of an already opened episode id is replay, not a new review; if another episode is needed, choose a fresh id and inspect its state.
