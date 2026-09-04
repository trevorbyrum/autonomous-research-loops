#!/usr/bin/env bash
# claude.sh — runner adapter for Anthropic's Claude Code CLI (`claude`).
#
# Usage (never called directly by a human — run-topic.sh invokes it):
#   claude.sh <topic_dir> <prompt_file>
#
# Configuration (all optional, sane defaults):
#   RESEARCH_LOOP_CLAUDE_BIN     claude binary/wrapper name (default: claude)
#   RESEARCH_LOOP_CLAUDE_MODEL   model id (default: claude-sonnet-5)
#   RESEARCH_LOOP_CLAUDE_FLAGS   extra flags appended verbatim (e.g. permission mode)
#
# Requires the caller's environment to already have Claude Code authenticated
# (CLAUDE_CODE_OAUTH_TOKEN or an interactive login done once beforehand). This adapter
# does not manage credentials — that's environment/deployment setup, not the chassis's job.
set -euo pipefail

topic_dir="$1"
prompt_file="$2"
bin="${RESEARCH_LOOP_CLAUDE_BIN:-claude}"
model="${RESEARCH_LOOP_CLAUDE_MODEL:-claude-sonnet-5}"

command -v "$bin" >/dev/null 2>&1 || {
  echo "configuration error: '$bin' not found on PATH" >&2
  exit 78
}

cd "$topic_dir"
prompt="$(cat "$prompt_file")"

# A nonzero claude exit must still surface its output: the queue's failure
# classifier regex-scans the log tail to distinguish subscription-limit /
# rate-limit / outage failures (each with different backoff), and claude
# prints those reasons to stdout/stderr as it exits. Under plain `set -e`
# the assignment would abort the adapter before the echo, losing exactly
# that text -- so capture the exit code explicitly instead.
rc=0
# shellcheck disable=SC2086
output="$("$bin" -p "$prompt" --model "$model" --output-format json ${RESEARCH_LOOP_CLAUDE_FLAGS:-} 2>&1)" || rc=$?
echo "$output"

if [[ -n "${RESEARCH_LOOP_USAGE_FILE:-}" ]]; then
  # Claude Code's --output-format json envelope carries usage under .usage; extract
  # best-effort so the queue's coverage-aware dashboard has real numbers when present.
  # Never fail the iteration if this extraction doesn't work — usage is optional.
  printf '%s' "$output" | python3 -c '
import json, sys
try:
    envelope = json.loads(sys.stdin.read())
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
usage = envelope.get("usage") if isinstance(envelope, dict) else None
if not isinstance(usage, dict):
    sys.exit(0)
# The -p JSON envelope has no top-level "model"; the models that actually
# ran live as the keys of "modelUsage" (primary + any subagent models).
model_usage = envelope.get("modelUsage")
models = sorted(model_usage.keys()) if isinstance(model_usage, dict) and model_usage else []
duration_ms = envelope.get("duration_ms")
num_turns = envelope.get("num_turns")
out = {
    "provider": "anthropic",
    "model": ", ".join(models) or None,
    "api_calls": num_turns if isinstance(num_turns, int) and num_turns >= 0 else None,
    "duration_seconds": (
        round(duration_ms / 1000, 1)
        if isinstance(duration_ms, (int, float)) and duration_ms >= 0
        else None
    ),
    "total_tokens": sum(
        v for k, v in usage.items()
        if isinstance(v, (int, float)) and "token" in k
    ) or None,
}
# Per-model breakdown (operator request 2026-09-04): modelUsage carries exact
# per-model token fields AND the CLI-priced costUSD -- record them so quota
# trajectory can be regressed against real per-model spend, never a blended mix.
if isinstance(model_usage, dict):
    FIELDS = (
        ("input_tokens", "inputTokens"), ("output_tokens", "outputTokens"),
        ("cache_read_tokens", "cacheReadInputTokens"),
        ("cache_creation_tokens", "cacheCreationInputTokens"),
        ("thinking_tokens", "thinkingTokens"), ("cost_usd", "costUSD"),
    )
    models_out = {}
    for name, fields in model_usage.items():
        if not isinstance(fields, dict):
            continue
        rec = {dst: fields[src] for dst, src in FIELDS
               if isinstance(fields.get(src), (int, float))}
        if rec:
            models_out[name] = rec
    if models_out:
        out["models"] = models_out
with open(sys.argv[1], "w") as fh:
    json.dump(out, fh)
' "$RESEARCH_LOOP_USAGE_FILE" 2>/dev/null || true
fi

exit "$rc"
