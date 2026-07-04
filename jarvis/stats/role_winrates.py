def load_role_segment_rows(cursor, season_id: int) -> list[tuple]:
    cursor.execute(
        """
        SELECT hs.match_uid, hs.game_label, hs.player_uid, pm.player,
               pm.camp, pm.is_win, hs.hero_id,
               SUM(COALESCE(hs.seconds, 0)) AS sec
        FROM mr_hero_segments hs
        JOIN mr_player_match pm
          ON pm.season_id  = hs.season_id
         AND pm.match_uid  = hs.match_uid
         AND pm.game_label = hs.game_label
         AND pm.player_uid = hs.player_uid
        WHERE hs.season_id = ?
          AND COALESCE(pm.is_bot, 0) = 0
        GROUP BY hs.match_uid, hs.game_label, hs.player_uid, pm.player,
                 pm.camp, pm.is_win, hs.hero_id
        HAVING sec > 0
        """,
        (int(season_id),),
    )
    return cursor.fetchall() or []
