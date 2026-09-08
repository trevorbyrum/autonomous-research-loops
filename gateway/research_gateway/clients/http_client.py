"""The one HTTP client the CLI, the stdio MCP server and the homelab adapter share.

A gateway that cannot be reached is reported as `capability_fact: gateway_unavailable`
(PLAN.md Phase 5 check) — never as an exception the caller has to guess about.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8765"


def settings_from_env(environ: dict | None = None) -> tuple[str, str | None]:
    env = os.environ if environ is None else environ
    url = env.get("RESEARCH_GATEWAY_URL", DEFAULT_URL).rstrip("/")
    token = env.get("RESEARCH_GATEWAY_TOKEN")
    if not token and env.get("RESEARCH_GATEWAY_TOKEN_FILE"):
        try:
            with open(env["RESEARCH_GATEWAY_TOKEN_FILE"]) as f:
                token = f.read().strip()
        except OSError:
            token = None
    return url, token


class GatewayClient:
    def __init__(self, url: str = DEFAULT_URL, token: str | None = None, timeout: float = 130.0,
                 iteration: str | None = None, topic: str | None = None):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout
        self.iteration = iteration      # 9·0 tracing: rides a HEADER, never the payload (D-33)
        self.topic = topic              # caller's topic id — same rule (two topics can share a second)
        self.batch_entry: int | None = None

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json", "User-Agent": "research-gateway-client/0.1"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.iteration:
            headers["X-Research-Iteration"] = self.iteration
        if self.topic:
            headers["X-Research-Topic"] = self.topic
        if self.batch_entry is not None:
            headers["X-Research-Batch-Entry"] = str(self.batch_entry)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw, ctype = resp.read(), resp.headers.get("Content-Type", "")
                envelope = resp.headers.get("X-Research-Gateway") == "result"
        except urllib.error.HTTPError as e:
            raw, ctype = e.read(), e.headers.get("Content-Type", "")
            detail = {}
            if "application/json" in ctype:
                try:
                    detail = json.loads(raw)
                except ValueError:
                    detail = {}
            if not isinstance(detail, dict):
                detail = {}
            # non-JSON error bodies are never relayed: a model context gets the status, not raw bytes
            return {"capability_fact": f"gateway_error_{e.code}", "status": e.code, **detail}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {"capability_fact": "gateway_unavailable", "error": f"{type(e).__name__}: {e}", "url": self.url}
        if envelope and "application/json" in ctype:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        # anything else — including a downloaded file that happens to BE JSON — stays bytes
        return {"content": raw, "content_type": ctype}

    def request(self, request_type: str, payload: dict) -> dict:
        return self._call("POST", f"/v1/{request_type}", payload)

    def job(self, job_id: int) -> dict:
        return self._call("GET", f"/v1/jobs/{int(job_id)}")

    def sources(self, source: str | None = None) -> dict:
        return self._call("GET", f"/v1/sources/{source}" if source else "/v1/sources")

    def status(self) -> dict:
        return self._call("GET", "/v1/status")

    def health(self) -> dict:
        return self._call("GET", "/v1/health")


def from_env(environ: dict | None = None) -> GatewayClient:
    import os
    url, token = settings_from_env(environ)
    env = os.environ if environ is None else environ
    stamp = (env.get("RESEARCH_LOOP_RESEARCH_ACTIVITY") or "")
    iteration = None
    if "research-activity-" in stamp:   # the chassis names the file with the iteration stamp
        iteration = stamp.rsplit("research-activity-", 1)[1].removesuffix(".jsonl") or None
    topic_dir = env.get("RESEARCH_LOOP_TOPIC_DIR") or ""
    topic = topic_dir.rstrip("/").rsplit("/", 1)[-1] or None if topic_dir else None
    return GatewayClient(url, token, iteration=iteration, topic=topic)
