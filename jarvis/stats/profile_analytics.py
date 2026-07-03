import math
from typing import Optional


def normalise_side(value):
    try:
        side = int(value)
    except Exception:
        return None
    if side in (0, 1):
        return side
    if side in (1, 2):
        return side - 1
    return None


def percentile(
    values: list[float],
    my_value: float,
    *,
    higher_is_better: bool = True,
) -> Optional[float]:
    cleaned = [
        float(value)
        for value in values
        if value is not None
        and not (isinstance(value, float) and math.isnan(value))
    ]
    if not cleaned:
        return None
    if not higher_is_better:
        cleaned = [-value for value in cleaned]
        mine = -float(my_value)
    else:
        mine = float(my_value)
    below = sum(1 for value in cleaned if value < mine)
    equal = sum(1 for value in cleaned if value == mine)
    return 100.0 * (below + 0.5 * equal) / len(cleaned)


def role_bucket(role_text: str) -> Optional[str]:
    role = (role_text or "").strip().lower()
    if "vanguard" in role:
        return "Vanguard"
    if "duelist" in role:
        return "Duelist"
    if "strateg" in role:
        return "Strategist"
    return None


def form_string(sequence: list[int], length: int) -> str:
    if len(sequence) < length:
        return "N/A"
    return "".join("W" if result == 1 else "L" for result in sequence[-length:])


def current_streak(sequence: list[int]) -> int:
    if not sequence:
        return 0
    streak_type = sequence[-1]
    run = 0
    for result in reversed(sequence):
        if result != streak_type:
            break
        run += 1
    return run if streak_type == 1 else -run


def streak_text(streak: int) -> str:
    if streak > 0:
        return f"{streak}W"
    if streak < 0:
        return f"{abs(streak)}L"
    return "0"


def pick_best_role(role_winrates: dict[str, dict], *, min_games: int = 4):
    candidates = []
    for role, values in role_winrates.items():
        games = int(values.get("games", 0) or 0)
        if games >= min_games:
            candidates.append(
                {
                    "role": role,
                    "games": games,
                    "win_pct": float(values.get("win_pct", 0.0) or 0.0),
                }
            )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["win_pct"], item["games"]), reverse=True)
    return candidates[0]


def signature_heroes(
    hero_stats: list[dict],
    *,
    min_games: int = 5,
    limit: int = 5,
) -> list[dict]:
    eligible = [
        hero for hero in hero_stats if int(hero.get("games", 0) or 0) >= min_games
    ]
    eligible.sort(
        key=lambda hero: (
            float(hero.get("win_pct", 0.0) or 0.0),
            int(hero.get("games", 0) or 0),
            int(hero.get("seconds", 0) or 0),
        ),
        reverse=True,
    )
    return eligible[:limit]


def build_snapshot_rows(
    all_metrics: dict[int, dict],
    mine: dict,
    *,
    enable_pct: bool,
) -> list[dict]:
    def metric_values(key):
        return [values[key] for values in all_metrics.values()]

    def pct(values, value, higher=True):
        return percentile(values, value, higher_is_better=higher) if enable_pct else None

    rows = [
        {"label": "Win %", "value_txt": f"{mine['win_pct']:.1f}%", "pct": pct(metric_values("win_pct"), mine["win_pct"])},
        {"label": "KDA", "value_txt": f"{mine['kda']:.2f}", "pct": pct(metric_values("kda"), mine["kda"])},
        {"label": "Deaths / G", "value_txt": f"{mine['deaths_pg']:.2f}", "pct": pct(metric_values("deaths_pg"), mine["deaths_pg"], False)},
        {"label": "Damage / G", "value_txt": f"{mine['dmg_pg']:.0f}", "pct": pct(metric_values("dmg_pg"), mine["dmg_pg"])},
        {"label": "Healing / G", "value_txt": f"{mine['heal_pg']:.0f}", "pct": pct(metric_values("heal_pg"), mine["heal_pg"])},
        {"label": "Taken / G", "value_txt": f"{mine['taken_pg']:.0f}", "pct": pct(metric_values("taken_pg"), mine["taken_pg"])},
        {"label": "Final Hits / G", "value_txt": f"{mine['fh_pg']:.2f}", "pct": pct(metric_values("fh_pg"), mine["fh_pg"])},
        {"label": "Solo Kills / G", "value_txt": f"{mine['sk_pg']:.2f}", "pct": pct(metric_values("sk_pg"), mine["sk_pg"])},
    ]
    accuracy_values = [
        values["acc"] for values in all_metrics.values() if values.get("acc") is not None
    ]
    if mine.get("acc") is None or not accuracy_values:
        rows.append({"label": "Accuracy", "value_txt": "\u2014", "pct": None})
    else:
        rows.append(
            {
                "label": "Accuracy",
                "value_txt": f"{mine['acc'] * 100:.1f}%",
                "pct": pct(accuracy_values, mine["acc"]),
            }
        )
    return rows


def collect_hero_ids(pack: dict) -> set[int]:
    hero_ids = set()
    for hero in pack.get("signature_heroes", []):
        hero_ids.add(int(hero["hero_id"]))
    for ban in pack.get("enemy_bans", {}).get("top", []):
        hero_ids.add(int(ban["hero_id"]))
    for key in ("teammate_hero_win", "teammate_hero_risk"):
        for hero in pack.get(key, []):
            hero_ids.add(int(hero["hero_id"]))
    return hero_ids
