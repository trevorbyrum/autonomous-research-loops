FROM docker.io/library/python@sha256:1148dbb014615300fa7e713b2f94f550c0d1c69780c0805f84f093ceee34dd0b AS base
RUN test -x /bin/bash && groupadd --gid 10001 gen2 && useradd --uid 10001 --gid 10001 --no-create-home gen2
RUN test ! -e /etc/codex && test ! -e /root/.codex && test ! -e /usr/local/etc/codex
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/gen2:/opt/gateway
HEALTHCHECK NONE

FROM base AS runner
COPY --from=approved-inputs --chmod=0555 codex /usr/local/bin/codex
COPY --chmod=0555 deploy/gen2/live/runner.py /opt/live/runner.py
COPY --chmod=0555 deploy/gen2/live/q_net.py /opt/live/q_net.py
RUN echo 'f8786262ebc0fa1337448a2977332beadec66c8d0cda0ce973c7849766d7943c  /usr/local/bin/codex' | sha256sum -c -
RUN test "$(/usr/local/bin/codex --version)" = 'codex-cli 0.153.2' && test ! -e /work && test ! -e /auth/codex
USER 10001:10001
ENTRYPOINT ["python3", "/opt/live/runner.py"]

FROM base AS engine
COPY gen2/ /opt/gen2/gen2/
COPY --from=approved-inputs --chmod=0555 docker /usr/bin/docker
COPY gen2/requirements.txt /opt/locks/engine.txt
COPY --from=approved-inputs wheels/rfc8785-0.1.4-py3-none-any.whl /opt/wheels/
RUN python3 -m pip install --disable-pip-version-check --no-input --require-hashes --no-deps --only-binary=:all: --no-cache-dir \
    --no-index --find-links=/opt/wheels -r /opt/locks/engine.txt
RUN echo 'adbc67ecdc2cd2d350c01a5964a205bd81470b485aba1fb90c2f559de9e4584f  /usr/bin/docker' | sha256sum -c -
RUN /usr/bin/docker --version && python3 -m gen2.store.compat
COPY deploy/gen2/live/initialize.py deploy/gen2/live/tool_probe.py deploy/gen2/live/runner-config.toml /opt/live/
COPY --from=approved-inputs models.json /opt/live/models.json
RUN echo '62d809889367324c104b13a4881e115286085d5674ffa77ab790b48c63002d10  /opt/live/models.json' | sha256sum -c -
USER 10001:10001
ENTRYPOINT ["python3", "-m", "gen2.app.engine"]

FROM base AS gateway
COPY gateway/research_gateway/ /opt/gateway/research_gateway/
COPY gateway/requirements-ci.txt /opt/locks/gateway.txt
COPY --from=approved-inputs wheels/psycopg-3.1.18-py3-none-any.whl \
    wheels/psycopg_binary-3.1.18-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl \
    wheels/typing_extensions-4.10.0-py3-none-any.whl /opt/wheels/
RUN python3 -m pip install --disable-pip-version-check --no-input --require-hashes --no-deps --only-binary=:all: --no-cache-dir \
    --no-index --find-links=/opt/wheels -r /opt/locks/gateway.txt
COPY deploy/gen2/live/q_2e1.py /opt/gateway/research_gateway/adapters/q_2e1.py
COPY deploy/gen2/live/q-source.toml deploy/gen2/live/initialize.py /opt/live/
RUN python3 /opt/live/initialize.py build-registry
RUN python3 -m research_gateway.registry.load --dry-run --check-adapters
USER 10001:10001
ENTRYPOINT ["python3", "-m", "research_gateway.api.http"]

FROM base AS fixture
COPY deploy/gen2/live/fixture.py deploy/gen2/live/q_net.py /opt/live/
USER 10001:10001
ENTRYPOINT ["python3", "/opt/live/fixture.py"]
