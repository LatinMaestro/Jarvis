from collections import defaultdict
from itertools import combinations

from jarvis.stats.sessions import load_all_ordered_game_labels

ROLES = ("Vanguard", "Duelist", "Strategist")


def _side_map(camp_values):
    values = {int(value) for value in camp_values if value is not None}
    if values and values <= {0, 1}:
        return {0: 0, 1: 1}
    if values and values <= {1, 2}:
        return {1: 0, 2: 1}
    ordered = sorted(values)
    if len(ordered) >= 2:
        return {ordered[0]: 0, ordered[1]: 1}
    return {}


def _pct(numerator: int, denominator: int):
    return round((numerator / denominator) * 100.0, 1) if denominator else None


def _role_record(seconds_by_role) -> dict:
    seconds = {
        role: round(float(seconds_by_role.get(role, 0.0)), 1)
        for role in (*ROLES, "Unknown")
    }
    known_total = sum(seconds[role] for role in ROLES)
    primary_role = max(ROLES, key=lambda role: seconds[role]) if known_total else "Unknown"
    return {
        "primary_role": primary_role,
        "role_seconds": seconds,
        "known_role_share_pct": {
            role: _pct(seconds[role], known_total) for role in ROLES
        },
    }


def build_fairness_replay(
    season_id: int,
    player_rows,
    ordered_labels,
    role_rows=(),
) -> dict:
    by_game = defaultdict(list)
    names = {}
    for game_label, player_uid, player_name, camp in player_rows:
        if not game_label or player_uid is None:
            continue
        uid = int(player_uid)
        names[uid] = str(player_name or f"UID_{uid}")
        try:
            camp_value = int(camp) if camp is not None else None
        except Exception:
            camp_value = None
        by_game[str(game_label)].append((uid, camp_value))

    labels = [str(label) for label in ordered_labels if str(label) in by_game]
    labels.extend(sorted(label for label in by_game if label not in set(labels)))

    roles_by_game = defaultdict(lambda: defaultdict(float))
    roles_by_player = defaultdict(lambda: defaultdict(float))
    primary_role_games = defaultdict(lambda: defaultdict(int))
    for game_label, player_uid, role_name, seconds in role_rows:
        if not game_label or player_uid is None:
            continue
        role = str(role_name or "Unknown")
        if role not in ROLES:
            role = "Unknown"
        value = max(0.0, float(seconds or 0.0))
        key = (str(game_label), int(player_uid))
        roles_by_game[key][role] += value
        roles_by_player[int(player_uid)][role] += value

    games_played = defaultdict(int)
    uneven_games = defaultdict(int)
    low_team_games = defaultdict(int)
    pair_overlap = defaultdict(int)
    pair_together = defaultdict(int)
    pair_uneven_overlap = defaultdict(int)
    low_pair_together = defaultdict(int)
    games = []

    for sequence, label in enumerate(labels, start=1):
        members = by_game[label]
        mapping = _side_map(camp for _uid, camp in members)
        teams = {0: set(), 1: set()}
        unknown = set()
        for uid, camp in members:
            if camp in mapping:
                teams[mapping[camp]].add(uid)
            else:
                unknown.add(uid)

        present = sorted(teams[0] | teams[1] | unknown)
        for uid in present:
            games_played[uid] += 1
        for first, second in combinations(present, 2):
            pair_overlap[(first, second)] += 1
        for team in (teams[0], teams[1]):
            for first, second in combinations(sorted(team), 2):
                pair_together[(first, second)] += 1

        low_team = None
        if teams[0] and teams[1] and len(teams[0]) != len(teams[1]):
            low_side = 0 if len(teams[0]) < len(teams[1]) else 1
            low_team = f"team_{low_side}"
            known_present = sorted(teams[0] | teams[1])
            for uid in known_present:
                uneven_games[uid] += 1
            for first, second in combinations(known_present, 2):
                pair_uneven_overlap[(first, second)] += 1
            for uid in teams[low_side]:
                low_team_games[uid] += 1
            for first, second in combinations(sorted(teams[low_side]), 2):
                low_pair_together[(first, second)] += 1

        role_usage = []
        for uid in present:
            record = _role_record(roles_by_game[(label, uid)])
            if record["primary_role"] != "Unknown":
                primary_role_games[uid][record["primary_role"]] += 1
            role_usage.append({"player_uid": uid, **record})

        games.append({
            "sequence": sequence,
            "game_label": label,
            "team_0": sorted(teams[0]),
            "team_1": sorted(teams[1]),
            "unknown_team": sorted(unknown),
            "low_team": low_team,
            "role_usage": role_usage,
        })

    players = [{
        "player_uid": uid,
        "player_name": names[uid],
        "games": games_played[uid],
        "uneven_games": uneven_games[uid],
        "low_team_games": low_team_games[uid],
        "low_team_pct": _pct(low_team_games[uid], uneven_games[uid]),
        "role_summary": {
            **_role_record(roles_by_player[uid]),
            "primary_role_games": {
                role: primary_role_games[uid][role] for role in ROLES
            },
        },
    } for uid in sorted(names, key=lambda value: names[value].lower())]

    pairs = []
    for (first, second), overlap in sorted(pair_overlap.items()):
        together = pair_together[(first, second)]
        pairs.append({
            "player_uid_a": first,
            "player_uid_b": second,
            "overlap_games": overlap,
            "teammate_games": together,
            "teammate_pct": _pct(together, overlap),
            "low_team_together_games": low_pair_together[(first, second)],
            "uneven_overlap_games": pair_uneven_overlap[(first, second)],
            "low_team_together_pct_of_uneven_overlap": _pct(
                low_pair_together[(first, second)],
                pair_uneven_overlap[(first, second)],
            ),
        })

    return {
        "schema_version": 1,
        "purpose": "Offline next-teams fairness replay; derived human team assignments only.",
        "season_id": int(season_id),
        "game_count": len(games),
        "players": players,
        "games": games,
        "pairs": pairs,
        "privacy_note": "No raw match JSON, combat stats, Discord IDs, or secrets are included.",
    }


def load_fairness_replay(cursor, season_id: int) -> dict:
    ordered_labels = load_all_ordered_game_labels(cursor, int(season_id))
    cursor.execute(
        """
        SELECT game_label, player_uid, player, camp
        FROM mr_player_match
        WHERE season_id=? AND COALESCE(is_bot, 0)=0
        ORDER BY rowid ASC
        """,
        (int(season_id),),
    )
    player_rows = cursor.fetchall() or []

    role_map = {}
    try:
        cursor.execute(
            "SELECT hero_id, hero_role FROM hero_cache WHERE COALESCE(hero_role, '') <> ''"
        )
        for hero_id, role_name in cursor.fetchall() or []:
            role = str(role_name or "").strip()
            if role in ROLES:
                role_map[str(hero_id).strip()] = role
    except Exception:
        role_map = {}

    role_rows = []
    try:
        cursor.execute(
            """
            SELECT game_label, player_uid, hero_id, SUM(COALESCE(seconds, 0))
            FROM mr_hero_segments
            WHERE season_id=? AND COALESCE(is_bot, 0)=0
            GROUP BY game_label, player_uid, hero_id
            """,
            (int(season_id),),
        )
        for game_label, player_uid, hero_id, seconds in cursor.fetchall() or []:
            role_rows.append(
                (
                    game_label,
                    player_uid,
                    role_map.get(str(hero_id).strip(), "Unknown"),
                    seconds,
                )
            )
    except Exception:
        role_rows = []

    return build_fairness_replay(
        int(season_id), player_rows, ordered_labels, role_rows
    )
