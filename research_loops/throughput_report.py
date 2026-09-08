"""Phase 9·0 throughput report: one topic's iterations measured, not guessed.

    RESEARCH_GATEWAY_DSN=... python3 -m research_loops.throughput_report topics/<id>

Correlation uses the tracing the stdio client sends as headers and the gateway stores
OUTSIDE request identity (D-33): iteration stamp, batch entry, topic, payload params
fingerprint, and per-caller `request` span rows. Every measured quantity stays
SEPARATE — summed provider service time, broker wait, queue wait, per-caller elapsed
union, and the call hull are different numbers and none is a concurrency speedup
claim. Missing observations PROPAGATE: a partially observed quantity prints as a
lower bound with its unobserved count, an unmeasured one prints "unknown", and rates
carry their coverage (N of M iterations observed) — zero requires evidence of zero.
Repeats group by subject AND params fingerprint over hop-0 rows only (transport hops,
retries within one dispatch, and null-subject exchanges are not repeated lookups);
their purpose is unobserved, so none is labeled waste or verification.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

UNKNOWN = "unknown"
NON_DISPATCH = ("cache", "coalesce", "request")   # telemetry/association rows, not provider dispatches


def _dt(stamp: str) -> datetime | None:
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
    """Iteration [start, end). End preference: the runner's phase-log `end` marker, the
    result file's mtime (written at iteration end), then the next iteration's start
    (approximate: it can attribute idle time between iterations)."""
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
    """'<iso> <phase>' markers → seconds per phase; the runner's `end` marker closes the
    final phase; an unclosed final phase is reported unmeasured, never guessed."""
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


def _delegate_tokens(topic_dir: Path, stamp: str, start: datetime | None, end: datetime | None):
    """(known_sum, unobserved_count, coverage) for one iteration's delegation.

    Attribution is by FILE ORDER between iteration markers (the runner appends a marker
    per iteration; the file is append-only under flock), so same-second boundary events
    are never lost to timestamp truncation. Coverage is EVIDENCE: 'complete' only inside
    a marked segment (marked + zero launches = true zero; a launch without a usage line
    is an unobserved outcome). Without a marker, timestamps attribute events but a
    success-only history proves a SUBTOTAL, never coverage."""
    path = topic_dir / "logs" / "delegate-usage.jsonl"
    if not path.exists() or start is None:
        return UNKNOWN, 0, "none"
    events = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    marker_idx = [i for i, e in enumerate(events) if e.get("event") == "iteration"]
    seg = None
    for pos, i in enumerate(marker_idx):
        if events[i].get("stamp") == stamp:
            j = marker_idx[pos + 1] if pos + 1 < len(marker_idx) else len(events)
            seg = events[i + 1:j]
            break
    if seg is not None:
        window, coverage = seg, "complete"
    else:
        window = []
        for e in events:
            if e.get("event") == "iteration":
                continue
            t = _iso(str(e.get("ts") or ""))
            if t is not None and t >= start and (end is None or t <= end):
                window.append(e)
        if not window:
            return UNKNOWN, 0, "none"
        coverage = "partial"   # timestamp-attributed history: subtotal evidence only
    total, usage_events, unobserved, launches = 0, 0, 0, 0
    for e in window:
        if e.get("event") == "launch":
            launches += 1
            continue
        usage_events += 1
        v = e.get("total_tokens")
        if isinstance(v, (int, float)):
            total += int(v)
        else:
            unobserved += 1
    unobserved += max(0, launches - usage_events)
    return total, unobserved, coverage


def _primary_usage(topic_dir: Path, stamp: str):
    """(total_tokens, cost, cost_partial, model) from the runner's per-iteration capture.
    A model whose cost is not numeric makes the summed cost a lower bound (partial)."""
    path = topic_dir / "logs" / f"iteration-{stamp}-usage.json"
    if not path.exists():
        return UNKNOWN, UNKNOWN, False, UNKNOWN
    try:
        u = json.loads(path.read_text())
    except ValueError:
        return UNKNOWN, UNKNOWN, False, UNKNOWN
    tokens = u.get("total_tokens") if isinstance(u.get("total_tokens"), (int, float)) else UNKNOWN
    models = u.get("models") if isinstance(u.get("models"), dict) else {}
    numeric = [m.get("cost_usd") for m in models.values()
               if isinstance(m, dict) and isinstance(m.get("cost_usd"), (int, float))]
    partial = bool(models) and len(numeric) < len(models)
    cost = round(sum(numeric), 4) if numeric else UNKNOWN
    return tokens, cost, partial, (u.get("model") or UNKNOWN)


def _result(topic_dir: Path, stamp: str) -> dict:
    try:
        return json.loads((topic_dir / "logs" / f"result-{stamp}.json").read_text())
    except (OSError, ValueError):
        return {}


def _union_seconds(spans: list[tuple[datetime, float]]) -> float:
    """Union of [at, at+latency] intervals — the per-caller ELAPSED measurement, distinct
    from every summed span."""
    ivals = sorted((at, at.timestamp() + max(0.0, ms / 1000.0)) for at, ms in spans)
    total, cur_start, cur_end = 0.0, None, None
    for at, end_ts in ivals:
        s = at.timestamp()
        if cur_end is None or s > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = s, end_ts
        else:
            cur_end = max(cur_end, end_ts)
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def _calls(conn, stamp: str, topic_id: str) -> dict:
    """Gateway-side spans for one iteration. Attribution: rows naming ANOTHER topic are
    excluded; rows with no topic attribution are counted with a caveat (they are either
    pre-tracing or from an untraced caller — the report asserts neither)."""
    with conn.cursor() as cur:
        # meanings kept separate (round-3 finding): a DISPATCH completed at a provider
        # (attempt and refused rows are not dispatches); a REFUSAL never reached the
        # provider (its credit figure was never charged); CREDITS were charged at acquire,
        # so crashed still-'attempt' rows keep theirs while refusals contribute none.
        tele = "('cache','coalesce','request')"
        # a BROKER refusal never dispatched and never charged: failure_class 'refused' AND
        # status IS NULL. An HTTP 400/405/422 also classifies 'refused' but WAS a charged
        # provider dispatch (it has a status) - it stays in calls/credits/repeats.
        broker_refusal = "(failure_class = 'refused' AND status IS NULL)"
        dispatch = f"source_id NOT IN {tele} AND failure_class <> 'attempt' AND NOT {broker_refusal}"
        base = ("FROM gateway.calls WHERE iteration = %s "
                "AND (topic IS NULL OR topic = %s)")
        cur.execute(f"SELECT count(*) FILTER (WHERE {dispatch}), "
                    f"count(*) FILTER (WHERE cache_hit), "
                    f"count(*) FILTER (WHERE source_id = 'coalesce'), "
                    f"count(*) FILTER (WHERE source_id NOT IN {tele} AND {broker_refusal}), "
                    f"coalesce(sum(latency_ms) FILTER (WHERE {dispatch}), 0), "
                    f"coalesce(sum(wait_ms) FILTER (WHERE failure_class <> 'attempt'), 0), "
                    f"count(*) FILTER (WHERE {dispatch} AND wait_ms IS NULL), "
                    f"count(batch_entry) FILTER (WHERE failure_class <> 'attempt'), "
                    f"count(*) FILTER (WHERE topic IS NULL), "
                    f"coalesce(sum(credits) FILTER (WHERE source_id NOT IN {tele} "
                    f"                              AND NOT {broker_refusal}), 0), "
                    f"count(*) FILTER (WHERE source_id NOT IN {tele} AND failure_class = 'attempt'), "
                    f"min(at) FILTER (WHERE {dispatch}), "
                    f"max(at + make_interval(secs => coalesce(latency_ms,0)/1000.0)) "
                    f"  FILTER (WHERE {dispatch}) {base}",
                    (stamp, topic_id))
        (n, cache_hits, coalesced, refused, provider_ms, wait_ms, wait_unmeasured, batched, untopic,
         credits, attempts_open, first, last) = cur.fetchone()
        cur.execute(
            "SELECT count(*), coalesce(sum(reps) - count(*), 0) FROM ("
            "  SELECT count(*) AS reps FROM gateway.calls "
            "  WHERE iteration = %s AND failure_class NOT IN ('attempt', 'refused') "
            "  AND (topic IS NULL OR topic = %s) "
            "  AND source_id NOT IN ('cache', 'coalesce', 'request') "
            "  AND coalesce(hop, 0) = 0 AND coalesce(query, identity) IS NOT NULL "
            "  GROUP BY request_type, source_id, coalesce(query, identity), coalesce(params_fp, '-') "
            "  HAVING count(*) > 1) r", (stamp, topic_id))
        groups, excess = cur.fetchone()
        # queue delay: same topic discipline as calls (finding: two topics in one second)
        cur.execute("SELECT coalesce(sum(extract(epoch FROM (started_at - created_at))), 0), count(*) "
                    "FROM gateway.jobs WHERE iteration = %s AND started_at IS NOT NULL "
                    "AND (coalesce(topic_id, topic) IS NULL OR coalesce(topic_id, topic) = %s)",
                    (stamp, topic_id))
        queue_wait_s, jobs_n = cur.fetchone()
        # per-caller elapsed union from `request` span rows (backdated to request start)
        cur.execute("SELECT at, latency_ms FROM gateway.calls "
                    "WHERE iteration = %s AND source_id = 'request' "
                    "AND (topic IS NULL OR topic = %s)", (stamp, topic_id))
        spans = [(at, float(ms or 0)) for at, ms in cur.fetchall()]
    conn.commit()
    return {"calls": int(n), "cache_hits": int(cache_hits), "coalesced": int(coalesced),
            "refused": int(refused), "attempts_open": int(attempts_open),
            "provider_s": round(int(provider_ms) / 1000.0, 1),
            "wait_s": round(int(wait_ms) / 1000.0, 1), "wait_unmeasured": int(wait_unmeasured),
            "queue_wait_s": round(float(queue_wait_s), 1), "jobs": int(jobs_n),
            "batched": int(batched), "untopic_rows": int(untopic),
            "credits": round(float(credits), 2),
            "elapsed_union_s": round(_union_seconds(spans), 1) if spans else UNKNOWN,
            "gateway_window_s": round((last - first).total_seconds(), 1) if first and last else None,
            "repeat_groups": int(groups), "repeat_excess": int(excess)}


def _result_mtime(topic_dir: Path, stamp: str) -> datetime | None:
    p = topic_dir / "logs" / f"result-{stamp}.json"
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _pending_ages(stamps: list[str], topic_dir: Path) -> dict[str, datetime]:
    """First-seen time per pending ref across recorded results. The observation instant
    is the RESULT-WRITE time (refs are read at iteration END): an end-of-iteration ref
    cannot be aged from the iteration's start, so ages are honest lower bounds between
    two snapshot instants."""
    first_seen: dict[str, datetime] = {}
    for stamp in stamps:
        res = _result(topic_dir, stamp)
        refs = res.get("pending_refs")
        at = _result_mtime(topic_dir, stamp)
        if not isinstance(refs, list) or at is None:
            continue
        for ref in refs:
            first_seen.setdefault(str(ref), at)
    return first_seen


def _report_time_context(root: Path, topic_id: str) -> list[str]:
    lines = ["## Context", "",
             "Captured at report time (mutable state; it does not describe past iterations):"]
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
    lines += ["", "Recorded per iteration (from when each instrument began): model identity and token "
              "cost (runner usage capture), worker + delegate command, gateway health incl. open "
              "breakers, in-memory cache aggregates and lane-concurrency knobs (`gw health` column), "
              "verified/flagged ledger deltas, pending refs. Iterations predating an instrument show "
              "unknown for it. Batch concurrency is a station-process setting not yet stamped per "
              "iteration; worker-profile history beyond the recorded fields remains unknown.", ""]
    return lines


def _fmt_bound(known, unobserved: int):
    if known == UNKNOWN:
        return UNKNOWN
    return f"≥{known} (+{unobserved} unobserved)" if unobserved else str(known)


def report(topic_dir: Path, conn) -> str:
    topic_id = topic_dir.name
    stamps = _iterations(topic_dir)
    lines = [f"# Throughput report — {topic_id} ({datetime.now(timezone.utc).isoformat(timespec='seconds')})", ""]
    lines += _report_time_context(topic_dir.parent.parent, topic_id)
    lines += ["Separate spans: `provider_s` (summed provider service), `wait_s` (summed broker waits; "
              "`(k unmeasured)` marks dispatch rows without a wait observation), `queue_s` (job queue "
              "delay, topic-filtered), `elapsed_s` (UNION of per-caller request spans — the elapsed "
              "measurement), `window_s` (iteration start → runner-recorded end; `~` = approximated by "
              "next start), `gw window` (call hull; includes non-retrieval gaps, not an overlap "
              "measure). `ver±/rej+` are ACCEPTED-verified and flagged ledger deltas (a flagged block "
              "never counts as verified). Repeats: `groups/excess` over hop-0, subject+fingerprint "
              "groups; purpose unobserved. `refused` counts broker refusals (never dispatched, never "
              "charged — excluded from calls, repeats, and credits; credits include crashed "
              "attempts whose acquire DID charge).", "",
              "| iteration | calls | cache | coal | refused | provider_s | wait_s | queue_s | elapsed_s | window_s | gw window | batched | credits | repeats | outcome | qual | src± | ver± | rej+ | pending | worker | model | primary tok | cost $ | delegate tok | gw health | phases |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    totals = {"qual": 0, "qual_obs": 0, "src": 0, "src_obs": 0, "ver": 0, "ver_obs": 0,
              "rej": 0, "primary": 0, "primary_obs": 0, "delegate": 0, "delegate_obs": 0,
              "delegate_partial": 0, "cost": 0.0, "cost_obs": 0, "cost_partial": 0}
    n_iter = len(stamps)
    pending_first = _pending_ages(stamps, topic_dir)
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
        phase_txt = (" ".join(f"{k}:{int(v)}s" for k, v in phases.items())
                     + "".join(f" {u}:unmeasured" for u in unmeasured)).strip() or UNKNOWN
        window_s = f"{(end - start).total_seconds():.0f}{'~' if approx else ''}" if start and end else UNKNOWN
        tokens, cost, cost_partial, model = _primary_usage(topic_dir, stamp)
        delegate, delegate_unobs, delegate_cov = _delegate_tokens(topic_dir, stamp, start, end)
        spans_present = bool(calls) and calls.get("elapsed_union_s") != UNKNOWN
        no_rows = (calls and calls["calls"] == 0 and calls["cache_hits"] == 0
                   and calls["coalesced"] == 0 and calls.get("refused", 0) == 0
                   and calls.get("attempts_open", 0) == 0 and not spans_present)
        qual = res.get("signature_changed")
        if qual is not None:
            totals["qual_obs"] += 1
            totals["qual"] += bool(qual)
        if isinstance(res.get("sources_cited"), int):
            totals["src_obs"] += 1
            totals["src"] += res["sources_cited"]
        if isinstance(res.get("verified_added"), int) and "flagged_added" in res:
            totals["ver_obs"] += 1
            totals["ver"] += res["verified_added"]
            totals["rej"] += res.get("flagged_added") or 0
        if isinstance(tokens, int):
            totals["primary"] += tokens
            totals["primary_obs"] += 1
        if isinstance(cost, float):
            totals["cost"] += cost
            totals["cost_obs"] += 1
            totals["cost_partial"] += bool(cost_partial)
        if isinstance(delegate, int):
            totals["delegate"] += delegate
            totals["delegate_obs"] += 1
            totals["delegate_partial"] += bool(delegate_unobs) or delegate_cov != "complete"
        pending = res.get("pending_count")
        if pending is not None and isinstance(res.get("pending_refs"), list) and res["pending_refs"]:
            observed_at = _result_mtime(topic_dir, stamp)
            oldest = min((pending_first.get(str(r)) for r in res["pending_refs"] if str(r) in pending_first),
                         default=None)
            if oldest and observed_at and observed_at > oldest:
                pending = f"{pending} (oldest ≥{(observed_at - oldest).total_seconds() / 3600.0:.1f}h)"
        gh = res.get("gateway_health")
        gh_txt = (f"ok={gh.get('ok')} wrk={gh.get('workers_alive')} brk={gh.get('breakers_open')} "
                  f"cmem={gh.get('cache_memory')} crec={gh.get('cache_records_estimate')} "
                  f"lanes={gh.get('lane_concurrency')}/{gh.get('lane_total')}"
                  if isinstance(gh, dict) else UNKNOWN)
        wait_txt = UNKNOWN if not calls else (
            f"{calls['wait_s']}" + (f" ({calls['wait_unmeasured']} unmeasured)" if calls["wait_unmeasured"] else ""))
        lines.append("| {stamp} | {calls} | {cache} | {coal} | {refused} | {prov} | {wait} | {queue} | {elapsed} | {window} | {gww} | {batched} | {credits} | {reps} | {outcome} | {qual} | {src} | {ver} | {rej} | {pend} | {worker} | {model} | {ptok} | {cost} | {dtok} | {gh} | {phases} |".format(
            stamp=stamp,
            calls="no traced rows" if no_rows else calls.get("calls", UNKNOWN),
            cache="-" if no_rows else calls.get("cache_hits", UNKNOWN),
            coal="-" if no_rows else calls.get("coalesced", UNKNOWN),
            refused="-" if no_rows else calls.get("refused", UNKNOWN),
            prov="-" if no_rows else calls.get("provider_s", UNKNOWN),
            wait="-" if no_rows else wait_txt,
            queue="-" if no_rows else calls.get("queue_wait_s", UNKNOWN),
            elapsed=calls.get("elapsed_union_s", UNKNOWN) if calls else UNKNOWN,
            window=window_s,
            gww=(calls.get("gateway_window_s") if calls.get("gateway_window_s") is not None else UNKNOWN) if calls else UNKNOWN,
            batched="-" if no_rows else calls.get("batched", UNKNOWN),
            credits="-" if no_rows else calls.get("credits", UNKNOWN),
            reps=(f"{calls['repeat_groups']}/{calls['repeat_excess']}"
                  if calls and calls.get("repeat_groups") else ("-" if calls else UNKNOWN)),
            outcome=res.get("outcome", UNKNOWN),
            qual=qual if qual is not None else UNKNOWN,
            src=res.get("sources_cited", UNKNOWN),
            ver=(res.get("verified_added") if isinstance(res.get("verified_added"), int)
                 and "flagged_added" in res else UNKNOWN),
            rej=(res.get("flagged_added") if "flagged_added" in res else UNKNOWN),
            pend=pending if pending is not None else UNKNOWN,
            worker=(f"{res.get('worker')} ({(res.get('agent_secondary') or '?').rsplit('/', 1)[-1][:40]})"
                    if res.get("worker") else UNKNOWN),
            model=model,
            ptok=tokens, cost=(f"≥{cost} (partial)" if cost_partial and isinstance(cost, float) else cost),
            dtok=(_fmt_bound(delegate, delegate_unobs) if delegate_cov == "complete"
                  else (UNKNOWN if delegate == UNKNOWN else f"≥{delegate} (coverage unknown)")),
            gh=gh_txt, phases=phase_txt))
    lines += ["", "## Rates and coverage", ""]
    if span_start and span_end and span_end > span_start and n_iter:
        hours = (span_end - span_start).total_seconds() / 3600.0
        lines.append(f"- report span {span_start.isoformat(timespec='seconds')} → "
                     f"{span_end.isoformat(timespec='seconds')} ({hours:.1f} h wall clock, idle "
                     "between iterations INCLUDED — a portfolio rate, not a busy rate)")

        def rate(total, obs, label, signed=False):
            if obs == 0:
                return f"- {label}: unknown (0 of {n_iter} iterations observed)"
            if obs == n_iter:
                return f"- {label}: {total / hours:.2f}/h over the full span"
            if signed:
                # a signed net over PARTIAL coverage bounds nothing: an unobserved
                # iteration could be negative (revocations), so no rate is claimed
                return (f"- {label}: observed net {total} over {obs} of {n_iter} iterations; "
                        "full net rate unknown (signed metric under partial coverage)")
            return (f"- {label}: {total / hours:.2f}/h over the full span — LOWER BOUND: only "
                    f"{obs} of {n_iter} iterations observed, the rest are unknown, not zero")
        lines.append(rate(totals["qual"], totals["qual_obs"], "qualifying iterations"))
        lines.append(rate(totals["src"], totals["src_obs"], "sources cited (net)", signed=True))
        lines.append(rate(totals["ver"], totals["ver_obs"], "ACCEPTED independently verified additions (net)", signed=True))
        if totals["ver_obs"]:
            lines.append(f"- flagged/rejected additions over the same observed iterations: {totals['rej']}")
        for key, label in (("primary", "primary tokens"), ("delegate", "delegate tokens")):
            obs = totals[f"{key}_obs"]
            partial = totals.get(f"{key}_partial", 0)
            if obs == 0:
                lines.append(f"- {label}: unknown (0 of {n_iter} iterations observed)")
            else:
                tag = "" if obs == n_iter and not partial else \
                    f" — LOWER BOUND ({obs} of {n_iter} iterations observed" + \
                    (f"; {partial} with partially observed events" if partial else "") + ")"
                lines.append(f"- {label}: {totals[key]}{tag}")
        if totals["cost_obs"]:
            tag = "" if totals["cost_obs"] == n_iter and not totals["cost_partial"] else \
                f" — LOWER BOUND ({totals['cost_obs']} of {n_iter} iterations observed" + \
                (f"; {totals['cost_partial']} partial" if totals["cost_partial"] else "") + ")"
            lines.append(f"- CLI-priced primary cost: ${round(totals['cost'], 2)}{tag}")
        else:
            lines.append(f"- CLI-priced primary cost: unknown (0 of {n_iter} iterations observed)")
    lines.append("- provider credits per iteration: `credits` column (from the call log)")
    lines.append("- rejection signal: flagged-ledger delta (`rej+`); other rework is not observed and stays unknown")
    lines.append("- pending-evidence age: measurable only from refs recorded by the runner (first-seen basis); "
                 "older backlog age is unknown")
    lines.append("- `no traced rows` is indistinguishable between 'made no gateway calls' and 'untraced "
                 "caller or pre-tracing deployment' — the report asserts neither. Rows without topic "
                 "attribution are pre-topic-tracing OR from an untraced caller; if two topics started in "
                 "the same second they are indistinguishable there (attributed rows are filtered exactly).")
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
