import ast
import pathlib
import unittest
from collections import Counter


ROOT = pathlib.Path(__file__).resolve().parents[1]


# Public Discord command surface before the main.py structural refactor.
EXPECTED_COMMANDS = {
    "2v2_records": ("two_v_two_records", ()),
    "4v4_records": ("four_v_four_records", ()),
    "auto_import_cutoff": ("auto_import_cutoff_cmd", ()),
    "auto_import_debug": ("auto_import_debug", ()),
    "auto_import_off": ("auto_import_off", ()),
    "auto_import_on": ("auto_import_on", ()),
    "auto_import_run": ("auto_import_run", ()),
    "auto_import_status": ("auto_import_status", ()),
    "backfill_hero_dht": ("backfill_hero_dht_cmd", ("mr_backfill_hero_dht",)),
    "browse_games": ("browse_games", ()),
    "delete_game": ("delete_game", ()),
    "edit_game": ("edit_game", ()),
    "fairness_debug": ("fairness_debug", ()),
    "h2h": ("head_to_head_cmd", ("head2head", "head_to_head")),
    "helpme": ("helpme", ("helper", "commands", "help_cmds")),
    "hero_bans": ("hero_bans", ()),
    "hero_role_set": ("hero_role_set", ()),
    "hero_roles_check": ("hero_roles_check", ()),
    "hero_synergy": ("hero_synergy", ()),
    "hero_tierlist": ("hero_tierlist", ()),
    "hero_time": ("hero_time", ()),
    "leaderboard_image": ("leaderboard_image", ()),
    "list_seasons": ("list_seasons", ()),
    "low_team": ("low_team", ()),
    "match_history_probe": ("match_history_probe", ()),
    "mr_cleanup_orphans": ("mr_cleanup_orphans", ()),
    "next_teams": ("next_teams", ()),
    "player_bans": ("player_bans", ()),
    "player_heros": ("player_heros", ("player_heroes",)),
    "pregame": ("pregame", ()),
    "profile": ("profile", ()),
    "refresh_heroes": (
        "refresh_heroes_cmd",
        ("refresh_heros", "refresh_hero_cache", "refreshheroes"),
    ),
    "reset_season": ("reset_season", ()),
    "role_distribution": ("role_distribution", ()),
    "role_winrates": ("role_winrates", ("role_wr", "player_role_wr")),
    "roster_add": ("roster_add", ()),
    "roster_list": ("roster_list", ()),
    "roster_remove": ("roster_remove", ()),
    "roster_update_all": ("roster_update_all", ()),
    "run_all_stats": ("run_all_stats", ()),
    "season": ("season", ()),
    "season_movie_pack": ("season_movie_pack", ()),
    "season_overviews": ("season_overviews", ()),
    "season_split_window_set": (
        "season_split_window_set_cmd",
        ("season_half_window_set",),
    ),
    "season_story": ("season_story", ()),
    "season_window_set": ("season_window_set_cmd", ()),
    "season_windows": ("season_windows_cmd", ()),
    "session_overview": ("session_overview", ()),
    "session_players": ("session_players", ()),
    "session_start": ("session_start_cmd", ()),
    "set_season": ("set_season", ()),
    "skipped_draws": (
        "skipped_draws_cmd",
        (
            "skipped_draw_games",
            "draw_skips",
            "skipped_games_draws",
            "skippinggames_draws",
        ),
    ),
    "submit_match": ("submit_match", ()),
    "teammate_role_bans": (
        "teammate_role_bans",
        ("role_ban_matrix", "teammate_ban_matrix"),
    ),
    "teammate_matrix_fair": ("teammate_matrix_fair", ()),
    "teammate_matrix_lowteam_fair": (
        "teammate_matrix_lowteam_fair",
        ("teammate_matrix_low_team_fair",),
    ),
    "top3_stack": ("top3_stack", ("elite_stack", "two_plus_top3")),
    "undelete_match": ("undelete_match", ()),
    "undo_last_game": ("undo_last_game", ()),
    "win_matrix": ("win_matrix", ()),
}

# Existing duplicate definitions whose final declaration currently wins.
KNOWN_DUPLICATE_DEFINITIONS = {
    "_is_bot_player",
    "_serialize_session",
    "ensure_mr_hero_segments_fhsk_cols",
    "upsert_match_into_mr_tables",
}


def _source_trees():
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if relative.parts[0] in {".git", ".tmp", "tests", "__pycache__"}:
            continue
        yield relative, ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _literal_keyword(call, name, default):
    for keyword in call.keywords:
        if keyword.arg == name:
            return ast.literal_eval(keyword.value)
    return default


def _command_inventory():
    inventory = {}
    for relative, tree in _source_trees():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if not isinstance(decorator.func, ast.Attribute):
                    continue
                if decorator.func.attr != "command":
                    continue
                name = _literal_keyword(decorator, "name", node.name)
                aliases = tuple(_literal_keyword(decorator, "aliases", ()))
                if name in inventory:
                    raise AssertionError(f"duplicate command name: {name}")
                inventory[name] = (node.name, aliases, str(relative))
    return inventory


class MainCharacterizationTests(unittest.TestCase):
    def test_public_command_names_aliases_and_callbacks_are_preserved(self):
        actual = {
            name: (callback, aliases)
            for name, (callback, aliases, _path) in _command_inventory().items()
        }
        self.assertEqual(actual, EXPECTED_COMMANDS)

    def test_role_ban_matrix_is_in_run_all_stats(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8-sig"))
        channel_map = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(isinstance(target, ast.Name) and target.id == "STATS_CHANNELS" for target in node.targets):
                channel_map = ast.literal_eval(node.value)
                break
        self.assertIsNotNone(channel_map)
        self.assertEqual(
            channel_map.get("teammate_role_bans"),
            "stats-teammate-role-bans",
        )

    def test_season_story_versatility_requires_five_minutes_per_hero(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8-sig")
        self.assertIn("SS_VERSATILITY_MIN_HERO_SECONDS = 300", source)
        self.assertIn("HAVING sec_elig >= ?", source)
        self.assertIn("int(SS_VERSATILITY_MIN_HERO_SECONDS)", source)

    def test_next_teams_visible_message_format_is_preserved(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8-sig")
        expected_fragments = (
            'lines = [f"**Next Teams (with role restrictions) (score {base_score:.3f})**"]',
            'lines.append(f"🎲 Picked **#{picked_rank} of {picked_pool}**")',
            'return f"{disp(p)} ({_nt_role_emoji((restricted_roles or {}).get(p))})"',
            'f"**{label_a}:** " + ", ".join(_disp_with_restrict(p) for p in sorted(team_a))',
            'f"**{label_b}:** " + ", ".join(_disp_with_restrict(p) for p in sorted(team_b))',
        )
        for fragment in expected_fragments:
            self.assertIn(fragment, source)

    def test_command_names_and_aliases_are_unique(self):
        exposed_names = []
        for name, (_callback, aliases, _path) in _command_inventory().items():
            exposed_names.append(name)
            exposed_names.extend(aliases)
        duplicates = sorted(
            name for name, count in Counter(exposed_names).items() if count > 1
        )
        self.assertEqual(duplicates, [])

    def test_no_new_duplicate_top_level_definitions_are_introduced(self):
        main_tree = ast.parse(
            (ROOT / "main.py").read_text(encoding="utf-8-sig"),
            filename="main.py",
        )
        names = [
            node.name
            for node in main_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        duplicates = {
            name for name, count in Counter(names).items() if count > 1
        }
        self.assertTrue(duplicates.issubset(KNOWN_DUPLICATE_DEFINITIONS))

    def test_discord_ready_event_remains_registered(self):
        events = []
        for _relative, tree in _source_trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                for decorator in node.decorator_list:
                    if (
                        isinstance(decorator, ast.Attribute)
                        and decorator.attr == "event"
                    ):
                        events.append(node.name)
        self.assertEqual(events, ["on_ready"])

    def test_railway_entrypoint_remains_main(self):
        railway = (ROOT / "railway.toml").read_text(encoding="utf-8")
        self.assertIn('startCommand = "python main.py"', railway)

    def test_main_entrypoint_still_runs_the_bot(self):
        main_tree = ast.parse(
            (ROOT / "main.py").read_text(encoding="utf-8-sig"),
            filename="main.py",
        )
        guarded_calls = []
        for node in main_tree.body:
            if not isinstance(node, ast.If):
                continue
            if "__name__" not in ast.unparse(node.test):
                continue
            guarded_calls.extend(
                child
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
            )
        self.assertTrue(
            any(
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "bot"
                and call.func.attr == "run"
                for call in guarded_calls
            )
        )


if __name__ == "__main__":
    unittest.main()
