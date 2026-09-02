"""The semantic-state accessor/write-through CLI (docs/state-access.md).

Agents must read scoped views (`select`/`get`) instead of the whole state
file, and write through guarded commands instead of rewriting the file with
ad-hoc scripts. The guards matter more than the token savings: a terminal
transition is validated with the DONE gate's own rule implementation at
write time, so a state the completion gate would reject can never land.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_STATE = ROOT / "research_loops" / "chassis" / "semantic-state.py"
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SEMANTIC_STATE), *args],
        capture_output=True,
        text=True,
    )


class StateCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topic_dir = Path(self._tmp.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)
        self.state_path = self.topic_dir / "SEMANTIC-STATE.json"
        # A real file evidence can point at.
        (self.topic_dir / "FINDINGS-LOG.md").write_text("finding\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _signature(self):
        return _run("signature", str(self.topic_dir)).stdout.strip()

    # --- reads ---------------------------------------------------------

    def test_select_returns_open_full_and_terminal_skeletons(self):
        state = self._state()
        first = state["obligations"][0]["id"]
        # Make one obligation terminal directly in the fixture.
        state["obligations"][0].update(
            disposition="unresolved",
            counterevidence_reviewed=True,
            acceptance_summary="s",
            counterevidence_summary="s",
            adequate_search={
                "summary": "x", "queries": ["q"],
                "source_lanes": ["web"], "retrieval_failures": [],
            },
        )
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
        result = _run("select", str(self.topic_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        view = json.loads(result.stdout)
        self.assertEqual(view["counts"]["obligations_terminal"], 1)
        skeleton = view["terminal_obligations"][0]
        self.assertEqual(skeleton["id"], first)
        self.assertNotIn("acceptance_summary", skeleton)
        for record in view["open_obligations"]:
            self.assertIn("text", record)  # open records are complete

    def test_get_returns_one_full_record_or_fails(self):
        some_id = self._state()["obligations"][0]["id"]
        result = _run("get", str(self.topic_dir), some_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["kind"], "obligation")
        self.assertIn("text", payload["record"])
        self.assertEqual(_run("get", str(self.topic_dir), "NOPE-99").returncode, 1)

    # --- obligation transitions ---------------------------------------

    def test_open_stage_update_writes_and_moves_the_signature(self):
        some_id = self._state()["obligations"][0]["id"]
        before = self._signature()
        result = _run(
            "transition", str(self.topic_dir), some_id,
            "--gap-state", "narrowed to two candidates",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(before, self._signature())
        record = json.loads(_run("get", str(self.topic_dir), some_id).stdout)["record"]
        self.assertEqual(record["gap_state"], "narrowed to two candidates")

    def test_incomplete_terminal_transition_refused_and_nothing_written(self):
        some_id = self._state()["obligations"][0]["id"]
        before = self.state_path.read_bytes()
        result = _run(
            "transition", str(self.topic_dir), some_id,
            "--disposition", "supported",  # no evidence, no summaries
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("terminal transition refused", result.stderr)
        self.assertEqual(before, self.state_path.read_bytes())

    def test_complete_terminal_transition_in_one_call_succeeds(self):
        some_id = self._state()["obligations"][0]["id"]
        result = _run(
            "transition", str(self.topic_dir), some_id,
            "--disposition", "unresolved",
            "--counterevidence-reviewed", "true",
            "--acceptance-summary", "searched, nothing decisive",
            "--counterevidence-summary", "no counterevidence located",
            "--adequate-search", json.dumps({
                "summary": "three lanes searched",
                "queries": ["q1", "q2"],
                "source_lanes": ["web", "papers"],
                "retrieval_failures": [],
            }),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(_run("get", str(self.topic_dir), some_id).stdout)["record"]
        self.assertEqual(record["disposition"], "unresolved")
        # The DONE gate agrees with the write-time check for this obligation.
        validate = _run("validate", str(self.topic_dir))
        self.assertNotIn(f"obligation {some_id}", validate.stderr)

    def test_supported_requires_existing_evidence_refs(self):
        some_id = self._state()["obligations"][0]["id"]
        missing = _run(
            "transition", str(self.topic_dir), some_id,
            "--add-evidence-ref", "NO-SUCH-FILE.md",
        )
        self.assertEqual(missing.returncode, 1)
        self.assertIn("does not exist", missing.stderr)
        ok = _run(
            "transition", str(self.topic_dir), some_id,
            "--disposition", "supported",
            "--confidence", "well-established",
            "--counterevidence-reviewed", "true",
            "--acceptance-summary", "s",
            "--counterevidence-summary", "s",
            "--add-evidence-ref", "FINDINGS-LOG.md",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_identity_fields_are_not_writable(self):
        some_id = self._state()["obligations"][0]["id"]
        result = subprocess.run(
            [sys.executable, str(SEMANTIC_STATE), "transition",
             str(self.topic_dir), some_id, "--disposition", "open",
             "--gap-state", "x"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # (id/text/source_ref are simply not exposed as flags; the guard in
        # apply_obligation_transition also rejects them programmatically.)
        sys.path.insert(0, str(SEMANTIC_STATE.parent))
        import importlib.util
        spec = importlib.util.spec_from_file_location("ss_guard", SEMANTIC_STATE)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["ss_guard"] = mod
        spec.loader.exec_module(mod)
        state = self._state()
        errors = mod.apply_obligation_transition(
            self.topic_dir, state, some_id, {"text": "rewritten scope"}, []
        )
        self.assertTrue(errors and "not writable" in errors[0])

    # --- pending / deliverable / contradiction ------------------------

    def test_pending_add_remove_roundtrip(self):
        add = _run("pending", str(self.topic_dir), "--add", "FINDINGS-LOG.md:L1")
        self.assertEqual(add.returncode, 0, add.stderr)
        self.assertIn("FINDINGS-LOG.md:L1", self._state()["pending_evidence_refs"])
        bogus = _run("pending", str(self.topic_dir), "--add", "GONE.md:L9")
        self.assertEqual(bogus.returncode, 1)
        remove = _run("pending", str(self.topic_dir), "--remove", "FINDINGS-LOG.md:L1")
        self.assertEqual(remove.returncode, 0, remove.stderr)
        self.assertEqual(self._state()["pending_evidence_refs"], [])

    def test_deliverable_completion_requires_summary_and_refs(self):
        deliverable_id = self._state()["deliverables"][0]["id"]
        refused = _run(
            "deliverable", str(self.topic_dir), deliverable_id, "--status", "complete"
        )
        self.assertEqual(refused.returncode, 1)
        ok = _run(
            "deliverable", str(self.topic_dir), deliverable_id,
            "--status", "complete",
            "--acceptance-summary", "written and checked",
            "--add-acceptance-ref", "FINDINGS-LOG.md",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_contradiction_open_and_resolve(self):
        opened = _run("contradiction", str(self.topic_dir), "--open", "CONTRA-01")
        self.assertEqual(opened.returncode, 0, opened.stderr)
        unresolved = _run("contradiction", str(self.topic_dir), "--resolve", "CONTRA-01")
        self.assertEqual(unresolved.returncode, 1)  # needs --resolution
        resolved = _run(
            "contradiction", str(self.topic_dir),
            "--resolve", "CONTRA-01", "--resolution", "sources reconciled",
        )
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        record = json.loads(_run("get", str(self.topic_dir), "CONTRA-01").stdout)
        self.assertEqual(record["record"]["status"], "resolved")


class ContinuousCadenceTests(unittest.TestCase):
    def test_repeat_seconds_zero_means_continuous_not_bounded(self):
        from research_loops.queue import QueueError, QueueStore

        with tempfile.TemporaryDirectory() as tmp:
            store = QueueStore(Path(tmp))
            item = store.add(
                title="continuous", cwd=tmp, command=["true"],
                item_id="c", repeat_seconds=0,
            )
            self.assertEqual(item["repeat_seconds"], 0)
            with self.assertRaises(QueueError):
                store.add(
                    title="bad", cwd=tmp, command=["true"],
                    item_id="bad", repeat_seconds=-1,
                )


if __name__ == "__main__":
    unittest.main()


class DeferredEscalationTests(unittest.TestCase):
    """Deferring is allowed as a record, never as a silent exit.

    Scope belongs to the operator: a deferred disposition immediately writes
    a NEEDS-OPERATOR STOP with a structured `flag:` line, so the queue parks
    the topic as needs_attention and the operator knows exactly where to
    look. Sneaking toward DONE via deferrals is structurally impossible.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topic_dir = Path(self._tmp.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _defer(self, obligation_id):
        return _run(
            "transition", str(self.topic_dir), obligation_id,
            "--disposition", "deferred",
            "--counterevidence-reviewed", "true",
            "--acceptance-summary", "deferred: depends on unshipped tooling",
            "--counterevidence-summary", "none reviewed; deferral is scope, not evidence",
            "--experiment", json.dumps({
                "question": "does the tooling exist yet",
                "method": "re-check the vendor changelog",
                "success_measure": "tooling shipped and testable",
            }),
        )

    def test_deferred_transition_writes_flagged_stop(self):
        state = json.loads((self.topic_dir / "SEMANTIC-STATE.json").read_text())
        first = state["obligations"][0]["id"]
        result = self._defer(first)
        self.assertEqual(result.returncode, 0, result.stderr)
        stop = self.topic_dir / "STOP"
        self.assertTrue(stop.exists(), "deferral must park the topic for the operator")
        body = stop.read_text(encoding="utf-8").splitlines()
        self.assertEqual(body[0], "NEEDS-OPERATOR")
        self.assertIn(f"flag: deferred-obligation {first}", body)

    def test_second_deferral_appends_without_duplicating(self):
        state = json.loads((self.topic_dir / "SEMANTIC-STATE.json").read_text())
        ids = [o["id"] for o in state["obligations"][:2]]
        self.assertEqual(self._defer(ids[0]).returncode, 0)
        self.assertEqual(self._defer(ids[1]).returncode, 0)
        body = (self.topic_dir / "STOP").read_text(encoding="utf-8")
        self.assertEqual(body.count("NEEDS-OPERATOR"), 1)
        for oid in ids:
            self.assertEqual(body.count(f"flag: deferred-obligation {oid}"), 1)

    def test_non_deferred_terminal_writes_no_stop(self):
        state = json.loads((self.topic_dir / "SEMANTIC-STATE.json").read_text())
        first = state["obligations"][0]["id"]
        result = _run(
            "transition", str(self.topic_dir), first,
            "--disposition", "unresolved",
            "--counterevidence-reviewed", "true",
            "--acceptance-summary", "searched, nothing decisive",
            "--counterevidence-summary", "no counterevidence located",
            "--adequate-search", json.dumps({
                "summary": "s", "queries": ["q"],
                "source_lanes": ["web"], "retrieval_failures": [],
            }),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.topic_dir / "STOP").exists())
