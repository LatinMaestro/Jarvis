from __future__ import annotations


DEFAULT_NOT_CONFIGURED_MESSAGE = (
    "Jarvis AI is not configured yet, or the free Gemini limit has been hit. "
    "The stats are safe, but the roast department is temporarily closed."
)

EMPTY_MENTION_HELP = (
    "You rang? Mention me with a question, like `@Jarvis roast LatinMaestro`, "
    "`@Jarvis who improved the most this season?`, or `@Jarvis what hero should I play more?`"
)


def clamp_response(text: str, max_chars: int) -> str:
    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return clean
    suffix = "\n\n[Trimmed so Discord does not turn this into a scroll boss.]"
    return clean[: max(0, max_chars - len(suffix))].rstrip() + suffix


def chunk_discord_message(text: str, limit: int = 1900) -> list[str]:
    clean = (text or "").strip()
    if not clean:
        return [DEFAULT_NOT_CONFIGURED_MESSAGE]

    chunks: list[str] = []
    remaining = clean
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
