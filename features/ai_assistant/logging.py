from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


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
    error TEXT,
    detected_intent TEXT,
    gemini_called INTEGER DEFAULT 0,
    deterministic_fallback INTEGER DEFAULT 0,
    diagnostics_json TEXT
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
    detected_intent: str | None = None
    gemini_called: bool = False
    deterministic_fallback: bool = False
    diagnostics: dict[str, Any] | None = None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_ai_query_log(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_AI_QUERY_LOG_SQL)
    columns = _column_names(conn, "ai_query_log")
    expected = {
        "detected_intent": "TEXT",
        "gemini_called": "INTEGER DEFAULT 0",
        "deterministic_fallback": "INTEGER DEFAULT 0",
        "diagnostics_json": "TEXT",
    }
    for column, column_type in expected.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE ai_query_log ADD COLUMN {column} {column_type}")
    conn.commit()


def log_ai_query(conn: sqlite3.Connection, record: QueryLogRecord) -> None:
    ensure_ai_query_log(conn)
    conn.execute(
        """
        INSERT INTO ai_query_log (
            guild_id, channel_id, user_id, user_display_name,
            question, tools_used, response_preview, error,
            detected_intent, gemini_called, deterministic_fallback, diagnostics_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            (record.detected_intent or "")[:100],
            1 if record.gemini_called else 0,
            1 if record.deterministic_fallback else 0,
            json.dumps(record.diagnostics or {}, ensure_ascii=True, default=str)[:1000],
        ),
    )
    conn.commit()
