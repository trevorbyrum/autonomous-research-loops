#!/usr/bin/env bash
# codex.sh — runner adapter for OpenAI's Codex CLI (`codex exec`).
#
# Usage (never called directly by a human — run-topic.sh invokes it):
#   codex.sh <topic_dir> <prompt_file>
#
# Configuration (all optional):
#   RESEARCH_LOOP_CODEX_BIN     codex binary name (default: codex)
#   RESEARCH_LOOP_CODEX_MODEL   model id, passed via -m if set
#   RESEARCH_LOOP_CODEX_FLAGS   extra flags appended verbatim
#
# Requires the caller's environment to already have Codex CLI authenticated.
set -euo pipefail

topic_dir="$1"
prompt_file="$2"
bin="${RESEARCH_LOOP_CODEX_BIN:-codex}"

command -v "$bin" >/dev/null 2>&1 || {
  echo "configuration error: '$bin' not found on PATH" >&2
  exit 78
}

cd "$topic_dir"
prompt="$(cat "$prompt_file")"

model_flag=()
[[ -n "${RESEARCH_LOOP_CODEX_MODEL:-}" ]] && model_flag=(-m "$RESEARCH_LOOP_CODEX_MODEL")

# OpenAI's documented headless pattern: `--json` turns stdout into a JSONL
# event stream (turn.completed carries token usage), `-o` captures the
# agent's final message, and stdin is explicitly closed -- codex exec reads
# extra instructions from a piped stdin and blocks forever on one that never
# closes ("Reading additional input from stdin..."). Sandbox/approval flags
# come from RESEARCH_LOOP_CODEX_FLAGS (the worker's agent_flags profile).
events="$(mktemp)"
last_message="$(mktemp)"
set +e
# shellcheck disable=SC2086
"$bin" exec "${model_flag[@]}" --json -o "$last_message" ${RESEARCH_LOOP_CODEX_FLAGS:-} "$prompt" \
  </dev/null | tee "$events"
rc=${PIPESTATUS[0]}
set -e
if [[ -s "$last_message" ]]; then
  printf '\n--- final message ---\n'
  cat "$last_message"
  printf '\n'
fi
if [[ -n "${RESEARCH_LOOP_USAGE_FILE:-}" ]]; then
  python3 - "$events" "$RESEARCH_LOOP_USAGE_FILE" "${RESEARCH_LOOP_CODEX_MODEL:-}" <<'PY' 2>/dev/null || true
import json, sys
total, turns, seen = 0, 0, False
detail = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
          "reasoning_output_tokens": 0}
for line in open(sys.argv[1], errors="replace"):
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get("type") != "turn.completed":
        continue
    turns += 1
    usage = event.get("usage") or {}
    for key in ("input_tokens", "output_tokens", "reasoning_output_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            total += int(value)
            seen = True
    # Cached input is billed at ~a tenth of fresh input: keep the split so
    # cost-weighted quota regression can price the iteration correctly.
    for key in detail:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            detail[key] += int(value)
out = {
    "provider": "openai",
    "model": sys.argv[3] or None,
    "api_calls": turns or None,
    "total_tokens": total if seen else None,
}
if seen and sys.argv[3]:
    out["models"] = {sys.argv[3]: detail}
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump(out, fh)
PY
fi
rm -f "$events" "$last_message"
exit "$rc"
