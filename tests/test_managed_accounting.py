import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_loops.control_store import ControlStore, default_configuration
from research_loops.queue import QueueStore
from research_loops.runner import LoopRunner, UsageLedger


class ManagedAccountingTests(unittest.TestCase):
    def test_zero_exit_needs_operator_stop_does_not_count_research(self):
        """The ordinary production runner must not count a parked zero-exit run."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            topic = root / "topic"
            topic.mkdir()
            config = default_configuration()
            config["active_count"] = 1
            for station in config["stations"]:
                station.update(primary_profile="runner", secondary_profile="runner", interval_seconds=0)
            control = ControlStore.initialize(
                root,
                configuration=config,
                agent_profiles={"runner": {"adapter": "codex", "model": "test", "executable": sys.executable, "argv": []}},
                queue={"revision": 0, "paused": False, "stopping": False, "items": []},
            )
            store = QueueStore(root)
            store.add(
                item_id="run-353", title="broken configuration", cwd=str(topic), stop_file="STOP",
                command=[sys.executable, "-c", "from pathlib import Path; Path('STOP').write_text('NEEDS-OPERATOR: configuration invalid\\n')"],
            )
            runner = LoopRunner(store, UsageLedger(root / "events.jsonl"), worker="station-1", poll_seconds=.01)
            # This test isolates accounting from deployment UID setup while
            # retaining the real managed claim, run, stop, and finalize path.
            with patch("research_loops.access.prepare_agent_launch", return_value=({}, {})):
                result = runner.run_once()
            self.assertEqual(result["outcome"], "needs_attention")
            topic_work = control.snapshot()["work"]["topics"]["run-353"]
            self.assertEqual(topic_work["research_iterations_completed"], 0)
            self.assertEqual(topic_work["next_research_ordinal"], 1)
            run = next(iter(control.snapshot()["work"]["runs"].values()))
            self.assertFalse(run["accepted"])


if __name__ == "__main__":
    unittest.main()
