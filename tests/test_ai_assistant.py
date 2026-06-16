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
from features.ai_assistant.response_formatting import (
    DEFAULT_NOT_CONFIGURED_MESSAGE,
    EMPTY_MENTION_HELP,
    chunk_discord_message,
)
from features.ai_assistant.service import JarvisAIAssistant
from features.ai_assistant.tools import (
    fuzzy_match_player,
    get_current_season,
    get_known_players,
    get_player_summary,
)


class MockGenerator:
    def __init__(self, response="mocked Jarvis response"):
        self.response = response
        self.prompts = []

    async def generate(self, prompt):
        self.prompts.append(prompt)
        return self.response


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
        (3, 'Nev Pounder', 1);
        """
    )
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
            ),
        )
        row = conn.execute("SELECT question, tools_used, response_preview FROM ai_query_log").fetchone()
        self.assertEqual(row[0], "roast latin")
        self.assertIn("get_player_summary", row[1])
        self.assertEqual(row[2], "mocked")


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
        outcome = await assistant.answer_question("roast latin", user_id="1")
        self.assertEqual(outcome.reply, DEFAULT_NOT_CONFIGURED_MESSAGE)
        self.assertEqual(outcome.reason, "not_configured")

    async def test_mocked_gemini_response_path(self):
        generator = MockGenerator("Latin got cooked, but politely.")
        assistant = JarvisAIAssistant(make_conn(), make_config(), generator)
        outcome = await assistant.answer_question("roast latin", user_id="1")
        self.assertTrue(outcome.handled)
        self.assertEqual(outcome.reply, "Latin got cooked, but politely.")
        self.assertIn("get_player_roast_context", outcome.tools_used)
        self.assertEqual(len(generator.prompts), 1)

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
