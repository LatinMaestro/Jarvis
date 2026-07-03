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


def load_player_totals(cursor, season_id: int, player_uid: int, match_uids: list[str]):
    if not match_uids:
        return (0, 0, 0, 0, 0, 0, 0, 0, 0)
    placeholders = ",".join("?" for _ in match_uids)
    sql = f"""
        SELECT COUNT(*),
               SUM(CASE WHEN is_win=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN is_win=0 THEN 1 ELSE 0 END),
               SUM(kills), SUM(deaths), SUM(assists),
               SUM(total_hero_damage), SUM(total_hero_heal), SUM(total_damage_taken)
        FROM mr_player_match
        WHERE season_id=? AND player_uid=? AND is_bot=0
          AND match_uid IN ({placeholders})
    """
    try:
        cursor.execute(sql, (int(season_id), int(player_uid), *[str(uid) for uid in match_uids]))
        return cursor.fetchone() or (0, 0, 0, 0, 0, 0, 0, 0, 0)
    except Exception:
        return (0, 0, 0, 0, 0, 0, 0, 0, 0)


def load_accuracy_components(cursor, season_id: int, player_uid: int, match_uids: list[str]):
    if not match_uids:
        return (0, 0)
    placeholders = ",".join("?" for _ in match_uids)
    sql = f"""
        SELECT SUM(CASE WHEN session_hit_rate IS NULL THEN 0 ELSE session_hit_rate * seconds END),
               SUM(CASE WHEN session_hit_rate IS NULL THEN 0 ELSE seconds END)
        FROM mr_hero_segments
        WHERE season_id=? AND player_uid=? AND is_bot=0
          AND match_uid IN ({placeholders})
    """
    try:
        cursor.execute(sql, (int(season_id), int(player_uid), *[str(uid) for uid in match_uids]))
        return cursor.fetchone() or (0, 0)
    except Exception:
        return (0, 0)


def load_total_seconds(cursor, season_id: int, player_uid: int, match_uids: list[str]):
    if not match_uids:
        return 0
    placeholders = ",".join("?" for _ in match_uids)
    try:
        cursor.execute(
            f"SELECT SUM(COALESCE(seconds,0)) FROM mr_hero_segments WHERE season_id=? AND player_uid=? AND is_bot=0 AND match_uid IN ({placeholders})",
            (int(season_id), int(player_uid), *[str(uid) for uid in match_uids]),
        )
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0
