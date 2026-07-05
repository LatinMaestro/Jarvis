"""Pure scoring helpers for next-teams season fairness."""

from __future__ import annotations

import math
from itertools import combinations
from typing import Mapping


ROLE_BAN_HISTORY_VERSION = 1
ROLE_BAN_KEY_SEPARATOR = "\x1f"


def same_team_probability(team_a_size: int, team_b_size: int) -> float:
    """Return the neutral chance that two lobby members are teammates."""
    a_size = max(0, int(team_a_size))
    b_size = max(0, int(team_b_size))
    lobby_size = a_size + b_size
    if lobby_size < 2:
        return 0.0
    teammate_pairs = math.comb(a_size, 2) + math.comb(b_size, 2)
    return teammate_pairs / math.comb(lobby_size, 2)


def pair_key(player_a: str, player_b: str) -> tuple[str, str]:
    return (player_a, player_b) if player_a < player_b else (player_b, player_a)


def candidate_pair_target_penalty(
    team_a: frozenset[str],
    team_b: frozenset[str],
    *,
    pair_seen: Mapping[tuple[str, str], int],
    pair_together: Mapping[tuple[str, str], int],
    pair_expected: Mapping[tuple[str, str], float],
    max_weight: float = 900.0,
    mean_weight: float = 450.0,
    sample_damp: float = 4.0,
) -> tuple[float, dict]:
    """Score projected pair deviations from lobby-size-aware neutral targets."""
    active = sorted(set(team_a) | set(team_b))
    current_expected = same_team_probability(len(team_a), len(team_b))
    deviations = []
    details = []

    for player_a, player_b in combinations(active, 2):
        key = pair_key(player_a, player_b)
        seen_after = float(pair_seen.get(key, 0)) + 1.0
        expected_after = float(pair_expected.get(key, 0.0)) + current_expected
        same_team = (
            (player_a in team_a and player_b in team_a)
            or (player_a in team_b and player_b in team_b)
        )
        together_after = float(pair_together.get(key, 0)) + (1.0 if same_team else 0.0)
        deviation = (together_after - expected_after) / seen_after
        sample_weight = seen_after / (seen_after + max(0.0, float(sample_damp)))
        weighted_abs = abs(deviation) * math.sqrt(sample_weight)
        deviations.append((deviation * deviation) * sample_weight)
        details.append({
            "pair": key,
            "seen_after": int(seen_after),
            "target_after": expected_after / seen_after,
            "rate_after": together_after / seen_after,
            "deviation": deviation,
            "same_team": bool(same_team),
            "weighted_abs": weighted_abs,
        })

    max_abs = max((row["weighted_abs"] for row in details), default=0.0)
    mean_squared = sum(deviations) / len(deviations) if deviations else 0.0
    penalty = (float(max_weight) * (max_abs ** 2)) + (float(mean_weight) * mean_squared)
    return penalty, {
        "neutral_probability": current_expected,
        "max_weighted_deviation": max_abs,
        "mean_weighted_squared_deviation": mean_squared,
        "pairs": details,
    }


def dynamic_pair_lock_limit(
    key: tuple[str, str],
    *,
    pair_seen: Mapping[tuple[str, str], int],
    pair_expected: Mapping[tuple[str, str], float],
    current_neutral_probability: float,
    margin: float = 0.10,
    minimum_seen: int = 6,
) -> float | None:
    """Return a sample-aware upper teammate-rate lock, or None if too early."""
    seen = int(pair_seen.get(key, 0))
    if seen < int(minimum_seen):
        return None
    target = (
        float(pair_expected.get(key, 0.0)) + float(current_neutral_probability)
    ) / (seen + 1)
    return min(1.0, target + float(margin))


def role_ban_history_key(receiver: str, teammate: str, banned_role: str) -> str:
    return ROLE_BAN_KEY_SEPARATOR.join((str(receiver), str(teammate), str(banned_role)))


def normalise_role_ban_history(value: object) -> dict:
    if not isinstance(value, dict):
        return {"version": ROLE_BAN_HISTORY_VERSION, "entries": {}, "rolls": []}
    entries = value.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    clean = {}
    for key, row in entries.items():
        if not isinstance(key, str) or not isinstance(row, dict):
            continue
        try:
            clean[key] = {
                "opportunities": max(0, int(row.get("opportunities", 0))),
                "expected": max(0.0, float(row.get("expected", 0.0))),
                "together": max(0, int(row.get("together", 0))),
            }
        except (TypeError, ValueError):
            continue
    rolls = []
    for roll in value.get("rolls", []):
        if not isinstance(roll, dict):
            continue
        team_a = sorted(str(player) for player in roll.get("team_a", []) if player)
        team_b = sorted(str(player) for player in roll.get("team_b", []) if player)
        restrictions = roll.get("restricted_roles")
        if not team_a or not team_b or not isinstance(restrictions, dict):
            continue
        rolls.append({
            "sequence": len(rolls) + 1,
            "team_a": team_a,
            "team_b": team_b,
            "restricted_roles": {
                str(player): str(role)
                for player, role in restrictions.items()
                if player and role
            },
        })
    return {"version": ROLE_BAN_HISTORY_VERSION, "entries": clean, "rolls": rolls}


def record_role_ban_exposure(
    history: object,
    team_a: frozenset[str],
    team_b: frozenset[str],
    restricted_roles: Mapping[str, str],
) -> dict:
    """Record one committed roll without storing player or match source data."""
    updated = normalise_role_ban_history(history)
    entries = updated["entries"]
    active = sorted(set(team_a) | set(team_b))
    expected_same = same_team_probability(len(team_a), len(team_b))

    for receiver in active:
        for teammate in active:
            if receiver == teammate:
                continue
            banned_role = restricted_roles.get(teammate)
            if not banned_role:
                continue
            key = role_ban_history_key(receiver, teammate, banned_role)
            row = entries.setdefault(key, {"opportunities": 0, "expected": 0.0, "together": 0})
            row["opportunities"] += 1
            row["expected"] += expected_same
            if (
                (receiver in team_a and teammate in team_a)
                or (receiver in team_b and teammate in team_b)
            ):
                row["together"] += 1
    updated["rolls"].append({
        "sequence": len(updated["rolls"]) + 1,
        "team_a": sorted(team_a),
        "team_b": sorted(team_b),
        "restricted_roles": {
            str(player): str(restricted_roles[player])
            for player in sorted(restricted_roles)
            if restricted_roles.get(player)
        },
    })
    return updated


def candidate_role_ban_exposure_penalty(
    team_a: frozenset[str],
    team_b: frozenset[str],
    restricted_roles: Mapping[str, str],
    history: object,
    *,
    mean_weight: float = 140.0,
    max_weight: float = 60.0,
    sample_damp: float = 4.0,
) -> tuple[float, dict]:
    """Softly spread each teammate's role-specific bans among receivers."""
    entries = normalise_role_ban_history(history)["entries"]
    active = sorted(set(team_a) | set(team_b))
    current_expected = same_team_probability(len(team_a), len(team_b))
    squared = []
    details = []

    for receiver in active:
        for teammate in active:
            if receiver == teammate:
                continue
            banned_role = restricted_roles.get(teammate)
            if not banned_role:
                continue
            row = entries.get(
                role_ban_history_key(receiver, teammate, banned_role),
                {"opportunities": 0, "expected": 0.0, "together": 0},
            )
            opportunities_after = int(row["opportunities"]) + 1
            expected_after = float(row["expected"]) + current_expected
            same_team = (
                (receiver in team_a and teammate in team_a)
                or (receiver in team_b and teammate in team_b)
            )
            together_after = int(row["together"]) + (1 if same_team else 0)
            deviation = (together_after - expected_after) / opportunities_after
            sample_weight = opportunities_after / (opportunities_after + max(0.0, float(sample_damp)))
            weighted_abs = abs(deviation) * math.sqrt(sample_weight)
            squared.append((deviation * deviation) * sample_weight)
            details.append({
                "receiver": receiver,
                "teammate": teammate,
                "banned_role": banned_role,
                "opportunities_after": opportunities_after,
                "deviation": deviation,
                "weighted_abs": weighted_abs,
            })

    max_abs = max((row["weighted_abs"] for row in details), default=0.0)
    mean_squared = sum(squared) / len(squared) if squared else 0.0
    penalty = (float(mean_weight) * mean_squared) + (float(max_weight) * (max_abs ** 2))
    return penalty, {
        "max_weighted_deviation": max_abs,
        "mean_weighted_squared_deviation": mean_squared,
        "records_scored": len(details),
    }
