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

# shellcheck disable=SC2086
"$bin" exec "${model_flag[@]}" ${RESEARCH_LOOP_CODEX_FLAGS:-} "$prompt"
