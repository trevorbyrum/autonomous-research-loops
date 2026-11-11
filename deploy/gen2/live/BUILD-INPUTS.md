I02 uses exactly four wheels in D11 `/home/trevor/.local/share/gen2-2e1/storage/build-inputs/wheels`:

- `rfc8785-0.1.4-py3-none-any.whl`
- `psycopg-3.1.18-py3-none-any.whl`
- `psycopg_binary-3.1.18-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`
- `typing_extensions-4.10.0-py3-none-any.whl`

Fetch only these official-index artifacts; receipt URLs, bytes and SHA256s, verifying against `gen2/requirements.txt` and `gateway/requirements-ci.txt` before use. Retain regular host-owned files, no extras, and the H17 512MiB input bound. Bake runs application commands with networking disabled; pip installs only local wheels with the existing hash/dependency locks. A successful native I02 rebuild is required before repinning images or claiming dependent qualification.

Compose is one retained input: `/usr/libexec/docker/cli-plugins/docker-compose`, version `5.6.0`, 32,663,526 bytes, SHA-256 `40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a`. Use `build.compose_command` for A07–A09 so its byte pin and the dedicated socket selector apply to every invocation. Retain the same bytes at D11/docker-compose before use. It is a host CLI plugin, outside the application image build context.
