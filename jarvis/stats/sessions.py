from datetime import datetime, timedelta, timezone

import pandas


DEFAULT_SESSION_GAP_HOURS = 12


def _parse_utc_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_games_grouped_by_local_date(
    cursor,
    season_id: int,
    utc_offset_hours: int = 10,
    session_gap_hours: int = DEFAULT_SESSION_GAP_HOURS,
):
    """Group chronologically adjacent games into play sessions.

    A new session starts only after more than ``session_gap_hours`` without a
    game.  The real match-play timestamp is preferred so crossing midnight or
    importing the same play session in multiple batches does not split it.
    ``match_imports.imported_at`` remains a compatibility fallback.

    Session keys retain the historical ``YYYY-MM-DD`` shape and represent the
    Brisbane-local date on which the session began.  A rare second session
    beginning on the same date receives ``#2`` (and so on).
    """
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mr_match_meta'"
    )
    has_match_meta = cursor.fetchone() is not None

    if has_match_meta:
        cursor.execute(
            """
            SELECT mi.game_label,
                   MIN(COALESCE(NULLIF(mm.match_time_utc, ''), mi.imported_at)) AS played_at
            FROM match_imports mi
            LEFT JOIN mr_match_meta mm
              ON mm.season_id = mi.season_id
             AND mm.match_uid = mi.match_uid
            WHERE mi.season_id=?
            GROUP BY mi.game_label
            """,
            (season_id,),
        )
    else:
        cursor.execute(
            """
            SELECT game_label, MIN(imported_at) AS played_at
            FROM match_imports
            WHERE season_id=?
            GROUP BY game_label
            """,
            (season_id,),
        )

    timed_games = []
    for label, played_at in cursor.fetchall():
        played_utc = _parse_utc_timestamp(played_at)
        if played_utc is not None:
            timed_games.append((played_utc, str(label)))
    timed_games.sort(key=lambda item: (item[0], item[1]))

    gap = timedelta(hours=max(1, int(session_gap_hours)))
    sessions = []
    for played_utc, label in timed_games:
        if not sessions or played_utc - sessions[-1]["last_utc"] > gap:
            sessions.append({
                "start_utc": played_utc,
                "last_utc": played_utc,
                "labels": [label],
            })
        else:
            sessions[-1]["last_utc"] = played_utc
            sessions[-1]["labels"].append(label)

    by_date = {}
    ordered_dates = []
    date_counts = {}
    local_offset = timedelta(hours=int(utc_offset_hours))
    for session in sessions:
        base_date = (session["start_utc"] + local_offset).date().isoformat()
        date_counts[base_date] = date_counts.get(base_date, 0) + 1
        occurrence = date_counts[base_date]
        session_key = base_date if occurrence == 1 else f"{base_date}#{occurrence}"
        ordered_dates.append(session_key)
        by_date[session_key] = list(session["labels"])
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


def load_human_season_standings(cursor, season_id: int) -> pandas.DataFrame:
    """Return the W/L standings from the same source used by ``!leaderboard_image``.

    ``game_stats_v`` is the leaderboard command's primary source.  The API
    player table is used only when that view contains no rows, matching the
    command's existing fallback behaviour.
    """
    try:
        cursor.execute("SELECT player, win, loss FROM game_stats_v")
        rows = cursor.fetchall()
    except Exception:
        rows = []

    if not rows:
        cursor.execute(
            """
            SELECT player, is_win
            FROM mr_player_match
            WHERE season_id=? AND is_bot=0
            """,
            (season_id,),
        )
        rows = [
            (player, 1 if int(is_win or 0) == 1 else 0,
             0 if int(is_win or 0) == 1 else 1)
            for player, is_win in cursor.fetchall()
        ]

    totals = {}
    for player, win, loss in rows:
        key = "".join(str(player or "").split()).lower()
        if not key:
            continue
        entry = totals.setdefault(key, {
            "player": str(player),
            "wins": 0,
            "losses": 0,
        })
        entry["player"] = str(player)
        entry["wins"] += int(win or 0)
        entry["losses"] += int(loss or 0)

    data = []
    for entry in totals.values():
        wins = int(entry["wins"])
        losses = int(entry["losses"])
        games = wins + losses
        if games <= 0:
            continue
        data.append({
            "player": entry["player"],
            "wins": wins,
            "losses": losses,
            "wl_str": f"{wins}/{losses}",
            "winrate": round((wins / games) * 100.0, 1),
        })

    frame = pandas.DataFrame(data)
    if frame.empty:
        return frame
    return frame.sort_values(
        by=["winrate", "wins"], ascending=[False, False]
    ).reset_index(drop=True)
