// CI (trevorbyrum/ci-cd): runs gen2's own gate suite in its declared reference
// environment (docs/gen2/ENVIRONMENT.md): Python 3.12.3 + SQLite 3.45.1, the
// ci-py312-noble:2 image on cir (adds PostgreSQL 16 for the gateway suite).
// Measured 2026-10-04 on image :1: ~32 min under CI limits.
// cleanWorkspace/recordIdentity: CI design §3.1 (clean runs, recorded library,
// image and commit identity). The gateway suite joins once its Python
// dependencies have a hash-locked install (CI design §7 step 2).
standardPipeline(
  image: 'ci-py312-noble:2',
  cleanWorkspace: true,
  recordIdentity: true,
  lint: 'make gen2-boundaries gen2-size',
  build: 'make gen2-venv',
  unit: 'make gen2-check',
  timeoutMinutes: 50
)
