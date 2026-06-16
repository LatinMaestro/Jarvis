from __future__ import annotations

import re
from dataclasses import dataclass


MENTION_RE_TEMPLATE = r"<@!?{bot_id}>"


@dataclass(frozen=True)
class MentionParseResult:
    mentioned: bool
    query: str


def should_ignore_message(author_is_bot: bool, content: str | None) -> bool:
    if author_is_bot:
        return True
    return not bool((content or "").strip())


def strip_bot_mention(content: str, bot_user_id: int | str | None) -> MentionParseResult:
    if bot_user_id is None:
        return MentionParseResult(False, "")
    pattern = re.compile(MENTION_RE_TEMPLATE.format(bot_id=re.escape(str(bot_user_id))))
    if not pattern.search(content or ""):
        return MentionParseResult(False, "")
    query = pattern.sub("", content or "").strip()
    query = re.sub(r"\s+", " ", query).strip()
    return MentionParseResult(True, query)


def is_command_message(content: str | None, prefix: str = "!") -> bool:
    return (content or "").lstrip().startswith(prefix)
