import io

from PIL import Image, ImageDraw, ImageFont

from jarvis.formatting import format_duration as _fmt_time
from jarvis.rendering.fonts import get_fonts


HERO_IMG_PER_PAGE = 18
HERO_WIN_MIN_SECONDS = 120
HERO_WIN_MIN_RATIO = 0.20


def _clip(value: str, length: int) -> str:
    value = str(value or "")
    return value if len(value) <= length else value[: max(0, length - 1)] + "…"



def _render_hero_tierlist_card(
    season_id: int,
    mode_label: str,
    rows: list[dict],
    min_picks: int,
    page: int,
    pages: int,
    total_picks: int,
) -> io.BytesIO:
    W, H = 1500, 980
    pad = 26

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

    title = f"Hero Tier List — Season {season_id} ({mode_label})"
    if pages > 1:
        title += f"  •  Page {page}/{pages}"
    draw.text((pad * 2, int(pad * 1.4)), title, font=title_font, fill=accent)

    left_x = pad * 2
    y = int(pad * 3.4)

    # Column positions
    x_hero = left_x
    x_win = left_x + 560
    x_picks = left_x + 700
    x_pickp = left_x + 835
    x_kda = left_x + 980
    x_time = left_x + 1280

    # Headers
    draw.text((x_hero, y), "Hero", font=body_font, fill=muted)
    draw.text((x_win, y), "Win%", font=body_font, fill=muted)
    draw.text((x_picks, y), "Picks", font=body_font, fill=muted)
    draw.text((x_pickp, y), "Pick%", font=body_font, fill=muted)
    draw.text((x_kda, y), "Avg K/D/A", font=body_font, fill=muted)
    draw.text((x_time, y), "Time", font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for r in rows[:HERO_IMG_PER_PAGE]:
        hero_nm = _clip(r.get("hero_name", r.get("hero_id", "")), 28)
        win_txt = f"{float(r.get('win_pct', 0.0)):.1f}%"
        picks = int(r.get("picks", 0))
        pick_pct = (picks / max(1, int(total_picks))) * 100.0
        pick_txt = f"{pick_pct:.1f}%"
        kda_txt = f"{float(r.get('avg_k', 0.0)):.1f}/{float(r.get('avg_d', 0.0)):.1f}/{float(r.get('avg_a', 0.0)):.1f}"
        time_txt = _fmt_time(int(r.get("seconds", 0)))

        draw.text((x_hero, y), hero_nm, font=body_font, fill=text)
        draw.text((x_win, y), win_txt, font=body_font, fill=text)
        draw.text((x_picks, y), str(picks), font=body_font, fill=text)
        draw.text((x_pickp, y), pick_txt, font=body_font, fill=text)
        draw.text((x_kda, y), kda_txt, font=body_font, fill=text)
        draw.text((x_time, y), time_txt, font=body_font, fill=text)
        y += 32

    y_footer = H - pad - 58
    footer = (
        f"Eligibility: hero ≥ {HERO_WIN_MIN_SECONDS}s AND ≥ {int(HERO_WIN_MIN_RATIO * 100)}% of player match time.  "
        f"Min picks to rank: {max(1, int(min_picks))}."
    )
    draw.text((left_x, y_footer), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _render_hero_synergy_card(
    season_id: int,
    mode_label: str,
    rows: list[dict],
    min_games: int,
    page: int,
    pages: int,
) -> io.BytesIO:
    W, H = 1500, 980
    pad = 26

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

    title = f"Hero Synergy (Same Team) — Season {season_id} ({mode_label})"
    if pages > 1:
        title += f"  •  Page {page}/{pages}"
    draw.text((pad * 2, int(pad * 1.4)), title, font=title_font, fill=accent)

    left_x = pad * 2
    y = int(pad * 3.4)

    # Column positions
    x_pair = left_x
    x_win = left_x + 980
    x_games = left_x + 1120
    x_wins = left_x + 1280

    draw.text((x_pair, y), "Pair", font=body_font, fill=muted)
    draw.text((x_win, y), "Win%", font=body_font, fill=muted)
    draw.text((x_games, y), "Games", font=body_font, fill=muted)
    draw.text((x_wins, y), "Wins", font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for r in rows[:HERO_IMG_PER_PAGE]:
        pair_nm = _clip(r.get("pair_name", ""), 54)
        win_txt = f"{float(r.get('win_pct', 0.0)):.1f}%"
        games = int(r.get("games", 0))
        wins = int(r.get("wins", 0))

        draw.text((x_pair, y), pair_nm, font=body_font, fill=text)
        draw.text((x_win, y), win_txt, font=body_font, fill=text)
        draw.text((x_games, y), str(games), font=body_font, fill=text)
        draw.text((x_wins, y), str(wins), font=body_font, fill=text)
        y += 32

    y_footer = H - pad - 58
    footer = (
        f"Dominant eligible hero per player per match; pairs counted when on same team.  "
        f"Eligibility: hero ≥ {HERO_WIN_MIN_SECONDS}s AND ≥ {int(HERO_WIN_MIN_RATIO * 100)}%.  "
        f"Min games to rank: {max(1, int(min_games))}."
    )
    draw.text((left_x, y_footer), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
