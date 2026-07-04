def load_human_match_rows(cursor, season_id: int) -> list[tuple]:
    cursor.execute(
        """
        SELECT match_uid, player_uid, player, camp, is_win
        FROM mr_player_match
        WHERE season_id = ?
          AND is_bot = 0
          AND match_uid IS NOT NULL
          AND player_uid IS NOT NULL
          AND player IS NOT NULL
        ORDER BY rowid ASC
        """,
        (int(season_id),),
    )
    return cursor.fetchall() or []
