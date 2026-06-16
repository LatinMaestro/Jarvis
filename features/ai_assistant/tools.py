from __future__ import annotations

import difflib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any


def _norm_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _season_filter(season_id: int | None, alias: str = "") -> tuple[str, list[Any]]:
    if season_id is None:
        return "", []
    prefix = f"{alias}." if alias else ""
    return f" AND {prefix}season_id = ?", [int(season_id)]


@dataclass(frozen=True)
class PlayerMatch:
    status: str
    player: str | None = None
    candidates: tuple[str, ...] = ()


def get_current_season(conn: sqlite3.Connection) -> int | None:
    if _table_exists(conn, "bot_settings"):
        row = conn.execute(
            "SELECT value FROM bot_settings WHERE key='current_season' LIMIT 1"
        ).fetchone()
        if row:
            try:
                return int(row[0])
            except (TypeError, ValueError):
                pass
    if _table_exists(conn, "mr_season_windows"):
        row = conn.execute("SELECT MAX(season_id) FROM mr_season_windows").fetchone()
        if row and row[0] is not None:
            return int(row[0])
    return None


def get_known_players(conn: sqlite3.Connection, limit: int = 200) -> list[str]:
    names: set[str] = set()
    if _table_exists(conn, "mr_roster"):
        for (name,) in conn.execute(
            """
            SELECT DISTINCT player_name
            FROM mr_roster
            WHERE COALESCE(enabled, 1)=1
              AND player_name IS NOT NULL
              AND TRIM(player_name) <> ''
            ORDER BY LOWER(player_name)
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall():
            names.add(str(name).strip())

    if _table_exists(conn, "mr_player_match") and len(names) < limit:
        for (name,) in conn.execute(
            """
            SELECT player
            FROM mr_player_match
            WHERE COALESCE(is_bot,0)=0
              AND player IS NOT NULL
              AND TRIM(player) <> ''
            GROUP BY player
            ORDER BY COUNT(*) DESC, LOWER(player)
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall():
            names.add(str(name).strip())

    if _table_exists(conn, "game_stats") and len(names) < limit:
        for (name,) in conn.execute(
            """
            SELECT player
            FROM game_stats
            WHERE player IS NOT NULL AND TRIM(player) <> ''
            GROUP BY player
            ORDER BY COUNT(*) DESC, LOWER(player)
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall():
            names.add(str(name).strip())

    return sorted(names, key=lambda n: n.lower())[:limit]


def fuzzy_match_player(query: str, known_players: list[str]) -> PlayerMatch:
    cleaned = _norm_name(query)
    if not cleaned:
        return PlayerMatch("missing")

    exact = [name for name in known_players if _norm_name(name) == cleaned]
    if len(exact) == 1:
        return PlayerMatch("matched", exact[0])
    if len(exact) > 1:
        return PlayerMatch("ambiguous", candidates=tuple(sorted(exact)))

    contains = [name for name in known_players if cleaned in _norm_name(name)]
    if len(contains) == 1:
        return PlayerMatch("matched", contains[0])
    if len(contains) > 1:
        return PlayerMatch("ambiguous", candidates=tuple(sorted(contains)[:5]))

    by_norm = {_norm_name(name): name for name in known_players}
    close = difflib.get_close_matches(cleaned, list(by_norm.keys()), n=5, cutoff=0.72)
    if len(close) == 1:
        return PlayerMatch("matched", by_norm[close[0]])
    if len(close) > 1:
        return PlayerMatch("ambiguous", candidates=tuple(by_norm[item] for item in close))
    return PlayerMatch("not_found")


def get_player_summary(conn: sqlite3.Connection, player_name: str, season_id: int | None = None) -> dict[str, Any]:
    where, params = _season_filter(season_id)
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS games,
            SUM(COALESCE(win,0)) AS wins,
            SUM(COALESCE(loss,0)) AS losses,
            SUM(COALESCE(kills,0)) AS kills,
            SUM(COALESCE(deaths,0)) AS deaths,
            SUM(COALESCE(assists,0)) AS assists,
            SUM(COALESCE(damage,0)) AS damage,
            SUM(COALESCE(healing,0)) AS healing
        FROM game_stats
        WHERE LOWER(player)=LOWER(?){where}
        """,
        [player_name, *params],
    ).fetchone()
    games, wins, losses, kills, deaths, assists, damage, healing = row or (0, 0, 0, 0, 0, 0, 0, 0)
    games = int(games or 0)
    wins = int(wins or 0)
    losses = int(losses or 0)
    return {
        "player": player_name,
        "season_id": season_id,
        "games": games,
        "wins": wins,
        "losses": losses,
        "win_rate": round((wins / games) * 100, 1) if games else 0.0,
        "kills": int(kills or 0),
        "deaths": int(deaths or 0),
        "assists": int(assists or 0),
        "kda_hint": round(((kills or 0) + (assists or 0)) / max(1, (deaths or 0)), 2),
        "damage": int(damage or 0),
        "healing": int(healing or 0),
    }


def compare_players(
    conn: sqlite3.Connection,
    player_a: str,
    player_b: str,
    season_id: int | None = None,
) -> dict[str, Any]:
    return {
        "player_a": get_player_summary(conn, player_a, season_id),
        "player_b": get_player_summary(conn, player_b, season_id),
    }


def get_player_hero_summary(
    conn: sqlite3.Connection,
    player_name: str,
    season_id: int | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    if not (_table_exists(conn, "mr_hero_segments") and _table_exists(conn, "hero_cache")):
        return []
    where, params = _season_filter(season_id, "hs")
    rows = conn.execute(
        f"""
        SELECT
            COALESCE(hc.hero_name, CAST(hs.hero_id AS TEXT)) AS hero_name,
            COALESCE(hc.hero_role, 'Unknown') AS hero_role,
            ROUND(SUM(COALESCE(hs.seconds,0)) / 60.0, 1) AS minutes,
            SUM(COALESCE(hs.kills,0)) AS kills,
            SUM(COALESCE(hs.deaths,0)) AS deaths,
            SUM(COALESCE(hs.assists,0)) AS assists
        FROM mr_hero_segments hs
        LEFT JOIN hero_cache hc ON CAST(hc.hero_id AS TEXT)=CAST(hs.hero_id AS TEXT)
        WHERE COALESCE(hs.is_bot,0)=0
          AND LOWER(hs.player)=LOWER(?){where}
        GROUP BY hero_name, hero_role
        ORDER BY SUM(COALESCE(hs.seconds,0)) DESC
        LIMIT ?
        """,
        [player_name, *params, int(limit)],
    ).fetchall()
    return [
        {
            "hero": row[0],
            "role": row[1],
            "minutes": row[2],
            "kills": int(row[3] or 0),
            "deaths": int(row[4] or 0),
            "assists": int(row[5] or 0),
        }
        for row in rows
    ]


def get_duo_synergy(
    conn: sqlite3.Connection,
    player_a: str,
    player_b: str,
    season_id: int | None = None,
) -> dict[str, Any]:
    if not _table_exists(conn, "mr_player_match"):
        return {"players": [player_a, player_b], "games_together": 0, "wins_together": 0, "win_rate": 0.0}
    where, params = _season_filter(season_id, "a")
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS games_together,
            SUM(CASE WHEN COALESCE(a.is_win,0)=1 AND COALESCE(b.is_win,0)=1 THEN 1 ELSE 0 END) AS wins_together
        FROM mr_player_match a
        JOIN mr_player_match b
          ON a.season_id=b.season_id
         AND a.match_uid=b.match_uid
         AND COALESCE(a.camp,-1)=COALESCE(b.camp,-2)
        WHERE COALESCE(a.is_bot,0)=0
          AND COALESCE(b.is_bot,0)=0
          AND LOWER(a.player)=LOWER(?)
          AND LOWER(b.player)=LOWER(?)
          AND LOWER(a.player) <> LOWER(b.player){where}
        """,
        [player_a, player_b, *params],
    ).fetchone()
    games = int((row or [0, 0])[0] or 0)
    wins = int((row or [0, 0])[1] or 0)
    return {
        "players": [player_a, player_b],
        "season_id": season_id,
        "games_together": games,
        "wins_together": wins,
        "win_rate": round((wins / games) * 100, 1) if games else 0.0,
    }


def get_recent_games(conn: sqlite3.Connection, limit: int = 10, season_id: int | None = None) -> list[dict[str, Any]]:
    where, params = _season_filter(season_id)
    rows = conn.execute(
        f"""
        SELECT game_label, MIN(timestamp) AS first_seen, COUNT(DISTINCT player) AS players_seen
        FROM game_stats
        WHERE 1=1{where}
        GROUP BY game_label
        ORDER BY first_seen DESC
        LIMIT ?
        """,
        [*params, int(limit)],
    ).fetchall()
    return [
        {"game_label": row[0], "first_seen": row[1], "players_seen": int(row[2] or 0)}
        for row in rows
    ]


def get_latest_session_summary(conn: sqlite3.Connection, season_id: int | None = None) -> dict[str, Any]:
    del season_id  # Session state is channel-scoped rather than season-scoped in the current schema.
    if not _table_exists(conn, "session_state"):
        return {"available": False}
    row = conn.execute(
        """
        SELECT guild_id, channel_id, state_json, updated_at
        FROM session_state
        ORDER BY updated_at DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return {"available": False}
    try:
        state = json.loads(row[2] or "{}")
    except json.JSONDecodeError:
        state = {}
    return {
        "available": True,
        "guild_id": str(row[0]),
        "channel_id": str(row[1]),
        "updated_at": row[3],
        "state_keys": sorted(state.keys())[:12],
        "player_count_hint": len(state.get("players", [])) if isinstance(state.get("players"), list) else None,
    }


def get_player_roast_context(
    conn: sqlite3.Connection,
    player_name: str,
    season_id: int | None = None,
) -> dict[str, Any]:
    return {
        "summary": get_player_summary(conn, player_name, season_id),
        "heroes": get_player_hero_summary(conn, player_name, season_id, limit=5),
    }


def get_lobby_roast_context(
    conn: sqlite3.Connection,
    season_id: int | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    where, params = _season_filter(season_id)
    rows = conn.execute(
        f"""
        SELECT
            player,
            COUNT(*) AS games,
            SUM(COALESCE(win,0)) AS wins,
            SUM(COALESCE(deaths,0)) AS deaths,
            SUM(COALESCE(kills,0)) AS kills,
            SUM(COALESCE(assists,0)) AS assists
        FROM game_stats
        WHERE player IS NOT NULL AND TRIM(player) <> ''{where}
        GROUP BY player
        HAVING games >= 3
        ORDER BY (1.0 * SUM(COALESCE(deaths,0)) / COUNT(*)) DESC
        LIMIT ?
        """,
        [*params, int(limit)],
    ).fetchall()
    out = []
    for row in rows:
        games = int(row[1] or 0)
        wins = int(row[2] or 0)
        out.append(
            {
                "player": row[0],
                "games": games,
                "win_rate": round((wins / games) * 100, 1) if games else 0.0,
                "deaths_per_game": round((row[3] or 0) / max(1, games), 2),
                "kills": int(row[4] or 0),
                "assists": int(row[5] or 0),
            }
        )
    return out
