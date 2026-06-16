from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


CREATE_AI_QUERY_LOG_SQL = """
CREATE TABLE IF NOT EXISTS ai_query_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    guild_id TEXT,
    channel_id TEXT,
    user_id TEXT,
    user_display_name TEXT,
    question TEXT,
    tools_used TEXT,
    response_preview TEXT,
    error TEXT
)
"""


@dataclass(frozen=True)
class QueryLogRecord:
    guild_id: str | None
    channel_id: str | None
    user_id: str | None
    user_display_name: str | None
    question: str
    tools_used: list[str]
    response_preview: str | None = None
    error: str | None = None


def ensure_ai_query_log(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_AI_QUERY_LOG_SQL)
    conn.commit()


def log_ai_query(conn: sqlite3.Connection, record: QueryLogRecord) -> None:
    ensure_ai_query_log(conn)
    conn.execute(
        """
        INSERT INTO ai_query_log (
            guild_id, channel_id, user_id, user_display_name,
            question, tools_used, response_preview, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.guild_id,
            record.channel_id,
            record.user_id,
            record.user_display_name,
            record.question[:1000],
            json.dumps(record.tools_used, ensure_ascii=True),
            (record.response_preview or "")[:500],
            (record.error or "")[:500],
        ),
    )
    conn.commit()
