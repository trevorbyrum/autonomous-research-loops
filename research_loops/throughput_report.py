"""Phase 9·0 throughput report: one topic's iterations measured, not guessed.

    RESEARCH_GATEWAY_DSN=... python3 -m research_loops.throughput_report topics/<id>

Per iteration (correlated by the tracing stamp the stdio client sends as a header and
the gateway stores OUTSIDE request identity — D-33): gateway call count, provider time,
broker wait, the overlap-aware elapsed retrieval window, batch usage, repeat lookups
classified by request type (independent verification is never labeled waste), phase
durations from the agent's markers (missing = unknown), delegate token cost, and the
iteration result's outcome facts. The same report re-runs after every lever so
"faster" is a number; a comparison without recorded context (models, workers, cache
state, provider health) does not attribute anything.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _iterations(topic_dir: Path) -> list[str]:
    stamps = sorted(p.name[len("result-"):-len(".json")] for p in (topic_dir / "logs").glob("result-*.json"))
    return stamps


def _phases(topic_dir: Path, stamp: str) -> dict[str, float]:
    """Marker lines '<iso> <phase>' → seconds per phase (duration = until next marker)."""
    path = topic_dir / "logs" / f"phases-{stamp}.log"
    if not path.exists():
        return {}
    marks = []
    for line in path.read_text(errors="replace").splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        try:
            marks.append((datetime.fromisoformat(parts[0].replace("Z", "+00:00")), parts[1]))
        except ValueError:
            continue
    out: dict[str, float] = {}
    for (t0, name), (t1, _) in zip(marks, marks[1:]):
        out[name] = out.get(name, 0.0) + (t1 - t0).total_seconds()
    return out


def _delegate_tokens(topic_dir: Path, start: str, end: str | None) -> int:
    total = 0
    path = topic_dir / "logs" / "delegate-usage.jsonl"
    if not path.exists():
        return 0
    lo = start.replace("T", " ")[:15]  # stamps are 20260908T012345Z; ts is ISO — compare coarsely by ISO string
    for line in path.read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        ts = (e.get("ts") or "").replace("-", "").replace(":", "")
        if ts >= start and (end is None or ts < end):
            total += int(e.get("total_tokens") or 0)
    return total


def _result(topic_dir: Path, stamp: str) -> dict:
    try:
        return json.loads((topic_dir / "logs" / f"result-{stamp}.json").read_text())
    except (OSError, ValueError):
        return {}


def _calls(conn, stamp: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), coalesce(sum(latency_ms),0), coalesce(sum(wait_ms),0), "
            "count(batch_entry), min(at), max(at + make_interval(secs => coalesce(latency_ms,0)/1000.0)) "
            "FROM gateway.calls WHERE iteration = %s AND failure_class <> 'attempt'", (stamp,))
        n, provider_ms, wait_ms, batched, first, last = cur.fetchone()
        cur.execute(
            "SELECT request_type, count(*) FROM ("
            "  SELECT request_type, source_id, coalesce(query, identity) AS subject, count(*) AS reps "
            "  FROM gateway.calls WHERE iteration = %s AND failure_class <> 'attempt' "
            "  GROUP BY 1, 2, 3 HAVING count(*) > 1) r GROUP BY request_type", (stamp,))
        repeats = dict(cur.fetchall())
    conn.commit()
    elapsed = (last - first).total_seconds() if first and last else None
    return {"calls": int(n), "provider_ms": int(provider_ms), "wait_ms": int(wait_ms),
            "batched": int(batched), "retrieval_elapsed_s": round(elapsed, 1) if elapsed is not None else None,
            "repeats_by_type": repeats}


def report(topic_dir: Path, conn) -> str:
    stamps = _iterations(topic_dir)
    lines = [f"# Throughput report — {topic_dir.name} ({datetime.now(timezone.utc).isoformat(timespec='seconds')})",
             "", "Context (record alongside every comparison): models/workers from state/queue.json "
             "worker_agents; cache state and provider health from /v1/status; anything unrecorded is unknown.", "",
             "| iteration | calls | provider_s | wait_s | retrieval window s | batched | repeats | outcome | qualifying | sources+ | delegate tokens | phases |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, stamp in enumerate(stamps):
        nxt = stamps[i + 1] if i + 1 < len(stamps) else None
        calls = _calls(conn, stamp) if conn is not None else {}
        res = _result(topic_dir, stamp)
        phases = _phases(topic_dir, stamp)
        phase_txt = " ".join(f"{k}:{int(v)}s" for k, v in phases.items()) or "unknown"
        repeats = calls.get("repeats_by_type") or {}
        lines.append("| {stamp} | {calls} | {prov} | {wait} | {window} | {batched} | {reps} | {outcome} | {qual} | {src} | {tok} | {phases} |".format(
            stamp=stamp,
            calls=calls.get("calls", "unknown"),
            prov=round(calls.get("provider_ms", 0) / 1000.0, 1) if calls else "unknown",
            wait=round(calls.get("wait_ms", 0) / 1000.0, 1) if calls else "unknown",
            window=calls.get("retrieval_elapsed_s", "unknown"),
            batched=calls.get("batched", "unknown"),
            reps=json.dumps(repeats) if repeats else "-",
            outcome=res.get("outcome", "unknown"),
            qual=res.get("signature_changed", "unknown"),
            src=res.get("sources_cited", "unknown"),
            tok=_delegate_tokens(topic_dir, stamp, nxt),
            phases=phase_txt))
    lines += ["", f"Iterations without tracing rows predate D-33 instrumentation: their gateway columns read 0/unknown — never imputed."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python3 -m research_loops.throughput_report <topic-dir>", file=sys.stderr)
        return 2
    topic_dir = Path(args[0]).resolve()
    if not (topic_dir / "logs").is_dir():
        print(f"not a topic dir (no logs/): {topic_dir}", file=sys.stderr)
        return 2
    conn = None
    dsn = os.environ.get("RESEARCH_GATEWAY_DSN")
    if dsn:
        import psycopg
        conn = psycopg.connect(dsn)
    try:
        print(report(topic_dir, conn))
    finally:
        if conn is not None:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
