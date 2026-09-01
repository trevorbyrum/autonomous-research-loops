"""Declarative repo config: scheduling, worker count, agent assignment, and
gap-handling policy, layered as [defaults] + per-[topics.<id>] overrides.

This is convenience over the same primitives the CLI already exposes --
`research-loops config apply` turns this file into `configure_topic()` calls,
it never replaces `add`/`sync` (which still own title/cwd/command). See
docs/operations.md#declarative-config.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .queue import QueueError

GAP_POLICIES = ("review", "auto")
TOPIC_REFRESH_SCHEDULES = ("off", "weekly", "monthly")
TOPIC_REFRESH_MODES = ("light", "continue", "full")


@dataclass(frozen=True)
class TopicSettings:
    repeat_seconds: int | None = None
    max_attempts: int = 5
    stall_limit: int | None = None
    agent_main: str | None = None
    agent_secondary: str | None = None
    gap_policy: str = "review"
    gap_auto_limit: int = 0
    internal_citations: bool = False
    topic_refresh: str = "off"
    topic_refresh_mode: str = "continue"


@dataclass(frozen=True)
class RepoConfig:
    workers: int
    poll_seconds: float
    idle_sleep: float
    defaults: TopicSettings
    topics: dict[str, TopicSettings]

    def for_topic(self, topic_id: str) -> TopicSettings:
        return self.topics.get(topic_id, self.defaults)


def _positive_int(table: dict[str, Any], key: str) -> int | None:
    if key not in table:
        return None
    value = table[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise QueueError(f"{key} must be an integer of at least 1")
    return value


def _non_negative_int(table: dict[str, Any], key: str) -> int | None:
    if key not in table:
        return None
    value = table[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise QueueError(f"{key} must be a non-negative integer")
    return value


def _positive_number(table: dict[str, Any], key: str, default: float) -> float:
    value = table.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise QueueError(f"{key} must be a positive number")
    return float(value)


def _optional_str(table: dict[str, Any], key: str) -> str | None:
    if key not in table:
        return None
    value = table[key]
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise QueueError(f"{key} must be a non-empty string")
    return value


def _optional_bool(table: dict[str, Any], key: str) -> bool | None:
    if key not in table:
        return None
    value = table[key]
    if not isinstance(value, bool):
        raise QueueError(f"{key} must be true or false")
    return value


def _optional_choice(table: dict[str, Any], key: str, choices: tuple[str, ...]) -> str | None:
    if key not in table:
        return None
    value = table[key]
    if value not in choices:
        raise QueueError(f"{key} must be one of {list(choices)}")
    return value


def _settings_from(table: dict[str, Any], base: TopicSettings) -> TopicSettings:
    updates: dict[str, Any] = {}
    repeat_seconds = _positive_int(table, "repeat_seconds")
    if repeat_seconds is not None:
        updates["repeat_seconds"] = repeat_seconds
    max_attempts = _positive_int(table, "max_attempts")
    if max_attempts is not None:
        updates["max_attempts"] = max_attempts
    stall_limit = _positive_int(table, "stall_limit")
    if stall_limit is not None:
        updates["stall_limit"] = stall_limit
    agent_main = _optional_str(table, "agent_main")
    if agent_main is not None:
        updates["agent_main"] = agent_main
    agent_secondary = _optional_str(table, "agent_secondary")
    if agent_secondary is not None:
        updates["agent_secondary"] = agent_secondary
    if "gap_policy" in table:
        value = table["gap_policy"]
        if value not in GAP_POLICIES:
            raise QueueError(f"gap_policy must be one of {list(GAP_POLICIES)}")
        updates["gap_policy"] = value
    gap_auto_limit = _non_negative_int(table, "gap_auto_limit")
    if gap_auto_limit is not None:
        updates["gap_auto_limit"] = gap_auto_limit
    internal_citations = _optional_bool(table, "internal_citations")
    if internal_citations is not None:
        updates["internal_citations"] = internal_citations
    topic_refresh = _optional_choice(table, "topic_refresh", TOPIC_REFRESH_SCHEDULES)
    if topic_refresh is not None:
        updates["topic_refresh"] = topic_refresh
    topic_refresh_mode = _optional_choice(table, "topic_refresh_mode", TOPIC_REFRESH_MODES)
    if topic_refresh_mode is not None:
        updates["topic_refresh_mode"] = topic_refresh_mode
    return replace(base, **updates)


def load_config(path: str | Path) -> RepoConfig:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise QueueError(f"cannot read config {path}: {exc}") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise QueueError(f"invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise QueueError(f"{path} must contain a TOML table")

    workers = _positive_int(data, "workers") or 1
    poll_seconds = _positive_number(data, "poll_seconds", 1.0)
    idle_sleep = _positive_number(data, "idle_sleep", 5.0)

    defaults_table = data.get("defaults", {})
    if not isinstance(defaults_table, dict):
        raise QueueError("[defaults] must be a table")
    defaults = _settings_from(defaults_table, TopicSettings())

    topics_table = data.get("topics", {})
    if not isinstance(topics_table, dict):
        raise QueueError("[topics] must be a table of per-topic tables")
    topics: dict[str, TopicSettings] = {}
    for topic_id, table in topics_table.items():
        if not isinstance(table, dict):
            raise QueueError(f"[topics.{topic_id}] must be a table")
        topics[topic_id] = _settings_from(table, defaults)

    return RepoConfig(
        workers=workers,
        poll_seconds=poll_seconds,
        idle_sleep=idle_sleep,
        defaults=defaults,
        topics=topics,
    )
