#!/usr/bin/env bash
# hermes.sh — runner adapter for the Hermes CLI, for anyone who already uses it.
#
# Usage (never called directly by a human — run-topic.sh invokes it):
#   hermes.sh <topic_dir> <prompt_file>
#
# Configuration:
#   RESEARCH_LOOP_HERMES_BIN   hermes binary/wrapper name (default: hermes)
#   RESEARCH_LOOP_PROFILE      Hermes profile name (default: default), read by
#                              run-topic.sh's environment export, interpreted here
set -euo pipefail

topic_dir="$1"
prompt_file="$2"
bin="${RESEARCH_LOOP_HERMES_BIN:-hermes}"
profile="${RESEARCH_LOOP_PROFILE:-default}"

command -v "$bin" >/dev/null 2>&1 || {
  echo "configuration error: '$bin' not found on PATH" >&2
  exit 78
}

cd "$topic_dir"
prompt="$(cat "$prompt_file")"

usage_args=()
[[ -n "${RESEARCH_LOOP_USAGE_FILE:-}" ]] && usage_args=(--usage-file "$RESEARCH_LOOP_USAGE_FILE")
extra_args=()
if [[ -n "${RESEARCH_LOOP_HERMES_ARGV_JSON:-}" ]]; then
  mapfile -d '' extra_args < <(python3 - "$RESEARCH_LOOP_HERMES_ARGV_JSON" <<'PY'
import json, sys
value = json.loads(sys.argv[1])
if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
    raise SystemExit("managed Hermes argv must be a JSON string array")
for arg in value:
    sys.stdout.buffer.write(arg.encode() + b"\0")
PY
)
fi

"$bin" -p "$profile" -z "$prompt" "${usage_args[@]}" "${extra_args[@]}"
