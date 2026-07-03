def load_hero_cache_rows(cursor) -> list[tuple]:
    cursor.execute("SELECT hero_id, hero_name, hero_role FROM hero_cache")
    return cursor.fetchall() or []


def load_hero_name_rows(cursor) -> list[tuple]:
    cursor.execute("SELECT hero_id, hero_name FROM hero_cache")
    return cursor.fetchall() or []


def load_season_hero_usage(cursor, season_id: int) -> list[tuple]:
    cursor.execute(
        """
        SELECT hero_id, SUM(COALESCE(seconds,0)) AS sec
        FROM mr_hero_segments
        WHERE season_id=?
        GROUP BY hero_id
        HAVING sec > 0
        ORDER BY sec DESC
        """,
        (int(season_id),),
    )
    return cursor.fetchall() or []
