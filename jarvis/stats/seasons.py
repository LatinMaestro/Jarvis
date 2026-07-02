def season_game_count(cursor, season_id: int) -> int:
    try:
        cursor.execute(
            "SELECT COUNT(DISTINCT game_label) FROM match_imports WHERE season_id=?",
            (season_id,),
        )
        count = (cursor.fetchone() or [0])[0] or 0
        if count:
            return int(count)
    except Exception:
        pass
    cursor.execute(
        "SELECT COUNT(DISTINCT game_label) FROM game_stats WHERE season_id=?",
        (season_id,),
    )
    return int((cursor.fetchone() or [0])[0] or 0)


def season_date_range(cursor, season_id: int):
    try:
        cursor.execute(
            "SELECT MIN(imported_at), MAX(imported_at) FROM mr_match_meta WHERE season_id=?",
            (season_id,),
        )
        minimum, maximum = cursor.fetchone() or (None, None)
        if minimum and maximum:
            return str(minimum)[:10], str(maximum)[:10]
    except Exception:
        pass
    cursor.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM game_stats WHERE season_id=?",
        (season_id,),
    )
    minimum, maximum = cursor.fetchone() or (None, None)
    if minimum and maximum:
        return str(minimum)[:10], str(maximum)[:10]
    return None, None
