from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = int(str(raw).strip())
        except ValueError:
            value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_optional_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = int(str(raw).strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_id_set(name: str) -> set[str]:
    raw = os.getenv(name, "")
    return {part.strip() for part in raw.split(",") if part.strip()}


@dataclass(frozen=True)
class AssistantConfig:
    enabled: bool
    provider: str
    model: str
    gemini_api_key: str
    free_only: bool
    allowed_channel_ids: set[str]
    denied_channel_ids: set[str]
    max_context_rows: int
    max_response_chars: int
    cooldown_seconds: int
    logging_enabled: bool
    daily_soft_limit: int | None
    monthly_soft_limit: int | None

    @classmethod
    def from_env(cls) -> "AssistantConfig":
        return cls(
            enabled=_env_bool("AI_ASSISTANT_ENABLED", False),
            provider=os.getenv("AI_PROVIDER", "gemini").strip().lower() or "gemini",
            model=os.getenv("AI_MODEL", "gemini-2.5-flash-lite").strip() or "gemini-2.5-flash-lite",
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            free_only=_env_bool("AI_ASSISTANT_FREE_ONLY", True),
            allowed_channel_ids=_parse_id_set("AI_ASSISTANT_ALLOWED_CHANNEL_IDS"),
            denied_channel_ids=_parse_id_set("AI_ASSISTANT_DENIED_CHANNEL_IDS"),
            max_context_rows=_env_int("AI_ASSISTANT_MAX_CONTEXT_ROWS", 100, minimum=5, maximum=500),
            max_response_chars=_env_int("AI_ASSISTANT_MAX_RESPONSE_CHARS", 1800, minimum=200, maximum=1900),
            cooldown_seconds=_env_int("AI_ASSISTANT_COOLDOWN_SECONDS", 10, minimum=0, maximum=3600),
            logging_enabled=_env_bool("AI_ASSISTANT_LOGGING_ENABLED", True),
            daily_soft_limit=_env_optional_int("AI_ASSISTANT_DAILY_SOFT_LIMIT"),
            monthly_soft_limit=_env_optional_int("AI_ASSISTANT_MONTHLY_SOFT_LIMIT"),
        )

    def is_channel_allowed(self, channel_id: int | str | None) -> bool:
        channel = "" if channel_id is None else str(channel_id)
        if channel in self.denied_channel_ids:
            return False
        if self.allowed_channel_ids and channel not in self.allowed_channel_ids:
            return False
        return True

    def gemini_ready(self) -> bool:
        return (
            self.enabled
            and self.provider == "gemini"
            and self.free_only
            and bool(self.gemini_api_key)
            and self.model.startswith("gemini-")
        )
