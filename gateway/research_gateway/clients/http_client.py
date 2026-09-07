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
    def __init__(self, url: str = DEFAULT_URL, token: str | None = None, timeout: float = 130.0):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json", "User-Agent": "research-gateway-client/0.1"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw, ctype = resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                detail = json.loads(raw)
            except ValueError:
                detail = {"error": raw.decode("utf-8", "replace")[:500]}
            return {"capability_fact": f"gateway_error_{e.code}", "status": e.code, **detail}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {"capability_fact": "gateway_unavailable", "error": f"{type(e).__name__}: {e}", "url": self.url}
        if "application/json" in ctype:
            return json.loads(raw)
        return {"content": raw, "content_type": ctype}

    def request(self, request_type: str, payload: dict) -> dict:
        return self._call("POST", f"/v1/{request_type}", payload)

    def job(self, job_id: int) -> dict:
        return self._call("GET", f"/v1/jobs/{int(job_id)}")

    def status(self) -> dict:
        return self._call("GET", "/v1/status")

    def health(self) -> dict:
        return self._call("GET", "/v1/health")


def from_env(environ: dict | None = None) -> GatewayClient:
    url, token = settings_from_env(environ)
    return GatewayClient(url, token)
