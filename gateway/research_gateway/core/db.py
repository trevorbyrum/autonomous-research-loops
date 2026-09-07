"""Database access: one driver (psycopg), one DSN from the environment."""
from __future__ import annotations

import os

import psycopg

ENV_DSN = "RESEARCH_GATEWAY_DSN"


def dsn() -> str:
    value = os.environ.get(ENV_DSN)
    if not value:
        raise RuntimeError(f"{ENV_DSN} is not set (libpq URI for the research database)")
    return value


def connect(autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(dsn(), autocommit=autocommit)


def configured() -> bool:
    return bool(os.environ.get(ENV_DSN))
