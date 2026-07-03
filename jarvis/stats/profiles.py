def list_human_players(cursor, season_id: int) -> list[dict]:
    cursor.execute(
        """
        SELECT player_uid, player, MAX(rowid)
        FROM mr_player_match
        WHERE season_id=? AND is_bot=0
        GROUP BY player_uid
        ORDER BY LOWER(player) ASC
        """,
        (int(season_id),),
    )
    return [
        {"player_uid": int(uid), "player": str(name or f"UID_{uid}")}
        for uid, name, _rowid in (cursor.fetchall() or [])
        if uid is not None
    ]


def latest_player_name(cursor, season_id: int, player_uid: int) -> str:
    cursor.execute(
        """
        SELECT player FROM mr_player_match
        WHERE season_id=? AND player_uid=? AND is_bot=0
        ORDER BY rowid DESC LIMIT 1
        """,
        (int(season_id), int(player_uid)),
    )
    row = cursor.fetchone()
    return str(row[0]) if row and row[0] else f"UID_{player_uid}"
