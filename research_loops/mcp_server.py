"""MCP server exposing the research-loops engine as agent-callable tools.

Two tiers, one server:

- **Read-only** (always registered): queue/topic introspection, doctor,
  event history, usage accounting. Safe for any operator-facing session.
- **Operator** (only with ``--operator``): everything that reshapes the
  queue or mints scope — pause/resume/move, agent assignment, refresh,
  relock, and the draft→approve topic-authoring flow. The gate is the
  server *instance*, configured in the harness, never negotiable by the
  model at runtime: a session attached to a read-only instance cannot
  talk its way into write access.

Research iterations themselves must NOT be given this server (either
tier): the loops need no queue awareness, and CONTRACT-CORE forbids a
research agent from reshaping scope or scheduling. This surface exists
for operator sessions (interactive Claude/Codex/Hermes, phone sessions
via the MCP gateway) and meta-tooling.

Transports: stdio (a local harness spawns this process) or streamable
HTTP (``--http``) for gateway federation — a gateway registers the URL as
an external MCP, which is how phone/web sessions reach it. stdio cannot
cross hosts: a gateway running elsewhere must use the HTTP transport.

The ``mcp`` SDK is an optional extra (``pip install research-loops[mcp]``);
this module imports it lazily so the core engine keeps zero dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from . import doctor as doctor_mod, refresh as refresh_mod, topic_authoring
from .queue import QueueError, QueueStore
from .runner import UsageLedger

# Fleet defaults applied when approve_and_queue registers a new item; they
# mirror the deployed portfolio's standard configuration.
DEFAULT_AGENT_MAIN = "claude"
DEFAULT_AGENT_SECONDARY = "codex exec -m gpt-5.6-luna"
DEFAULT_REPEAT_SECONDS = 900
DEFAULT_STALL_LIMIT = 6
DEFAULT_MAX_ATTEMPTS = 8

# Compact per-item projection for queue_status: enough to reason about
# scheduling and health from a chat session without drowning it in the
# full item record.
_STATUS_FIELDS = (
    "id",
    "title",
    "status",
    "desired_state",
    "claimed_by",
    "attempts",
    "consecutive_failures",
    "last_error_kind",
    "last_exit_code",
    "next_eligible_at",
    "agent_main",
    "agent_secondary",
)


class EngineTools:
    """Plain-function tool handlers over one engine root.

    Deliberately MCP-free: every public method takes/returns JSON-able
    values and raises QueueError on misuse, so the whole surface is
    testable without an MCP client and reusable by any future transport.
    """

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.topics_root = self.root / "topics"

    # ------------------------------------------------------------------
    # Read-only tier
    # ------------------------------------------------------------------

    def queue_status(self) -> dict[str, Any]:
        state = self.store.snapshot()
        items = [
            {field: item.get(field) for field in _STATUS_FIELDS}
            | {
                "position": position,
                "depends_on_count": len(item.get("depends_on") or []),
            }
            for position, item in enumerate(state["items"])
        ]
        return {
            "paused": state.get("paused"),
            "stopping": state.get("stopping"),
            "pause_reason": state.get("pause_reason"),
            "item_count": len(items),
            "items": items,
        }

    def topic_state(self, topic_id: str) -> dict[str, Any]:
        item = self.store.get(topic_id)
        result: dict[str, Any] = {
            "item": {field: item.get(field) for field in _STATUS_FIELDS},
            "depends_on": item.get("depends_on") or [],
        }
        topic_dir = Path(item["cwd"])
        state_path = topic_dir / "SEMANTIC-STATE.json"
        if state_path.is_file():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            dispositions = Counter(
                str(o.get("disposition"))
                for o in state.get("obligations", [])
                if isinstance(o, dict)
            )
            result["semantic"] = {
                "schema_version": state.get("schema_version"),
                "obligations_total": sum(dispositions.values()),
                "obligations_by_disposition": dict(dispositions),
                "pending_evidence_refs": len(state.get("pending_evidence_refs") or []),
                "open_contradictions": sum(
                    1
                    for c in state.get("contradictions", [])
                    if isinstance(c, dict) and c.get("status") == "open"
                ),
                "deliverables": [
                    {"id": d.get("id"), "status": d.get("status")}
                    for d in state.get("deliverables", [])
                    if isinstance(d, dict)
                ],
            }
        latest = topic_dir / "logs" / "latest-result.json"
        if latest.is_file():
            try:
                result["latest_iteration"] = json.loads(
                    latest.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError:
                pass
        return result

    def doctor(self) -> dict[str, Any]:
        return doctor_mod.run_doctor(
            self.store.snapshot()["items"], topics_root=self.topics_root
        )

    def recent_events(
        self,
        limit: int = 50,
        topic_id: str | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        events = self.ledger.events()
        if topic_id:
            events = [e for e in events if e.get("item_id") == topic_id]
        if event_type:
            events = [e for e in events if e.get("type") == event_type]
        return events[-limit:]

    def usage_summary(self) -> dict[str, Any]:
        return {"summary": self.ledger.summary()}

    # ------------------------------------------------------------------
    # Operator tier
    # ------------------------------------------------------------------

    def pause_topic(
        self, topic_id: str, reason: str | None = None, graceful: bool = True
    ) -> dict[str, Any]:
        return self.store.pause_item(topic_id, reason, graceful=graceful)

    def resume_topic(self, topic_id: str) -> dict[str, Any]:
        return self.store.resume_item(topic_id)

    def pause_all(
        self, reason: str | None = None, graceful: bool = True
    ) -> dict[str, Any]:
        return self.store.pause_all(reason, graceful=graceful)

    def resume_all(self) -> dict[str, Any]:
        return self.store.resume_all()

    def move_topic(self, topic_id: str, position: int) -> dict[str, Any]:
        return self.store.move(topic_id, int(position))

    def restart_topic(self, topic_id: str) -> dict[str, Any]:
        return self.store.request_restart(topic_id)

    def swap_active(self, worker: str, topic_id: str) -> dict[str, Any]:
        return self.store.reassign_worker(worker, topic_id)

    def set_agents(
        self,
        topic_id: str,
        agent_main: str | None = None,
        agent_secondary: str | None = None,
    ) -> dict[str, Any]:
        settings: dict[str, Any] = {}
        if agent_main is not None:
            settings["agent_main"] = agent_main or None
        if agent_secondary is not None:
            settings["agent_secondary"] = agent_secondary or None
        if not settings:
            raise QueueError("set_agents: pass agent_main and/or agent_secondary")
        return self.store.configure_topic(topic_id, **settings)

    def refresh_topic(self, topic_id: str, mode: str) -> dict[str, Any]:
        return refresh_mod.apply_refresh(self.store, topic_id, mode)

    def relock_topic(self, topic_id: str) -> dict[str, Any]:
        item = self.store.get(topic_id)
        lock = topic_authoring.compute_lock(Path(item["cwd"]))
        return self.store.set_completion_lock(topic_id, lock)

    def draft_topic(
        self, topic_id: str, title: str, brief: str, mode: str = "broad"
    ) -> dict[str, Any]:
        """Scaffold a DRAFT topic from an operator brief.

        mode="broad" (default): assumptions get surfaced and a discovery pass
        (start_discovery) maps the topic space before scoping. mode="focused":
        the operator's stated frame is fixed — QA clarifies within it and
        never questions premises. Drafts are reviewable and re-draftable:
        calling again with a refined brief overwrites the DRAFT-* files.
        Nothing is binding until approve_and_queue, which is gated on a
        completed QA record either way.
        """
        result = topic_authoring.new_topic(
            topic_id, title=title, brief_text=brief, dest=self.topics_root, mode=mode
        )
        draft_state = json.loads(
            (self.topics_root / topic_id / "DRAFT-SEMANTIC-STATE.json").read_text(
                encoding="utf-8"
            )
        )
        result["obligations"] = [
            {"id": o["id"], "text": o["text"]} for o in draft_state["obligations"]
        ]
        return result

    def read_draft(self, topic_id: str) -> dict[str, Any]:
        topic_dir = self.topics_root / topic_id
        draft = topic_dir / "DRAFT-TOPIC.md"
        if not draft.is_file():
            if (topic_dir / "TOPIC.md").is_file():
                raise QueueError(f"{topic_id} is already approved (no draft pending)")
            raise QueueError(f"no draft for {topic_id} -- call draft_topic first")
        return {
            "topic_id": topic_id,
            "draft_topic_md": draft.read_text(encoding="utf-8"),
        }

    def start_discovery(
        self, topic_id: str, agent_main: str = DEFAULT_AGENT_MAIN,
        agent_secondary: str = DEFAULT_AGENT_SECONDARY,
    ) -> dict[str, Any]:
        """Queue a bounded discovery pass for a DRAFT topic on the intake lane.

        Runs in parallel with the research fleet (dedicated intake worker),
        but discovery passes themselves serialize: the intake lane's
        concurrency cap defaults to 1, so a pile of broad-mode drafts queue
        their passes one at a time. Output: SCOPE-PROPOSAL.md plus surfaced
        assumptions appended to QA-RECORD.md, awaiting the operator's ruling.
        """
        draft_dir = self.topics_root / topic_id
        if not (draft_dir / "DRAFT-TOPIC.md").is_file():
            raise QueueError(
                f"no draft for {topic_id} -- call draft_topic first "
                "(discovery runs on drafts, before approval)"
            )
        run_discovery = (
            Path(__file__).resolve().parent / "chassis" / "run-discovery.sh"
        )
        return self.store.add(
            title=f"Discovery: {topic_id}",
            cwd=str(draft_dir),
            command=[str(run_discovery), str(draft_dir), agent_main],
            item_id=f"discovery.{topic_id}",
            usage_file="logs/latest-usage.json",
            max_attempts=3,
            agent_main=agent_main,
            agent_secondary=agent_secondary,
            lane="intake",
        )

    def read_scope_proposal(self, topic_id: str) -> dict[str, Any]:
        """The discovery pass's output plus the current QA record, for the
        operator's review before ruling via record_qa."""
        draft_dir = self.topics_root / topic_id
        result: dict[str, Any] = {"topic_id": topic_id}
        proposal = draft_dir / "SCOPE-PROPOSAL.md"
        if proposal.is_file():
            result["scope_proposal_md"] = proposal.read_text(encoding="utf-8")
        qa = draft_dir / "QA-RECORD.md"
        if qa.is_file():
            result["qa_record_md"] = qa.read_text(encoding="utf-8")
        if len(result) == 1:
            raise QueueError(
                f"nothing to review for {topic_id}: no SCOPE-PROPOSAL.md or "
                "QA-RECORD.md (draft it, run discovery, then review)"
            )
        return result

    _QA_HEADINGS = (
        "Operator confirmation",
        "Scope decision",
        "Questions for the operator",
        "Deliverable exceptions",
    )

    def record_qa(self, topic_id: str, heading: str, text: str) -> dict[str, Any]:
        """Append the operator's ruling under a QA-RECORD.md section.

        Restricted to the operator-owned headings — the QA agent's own
        sections are its to write. approve_and_queue refuses until
        'Operator confirmation' (and, broad mode, 'Scope decision') carry a
        real answer, so this is how a phone session unblocks approval.
        """
        if heading not in self._QA_HEADINGS:
            raise QueueError(
                f"heading must be one of {list(self._QA_HEADINGS)}"
            )
        if not text.strip():
            raise QueueError("text is required")
        qa = self.topics_root / topic_id / "QA-RECORD.md"
        if not qa.is_file():
            raise QueueError(f"no QA-RECORD.md for {topic_id} -- draft_topic first")
        content = qa.read_text(encoding="utf-8")
        marker = f"## {heading}"
        if marker in content:
            head, tail = content.split(marker, 1)
            rest = tail.split("\n## ", 1)
            section = rest[0].rstrip() + f"\n\n{text.strip()}\n"
            content = head + marker + section + (
                ("\n## " + rest[1]) if len(rest) > 1 else ""
            )
        else:
            content = content.rstrip() + f"\n\n{marker}\n\n{text.strip()}\n"
        qa.write_text(content, encoding="utf-8")
        return {"topic_id": topic_id, "heading": heading, "recorded": True}

    def approve_and_queue(
        self,
        topic_id: str,
        confirm: str,
        position: int | None = None,
        agent_main: str = DEFAULT_AGENT_MAIN,
        agent_secondary: str = DEFAULT_AGENT_SECONDARY,
    ) -> dict[str, Any]:
        """Promote a reviewed draft into a binding topic AND register it.

        This mints binding obligations and pins the completion lock — the
        single most governance-sensitive act in the system — so `confirm`
        must repeat the topic id exactly. Registration applies the fleet
        defaults; `position` (0-based) optionally moves it in the queue.
        """
        if confirm != topic_id:
            raise QueueError(
                "approve_and_queue mints binding scope: pass confirm equal to "
                f"the topic id ({topic_id!r}) to proceed"
            )
        approved = topic_authoring.approve_topic(topic_id, dest=self.topics_root)
        topic_dir = self.topics_root / topic_id
        title = (
            (topic_dir / "TOPIC.md")
            .read_text(encoding="utf-8")
            .splitlines()[0]
            .lstrip("# ")
            .strip()
        )
        run_topic = (
            Path(__file__).resolve().parent / "chassis" / "run-topic.sh"
        )
        item = self.store.add(
            title=title,
            cwd=str(topic_dir),
            command=[str(run_topic), str(topic_dir), agent_main],
            item_id=topic_id,
            usage_file="logs/latest-usage.json",
            stop_file="STOP",
            repeat_seconds=DEFAULT_REPEAT_SECONDS,
            stall_limit=DEFAULT_STALL_LIMIT,
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            agent_main=agent_main,
            agent_secondary=agent_secondary,
            completion_lock=approved["lock"],
        )
        if position is not None:
            item = self.store.move(topic_id, int(position))
        return {
            "approved": approved,
            "item": {field: item.get(field) for field in _STATUS_FIELDS},
            "position": position,
        }


_READ_ONLY_TOOLS = (
    "queue_status",
    "topic_state",
    "doctor",
    "recent_events",
    "usage_summary",
)
_OPERATOR_TOOLS = (
    "pause_topic",
    "resume_topic",
    "pause_all",
    "resume_all",
    "move_topic",
    "restart_topic",
    "swap_active",
    "set_agents",
    "refresh_topic",
    "relock_topic",
    "draft_topic",
    "read_draft",
    "start_discovery",
    "read_scope_proposal",
    "record_qa",
    "approve_and_queue",
)


def build_server(root: Path, *, operator: bool = False):
    """Construct the MCP app. Imports the optional `mcp` extra lazily."""
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise SystemExit(
            "the MCP server needs the optional extra: pip install research-loops[mcp]"
        ) from exc

    tools = EngineTools(root)
    name = "research-loops" + ("-operator" if operator else "")
    tier = (
        "read-only and operator tiers (this instance can reshape the queue "
        "and mint topic scope; approve_and_queue requires confirm=<topic id>)"
        if operator
        else "read-only tier (introspection only; no tool here mutates anything)"
    )
    server = MCPServer(
        name,
        instructions=(
            "Tools over a research-loops engine (autonomous research queue): "
            f"{tier}. Root: {tools.root}. Never attach this server to a "
            "research iteration itself."
        ),
    )
    registered = _READ_ONLY_TOOLS + (_OPERATOR_TOOLS if operator else ())
    for tool_name in registered:
        server.tool()(getattr(tools, tool_name))
    return server


def main(argv: list[str] | None = None) -> int:
    from .__main__ import _default_root

    parser = argparse.ArgumentParser(
        prog="research-loops-mcp",
        description=(
            "Serve the research-loops engine as MCP tools. Read-only by "
            "default; --operator adds queue-mutating and topic-authoring "
            "tools. Never attach either tier to a research iteration."
        ),
    )
    parser.add_argument(
        "--root",
        default=None,
        help="engine root containing state/ and topics/ (default: same "
        "resolution as the research-loops CLI)",
    )
    parser.add_argument(
        "--operator",
        action="store_true",
        help="register the operator tier (pause/resume/move/authoring/relock)",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve streamable HTTP instead of stdio (for gateway federation)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8321)
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve() if args.root else _default_root()
    server = build_server(root, operator=args.operator)
    if args.http:
        server.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
