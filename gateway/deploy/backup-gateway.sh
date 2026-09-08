#!/usr/bin/env bash
# Dump the gateway schema (Phase 8f). Custom format so pg_restore can filter; dated
# files, newest kept alongside prior ones — pruning is the operator's call.
#   RESEARCH_GATEWAY_DSN=... bash deploy/backup-gateway.sh [output-dir]
# pg_dump must be >= the server's major version; when the local client is older, run
# it inside the database host's own container instead and redirect locally, e.g.:
#   ssh <host> "docker exec <pg-container> pg_dump -U postgres -d <db> --schema=gateway -Fc" > out.dump
# Restore rehearsal (do this at least once per deployment): create a scratch database,
# `pg_restore -d <scratch>` the dump, compare table counts against live, drop the scratch.
set -euo pipefail

DSN="${RESEARCH_GATEWAY_DSN:?RESEARCH_GATEWAY_DSN is not set}"
OUT_DIR="${1:-private/backups}"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/gateway-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --dbname="$DSN" --schema=gateway --format=custom --file="$OUT"
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
