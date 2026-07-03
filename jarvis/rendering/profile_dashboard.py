import io

from PIL import Image, ImageDraw, ImageFont

from jarvis.formatting import format_duration as _fmt_time
from jarvis.rendering.fonts import get_fonts

def _profile_text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    try:
        return draw.textbbox((0, 0), text, font=font)
    except Exception:
        w, h = font.getsize(text)
        return (0, 0, w, h)


def _profile_text_w(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    b = _profile_text_bbox(draw, text, font)
    return int(b[2] - b[0])


def _profile_clip_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
    s = str(text or "")
    if _profile_text_w(draw, s, font) <= max_w:
        return s

    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi) // 2
        cand = s[:mid] + "…"
        if _profile_text_w(draw, cand, font) <= max_w:
            lo = mid + 1
        else:
            hi = mid
    mid = max(0, lo - 1)
    return (s[:mid] + "…") if mid > 0 else "…"


def _profile_draw_role_mix_bar(draw, x, y, w, h, share: dict[str, float]):
    col = {
        "Vanguard": (90, 160, 255),
        "Duelist": (255, 120, 120),
        "Strategist": (120, 220, 140),
    }
    bg = (60, 60, 78)
    outline = (90, 90, 110)

    draw.rounded_rectangle([x, y, x + w, y + h],
                           radius=max(1, h // 2),
                           fill=bg,
                           outline=outline,
                           width=1)

    cur = x
    for key in ["Vanguard", "Duelist", "Strategist"]:
        frac = max(0.0, float(share.get(key, 0.0) or 0.0))
        segw = int(round(w * frac))
        if segw <= 0:
            continue
        draw.rectangle([cur, y, cur + segw, y + h], fill=col.get(key, (200, 200, 200)))
        cur += segw


def _render_profile_dashboard(player_name: str, pack: dict) -> io.BytesIO:
    # Canvas
    W, H = 2000, 1300
    pad = 26
    gap = 18

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)

    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    body_font, title_font = get_fonts(body_pt=22, title_pt=40)

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    # Header
    header_y = int(pad * 1.3)
    draw.text((pad * 2, header_y),
              f"{player_name} — Season {pack['season_id']} • Scouting Report",
              font=title_font,
              fill=accent)

    t = pack["totals"]
    meta = (f"{t['games']} games • {t['wins']}-{t['losses']} ({t['win_pct']:.1f}%)"
            f" • Streak {pack['streak_txt']} • Last10 {pack['form10']}")
    draw.text((pad * 2, header_y + 46), meta, font=body_font, fill=muted)

    # Grid
    top_y = header_y + 92
    col_w = (W - pad * 4 - gap * 2) // 3
    x1 = pad * 2
    x2 = x1 + col_w + gap
    x3 = x2 + col_w + gap
    row1_h = 520
    y1 = top_y
    y2 = y1 + row1_h + gap
    wide_w = (W - pad * 4 - gap) // 2
    row2_h = (H - pad * 2) - y2

    def panel(x, y, w, h, title):
        draw.rounded_rectangle([x, y, x + w, y + h], radius=18, outline=line, width=2)
        draw.text((x + 18, y + 14), title, font=body_font, fill=accent)

    panel(x1, y1, col_w, row1_h, "Snapshot")
    panel(x2, y1, col_w, row1_h, "Role Mix + Signature Heroes")
    panel(x3, y1, col_w, row1_h, "Win Conditions + Avoid List")
    panel(x1, y2, wide_w, row2_h, "Chemistry")
    panel(x1 + wide_w + gap, y2, wide_w, row2_h, "Momentum + Ban Pressure")

    # Panel A: Snapshot (no bars)
    px = x1 + 18
    py = y1 + 54

    label_x = px
    value_x = px + 230
    pct_x = px + (col_w - 36) - 90

    for m in pack["snapshot_rows"]:
        draw.text((label_x, py), m["label"], font=body_font, fill=muted)
        draw.text((value_x, py), m["value_txt"], font=body_font, fill=text)
        pct_val = m.get("pct")
        pct_txt = "—" if pct_val is None else f"{pct_val:.0f}th"
        draw.text((pct_x, py), pct_txt, font=body_font, fill=text)
        py += 40

    # Panel B: Role mix + signature heroes (performance)
    bx = x2 + 18
    by = y1 + 54
    draw.text((bx, by), "Role mix (time share)", font=body_font, fill=muted)
    by += 30
    _profile_draw_role_mix_bar(draw, bx, by, col_w - 36, 22, pack["role_share"])
    by += 34

    rs = pack["role_share"]
    draw.text((bx, by),
              f"Vanguard {rs['Vanguard']*100:.0f}%   Duelist {rs['Duelist']*100:.0f}%   Strategist {rs['Strategist']*100:.0f}%",
              font=body_font,
              fill=text)
    by += 50

    draw.text((bx, by), "Signature heroes (top 5 by win%, ≥5 games)", font=body_font, fill=muted)
    by += 30

    # Shift columns LEFT so WR shows game count fully
    hero_col = bx
    time_col = bx + 270
    wr_col = bx + 380
    kda_col = bx + 520

    draw.text((hero_col, by), "Hero", font=body_font, fill=muted)
    draw.text((time_col, by), "Time", font=body_font, fill=muted)
    draw.text((wr_col, by), "WR", font=body_font, fill=muted)
    draw.text((kda_col, by), "KDA", font=body_font, fill=muted)
    by += 26

    sig = pack.get("signature_heroes", []) or []
    if not sig:
        draw.text((bx, by), "—", font=body_font, fill=text)
    else:
        for h in sig:
            hn = pack["hero_names"].get(h["hero_id"], str(h["hero_id"]))
            hn = _profile_clip_text(draw, hn, body_font, 255)
            draw.text((hero_col, by), hn, font=body_font, fill=text)
            draw.text((time_col, by), _fmt_time(h["seconds"]), font=body_font, fill=text)
            draw.text((wr_col, by), f"{h['win_pct']:.0f}% ({h['games']}g)", font=body_font, fill=text)
            draw.text((kda_col, by), f"{h['kda']:.2f}", font=body_font, fill=text)
            by += 32

    # Panel C: Best role + TEAMMATE HERO win/avoid
    cx = x3 + 18
    cy = y1 + 54

    br = pack.get("best_role")
    if br:
        draw.text((cx, cy),
                  f"Best primary role: {br['role']} ({br['win_pct']:.0f}% over {br['games']}g)",
                  font=body_font,
                  fill=text)
    else:
        draw.text((cx, cy), "Best primary role: —", font=body_font, fill=text)
    cy += 44

    draw.text((cx, cy), "Win conditions teammates (top 3 heroes)", font=body_font, fill=muted)
    cy += 30

    tw = pack.get("teammate_hero_win", []) or []
    if tw:
        for h in tw[:3]:
            hn = pack["hero_names"].get(h["hero_id"], str(h["hero_id"]))
            hn = _profile_clip_text(draw, hn, body_font, col_w - 36)
            draw.text((cx, cy),
                      f"• {hn}: {h['win_pct']:.0f}% ({h['games']}g)",
                      font=body_font,
                      fill=text)
            cy += 30
    else:
        draw.text((cx, cy), "—", font=body_font, fill=text)
        cy += 30

    cy += 14
    draw.text((cx, cy), "Avoid / risk teammates (bottom 3 heroes)", font=body_font, fill=muted)
    cy += 30

    tr = pack.get("teammate_hero_risk", []) or []
    if tr:
        for h in tr[:3]:
            hn = pack["hero_names"].get(h["hero_id"], str(h["hero_id"]))
            hn = _profile_clip_text(draw, hn, body_font, col_w - 36)
            draw.text((cx, cy),
                      f"• {hn}: {h['win_pct']:.0f}% ({h['games']}g)",
                      font=body_font,
                      fill=text)
            cy += 30
    else:
        draw.text((cx, cy), "—", font=body_font, fill=text)
        cy += 30

    # Panel D: Chemistry (no deltas)
    dx = x1 + 18
    dy = y2 + 54
    chem = pack["chemistry"]
    draw.text((dx, dy),
              f"Eligible games: {chem.get('eligible_games',0)} • Baseline WR: {chem.get('baseline',0.0):.1f}%",
              font=body_font,
              fill=muted)
    dy += 40

    draw.text((dx, dy), "Best allies", font=body_font, fill=accent)
    dy += 30
    if chem["best"]:
        for a in chem["best"]:
            nm = _profile_clip_text(draw, a["player"], body_font, wide_w - 60)
            draw.text((dx, dy),
                      f"• {nm}: {a['win_pct']:.0f}% ({a['wins']}/{a['games']})",
                      font=body_font,
                      fill=text)
            dy += 30
    else:
        draw.text((dx, dy), "—", font=body_font, fill=text)
        dy += 30

    dy += 10
    draw.text((dx, dy), "Worst pairings", font=body_font, fill=accent)
    dy += 30
    if chem["worst"]:
        for a in chem["worst"]:
            nm = _profile_clip_text(draw, a["player"], body_font, wide_w - 60)
            draw.text((dx, dy),
                      f"• {nm}: {a['win_pct']:.0f}% ({a['wins']}/{a['games']})",
                      font=body_font,
                      fill=text)
            dy += 30
    else:
        draw.text((dx, dy), "—", font=body_font, fill=text)
        dy += 30

    dy += 10
    draw.text((dx, dy), "Under-used synergy", font=body_font, fill=accent)
    dy += 30
    u = chem.get("underused")
    if u:
        nm = _profile_clip_text(draw, u["player"], body_font, wide_w - 60)
        draw.text((dx, dy),
                  f"• {nm}: {u['win_pct']:.0f}% ({u['wins']}/{u['games']})",
                  font=body_font,
                  fill=text)
    else:
        draw.text((dx, dy), "—", font=body_font, fill=text)

    # Panel E: Momentum + bans (no deltas)
    ex = x1 + wide_w + gap + 18
    ey = y2 + 54
    m10 = pack["momentum"]

    draw.text((ex, ey), "Last 10 games momentum", font=body_font, fill=accent)
    ey += 34

    if m10["games"]:
        draw.text((ex, ey), f"Win%: {m10['win_pct']:.1f}%", font=body_font, fill=text)
        ey += 28
        draw.text((ex, ey), f"Deaths/G: {m10['deaths_pg']:.2f}", font=body_font, fill=text)
        ey += 28
        draw.text((ex, ey), f"Final Hits/G: {m10['fh_pg']:.2f}", font=body_font, fill=text)
    else:
        draw.text((ex, ey), "Not enough data.", font=body_font, fill=text)
    ey += 44

    bans = pack["enemy_bans"]
    draw.text((ex, ey),
              f"Enemy ban pressure (eligible games: {bans['games']})",
              font=body_font,
              fill=accent)
    ey += 34

    if bans["top"]:
        for b in bans["top"]:
            hn = pack["hero_names"].get(b["hero_id"], str(b["hero_id"]))
            hn = _profile_clip_text(draw, hn, body_font, wide_w - 240)
            draw.text((ex, ey), f"• {hn}: {b['count']} ({b['pct']:.0f}%)", font=body_font, fill=text)
            ey += 28
    else:
        draw.text((ex, ey), "—", font=body_font, fill=text)

    # Footer
    foot = "Percentiles are against humans with ≥5 games. Accuracy shown only where session_hit_rate exists."
    draw.text((pad * 2, H - pad - 28), foot, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


