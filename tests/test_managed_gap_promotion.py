"""Durability contract for lease-scoped managed auto-gap promotion."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_loops.access import issue_capability
from research_loops.control_store import ControlScheduler, ControlStore, default_configuration, default_work
from research_loops.gap_promotion import promote


REPO = Path(__file__).resolve().parents[1]


class ManagedGapPromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.topic = self.root / "topics" / "example"
        shutil.copytree(REPO / "examples" / "static-site-generator-choice", self.topic)
        config = default_configuration(); config["active_count"] = 1
        for station in config["stations"]: station.update(primary_profile="test", secondary_profile="test")
        work = default_work(); work["agent_profiles"] = {"test": {"adapter":"generic", "model":"test", "executable":"/bin/true", "argv":[]}}
        queue = {"revision":0,"paused":False,"stopping":False,"items":[{"id":"example","cwd":str(self.topic),"status":"queued","desired_state":"running","lane":"research","gap_policy":"auto","gap_auto_limit":1,"completion_lock":None}]}
        self.control = ControlStore.initialize(self.root, configuration=config, queue=queue, work=work)
        self.lease = ControlScheduler(self.control).claim(1)
        # Direct helper tests use a same-UID capability; controller peer tests
        # cover OS credential transport separately.
        self.token = issue_capability(self.control, topic_id="example", lease_id=self.lease["lease_id"], agent_uid=os.geteuid())
        self.payload = {"topic_id":"example", "obligation_id":"AUTO-01", "text":"An approved bounded gap.", "source_ref":"operator brief"}

    def tearDown(self): self.temp.cleanup()

    def _call(self, payload=None):
        return promote(self.control, peer_uid=os.geteuid(), token=self.token, payload=payload or self.payload)

    def test_exact_replay_commits_one_budget_entry(self):
        first = self._call(); replay = self._call()
        self.assertEqual(first, replay)
        self.assertEqual(len(self.control.snapshot()["work"]["auto_gap_promotions"]["example"]), 1)

    def test_changed_reuse_of_same_obligation_is_rejected(self):
        self._call()
        with self.assertRaises(ValueError): self._call(self.payload | {"text":"changed"})

    def test_invalid_source_does_not_write_any_contract_file(self):
        before = {(self.topic / name).read_bytes() for name in ("TOPIC.md", "SEMANTIC-STATE.json", "DECISIONS-LOG.md")}
        with self.assertRaises(ValueError): self._call(self.payload | {"source_ref":""})
        after = {(self.topic / name).read_bytes() for name in ("TOPIC.md", "SEMANTIC-STATE.json", "DECISIONS-LOG.md")}
        self.assertEqual(before, after)

    def test_crash_after_files_before_commit_recovers_exactly_once(self):
        with patch("research_loops.gap_promotion._commit_promotion", side_effect=RuntimeError("crash after publication")):
            with self.assertRaisesRegex(RuntimeError, "crash"): self._call()
        result = self._call()
        self.assertEqual(result["obligation_id"], "AUTO-01")
        self.assertEqual(len(self.control.snapshot()["work"]["auto_gap_promotions"]["example"]), 1)

    def test_symlinked_target_is_refused(self):
        target = self.topic / "TOPIC.md"; outside = self.root / "outside"
        outside.write_text(target.read_text()); target.unlink(); target.symlink_to(outside)
        with self.assertRaises(ValueError): self._call()
        self.assertEqual(outside.read_text(), (self.root / "outside").read_text())


if __name__ == "__main__": unittest.main()
