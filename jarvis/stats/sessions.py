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


def aggregate_wl_for_labels(cursor, season_id: int, labels: list[str]) -> pandas.DataFrame:
    if not labels:
        return pandas.DataFrame()
    placeholders = ",".join("?" for _ in labels)
    cursor.execute(
        f"""
        SELECT pm.player_uid, MAX(pm.player) AS player,
               SUM(CASE WHEN pm.is_win=1 THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN pm.is_win=0 THEN 1 ELSE 0 END) AS losses
        FROM mr_player_match pm
        WHERE pm.season_id=? AND pm.is_bot=0
          AND pm.game_label IN ({placeholders})
        GROUP BY pm.player_uid
        """,
        (season_id, *labels),
    )
    data = []
    for uid, player, wins, losses in cursor.fetchall():
        wins = int(wins or 0)
        losses = int(losses or 0)
        games = wins + losses
        if games > 0:
            data.append({"player_uid": int(uid), "player": str(player), "wins": wins, "losses": losses, "wl_str": f"{wins}/{losses}", "winrate": round((wins / games) * 100.0, 1)})
    frame = pandas.DataFrame(data)
    if frame.empty:
        return frame
    return frame.sort_values(by=["winrate", "wins"], ascending=[False, False]).reset_index(drop=True)
import pandas

