#!/usr/bin/env python3
"""Optional, zero-dependency cross-reference index over every topic's
SOURCE-LEDGER.md citations (see docs/citations.md).

Entirely derived, never authoritative: delete the output file and rebuild
any time from the topics themselves -- nothing here is the evidence of
record. Never auto-built, never a `completion_errors()`/`validate`
dependency; building it is an explicit, optional operator action, same as
running `dashboard` today. An index hit is a lead, not evidence -- see
`chassis/CONTRACT-CORE.md`'s evidence-handling section and
`docs/citations.md`'s "Index hits are leads, never evidence".

This *is* the default/reference backend, not the only one. Anything
satisfying the same two-verb contract (`<backend> build <topics_root>
<output>`, `<backend> query <output> [--field value]...` printing JSON)
can stand in for it -- see docs/operations.md for the adapter-selection
convention, mirroring runners/README.md's spirit for LLM CLI adapters.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SEMANTIC_STATE_PATH = Path(__file__).resolve().parent / "semantic-state.py"
_spec = importlib.util.spec_from_file_location("semantic_state", _SEMANTIC_STATE_PATH)
assert _spec is not None and _spec.loader is not None
semantic_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(semantic_state)


def _obligation_citations(topic_dir: Path) -> dict[str, list[str]]:
    """Map src_id -> sorted obligation ids that cite it, for one topic."""
    try:
        state = json.loads((topic_dir / "SEMANTIC-STATE.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result: dict[str, list[str]] = {}
    for obligation in state.get("obligations", []):
        obligation_id = obligation.get("id")
        for reference in obligation.get("evidence_refs") or []:
            src_id = semantic_state.resolve_citation_id(topic_dir, reference)
            if src_id is not None:
                result.setdefault(src_id, []).append(obligation_id)
    return {src_id: sorted(set(ids)) for src_id, ids in result.items()}


def build(topics_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for topic_dir in sorted(p for p in topics_root.iterdir() if p.is_dir()):
        try:
            ledger_text = (topic_dir / "SOURCE-LEDGER.md").read_text(encoding="utf-8")
        except OSError:
            continue
        blocks = semantic_state.parse_source_ledger(ledger_text)
        if not blocks:
            continue
        obligation_citations = _obligation_citations(topic_dir)
        for src_id in sorted(blocks):
            block = blocks[src_id]
            fields = block.get("fields", {})
            block_type = block.get("type")
            record: dict[str, Any] = {
                "topic_id": topic_dir.name,
                "src_id": src_id,
                "type": block_type,
                "obligation_ids": obligation_citations.get(src_id, []),
                "indexed_at": now,
            }
            if block_type == "external":
                record["url"] = fields.get("url")
                record["title"] = fields.get("title")
                record["retrieved"] = fields.get("retrieved")
            elif block_type == "local":
                record["path"] = fields.get("path")
            elif block_type == "internal":
                record["ref_topic"] = fields.get("topic")
                record["ref_src"] = fields.get("ref")
            records.append(record)
    return records


def write_jsonl(records: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def read_jsonl(index_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with index_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def query(
    index_path: Path,
    *,
    url_contains: str | None = None,
    title_contains: str | None = None,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    records = read_jsonl(index_path)
    if url_contains:
        records = [r for r in records if url_contains in (r.get("url") or "")]
    if title_contains:
        records = [r for r in records if title_contains in (r.get("title") or "")]
    if topic:
        records = [r for r in records if r.get("topic_id") == topic]
    return records


def doctor(topics_root: Path) -> list[dict[str, Any]]:
    """Report every `internal` citation across the portfolio whose pointer
    no longer resolves, or chains into another `internal` citation --
    the same drift class `evidence_citation_errors()` catches per-topic at
    `validate` time, but scanned proactively, portfolio-wide, without
    needing any topic's obligations to actually cite the block."""
    problems: list[dict[str, Any]] = []
    all_blocks: dict[str, dict[str, dict[str, Any]]] = {}
    for topic_dir in sorted(p for p in topics_root.iterdir() if p.is_dir()):
        try:
            text = (topic_dir / "SOURCE-LEDGER.md").read_text(encoding="utf-8")
        except OSError:
            continue
        all_blocks[topic_dir.name] = semantic_state.parse_source_ledger(text)
    for topic_id, blocks in all_blocks.items():
        for src_id, block in blocks.items():
            if block.get("type") != "internal":
                continue
            fields = block.get("fields", {})
            ref_topic = fields.get("topic", "")
            ref_src = fields.get("ref", "")
            target_blocks = all_blocks.get(ref_topic)
            if target_blocks is None or ref_src not in target_blocks:
                problems.append(
                    {
                        "topic_id": topic_id,
                        "src_id": src_id,
                        "problem": f"points at {ref_topic}#{ref_src} which does not exist",
                    }
                )
            elif target_blocks[ref_src].get("type") == "internal":
                problems.append(
                    {
                        "topic_id": topic_id,
                        "src_id": src_id,
                        "problem": f"points at another internal citation ({ref_topic}#{ref_src})",
                    }
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    build_p = sub.add_parser(
        "build", help="scan every topic's SOURCE-LEDGER.md and write the index"
    )
    build_p.add_argument("topics_root", type=Path)
    build_p.add_argument("output", type=Path)

    query_p = sub.add_parser("query", help="filter an already-built index")
    query_p.add_argument("index", type=Path)
    query_p.add_argument("--url-contains")
    query_p.add_argument("--title-contains")
    query_p.add_argument("--topic")

    doctor_p = sub.add_parser(
        "doctor",
        help="report dangling or chained internal citations across the portfolio",
    )
    doctor_p.add_argument("topics_root", type=Path)

    args = parser.parse_args(argv)
    if args.action == "build":
        records = build(args.topics_root)
        write_jsonl(records, args.output)
        print(f"indexed {len(records)} citation(s) across the portfolio -> {args.output}")
        return 0
    if args.action == "query":
        results = query(
            args.index,
            url_contains=args.url_contains,
            title_contains=args.title_contains,
            topic=args.topic,
        )
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0
    if args.action == "doctor":
        problems = doctor(args.topics_root)
        print(json.dumps(problems, indent=2, sort_keys=True))
        return 1 if problems else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
