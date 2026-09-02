"""The DONE gate and the liveness signature must share one definition of
"semantic state".

completion_errors() decides when a topic may finish; semantic_projection()
decides whether an iteration made progress (the queue's stall guard hashes
it). When the two disagree, a whole class of contract-compliant iterations
registers as "no progress": the 2026-08-31 incident was a discovery-only
iteration whose only change was new pending_evidence_refs — required by
CONTRACT-CORE's evidence discipline, invisible to the old projection,
flagged as a stall.

The fix is structural, not per-field: semantic_projection() derives from the
*_SEMANTIC_FIELDS tuples, and the parity test here fails the build the moment
completion_errors() starts reasoning over a field those tuples don't carry.
"""

import hashlib
import importlib.util
import inspect
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_STATE = ROOT / "research_loops" / "chassis" / "semantic-state.py"
EXAMPLE_TOPIC = ROOT / "examples" / "static-site-generator-choice"

_spec = importlib.util.spec_from_file_location("chassis_semantic_state", SEMANTIC_STATE)
chassis = importlib.util.module_from_spec(_spec)
sys.modules["chassis_semantic_state"] = chassis
_spec.loader.exec_module(chassis)


def _signature(state: dict) -> str:
    payload = json.dumps(
        chassis.semantic_projection(state), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _minimal_state() -> dict:
    return {
        "schema_version": 1,
        "topic_id": "t",
        "contract_sha256": "c" * 64,
        "authority_sha256": "a" * 64,
        "pending_evidence_refs": [],
        "contradictions": [],
        "obligations": [
            chassis.obligation("SCOPE-01", "text", "TOPIC.md"),
        ],
        "deliverables": [
            chassis.deliverable("TOPIC-SYNTHESIS", "SYNTHESIS.md", ["## SCOPE-01"], "d"),
        ],
    }


class ProjectionParityTests(unittest.TestCase):
    """The class guard: everything the validator reasons over is projected."""

    # Identity fields are pinned by the completion-inventory lock and the
    # TOPIC.md/AUTHORITY.md hashes (both projected via contract_sha256 /
    # authority_sha256); changing them is a scope change, not iteration
    # progress, so they are exempt from liveness projection.
    OBLIGATION_IDENTITY_FIELDS = {"text", "source_ref"}
    DELIVERABLE_IDENTITY_FIELDS = {"description", "path", "required_headings"}
    # Containers the projection walks rather than projects as scalar fields.
    STATE_CONTAINER_FIELDS = {"obligations", "deliverables", "contradictions"}

    def setUp(self):
        # The per-obligation rules live in obligation_terminal_errors (shared
        # with the `transition` write path); the parity guard must see both.
        self.validator_source = inspect.getsource(
            chassis.completion_errors
        ) + inspect.getsource(chassis.obligation_terminal_errors)

    def _accessed(self, variable: str) -> set[str]:
        """Every field completion_errors() reads off `variable`, whether via
        .get("name") or a `for field in ("a", "b", ...)` identity loop."""
        fields = set(
            re.findall(rf'{variable}\.get\(\s*"([a-z_]+)"', self.validator_source)
        )
        for match in re.finditer(
            r'for field in \(([^)]*)\):\s*\n\s*if not isinstance\('
            rf"{variable}\.get\(field\)",
            self.validator_source,
        ):
            fields.update(re.findall(r'"([a-z_]+)"', match.group(1)))
        return fields

    def test_projection_covers_every_validated_obligation_field(self):
        validated = self._accessed("obligation") - self.OBLIGATION_IDENTITY_FIELDS
        missing = validated - set(chassis.OBLIGATION_SEMANTIC_FIELDS)
        self.assertFalse(
            missing,
            f"completion_errors() validates obligation field(s) {sorted(missing)} "
            "that OBLIGATION_SEMANTIC_FIELDS does not project — iterations that "
            "change only those fields would look stalled. Add them to the tuple.",
        )

    def test_projection_covers_every_validated_deliverable_field(self):
        validated = self._accessed("deliverable") - self.DELIVERABLE_IDENTITY_FIELDS
        missing = validated - set(chassis.DELIVERABLE_SEMANTIC_FIELDS)
        self.assertFalse(
            missing,
            f"completion_errors() validates deliverable field(s) {sorted(missing)} "
            "that DELIVERABLE_SEMANTIC_FIELDS does not project.",
        )

    def test_projection_covers_every_validated_contradiction_field(self):
        validated = self._accessed("contradiction")
        missing = validated - set(chassis.CONTRADICTION_SEMANTIC_FIELDS)
        self.assertFalse(
            missing,
            f"completion_errors() validates contradiction field(s) {sorted(missing)} "
            "that CONTRADICTION_SEMANTIC_FIELDS does not project.",
        )

    def test_projection_covers_every_validated_top_level_field(self):
        validated = self._accessed("state") - self.STATE_CONTAINER_FIELDS
        missing = validated - set(chassis.TOP_LEVEL_SEMANTIC_FIELDS)
        self.assertFalse(
            missing,
            f"completion_errors() validates top-level field(s) {sorted(missing)} "
            "that TOP_LEVEL_SEMANTIC_FIELDS does not project — the 2026-08-31 "
            "pending_evidence_refs incident was exactly this gap.",
        )


class DiscoveryProgressTests(unittest.TestCase):
    """The instances the parity guard exists to prevent, kept as regressions."""

    def test_discovery_only_iteration_moves_the_signature(self):
        state = _minimal_state()
        before = _signature(state)
        state["pending_evidence_refs"] = ["SOURCE-LEDGER.md:L12"]
        self.assertNotEqual(before, _signature(state))

    def test_strengthening_evidence_moves_the_signature(self):
        state = _minimal_state()
        state["obligations"][0]["evidence_refs"] = ["FINDINGS-LOG.md:L3"]
        before = _signature(state)
        state["obligations"][0]["evidence_refs"].append("FINDINGS-LOG.md:L9")
        self.assertNotEqual(before, _signature(state))

    def test_recording_an_adequate_search_moves_the_signature(self):
        state = _minimal_state()
        before = _signature(state)
        state["obligations"][0]["adequate_search"] = {
            "summary": "searched",
            "queries": ["q"],
            "source_lanes": ["web"],
            "retrieval_failures": [],
        }
        self.assertNotEqual(before, _signature(state))

    def test_reordering_references_is_not_progress(self):
        state = _minimal_state()
        state["obligations"][0]["evidence_refs"] = ["b.md", "a.md"]
        state["pending_evidence_refs"] = ["y.md", "x.md"]
        before = _signature(state)
        state["obligations"][0]["evidence_refs"] = ["a.md", "b.md"]
        state["pending_evidence_refs"] = ["x.md", "y.md"]
        self.assertEqual(before, _signature(state))


class SignatureCliTests(unittest.TestCase):
    """End-to-end through the same `signature` subcommand the queue's
    progress_command invokes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.topic_dir = Path(self._tmp.name) / "topic"
        shutil.copytree(EXAMPLE_TOPIC, self.topic_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _cli_signature(self) -> str:
        result = subprocess.run(
            [sys.executable, str(SEMANTIC_STATE), "signature", str(self.topic_dir)],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def test_pending_evidence_moves_the_cli_signature(self):
        before = self._cli_signature()
        state_path = self.topic_dir / "SEMANTIC-STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.setdefault("pending_evidence_refs", []).append("SOURCE-LEDGER.md:L1")
        state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.assertNotEqual(before, self._cli_signature())


if __name__ == "__main__":
    unittest.main()
