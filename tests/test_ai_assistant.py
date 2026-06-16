import sqlite3
import unittest
from types import SimpleNamespace

from features.ai_assistant.config import AssistantConfig
from features.ai_assistant.discord_listener import (
    is_command_message,
    should_ignore_message,
    strip_bot_mention,
)
from features.ai_assistant.logging import log_ai_query, QueryLogRecord
from features.ai_assistant.gemini_client import GeminiRateLimitError
from features.ai_assistant.intent_router import detect_intent
from features.ai_assistant.response_formatting import (
    DEFAULT_NOT_CONFIGURED_MESSAGE,
    EMPTY_MENTION_HELP,
    chunk_discord_message,
)
from features.ai_assistant.service import JarvisAIAssistant
from features.ai_assistant.tools import (
    get_best_hero_players,
    get_best_role_players,
    fuzzy_match_player,
    get_current_season,
    get_known_players,
    get_first_place,
    get_highest_win_rate,
    get_player_summary,
    get_top_by_metric,
    get_top_duos,
)


class MockGenerator:
    def __init__(self, response="mocked Jarvis response"):
        self.response = response
        self.prompts = []

    async def generate(self, prompt):
        self.prompts.append(prompt)
        return self.response


class FailingGenerator:
    async def generate(self, prompt):
        raise GeminiRateLimitError("quota")


def make_config(**overrides):
    values = {
        "enabled": True,
        "provider": "gemini",
        "model": "gemini-2.5-flash-lite",
        "gemini_api_key": "test-key",
        "free_only": True,
        "allowed_channel_ids": set(),
        "denied_channel_ids": set(),
        "max_context_rows": 100,
        "max_response_chars": 1800,
        "cooldown_seconds": 0,
        "logging_enabled": True,
        "daily_soft_limit": None,
        "monthly_soft_limit": None,
    }
    values.update(overrides)
    return AssistantConfig(**values)


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO bot_settings (key, value) VALUES ('current_season', '7');

        CREATE TABLE game_stats (
            season_id INTEGER,
            game_label TEXT,
            player TEXT,
            kills INTEGER,
            deaths INTEGER,
            assists INTEGER,
            damage INTEGER,
            damage_taken INTEGER,
            healing INTEGER,
            win INTEGER,
            loss INTEGER,
            mvp INTEGER,
            svp INTEGER,
            timestamp TEXT
        );

        INSERT INTO game_stats VALUES
        (7, 'Game 1', 'LatinMaestro', 20, 10, 5, 12000, 8000, 0, 1, 0, 0, 0, '2026-01-01 10:00:00'),
        (7, 'Game 2', 'LatinMaestro', 8, 14, 11, 9000, 10000, 0, 0, 1, 0, 0, '2026-01-02 10:00:00'),
        (7, 'Game 1', 'NevSONIC', 15, 12, 8, 10000, 7000, 2000, 0, 1, 0, 0, '2026-01-01 10:00:00');

        CREATE TABLE mr_roster (
            player_uid INTEGER PRIMARY KEY,
            player_name TEXT,
            enabled INTEGER
        );
        INSERT INTO mr_roster VALUES
        (1, 'LatinMaestro', 1),
        (2, 'NevSONIC', 1),
        (3, 'Nev Pounder', 1),
        (4, 'Alpha', 1),
        (5, 'Bravo', 1),
        (6, 'Charlie', 1);

        CREATE TABLE hero_cache (
            hero_id TEXT PRIMARY KEY,
            hero_name TEXT,
            updated_at TEXT,
            hero_role TEXT
        );
        INSERT INTO hero_cache VALUES
        ('101', 'Angela', '2026-01-01', 'Strategist'),
        ('102', 'Magneto', '2026-01-01', 'Vanguard');

        CREATE TABLE mr_player_match (
            season_id INTEGER,
            match_uid TEXT,
            game_label TEXT,
            player_uid INTEGER,
            player TEXT,
            is_bot INTEGER,
            camp INTEGER,
            is_win INTEGER,
            kills INTEGER,
            deaths INTEGER,
            assists INTEGER,
            total_hero_damage INTEGER,
            total_hero_heal INTEGER,
            total_damage_taken INTEGER
        );

        CREATE TABLE mr_hero_segments (
            season_id INTEGER,
            match_uid TEXT,
            game_label TEXT,
            player_uid INTEGER,
            player TEXT,
            is_bot INTEGER,
            hero_id TEXT,
            seconds INTEGER,
            kills INTEGER,
            deaths INTEGER,
            assists INTEGER,
            hero_damage INTEGER,
            hero_heal INTEGER,
            damage_taken INTEGER
        );
        """
    )
    leaderboard_rows = []
    match_rows = []
    segment_rows = []
    for index in range(1, 36):
        alpha_win = 1 if index <= 25 else 0
        bravo_win = 1 if index <= 20 else 0
        leaderboard_rows.extend(
            [
                (7, f"LB {index}", "Alpha", 18, 8, 9, 14000, 7000, 1200, alpha_win, 1 - alpha_win, 0, 0, f"2026-02-{index % 28 + 1:02d} 10:00:00"),
                (7, f"LB {index}", "Bravo", 14, 10, 11, 11000, 9000, 2200, bravo_win, 1 - bravo_win, 0, 0, f"2026-02-{index % 28 + 1:02d} 10:00:00"),
                (7, f"LB {index}", "Charlie", 11, 12, 7, 10000, 10000, 400, 0, 1, 0, 0, f"2026-02-{index % 28 + 1:02d} 10:00:00"),
            ]
        )
        match_rows.extend(
            [
                (7, f"m{index}", f"LB {index}", 4, "Alpha", 0, 1, alpha_win, 18, 8, 9, 14000, 1200, 7000),
                (7, f"m{index}", f"LB {index}", 5, "Bravo", 0, 1, alpha_win, 14, 10, 11, 11000, 2200, 9000),
                (7, f"m{index}", f"LB {index}", 6, "Charlie", 0, 2, 0, 11, 12, 7, 10000, 400, 10000),
            ]
        )
        segment_rows.extend(
            [
                (7, f"m{index}", f"LB {index}", 4, "Alpha", 0, "101", 600, 18, 8, 9, 14000, 1200, 7000),
                (7, f"m{index}", f"LB {index}", 5, "Bravo", 0, "102", 600, 14, 10, 11, 11000, 2200, 9000),
            ]
        )
    conn.executemany("INSERT INTO game_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", leaderboard_rows)
    conn.executemany("INSERT INTO mr_player_match VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", match_rows)
    conn.executemany("INSERT INTO mr_hero_segments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", segment_rows)
    return conn


class DiscordListenerTests(unittest.TestCase):
    def test_mention_stripping(self):
        parsed = strip_bot_mention("<@123> roast latin", 123)
        self.assertTrue(parsed.mentioned)
        self.assertEqual(parsed.query, "roast latin")

    def test_nickname_mention_stripping(self):
        parsed = strip_bot_mention("<@!123> who improved?", 123)
        self.assertTrue(parsed.mentioned)
        self.assertEqual(parsed.query, "who improved?")

    def test_non_mentions_and_bot_messages_are_ignored(self):
        self.assertTrue(should_ignore_message(True, "<@123> hello"))
        self.assertFalse(strip_bot_mention("hello", 123).mentioned)

    def test_command_messages_pass_through(self):
        self.assertTrue(is_command_message("!profile LatinMaestro"))


class FormattingTests(unittest.TestCase):
    def test_chunking_respects_limit(self):
        chunks = chunk_discord_message("a" * 25, limit=10)
        self.assertEqual([len(chunk) for chunk in chunks], [10, 10, 5])


class ToolTests(unittest.TestCase):
    def test_current_season_and_player_summary(self):
        conn = make_conn()
        self.assertEqual(get_current_season(conn), 7)
        summary = get_player_summary(conn, "LatinMaestro", 7)
        self.assertEqual(summary["games"], 2)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["losses"], 1)

    def test_fuzzy_player_matching(self):
        conn = make_conn()
        known = get_known_players(conn)
        match = fuzzy_match_player("latin", known)
        self.assertEqual(match.status, "matched")
        self.assertEqual(match.player, "LatinMaestro")
        ambiguous = fuzzy_match_player("nev", known)
        self.assertEqual(ambiguous.status, "ambiguous")

    def test_leaderboard_and_metric_tools_are_read_only_whitelisted(self):
        conn = make_conn()
        first = get_first_place(conn, 7)
        self.assertEqual(first["player"], "Alpha")
        self.assertEqual(first["games"], 35)
        win_rate = get_highest_win_rate(conn, 7, limit=1)
        self.assertEqual(win_rate[0]["player"], "Alpha")
        damage = get_top_by_metric(conn, "damage", 7, limit=1)
        self.assertEqual(damage[0]["player"], "Alpha")
        with self.assertRaises(ValueError):
            get_top_by_metric(conn, 'wins"; DROP TABLE game_stats; --', 7)
        self.assertIsNotNone(conn.execute("SELECT COUNT(*) FROM game_stats").fetchone())

    def test_duo_role_and_hero_tools(self):
        conn = make_conn()
        duos = get_top_duos(conn, 7, limit=1)
        self.assertEqual(duos[0]["players"], ["Alpha", "Bravo"])
        roles = get_best_role_players(conn, "strategist", 7, limit=1)
        self.assertEqual(roles[0]["player"], "Alpha")
        heroes = get_best_hero_players(conn, "Angela", 7, limit=1)
        self.assertTrue(heroes["matched"])
        self.assertEqual(heroes["players"][0]["player"], "Alpha")


class IntentRouterTests(unittest.TestCase):
    def test_detects_broad_stat_intents(self):
        known = get_known_players(make_conn())
        self.assertEqual(detect_intent("who is first place?", known).name, "first_place")
        self.assertEqual(detect_intent("best vanguard?", known).name, "best_role")
        self.assertEqual(detect_intent("best Angela?", known).name, "best_hero")
        self.assertEqual(detect_intent("who has most damage?", known).metric, "damage")


class LoggingTests(unittest.TestCase):
    def test_logging_stores_no_secret_fields(self):
        conn = make_conn()
        log_ai_query(
            conn,
            QueryLogRecord(
                guild_id="1",
                channel_id="2",
                user_id="3",
                user_display_name="Tester",
                question="roast latin",
                tools_used=["get_player_summary"],
                response_preview="mocked",
                error=None,
                detected_intent="player_summary",
                gemini_called=False,
                deterministic_fallback=True,
            ),
        )
        row = conn.execute(
            "SELECT question, tools_used, response_preview, detected_intent, deterministic_fallback FROM ai_query_log"
        ).fetchone()
        self.assertEqual(row[0], "roast latin")
        self.assertIn("get_player_summary", row[1])
        self.assertEqual(row[2], "mocked")
        self.assertEqual(row[3], "player_summary")
        self.assertEqual(row[4], 1)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_mention_help(self):
        assistant = JarvisAIAssistant(make_conn(), make_config(), MockGenerator())
        outcome = await assistant.answer_question("", user_id="1")
        self.assertTrue(outcome.handled)
        self.assertEqual(outcome.reply, EMPTY_MENTION_HELP)

    async def test_disabled_mode_fails_gracefully(self):
        assistant = JarvisAIAssistant(make_conn(), make_config(enabled=False), MockGenerator())
        outcome = await assistant.answer_question("roast latin", user_id="1")
        self.assertEqual(outcome.reply, DEFAULT_NOT_CONFIGURED_MESSAGE)
        self.assertEqual(outcome.reason, "not_configured")

    async def test_missing_gemini_key_fails_gracefully(self):
        assistant = JarvisAIAssistant(make_conn(), make_config(gemini_api_key=""), MockGenerator())
        outcome = await assistant.answer_question("who is first place?", user_id="1")
        self.assertIn("Alpha is first", outcome.reply)
        self.assertEqual(outcome.reason, "deterministic_fallback")

    async def test_mocked_gemini_response_path(self):
        generator = MockGenerator("Latin got cooked, but politely.")
        assistant = JarvisAIAssistant(make_conn(), make_config(), generator)
        outcome = await assistant.answer_question("roast latin", user_id="1")
        self.assertTrue(outcome.handled)
        self.assertIn("LatinMaestro snapshot", outcome.reply)
        self.assertIn("Latin got cooked", outcome.reply)
        self.assertIn("get_player_roast_context", outcome.tools_used)
        self.assertEqual(len(generator.prompts), 1)
        self.assertIn("Deterministic factual answer", generator.prompts[0])

    async def test_stat_answer_survives_gemini_rate_limit(self):
        assistant = JarvisAIAssistant(make_conn(), make_config(), FailingGenerator())
        outcome = await assistant.answer_question("who is first place?", user_id="1")
        self.assertEqual(outcome.reason, "deterministic_fallback")
        self.assertIn("Alpha is first", outcome.reply)

    async def test_pure_chat_without_gemini_uses_generic_message(self):
        assistant = JarvisAIAssistant(make_conn(), make_config(gemini_api_key=""), MockGenerator())
        outcome = await assistant.answer_question("tell me a silly intro", user_id="1")
        self.assertEqual(outcome.reply, DEFAULT_NOT_CONFIGURED_MESSAGE)
        self.assertEqual(outcome.reason, "not_configured")

    async def test_prompt_tells_gemini_not_to_ask_the_bot(self):
        generator = MockGenerator("Alpha is first place. Tiny crown, statistically verified.")
        assistant = JarvisAIAssistant(make_conn(), make_config(), generator)
        outcome = await assistant.answer_question("who is first place?", user_id="1")
        self.assertIn("Alpha is first", outcome.reply)
        self.assertIn("do not tell the user to ask the bot", generator.prompts[0])

    async def test_cooldown_behavior(self):
        assistant = JarvisAIAssistant(make_conn(), make_config(cooldown_seconds=10), MockGenerator())
        first = await assistant.answer_question("hello", user_id="1")
        second = await assistant.answer_question("hello again", user_id="1")
        self.assertEqual(first.reason, "ok")
        self.assertEqual(second.reason, "cooldown")

    async def test_discord_message_non_mentions_ignored(self):
        assistant = JarvisAIAssistant(make_conn(), make_config(), MockGenerator())
        message = SimpleNamespace(
            content="hello",
            author=SimpleNamespace(bot=False, id=1, display_name="Tester"),
            guild=SimpleNamespace(id=10),
            channel=SimpleNamespace(id=20),
        )
        outcome = await assistant.handle_discord_message(message, 999)
        self.assertFalse(outcome.handled)

    async def test_discord_message_bot_ignored(self):
        assistant = JarvisAIAssistant(make_conn(), make_config(), MockGenerator())
        message = SimpleNamespace(
            content="<@999> hello",
            author=SimpleNamespace(bot=True, id=1, display_name="Tester"),
            guild=SimpleNamespace(id=10),
            channel=SimpleNamespace(id=20),
        )
        outcome = await assistant.handle_discord_message(message, 999)
        self.assertFalse(outcome.handled)


if __name__ == "__main__":
    unittest.main()
