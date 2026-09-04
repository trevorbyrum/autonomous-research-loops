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

# Capture the transcript (still streamed to stdout for run-topic.sh's log) so
# the usage record the queue's dashboard reads can be written: `codex exec`
# prints a trailing "tokens used" / "<N>" pair; model is whatever we asked for.
tmp_out="$(mktemp)"
set +e
# shellcheck disable=SC2086
"$bin" exec "${model_flag[@]}" ${RESEARCH_LOOP_CODEX_FLAGS:-} "$prompt" | tee "$tmp_out"
rc=${PIPESTATUS[0]}
set -e
if [[ -n "${RESEARCH_LOOP_USAGE_FILE:-}" ]]; then
  python3 - "$tmp_out" "$RESEARCH_LOOP_USAGE_FILE" "${RESEARCH_LOOP_CODEX_MODEL:-}" <<'PY' 2>/dev/null || true
import json, re, sys
text = open(sys.argv[1], errors="replace").read()
tokens = None
for m in re.finditer(r"tokens used\s*\n\s*([0-9][0-9,]*)", text):
    tokens = int(m.group(1).replace(",", ""))  # last occurrence wins
out = {"provider": "openai", "model": sys.argv[3] or None, "total_tokens": tokens}
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump(out, fh)
PY
fi
rm -f "$tmp_out"
exit "$rc"
