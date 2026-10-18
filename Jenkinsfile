// CI (trevorbyrum/ci-cd): runs gen2's own gate suite in its declared reference
// environment (docs/gen2/ENVIRONMENT.md): Python 3.12.3 + SQLite 3.45.1, the
// ci-py312-noble:1 image on cir (ci-2 amendment, 2026-10-18).
// Branch pushes and PR merge jobs run T0 + complete trigger-order.
// This is NOT full acceptance.
// Engine/gateway acceptance modes are separate Make invocations; scheduling
// their shards needs the platform extension described in docs/gen2/CI-RUNNER.md.
// Image :2 / gateway DB remain off until the operator deploys and confirms :2.
standardPipeline(
  image: 'ci-py312-noble:1',
  cleanWorkspace: true,
  recordIdentity: true,
  build: 'make gen2-venv',
  unit: 'make gen2-ci-default',
  junit: 'build/ci-evidence/engine-trigger-order-1-of-1/*.xml',
  timeoutMinutes: 50
)
