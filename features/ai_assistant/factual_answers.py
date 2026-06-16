from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .intent_router import StatIntent
from .tools import (
    compare_players,
    get_best_hero_players,
    get_best_role_players,
    get_current_season,
    get_duo_synergy,
    get_first_place,
    get_highest_win_rate,
    get_leaderboard_summary,
    get_latest_session_summary,
    get_player_podium_context,
    get_player_recommendation_context,
    get_player_roast_context,
    get_player_summary,
    get_recent_games,
    get_top_by_metric,
    get_top_duos,
)


@dataclass(frozen=True)
class FactualAnswer:
    intent: str
    text: str
    context_text: str
    tools_used: list[str]
    data_found: bool


def _json_line(label: str, value: object) -> str:
    return f"{label}: {json.dumps(value, ensure_ascii=True, default=str)}"


def _fmt_num(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _player_line(row: dict[str, Any], metric: str = "win_rate") -> str:
    suffix = {
        "win_rate": f"{row.get('win_rate', 0)}% WR over {row.get('games', 0)} games",
        "wins": f"{row.get('wins', 0)} wins over {row.get('games', 0)} games",
        "kda": f"{row.get('kda', 0)} KDA",
        "damage": f"{_fmt_num(row.get('damage', 0))} damage",
        "kills": f"{_fmt_num(row.get('kills', 0))} kills",
        "healing": f"{_fmt_num(row.get('healing', 0))} healing",
        "damage_taken": f"{_fmt_num(row.get('damage_taken', 0))} damage taken",
        "mvp": f"{row.get('mvp', 0)} MVPs",
        "svp": f"{row.get('svp', 0)} SVPs",
    }.get(metric, f"{row.get(metric, 0)} {metric}")
    return f"{row.get('player')}: {suffix}"


def _ranked_lines(rows: list[dict[str, Any]], metric: str = "win_rate") -> list[str]:
    return [f"{index}. {_player_line(row, metric)}" for index, row in enumerate(rows, start=1)]


def _empty(intent: StatIntent, tools: list[str], season_id: int | None) -> FactualAnswer:
    text = (
        f"I checked the offline snapshot for season {season_id}, but there was not enough matching data "
        "to answer that one cleanly."
    )
    return FactualAnswer(intent.name, text, _json_line("current_season_snapshot_marker", season_id), tools, False)


def build_factual_answer(
    conn: sqlite3.Connection,
    question: str,
    intent: StatIntent,
    max_rows: int = 100,
) -> FactualAnswer | None:
    del question
    if not intent.stat_backed:
        if intent.name == "stat_bot_correction":
            text = "Fair. I am the stat bot. Ask me a concrete stat question and I will check the approved snapshot tools first, then add the attitude after."
            return FactualAnswer(intent.name, text, "", [], True)
        return None

    season_id = get_current_season(conn)
    tools = ["get_current_season"]
    context_lines = [_json_line("current_season_snapshot_marker", season_id)]
    limit = min(10, max(1, int(max_rows)))

    if intent.name == "leaderboard":
        rows = get_leaderboard_summary(conn, season_id, limit=min(limit, 10))
        tools.append("get_leaderboard_summary")
        context_lines.append(_json_line("leaderboard_summary", rows))
        if not rows:
            return _empty(intent, tools, season_id)
        text = "Leaderboard snapshot, using the main 30-game threshold:\n" + "\n".join(_ranked_lines(rows[:5]))
        return FactualAnswer(intent.name, text, "\n".join(context_lines), tools, True)

    if intent.name == "first_place":
        row = get_first_place(conn, season_id)
        tools.append("get_first_place")
        context_lines.append(_json_line("first_place", row))
        if not row:
            return _empty(intent, tools, season_id)
        text = (
            f"{row['player']} is first in the snapshot leaderboard: "
            f"{row['win_rate']}% win rate, {row['wins']} wins, {row['games']} games."
        )
        return FactualAnswer(intent.name, text, "\n".join(context_lines), tools, True)

    if intent.name == "highest_win_rate":
        rows = get_highest_win_rate(conn, season_id, limit=5)
        tools.append("get_highest_win_rate")
        context_lines.append(_json_line("highest_win_rate", rows))
        if not rows:
            return _empty(intent, tools, season_id)
        text = "Highest win rate snapshot, main leaderboard threshold:\n" + "\n".join(_ranked_lines(rows, "win_rate"))
        return FactualAnswer(intent.name, text, "\n".join(context_lines), tools, True)

    if intent.name == "top_metric":
        metric = intent.metric or "wins"
        rows = get_top_by_metric(conn, metric, season_id, limit=5)
        tools.append("get_top_by_metric")
        context_lines.append(_json_line(f"top_by_{metric}", rows))
        if not rows:
            return _empty(intent, tools, season_id)
        text = f"Top {metric.replace('_', ' ')} snapshot:\n" + "\n".join(_ranked_lines(rows, metric))
        return FactualAnswer(intent.name, text, "\n".join(context_lines), tools, True)

    if intent.name == "top_duos":
        rows = get_top_duos(conn, season_id, limit=5, worst=intent.wants_worst)
        tools.append("get_top_duos")
        context_lines.append(_json_line("duos", rows))
        if not rows:
            return _empty(intent, tools, season_id)
        label = "Worst duo chemistry" if intent.wants_worst else "Best duo chemistry"
        lines = [
            f"{i}. {row['players'][0]} + {row['players'][1]}: {row['win_rate']}% WR, {row['wins_together']}/{row['games_together']}"
            for i, row in enumerate(rows, start=1)
        ]
        return FactualAnswer(intent.name, f"{label} in the snapshot:\n" + "\n".join(lines), "\n".join(context_lines), tools, True)

    if intent.name == "player_duo" and len(intent.players) >= 2:
        data = get_duo_synergy(conn, intent.players[0], intent.players[1], season_id)
        tools.append("get_duo_synergy")
        context_lines.append(_json_line("duo_synergy", data))
        if not data.get("games_together"):
            return _empty(intent, tools, season_id)
        text = (
            f"{intent.players[0]} + {intent.players[1]} are {data['wins_together']}/{data['games_together']} together "
            f"for a {data['win_rate']}% win rate in the snapshot."
        )
        return FactualAnswer(intent.name, text, "\n".join(context_lines), tools, True)

    if intent.name == "best_role" and intent.role:
        rows = get_best_role_players(conn, intent.role, season_id, limit=5)
        tools.append("get_best_role_players")
        context_lines.append(_json_line(f"best_{intent.role}_players", rows))
        if not rows:
            return _empty(intent, tools, season_id)
        lines = [
            f"{i}. {row['player']}: {row['win_rate']}% WR, {row['kda']} KDA, {row['minutes']} min"
            for i, row in enumerate(rows, start=1)
        ]
        return FactualAnswer(intent.name, f"Best {intent.role} players in the snapshot:\n" + "\n".join(lines), "\n".join(context_lines), tools, True)

    if intent.name == "best_hero" and intent.hero:
        data = get_best_hero_players(conn, intent.hero, season_id, limit=5)
        tools.append("get_best_hero_players")
        context_lines.append(_json_line("best_hero_players", data))
        players = data.get("players", [])
        if not players:
            return _empty(intent, tools, season_id)
        lines = [
            f"{i}. {row['player']}: {row['win_rate']}% WR, {row['kda']} KDA, {row['minutes']} min"
            for i, row in enumerate(players, start=1)
        ]
        return FactualAnswer(intent.name, f"Best {data.get('hero', intent.hero)} players in the snapshot:\n" + "\n".join(lines), "\n".join(context_lines), tools, True)

    if intent.name == "podium_context" and intent.players:
        data = get_player_podium_context(conn, intent.players[0], season_id)
        tools.append("get_player_podium_context")
        context_lines.append(_json_line("podium_context", data))
        summary = data.get("summary", {})
        if not data.get("ranked"):
            text = f"{intent.players[0]} is not on the main snapshot leaderboard threshold yet: {summary.get('games', 0)} games logged."
        else:
            text = (
                f"{intent.players[0]} is rank #{data['rank']} in the snapshot: "
                f"{summary.get('win_rate', 0)}% WR over {summary.get('games', 0)} games."
            )
        return FactualAnswer(intent.name, text, "\n".join(context_lines), tools, True)

    if intent.name == "recommendation" and intent.players:
        data = get_player_recommendation_context(conn, intent.players[0], season_id)
        tools.append("get_player_recommendation_context")
        context_lines.append(_json_line("recommendation_context", data))
        heroes = data.get("hero_history", [])
        if not heroes:
            return _empty(intent, tools, season_id)
        top = heroes[0]
        text = (
            f"For {intent.players[0]}, the snapshot points first at {top['hero']} ({top['role']}): "
            f"{top['minutes']} minutes, {top['kills']}/{top['deaths']}/{top['assists']} KDA line."
        )
        return FactualAnswer(intent.name, text, "\n".join(context_lines), tools, True)

    if intent.name == "player_comparison" and len(intent.players) >= 2:
        data = compare_players(conn, intent.players[0], intent.players[1], season_id)
        tools.append("compare_players")
        context_lines.append(_json_line("player_comparison", data))
        a, b = data["player_a"], data["player_b"]
        leader = a if (a["win_rate"], a["games"]) >= (b["win_rate"], b["games"]) else b
        text = (
            f"{leader['player']} has the cleaner snapshot edge by win rate: "
            f"{leader['win_rate']}% over {leader['games']} games. "
            f"{a['player']}: {a['win_rate']}% WR, {a['kda_hint']} KDA. "
            f"{b['player']}: {b['win_rate']}% WR, {b['kda_hint']} KDA."
        )
        return FactualAnswer(intent.name, text, "\n".join(context_lines), tools, True)

    if intent.name in {"player_summary", "roast"} and intent.players:
        data = get_player_roast_context(conn, intent.players[0], season_id) if intent.name == "roast" else get_player_summary(conn, intent.players[0], season_id)
        tools.append("get_player_roast_context" if intent.name == "roast" else "get_player_summary")
        context_lines.append(_json_line(intent.name, data))
        summary = data.get("summary", data)
        if not summary.get("games"):
            return _empty(intent, tools, season_id)
        text = (
            f"{intent.players[0]} snapshot: {summary['wins']}-{summary['losses']} over {summary['games']} games, "
            f"{summary['win_rate']}% WR, {summary.get('kda_hint', 0)} KDA."
        )
        return FactualAnswer(intent.name, text, "\n".join(context_lines), tools, True)

    if intent.name == "recent_session":
        recent = get_recent_games(conn, limit=5, season_id=season_id)
        session = get_latest_session_summary(conn, season_id)
        tools.extend(["get_recent_games", "get_latest_session_summary"])
        context_lines.append(_json_line("recent_games", recent))
        context_lines.append(_json_line("latest_session_summary", session))
        if not recent and not session.get("available"):
            return _empty(intent, tools, season_id)
        text = "Recent snapshot games:\n" + "\n".join(
            f"- {row['game_label']}: {row['players_seen']} players seen, first logged {row['first_seen']}"
            for row in recent
        )
        return FactualAnswer(intent.name, text, "\n".join(context_lines), tools, True)

    return None
