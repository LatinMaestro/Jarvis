from collections import defaultdict



def _top3_more_side_map(camp_values):
    """
    Robustly map raw camp values into team 0 / team 1 on a per-match basis.
    Supports either {0,1} or {1,2}. Falls back to the first two sorted values.
    """
    vals = {int(v) for v in camp_values if v is not None}
    if vals == {0, 1} or vals <= {0, 1}:
        return {0: 0, 1: 1}
    if vals == {1, 2} or vals <= {1, 2}:
        return {1: 0, 2: 1}

    ordered = sorted(vals)
    if len(ordered) >= 2:
        return {ordered[0]: 0, ordered[1]: 1}
    return None


def build_top3_base(raw_rows, top3_uids: list[int]) -> dict:
    """
    Builds base counts for the selected top 3.

    Qualifying match:
      - one team had MORE of the selected top 3 than the other team
      - examples: 1-0, 2-0, 2-1, 3-0, 3-1, 3-2

    Returns base rows with:
      - all-game totals
      - qualifying-game totals
      - advantaged-team totals
      - against-advantaged-team totals
    """
    top3_set = {int(x) for x in (top3_uids or []) if x is not None}

    if len(top3_set) != 3:
        raise ValueError("Exactly 3 selected players are required.")

    if not raw_rows:
        return {
            "rows_base": [],
            "summary": {
                "total_matches": 0,
                "qualifying_matches": 0,
                "equal_matches": 0,
                "no_selected_matches": 0,
                "balanced_selected_matches": 0,
                "diff1_matches": 0,
                "diff2plus_matches": 0,
            },
        }

    by_match_raw = defaultdict(list)
    display_name = {}

    for match_uid, uid, player, camp, is_win in raw_rows:
        try:
            uid_i = int(uid)
        except Exception:
            continue

        match_s = str(match_uid or "").strip()
        player_s = str(player or "").strip() or f"UID_{uid_i}"

        if not match_s:
            continue

        try:
            camp_i = int(camp)
        except Exception:
            continue

        is_win_i = 1 if int(is_win or 0) == 1 else 0
        display_name[uid_i] = player_s
        by_match_raw[match_s].append((uid_i, player_s, camp_i, is_win_i))

    all_games = defaultdict(int)
    all_wins = defaultdict(int)

    qual_games = defaultdict(int)
    qual_wins = defaultdict(int)

    more_games = defaultdict(int)
    more_wins = defaultdict(int)
    more_by1 = defaultdict(int)
    more_by2plus = defaultdict(int)

    vs_more_games = defaultdict(int)
    vs_more_wins = defaultdict(int)

    total_matches = 0
    qualifying_matches = 0
    equal_matches = 0
    no_selected_matches = 0
    balanced_selected_matches = 0
    diff1_matches = 0
    diff2plus_matches = 0

    for _match_uid, members in by_match_raw.items():
        side_map = _top3_more_side_map([m[2] for m in members])
        if not side_map:
            continue

        teams = {0: [], 1: []}
        valid_rows = 0

        for uid_i, player_s, camp_i, is_win_i in members:
            if camp_i not in side_map:
                continue
            side = side_map[camp_i]
            teams[side].append((uid_i, player_s, is_win_i))
            all_games[uid_i] += 1
            all_wins[uid_i] += is_win_i
            valid_rows += 1

        if valid_rows == 0:
            continue

        total_matches += 1

        team0 = teams.get(0) or []
        team1 = teams.get(1) or []

        top0 = sum(1 for uid_i, _nm, _w in team0 if uid_i in top3_set)
        top1 = sum(1 for uid_i, _nm, _w in team1 if uid_i in top3_set)
        diff = top0 - top1

        if diff == 0:
            equal_matches += 1
            if top0 == 0:
                no_selected_matches += 1
            else:
                balanced_selected_matches += 1
            continue

        qualifying_matches += 1
        if abs(diff) == 1:
            diff1_matches += 1
        else:
            diff2plus_matches += 1

        for uid_i, _nm, is_win_i in (team0 + team1):
            qual_games[uid_i] += 1
            qual_wins[uid_i] += is_win_i

        advantaged_team = 0 if diff > 0 else 1
        disadvantaged_team = 1 if diff > 0 else 0

        for uid_i, _nm, is_win_i in teams[advantaged_team]:
            more_games[uid_i] += 1
            more_wins[uid_i] += is_win_i
            if abs(diff) == 1:
                more_by1[uid_i] += 1
            else:
                more_by2plus[uid_i] += 1

        for uid_i, _nm, is_win_i in teams[disadvantaged_team]:
            vs_more_games[uid_i] += 1
            vs_more_wins[uid_i] += is_win_i

    rows_base = []
    all_uids = sorted(display_name.keys(), key=lambda u: display_name[u].lower())

    for uid_i in all_uids:
        rows_base.append({
            "player_uid": uid_i,
            "player": display_name.get(uid_i, f"UID_{uid_i}"),
            "is_top3": uid_i in top3_set,
            "all_games": int(all_games.get(uid_i, 0)),
            "all_wins": int(all_wins.get(uid_i, 0)),
            "qual_games": int(qual_games.get(uid_i, 0)),
            "qual_wins": int(qual_wins.get(uid_i, 0)),
            "more_games": int(more_games.get(uid_i, 0)),
            "more_wins": int(more_wins.get(uid_i, 0)),
            "more_by1": int(more_by1.get(uid_i, 0)),
            "more_by2plus": int(more_by2plus.get(uid_i, 0)),
            "vs_more_games": int(vs_more_games.get(uid_i, 0)),
            "vs_more_wins": int(vs_more_wins.get(uid_i, 0)),
        })

    return {
        "rows_base": rows_base,
        "summary": {
            "total_matches": total_matches,
            "qualifying_matches": qualifying_matches,
            "equal_matches": equal_matches,
            "no_selected_matches": no_selected_matches,
            "balanced_selected_matches": balanced_selected_matches,
            "diff1_matches": diff1_matches,
            "diff2plus_matches": diff2plus_matches,
        },
    }
