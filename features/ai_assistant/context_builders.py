from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from .tools import (
    PlayerMatch,
    compare_players,
    fuzzy_match_player,
    get_current_season,
    get_duo_synergy,
    get_known_players,
    get_latest_session_summary,
    get_lobby_roast_context,
    get_player_hero_summary,
    get_player_roast_context,
    get_player_summary,
    get_recent_games,
)


@dataclass(frozen=True)
class AssistantContext:
    text: str
    tools_used: list[str]
    clarification: str | None = None


def _json_line(label: str, value: object) -> str:
    return f"{label}: {json.dumps(value, ensure_ascii=True, default=str)}"


def _candidate_phrases(question: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s_-]+", " ", question)
    tokens = [token.strip() for token in cleaned.split() if len(token.strip()) >= 3]
    phrases = []
    for size in (3, 2, 1):
        for i in range(0, max(0, len(tokens) - size + 1)):
            phrases.append(" ".join(tokens[i : i + size]))
    return phrases


def _find_players(question: str, known_players: list[str], max_players: int = 2) -> tuple[list[str], str | None]:
    found: list[str] = []
    ambiguous: list[str] = []
    question_norm = re.sub(r"[^a-z0-9]+", "", question.lower())
    for name in known_players:
        norm = re.sub(r"[^a-z0-9]+", "", name.lower())
        if norm and norm in question_norm and name not in found:
            found.append(name)

    for phrase in _candidate_phrases(question):
        if len(found) >= max_players:
            break
        match = fuzzy_match_player(phrase, known_players)
        if match.status == "matched" and match.player and match.player not in found:
            found.append(match.player)
        elif match.status == "ambiguous":
            ambiguous.extend(match.candidates)

    if len(found) >= max_players:
        return found[:max_players], None
    if ambiguous and not found:
        return [], "I can roast efficiently, but that name is ambiguous. Did you mean: " + ", ".join(ambiguous[:5]) + "?"
    return found, None


def build_stat_context(
    conn: sqlite3.Connection,
    question: str,
    max_rows: int = 100,
) -> AssistantContext:
    lowered = question.lower()
    tools_used: list[str] = []
    lines: list[str] = []

    season_id = get_current_season(conn)
    tools_used.append("get_current_season")
    lines.append(_json_line("current_season_snapshot_marker", season_id))

    known_players = get_known_players(conn, limit=max_rows)
    tools_used.append("get_known_players")
    lines.append(_json_line("known_players_sample", known_players[: min(25, len(known_players))]))

    players, clarification = _find_players(question, known_players)
    if clarification:
        return AssistantContext("\n".join(lines), tools_used, clarification=clarification)

    wants_recent = any(term in lowered for term in ("last night", "recent", "latest", "what happened"))
    wants_duo = any(term in lowered for term in ("duo", "chemistry", "pair", "combo", "together"))
    wants_hero = any(term in lowered for term in ("hero", "play", "playing", "main"))
    wants_roast = any(term in lowered for term in ("roast", "liability", "honest opinion", "fraud", "farming"))
    wants_session = any(term in lowered for term in ("tonight", "session", "lobby", "teams"))
    wants_compare = len(players) >= 2 or any(term in lowered for term in ("better", "best", "worse", "versus", " vs "))

    if players:
        for player in players:
            if wants_roast:
                lines.append(_json_line(f"player_roast_context_{player}", get_player_roast_context(conn, player, season_id)))
                tools_used.append("get_player_roast_context")
            else:
                lines.append(_json_line(f"player_summary_{player}", get_player_summary(conn, player, season_id)))
                tools_used.append("get_player_summary")
            if wants_hero:
                lines.append(_json_line(f"player_hero_summary_{player}", get_player_hero_summary(conn, player, season_id)))
                tools_used.append("get_player_hero_summary")

    if wants_duo and len(players) >= 2:
        lines.append(_json_line("duo_synergy", get_duo_synergy(conn, players[0], players[1], season_id)))
        tools_used.append("get_duo_synergy")
    elif wants_compare and len(players) >= 2:
        lines.append(_json_line("player_comparison", compare_players(conn, players[0], players[1], season_id)))
        tools_used.append("compare_players")

    if wants_recent:
        lines.append(_json_line("recent_games", get_recent_games(conn, limit=min(10, max_rows), season_id=season_id)))
        tools_used.append("get_recent_games")

    if wants_session:
        lines.append(_json_line("latest_session_summary", get_latest_session_summary(conn, season_id)))
        tools_used.append("get_latest_session_summary")

    if wants_roast and not players:
        lines.append(_json_line("lobby_roast_context", get_lobby_roast_context(conn, season_id, limit=min(8, max_rows))))
        tools_used.append("get_lobby_roast_context")

    return AssistantContext("\n".join(lines), tools_used)
