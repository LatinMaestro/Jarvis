"""Factual, season-scoped database export for !season_movie_pack.

The downloadable ZIP is a portable copy of the recorded season match data,
not a movie script or a rendered video. It includes complete historical
leaderboard snapshots and the underlying source tables.
"""

import csv
import io
import json
import zipfile

from jarvis.stats.season_leaderboard_timeline import build_season_leaderboard_timeline
from jarvis.stats.sessions import load_all_ordered_game_labels


# Explicitly export match and season analytics, not settings, credentials,
# private roster/configuration tables, or records belonging to other seasons.
SEASON_TABLES = (
    "match_imports",
    "mr_match_meta",
    "mr_player_match",
    "mr_hero_segments",
    "mr_player_badges",
    "mr_ban_picks",
    "mr_match_json_raw",
    "mr_match_json_humans",
    "hero_time_stats",
    "hero_time_stats_all",
    "hero_bans",
    "game_stats",
    "mr_skipped_matches",
)


def _read_season_table(cursor, name, season_id):
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    if cursor.fetchone() is None:
        return None
    cursor.execute(f"PRAGMA table_info({name})")
    columns = [row[1] for row in cursor.fetchall()]
    if "season_id" not in columns:
        return None
    cursor.execute(f"SELECT * FROM {name} WHERE season_id=?", (season_id,))
    return columns, cursor.fetchall()


def _csv_bytes(columns, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")


def build_season_data_export(cursor, season_id, utc_offset_hours=10):
    """Build a ZIP containing game-by-game rankings and all season match data.

    Reads only; does not alter the database or call external APIs.
    Throws on incomplete chronology to avoid misleading leaderboard movies.
    """
    season_id = int(season_id)
    labels = load_all_ordered_game_labels(cursor, season_id, utc_offset_hours)
    if not labels:
        return None
    timeline = build_season_leaderboard_timeline(cursor, season_id, labels)
    if timeline["game_count"] != len(labels):
        raise ValueError("Incomplete chronological season history")

    export_tables = {}
    for name in SEASON_TABLES:
        rows = _read_season_table(cursor, name, season_id)
        if rows is not None:
            export_tables[name] = rows

    required = ("match_imports", "mr_match_meta", "mr_player_match")
    if any(name not in export_tables for name in required):
        raise ValueError("Required match metadata or human match results are missing")

    # Reconcile final totals directly against the source player-match records.
    final = {r["player_uid"]: r for r in timeline["games"][-1]["standings_after"]}
    cols, rows = export_tables["mr_player_match"]
    index = {col: idx for idx, col in enumerate(cols)}
    totals = {}
    for row in rows:
        if int(row[index["is_bot"]] or 0):
            continue
        uid = int(row[index["player_uid"]])
        entry = totals.setdefault(uid, [0, 0])
        entry[0] += 1
        entry[1] += int(row[index["is_win"]])
    if len(totals) != len(final) or any(
        (final[uid]["games"], final[uid]["wins"]) != tuple(total)
        for uid, total in totals.items()
    ):
        raise ValueError("Final standings do not reconcile with the source database")

    # Each timeline snapshot includes all known season players, even before
    # they play their first game (in which case their rank is null).
    leaderboard_rows = []
    for game in timeline["games"]:
        for standing in game["standings_after"]:
            leaderboard_rows.append((
                game["sequence"], game["game_label"],
                game["recorded_at_utc"], game["time_source"],
                standing["player_uid"], standing["player_name"],
                standing["rank"], standing["previous_rank"],
                standing["rank_change"], standing["games"],
                standing["wins"], standing["losses"], standing["winrate"],
            ))

    game_rows = []
    for game in timeline["games"]:
        game_rows.append((
            game["sequence"], game["game_label"], game["match_uid"],
            game["recorded_at_utc"], game["time_source"],
            game["winning_camp"],
            len(game["players"]),
        ))

    manifest = {
        "type": "marvel_rivals_season_database_export",
        "schema_version": 1,
        "season_id": season_id,
        "game_count": timeline["game_count"],
        "unique_human_players": timeline["player_count"],
        "chronological_order": "Real UTC match time where present; import-time fallback otherwise; ties resolved by game label",
        "timestamp_fallback_games": timeline["fallback_or_unknown_timestamp_count"],
        "standings_rule": timeline["ranking_rules"],
        "source": "Jarvis SQLite match records for the selected season only",
        "files": {
            "leaderboard_timeline.json": "Complete match results and ranked standings after every game",
            "leaderboard_history.csv": "One row per season player per game, including unranked players",
            "games.csv": "Chronological match order, timestamps and recorded winning camp",
            "tables/*.csv": "All stored records in the listed season-scoped source tables, including raw API match JSON text",
        },
        "source_table_row_counts": {
            name: len(rows) for name, (_, rows) in export_tables.items()
        },
        "absent_optional_tables": [
            name for name in SEASON_TABLES if name not in export_tables
        ],
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        archive.writestr("leaderboard_timeline.json", json.dumps(timeline, indent=2, ensure_ascii=False))
        archive.writestr(
            "leaderboard_history.csv",
            _csv_bytes(
                ("sequence", "game_label", "recorded_at_utc", "time_source",
                 "player_uid", "player_name", "rank", "previous_rank",
                 "rank_change", "games", "wins", "losses", "winrate"),
                leaderboard_rows,
            ),
        )
        archive.writestr(
            "games.csv",
            _csv_bytes(
                ("sequence", "game_label", "match_uid",
                 "recorded_at_utc", "time_source", "winning_camp",
                 "human_player_count"),
                game_rows,
            ),
        )
        for name, (columns, rows) in export_tables.items():
            archive.writestr(f"tables/{name}.csv", _csv_bytes(columns, rows))
    buffer.seek(0)
    return buffer
