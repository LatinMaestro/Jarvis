def get_opponent_match_uids(cursor, season_id: int, uid_a: int, uid_b: int) -> list[str]:
    try:
        cursor.execute(
            """
            SELECT a.match_uid
            FROM mr_player_match a
            JOIN mr_player_match b
              ON b.season_id=a.season_id
             AND b.match_uid=a.match_uid
             AND b.game_label=a.game_label
            WHERE a.season_id=?
              AND a.player_uid=?
              AND b.player_uid=?
              AND COALESCE(a.is_bot,0)=0
              AND COALESCE(b.is_bot,0)=0
              AND a.is_win IS NOT NULL
              AND b.is_win IS NOT NULL
              AND a.is_win != b.is_win
            """,
            (int(season_id), int(uid_a), int(uid_b)),
        )
        return [str(row[0]) for row in (cursor.fetchall() or []) if row and row[0] is not None]
    except Exception:
        return []
