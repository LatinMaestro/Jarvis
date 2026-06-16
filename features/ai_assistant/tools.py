from __future__ import annotations

import difflib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

DEFAULT_LEADERBOARD_MIN_GAMES = 30
DEFAULT_DUO_MIN_GAMES = 3
DEFAULT_HERO_MIN_GAMES = 2
DEFAULT_ROLE_MIN_GAMES = 3


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


def _kda(kills: int | float, assists: int | float, deaths: int | float) -> float:
    return round((float(kills or 0) + float(assists or 0)) / max(1.0, float(deaths or 0)), 2)


def _win_rate(wins: int | float, games: int | float) -> float:
    return round((float(wins or 0) / max(1.0, float(games or 0))) * 100, 1)


def _leaderboard_rows(
    conn: sqlite3.Connection,
    season_id: int | None = None,
    min_games: int | None = None,
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "game_stats"):
        return []
    where, params = _season_filter(season_id)
    rows = conn.execute(
        f"""
        SELECT
            player,
            COUNT(*) AS games,
            SUM(COALESCE(win,0)) AS wins,
            SUM(COALESCE(loss,0)) AS losses,
            SUM(COALESCE(kills,0)) AS kills,
            SUM(COALESCE(deaths,0)) AS deaths,
            SUM(COALESCE(assists,0)) AS assists,
            SUM(COALESCE(damage,0)) AS damage,
            SUM(COALESCE(healing,0)) AS healing,
            SUM(COALESCE(damage_taken,0)) AS damage_taken,
            SUM(COALESCE(mvp,0)) AS mvp,
            SUM(COALESCE(svp,0)) AS svp
        FROM game_stats
        WHERE player IS NOT NULL AND TRIM(player) <> ''{where}
        GROUP BY player
        """,
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        games = int(row[1] or 0)
        wins = int(row[2] or 0)
        losses = int(row[3] or 0)
        kills = int(row[4] or 0)
        deaths = int(row[5] or 0)
        assists = int(row[6] or 0)
        if min_games is not None and games < int(min_games):
            continue
        out.append(
            {
                "player": row[0],
                "season_id": season_id,
                "games": games,
                "wins": wins,
                "losses": losses,
                "win_rate": _win_rate(wins, games),
                "kills": kills,
                "deaths": deaths,
                "assists": assists,
                "kda": _kda(kills, assists, deaths),
                "damage": int(row[7] or 0),
                "healing": int(row[8] or 0),
                "damage_taken": int(row[9] or 0),
                "mvp": int(row[10] or 0),
                "svp": int(row[11] or 0),
            }
        )
    out.sort(key=lambda item: (item["win_rate"], item["games"], item["wins"]), reverse=True)
    for index, item in enumerate(out, start=1):
        item["rank"] = index
    return out


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


def get_leaderboard_summary(
    conn: sqlite3.Connection,
    season_id: int | None = None,
    limit: int = 10,
    min_games: int | None = DEFAULT_LEADERBOARD_MIN_GAMES,
) -> list[dict[str, Any]]:
    return _leaderboard_rows(conn, season_id, min_games)[: int(limit)]


def get_first_place(conn: sqlite3.Connection, season_id: int | None = None) -> dict[str, Any] | None:
    rows = get_leaderboard_summary(conn, season_id, limit=1, min_games=DEFAULT_LEADERBOARD_MIN_GAMES)
    if rows:
        return rows[0]
    fallback = get_leaderboard_summary(conn, season_id, limit=1, min_games=None)
    return fallback[0] if fallback else None


def get_top_by_metric(
    conn: sqlite3.Connection,
    metric: str,
    season_id: int | None = None,
    limit: int = 5,
    min_games: int | None = None,
) -> list[dict[str, Any]]:
    metric_key = (metric or "").strip().lower()
    metric_aliases = {
        "winrate": "win_rate",
        "win_rate": "win_rate",
        "wins": "wins",
        "games": "games",
        "kda": "kda",
        "damage": "damage",
        "kills": "kills",
        "assists": "assists",
        "healing": "healing",
        "damage_taken": "damage_taken",
        "mvp": "mvp",
        "svp": "svp",
    }
    if metric_key not in metric_aliases:
        raise ValueError(f"Unsupported leaderboard metric: {metric}")
    selected = metric_aliases[metric_key]
    effective_min_games = DEFAULT_LEADERBOARD_MIN_GAMES if selected == "win_rate" and min_games is None else min_games
    rows = _leaderboard_rows(conn, season_id, effective_min_games)
    rows.sort(key=lambda item: (item.get(selected, 0), item.get("games", 0), item.get("win_rate", 0)), reverse=True)
    return rows[: int(limit)]


def get_highest_win_rate(
    conn: sqlite3.Connection,
    season_id: int | None = None,
    min_games: int | None = DEFAULT_LEADERBOARD_MIN_GAMES,
    limit: int = 5,
) -> list[dict[str, Any]]:
    return get_top_by_metric(conn, "win_rate", season_id, limit=limit, min_games=min_games)


def get_top_duos(
    conn: sqlite3.Connection,
    season_id: int | None = None,
    min_games: int | None = DEFAULT_DUO_MIN_GAMES,
    limit: int = 5,
    worst: bool = False,
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "mr_player_match"):
        return []
    where, params = _season_filter(season_id, "a")
    rows = conn.execute(
        f"""
        SELECT
            a.player AS player_a,
            b.player AS player_b,
            COUNT(*) AS games_together,
            SUM(CASE WHEN COALESCE(a.is_win,0)=1 AND COALESCE(b.is_win,0)=1 THEN 1 ELSE 0 END) AS wins_together
        FROM mr_player_match a
        JOIN mr_player_match b
          ON a.season_id=b.season_id
         AND a.match_uid=b.match_uid
         AND COALESCE(a.camp,-1)=COALESCE(b.camp,-2)
         AND LOWER(a.player) < LOWER(b.player)
        WHERE COALESCE(a.is_bot,0)=0
          AND COALESCE(b.is_bot,0)=0
          AND a.player IS NOT NULL
          AND b.player IS NOT NULL{where}
        GROUP BY LOWER(a.player), LOWER(b.player)
        """,
        params,
    ).fetchall()
    out = []
    for row in rows:
        games = int(row[2] or 0)
        if min_games is not None and games < int(min_games):
            continue
        wins = int(row[3] or 0)
        out.append(
            {
                "players": [row[0], row[1]],
                "season_id": season_id,
                "games_together": games,
                "wins_together": wins,
                "win_rate": _win_rate(wins, games),
            }
        )
    out.sort(key=lambda item: (item["win_rate"], item["games_together"]), reverse=not worst)
    return out[: int(limit)]


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


def _match_hero(conn: sqlite3.Connection, hero_name_or_id: str) -> dict[str, Any] | None:
    if not _table_exists(conn, "hero_cache"):
        return None
    query = (hero_name_or_id or "").strip()
    if not query:
        return None
    heroes = conn.execute(
        """
        SELECT hero_id, hero_name, COALESCE(hero_role, 'Unknown')
        FROM hero_cache
        WHERE hero_name IS NOT NULL AND TRIM(hero_name) <> ''
        """
    ).fetchall()
    normalized = _norm_name(query)
    for hero_id, hero_name, hero_role in heroes:
        if str(hero_id) == query or _norm_name(str(hero_name)) == normalized:
            return {"hero_id": hero_id, "hero": hero_name, "role": hero_role}
    contains = [
        (hero_id, hero_name, hero_role)
        for hero_id, hero_name, hero_role in heroes
        if normalized and normalized in _norm_name(str(hero_name))
    ]
    if contains:
        hero_id, hero_name, hero_role = contains[0]
        return {"hero_id": hero_id, "hero": hero_name, "role": hero_role}
    by_norm = {_norm_name(str(hero_name)): (hero_id, hero_name, hero_role) for hero_id, hero_name, hero_role in heroes}
    close = difflib.get_close_matches(normalized, list(by_norm.keys()), n=1, cutoff=0.72)
    if close:
        hero_id, hero_name, hero_role = by_norm[close[0]]
        return {"hero_id": hero_id, "hero": hero_name, "role": hero_role}
    return None


def get_best_role_players(
    conn: sqlite3.Connection,
    role: str,
    season_id: int | None = None,
    min_games: int | None = DEFAULT_ROLE_MIN_GAMES,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not (_table_exists(conn, "mr_hero_segments") and _table_exists(conn, "hero_cache")):
        return []
    role_key = (role or "").strip().lower()
    role_aliases = {
        "tank": "vanguard",
        "vanguard": "vanguard",
        "dps": "duelist",
        "duelist": "duelist",
        "support": "strategist",
        "strategist": "strategist",
        "healer": "strategist",
    }
    selected_role = role_aliases.get(role_key, role_key)
    where, params = _season_filter(season_id, "hs")
    rows = conn.execute(
        f"""
        SELECT
            hs.player,
            COUNT(DISTINCT hs.match_uid) AS games,
            COUNT(DISTINCT CASE WHEN COALESCE(pm.is_win,0)=1 THEN hs.match_uid END) AS wins,
            SUM(COALESCE(hs.seconds,0)) AS seconds,
            SUM(COALESCE(hs.kills,0)) AS kills,
            SUM(COALESCE(hs.deaths,0)) AS deaths,
            SUM(COALESCE(hs.assists,0)) AS assists
        FROM mr_hero_segments hs
        JOIN hero_cache hc ON CAST(hc.hero_id AS TEXT)=CAST(hs.hero_id AS TEXT)
        LEFT JOIN mr_player_match pm
          ON pm.season_id=hs.season_id
         AND pm.match_uid=hs.match_uid
         AND pm.player_uid=hs.player_uid
        WHERE COALESCE(hs.is_bot,0)=0
          AND LOWER(COALESCE(hc.hero_role,''))=LOWER(?){where}
        GROUP BY hs.player
        """,
        [selected_role, *params],
    ).fetchall()
    out = []
    for row in rows:
        games = int(row[1] or 0)
        if min_games is not None and games < int(min_games):
            continue
        wins = int(row[2] or 0)
        kills = int(row[4] or 0)
        deaths = int(row[5] or 0)
        assists = int(row[6] or 0)
        out.append(
            {
                "player": row[0],
                "role": selected_role.title(),
                "season_id": season_id,
                "games": games,
                "wins": wins,
                "win_rate": _win_rate(wins, games),
                "minutes": round(float(row[3] or 0) / 60.0, 1),
                "kills": kills,
                "deaths": deaths,
                "assists": assists,
                "kda": _kda(kills, assists, deaths),
            }
        )
    out.sort(key=lambda item: (item["win_rate"], item["kda"], item["minutes"]), reverse=True)
    return out[: int(limit)]


def get_best_hero_players(
    conn: sqlite3.Connection,
    hero_name_or_id: str,
    season_id: int | None = None,
    min_games: int | None = DEFAULT_HERO_MIN_GAMES,
    limit: int = 5,
) -> dict[str, Any]:
    hero = _match_hero(conn, hero_name_or_id)
    if not hero or not _table_exists(conn, "mr_hero_segments"):
        return {"hero": hero_name_or_id, "matched": False, "players": []}
    where, params = _season_filter(season_id, "hs")
    rows = conn.execute(
        f"""
        SELECT
            hs.player,
            COUNT(DISTINCT hs.match_uid) AS games,
            COUNT(DISTINCT CASE WHEN COALESCE(pm.is_win,0)=1 THEN hs.match_uid END) AS wins,
            SUM(COALESCE(hs.seconds,0)) AS seconds,
            SUM(COALESCE(hs.kills,0)) AS kills,
            SUM(COALESCE(hs.deaths,0)) AS deaths,
            SUM(COALESCE(hs.assists,0)) AS assists
        FROM mr_hero_segments hs
        LEFT JOIN mr_player_match pm
          ON pm.season_id=hs.season_id
         AND pm.match_uid=hs.match_uid
         AND pm.player_uid=hs.player_uid
        WHERE COALESCE(hs.is_bot,0)=0
          AND CAST(hs.hero_id AS TEXT)=CAST(? AS TEXT){where}
        GROUP BY hs.player
        """,
        [hero["hero_id"], *params],
    ).fetchall()
    players = []
    for row in rows:
        games = int(row[1] or 0)
        if min_games is not None and games < int(min_games):
            continue
        wins = int(row[2] or 0)
        kills = int(row[4] or 0)
        deaths = int(row[5] or 0)
        assists = int(row[6] or 0)
        players.append(
            {
                "player": row[0],
                "games": games,
                "wins": wins,
                "win_rate": _win_rate(wins, games),
                "minutes": round(float(row[3] or 0) / 60.0, 1),
                "kills": kills,
                "deaths": deaths,
                "assists": assists,
                "kda": _kda(kills, assists, deaths),
            }
        )
    players.sort(key=lambda item: (item["win_rate"], item["kda"], item["minutes"]), reverse=True)
    return {**hero, "matched": True, "players": players[: int(limit)]}


def get_player_podium_context(
    conn: sqlite3.Connection,
    player_name: str,
    season_id: int | None = None,
) -> dict[str, Any]:
    rows = _leaderboard_rows(conn, season_id, DEFAULT_LEADERBOARD_MIN_GAMES)
    player_norm = _norm_name(player_name)
    player_row = next((row for row in rows if _norm_name(row["player"]) == player_norm), None)
    if not player_row:
        provisional = get_player_summary(conn, player_name, season_id)
        return {
            "player": player_name,
            "ranked": False,
            "min_games": DEFAULT_LEADERBOARD_MIN_GAMES,
            "summary": provisional,
            "message": "Player is not on the main leaderboard threshold yet.",
        }
    top_three = rows[:3]
    third = top_three[-1] if len(top_three) >= 3 else None
    return {
        "player": player_name,
        "ranked": True,
        "rank": player_row["rank"],
        "summary": player_row,
        "top_three": top_three,
        "third_place_gap": None
        if third is None or player_row["rank"] <= 3
        else {
            "win_rate_points": round(third["win_rate"] - player_row["win_rate"], 1),
            "games": third["games"] - player_row["games"],
        },
    }


def get_player_recommendation_context(
    conn: sqlite3.Connection,
    player_name: str,
    season_id: int | None = None,
) -> dict[str, Any]:
    summary = get_player_summary(conn, player_name, season_id)
    heroes = get_player_hero_summary(conn, player_name, season_id, limit=8)
    role_minutes: dict[str, float] = {}
    for hero in heroes:
        role_minutes[hero["role"]] = role_minutes.get(hero["role"], 0.0) + float(hero["minutes"] or 0)
    return {
        "summary": summary,
        "hero_history": heroes,
        "role_minutes": role_minutes,
        "note": "Recommendation context is read-only snapshot data; it suggests trends but does not rewrite team strategy.",
    }


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
