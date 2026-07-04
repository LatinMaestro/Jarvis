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


def load_accuracy_rows(cursor, season_id: int) -> list[tuple]:
    cursor.execute(
        """
        SELECT player_uid,
               SUM(CASE WHEN session_hit_rate IS NOT NULL THEN session_hit_rate * COALESCE(seconds,0) ELSE 0 END),
               SUM(CASE WHEN session_hit_rate IS NOT NULL THEN COALESCE(seconds,0) ELSE 0 END)
        FROM mr_hero_segments
        WHERE season_id=? AND COALESCE(is_bot,0)=0
        GROUP BY player_uid
        """,
        (int(season_id),),
    )
    return cursor.fetchall() or []


def load_season_totals(
    cursor,
    season_id: int,
    player_uid: int,
    include_final_hits: bool,
    include_solo_kills: bool,
):
    final_hits_sql = "SUM(COALESCE(final_hits,0))" if include_final_hits else "0"
    solo_kills_sql = "SUM(COALESCE(solo_kill,0))" if include_solo_kills else "0"
    cursor.execute(
        f"""
        SELECT COUNT(*),
               SUM(CASE WHEN is_win=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN is_win=0 THEN 1 ELSE 0 END),
               SUM(kills), SUM(deaths), SUM(assists),
               SUM(total_hero_damage), SUM(total_damage_taken), SUM(total_hero_heal),
               {final_hits_sql}, {solo_kills_sql}
        FROM mr_player_match
        WHERE season_id=? AND player_uid=? AND is_bot=0
        """,
        (int(season_id), int(player_uid)),
    )
    return cursor.fetchone() or (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
