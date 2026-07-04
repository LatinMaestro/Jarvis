import io
from collections import defaultdict
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from jarvis.rendering.fonts import get_fonts


HERO_WIN_MIN_SECONDS = 120
HERO_WIN_MIN_RATIO = 0.20


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except Exception:
        return default


_ROLE_WR_ALLOWED = {
    "v": "Vanguard",
    "vang": "Vanguard",
    "vanguard": "Vanguard",
    "d": "Duelist",
    "duel": "Duelist",
    "duelist": "Duelist",
    "s": "Strategist",
    "strat": "Strategist",
    "strategist": "Strategist",
}
_ROLE_WR_ORDER = ["Vanguard", "Duelist", "Strategist"]


def _role_wr_clip(text: str, n: int) -> str:
    s = str(text or "")
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")


def _role_wr_norm_role(role_text: str) -> Optional[str]:
    if not role_text:
        return None
    return _ROLE_WR_ALLOWED.get(str(role_text).strip().lower())


def _role_wr_line_height(font) -> int:
    try:
        box = font.getbbox("Ag")
        return int(box[3] - box[1])
    except Exception:
        return 18


def _role_wr_draw_centered_multiline(draw, x: int, y: int, w: int, h: int,
                                     text: str, font, fill, spacing: int = 2):
    lines = (str(text or "")).splitlines() or [""]
    lh = _role_wr_line_height(font)
    try:
        widths = [font.getlength(line) for line in lines]
    except Exception:
        widths = [len(line) * 10 for line in lines]

    total_h = int(lh * len(lines) + spacing * (len(lines) - 1))
    cur_y = y + max(0, (h - total_h) // 2)

    for line, lw in zip(lines, widths):
        cur_x = x + max(0, (w - int(lw)) // 2)
        draw.text((cur_x, cur_y), line, font=font, fill=fill)
        cur_y += lh + spacing



def _role_wr_role_eligible(row: dict, role_name: str) -> bool:
    total_sec = float(row.get("total_sec", 0.0) or 0.0)
    role_sec = float((row.get("role_sec") or {}).get(role_name, 0.0) or 0.0)
    if total_sec <= 0 or role_sec <= 0:
        return False
    return (
        role_sec >= int(HERO_WIN_MIN_SECONDS)
        and (role_sec / total_sec) >= float(HERO_WIN_MIN_RATIO)
    )


def _role_wr_cell_text(wins: int, games: int) -> str:
    games_i = int(games or 0)
    wins_i = int(wins or 0)
    if games_i <= 0:
        return "—"
    return f"{(wins_i / games_i) * 100.0:.1f}% ({wins_i}/{games_i})"


def _role_wr_build_overall_rows(match_rows: list[dict]) -> list[dict]:
    agg = {}

    for row in match_rows:
        uid = int(row["player_uid"])
        rec = agg.get(uid)
        if rec is None:
            rec = {
                "player_uid": uid,
                "player": str(row.get("player") or f"UID_{uid}"),
                "Vanguard_wins": 0,
                "Vanguard_games": 0,
                "Duelist_wins": 0,
                "Duelist_games": 0,
                "Strategist_wins": 0,
                "Strategist_games": 0,
            }
            agg[uid] = rec

        rec["player"] = str(row.get("player") or rec["player"])

        for role_name in _ROLE_WR_ORDER:
            if _role_wr_role_eligible(row, role_name):
                rec[f"{role_name}_games"] += 1
                if _safe_int(row.get("is_win"), 0) == 1:
                    rec[f"{role_name}_wins"] += 1

    out = list(agg.values())
    out.sort(key=lambda r: str(r.get("player") or "").lower())
    return out


def _role_wr_build_teammate_rows(match_rows: list[dict],
                                 anchor_uid: int,
                                 anchor_role: str) -> list[dict]:
    anchor_uid = int(anchor_uid)

    by_team = defaultdict(list)
    anchor_matches = []

    for row in match_rows:
        camp = row.get("camp")
        if camp in (0, 1):
            by_team[(str(row["match_key"]), int(camp))].append(row)

        if int(row["player_uid"]) == anchor_uid and camp in (0, 1):
            if _role_wr_role_eligible(row, anchor_role):
                anchor_matches.append(row)

    if not anchor_matches:
        return []

    agg = {}

    for anchor_row in anchor_matches:
        team_rows = by_team.get((str(anchor_row["match_key"]), int(anchor_row["camp"])), [])
        for row in team_rows:
            uid = int(row["player_uid"])
            if uid == anchor_uid:
                continue

            rec = agg.get(uid)
            if rec is None:
                rec = {
                    "player_uid": uid,
                    "player": str(row.get("player") or f"UID_{uid}"),
                    "wins": 0,
                    "games": 0,
                }
                agg[uid] = rec

            rec["player"] = str(row.get("player") or rec["player"])
            rec["games"] += 1
            if _safe_int(row.get("is_win"), 0) == 1:
                rec["wins"] += 1

    out = list(agg.values())
    out.sort(
        key=lambda r: (
            int(r.get("games", 0)),
            (float(r.get("wins", 0)) / float(r.get("games", 1))) if int(r.get("games", 0)) > 0 else 0.0,
            str(r.get("player") or "").lower(),
        ),
        reverse=True,
    )
    return out


def _role_wr_render_overall_image(season_id: int, rows: list[dict]) -> io.BytesIO:
    pad = 26
    row_h = 34
    table_rows = max(1, len(rows))
    extra_h = 220

    W = 1900
    H = max(520, 210 + (table_rows * row_h) + extra_h)

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    title = f"Role Win Rates — Season {season_id}"
    subtitle = (
        f"Eligible role games only • role ≥ {HERO_WIN_MIN_SECONDS}s and "
        f"≥ {int(HERO_WIN_MIN_RATIO * 100)}% of that player's match time"
    )

    draw.text((pad * 2, int(pad * 1.35)), title, font=title_font, fill=accent)
    draw.text((pad * 2, int(pad * 2.7)), subtitle, font=body_font, fill=muted)

    left_x = pad * 2
    y = int(pad * 4.2)

    x_player = left_x
    x_v = left_x + 360
    x_d = left_x + 840
    x_s = left_x + 1320

    headers = [
        (x_player, "Player"),
        (x_v, "Vanguard"),
        (x_d, "Duelist"),
        (x_s, "Strategist"),
    ]
    for x, label in headers:
        draw.text((x, y), label, font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for r in rows:
        player_txt = _role_wr_clip(str(r.get("player", "")), 22)
        v_txt = _role_wr_cell_text(
            int(r.get("Vanguard_wins", 0)),
            int(r.get("Vanguard_games", 0)),
        )
        d_txt = _role_wr_cell_text(
            int(r.get("Duelist_wins", 0)),
            int(r.get("Duelist_games", 0)),
        )
        s_txt = _role_wr_cell_text(
            int(r.get("Strategist_wins", 0)),
            int(r.get("Strategist_games", 0)),
        )

        draw.text((x_player, y), player_txt, font=body_font, fill=text)
        draw.text((x_v, y), v_txt, font=body_font, fill=text)
        draw.text((x_d, y), d_txt, font=body_font, fill=text)
        draw.text((x_s, y), s_txt, font=body_font, fill=text)

        # subtle row divider like the cleaner themed outputs
        draw.line([(x_player, y + row_h - 6), (W - pad * 2, y + row_h - 6)], fill=(58, 58, 76), width=1)

        y += row_h

    footer = (
        "Win rates shown as percentage with wins/games in brackets. "
        "Only eligible role appearances are counted."
    )
    draw.text((left_x, H - pad - 58), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _role_wr_render_teammate_image(
    season_id: int,
    anchor_player: str,
    anchor_role: str,
    rows: list[dict]
) -> io.BytesIO:
    pad = 26
    row_h = 34
    table_rows = max(1, len(rows))
    extra_h = 220

    W = 1450
    H = max(500, 210 + (table_rows * row_h) + extra_h)

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    title = f"Teammates with {anchor_player} on {anchor_role} — Season {season_id}"
    subtitle = (
        f"Counts only matches where {anchor_player} was eligible on {anchor_role}"
    )

    draw.text((pad * 2, int(pad * 1.35)), title, font=title_font, fill=accent)
    draw.text((pad * 2, int(pad * 2.7)), subtitle, font=body_font, fill=muted)

    left_x = pad * 2
    y = int(pad * 4.2)

    x_player = left_x
    x_wins = left_x + 520
    x_games = left_x + 700
    x_wr = left_x + 900

    headers = [
        (x_player, "Player"),
        (x_wins, "Wins"),
        (x_games, "Games"),
        (x_wr, "Win%"),
    ]
    for x, label in headers:
        draw.text((x, y), label, font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for r in rows:
        wins = int(r.get("wins", 0))
        games = int(r.get("games", 0))
        wr = (wins / games) * 100.0 if games > 0 else 0.0

        draw.text((x_player, y), _role_wr_clip(str(r.get("player", "")), 26), font=body_font, fill=text)
        draw.text((x_wins, y), str(wins), font=body_font, fill=text)
        draw.text((x_games, y), str(games), font=body_font, fill=text)
        draw.text((x_wr, y), f"{wr:.1f}%", font=body_font, fill=text)

        draw.line([(x_player, y + row_h - 6), (W - pad * 2, y + row_h - 6)], fill=(58, 58, 76), width=1)

        y += row_h

    footer = (
        f"Eligibility: {anchor_role} must reach at least {HERO_WIN_MIN_SECONDS}s "
        f"and {int(HERO_WIN_MIN_RATIO * 100)}% of {anchor_player}'s match time."
    )
    draw.text((left_x, H - pad - 58), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

