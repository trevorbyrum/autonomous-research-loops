"""Deterministic topic scaffolding and approval -- no LLM call, ever.

`new_topic()` splits a free-text brief into candidate obligations and writes
DRAFT-AUTHORITY.md/DRAFT-TOPIC.md/DRAFT-SEMANTIC-STATE.json; nothing is binding
until `approve_topic()` promotes them, recomputing hashes from whatever you
actually left in the DRAFT files after review. See docs/topic-authoring.md.

Backs the `research-loops new-topic`/`research-loops approve-topic`
subcommands in __main__.py.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .queue import QueueError

_PACKAGE_DIR = Path(__file__).resolve().parent

LEDGER_FILES = (
    "SOURCE-LEDGER.md",
    "FINDINGS-LOG.md",
    "DECISIONS-LOG.md",
    "NEEDS-SOURCE.md",
    "PROGRESS.md",
    "SYNTHESIS.md",
)

SOURCE_LEDGER_STUB = (
    "# SOURCE-LEDGER.md\n\n"
    "Every claim an obligation cites as evidence must resolve to a typed citation\n"
    "block here -- see ../../docs/citations.md for the full format "
    "(`external`/`local`/`internal`).\n"
)

_TOPIC_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def split_brief(text: str) -> list[str]:
    """Decompose free text into candidate obligations.

    Splits on semicolons and sentence boundaries (period + capital letter), strips a
    leading conjunction, and keeps each result as one whole obligation -- no further
    comma-splitting. A paragraph with no semicolons and no internal sentence breaks
    becomes one (possibly long) obligation; that's a signal to go back and add
    semicolons to your brief for finer decomposition, not a bug to work around here.
    """
    chunks: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        cleaned = " ".join(paragraph.split())
        if not cleaned:
            continue
        for value in re.split(r";\s+|\.\s+(?=[A-Z])", cleaned):
            value = value.strip(" .")
            value = re.sub(r"^(?:and|or|but)\s+", "", value, flags=re.IGNORECASE)
            value = value.strip(" .")
            if len(value) < 3:
                continue
            chunks.append(value)
    return list(dict.fromkeys(chunks))


def obligation(identifier: str, text: str, source_ref: str) -> dict[str, object]:
    return {
        "id": identifier,
        "text": text,
        "source_ref": source_ref,
        "disposition": "open",
        "confidence": None,
        "evidence_refs": [],
        "counterevidence_reviewed": False,
        "acceptance_summary": None,
        "counterevidence_summary": None,
        "gap_state": f"unaddressed: {identifier}",
        "adequate_search": None,
        "experiment": None,
    }


def default_deliverables() -> list[dict[str, object]]:
    return [
        {
            "id": "TOPIC-SYNTHESIS",
            "description": "Topic-specific synthesis with one section per approved obligation",
            "path": "SYNTHESIS.md",
            "required_headings": [],
            "status": "missing",
            "acceptance_summary": None,
            "acceptance_evidence_refs": [],
        }
    ]


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_authority(title: str, brief_text: str) -> str:
    return (
        f"# {title} — authoritative sources\n\n"
        "This is the operator-authored scope for this topic, pasted or drafted below.\n"
        "Replace or extend this freely -- it is the ground truth this topic's research\n"
        "is measured against.\n\n"
        "## Operator brief (verbatim)\n\n"
        f"{brief_text.strip()}\n\n"
        "## Evidence-quality vocabulary (default -- replace if your domain needs different tiers)\n\n"
        "- **T1**: primary sources -- official documentation, peer-reviewed papers,\n"
        "  first-party measured data, official changelogs.\n"
        "- **T2**: reproducible independent evaluations, credible engineering reports\n"
        "  with direct measurements.\n"
        "- **T3**: practitioner reports and community accounts -- leads/corroboration\n"
        "  only, never sole support for a high-confidence claim.\n"
        "- **T4**: marketing prose, unsourced leaderboards -- leads only, never evidence.\n\n"
        "Every evidence_ref this topic's obligations cite must resolve to a typed\n"
        "citation block in SOURCE-LEDGER.md -- see docs/citations.md for the exact\n"
        "format (`external`/`local`/`internal`) before writing your first one.\n"
    )


def render_topic(
    title: str,
    authority_hash: str,
    obligations: list[dict[str, object]],
    deliverables: list[dict[str, object]],
) -> str:
    lines = [
        f"# {title}",
        "",
        "## Authority and boundary",
        "",
        "This is the operator-approved semantic contract. `AUTHORITY.md` is",
        f"incorporated verbatim by reference (SHA-256 `{authority_hash}`). No research",
        "agent may add binding scope or redefine DONE.",
        "",
        "## Dependencies",
        "",
        "- None declared. Add real content-dependency topic IDs here if this topic",
        "  genuinely cannot proceed without another topic's output -- not for",
        "  scheduling preference (see docs/topic-authoring.md).",
        "",
        "## Approved finite obligations",
        "",
        "Draft, decomposed from your brief -- review and edit before approving.",
        "",
    ]
    for item in obligations:
        lines.append(f"- **{item['id']}** — {item['text']}")
    lines.extend(["", "## Required deliverables", ""])
    for item in deliverables:
        lines.append(f"- **{item['id']}** — {item['description']} (`{item['path']}`).")
    lines.extend(
        [
            "",
            "## Semantic exit condition",
            "",
            "Continue until every obligation above has a terminal disposition",
            "(supported, contradicted, unresolved, or deferred), pending evidence and",
            "contradictions are dispositioned, and every deliverable exists.",
            "`semantic-state.py validate` is the executable gate -- not a description",
            "of it. No fixed iteration, token, source, or time limit defines DONE.",
            "",
            "## Storage",
            "",
            "This topic's own ledgers in this directory. No external storage is",
            "required; add your own storage bindings here if you configure one.",
            "",
        ]
    )
    return "\n".join(lines)


def compute_lock(topic_dir: Path) -> str:
    """The topic's current completion-inventory lock, via the chassis.

    The single shared implementation for everything that pins or re-pins a
    lock (approve_topic here, the CLI `relock`, the MCP relock_topic tool) —
    duplicating the chassis invocation would let their lock semantics drift.
    """
    semantic_state_py = _PACKAGE_DIR / "chassis" / "semantic-state.py"
    result = subprocess.run(
        [sys.executable, str(semantic_state_py), "lock", str(topic_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise QueueError(
            f"could not compute the completion lock for {topic_dir}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result.stdout.strip()


def new_topic(topic_id: str, *, title: str, brief_text: str, dest: Path) -> dict[str, Any]:
    if not _TOPIC_ID_PATTERN.fullmatch(topic_id):
        raise QueueError("topic id must be lowercase letters/digits/hyphens")
    if not brief_text.strip():
        raise QueueError("brief is empty")

    topic_dir = dest / topic_id
    if (topic_dir / "TOPIC.md").exists():
        raise QueueError(f"{topic_dir}/TOPIC.md already exists -- this topic is already approved")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "logs").mkdir(exist_ok=True)
    for name in LEDGER_FILES:
        target = topic_dir / name
        if not target.exists():
            target.write_text(
                SOURCE_LEDGER_STUB if name == "SOURCE-LEDGER.md" else f"# {name}\n",
                encoding="utf-8",
            )
    (topic_dir / "DECISIONS-LOG.md").write_text(
        "# Decisions\n\n| id | date | decision |\n|---|---|---|\n", encoding="utf-8"
    )

    chunks = split_brief(brief_text)
    obligations = [
        obligation(f"SCOPE-{i:02d}", text, "AUTHORITY.md#operator-brief-verbatim")
        for i, text in enumerate(chunks, 1)
    ]
    deliverables = default_deliverables()

    authority = render_authority(title, brief_text)
    authority_hash = _sha256_text(authority)
    contract = render_topic(title, authority_hash, obligations, deliverables)
    contract_hash = _sha256_text(contract)

    state = {
        "schema_version": 2,
        "topic_id": topic_id,
        "contract_sha256": contract_hash,
        "authority_sha256": authority_hash,
        "obligations": obligations,
        "deliverables": deliverables,
        "pending_evidence_refs": [],
        "contradictions": [],
    }

    (topic_dir / "DRAFT-AUTHORITY.md").write_text(authority, encoding="utf-8")
    (topic_dir / "DRAFT-TOPIC.md").write_text(contract, encoding="utf-8")
    (topic_dir / "DRAFT-SEMANTIC-STATE.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return {
        "topic_dir": str(topic_dir),
        "obligation_count": len(obligations),
        "chunk_count": len(chunks),
    }


def approve_topic(topic_id: str, *, dest: Path) -> dict[str, Any]:
    topic_dir = dest / topic_id
    draft_authority = topic_dir / "DRAFT-AUTHORITY.md"
    draft_topic = topic_dir / "DRAFT-TOPIC.md"
    draft_state = topic_dir / "DRAFT-SEMANTIC-STATE.json"
    for path in (draft_authority, draft_topic, draft_state):
        if not path.is_file():
            raise QueueError(f"{path} not found -- run `research-loops new-topic` first")
    if (topic_dir / "TOPIC.md").exists():
        raise QueueError(f"{topic_dir}/TOPIC.md already exists -- already approved")

    state = json.loads(draft_state.read_text(encoding="utf-8"))
    # Recompute from whatever is actually on disk now, not what new_topic computed
    # at scaffold time -- the whole point of the DRAFT stage is that you edit these.
    state["contract_sha256"] = hashlib.sha256(draft_topic.read_bytes()).hexdigest()
    state["authority_sha256"] = hashlib.sha256(draft_authority.read_bytes()).hexdigest()

    draft_authority.rename(topic_dir / "AUTHORITY.md")
    draft_topic.rename(topic_dir / "TOPIC.md")
    (topic_dir / "SEMANTIC-STATE.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    draft_state.unlink()

    semantic_state_py = _PACKAGE_DIR / "chassis" / "semantic-state.py"
    run_topic_sh = _PACKAGE_DIR / "chassis" / "run-topic.sh"

    check = subprocess.run(
        [sys.executable, str(semantic_state_py), "check", str(topic_dir)],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        raise QueueError(
            f"{check.stdout.strip()}\n{check.stderr.strip()}".strip()
        )

    lock = compute_lock(topic_dir)

    suggested_command = (
        "research-loops add --id "
        f"{topic_id} --title \"...\" --cwd {topic_dir} "
        f"--stop-file STOP --max-attempts 8 --repeat-seconds 900 "
        f"--lock-sha256 {lock} -- "
        f"{run_topic_sh} {topic_dir} generic"
    )

    return {
        "topic_dir": str(topic_dir),
        "check_output": check.stdout.strip(),
        "lock": lock,
        "suggested_command": suggested_command,
    }
