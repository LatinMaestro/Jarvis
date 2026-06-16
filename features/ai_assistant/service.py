from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from .config import AssistantConfig
from .context_builders import build_stat_context
from .discord_listener import is_command_message, should_ignore_message, strip_bot_mention
from .gemini_client import GeminiClient, GeminiError, GeminiRateLimitError
from .logging import QueryLogRecord, log_ai_query
from .prompts import build_prompt
from .response_formatting import DEFAULT_NOT_CONFIGURED_MESSAGE, EMPTY_MENTION_HELP, clamp_response


class TextGenerator(Protocol):
    async def generate(self, prompt: str) -> str:
        ...


@dataclass
class AssistantOutcome:
    handled: bool
    reply: str | None = None
    tools_used: list[str] = field(default_factory=list)
    reason: str | None = None


@dataclass
class _LimitCounter:
    day_key: str = ""
    month_key: str = ""
    day_count: int = 0
    month_count: int = 0

    def check_and_increment(self, config: AssistantConfig) -> bool:
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")
        if day != self.day_key:
            self.day_key = day
            self.day_count = 0
        if month != self.month_key:
            self.month_key = month
            self.month_count = 0
        if config.daily_soft_limit is not None and self.day_count >= config.daily_soft_limit:
            return False
        if config.monthly_soft_limit is not None and self.month_count >= config.monthly_soft_limit:
            return False
        self.day_count += 1
        self.month_count += 1
        return True


class JarvisAIAssistant:
    def __init__(
        self,
        conn: sqlite3.Connection,
        config: AssistantConfig | None = None,
        generator: TextGenerator | None = None,
    ) -> None:
        self.conn = conn
        self.config = config or AssistantConfig.from_env()
        self.generator = generator or GeminiClient(self.config)
        self._cooldowns: dict[str, float] = {}
        self._limits = _LimitCounter()

    async def handle_discord_message(self, message: object, bot_user_id: int | str | None) -> AssistantOutcome:
        author = getattr(message, "author", None)
        author_is_bot = bool(getattr(author, "bot", False))
        content = getattr(message, "content", "") or ""

        if should_ignore_message(author_is_bot, content):
            return AssistantOutcome(False, reason="ignored")

        # Preserve existing command semantics. main.py still calls process_commands first.
        if is_command_message(content):
            return AssistantOutcome(False, reason="command")

        parsed = strip_bot_mention(content, bot_user_id)
        if not parsed.mentioned:
            return AssistantOutcome(False, reason="not_mentioned")

        guild = getattr(message, "guild", None)
        channel = getattr(message, "channel", None)
        return await self.answer_question(
            question=parsed.query,
            guild_id=getattr(guild, "id", None),
            channel_id=getattr(channel, "id", None),
            user_id=getattr(author, "id", None),
            user_display_name=getattr(author, "display_name", None) or getattr(author, "name", None),
        )

    async def answer_question(
        self,
        question: str,
        guild_id: int | str | None = None,
        channel_id: int | str | None = None,
        user_id: int | str | None = None,
        user_display_name: str | None = None,
    ) -> AssistantOutcome:
        clean_question = (question or "").strip()
        if not clean_question:
            return AssistantOutcome(True, reply=EMPTY_MENTION_HELP, reason="empty_mention")

        if not self.config.is_channel_allowed(channel_id):
            return AssistantOutcome(False, reason="channel_blocked")

        cooldown_reply = self._check_cooldown(user_id)
        if cooldown_reply:
            return AssistantOutcome(True, reply=cooldown_reply, reason="cooldown")

        if not self.config.enabled:
            self._safe_log(
                guild_id,
                channel_id,
                user_id,
                user_display_name,
                clean_question,
                [],
                None,
                "not_configured",
                "not_configured",
                False,
                False,
            )
            return AssistantOutcome(True, reply=DEFAULT_NOT_CONFIGURED_MESSAGE, reason="not_configured")

        context = build_stat_context(self.conn, clean_question, self.config.max_context_rows)
        if context.clarification:
            self._safe_log(
                guild_id,
                channel_id,
                user_id,
                user_display_name,
                clean_question,
                context.tools_used,
                context.clarification,
                None,
                context.intent_name,
                False,
                True,
            )
            return AssistantOutcome(True, reply=context.clarification, tools_used=context.tools_used, reason="clarification")

        factual_reply = context.factual_answer.text if context.factual_answer and context.factual_answer.data_found else None

        if not self.config.gemini_ready():
            if factual_reply:
                reply = clamp_response(factual_reply, self.config.max_response_chars)
                self._safe_log(
                    guild_id,
                    channel_id,
                    user_id,
                    user_display_name,
                    clean_question,
                    context.tools_used,
                    reply,
                    "gemini_unavailable",
                    context.intent_name,
                    False,
                    True,
                )
                return AssistantOutcome(True, reply=reply, tools_used=context.tools_used, reason="deterministic_fallback")
            self._safe_log(
                guild_id,
                channel_id,
                user_id,
                user_display_name,
                clean_question,
                context.tools_used,
                None,
                "not_configured",
                context.intent_name,
                False,
                False,
            )
            return AssistantOutcome(True, reply=DEFAULT_NOT_CONFIGURED_MESSAGE, tools_used=context.tools_used, reason="not_configured")

        if not self._limits.check_and_increment(self.config):
            if factual_reply:
                reply = clamp_response(factual_reply, self.config.max_response_chars)
                self._safe_log(
                    guild_id,
                    channel_id,
                    user_id,
                    user_display_name,
                    clean_question,
                    context.tools_used,
                    reply,
                    "soft_limit",
                    context.intent_name,
                    False,
                    True,
                )
                return AssistantOutcome(True, reply=reply, tools_used=context.tools_used, reason="deterministic_fallback")
            return AssistantOutcome(True, reply=DEFAULT_NOT_CONFIGURED_MESSAGE, reason="soft_limit")

        prompt = build_prompt(clean_question, context.text, factual_reply)
        try:
            raw_reply = await self.generator.generate(prompt)
            reply = self._merge_factual_and_gemini(factual_reply, raw_reply)
            self._safe_log(
                guild_id,
                channel_id,
                user_id,
                user_display_name,
                clean_question,
                context.tools_used,
                reply,
                None,
                context.intent_name,
                True,
                False,
            )
            return AssistantOutcome(True, reply=reply, tools_used=context.tools_used, reason="ok")
        except (GeminiRateLimitError, GeminiError) as exc:
            if factual_reply:
                reply = clamp_response(factual_reply, self.config.max_response_chars)
                self._safe_log(
                    guild_id,
                    channel_id,
                    user_id,
                    user_display_name,
                    clean_question,
                    context.tools_used,
                    reply,
                    type(exc).__name__,
                    context.intent_name,
                    True,
                    True,
                )
                return AssistantOutcome(True, reply=reply, tools_used=context.tools_used, reason="deterministic_fallback")
            self._safe_log(
                guild_id,
                channel_id,
                user_id,
                user_display_name,
                clean_question,
                context.tools_used,
                None,
                type(exc).__name__,
                context.intent_name,
                True,
                False,
            )
            return AssistantOutcome(True, reply=DEFAULT_NOT_CONFIGURED_MESSAGE, tools_used=context.tools_used, reason="ai_error")

    def _merge_factual_and_gemini(self, factual_reply: str | None, raw_reply: str) -> str:
        if not factual_reply:
            return clamp_response(raw_reply, self.config.max_response_chars)
        clean = (raw_reply or "").strip()
        first_fact = factual_reply.splitlines()[0].strip()
        if first_fact and first_fact.lower() in clean.lower():
            return clamp_response(clean, self.config.max_response_chars)
        merged = f"{factual_reply.strip()}\n\n{clean}" if clean else factual_reply.strip()
        return clamp_response(merged, self.config.max_response_chars)

    def _check_cooldown(self, user_id: int | str | None) -> str | None:
        if self.config.cooldown_seconds <= 0 or user_id is None:
            return None
        key = str(user_id)
        now = time.monotonic()
        last_seen = self._cooldowns.get(key)
        if last_seen is not None:
            remaining = self.config.cooldown_seconds - (now - last_seen)
            if remaining > 0:
                return f"Easy there. Give the free Gemini meter {int(remaining) + 1}s to breathe."
        self._cooldowns[key] = now
        return None

    def _safe_log(
        self,
        guild_id: int | str | None,
        channel_id: int | str | None,
        user_id: int | str | None,
        user_display_name: str | None,
        question: str,
        tools_used: list[str],
        response_preview: str | None,
        error: str | None,
        detected_intent: str | None = None,
        gemini_called: bool = False,
        deterministic_fallback: bool = False,
    ) -> None:
        if not self.config.logging_enabled:
            return
        try:
            log_ai_query(
                self.conn,
                QueryLogRecord(
                    guild_id=None if guild_id is None else str(guild_id),
                    channel_id=None if channel_id is None else str(channel_id),
                    user_id=None if user_id is None else str(user_id),
                    user_display_name=user_display_name,
                    question=question,
                    tools_used=tools_used,
                    response_preview=response_preview,
                    error=error,
                    detected_intent=detected_intent,
                    gemini_called=gemini_called,
                    deterministic_fallback=deterministic_fallback,
                    diagnostics={
                        "tools_selected": tools_used,
                        "gemini_called": gemini_called,
                        "deterministic_fallback": deterministic_fallback,
                    },
                ),
            )
        except Exception:
            # Logging must never break Discord replies.
            return
