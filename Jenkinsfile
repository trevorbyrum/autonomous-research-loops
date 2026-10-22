// CI (trevorbyrum/ci-cd): runs gen2's own gate suite in its declared reference
// environment (docs/gen2/ENVIRONMENT.md): Python 3.12.3 + SQLite 3.45.1, the
// ci-py312-noble:2 image on cir (operator confirmed :2 on 2026-10-22; it adds PostgreSQL 16).
// Branch pushes and PR merge jobs run T0 + complete trigger-order + units 1/8.
// This is NOT full acceptance.
// Engine/gateway acceptance modes are separate Make invocations; scheduling
// their shards needs the platform extension described in docs/gen2/CI-RUNNER.md.
standardPipeline(
  image: 'ci-py312-noble:2',
  cleanWorkspace: true,
  recordIdentity: true,
  build: 'make gen2-venv',
  unit: 'make gen2-ci-default',
  junit: 'build/ci-evidence/**/*.xml',
  timeoutMinutes: 50
)
