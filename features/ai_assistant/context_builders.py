from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .factual_answers import FactualAnswer, build_factual_answer
from .intent_router import StatIntent, detect_intent
from .tools import get_known_players


@dataclass(frozen=True)
class AssistantContext:
    text: str
    tools_used: list[str]
    clarification: str | None = None
    intent: StatIntent | None = None
    factual_answer: FactualAnswer | None = None

    @property
    def intent_name(self) -> str:
        return self.intent.name if self.intent else "unknown"

    @property
    def stat_backed(self) -> bool:
        return bool(self.intent and self.intent.stat_backed)

    @property
    def data_found(self) -> bool:
        return bool(self.factual_answer and self.factual_answer.data_found)


def build_stat_context(
    conn: sqlite3.Connection,
    question: str,
    max_rows: int = 100,
) -> AssistantContext:
    tools_used: list[str] = []
    known_players = get_known_players(conn, limit=max_rows)
    tools_used.append("get_known_players")
    intent = detect_intent(question, known_players)

    if intent.clarification:
        return AssistantContext("", tools_used, clarification=intent.clarification, intent=intent)

    factual = build_factual_answer(conn, question, intent, max_rows=max_rows)
    if factual:
        combined_tools = tools_used + [tool for tool in factual.tools_used if tool not in tools_used]
        return AssistantContext(
            factual.context_text,
            combined_tools,
            intent=intent,
            factual_answer=factual,
        )

    return AssistantContext("", tools_used, intent=intent)
