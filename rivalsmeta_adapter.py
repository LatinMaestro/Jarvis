"""Pure helpers for importing public RivalsMeta match payloads into Jarvis."""

from __future__ import annotations

from copy import deepcopy
import json
from urllib.parse import urlparse


RIVALSMETA_API_BASE = "https://rivalsmeta.com/api"
_RIVALSMETA_HOSTS = {"rivalsmeta.com", "www.rivalsmeta.com"}


async def read_limited_response_body(content, max_bytes: int = 2_000_000) -> bytes:
    """Read a complete streamed response without allowing an unbounded body."""
    chunks = []
    total = 0
    async for chunk in content.iter_chunked(64 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("RivalsMeta response was unexpectedly large.")
        chunks.append(chunk)
    return b"".join(chunks)


def match_id_from_rivalsmeta_url(value: str) -> str | None:
    """Return a match UID only for an HTTPS RivalsMeta /matches/<uid> URL."""
    try:
        parsed = urlparse((value or "").strip())
    except Exception:
        return None

    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() not in _RIVALSMETA_HOSTS:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0].lower() != "matches":
        return None

    match_uid = parts[1]
    if not match_uid or len(match_uid) > 160:
        return None
    if not all(ch.isdigit() or ch == "_" for ch in match_uid):
        return None
    return match_uid


def is_rivalsmeta_match_url(value: str) -> bool:
    return match_id_from_rivalsmeta_url(value) is not None


def rivalsmeta_season_id(season_label: str) -> int:
    """Map Marvel Rivals season labels (for example 8 or 8.5) to RivalsMeta ids."""
    raw = str(season_label or "").strip().upper()
    if raw.startswith("S"):
        raw = raw[1:]
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unsupported RivalsMeta season label: {season_label}") from exc

    season_number = int(value)
    fraction = round(value - season_number, 3)
    if season_number == 0 and fraction == 0:
        return 1
    if season_number < 1 or fraction not in (0, 0.5):
        raise ValueError(f"Unsupported RivalsMeta season label: {season_label}")
    return (season_number * 2) + (1 if fraction == 0.5 else 0)


def normalise_rivalsmeta_history_payload(raw) -> dict:
    """Wrap RivalsMeta's history list in the shape used by Jarvis discovery."""
    if not isinstance(raw, list):
        raise ValueError("RivalsMeta returned a non-list match history payload.")
    return {"match_history": [item for item in raw if isinstance(item, dict)]}


async def fetch_rivalsmeta_player_history(query: str,
                                          session,
                                          *,
                                          skip: int,
                                          season: str,
                                          game_mode: int = 3) -> dict:
    """Fetch and normalize one public RivalsMeta history page for a roster UID."""
    player_uid = str(query or "").strip()
    if not player_uid.isdigit():
        raise RuntimeError("RivalsMeta history fallback requires roster UIDs.")

    url = f"{RIVALSMETA_API_BASE}/player-match-history/{player_uid}"
    params = {
        "skip": max(0, int(skip)),
        "game_mode_id": int(game_mode or 3),
        "hero_id": 0,
        "season": rivalsmeta_season_id(season),
    }
    headers = {"User-Agent": "Jarvis-Marvel-Rivals-Bot/1.0"}
    async with session.get(url,
                           params=params,
                           headers=headers,
                           allow_redirects=False) as response:
        if response.status == 429:
            raise RuntimeError("RATE_LIMIT_429")
        if response.status != 200:
            text = await response.text()
            raise RuntimeError(
                f"RivalsMeta history HTTP {response.status}: {text[:200]}")

        body = await read_limited_response_body(response.content)
        try:
            raw = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            content_type = response.headers.get("Content-Type", "unknown")
            raise RuntimeError(
                f"RivalsMeta history returned invalid JSON ({content_type}, {len(body)} bytes)."
            ) from exc

    result = normalise_rivalsmeta_history_payload(raw)
    result["_jarvis_source"] = "rivalsmeta"
    return result


def normalise_rivalsmeta_match_payload(raw: dict) -> dict:
    """Translate RivalsMeta's public match JSON into Jarvis's API payload shape."""
    if not isinstance(raw, dict):
        raise ValueError("RivalsMeta returned a non-object match payload.")

    match_uid = str(raw.get("match_uid") or "").strip()
    players = raw.get("match_players")
    if not match_uid or not isinstance(players, list) or not players:
        raise ValueError("RivalsMeta payload is missing a match UID or player rows.")

    mode_id = raw.get("game_mode_id")
    mode_names = {2: "Competitive", 3: "Custom"}
    try:
        mode_name = mode_names.get(int(mode_id), f"Mode {int(mode_id)}")
    except (TypeError, ValueError):
        mode_name = "Unknown mode"

    md = deepcopy(raw)
    if raw.get("match_time_stamp") is not None and md.get("timestamp") is None:
        md["timestamp"] = raw.get("match_time_stamp")
    md["game_mode"] = {
        "game_mode_id": mode_id,
        "game_mode_name": mode_name,
    }
    md["match_dynamic_fields"] = deepcopy(raw.get("dynamic_fields") or {})

    translated_players = []
    for source_player in players:
        if not isinstance(source_player, dict):
            continue
        player = deepcopy(source_player)
        player["kills"] = source_player.get("kills", source_player.get("k", 0))
        player["deaths"] = source_player.get("deaths", source_player.get("d", 0))
        player["assists"] = source_player.get("assists", source_player.get("a", 0))
        player["final_hits"] = source_player.get("final_hits", source_player.get("last_kill", 0))

        translated_heroes = []
        for source_hero in source_player.get("player_heroes") or []:
            if not isinstance(source_hero, dict):
                continue
            hero = deepcopy(source_hero)
            hero["kills"] = source_hero.get("kills", source_hero.get("k", 0))
            hero["deaths"] = source_hero.get("deaths", source_hero.get("d", 0))
            hero["assists"] = source_hero.get("assists", source_hero.get("a", 0))
            translated_heroes.append(hero)
        player["player_heroes"] = translated_heroes
        translated_players.append(player)

    if not translated_players:
        raise ValueError("RivalsMeta payload contains no usable player rows.")

    md["match_players"] = translated_players
    return {
        "match_details": md,
        "jarvis_import_source": "rivalsmeta",
    }
