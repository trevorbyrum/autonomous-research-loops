#!/usr/bin/env bash
# progress-signature.sh — deterministic digest of QUALIFYING progress for one topic.
# Usage: progress-signature.sh <topic-dir>
# Used by the durable queue's stall guard: unchanged output across stall_limit
# consecutive successful runs = refinement churn -> needs_attention.
# Counts only named obligation/gap/contradiction/deliverable transitions from
# SEMANTIC-STATE.json. Source volume and prose churn are deliberately excluded.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/semantic-state.py" signature "$1"
