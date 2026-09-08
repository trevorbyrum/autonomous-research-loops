"""Phase 9·0 throughput report: one topic's iterations measured, not guessed.

    RESEARCH_GATEWAY_DSN=... python3 -m research_loops.throughput_report topics/<id>

Correlation uses the tracing the stdio client sends as headers and the gateway stores
OUTSIDE request identity (D-33): iteration stamp, batch entry, topic, and the payload
params fingerprint. Every measured quantity is kept SEPARATE — summed provider service
time, broker wait, queue wait, and the retrieval window are different numbers and none
of them is a concurrency speedup claim. A missing observation prints "unknown", never
0: zero traced rows does not establish zero activity, and a missing usage file does not
establish free work. Repeat lookups are grouped by subject AND params fingerprint, so
pagination and parameter changes are not conflated with true repeats; their purpose is
reported as unobserved rather than labeled (independent verification is never "waste").
The same report re-runs after every lever; the context section captures what is
knowable AT REPORT TIME and says plainly what was not recorded per iteration.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

UNKNOWN = "unknown"


def _dt(stamp: str) -> datetime | None:
    """20260908T012345Z → aware datetime."""
    try:
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iterations(topic_dir: Path) -> list[str]:
    return sorted(p.name[len("result-"):-len(".json")] for p in (topic_dir / "logs").glob("result-*.json"))


def _window(topic_dir: Path, stamp: str, next_stamp: str | None) -> tuple[datetime | None, datetime | None, bool]:
    """Iteration [start, end). End is, in preference order: the phase log's `end` marker
    (the runner writes it), the result file's mtime (written at iteration end), or the
    next iteration's start (approximate: it attributes idle time between iterations)."""
    start = _dt(stamp)
    phase_path = topic_dir / "logs" / f"phases-{stamp}.log"
    if phase_path.exists():
        for line in reversed(phase_path.read_text(errors="replace").splitlines()):
            parts = line.strip().split()
            if len(parts) == 2 and parts[1] == "end":
                end = _iso(parts[0])
                if end:
                    return start, end, False
    result_path = topic_dir / "logs" / f"result-{stamp}.json"
    if result_path.exists():
        return start, datetime.fromtimestamp(result_path.stat().st_mtime, tz=timezone.utc), False
    if next_stamp:
        return start, _dt(next_stamp), True
    return start, None, True


def _phases(topic_dir: Path, stamp: str) -> tuple[dict[str, float], list[str]]:
    """Marker lines '<iso> <phase>' → seconds per phase. The runner's `end` marker closes
    the final phase; a final phase with no closing boundary is reported unmeasured, never
    silently dropped or guessed."""
    path = topic_dir / "logs" / f"phases-{stamp}.log"
    if not path.exists():
        return {}, []
    marks: list[tuple[datetime, str]] = []
    for line in path.read_text(errors="replace").splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        t = _iso(parts[0])
        if t:
            marks.append((t, parts[1]))
    out: dict[str, float] = {}
    unmeasured: list[str] = []
    for (t0, name), (t1, _nxt) in zip(marks, marks[1:]):
        if name == "end":
            continue
        out[name] = out.get(name, 0.0) + (t1 - t0).total_seconds()
    if marks and marks[-1][1] != "end":
        unmeasured.append(marks[-1][1])
    return out, unmeasured


def _delegate_tokens(topic_dir: Path, start: datetime | None, end: datetime | None):
    """Sum of delegate usage events inside [start, end). Missing file → unknown (the
    wrapper records on success only, so absence of the FILE is absence of observation)."""
    path = topic_dir / "logs" / "delegate-usage.jsonl"
    if not path.exists() or start is None:
        return UNKNOWN
    total = 0
    for line in path.read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        ts = _iso(str(e.get("ts") or ""))
        if ts is None:
            continue
        if ts >= start and (end is None or ts < end):
            v = e.get("total_tokens")
            if isinstance(v, (int, float)):
                total += int(v)
    return total


def _primary_usage(topic_dir: Path, stamp: str):
    """(total_tokens, cost_usd, models) from the runner's per-iteration usage capture,
    or unknowns when it was not recorded."""
    path = topic_dir / "logs" / f"iteration-{stamp}-usage.json"
    if not path.exists():
        return UNKNOWN, UNKNOWN, UNKNOWN
    try:
        u = json.loads(path.read_text())
    except ValueError:
        return UNKNOWN, UNKNOWN, UNKNOWN
    tokens = u.get("total_tokens") if isinstance(u.get("total_tokens"), (int, float)) else UNKNOWN
    models = u.get("models") if isinstance(u.get("models"), dict) else {}
    costs = [m.get("cost_usd") for m in models.values() if isinstance(m, dict) and isinstance(m.get("cost_usd"), (int, float))]
    cost = round(sum(costs), 4) if costs else UNKNOWN
    return tokens, cost, (u.get("model") or UNKNOWN)


def _result(topic_dir: Path, stamp: str) -> dict:
    try:
        return json.loads((topic_dir / "logs" / f"result-{stamp}.json").read_text())
    except (OSError, ValueError):
        return {}


def _calls(conn, stamp: str, topic_id: str) -> dict:
    """Gateway-side spans for one iteration. Rows with a topic that names ANOTHER topic
    are excluded; NULL-topic rows predate topic tracing and are counted with a caveat
    (two topics that started in the same second are indistinguishable there)."""
    with conn.cursor() as cur:
        base = ("FROM gateway.calls WHERE iteration = %s AND failure_class <> 'attempt' "
                "AND (topic IS NULL OR topic = %s)")
        cur.execute(f"SELECT count(*), count(*) FILTER (WHERE cache_hit), "
                    f"count(*) FILTER (WHERE source_id = 'coalesce'), "
                    f"coalesce(sum(latency_ms),0), coalesce(sum(wait_ms),0), count(batch_entry), "
                    f"count(*) FILTER (WHERE topic IS NULL), "
                    f"min(at), max(at + make_interval(secs => coalesce(latency_ms,0)/1000.0)) {base}",
                    (stamp, topic_id))
        n, cache_hits, coalesced, provider_ms, wait_ms, batched, untopic, first, last = cur.fetchone()
        cur.execute(
            "SELECT count(*), coalesce(sum(reps) - count(*), 0) FROM ("
            "  SELECT count(*) AS reps FROM gateway.calls "
            "  WHERE iteration = %s AND failure_class <> 'attempt' AND (topic IS NULL OR topic = %s) "
            "  AND source_id NOT IN ('cache', 'coalesce') "
            "  GROUP BY request_type, source_id, coalesce(query, identity), coalesce(params_fp, '-') "
            "  HAVING count(*) > 1) r", (stamp, topic_id))
        groups, excess = cur.fetchone()
        cur.execute("SELECT coalesce(sum(extract(epoch FROM (started_at - created_at))), 0), count(*) "
                    "FROM gateway.jobs WHERE iteration = %s AND started_at IS NOT NULL", (stamp,))
        queue_wait_s, jobs_n = cur.fetchone()
    conn.commit()
    return {"calls": int(n), "cache_hits": int(cache_hits), "coalesced": int(coalesced),
            "provider_s": round(int(provider_ms) / 1000.0, 1), "wait_s": round(int(wait_ms) / 1000.0, 1),
            "queue_wait_s": round(float(queue_wait_s), 1), "jobs": int(jobs_n), "batched": int(batched),
            "untopic_rows": int(untopic),
            "gateway_window_s": round((last - first).total_seconds(), 1) if first and last else None,
            "repeat_groups": int(groups), "repeat_excess": int(excess)}


def _report_time_context(root: Path, topic_id: str) -> list[str]:
    """What is knowable AT REPORT TIME. This accompanies the numbers; it does not
    substitute for per-iteration context, which (except each iteration's own model
    usage capture) was not recorded and is reported unknown."""
    lines = ["## Context (captured at report time)", ""]
    try:
        q = json.loads((root / "state" / "queue.json").read_text())
        workers = {name: {k: cfg.get(k) for k in ("agent_main", "agent_model", "interval_seconds")}
                   for name, cfg in (q.get("worker_agents") or {}).items()}
        lines.append(f"- worker configuration now: `{json.dumps(workers, sort_keys=True)}`")
        it = next((i for i in q.get("items", []) if i.get("id") == topic_id), None)
        if it:
            lines.append(f"- topic now: status={it.get('status')} repeat_seconds={it.get('repeat_seconds')} "
                         f"secondary=`{it.get('agent_secondary')}`")
    except Exception:
        lines.append("- worker configuration: unknown (state/queue.json unreadable)")
    lines += ["- per-iteration model usage: in each row's tokens/cost columns (recorded by the runner)",
              "- per-iteration cache state and provider health: unknown — not recorded at capture "
              "time; only report-time /v1/status can be consulted, and it does not describe the past",
              ""]
    return lines


def report(topic_dir: Path, conn) -> str:
    topic_id = topic_dir.name
    stamps = _iterations(topic_dir)
    lines = [f"# Throughput report — {topic_id} ({datetime.now(timezone.utc).isoformat(timespec='seconds')})", ""]
    lines += _report_time_context(topic_dir.parent.parent, topic_id)
    lines += ["Separate spans per iteration: `provider_s` (summed provider service time), `wait_s` "
              "(summed broker waits, redirect hops included), `queue_wait_s` (job queue delay), and "
              "`window_s` (iteration start → runner-recorded end; a trailing `~` means the end "
              "boundary was approximated by the NEXT iteration's start, which can attribute idle "
              "time). `gateway window` is the hull of traced calls — it includes non-retrieval gaps "
              "and is not an elapsed-overlap measurement. Repeats are `groups/excess calls` grouped "
              "by subject AND params fingerprint (pagination and parameter changes are separate "
              "groups); their purpose is not observed, so none is labeled waste or verification.", "",
              "| iteration | calls | cache | coal | provider_s | wait_s | queue_s | window_s | gw window | batched | repeats | outcome | qual | src+ | verified+ | pending | primary tok | cost $ | delegate tok | phases |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    totals = {"qual": 0, "src": 0, "verified": 0, "primary": 0, "delegate": 0, "cost": 0.0,
              "primary_known": False, "delegate_known": False, "cost_known": False}
    span_start = span_end = None
    for i, stamp in enumerate(stamps):
        nxt = stamps[i + 1] if i + 1 < len(stamps) else None
        start, end, approx = _window(topic_dir, stamp, nxt)
        if start and (span_start is None or start < span_start):
            span_start = start
        if end and (span_end is None or end > span_end):
            span_end = end
        calls = _calls(conn, stamp, topic_id) if conn is not None else {}
        res = _result(topic_dir, stamp)
        phases, unmeasured = _phases(topic_dir, stamp)
        phase_txt = " ".join(f"{k}:{int(v)}s" for k, v in phases.items())
        phase_txt += ("".join(f" {u}:unmeasured" for u in unmeasured)) or ""
        phase_txt = phase_txt.strip() or UNKNOWN
        window_s = (f"{(end - start).total_seconds():.0f}{'~' if approx else ''}"
                    if start and end else UNKNOWN)
        tokens, cost, _models = _primary_usage(topic_dir, stamp)
        delegate = _delegate_tokens(topic_dir, start, end)
        no_rows = calls and calls["calls"] == 0
        repeats = (f"{calls['repeat_groups']}/{calls['repeat_excess']}"
                   if calls and calls["repeat_groups"] else ("-" if calls else UNKNOWN))
        qual = res.get("signature_changed")
        if qual:
            totals["qual"] += 1
        if isinstance(res.get("sources_cited"), int):
            totals["src"] += res["sources_cited"]
        if isinstance(res.get("verified_added"), int):
            totals["verified"] += res["verified_added"]
        if isinstance(tokens, int):
            totals["primary"] += tokens
            totals["primary_known"] = True
        if isinstance(cost, float):
            totals["cost"] += cost
            totals["cost_known"] = True
        if isinstance(delegate, int):
            totals["delegate"] += delegate
            totals["delegate_known"] = True
        lines.append("| {stamp} | {calls} | {cache} | {coal} | {prov} | {wait} | {queue} | {window} | {gww} | {batched} | {reps} | {outcome} | {qual} | {src} | {ver} | {pend} | {ptok} | {cost} | {dtok} | {phases} |".format(
            stamp=stamp,
            calls="no traced rows" if no_rows else calls.get("calls", UNKNOWN),
            cache=calls.get("cache_hits", UNKNOWN) if not no_rows else "-",
            coal=calls.get("coalesced", UNKNOWN) if not no_rows else "-",
            prov=calls.get("provider_s", UNKNOWN) if not no_rows else "-",
            wait=calls.get("wait_s", UNKNOWN) if not no_rows else "-",
            queue=calls.get("queue_wait_s", UNKNOWN) if not no_rows else "-",
            window=window_s,
            gww=(calls.get("gateway_window_s") if calls.get("gateway_window_s") is not None else UNKNOWN) if calls else UNKNOWN,
            batched=calls.get("batched", UNKNOWN) if not no_rows else "-",
            reps=repeats,
            outcome=res.get("outcome", UNKNOWN),
            qual=qual if qual is not None else UNKNOWN,
            src=res.get("sources_cited", UNKNOWN),
            ver=res.get("verified_added", UNKNOWN),
            pend=res.get("pending_count") if res.get("pending_count") is not None else UNKNOWN,
            ptok=tokens, cost=cost, dtok=delegate,
            phases=phase_txt))
    lines += ["", "## Rates and coverage", ""]
    if span_start and span_end and span_end > span_start:
        hours = (span_end - span_start).total_seconds() / 3600.0
        lines.append(f"- report span {span_start.isoformat(timespec='seconds')} → "
                     f"{span_end.isoformat(timespec='seconds')} ({hours:.1f} h wall clock, idle "
                     "between iterations INCLUDED — this is a portfolio rate, not a busy rate)")
        lines.append(f"- qualifying iterations/hour: {totals['qual'] / hours:.2f}; "
                     f"sources cited/hour: {totals['src'] / hours:.2f}; "
                     f"independently verified additions/hour: {totals['verified'] / hours:.2f} "
                     "(verified counts exist only for iterations after the runner began recording them)")
        lines.append(f"- token cost: primary {totals['primary'] if totals['primary_known'] else UNKNOWN}"
                     f" (+ delegate {totals['delegate'] if totals['delegate_known'] else UNKNOWN})"
                     f"; CLI-priced primary cost ${round(totals['cost'], 2) if totals['cost_known'] else UNKNOWN}"
                     " — totals cover only iterations whose usage was recorded; the rest are unknown, not zero")
    lines.append("- rejection/rework counts: unknown (not observed by any current instrument)")
    lines.append("- pending-evidence AGE: unknown (pending refs carry no timestamps); count is per-row above")
    lines.append("- iterations shown as `no traced rows` are indistinguishable between 'made no gateway "
                 "calls' and 'ran before tracing/deployment' — the report asserts neither. Rows with a "
                 "NULL topic predate topic tracing: if two topics started in the same second they are "
                 "indistinguishable there (newer rows carry the topic and are filtered exactly).")
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
