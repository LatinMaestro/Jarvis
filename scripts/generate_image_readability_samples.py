#!/usr/bin/env python3
"""Generate representative offline PNGs for Jarvis image readability checks."""

import argparse
import importlib
import os
import pathlib
import sys

from PIL import Image

from offline_test_utils import prepare_db_fixture


def _write_png(output_dir: pathlib.Path, name: str, buffer) -> dict[str, object]:
    path = output_dir / name
    path.write_bytes(buffer.getvalue())
    if path.stat().st_size <= 0:
        raise RuntimeError(f"empty image generated: {path}")
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
    return {"file": path.name, "width": width, "height": height, "bytes": path.stat().st_size}


def _hero_rows(count: int) -> list[dict]:
    return [
        {
            "hero_id": 1000 + index,
            "hero_name": f"Representative Hero {index + 1}",
            "seconds": 7200 - index * 173,
            "avg_k": 16.8 - index * 0.21,
            "avg_d": 6.1 + index * 0.08,
            "avg_a": 12.4 - index * 0.12,
            "matches_elig": 32 - index,
            "wins_elig": 20 - index // 2,
            "picks": 34 - index,
            "win_pct": 68.5 - index * 1.45,
        }
        for index in range(count)
    ]


def _profile_pack() -> dict:
    hero_names = {index: f"Representative Hero {index}" for index in range(1, 16)}
    return {
        "season_id": 8,
        "totals": {"games": 84, "wins": 48, "losses": 36, "win_pct": 57.1},
        "streak_txt": "W3",
        "form10": "6-4",
        "snapshot_rows": [
            {"label": label, "value_txt": value, "pct": pct}
            for label, value, pct in [
                ("Win %", "57.1%", 72),
                ("KDA", "4.18", 81),
                ("Deaths / G", "5.72", 67),
                ("Damage / G", "18,942", 76),
                ("Healing / G", "4,830", 55),
                ("Taken / G", "13,101", 63),
                ("Final Hits / G", "8.42", 79),
                ("Solo Kills / G", "2.18", 73),
                ("Accuracy", "42.7%", 69),
            ]
        ],
        "role_share": {"Vanguard": 0.28, "Duelist": 0.47, "Strategist": 0.25},
        "signature_heroes": [
            {"hero_id": index, "seconds": 9800 - index * 510, "win_pct": 69 - index * 2, "games": 18 - index, "kda": 5.1 - index * 0.3}
            for index in range(1, 6)
        ],
        "hero_names": hero_names,
        "best_role": {"role": "Duelist", "win_pct": 61.2, "games": 39},
        "teammate_hero_win": [
            {"hero_id": index, "win_pct": 71 - index, "games": 13 - index}
            for index in range(6, 9)
        ],
        "teammate_hero_risk": [
            {"hero_id": index, "win_pct": 39 + index, "games": 12 - (index - 9)}
            for index in range(9, 12)
        ],
        "chemistry": {
            "eligible_games": 74,
            "baseline": 57.1,
            "best": [
                {"player": f"Reliable Ally {index}", "win_pct": 68 - index, "wins": 10 - index, "games": 14 - index}
                for index in range(1, 4)
            ],
            "worst": [
                {"player": f"Difficult Pairing {index}", "win_pct": 38 + index, "wins": 4, "games": 11 + index}
                for index in range(1, 4)
            ],
            "underused": {"player": "Underused Synergy", "win_pct": 75, "wins": 6, "games": 8},
        },
        "momentum": {"games": 10, "win_pct": 60.0, "deaths_pg": 5.2, "fh_pg": 8.9},
        "enemy_bans": {
            "games": 27,
            "top": [
                {"hero_id": index, "count": 9 - index, "pct": 33 - index * 2}
                for index in range(12, 15)
            ],
        },
    }


def _h2h_player(name: str, win_pct: float) -> dict:
    return {
        "name": name,
        "h2h_games": 24,
        "h2h_wins": round(24 * win_pct / 100),
        "h2h_losses": 24 - round(24 * win_pct / 100),
        "h2h_win_pct": win_pct,
        "h2h_avg_k": 16.4,
        "h2h_avg_d": 6.2,
        "h2h_avg_a": 11.8,
        "h2h_avg_kda": 4.55,
        "h2h_avg_dmg": 18420,
        "h2h_avg_heal": 4910,
        "h2h_avg_taken": 12880,
        "h2h_accuracy": 0.427,
        "h2h_seconds": 19800,
        "h2h_avg_seconds": 825,
        "h2h_hero_pool": 9,
        "h2h_mvp": 5,
        "h2h_svp": 4,
        "season_win_pct": 57.1,
        "low_team_pct": 46.3,
        "low_team_on_less": 19,
        "low_team_uneven": 41,
        "vers_pct": 72.0,
        "vers_heroes": 8,
        "top_hero": "Representative Hero",
        "badges": "Flexible, Clutch, Durable",
        "hero_id": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="marvel_rivals_stats.db")
    parser.add_argument("--output-dir", default=".tmp/image-readability/current")
    args = parser.parse_args()

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    _, fixture = prepare_db_fixture(repo_root, args.db, "image-readability")
    os.environ["MR_DB_PATH"] = str(fixture)
    os.environ["ENABLE_COMMAND_HERO_CACHE_REFRESH"] = "false"
    os.environ["HERO_NAME_API_FALLBACK_ENABLED"] = "false"

    sys.path.insert(0, str(repo_root))
    jarvis = importlib.import_module("main")
    pandas = importlib.import_module("pandas")

    output_dir = (repo_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    heroes = _hero_rows(18)
    results.append(_write_png(output_dir, "player_heroes.png", jarvis._render_player_heros_card("Representative Player", 8, heroes)))
    results.append(_write_png(output_dir, "hero_tierlist.png", jarvis._render_hero_tierlist_card(8, "Humans", heroes, 5, 1, 1, 240)))
    synergy = [
        {"pair_name": f"Representative Hero {index} + Complementary Hero {index}", "win_pct": 72 - index, "games": 24 - index, "wins": 17 - index // 2}
        for index in range(1, 19)
    ]
    results.append(_write_png(output_dir, "hero_synergy.png", jarvis._render_hero_synergy_card(8, "Humans", synergy, 5, 1, 1)))

    players = [f"Representative Player {index}" for index in range(1, 10)]
    session_rows = []
    standings_rows = []
    for index, player in enumerate(players):
        session_rows.append({
            "player": player,
            "player_uid": 9000 + index,
            "wl_str": f"{6 - index % 3}/{2 + index % 3}",
            "winrate": 70 - index * 3.1,
            "avg_kda": 5.2 - index * 0.22,
            "avg_dmg": 19200 - index * 540,
            "avg_heal": 6100 - index * 310,
            "avg_taken": 14100 + index * 260,
            "top_hero_sess": f"Representative Hero {index + 1}",
            "mvp": 3 - index // 4,
            "svp": index // 4,
            "badges": "Clutch, Flexible, Objective Focus",
        })
        standings_rows.append({
            "player": player,
            "wl_str": f"{34 - index}/{24 + index}",
            "winrate": 59 - index * 1.7,
            "rank": index + 1,
            "delta": "+1" if index % 3 == 0 else "=",
        })
    session_df = pandas.DataFrame(session_rows)
    standings_df = pandas.DataFrame(standings_rows)
    results.append(_write_png(output_dir, "session_overview.png", jarvis._render_session_overview_image_api("Snapshot Example", ["G1", "G2", "G3"], session_df, standings_df)))

    a = _h2h_player("Representative Player Alpha", 58.3)
    b = _h2h_player("Representative Player Bravo", 41.7)
    pair = {"a_wins": 14, "b_wins": 10, "opp_games": 24, "duo_wins": 18, "duo_losses": 11, "duo_games": 29}
    results.append(_write_png(output_dir, "head_to_head.png", jarvis._h2h_render_matchup_image("Head to Head - Snapshot Regression", a, b, pair)))

    results.append(_write_png(output_dir, "profile.png", jarvis._render_profile_dashboard("Representative Player", _profile_pack())))

    role_rows = []
    player_names = {}
    for index in range(24):
        uid = 7000 + index
        player_names[uid] = f"Representative Player {index + 1}"
        raw_v = 2 + index % 5
        raw_d = 2 + (index + 2) % 5
        raw_s = 2 + (index + 4) % 5
        total = raw_v + raw_d + raw_s
        role_rows.append({
            "player_uid": uid,
            "v": raw_v / total,
            "d": raw_d / total,
            "s": raw_s / total,
        })
    results.append(_write_png(output_dir, "role_distribution.png", jarvis._rd_render_role_bar_chart(
        season_id=8,
        role_label="Duelist",
        role_key="d",
        role_rows=role_rows,
        player_names=player_names,
    )))

    core = {
        "total_games": 146,
        "unique_players": 24,
        "uneven_games": 41,
        "underdog_wins": 18,
        "date_range": "snapshot fixture",
        "most_active": [(7000 + index, 80 - index * 4, 48 - index * 2) for index in range(5)],
        "improved": [(7000 + index, 8.4 - index, 48.0, 56.4 - index) for index in range(5)],
        "best_duos": [(7000 + index, 7005 + index, 68.0 - index, 14 - index, 20 - index) for index in range(5)],
        "biggest_upset": None,
    }
    versatile = [{"player_uid": 7000 + index, "unique_heroes": 10 - index, "vers_pct": 78 - index * 3, "avg_share": 18 + index} for index in range(5)]
    bot_heroes = [{"hero_id": index + 1, "picks": 30 - index, "wins": 20 - index, "losses": 10, "win_pct": 66 - index * 2} for index in range(5)]
    tier = [{"hero_id": index + 1, "picks": 42 - index, "wins": 27 - index, "win_pct": 64 - index * 2} for index in range(8)]
    synergy_story = [{"a": index + 1, "b": index + 6, "win_pct": 69 - index, "wins": 14 - index, "games": 20 - index} for index in range(5)]
    dominant = [{"hero_id": index + 1, "player_uid": 7000 + index, "win_pct": 70 - index, "wins": 14 - index, "matches": 20 - index} for index in range(5)]
    bans = [{"hero_id": index + 1, "bans": 18 - index * 2} for index in range(5)]
    hero_names = {index: f"Representative Hero {index}" for index in range(1, 16)}
    results.append(_write_png(output_dir, "season_story.png", jarvis._ss_render(
        8, core, player_names, hero_names, versatile, bot_heroes, synergy_story,
        dominant, tier, bans, role_rows,
    )))

    print(f"Generated and validated {len(results)} offline readability samples from copied snapshot fixture:")
    for result in results:
        print(f"- {result['file']}: {result['width']}x{result['height']}, {result['bytes']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
