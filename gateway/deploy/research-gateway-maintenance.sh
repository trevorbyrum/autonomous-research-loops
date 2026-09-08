#!/usr/bin/env bash
# The gateway's exclusive maintenance window (Phase 8f): stop the service, run every
# registry loader (and the OpenAlex snapshot when RESEARCH_GATEWAY_SNAPSHOT_DIR is
# set), then ALWAYS restore the service's prior state — a failed harvest must never
# leave the gateway down, and "defer while the service is running" alone would starve
# harvest forever. Pair with research-gateway-harvest.timer, or run by hand:
#   bash deploy/research-gateway-maintenance.sh
#
# The loaders refuse while a service answers on the gateway URL (I-1); this script IS
# the sanctioned window that satisfies that guard. Restoration is installed BEFORE the
# stop is attempted (an interruption mid-stop still restores), and a failed restart is
# a loud non-zero exit, never a silent success (pass-1 finding 13).
set -u

UNIT="${RESEARCH_GATEWAY_UNIT:-research-gateway.service}"
PYTHON="${RESEARCH_GATEWAY_PYTHON:-python3}"
LOADERS=(datacite doaj crossref)

was_active=0
restore_rc=0
if systemctl --user is-active --quiet "$UNIT"; then
  was_active=1
fi

restore() {
  if [[ "$was_active" == 1 ]]; then
    echo "maintenance: restoring $UNIT"
    if ! systemctl --user start "$UNIT"; then
      echo "maintenance: FAILED to restart $UNIT — the gateway is DOWN, investigate now" >&2
      restore_rc=3
    fi
  fi
}
trap 'restore' EXIT

if [[ "$was_active" == 1 ]]; then
  echo "maintenance: stopping $UNIT for the harvest window"
  systemctl --user stop "$UNIT"
fi

rc=0
for loader in "${LOADERS[@]}"; do
  echo "maintenance: harvesting $loader"
  if ! "$PYTHON" -m research_gateway.harvest.registries "$loader"; then
    echo "maintenance: $loader FAILED (continuing; its gateway.meta stamp stays at the last success)" >&2
    rc=1
  fi
done
if [[ -n "${RESEARCH_GATEWAY_SNAPSHOT_DIR:-}" ]]; then
  echo "maintenance: loading OpenAlex snapshot from $RESEARCH_GATEWAY_SNAPSHOT_DIR"
  if ! "$PYTHON" -m research_gateway.harvest.openalex_snapshot "$RESEARCH_GATEWAY_SNAPSHOT_DIR"; then
    echo "maintenance: openalex_snapshot FAILED" >&2
    rc=1
  fi
fi

# run restore now so ITS failure decides the exit code (the trap would run after `exit`
# and could not change it); the trap remains armed for the interruption paths above
trap - EXIT
restore
[[ "$restore_rc" != 0 ]] && exit "$restore_rc"
exit "$rc"
