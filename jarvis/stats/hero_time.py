from collections import defaultdict


def get_hero_time_by_player(
    cursor,
    season_id: int,
    player_name: str | None = None,
) -> dict[str, list[tuple[str, int]]]:
    params = [season_id]
    where = "WHERE season_id = ?"
    if player_name:
        where += " AND player = ?"
        params.append(player_name)

    cursor.execute(
        f"""
        SELECT player, hero_id, SUM(seconds) AS total_seconds
        FROM hero_time_stats
        {where}
        GROUP BY player, hero_id
        ORDER BY player ASC, total_seconds DESC
        """,
        params,
    )
    grouped = defaultdict(list)
    for player, hero_id, total_seconds in cursor.fetchall():
        grouped[player].append((str(hero_id), int(total_seconds)))
    return dict(grouped)
