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
- bare-host.stderr-line: exact native diagnostic-line excerpt from resume-20261110T081906Z/i02-build.stderr, bytes 16494..16620 (end exclusive); source SHA256 1ed20dffe423a51f92e0dce23d3829e4449597e1d927e501d43391bad7864082; script_exit/r6-I02 at 2026-11-10T08:20:06.816741+00:00. Only the Python ValueError prefix is excluded; full 360-line combined build log remains in private evidence.
- nginx-version.stderr: complete unmodified stderr of pinned nginx `-V`; result/173-nginx-compile-options at 2026-11-11T09:44:00.750291+00:00; SHA256 e02223c01ed50d5dff5731e7b910a91b5c02577de28aba6de1b67528f68e20b6. Network none, root read-only; no server started.
- nginx-temp.stderr-line: exact first `[emerg]` line from result/173-live-stop-logs-relay at 2026-11-11T09:38:16.576092+00:00; full source SHA256 b302168d20affe83fda09f4ba2a463c16a553bc3e17a515531c86a15771be0fa; excerpt SHA256 e2108709790c4ecf23ba17c930b8e9bc2d50c92ee64ba137551030262b48984a. Original complete logs remain in host-T9/native-pr173-20261111T093245Z.
