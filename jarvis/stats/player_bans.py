def load_human_player_matches(cursor, season_id: int) -> list[tuple]:
    cursor.execute(
        """
        SELECT match_uid, player, camp
        FROM mr_player_match
        WHERE season_id = ?
          AND COALESCE(is_bot, 0) = 0
          AND match_uid IS NOT NULL
          AND player IS NOT NULL
        """,
        (int(season_id),),
    )
    return cursor.fetchall()


def load_ban_events(cursor, season_id: int) -> list[tuple]:
    cursor.execute(
        """
        SELECT match_uid, battle_side, hero_id
        FROM mr_ban_picks
        WHERE season_id = ?
          AND is_pick = 0
          AND hero_id IS NOT NULL
          AND match_uid IS NOT NULL
        """,
        (int(season_id),),
    )
    return cursor.fetchall()
