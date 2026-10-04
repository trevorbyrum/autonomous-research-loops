// CI (trevorbyrum/ci-cd): runs gen2's own gate suite in its declared reference
// environment (docs/gen2/ENVIRONMENT.md): Python 3.12.3 + SQLite 3.45.1, the
// ci-py312-noble image on cir. Measured 2026-10-04: ~32 min under CI limits.
standardPipeline(
  image: 'ci-py312-noble:1',
  lint: 'make gen2-boundaries gen2-size',
  build: 'make gen2-venv',
  unit: 'make gen2-check',
  timeoutMinutes: 50
)
