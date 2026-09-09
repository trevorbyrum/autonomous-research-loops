from __future__ import annotations

import copy
import json
from contextlib import contextmanager
import tempfile
import unittest
from pathlib import Path

from research_loops.checkpoints.runner import CheckpointResultError, CheckpointRunner, RegisteredCheckpointAdapter
from research_loops.checkpoints.service import (
    CheckpointError,
    accept_research_completion,
    apply_decision,
    finish_checkpoint,
    reserve_delegate_launch,
    record_delegate_result,
    start_checkpoint,
)
from research_loops.control_store import ControlScheduler, ControlStore, default_configuration
from research_loops.queue import QueueStore
from research_loops.runner import LoopRunner, UsageLedger
from research_loops.intake import IntakeService
from research_loops import topic_authoring
from research_loops.intake import operator_dispatch


class FakeControl:
    def __init__(self):
        self.state = {
            "revision": 0,
            "configuration": {
                "stations": [
                    {"id": 1, "primary_profile": "terra", "secondary_profile": "haiku", "interval_seconds": 0},
                    {"id": 2, "primary_profile": "sonnet", "secondary_profile": "luna", "interval_seconds": 0},
                ],
                "checkpoints": {"enabled": True, "every_research_iterations": 25, "on_deepening_entry": True, "agent_source": "station_1"},
            },
            "queue": {"items": []},
            "work": {"topics": {}, "runs": {}, "triggers": {}, "episodes": {}, "proposals": {}, "decisions": {}, "assignments": {}},
        }

    @contextmanager
    def transaction(self, **_kwargs):
        before = copy.deepcopy(self.state)
        yield self.state
        if before != self.state:
            self.state["revision"] += 1

    def snapshot(self):
        return copy.deepcopy(self.state)

    def resolve_checkpoint_pair(self, state):
        policy = state["configuration"]["checkpoints"]
        if policy.get("agent_source") == "explicit":
            return {"primary_profile": policy["primary_profile"], "secondary_profile": policy["secondary_profile"]}
        station = next(item for item in state["configuration"]["stations"] if item["id"] == 1)
        return {"primary_profile": station["primary_profile"], "secondary_profile": station["secondary_profile"]}


def checkpoint_result(episode, run_id, proposals=None, complete=True):
    return {
        "episode_id": episode["episode_id"], "run_id": run_id,
        "inventory_version": episode["inventory_version"], "trigger_ids": episode["trigger_ids"],
        "complete": complete, "findings": ["reviewed"], "limitations": [] if complete else ["packet missing"],
        "protocol_evidence_refs": ["logs/checkpoint.md"], "proposals": proposals or [],
    }


def proposal(pid="proposal-1"):
    return {"proposal_id": pid, "proposal_version": 1, "kind": "addition", "anchors": [{"locator": "SRC-1#passage", "observation": "observed", "inference": "inferred"}],
            "evidence_target": {"route": "corpus", "support": "support", "complication": "complication", "null": "null", "unresolved": "unresolved"}, "nearest_reference": {"reference": "none", "non_duplication": "documented absence"},
            "consequence": "changes prioritization", "counterargument": "already covered", "dependencies": [],
            "content": {"text": "An exact proposed obligation", "source_ref": "SRC-1"}}


def registered_profiles(configuration):
    ids = {station[field] for station in configuration["stations"] for field in ("primary_profile", "secondary_profile")}
    return {profile_id: {"adapter": "fake", "model": profile_id, "executable": "fake-adapter", "argv": []} for profile_id in ids}


def complete_counter(control, episode):
    reserve_delegate_launch(control, episode_id=episode["episode_id"], lease_id=episode["run_id"], invocation_id="counter-complete", role="counter")
    record_delegate_result(control, episode_id=episode["episode_id"], invocation_id="counter-complete", exit_code=0, output_reference=".checkpoint-reports/counter.json",
                           delegate_result={"schema_version": 1, "invocation_id": "counter-complete", "role": "counter", "status": "complete", "findings": [], "limitations": []})


class CheckpointLifecycleTests(unittest.TestCase):
    def test_real_control_store_dispatches_checkpoint_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            configuration = default_configuration()
            configuration["active_count"] = 1
            for station in configuration["stations"]:
                station["primary_profile"] = f"primary-{station['id']}"
                station["secondary_profile"] = f"secondary-{station['id']}"
            control = ControlStore.initialize(Path(tmp), configuration=configuration,
                agent_profiles=registered_profiles(configuration),
                queue={"revision": 0, "items": [{"id": "A", "status": "queued", "desired_state": "running"}]})
            accounted = accept_research_completion(control, topic_id="A", run_id="ordinary-1", station_id=1,
                                                    inventory_version="v1", accepted=True, deepening_entry=True)
            lease = ControlScheduler(control).claim(1)
            self.assertEqual((lease["topic_id"], lease["execution_kind"]), ("A", "checkpoint"))
            started = start_checkpoint(control, episode_id=accounted["episode_id"], station_id=1, run_id="checkpoint-1")
            self.assertEqual(started["resolved_agent_pair"]["primary"]["id"], "primary-1")
            self.assertEqual(started["resolved_agent_pair"]["secondary"]["id"], "secondary-1")

    def test_managed_runner_uses_separate_checkpoint_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configuration = default_configuration(); configuration["active_count"] = 1
            for station in configuration["stations"]:
                station["primary_profile"] = f"primary-{station['id']}"; station["secondary_profile"] = f"secondary-{station['id']}"
            control = ControlStore.initialize(root, configuration=configuration, agent_profiles=registered_profiles(configuration),
                queue={"revision": 0, "items": [{"id": "A", "cwd": str(root), "command": ["false"], "status": "queued", "desired_state": "running"}]})
            accept_research_completion(control, topic_id="A", run_id="ordinary-1", station_id=1,
                                        inventory_version="v1", accepted=True, deepening_entry=True)
            seen = []
            def adapter(context):
                seen.append(context)
                complete_counter(control, context)
                return checkpoint_result(context, context["run_id"])
            runner = LoopRunner(QueueStore(root), UsageLedger(root / "usage.jsonl"), worker="station-1", checkpoint_adapter=adapter)
            outcome = runner.run_once()
            self.assertEqual((outcome["execution_kind"], outcome["outcome"]), ("checkpoint", "complete_without_proposals"))
            self.assertEqual(len(seen), 1)
            self.assertEqual(control.snapshot()["work"]["topics"]["A"]["next_research_ordinal"], 2)

    def test_25_checkpoint_26_and_duplicate_completion(self):
        control = FakeControl()
        for ordinal in range(1, 25):
            accepted = accept_research_completion(control, topic_id="A", run_id=f"run-{ordinal}", station_id=3, inventory_version="v1", accepted=True)
            self.assertEqual(accepted["ordinal"], ordinal)
            self.assertIsNone(accepted["episode_id"])
        accepted = accept_research_completion(control, topic_id="A", run_id="run-25", station_id=3, inventory_version="v1", accepted=True)
        self.assertEqual((accepted["research_iterations_completed"], accepted["next_research_ordinal"]), (25, 26))
        episode = start_checkpoint(control, episode_id=accepted["episode_id"], station_id=3, run_id="checkpoint-run")
        self.assertEqual(episode["resolved_agent_pair"], {"primary_profile": "terra", "secondary_profile": "haiku"})
        complete_counter(control, episode)
        finish_checkpoint(control, checkpoint_result(episode, "checkpoint-run"))
        topic = control.snapshot()["work"]["topics"]["A"]
        self.assertEqual((topic["research_iterations_completed"], topic["next_research_ordinal"], topic["review_state"]), (25, 26, "eligible"))
        replay = accept_research_completion(control, topic_id="A", run_id="run-25", station_id=3, inventory_version="v1", accepted=True)
        self.assertEqual(replay["ordinal"], 25)
        self.assertEqual(len(control.snapshot()["work"]["episodes"]), 1)

    def test_deepening_and_cadence_coalesce_once(self):
        control = FakeControl()
        for ordinal in range(1, 25):
            accept_research_completion(control, topic_id="A", run_id=f"run-{ordinal}", station_id=1, inventory_version="v1", accepted=True)
        completed = accept_research_completion(control, topic_id="A", run_id="run-25", station_id=1, inventory_version="v1", accepted=True, deepening_entry=True)
        episode = control.snapshot()["work"]["episodes"][completed["episode_id"]]
        self.assertEqual(len(episode["trigger_ids"]), 2)
        episode = start_checkpoint(control, episode_id=episode["episode_id"], station_id=1, run_id="cp")
        complete_counter(control, episode)
        finish_checkpoint(control, checkpoint_result(episode, "cp"))
        self.assertTrue(all(t["handled"] for t in control.snapshot()["work"]["triggers"].values()))

    def test_incomplete_cannot_be_zero_proposal_success(self):
        control = FakeControl()
        result = accept_research_completion(control, topic_id="A", run_id="run", station_id=1, inventory_version="v1", accepted=True, deepening_entry=True)
        episode = start_checkpoint(control, episode_id=result["episode_id"], station_id=1, run_id="cp")
        response = finish_checkpoint(control, checkpoint_result(episode, "cp", complete=False))
        self.assertEqual(response["state"], "needs_attention")
        with self.assertRaises(CheckpointResultError):
            CheckpointRunner(lambda _ctx: {"episode_id": "x"}).run({"episode_id": "x", "run_id": "r"})

    def test_final_result_requires_recorded_complete_counter_evidence(self):
        control = FakeControl()
        accepted = accept_research_completion(control, topic_id="A", run_id="run", station_id=1, inventory_version="v1", accepted=True, deepening_entry=True)
        episode = start_checkpoint(control, episode_id=accepted["episode_id"], station_id=1, run_id="cp")
        reserve_delegate_launch(control, episode_id=episode["episode_id"], lease_id="cp", invocation_id="counter", role="counter")
        # An exit code and a path alone are not evidence from the broker's
        # strict delegate envelope.
        record_delegate_result(control, episode_id=episode["episode_id"], invocation_id="counter", exit_code=0,
                               output_reference=".checkpoint-reports/counter.json")
        final = finish_checkpoint(control, checkpoint_result(episode, "cp"))
        self.assertEqual(final["state"], "retry_wait")
        state = control.snapshot()
        self.assertEqual(state["work"]["topics"]["A"]["review_state"], "checkpoint_due")

    def test_prior_complete_reuse_allows_log_growth_but_not_material_or_operator_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, text in (("TOPIC.md", "topic"), ("AUTHORITY.md", "authority"), ("SEMANTIC-STATE.json", "{}"), ("SOURCE-LEDGER.md", "sources"), ("SYNTHESIS.md", "synthesis")):
                (root / name).write_text(text)
            control = FakeControl(); control.state["queue"]["items"].append({"id": "A", "cwd": str(root)})
            first = accept_research_completion(control, topic_id="A", run_id="one", station_id=1, inventory_version="v", accepted=True, deepening_entry=True)
            prior = start_checkpoint(control, episode_id=first["episode_id"], station_id=1, run_id="prior")
            complete_counter(control, prior); finish_checkpoint(control, checkpoint_result(prior, "prior"))
            with control.transaction() as state:
                state["work"]["topics"]["A"].update(research_iterations_completed=24, next_research_ordinal=25)
            (root / "logs").mkdir(); (root / "logs" / "growth.log").write_text("irrelevant")
            due = accept_research_completion(control, topic_id="A", run_id="two", station_id=1, inventory_version="v", accepted=True)
            reuse = start_checkpoint(control, episode_id=due["episode_id"], station_id=1, run_id="reuse")
            self.assertEqual(reuse["prior_review_reference"], prior["episode_id"])
            value = checkpoint_result(reuse, "reuse"); value["reuse_of"] = prior["episode_id"]
            self.assertEqual(finish_checkpoint(control, value)["state"], "complete_without_proposals")
            for change in ("operator_feedback", "inventory", "incomplete_prior"):
                with self.subTest(change=change):
                    changed_control = FakeControl()
                    changed_control.state = control.snapshot()
                    changed_control.state["work"]["topics"]["A"].update(research_iterations_completed=49, next_research_ordinal=50)
                    if change == "operator_feedback":
                        changed_control.state["work"]["decisions"]["feedback"] = {"result": {"topic_id": "A"}, "reason": "reconsider the prior exclusion"}
                    if change == "incomplete_prior":
                        for old in changed_control.state["work"]["episodes"].values():
                            old["state"] = "needs_attention"
                    next_due = accept_research_completion(changed_control, topic_id="A", run_id="fifty", station_id=1,
                        inventory_version="new-inventory" if change == "inventory" else "v", accepted=True)
                    next_episode = start_checkpoint(changed_control, episode_id=next_due["episode_id"], station_id=1, run_id="next-review")
                    self.assertIsNone(next_episode["prior_review_reference"])
                    invalid_reuse = checkpoint_result(next_episode, "next-review") | {"reuse_of": prior["episode_id"]}
                    with self.assertRaises(CheckpointError):
                        finish_checkpoint(changed_control, invalid_reuse)
            # Contract/inventory changes and operator feedback both invalidate
            # the digest before a later reuse can be accepted.
            (root / "TOPIC.md").write_text("changed")
            with control.transaction() as state:
                state["work"]["topics"]["A"].update(research_iterations_completed=49, next_research_ordinal=50)
            changed_due = accept_research_completion(control, topic_id="A", run_id="three", station_id=1, inventory_version="v", accepted=True)
            changed = start_checkpoint(control, episode_id=changed_due["episode_id"], station_id=1, run_id="changed")
            self.assertIsNone(changed["prior_review_reference"])
            invalid = checkpoint_result(changed, "changed"); invalid["reuse_of"] = prior["episode_id"]
            with self.assertRaises(CheckpointError):
                finish_checkpoint(control, invalid)

    def test_proposal_decision_is_strict_idempotent_and_preserves_ordinal(self):
        control = FakeControl()
        result = accept_research_completion(control, topic_id="A", run_id="run", station_id=1, inventory_version="v1", accepted=True, deepening_entry=True)
        episode = start_checkpoint(control, episode_id=result["episode_id"], station_id=1, run_id="cp")
        complete_counter(control, episode)
        finish_checkpoint(control, checkpoint_result(episode, "cp", [proposal()]))
        payload = {"schema_version": 1, "request_id": "decision-1", "expected_revision": control.snapshot()["revision"], "topic_id": "A", "episode_id": episode["episode_id"], "decisions": [{"proposal_id": "proposal-1", "proposal_version": 1, "action": "reject", "reason": "covered"}]}
        decision = apply_decision(control, payload)
        self.assertTrue(decision["resolved"])
        self.assertEqual(decision["next_research_ordinal"], 2)
        self.assertEqual(apply_decision(control, payload), decision)
        changed = copy.deepcopy(payload); changed["decisions"][0]["reason"] = "different ruling"
        with self.assertRaises(CheckpointError) as raised:
            apply_decision(control, changed)
        self.assertEqual(raised.exception.code, "DUPLICATE_REQUEST_CONFLICT")

    def test_approval_fails_closed_without_contract_publisher(self):
        control = FakeControl()
        result = accept_research_completion(control, topic_id="A", run_id="run", station_id=1, inventory_version="v1", accepted=True, deepening_entry=True)
        episode = start_checkpoint(control, episode_id=result["episode_id"], station_id=1, run_id="cp")
        complete_counter(control, episode)
        finish_checkpoint(control, checkpoint_result(episode, "cp", [proposal()]))
        payload = {"schema_version": 1, "request_id": "approve-1", "expected_revision": control.snapshot()["revision"], "topic_id": "A", "episode_id": episode["episode_id"], "decisions": [{"proposal_id": "proposal-1", "proposal_version": 1, "action": "approve", "reason": "publish it"}]}
        with self.assertRaises(CheckpointError) as raised:
            apply_decision(control, payload)
        self.assertEqual(raised.exception.code, "PUBLICATION_PENDING")
        self.assertEqual(control.snapshot()["work"]["proposals"]["proposal-1"]["status"], "pending")

    def test_delegate_broker_debits_budget_before_idempotent_launch(self):
        control = FakeControl()
        result = accept_research_completion(control, topic_id="A", run_id="run", station_id=1, inventory_version="v1", accepted=True, deepening_entry=True)
        episode = start_checkpoint(control, episode_id=result["episode_id"], station_id=1, run_id="cp")
        launch = reserve_delegate_launch(control, episode_id=episode["episode_id"], lease_id="cp", invocation_id="counter-1", role="counter")
        self.assertEqual((launch["seat"], launch["profile"]), ("primary", "terra"))
        replay = reserve_delegate_launch(control, episode_id=episode["episode_id"], lease_id="cp", invocation_id="counter-1", role="counter")
        self.assertFalse(replay["_new_reservation"])
        self.assertTrue(launch["_new_reservation"])
        remaining = control.snapshot()["work"]["episodes"][episode["episode_id"]]["remaining_budgets"]["delegate_launches"]
        self.assertEqual(remaining, 3)

    def test_repair_exchange_reserves_response_then_assessment(self):
        control = FakeControl()
        accepted = accept_research_completion(control, topic_id="A", run_id="r", station_id=1, inventory_version="v", accepted=True, deepening_entry=True)
        episode = start_checkpoint(control, episode_id=accepted["episode_id"], station_id=1, run_id="cp")
        reserve_delegate_launch(control, episode_id=episode["episode_id"], lease_id="cp", invocation_id="counter", role="counter")
        record_delegate_result(control, episode_id=episode["episode_id"], invocation_id="counter", exit_code=0, output_reference="counter.json")
        reserve_delegate_launch(control, episode_id=episode["episode_id"], lease_id="cp", invocation_id="repair-r", role="repair_response")
        record_delegate_result(control, episode_id=episode["episode_id"], invocation_id="repair-r", exit_code=0, output_reference="repair-r.json")
        assessment = reserve_delegate_launch(control, episode_id=episode["episode_id"], lease_id="cp", invocation_id="repair-a", role="repair_assessment")
        self.assertEqual(assessment["seat"], "primary")
        state = control.snapshot()["work"]["episodes"][episode["episode_id"]]
        self.assertEqual((state["remaining_budgets"]["delegate_launches"], state["remaining_budgets"]["repair_exchanges"]), (1, 0))
        with self.assertRaises(CheckpointError) as raised:
            reserve_delegate_launch(control, episode_id=episode["episode_id"], lease_id="cp", invocation_id="repair-a-again", role="repair_assessment")
        self.assertEqual(raised.exception.code, "REVISION_CONFLICT")

    def test_delegate_rejects_path_like_invocation_id(self):
        control = FakeControl()
        accepted = accept_research_completion(control, topic_id="A", run_id="r", station_id=1, inventory_version="v", accepted=True, deepening_entry=True)
        episode = start_checkpoint(control, episode_id=accepted["episode_id"], station_id=1, run_id="cp")
        with self.assertRaises(CheckpointError) as raised:
            reserve_delegate_launch(control, episode_id=episode["episode_id"], lease_id="cp", invocation_id="../../planted", role="counter")
        self.assertEqual(raised.exception.code, "VALIDATION_ERROR")

    def test_registered_codex_adapter_uses_exec_model_output_file_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fake-codex.py"; seen = Path(tmp) / "args.json"
            result = {"episode_id": "episode", "run_id": "run", "inventory_version": "v1", "trigger_ids": ["trigger"], "complete": True, "findings": [], "limitations": [], "protocol_evidence_refs": [], "proposals": []}
            script.write_text("#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\na=sys.argv[1:]; Path(a[a.index('--trusted')-1]).write_text(json.dumps(a))\nPath(a[a.index('-o')+1]).write_text(" + repr(json.dumps(result)) + ")\n")
            script.chmod(0o755)
            adapter = RegisteredCheckpointAdapter({"id": "terra", "adapter": "codex", "model": "test-model", "executable": str(script), "argv": [str(seen), "--trusted"]})
            value = CheckpointRunner(adapter).run({"episode_id": "episode", "run_id": "run", "inventory_version": "v1", "trigger_ids": ["trigger"]})
            args = json.loads(seen.read_text())
            self.assertEqual(args[:4], ["exec", "-m", "test-model", "-o"])
            self.assertIn("--trusted", args); self.assertEqual(value["episode_id"], "episode")

    def test_managed_intake_lane_records_fresh_structured_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = default_configuration(); config["active_count"] = 1
            for station in config["stations"]:
                station["primary_profile"] = f"primary-{station['id']}"; station["secondary_profile"] = f"secondary-{station['id']}"
            control = ControlStore.initialize(root, configuration=config, agent_profiles=registered_profiles(config))
            service = IntakeService(control, root / "topics", actor="operator")
            service.submit_brief({"schema_version": 1, "request_id": "brief", "topic_id": "intake-topic", "title": "Intake", "operator_brief": "Check the brief.", "mode": "focused"})
            def discovery(context):
                return {"pass_kind": "criteria", "restated_intent": "Check the brief.", "criteria": [{"id": str(i), "status": "pass", "explanation": "checked"} for i in range(1, 7)], "traceability": [], "questions": []}
            runner = LoopRunner(QueueStore(root), UsageLedger(root / "usage.jsonl"), worker="intake-1", lanes=("intake",), discovery_adapter=discovery)
            outcome = runner.run_once()
            self.assertEqual(outcome["outcome"], "awaiting_operator")
            draft = control.snapshot()["work"]["intake_drafts"]["intake-topic"]
            self.assertEqual((draft["status"], len(draft["discovery_history"])), ("awaiting_operator", 1))

    def test_dispatch_approval_publishes_once_and_preserves_next_ordinal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); topics = root / "topics"
            topic_authoring.new_topic("a", title="A", brief_text="Original obligation.", dest=topics, mode="focused")
            directory = topics / "a"; qa = directory / "QA-RECORD.md"
            qa.write_text(qa.read_text().replace("## Operator confirmation", "## Operator confirmation\n\nConfirmed."))
            (directory / "SCOPE-PROPOSAL.md").write_text("pass")
            topic_authoring.approve_topic("a", dest=topics)
            control = FakeControl()
            result = accept_research_completion(control, topic_id="a", run_id="r", station_id=1, inventory_version="v1", accepted=True, deepening_entry=True)
            episode = start_checkpoint(control, episode_id=result["episode_id"], station_id=1, run_id="cp")
            complete_counter(control, episode)
            finish_checkpoint(control, checkpoint_result(episode, "cp", [proposal()]))
            payload = {"schema_version":1,"request_id":"approve","expected_revision":control.snapshot()["revision"],"topic_id":"a","episode_id":episode["episode_id"],"decisions":[{"proposal_id":"proposal-1","proposal_version":1,"action":"approve","reason":"publish"}]}
            decide = operator_dispatch(control, topics, actor="operator")["checkpoint.decide"]
            first = decide(payload); replay = decide(payload)
            self.assertEqual(first, replay); self.assertEqual(first["next_research_ordinal"], 2)
            self.assertEqual(sum(1 for x in json.loads((directory / "SEMANTIC-STATE.json").read_text())["obligations"] if x["text"] == "An exact proposed obligation"), 1)
            self.assertFalse((directory / ".checkpoint-contract-publication.json").exists())
