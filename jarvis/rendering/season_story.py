import io
import math

from PIL import Image, ImageDraw, ImageFont
from jarvis.rendering.fonts import get_fonts

SS_TOP_ACTIVE=5
SS_TOP_VERSATILE=5
SS_TOP_BOT_HEROES=5
SS_MIN_HALF_GAMES=3
SS_TOP_IMPROVED=5
SS_MIN_DUO_GAMES=5
SS_TOP_DUOS=5
SS_TOP_SYNERGY=5
SS_TOP_DOMINANT=5
SS_TOP_TIER=5
SS_TIER_MIN_PICKS=10
SS_TOP_BANS=5
SS_ROLE_PLOT_TITLE="Role Distribution (All Players)"
SS_ROLE_LABEL_MAX=12
SS_ROLE_DOT_R=6
SS_ROLE_GRID_STEPS=(0.2,0.4,0.6,0.8)
SS_ROLE_PLOT_TOP_PAD=30


def _ss_clip(value, length):
    value=str(value or "")
    return value if len(value)<=length else value[:max(0,length-1)]+"…"


def _ss_draw_role_ternary_plot(draw: "ImageDraw.ImageDraw",
                              x: int, y: int, width: int, height: int,
                              role_rows: list[dict],
                              player_names: dict[int, str],
                              body_font: "ImageFont.ImageFont",
                              LH: int,
                              accent, text, muted, line):
    """
    Draws a role ternary plot in the provided rectangle.
    v (Vanguard) at top, d (Duelist) bottom-left, s (Strategist) bottom-right.
    """
    # title + separator
    draw.text((x, y), SS_ROLE_PLOT_TITLE, font=body_font, fill=accent)
    y_sep = y + LH
    draw.line([(x, y_sep), (x + width, y_sep)], fill=line, width=2)

    y_plot = y_sep + SS_ROLE_PLOT_TOP_PAD

    # compute plot height based on actual top offset (more robust than LH+14)
    h_plot = max(180, height - (y_plot - y) - 2)

    if not role_rows:
        draw.text((x, y_plot), "No role distribution data available yet.", font=body_font, fill=text)
        return

    # Fit an equilateral triangle inside (width x h_plot)
    sqrt3 = math.sqrt(3.0)
    side = min(float(width), float(h_plot) * 2.0 / sqrt3)
    tri_h = side * sqrt3 / 2.0

    # center triangle within the plot box
    x_left = float(x) + (float(width) - side) / 2.0
    y_top = float(y_plot) + (float(h_plot) - tri_h) / 2.0
    y_bottom = y_top + tri_h

    A = (x_left + side / 2.0, y_top)        # Vanguard
    B = (x_left, y_bottom)                  # Duelist
    C = (x_left + side, y_bottom)           # Strategist

    def mix(P, Q, t: float):
        return (t * P[0] + (1.0 - t) * Q[0], t * P[1] + (1.0 - t) * Q[1])

    # grid lines
    grid_col = (70, 70, 90)
    for t in SS_ROLE_GRID_STEPS:
        # v = t  (parallel to base BC): between AB and AC
        p1 = mix(A, B, t)
        p2 = mix(A, C, t)
        draw.line([p1, p2], fill=grid_col, width=1)

        # d = t  (parallel to AC): between AB and BC
        p3 = mix(B, A, t)
        p4 = mix(B, C, t)
        draw.line([p3, p4], fill=grid_col, width=1)

        # s = t  (parallel to AB): between AC and BC
        p5 = mix(C, A, t)
        p6 = mix(C, B, t)
        draw.line([p5, p6], fill=grid_col, width=1)

    # triangle outline
    draw.line([A, B], fill=muted, width=3)
    draw.line([B, C], fill=muted, width=3)
    draw.line([C, A], fill=muted, width=3)

    # axis labels
    def _tw(s: str) -> float:
        try:
            return float(draw.textlength(s, font=body_font))
        except Exception:
            return float(len(s) * 9)

    lab_v = "Vanguard"
    lab_d = "Duelist"
    lab_s = "Strategist"

    draw.text((A[0] - _tw(lab_v) / 2.0, A[1] - LH - 4), lab_v, font=body_font, fill=accent)
    draw.text((B[0] - _tw(lab_d) / 2.0, B[1] + 6), lab_d, font=body_font, fill=accent)
    draw.text((C[0] - _tw(lab_s) / 2.0, C[1] + 6), lab_s, font=body_font, fill=accent)

    # dot plotting (with small cycling label offsets)
    offsets = [(10, -14), (10, 4), (-10, -14), (-10, 4), (14, -6), (-14, -6)]

    for idx, r in enumerate(role_rows):
        uid = int(r.get("player_uid", 0))
        v = float(r.get("v", 0.0))
        d = float(r.get("d", 0.0))
        s = float(r.get("s", 0.0))

        # barycentric -> cartesian
        px = d * B[0] + s * C[0] + v * A[0]
        py = d * B[1] + s * C[1] + v * A[1]

        rr = SS_ROLE_DOT_R
        draw.ellipse([px - rr, py - rr, px + rr, py + rr], fill=accent, outline=(0, 0, 0), width=1)

        name = _ss_clip(player_names.get(uid, f"UID_{uid}"), SS_ROLE_LABEL_MAX)
        dx, dy = offsets[idx % len(offsets)]
        tx = px + dx
        ty = py + dy

        # keep labels within plot area bounds (basic clamp)
        tx = max(float(x), min(tx, float(x + width) - _tw(name) - 2.0))
        ty = max(float(y_plot), min(ty, float(y_plot + h_plot) - LH))

        draw.text((tx, ty), name, font=body_font, fill=text)

def _ss_render(season_id: int,
               core: dict,
               player_names: dict[int, str],
               hero_names: dict[int, str],
               versatile: list[dict],
               bot_heroes: list[dict],
               synergy: list[dict],
               dominant: list[dict],
               tier: list[dict],
               bans: list[dict],
               role_rows: list[dict]) -> io.BytesIO:

    if Image is None:
        raise RuntimeError("PIL not available")

    W, H = 1850, 1380
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
        fonts = get_fonts()
        if isinstance(fonts, tuple) and len(fonts) >= 2:
            body_font = fonts[0]
            title_font = fonts[1]
        else:
            body_font = ImageFont.load_default()
            title_font = ImageFont.load_default()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)
    draw.text((pad * 2, int(pad * 1.35)), f"Season Story — Season {season_id}", font=title_font, fill=accent)

    subtitle_parts = [
        f"Games: {core.get('total_games', 0)}",
        f"Players: {core.get('unique_players', 0)}",
        f"Uneven: {core.get('uneven_games', 0)} (Underdog wins: {core.get('underdog_wins', 0)})",
    ]
    if core.get("date_range"):
        subtitle_parts.append(f"Dates: {core['date_range']}")
    draw.text((pad * 2, int(pad * 2.6)), "  •  ".join(subtitle_parts), font=body_font, fill=muted)

    left_x = pad * 2
    right_x = int(W * 0.54)
    top_y = int(pad * 3.95)
    LH = 28
    SEC_W = 820

    def _tw(s: str) -> float:
        try:
            return float(draw.textlength(s, font=body_font))
        except Exception:
            return float(len(s) * 9)

    def _fit(s: str, max_w: int) -> str:
        if _tw(s) <= max_w:
            return s
        t = s
        while t and _tw(t + "…") > max_w:
            t = t[:-1]
        return (t + "…") if t else "…"

    def section(x: int, y: int, title_s: str, lines: list[str], width: int = SEC_W) -> int:
        draw.text((x, y), title_s, font=body_font, fill=accent)
        y += LH
        draw.line([(x, y), (x + width, y)], fill=line, width=2)
        y += 8
        for ln in lines:
            draw.text((x, y), _fit(ln, width), font=body_font, fill=text)
            y += LH
        return y + 10

    def wrap_names(prefix: str, uids: list[int], max_w: int, max_lines: int = 3) -> list[str]:
        if not uids:
            return [_fit(prefix + "—", max_w)]
        prefix2 = " " * len(prefix)
        tokens = [_ss_clip(player_names.get(int(u), f"UID_{u}"), 12) for u in uids]
        lines, cur, used = [], prefix, 0
        for t in tokens:
            add = (", " + t) if used > 0 else t
            if _tw(cur + add) > max_w and used > 0:
                lines.append(_fit(cur, max_w))
                if len(lines) >= max_lines:
                    break
                cur = prefix2 + t
                used = 1
            else:
                cur += add
                used += 1
        if len(lines) < max_lines and cur.strip():
            lines.append(_fit(cur, max_w))
        remaining = max(0, len(tokens) - sum(len([p for p in ln.split(",") if p.strip()]) for ln in lines))
        if remaining > 0 and lines:
            suffix = f" +{remaining}"
            if _tw(lines[-1] + suffix) <= max_w:
                lines[-1] += suffix
        return lines[:max_lines]

    # LEFT
    yL = top_y

    lines = []
    for uid, g, w in (core.get("most_active") or []):
        nm = player_names.get(int(uid), f"UID_{uid}")
        lines.append(f"{_ss_clip(nm, 22)} — {int(g)} games ({int(w)}-{int(g)-int(w)})")
    if not lines:
        lines = ["No human matches recorded yet."]
    yL = section(left_x, yL, f"Most Active Players (Top {SS_TOP_ACTIVE})", lines)

    lines = []
    if versatile:
        for i, r in enumerate(versatile[:SS_TOP_VERSATILE], start=1):
            uid = int(r["player_uid"])
            nm = player_names.get(uid, f"UID_{uid}")
            lines.append(
                f"{i}. {_ss_clip(nm, 20)} — {int(r['unique_heroes'])} heroes — {float(r['vers_pct']):.1f}%"
                f" (avg {float(r['avg_share']):.1f}% per hero)"
            )
    else:
        lines = ["No versatility results yet (needs eligible hero segments)."]
    yL = section(left_x, yL, f"Most Versatile Players (Top {SS_TOP_VERSATILE})", lines)

    lines = []
    if bot_heroes:
        for i, r in enumerate(bot_heroes[:SS_TOP_BOT_HEROES], start=1):
            hid = int(r.get("hero_id", 0))
            hn = hero_names.get(hid) or "Unknown Hero"
            picks = int(r.get("picks", 0))
            wins = int(r.get("wins", 0))
            losses = int(r.get("losses", 0))
            wp = float(r.get("win_pct", 0.0))
            lines.append(f"{i}. {_ss_clip(hn, 24)} — {wp:.1f}% ({wins}/{losses}) • {picks} picks")
    else:
        lines = ["No bot hero data available yet."]
    yL = section(left_x, yL, f"Top Bot Heroes by Win% (Top {SS_TOP_BOT_HEROES})", lines)

    imp = core.get("improved") or []
    lines = []
    if imp:
        for rank, (uid, delta, p1, p2) in enumerate(imp, start=1):
            nm = player_names.get(int(uid), f"UID_{uid}")
            sign = "+" if float(delta) >= 0 else ""
            lines.append(f"{rank}. {_ss_clip(nm, 20)} — {sign}{float(delta):.1f}% ({float(p1):.1f}% → {float(p2):.1f}%)")
    else:
        lines = [f"Not enough games per half (min {SS_MIN_HALF_GAMES} each)."]
    yL = section(left_x, yL, f"Most Improved (Top {SS_TOP_IMPROVED})", lines)

    lines = []
    if synergy:
        for i, r in enumerate(synergy[:SS_TOP_SYNERGY], start=1):
            a = int(r["a"]); b = int(r["b"])
            an = hero_names.get(a) or "Unknown Hero"
            bn = hero_names.get(b) or "Unknown Hero"
            lines.append(f"{i}. {_ss_clip(an, 18)} + {_ss_clip(bn, 18)} — {float(r['win_pct']):.1f}% ({int(r['wins'])}/{int(r['games'])})")
    else:
        lines = ["No synergy results available yet."]
    yL = section(left_x, yL, f"Hero Synergy (Top {SS_TOP_SYNERGY})", lines)

    lines = []
    if dominant:
        for i, r in enumerate(dominant[:SS_TOP_DOMINANT], start=1):
            hid = int(r.get("hero_id", 0))
            uid = int(r.get("player_uid", 0))
            hn = hero_names.get(hid) or "Unknown Hero"
            pn = player_names.get(uid, f"UID_{uid}")
            wp = float(r.get("win_pct", 0.0))
            wins = int(r.get("wins", 0))
            matches = int(r.get("matches", 0))
            lines.append(f"{i}. {_ss_clip(hn, 18)} — {_ss_clip(pn, 16)} — {wp:.1f}% ({wins}/{matches})")
    else:
        lines = ["No dominant hero results available yet."]
    yL = section(left_x, yL, f"Most Dominant Heroes (Top {SS_TOP_DOMINANT})", lines)

    # RIGHT
    yR = top_y

    du = core.get("best_duos") or []
    lines = []
    if du:
        for rank, (a, b, wp, w, g) in enumerate(du, start=1):
            na = player_names.get(int(a), f"UID_{a}")
            nb = player_names.get(int(b), f"UID_{b}")
            lines.append(f"{rank}. {_ss_clip(na, 14)} + {_ss_clip(nb, 14)} — {float(wp):.1f}% ({int(w)}/{int(g)})")
    else:
        lines = [f"No duos meet min games together ({SS_MIN_DUO_GAMES})."]
    yR = section(right_x, yR, f"Best Duos (Top {SS_TOP_DUOS}, min {SS_MIN_DUO_GAMES})", lines)

    lines = []
    if tier:
        for i, r in enumerate(tier[:SS_TOP_TIER], start=1):
            hid = int(r.get("hero_id", 0))
            hn = hero_names.get(hid) or "Unknown Hero"
            picks = int(r.get("picks", 0) or 0)
            wins = int(r.get("wins", 0) or 0)
            wp = float(r.get("win_pct", 0.0) or 0.0)
            lines.append(f"{i}. {_ss_clip(hn, 22)} — {wp:.1f}% ({wins}/{picks})")
    else:
        lines = [f"No heroes meet min {SS_TIER_MIN_PICKS} eligible picks yet."]
    yR = section(right_x, yR, f"Hero Tier List (Top {SS_TOP_TIER}, min {SS_TIER_MIN_PICKS})", lines)

    lines = []
    if bans:
        for r in bans[:SS_TOP_BANS]:
            hid = int(r["hero_id"])
            hn = hero_names.get(hid) or "Unknown Hero"
            lines.append(f"• {_ss_clip(hn, 28)} — {int(r['bans'])} bans")
    else:
        lines = ["No ban data recorded yet."]
    yR = section(right_x, yR, f"Most Banned Heroes (Top {SS_TOP_BANS})", lines)

    upset = core.get("biggest_upset")
    if upset:
        gl = str(upset.get("game_label", "Unknown"))
        fav_c = int(upset.get("fav_camp", -1))
        dog_c = int(upset.get("dog_camp", -1))
        dog_pct = float(upset.get("dog_pct", 0.0))
        fav_pct = float(upset.get("fav_pct", 0.0))

        lines = [
            f"{gl} — Underdog win (Team {dog_c} beat Team {fav_c})",
            f"Pre-game strength: {dog_pct:.1f}% vs {fav_pct:.1f}%",
        ]
        lines.extend(wrap_names("T0: ", upset.get("team0_uids", []) or [], SEC_W, max_lines=3))
        lines.extend(wrap_names("T1: ", upset.get("team1_uids", []) or [], SEC_W, max_lines=3))
    else:
        lines = ["No upsets yet (needs enough pre-game history)."]
    yR = section(right_x, yR, "Biggest Upset (pre-game strength)", lines)

    # Role Distribution plot uses remaining right-column space
    bottom_limit = H - pad - 78
    remaining = max(0, bottom_limit - yR)
    if remaining >= 220:
        _ss_draw_role_ternary_plot(
            draw=draw,
            x=right_x,
            y=yR,
            width=SEC_W,
            height=remaining,
            role_rows=role_rows,
            player_names=player_names,
            body_font=body_font,
            LH=LH,
            accent=accent,
            text=text,
            muted=muted,
            line=line
        )

    footer = "Bot section matches !leaderboard_image bots (bot hero performance)."
    draw.text((pad * 2, H - pad - 52), _fit(footer, W - pad * 4), font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
