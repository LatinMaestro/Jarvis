def load_human_player_matches(cursor, season_id: int) -> list[tuple]:
    cursor.execute(
        """
        SELECT match_uid, player, camp
        FROM mr_player_match
        WHERE season_id = ?
          AND COALESCE(is_bot, 0) = 0
          AND match_uid IS NOT NULL
          AND player IS NOT NULL
        """,
        (int(season_id),),
    )
    return cursor.fetchall()


def load_ban_events(cursor, season_id: int) -> list[tuple]:
    cursor.execute(
        """
        SELECT match_uid, battle_side, hero_id
        FROM mr_ban_picks
        WHERE season_id = ?
          AND is_pick = 0
          AND hero_id IS NOT NULL
          AND match_uid IS NOT NULL
        """,
        (int(season_id),),
    )
    return cursor.fetchall()


def _safe_string(value) -> str:
    return "" if value is None else str(value).strip()


def _normalise_side(value):
    try:
        side = int(value)
    except Exception:
        return None
    if side in (0, 1):
        return side
    if side in (1, 2):
        return side - 1
    return None


def _clip(text: str, length: int) -> str:
    text = text or ""
    return text if len(text) <= length else text[: max(0, length - 1)] + "\u00e2\u20ac\u00a6"


def build_player_bans_report(
    player_match_rows: list[tuple],
    ban_rows: list[tuple],
    hero_map: dict[str, str],
    min_games_top5: int = 5,
) -> dict:
    def hero_label(hero_id) -> str:
        key = _safe_string(hero_id)
        return hero_map.get(key, key if key else "-")

    player_matches = defaultdict(set)
    player_side = {}
    for match_uid, player, camp in player_match_rows:
        match_key = _safe_string(match_uid)
        player_name = _safe_string(player)
        if not match_key or not player_name:
            continue
        player_matches[player_name].add(match_key)
        side = _normalise_side(camp)
        if side is not None:
            player_side[(player_name, match_key)] = side

    bans_by_match_side = defaultdict(lambda: {0: [], 1: []})
    for match_uid, battle_side, hero_id in ban_rows:
        match_key = _safe_string(match_uid)
        hero_key = _safe_string(hero_id)
        side = _normalise_side(battle_side)
        if match_key and hero_key and side is not None:
            bans_by_match_side[match_key][side].append(hero_key)
    matches_with_bans = set(bans_by_match_side)

    def enemy_bans(player: str, match_uid: str) -> list[str]:
        side = player_side.get((player, match_uid))
        if side not in (0, 1):
            return []
        return bans_by_match_side.get(match_uid, {}).get(1 - side, []) or []

    table_rows = []
    counters = {}
    eligible_by_player = {}
    for player in sorted(player_matches, key=str.lower):
        eligible = [
            match_uid
            for match_uid in player_matches[player]
            if match_uid in matches_with_bans
            and player_side.get((player, match_uid)) in (0, 1)
        ]
        games = len(eligible)
        if games <= 0:
            continue
        counter = Counter(
            hero_id
            for match_uid in eligible
            for hero_id in enemy_bans(player, match_uid)
            if hero_id
        )
        counters[player] = counter
        eligible_by_player[player] = eligible

        def format_ban(item):
            if not item:
                return "-"
            hero_id, count = item
            return f"{_clip(hero_label(hero_id), 18)} ({count}, {(count / games) * 100.0:.0f}%)"

        top = counter.most_common(3)
        table_rows.append(
            {
                "player": player,
                "games": games,
                "b1": format_ban(top[0] if len(top) > 0 else None),
                "b2": format_ban(top[1] if len(top) > 1 else None),
                "b3": format_ban(top[2] if len(top) > 2 else None),
            }
        )
    table_rows.sort(key=lambda row: row["games"], reverse=True)

    candidates = []
    for row in table_rows:
        player = row["player"]
        games = len(eligible_by_player.get(player, []))
        if games < min_games_top5:
            continue
        for hero_id, count in counters[player].most_common(3):
            candidates.append((count / games, games, count, player, hero_id))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

    seen_heroes = set()
    top5 = []
    for rate, games, count, player, hero_id in candidates:
        hero_key = _safe_string(hero_id)
        if not hero_key or hero_key in seen_heroes:
            continue
        seen_heroes.add(hero_key)
        top5.append((rate, games, count, player, hero_id))
        if len(top5) >= 5:
            break

    return {"table_rows": table_rows, "top5": top5, "hero_map": hero_map}


def render_player_bans_image(season_id: int, report: dict):
    width, height = 1500, 980
    padding = 26
    background = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()
    draw.rounded_rectangle(
        [padding, padding, width - padding, height - padding], radius=22, fill=card
    )
    draw.text(
        (padding * 2, int(padding * 1.4)),
        f"Enemy Team Bans vs Players \u00e2\u20ac\u201d Season {season_id}",
        font=title_font,
        fill=accent,
    )
    left_x = padding * 2
    y = int(padding * 3.4)
    columns = [left_x, left_x + 300, left_x + 400, left_x + 730, left_x + 1060]
    for x, label in zip(columns, ["Player", "Games", "Enemy Ban #1", "Enemy Ban #2", "Enemy Ban #3"]):
        draw.text((x, y), label, font=body_font, fill=muted)
    y += 28
    draw.line([(padding * 2, y), (width - padding * 2, y)], fill=line, width=2)
    y += 14
    for row in report["table_rows"][:15]:
        values = [_clip(row["player"], 18), str(row["games"]), _clip(row["b1"], 28), _clip(row["b2"], 28), _clip(row["b3"], 28)]
        for x, value in zip(columns, values):
            draw.text((x, y), value, font=body_font, fill=text)
        y += 32
    y += 6
    draw.line([(padding * 2, y), (width - padding * 2, y)], fill=line, width=2)
    y += 14
    draw.text((left_x, y), "Top 5 highest enemy-ban rates (unique heroes; min 5 games)", font=body_font, fill=muted)
    y += 34
    summary_columns = [left_x, left_x + 90, left_x + 390, left_x + 760, left_x + 900]
    for x, label in zip(summary_columns, ["Rank", "Player", "Hero", "Count", "Rate"]):
        draw.text((x, y), label, font=body_font, fill=muted)
    y += 28
    draw.line([(padding * 2, y), (width - padding * 2, y)], fill=line, width=2)
    y += 14
    hero_map = report.get("hero_map") or {}
    for index, (rate, _games, count, player, hero_id) in enumerate(report["top5"], 1):
        hero_key = _safe_string(hero_id)
        hero_name = hero_map.get(hero_key, hero_key if hero_key else "-")
        values = [f"#{index}", _clip(player, 18), _clip(hero_name, 22), str(count), f"{rate * 100:.0f}%"]
        for x, value in zip(summary_columns, values):
            draw.text((x, y), value, font=body_font, fill=text)
        y += 32
    footer = "Games count only matches with recorded bans + known team side. Bans shown are the opposing team\u00e2\u20ac\u2122s bans."
    draw.text((left_x, height - padding - 58), footer, font=body_font, fill=muted)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
import io
from collections import Counter, defaultdict

from PIL import Image, ImageDraw, ImageFont

from jarvis.rendering.fonts import get_fonts
