"""Production chassis, Unix controller, UID drop, provider and checkpoint smoke.

No provider network or live portfolio is used. A disposable fake Codex speaks the
real CLI/last-message protocol and invokes the actual checkpoint delegate broker.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

REPO = Path(__file__).resolve().parents[1]


def exercise(root: Path) -> dict:
    installed = root / "installed"
    shutil.copytree(REPO / "research_loops", installed / "research_loops", ignore=shutil.ignore_patterns("__pycache__"))
    for path in [installed, *installed.rglob("*")]:
        path.chmod(0o755 if path.is_dir() or path.suffix == ".sh" else 0o644)
    sys.path.insert(0, str(installed))
    from research_loops.access import initialize_access
    from research_loops.control_store import ControlStore, default_configuration
    from research_loops.controller import Controller, ControllerServer
    from research_loops.deployment import protect_topic
    from research_loops.intake import _research_item
    from research_loops.queue import QueueStore
    from research_loops.runner import LoopRunner, UsageLedger
    from research_loops.topic_authoring import compute_lock

    root.chmod(0o755)
    directory = root / "topics" / "example"
    shutil.copytree(REPO / "examples" / "static-site-generator-choice", directory)
    provider = root / "fake-codex"
    provider.write_text("#!/usr/bin/python3\n" + f"import sys; sys.path.insert(0, {str(installed)!r})\n" + r'''
import json, os
from pathlib import Path
args = sys.argv[1:]
assert args[0] == 'exec', args
assert args[args.index('-m') + 1] == 'fake-model', args
prompt = args[-1]
output = args[args.index('-o') + 1]
if os.environ.get('RESEARCH_LOOP_CHECKPOINT_ROLE'):
    task = json.loads(prompt)
    result = {'schema_version': 1, 'invocation_id': task['invocation_id'],
              'role': task['role'], 'status': 'complete', 'findings': ['counter complete'], 'limitations': []}
elif 'STRUCTURED CONTEXT:' in prompt:
    context = json.JSONDecoder().raw_decode(prompt.split('STRUCTURED CONTEXT:', 1)[1].lstrip())[0]
    from research_loops.controller_client import call
    counter = call(os.environ['RESEARCH_LOOP_CONTROLLER_SOCKET'], 'checkpoint.delegate', {
        'episode_id': context['episode_id'], 'lease_id': context['run_id'],
        'invocation_id': 'fresh-counter', 'role': 'counter', 'prompt': 'Independently review this checkpoint.'
    }, token=os.environ['RESEARCH_LOOP_EXECUTION_CAPABILITY'])
    assert counter['invocation']['exit_code'] == 0, counter
    result = {key: context[key] for key in ('episode_id', 'run_id', 'inventory_version', 'trigger_ids')}
    result.update(complete=True, findings=['review complete'], limitations=[],
                  protocol_evidence_refs=[counter['invocation']['output_reference']], proposals=[])
else:
    result = 'ordinary provider invocation completed'
Path(output).write_text(json.dumps(result) if isinstance(result, dict) else result)
''')
    provider.chmod(0o755)
    config = default_configuration()
    config["active_count"] = 1
    for station in config["stations"]:
        station.update(primary_profile="fake", secondary_profile="fake", interval_seconds=0)
    config["checkpoints"]["on_deepening_entry"] = False
    item = _research_item("example", directory, compute_lock(directory))
    control = ControlStore.initialize(root, configuration=config,
        agent_profiles={"fake": {"adapter": "codex", "model": "fake-model", "executable": str(provider), "argv": []}},
        queue={"revision": 0, "paused": False, "stopping": False, "items": [item]})
    with control.transaction() as state:
        topic = control.ensure_topic_work(state, "example", inventory_version=item["completion_lock"])
        topic.update(research_iterations_completed=24, next_research_ordinal=25)
    initialize_access(root, agent_uid=65534, agent_gid=65534, operator_uids=[0], socket_path=str(root / "run" / "controller.sock"))
    protect_topic(directory, agent_uid=65534, agent_gid=65534)
    os.environ["RESEARCH_GATEWAY_URL"] = "http://127.0.0.1:1"
    runner = LoopRunner(QueueStore(root), UsageLedger(root / "usage.jsonl"), worker="station-1", poll_seconds=0.05)
    records, counts = [], []
    with ControllerServer(Controller(root)) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for _ in range(3):
                result = runner.run_once()
                records.append(result)
                counts.append(control.snapshot()["work"]["topics"]["example"]["research_iterations_completed"])
        finally:
            server.shutdown()
            thread.join()
    return {"records": records, "counts": counts,
            "topic": control.snapshot()["work"]["topics"]["example"],
            "logs": {p.name: p.read_text(errors="replace")[-3000:] for p in (root / "logs").glob("*.log")}}


class ManagedExecutionTests(unittest.TestCase):
    def test_real_chassis_25_checkpoint_26_with_controller_and_separate_uid(self):
        if not shutil.which("sudo") or subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode:
            self.skipTest("requires a privileged disposable supervisor to drop execution UID")
        with tempfile.TemporaryDirectory(prefix="managed-e2e-") as temporary:
            command = ["sudo", "-n", sys.executable, str(Path(__file__).resolve()), "--exercise", temporary]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["counts"], [25, 25, 26], report)
                self.assertEqual([r["outcome"] for r in report["records"]], ["scheduled", "complete_without_proposals", "scheduled"], report)
                self.assertEqual(report["topic"]["next_research_ordinal"], 27)
            finally:
                subprocess.run(["sudo", "-n", "/bin/rm", "-rf", "--", temporary], check=True)


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    if len(sys.argv) == 3 and sys.argv[1] == "--exercise":
        print(json.dumps(exercise(Path(sys.argv[2]))))
    else:
        unittest.main()
