def get_recent_games(cursor, season_id: int, limit: int) -> list[tuple]:
    cursor.execute(
        """
        SELECT game_label, match_uid, match_time_utc, imported_at
        FROM mr_match_meta
        WHERE season_id=?
        ORDER BY datetime(imported_at) DESC
        LIMIT ?
        """,
        (season_id, limit),
    )
    rows = cursor.fetchall() or []
    if rows:
        return rows

    cursor.execute(
        """
        SELECT game_label, match_uid, imported_at
        FROM match_imports
        WHERE season_id=?
        ORDER BY datetime(imported_at) DESC
        LIMIT ?
        """,
        (season_id, limit),
    )
    imported = cursor.fetchall() or []
    if imported:
        return [(label, uid, None, timestamp) for label, uid, timestamp in imported]

    cursor.execute(
        """
        SELECT game_label, MAX(timestamp) AS ts
        FROM game_stats_v
        GROUP BY game_label
        ORDER BY MAX(timestamp) DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [(label, None, None, timestamp) for label, timestamp in (cursor.fetchall() or [])]
