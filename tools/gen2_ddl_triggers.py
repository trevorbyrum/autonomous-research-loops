"""Installed trigger definitions and their source spans in ordered gen-2 DDL.

SQLite determines statement boundaries and the installed catalog, including
DROP/re-CREATE and no-op CREATE IF NOT EXISTS. Comments and string literals
never count as schema changes. All execution uses a fresh in-memory database.
Both mutation coverage and trigger reversal consume this inventory.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Trigger:
    sql: str
    start: int
    end: int


def installed_triggers(ddl: str) -> dict[str, Trigger]:
    """Final triggers in catalog creation order, pointing at their live CREATE.

    Retain only the last installed definition, even when a name or identical
    body is re-created. Source spans exclude leading comments and include the
    terminating semicolon and its newline, so reversal leaves unrelated text
    in place (and preserves the tools' existing block-text coverage checks).
    """
    conn = sqlite3.connect(":memory:")
    try:
        installed: dict[str, Trigger] = {}
        start = 0
        for end, char in enumerate(ddl, 1):
            if char != ";" or not sqlite3.complete_statement(ddl[start:end]):
                continue
            statement = ddl[start:end]
            conn.execute(statement)
            current = {}
            for name, sql in conn.execute("SELECT name, sql FROM sqlite_schema WHERE type = 'trigger' ORDER BY rowid"):
                if name in installed and installed[name].sql == sql:
                    current[name] = installed[name]
                else:
                    offset = statement.find(sql)
                    if offset < 0:
                        raise ValueError(f"cannot locate installed trigger definition: {name}")
                    block_end = end + (ddl[end:end + 1] == "\n")
                    current[name] = Trigger(sql, start + offset, block_end)
            installed = current
            start = end
        # Execute the remainder too: trailing comments are harmless, incomplete
        # SQL must fail rather than silently truncate the installed inventory.
        conn.execute(ddl[start:])
        final = dict(conn.execute("SELECT name, sql FROM sqlite_schema WHERE type = 'trigger'"))
        if final != {name: trigger.sql for name, trigger in installed.items()}:
            raise ValueError("trigger DDL requires a terminating semicolon")
        return installed
    finally:
        conn.close()
