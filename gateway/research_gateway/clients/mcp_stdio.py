"""The loops' local tool: an MCP server over stdio that forwards to the gateway's HTTP API.

Mounted by a station via --mcp-config exactly like the read-only GitHub tool:
  {"research": {"type": "stdio", "command": "python3", "args": ["-m", "research_gateway.clients.mcp_stdio"]}}
Environment: RESEARCH_GATEWAY_URL (default http://127.0.0.1:8765) and
RESEARCH_GATEWAY_TOKEN or RESEARCH_GATEWAY_TOKEN_FILE. Newline-delimited JSON-RPC 2.0; no third-party deps.

Topic binding (docs/STATION-CONTRACT.md): when the runner exports RESEARCH_TOPIC_*
variables, this dispatcher INJECTS the topic's policy into every call and REJECTS
conflicting arguments — the agent cannot loosen or tighten the operator's licence
posture. When RESEARCH_LOOP_RESEARCH_ACTIVITY names a file, degraded coverage states
and failed calls are appended there for the chassis's saturation gate; when
RESEARCH_LOOP_TOPIC_DIR is set, downloaded bytes are saved under <topic>/downloads/
instead of being reported as a bare byte count.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from .http_client import GatewayClient, from_env

STR, INT, BOOL, OBJ = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "object"}
COMMON = {"domain": {**STR, "description": "finance|market|social|management|ai-ml|software|biomed|other (default other)"},
          "commercial": {**BOOL, "description": "true when the topic's output may be used commercially: deny/unknown sources are skipped"},
          "accept_per_item": {**BOOL, "description": "with commercial=true, also use per-item-licensed sources and keep only allow-listed records"},
          "topic_id": STR}
INSTEAD = ("USE THIS instead of calling source APIs (Crossref, OpenAlex, Semantic Scholar, DOAJ, doi.org, ...) "
           "directly with curl/WebFetch: calls here are budgeted, licence-checked, deduplicated, logged, and "
           "carry the provenance a citation needs. ")
TOOLS = [
    ("research_find", "Search scholarly articles and datasets across the registered sources for a domain. " + INSTEAD +
     "`limit` applies PER SOURCE LANE before dedup. Every lane in the answer reports `coverage` "
     "(searched_ok|searched_empty|not_searched|provider_unavailable|auth_failed) — searched-and-empty is never the same "
     "as unavailable. To continue a search, pass the answer's `next` map back as `cursors`.",
     {"query": STR, "kind": {**STR, "description": "article|dataset|venue|repository (default: articles and datasets)"},
      "limit": INT, "year_from": INT,
      "published_after": {**STR, "description": "ISO date; within 30 days skips the local index"},
      "cursors": {**OBJ, "description": "continuation: the `next` map from a previous research_find answer, unchanged"},
      **COMMON}, ["query"]),
    ("research_resolve", "Look up one identity (doi:, arxiv:, issn:, hf:, openml:, ...) at the registry that owns it, with fallbacks. " + INSTEAD,
     {"identity": STR, **COMMON}, ["identity"]),
    ("research_enrich", "Citations, references, open-access location or full text link for an identity. " + INSTEAD,
     {"identity": STR, "what": {**STR, "description": "citations|references|oa_location|full_text|metadata"}, **COMMON}, ["identity", "what"]),
    ("research_files", "LIST a dataset's or document's files from a registry source: doi:, hf:, kaggle:, "
     "openml:, socrata:, govinfo:, url:. " + INSTEAD + "This tool only lists; each listed file carries a "
     "ready-made `download_request` — pass its arguments straight to research_download.",
     {"target": STR, "params": {**OBJ, "description": "adapter options (never download: that is research_download's job)"}, **COMMON}, ["target"]),
    ("research_download", "DOWNLOAD one file from a registry source (the step after research_fetch listed it). "
     "Same `target` as research_fetch; `params` identify the file, e.g. {\"file_id\": 123} or "
     "{\"revision\": \"main\", \"path\": \"data/train.csv\"}. The bytes are saved into this iteration's "
     "TEMPORARY download directory and the saved path is returned — copy anything you keep into the "
     "topic's own files before the iteration ends; bytes are never dumped into context.",
     {"target": STR, "params": {**OBJ, "description": "file-identifying adapter options, e.g. {\"file_id\": 123}"}, **COMMON}, ["target"]),
    ("research_data", "A statistical series/table from exactly one source, with that source's native params. Key shapes — "
     "fred: series(+start,end,limit); bea: method/dataset/table/frequency/year(+BEA-native keys); "
     "census: dataset+get(+for,in,predicates); bls: series ≤50(+start_year,end_year); "
     "bis: dataflow(+key,start,end); ecb: dataflow+key(+start,end). "
     "Full contract with a working example: research_sources({\"source\": ...}). Params are validated against the "
     "declared contract BEFORE any budget is spent — a bad call returns the contract, not an upstream error. "
     + INSTEAD + "The answer echoes the request (source + params) so the cited table is reproducible.",
     {"source": {**STR, "enum": ["fred", "bea", "census", "bls", "bis", "ecb"]}, "params": OBJ, **COMMON},
     ["source", "params"]),
    ("research_sources", "Describe the registered sources: with no arguments, every source's capabilities, domains and "
     "commercial verdict; with {\"source\": id}, that source's EXACT declared contract — required/optional data params, "
     "a working example, enrichment kinds, schemes. Call this before your first research_data call to a source.",
     {"source": {**STR, "description": "a source id from the no-argument listing, e.g. fred"}}, []),
    ("research_status", "Gateway health, breaker states, budgets, cache and queue counts.", {}, []),
    ("research_job", "Fetch a previously returned pending/async job by its job_id (jobs are visible only to the client that created them).",
     {"job_id": INT}, ["job_id"]),
    ("research_batch", "Run up to 20 independent research_resolve / research_enrich calls in one request. Each entry is "
     "{\"tool\": name, \"arguments\": {...}}; results and failures come back per entry, in order. Prefer this over "
     "sequential single calls for identifier lists.",
     {"calls": {"type": "array", "maxItems": 20,
                "items": {"type": "object", "required": ["tool", "arguments"], "properties": {
                    "tool": {"type": "string", "enum": ["research_resolve", "research_enrich"]},
                    "arguments": {"type": "object"}}},
                "description": "up to 20 entries of {\"tool\": \"research_resolve\"|\"research_enrich\", \"arguments\": {...}}"}},
     ["calls"]),
]


def tool_specs(bound: bool = False) -> list[dict]:
    """The advertised surface. Under a bound topic the operator-owned policy fields are
    NOT advertised — the dispatcher injects them and rejects conflicts anyway, and an
    argument an agent must never set does not belong in its schema (D-31)."""
    specs = []
    for n, d, p, r in TOOLS:
        props = {k: v for k, v in p.items() if not (bound and k in BOUND_HIDDEN)}
        specs.append({"name": n, "description": d, "inputSchema": {"type": "object", "properties": props, "required": r}})
    return specs


REQUEST_TOOLS = {"research_find": "find", "research_resolve": "resolve", "research_enrich": "enrich",
                 "research_files": "fetch", "research_data": "data"}
BOUND_HIDDEN = ("topic_id", "commercial", "accept_per_item")   # operator-owned under a bound topic: enforced
                                                               # internally, not advertised as arguments (D-31)
BATCH_TOOLS = ("research_resolve", "research_enrich")
BATCH_LIMIT = 20

# coverage states that the chassis's saturation gate cares about (STATION-CONTRACT.md §2).
# The activity file records STATE TRANSITIONS in order: a line is written whenever a
# source's coverage differs from the last state this process logged for it, successes
# included — recovery (fail → ok) is a transition and is never deduplicated away, so the
# chassis can apply each source's LAST outcome (pass-1 finding 6).
DEGRADED_COVERAGE = ("not_searched", "provider_unavailable", "auth_failed", "metadata_only")
_LAST_STATE: dict[tuple[str, str, str, str], str] = {}   # (path, source, request_type, subject) -> last coverage written
# keyed per REQUEST (source + type + query/identity), matching the chassis's blocker key:
# a success on an unrelated query must never mask or clear a different request's failure (finding 4)

POLICY_ENV = {"topic_id": "RESEARCH_TOPIC_ID", "commercial": "RESEARCH_TOPIC_COMMERCIAL",
              "accept_per_item": "RESEARCH_TOPIC_ACCEPT_PER_ITEM", "domain": "RESEARCH_TOPIC_DOMAIN"}
ENFORCED = ("topic_id", "commercial", "accept_per_item")   # injected; a conflicting argument is an error
ADVISORY = ("domain",)                                     # injected only when the agent said nothing


class PolicyError(Exception):
    """An agent argument conflicts with the topic's operator-bound research policy."""


def policy_from_env(environ: dict | None = None) -> dict:
    env = os.environ if environ is None else environ
    policy: dict = {}
    for field, var in POLICY_ENV.items():
        raw = env.get(var)
        if raw is None or raw == "":
            continue
        if field in ("commercial", "accept_per_item"):
            policy[field] = raw.strip().lower() in ("1", "true", "yes")
        else:
            policy[field] = raw
    return policy


def apply_policy(args: dict, policy: dict) -> dict:
    """STATION-CONTRACT.md §1: bound fields are injected; a conflicting agent argument is
    rejected in-band, never silently overridden in either direction. Advisory fields fill
    only when absent. No policy (operator CLI, ad-hoc use) = unchanged behaviour."""
    if not policy:
        return args
    out = dict(args)
    for field in ENFORCED:
        if field not in policy:
            continue
        if field in out and out[field] is not None and out[field] != policy[field]:
            raise PolicyError(f"policy-bound: {field} is set by the topic, not the agent")
        out[field] = policy[field]
    for field in ADVISORY:
        if field in policy and out.get(field) is None:
            out[field] = policy[field]
    return out


def _subject_of(mapping: dict) -> str:
    """One subject rule for arguments AND stored job payloads: two different data series
    from one source are two different requests (finding 4)."""
    subject = mapping.get("query") or mapping.get("identity") or mapping.get("target") or ""
    if not subject and mapping.get("source"):
        subject = json.dumps({"source": mapping["source"], "params": mapping.get("params") or {}},
                             sort_keys=True, separators=(",", ":"))
    return subject


def record_activity(path: str | None, tool: str, args: dict, result: dict | None, error: str | None = None) -> None:
    """Append degraded coverage states (and outright failures) for the chassis. Best-effort by
    design: a broken activity file must never break research itself."""
    if not path:
        return
    lines = []
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = (result or {}).get("payload") if isinstance((result or {}).get("payload"), dict) else {}
    if tool == "research_job":
        # gateway-level polling events key by the JOB (stable across poll attempts, so a
        # failed poll's blocker clears when a later poll of the same job answers); the
        # job's inner lanes key by the ORIGINAL request so a direct retry matches too
        request_type = "research_job"
        subject = f"job:{args.get('job_id')}"
        lane_rt = str((result or {}).get("request_type") or payload.get("request_type") or request_type)
        lane_subject = _subject_of(payload) or subject
    else:
        request_type = REQUEST_TOOLS.get(tool, tool)
        subject = _subject_of(args)
        lane_rt, lane_subject = request_type, subject
    observed: list[tuple[str, str, str | None, str, str]] = []
    gateway_trouble = False
    if error is not None:
        observed.append(("gateway", "provider_unavailable", error[:200], request_type, subject))
        gateway_trouble = True
    fact = str((result or {}).get("capability_fact") or "")
    if fact.startswith("gateway"):   # the client answered with a capability-fact dict, not lanes (finding 3)
        observed.append(("gateway", "provider_unavailable", ((result or {}).get("error") or fact)[:200],
                         request_type, subject))
        gateway_trouble = True
    # lanes live at the top level of a direct answer AND nested inside a polled job's
    # stored result — both feed the completion guard, under the ORIGINAL request's key
    lanes = list((result or {}).get("lanes") or [])
    lanes += list(((result or {}).get("result") or {}).get("lanes") or []) if isinstance((result or {}).get("result"), dict) else []
    for lane in lanes:
        if lane.get("source") and lane.get("coverage"):
            observed.append((lane["source"], lane["coverage"], None, lane_rt, lane_subject))
    if isinstance(result, dict) and result.get("status") == "failed":   # a polled job that failed (finding 3)
        observed.append(("gateway", "provider_unavailable", str(result.get("error_class") or "job failed")[:200],
                         request_type, subject))
        gateway_trouble = True
    if not gateway_trouble and result is not None:
        # the gateway itself answered: that clears a gateway blocker for this request —
        # otherwise a transport blip's blocker could never resolve (finding 6)
        observed.append(("gateway", "searched_ok", None, request_type, subject))
    for source, coverage, detail, rt, subj in observed:
        state_key = (path, source, rt, subj)
        if _LAST_STATE.get(state_key) == coverage:
            continue   # unchanged state for this exact request: every TRANSITION (either direction) gets a line
        _LAST_STATE[state_key] = coverage
        line = {"at": at, "source": source, "request_type": rt,
                "coverage": coverage, "query_or_identity": subj}
        if detail:
            line["detail"] = detail
        lines.append(line)
    if not lines:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    except OSError:
        pass


def strip_bytes(out: dict) -> dict:
    """A download's bytes are reported, never dumped into a model context."""
    if isinstance(out.get("content"), (bytes, bytearray)):
        return {**out, "content": None, "content_bytes": len(out["content"])}
    return out


def deliver_content(out: dict, target: str, args: dict, download_dir: str | None) -> dict:
    """With a bound topic, downloaded bytes land in the iteration's TEMPORARY download
    directory (the chassis creates it per iteration and removes it when the iteration
    ends, normal or interrupted — copy what you keep into the topic's ledgers/files);
    otherwise the byte count alone is reported. Names carry the file/revision identity
    from the request and are created exclusively — a second file in the same second can
    never overwrite the first (pass-1 findings 11, 20)."""
    if not isinstance(out.get("content"), (bytes, bytearray)):
        return out
    if not download_dir:
        return strip_bytes(out)
    directory = Path(download_dir)
    directory.mkdir(parents=True, exist_ok=True)
    params = args.get("params") if isinstance(args.get("params"), dict) else {}
    identity_bits = [str(params[k]) for k in ("file_id", "revision", "path", "filename") if params.get(k)]
    stem = "-".join([target or "download"] + identity_bits)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_")[-100:] or "download"
    base = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{safe}"
    for suffix in [""] + [f"-{i}" for i in range(1, 1000)]:
        dest = directory / (base + suffix)
        try:
            with open(dest, "xb") as fh:   # exclusive: an existing file is never overwritten
                fh.write(out["content"])
            break
        except FileExistsError:
            continue
    else:
        return strip_bytes(out)
    return {**out, "content": None, "saved_to": str(dest), "target": target,
            "content_bytes": len(out["content"])}


FILE_SELECTOR_KEYS = ("file_id", "path", "revision", "filename")


def attach_download_requests(out: dict, target: str) -> dict:
    """Every listed file carries the COMPLETE next call (D-31, per the agent-tool principle
    of returning enough context to make the next call correctly): the agent passes
    `download_request.arguments` straight to research_download instead of reassembling
    selectors from record fields."""
    records = out.get("records")
    if not isinstance(records, list):
        return out
    enriched = []
    for rec in records:
        if isinstance(rec, dict):
            selectors = {k: rec[k] for k in FILE_SELECTOR_KEYS if rec.get(k) is not None}
            extra = rec.get("extra") if isinstance(rec.get("extra"), dict) else {}
            selectors.update({k: extra[k] for k in FILE_SELECTOR_KEYS if extra.get(k) is not None and k not in selectors})
            if rec.get("kind") == "file" or selectors:
                rec = {**rec, "download_request": {"tool": "research_download",
                                                   "arguments": {"target": rec.get("identity") or target,
                                                                 "params": selectors}}}
        enriched.append(rec)
    return {**out, "records": enriched}


def call_tool(client: GatewayClient, name: str, args: dict, *, policy: dict | None = None,
              activity: str | None = None, download_dir: str | None = None) -> dict:
    """Tool dispatch for the stdio server: everything goes over HTTP to the gateway."""
    if name == "research_status":
        return client.status()
    if name == "research_job":
        try:
            job = client.job(int(args["job_id"]))
        except Exception as e:
            record_activity(activity, name, args, None, error=f"{type(e).__name__}: {e}")
            raise
        if isinstance(job, dict) and "payload" not in job:
            # a gateway-trouble answer (capability fact, no job payload) is an OUTAGE
            # observation, never a policy question: record it and hand it back —
            # raising a policy error here would hide the outage from the completion
            # guard (closing-round finding 3)
            record_activity(activity, name, args, job)
            return job
        if policy and isinstance(job, dict):
            payload = job.get("payload") or {}
            if policy.get("topic_id") and payload.get("topic_id") != policy["topic_id"]:
                # polling is policy-bound too: a topic never reads results another topic
                # obtained under a different (possibly looser) posture (pass-1 finding 1)
                raise PolicyError("policy-bound: that job belongs to a different topic")
            for field in ("commercial", "accept_per_item"):
                # even the SAME topic's older jobs must match the policy in force NOW —
                # a since-tightened commercial posture never reads personal-mode results
                if field in policy and bool(payload.get(field)) != policy[field]:
                    raise PolicyError(f"policy-bound: that job was created under a different {field} posture")
        record_activity(activity, name, args, job if isinstance(job, dict) else None)
        return job
    if name == "research_batch":
        calls = args.get("calls")
        if not isinstance(calls, list) or not calls:
            raise ValueError("calls must be a non-empty array")
        if len(calls) > BATCH_LIMIT:
            raise ValueError(f"at most {BATCH_LIMIT} calls per batch")
        results = []
        for i, entry in enumerate(calls):
            tool = (entry or {}).get("tool")
            sub_args = (entry or {}).get("arguments") or {}
            if tool not in BATCH_TOOLS:
                results.append({"tool": tool, "error": f"batch entries may only be {' or '.join(BATCH_TOOLS)}"})
                continue
            try:
                results.append({"tool": tool,
                                "result": call_tool(client, tool, sub_args, policy=policy,
                                                    activity=activity, download_dir=download_dir)})
            except Exception as e:  # one bad entry never sinks its neighbours
                results.append({"tool": tool, "error": f"{type(e).__name__}: {e}"})
        return {"results": results}
    if name == "research_download":
        params = dict(args.get("params") or {})
        params["download"] = True
        bound = apply_policy({**args, "params": params}, policy or {})
        try:
            out = client.request("fetch", bound)
        except Exception as e:
            record_activity(activity, "research_files", bound, None, error=f"{type(e).__name__}: {e}")
            raise
        record_activity(activity, "research_files", bound, out)   # same request key as the listing step
        return deliver_content(out, str(bound.get("target") or ""), bound, download_dir)
    if name == "research_sources":
        return client.sources(args.get("source") or None)
    if name not in REQUEST_TOOLS:
        raise LookupError(name)
    if name == "research_files" and (args.get("params") or {}).get("download"):
        raise ValueError("research_fetch lists files; downloading is research_download's job — "
                         "call it with the same target and the file's identifying params")
    bound = apply_policy(args, policy or {})
    try:
        out = client.request(REQUEST_TOOLS[name], bound)
    except Exception as e:
        record_activity(activity, name, bound, None, error=f"{type(e).__name__}: {e}")
        raise
    record_activity(activity, name, bound, out)   # lanes, capability-fact dicts and failed jobs all land here
    if name == "research_files":
        return attach_download_requests(deliver_content(out, str(bound.get("target") or ""), bound, download_dir),
                                        str(bound.get("target") or ""))
    return strip_bytes(out)


def handle(msg: dict, call, specs: list | None = None) -> dict:
    """One JSON-RPC request → result. `call(name, args)` performs the tool; shared by the
    stdio server (HTTP-backed) and the gateway's own MCP endpoint (in-process)."""
    method = msg.get("method")
    if method == "initialize":
        return {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "research-gateway", "version": "0.1"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": specs if specs is not None else tool_specs()}
    if method == "tools/call":
        params = msg.get("params") or {}
        try:
            result = call(params.get("name", ""), params.get("arguments") or {})
            is_error = str(result.get("capability_fact", "")).startswith("gateway_")
            return {"content": [{"type": "text", "text": json.dumps(result, indent=1, default=str)}], "isError": is_error}
        except LookupError as e:
            return {"content": [{"type": "text", "text": f"error: unknown tool {e}"}], "isError": True}
        except Exception as e:  # tool errors go back in-band, never crash the server
            return {"content": [{"type": "text", "text": f"error: {type(e).__name__}: {e}"}], "isError": True}
    raise LookupError(method)


def main() -> int:
    client = from_env()
    policy = policy_from_env()
    activity = os.environ.get("RESEARCH_LOOP_RESEARCH_ACTIVITY")
    # the chassis provides a per-iteration TEMPORARY dir and removes it at iteration end;
    # without one (operator/ad-hoc use) downloads land under the topic's downloads/ as before
    topic_dir = os.environ.get("RESEARCH_LOOP_TOPIC_DIR")
    download_dir = os.environ.get("RESEARCH_LOOP_DOWNLOAD_DIR") or (str(Path(topic_dir) / "downloads") if topic_dir else None)
    call = lambda name, args: call_tool(client, name, args, policy=policy, activity=activity, download_dir=download_dir)  # noqa: E731
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:  # notification
            continue
        try:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg, call, specs=tool_specs(bound=bool(policy)))}
        except LookupError:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"method not found: {msg.get('method')}"}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
