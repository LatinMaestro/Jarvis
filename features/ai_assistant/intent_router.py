from __future__ import annotations

import re
from dataclasses import dataclass, field

from .tools import fuzzy_match_player


@dataclass(frozen=True)
class StatIntent:
    name: str
    stat_backed: bool
    players: list[str] = field(default_factory=list)
    metric: str | None = None
    role: str | None = None
    hero: str | None = None
    wants_worst: bool = False
    clarification: str | None = None


def _candidate_phrases(question: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s_-]+", " ", question)
    tokens = [token.strip() for token in cleaned.split() if len(token.strip()) >= 3]
    phrases = []
    for size in (3, 2, 1):
        for i in range(0, max(0, len(tokens) - size + 1)):
            phrases.append(" ".join(tokens[i : i + size]))
    return phrases


def _find_players(question: str, known_players: list[str], max_players: int = 2) -> tuple[list[str], str | None]:
    found: list[str] = []
    ambiguous: list[str] = []
    question_norm = re.sub(r"[^a-z0-9]+", "", question.lower())
    for name in known_players:
        norm = re.sub(r"[^a-z0-9]+", "", name.lower())
        if norm and norm in question_norm and name not in found:
            found.append(name)

    for phrase in _candidate_phrases(question):
        if len(found) >= max_players:
            break
        match = fuzzy_match_player(phrase, known_players)
        if match.status == "matched" and match.player and match.player not in found:
            found.append(match.player)
        elif match.status == "ambiguous":
            ambiguous.extend(match.candidates)

    if len(found) >= max_players:
        return found[:max_players], None
    if ambiguous and not found:
        return [], "That name is ambiguous. Did you mean: " + ", ".join(ambiguous[:5]) + "?"
    return found, None


def _detect_metric(lowered: str) -> str | None:
    if "win rate" in lowered or "winrate" in lowered:
        return "win_rate"
    if "most wins" in lowered or "wins" in lowered:
        return "wins"
    if "kda" in lowered or "k/d/a" in lowered:
        return "kda"
    if "damage taken" in lowered:
        return "damage_taken"
    if "damage" in lowered:
        return "damage"
    if "kills" in lowered or "frags" in lowered:
        return "kills"
    if "healing" in lowered or "heal" in lowered:
        return "healing"
    if "mvp" in lowered:
        return "mvp"
    if "svp" in lowered:
        return "svp"
    return None


def _detect_role(lowered: str) -> str | None:
    roles = {
        "vanguard": "vanguard",
        "tank": "vanguard",
        "duelist": "duelist",
        "dps": "duelist",
        "strategist": "strategist",
        "support": "strategist",
        "healer": "strategist",
    }
    for token, role in roles.items():
        if re.search(rf"\b{re.escape(token)}s?\b", lowered):
            return role
    return None


def _detect_hero_phrase(question: str) -> str | None:
    patterns = (
        r"\bbest\s+([A-Za-z][A-Za-z0-9' -]{1,30})\b",
        r"\bwho(?:'s| is)?\s+best\s+on\s+([A-Za-z][A-Za-z0-9' -]{1,30})\b",
        r"\btop\s+([A-Za-z][A-Za-z0-9' -]{1,30})\b",
    )
    stop_words = {
        "player",
        "players",
        "duo",
        "duos",
        "vanguard",
        "tank",
        "duelist",
        "dps",
        "strategist",
        "support",
        "healer",
        "win rate",
        "kda",
        "damage",
        "kills",
    }
    for pattern in patterns:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if not match:
            continue
        phrase = re.sub(r"\s+", " ", match.group(1)).strip(" ?!.:,")
        if phrase.lower() not in stop_words:
            return phrase
    return None


def detect_intent(question: str, known_players: list[str]) -> StatIntent:
    lowered = (question or "").lower()
    players, clarification = _find_players(question, known_players)
    if clarification:
        return StatIntent("clarification", False, clarification=clarification)

    if "you are the stat bot" in lowered or "you're the stat bot" in lowered:
        return StatIntent("stat_bot_correction", False)

    role = _detect_role(lowered)
    hero = _detect_hero_phrase(question)
    metric = _detect_metric(lowered)
    wants_worst = any(term in lowered for term in ("worst", "lowest", "bottom"))
    wants_roast = any(term in lowered for term in ("roast", "honest opinion", "liability", "fraud", "farming"))
    wants_recent = any(term in lowered for term in ("last night", "recent", "latest", "what happened", "session"))
    wants_duo = any(term in lowered for term in ("duo", "duos", "chemistry", "pair", "combo", "together"))
    wants_leaderboard = any(term in lowered for term in ("leaderboard", "standings", "breakdown", "table"))
    wants_first = any(term in lowered for term in ("first place", "in first", "top player", "leading", "number one", "#1"))
    wants_podium = any(term in lowered for term in ("podium", "top 3", "top-3", "top three"))
    wants_recommendation = any(
        term in lowered
        for term in ("what hero should", "who should i play", "play more", "recommend", "prioritise", "prioritize")
    )

    if wants_duo:
        if len(players) >= 2:
            return StatIntent("player_duo", True, players=players, wants_worst=wants_worst)
        return StatIntent("top_duos", True, wants_worst=wants_worst)
    if wants_first:
        return StatIntent("first_place", True)
    if wants_leaderboard:
        return StatIntent("leaderboard", True)
    if metric == "win_rate":
        return StatIntent("highest_win_rate", True, metric=metric)
    if metric:
        return StatIntent("top_metric", True, metric=metric)
    if role and any(term in lowered for term in ("best", "top", "who")):
        return StatIntent("best_role", True, role=role)
    if hero and any(term in lowered for term in ("best", "top", "who")):
        return StatIntent("best_hero", True, hero=hero)
    if wants_podium and players:
        return StatIntent("podium_context", True, players=players[:1])
    if wants_recommendation and players:
        return StatIntent("recommendation", True, players=players[:1])
    if len(players) >= 2 or any(term in lowered for term in ("better", "versus", " vs ", "compare")):
        return StatIntent("player_comparison", True, players=players)
    if wants_recent:
        return StatIntent("recent_session", True)
    if wants_roast:
        return StatIntent("roast", bool(players), players=players)
    if players:
        return StatIntent("player_summary", True, players=players[:1])
    return StatIntent("general_chat", False)
