"""Small Unix-socket client shared by managed CLI/MCP and topic-state tools."""
from __future__ import annotations

import json
import socket
from typing import Any

MAX_MESSAGE_BYTES = 1024 * 1024


class ControllerClientError(RuntimeError):
    def __init__(self, message: str, *, error: dict[str, Any] | None = None):
        self.error = error or {"code": "CONTROLLER_UNAVAILABLE", "message": message}
        super().__init__(json.dumps(self.error, sort_keys=True))

    def as_dict(self) -> dict[str, Any]:
        return dict(self.error)


def call(socket_path: str, method: str, params: dict[str, Any], *, token: str | None = None,
         timeout: float = 60) -> Any:
    payload = {"method": method, "params": params}
    if token is not None:
        payload["token"] = token
    raw = json.dumps(payload, ensure_ascii=False).encode() + b"\n"
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ControllerClientError("request exceeds the controller message limit")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(socket_path)
            connection.sendall(raw)
            stream = connection.makefile("rb")
            response = stream.readline(MAX_MESSAGE_BYTES + 1)
        if len(response) > MAX_MESSAGE_BYTES or not response.endswith(b"\n"):
            raise ControllerClientError("invalid or oversized controller response")
        value = json.loads(response)
    except (OSError, ValueError) as exc:
        raise ControllerClientError(f"controller unavailable or invalid response: {exc}") from exc
    if not value.get("ok"):
        error = value.get("error") or {}
        raise ControllerClientError(error.get("message", "request rejected"), error=error)
    return value["result"]
