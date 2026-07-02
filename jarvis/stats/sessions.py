def load_games_grouped_by_local_date(
    cursor,
    season_id: int,
    utc_offset_hours: int = 10,
):
    cursor.execute(
        """
        SELECT game_label, MIN(datetime(imported_at, ?)) AS first_local
        FROM match_imports
        WHERE season_id=?
        GROUP BY game_label
        ORDER BY datetime(first_local) ASC
        """,
        (f"+{utc_offset_hours} hours", season_id),
    )
    by_date = {}
    ordered_dates = []
    for label, first_local in cursor.fetchall():
        date = (first_local or "")[:10]
        if date not in by_date:
            by_date[date] = []
            ordered_dates.append(date)
        by_date[date].append(label)
    return ordered_dates, by_date


def load_all_ordered_game_labels(cursor, season_id: int, utc_offset_hours: int = 10):
    ordered_dates, by_date = load_games_grouped_by_local_date(
        cursor, season_id, utc_offset_hours
    )
    return [label for date in ordered_dates for label in by_date[date]]
