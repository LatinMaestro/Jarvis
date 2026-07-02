def get_top_hero_bans(cursor, season_id: int, limit: int = 30) -> list[tuple]:
    """Return hero IDs and season ban-event counts in descending order."""
    cursor.execute(
        """
        SELECT hero_id, COUNT(*) AS ban_events
        FROM hero_bans
        WHERE season_id = ?
        GROUP BY hero_id
        ORDER BY ban_events DESC
        LIMIT ?
        """,
        (season_id, int(limit)),
    )
    return cursor.fetchall()
