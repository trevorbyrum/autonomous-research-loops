#!/usr/bin/env bash
# generic.sh — the "any CLI" escape hatch. Proves the Agent Runner contract isn't
# secretly shaped around one harness: this adapter just pipes the prompt to whatever
# command RESEARCH_LOOP_RUNNER_CMD names, on its stdin, from the topic directory.
#
# Usage (never called directly by a human — run-topic.sh invokes it):
#   generic.sh <topic_dir> <prompt_file>
#
# Required: RESEARCH_LOOP_RUNNER_CMD, a shell command that reads a prompt on stdin
# and does the work (e.g. a one-off script wrapping any provider's API or CLI).
# This adapter does not write a usage file; RESEARCH_LOOP_USAGE_FILE stays absent
# unless RESEARCH_LOOP_RUNNER_CMD writes it itself.
set -euo pipefail

topic_dir="$1"
prompt_file="$2"

if [[ -z "${RESEARCH_LOOP_RUNNER_CMD:-}" ]]; then
  echo "configuration error: RESEARCH_LOOP_RUNNER_CMD is not set (generic.sh needs a command to run)" >&2
  exit 78
fi

cd "$topic_dir"
# shellcheck disable=SC2086
eval "$RESEARCH_LOOP_RUNNER_CMD" <"$prompt_file"
