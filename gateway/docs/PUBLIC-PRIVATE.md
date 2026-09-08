# What is public, what is not, and why

This directory is published. It contains the gateway's code, its source
registry (the seed), and its documentation. It deliberately does **not**
contain:

- **Credentials of any kind.** Keys, tokens, client secrets, database
  passwords. The seed names each secret; deployments supply values through
  environment variables or a secrets backend configured outside the tree.
- **Deployment specifics.** Hostnames, addresses, internal service names,
  vault paths. `sources.example.toml` shows the shape; the real
  `sources.local.toml` is gitignored.
- **Data.** No harvested registries, cached payloads, snapshots, result
  sets, or test fixtures above a few kilobytes. The gateway's tables live in
  the deployment's database.
- **Retrieved content that may not be redistributed.** Sources whose terms
  forbid it (see `docs/SOURCES.md`) are cached in memory only and never
  written to disk or exported.
- **Discovery tooling.** The registry harvesters, overlap probes and
  provenance analyses used to *choose* the working set were run privately;
  only their conclusions (the seed and its evidence links) are here.
- **Institution-licensed sources.** Library subscriptions and similar are
  documented nowhere in this tree and are not usable through the gateway.

The check that enforces this runs before every commit on the gateway branch
(`PLAN.md` §12): greps for addresses, tokens and vault references; no data
files; docs equal the registry; no adapter without a registry row; no
placeholders; no file over 1,500 lines.

If you deploy this yourself, the same boundary applies to you: keep your
`sources.local.toml` and secrets out of any fork you publish.
