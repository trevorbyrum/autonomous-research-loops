# Retained CLI artifacts

Source: private/evidence/2e1/host-T9/receipts.jsonl. Receipt identity is event + step + at.
- version.txt: result/class-artifact-version at 2026-11-07T17:08:52.863315+00:00; SHA256 af9e26004e1d709f960d6dda62c5bb9415782f12269f0ccce6c8b918d2326d72.
- context.json: result/class-artifact-context at 2026-11-07T17:08:52.910641+00:00; SHA256 377ea9b36f036e659c866e97e4c52b8b6c4f9f567bce7f6f929086171f4dada2.
- builders.jsonl: result/class-artifact-builders at 2026-11-07T17:08:53.081777+00:00; SHA256 b3afe719179b86bb63626e8dbb546ec5cca99129fc92b07502fcf7f171baa986.
- inspect.stderr: result/dedicated-builder-inspect at 2026-11-07T15:20:12.186954+00:00; SHA256 efc09f33c161340d92b67de0d7b3cdf5b7e414f3730315c879d9bfedcacb2353.
- bake.stderr: script_exit/I02 at 2026-11-07T16:40:39.115023+00:00; SHA256 f25a58f3c09eb03f28a89ea17574155bce9efebe3c270fb88aed8fa3dc3ed912.
- Bake argv/exit replay: readonly-print-survey at 2026-11-07T17:04:18.344719+00:00; print stdout is discarded by the runtime preflight and is not replayed.
- Scratch-only argv/exit replay: noop-exercise/class-noop at 2026-11-07T17:21:16.686002+00:00; original logs remain in the cited evidence directory; no application image build or Q run.
- bake-fs-read.stderr: full unmodified resume-20261110T003607Z/i02-build.stderr; script_exit/r4-I02 at 2026-11-10T00:49:58.415252+00:00; SHA256 37e4c342c93a19ed9a27ed0ae0ebb969b60181cbcc241bf4db09242ecc12c256. Replay adds its exact named grant to the older captured argv; it does not claim a new build succeeded.
