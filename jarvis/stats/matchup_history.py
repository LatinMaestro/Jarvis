"""Exact-lobby matchup history and non-invasive diversity selection.

This module does not calculate fairness: it selects among candidates already
scored and filtered by the existing !next_teams engine.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone


def matchup_key(team_a, team_b):
    """Team order and player order are irrelevant; lobby membership is explicit."""
    a, b = tuple(sorted(str(p) for p in team_a)), tuple(sorted(str(p) for p in team_b))
    if not a or not b or set(a) & set(b):
        raise ValueError("Matchup requires two nonempty, disjoint teams")
    return tuple(sorted(a + b)), tuple(sorted((a, b)))


def imported_matchups(rows):
    """Build imported matchups from (match_uid, player_uid, camp, match_time_utc) rows.

    Only complete human camp assignments are accepted. Missing camp values are
    skipped rather than inferring teams from win/loss (which fails on draws).
    """
    games = defaultdict(lambda: {0: set(), 1: set(), "time": None, "bad": False})
    for match_uid, player_uid, camp, match_time in rows:
        if match_uid is None or player_uid is None:
            continue
        record = games[str(match_uid)]
        if camp not in (0, 1):
            record["bad"] = True
            continue
        record[int(camp)].add("u" + str(int(player_uid)))
        record["time"] = record["time"] or match_time
    result = []
    for record in games.values():
        if record["bad"] or not record[0] or not record[1]:
            continue
        try:
            result.append((matchup_key(record[0], record[1]), _epoch(record["time"])))
        except ValueError:
            continue
    return result


def _epoch(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def combined_matchup_counts(imported, session_games, season_id, match_window_seconds=10800):
    """Merge imported and provisional games without counting clear imports twice.

    An imported match reconciles one session roll only when teams are identical
    and its actual match timestamp is within 3 hours AFTER roll generation.
    Uncertain records remain counted (conservative repeat avoidance).
    """
    counts = Counter(key for key, _ in imported)
    per_key = defaultdict(list)
    for key, timestamp in imported:
        if timestamp is not None:
            per_key[key].append(float(timestamp))
    consumed = defaultdict(set)
    for game in session_games or []:
        if int(game.get("season_id") or season_id) != int(season_id):
            continue
        try:
            key = matchup_key(game.get("team_a") or [], game.get("team_b") or [])
        except ValueError:
            continue
        created = _epoch(game.get("generated_at_epoch"))
        matched = False
        if created is not None:
            for index, played in enumerate(per_key.get(key, [])):
                if index not in consumed[key] and -300 <= played - created <= match_window_seconds:
                    consumed[key].add(index)
                    matched = True
                    break
        if not matched:
            counts[key] += 1
    return counts


def choose_diverse_candidate(scored_candidates, history_counts, absolute_tolerance=25.0,
                             relative_tolerance=0.03):
    """Choose least repeated candidate within a narrow band of best fairness.

    Entries are (score, internal_id, metadata). All fairness hard-filtering must
    occur BEFORE calling this function. The best-scoring option always remains
    eligible, so diversity cannot make team generation fail.
    """
    if not scored_candidates:
        return None, {"eligible": 0, "reason": "no_candidates"}
    baseline = min(scored_candidates, key=lambda item: (item[0], item[1]))
    limit = baseline[0] + max(float(absolute_tolerance),
                              abs(float(baseline[0])) * float(relative_tolerance))
    eligible = [entry for entry in scored_candidates if entry[0] <= limit]
    def frequency(entry):
        try:
            meta = entry[2]
            return int(history_counts.get(matchup_key(meta["team_a"], meta["team_b"]), 0))
        except (KeyError, ValueError, TypeError):
            return 0
    picked = min(eligible, key=lambda entry: (frequency(entry), entry[0], entry[1]))
    return picked, {
        "eligible": len(eligible),
        "evaluated": len(scored_candidates),
        "fairness_best": float(baseline[0]),
        "fairness_selected": float(picked[0]),
        "selected_repeat_count": frequency(picked),
        "best_repeat_count": frequency(baseline),
        "unused_eligible": sum(frequency(entry) == 0 for entry in eligible),
        "reason": "diversity" if picked != baseline else "best_fairness",
    }
