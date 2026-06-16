"""Jarvis Discord mention-based AI assistant.

Phase 1 keeps this package isolated from the command handlers in main.py. The
assistant uses Gemini only, controlled read-only stat summaries, and no live
Discord or Railway access during tests.
"""

from .config import AssistantConfig
from .service import AssistantOutcome, JarvisAIAssistant

__all__ = ["AssistantConfig", "AssistantOutcome", "JarvisAIAssistant"]
