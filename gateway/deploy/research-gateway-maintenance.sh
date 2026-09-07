#!/usr/bin/env bash
# The gateway's exclusive maintenance window (Phase 8f): stop the service, run every
# registry loader, then ALWAYS restore the service's prior state — a failed harvest
# must never leave the gateway down, and "defer while the service is running" alone
# would starve harvest forever. Pair with research-gateway-harvest.timer replacing its
# direct ExecStart lines, or run by hand:  bash deploy/research-gateway-maintenance.sh
#
# The loaders refuse while a service answers on the gateway URL (I-1); this script IS
# the sanctioned window that satisfies that guard. Each loader takes the advisory lock,
# so they run strictly one at a time; a completed loader stamps gateway.meta and shows
# up under /v1/status "harvest".
set -u

UNIT="${RESEARCH_GATEWAY_UNIT:-research-gateway.service}"
PYTHON="${RESEARCH_GATEWAY_PYTHON:-python3}"
LOADERS=(datacite doaj crossref)

was_active=0
if systemctl --user is-active --quiet "$UNIT"; then
  was_active=1
  echo "maintenance: stopping $UNIT for the harvest window"
  systemctl --user stop "$UNIT"
fi

restore() {
  if [[ "$was_active" == 1 ]]; then
    echo "maintenance: restoring $UNIT"
    systemctl --user start "$UNIT" || echo "maintenance: FAILED to restart $UNIT — investigate now" >&2
  fi
}
trap restore EXIT

rc=0
for loader in "${LOADERS[@]}"; do
  echo "maintenance: harvesting $loader"
  if ! "$PYTHON" -m research_gateway.harvest.registries "$loader"; then
    echo "maintenance: $loader FAILED (continuing; its gateway.meta stamp stays at the last success)" >&2
    rc=1
  fi
done
exit "$rc"
