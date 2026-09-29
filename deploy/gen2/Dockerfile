# The gen-2 engine image (task 1f): the smallest deployable slice that runs
# supervisor jobs — the engine (router + station supervisor + operator
# listener) with one pinned provider runner baked in.
#
# Trace: docs/gen2/DEPLOYMENT-CONTRACT.md §1 (the `engine` service: baked gen-2
# image), §1.1 (listens on 0.0.0.0:8770 inside its container), §1.2 (its
# healthcheck: GET /v1/health from inside), §2 (baked: engine code, the DDL,
# the schemas, pinned provider CLIs; mounted: config, secrets, auth homes),
# §4 (pinned CLIs baked; each auth home a volume at a fixed path, owned by the
# service user with a stable uid/gid, 0700). docs/gen2/AUTH-DEMO.md records
# why codex and this version.
#
# Build from the repository root: docker build -f deploy/gen2/Dockerfile .
# (deploy/gen2/Dockerfile.dockerignore admits only gen2/, without its tests.)

# ubuntu 24.04: Python 3.12.3 and SQLite 3.45.1, the pair the gen-2 suite and
# its compatibility gate were run on (docs/gen2/ENVIRONMENT.md). By digest.
ARG BASE=ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3

# -- the pinned runner: the public npm tarball of @openai/codex 0.153.2 for
# linux-x64 (Apache-2.0), checked against the registry's published sha512
# integrity, and its static musl binary against its own SHA-256.
FROM ${BASE} AS runner
ARG CODEX_VERSION=0.153.2
ARG CODEX_TARBALL=https://registry.npmjs.org/@openai/codex/-/codex-0.153.2-linux-x64.tgz
ARG CODEX_TARBALL_SHA512=08f50f8459b290a45d21c83088e7cabc528704feb674f7da88ffa9cd0d9b54d01f2d35be8b429ab1dee142bca8c595264cfbf0d21f47c8cd8d82c9d0f402654f
ARG CODEX_BINARY_SHA256=f8786262ebc0fa1337448a2977332beadec66c8d0cda0ce973c7849766d7943c
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    curl -fsSL -o /tmp/codex.tgz "${CODEX_TARBALL}"; \
    echo "${CODEX_TARBALL_SHA512}  /tmp/codex.tgz" | sha512sum -c -; \
    tar -xzf /tmp/codex.tgz -C /tmp package/vendor/x86_64-unknown-linux-musl/bin/codex; \
    install -m 0755 /tmp/package/vendor/x86_64-unknown-linux-musl/bin/codex /codex; \
    echo "${CODEX_BINARY_SHA256}  /codex" | sha256sum -c -; \
    test "$(/codex --version)" = "codex-cli ${CODEX_VERSION}"

# -- the engine
FROM ${BASE}
ARG GEN2_UID=10001
ARG GEN2_GID=10001
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*
# the service user: a stable uid/gid, so every volume it owns stays its own across replacement (§4)
RUN groupadd --gid "${GEN2_GID}" gen2 && useradd --uid "${GEN2_UID}" --gid "${GEN2_GID}" --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin gen2
COPY gen2/requirements.txt /opt/gen2/requirements.txt
RUN python3 -m venv /opt/gen2/venv \
 && /opt/gen2/venv/bin/python -m pip install --no-input --disable-pip-version-check --no-cache-dir --require-hashes --no-deps -r /opt/gen2/requirements.txt \
 && /opt/gen2/venv/bin/python -c "import rfc8785"
COPY --from=runner /codex /usr/local/bin/codex
COPY gen2/ /opt/gen2/src/gen2/
# the mount points, owned by the service user, 0700: a fresh named volume takes them over (§4, §5)
RUN install -d -o "${GEN2_UID}" -g "${GEN2_GID}" -m 0700 /var/lib/gen2/state /auth/codex \
 && /opt/gen2/venv/bin/python -c "import sqlite3, sys; print('python', sys.version.split()[0], 'sqlite', sqlite3.sqlite_version)"
ENV PYTHONPATH=/opt/gen2/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GEN2_OPERATOR_LISTEN=0.0.0.0:8770
LABEL org.opencontainers.image.title="gen2-engine" \
      org.research-loops.gen2.runner="codex 0.153.2" \
      org.research-loops.gen2.runner-sha256="f8786262ebc0fa1337448a2977332beadec66c8d0cda0ce973c7849766d7943c"
USER ${GEN2_UID}:${GEN2_GID}
WORKDIR /var/lib/gen2
EXPOSE 8770
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
  CMD ["/opt/gen2/venv/bin/python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8770/v1/health', timeout=4).status == 200 else 1)"]
ENTRYPOINT ["/opt/gen2/venv/bin/python", "-m", "gen2.app.engine"]
