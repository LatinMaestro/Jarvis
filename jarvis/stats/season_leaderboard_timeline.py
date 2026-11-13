"""Chronological, match-by-match leaderboard history for season movie exports.

Use the same ordered match labels as the bot's session commands. All rankings are
computed solely from in-season human player results in ``mr_player_match``.
"""

from collections import defaultdict


def build_season_leaderboard_timeline(cursor, season_id, ordered_game_labels):
    """Return complete match outcomes and cumulative post-game standings.

    Rank players who have appeared by displayed cumulative win percentage
    (one decimal place), then cumulative wins, then stable player UID. A player
    who has not yet entered the season remains unranked (rank=None).

    Missing matches or outcomes are errors: silently omitting one would create
    a plausible-looking but historically incorrect leaderboard animation.
    """
    season_id = int(season_id)
    labels = [str(label) for label in ordered_game_labels]
    if not labels or len(labels) != len(set(labels)):
        raise ValueError("Missing or duplicate chronological game labels for this season")

    cursor.execute(
        """SELECT game_label, match_uid, player_uid, player, camp, is_win
           FROM mr_player_match
           WHERE season_id=? AND COALESCE(is_bot, 0)=0""",
        (season_id,),
    )
    rows_by_game = defaultdict(list)
    player_names = {}
    match_uids = {}
    for label, match_uid, uid, name, camp, is_win in cursor.fetchall():
        label = str(label)
        uid = int(uid)
        if is_win not in (0, 1):
            raise ValueError(f"{label}: missing or invalid human win/loss result")
        if uid <= 0:
            raise ValueError(f"{label}: invalid player UID")
        match_uid = str(match_uid)
        if label in match_uids and match_uids[label] != match_uid:
            raise ValueError(f"{label}: multiple match IDs share a game label")
        match_uids[label] = match_uid
        rows_by_game[label].append((uid, str(name), camp, int(is_win)))

    missing = set(rows_by_game) - set(labels)
    extra = set(labels) - set(rows_by_game)
    if missing or extra:
        raise ValueError(
            f"Chronological match list does not match human results "
            f"({len(missing)} missing from timeline; {len(extra)} without human results)"
        )

    # Choose a consistent display name using the last chronological appearance.
    for label in labels:
        seen = set()
        for uid, name, _camp, _win in rows_by_game[label]:
            if uid in seen:
                raise ValueError(f"{label}: duplicate human result for player {uid}")
            seen.add(uid)
            player_names[uid] = name

    cursor.execute(
        """SELECT mi.game_label, mi.match_uid, mm.match_time_utc, mi.imported_at
           FROM match_imports mi
           LEFT JOIN mr_match_meta mm
             ON mm.season_id=mi.season_id AND mm.match_uid=mi.match_uid
           WHERE mi.season_id=?""",
        (season_id,),
    )
    times = {}
    for label, match_uid, actual_time, imported_at in cursor.fetchall():
        label = str(label)
        if label in times:
            raise ValueError(f"{label}: duplicate import metadata")
        if actual_time and str(actual_time).strip():
            times[label] = (str(actual_time), "match_play_time")
        elif imported_at and str(imported_at).strip():
            times[label] = (str(imported_at), "import_time_fallback")
        else:
            times[label] = (None, "unknown")
    if set(labels) - set(times):
        raise ValueError("One or more games have no chronological import metadata")

    state = {uid: {"games": 0, "wins": 0, "losses": 0} for uid in player_names}
    previous_ranks = {}
    games = []
    fallback_count = 0

    for sequence, label in enumerate(labels, start=1):
        match_players = []
        winning_camps = set()
        for uid, _name, camp, win in sorted(rows_by_game[label], key=lambda row: row[0]):
            state[uid]["games"] += 1
            state[uid]["wins"] += win
            state[uid]["losses"] += 1 - win
            match_players.append({
                "player_uid": uid,
                "player_name": player_names[uid],
                "camp": int(camp) if camp in (0, 1) else None,
                "is_win": bool(win),
            })
            if camp in (0, 1) and win:
                winning_camps.add(int(camp))

        def sort_key(uid):
            current = state[uid]
            win_pct = round(100 * current["wins"] / current["games"], 1)
            return (-win_pct, -current["wins"], uid)

        ranked_uids = sorted(
            (uid for uid in player_names if state[uid]["games"]), key=sort_key
        )
        ranks = {uid: rank for rank, uid in enumerate(ranked_uids, start=1)}
        standings = []
        for uid in sorted(player_names, key=lambda u: (ranks.get(u, 10**9), u)):
            current = state[uid]
            rank = ranks.get(uid)
            old_rank = previous_ranks.get(uid)
            standings.append({
                "player_uid": uid,
                "player_name": player_names[uid],
                "rank": rank,
                "previous_rank": old_rank,
                "rank_change": old_rank - rank if rank is not None and old_rank is not None else None,
                "games": current["games"],
                "wins": current["wins"],
                "losses": current["losses"],
                "winrate": round(100 * current["wins"] / current["games"], 1)
                if current["games"] else None,
            })
        previous_ranks = ranks

        date_value, date_source = times[label]
        fallback_count += date_source != "match_play_time"
        games.append({
            "sequence": sequence,
            "game_label": label,
            "match_uid": match_uids[label],
            "recorded_at_utc": date_value,
            "time_source": date_source,
            "winning_camp": next(iter(winning_camps)) if len(winning_camps) == 1 else None,
            "players": match_players,
            "standings_after": standings,
        })

    return {
        "schema_version": 1,
        "ranking_metric": "cumulative_in_season_winrate",
        "ranking_rules": "Winrate rounded to 1 decimal descending, wins descending, player_uid ascending; unplayed players unranked",
        "game_count": len(games),
        "player_count": len(player_names),
        "fallback_or_unknown_timestamp_count": fallback_count,
        "games": games,
    }
