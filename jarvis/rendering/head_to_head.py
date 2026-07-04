import io

from PIL import Image, ImageDraw, ImageFont

from jarvis.rendering.fonts import get_fonts


def _h2h_draw_text_bold(draw, xy, text, font, fill, bold=False):
    x, y = xy
    if not bold:
        draw.text((x, y), text, font=font, fill=fill)
        return
    for dx, dy in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        draw.text((x + dx, y + dy), text, font=font, fill=fill)


def _h2h_text_wh(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except Exception:
        try:
            return draw.textsize(text, font=font)
        except Exception:
            return (len(str(text)) * 10, 20)


def _h2h_wrap_text_lines(draw, text, font, max_width: int):
    if not text:
        return ["—"]

    words = str(text).split()
    lines = []
    cur = ""

    def fits(s: str) -> bool:
        w, _ = _h2h_text_wh(draw, s, font)
        return w <= max_width

    for w in words:
        trial = w if not cur else f"{cur} {w}"
        if fits(trial):
            cur = trial
            continue

        if cur:
            lines.append(cur)
            cur = ""

        if not fits(w):
            chunk = ""
            for ch in w:
                t2 = chunk + ch
                if fits(t2):
                    chunk = t2
                else:
                    if chunk:
                        lines.append(chunk)
                    chunk = ch
            if chunk:
                cur = chunk
        else:
            cur = w

    if cur:
        lines.append(cur)

    return lines if lines else ["—"]


def _h2h_fmt_pct(v) -> str:
    return "—" if v is None else f"{float(v):.1f}%"


def _h2h_fmt_num(v) -> str:
    if v is None:
        return "—"
    try:
        fv = float(v)
        if fv.is_integer():
            return str(int(fv))
        return f"{fv:.2f}"
    except Exception:
        return str(v)


# -----------------------------
# TRUE H2H opponent matches (match_uid list)
# -----------------------------

def _h2h_render_matchup_image(
    title: str,
    a: dict,
    b: dict,
    pair: dict,
    a_hero_name: str | None = None,
    b_hero_name: str | None = None,
) -> io.BytesIO:
    if Image is None:
        buf = io.BytesIO()
        buf.seek(0)
        return buf

    try:
        body_font, title_font = get_fonts(body_pt=24, title_pt=44)
        small_font, _ = get_fonts(body_pt=20, title_pt=34)
    except Exception:
        body_font = title_font = small_font = None

    bg = (25, 25, 25)
    fg = (235, 235, 235)
    muted = (170, 170, 170)
    gold = (255, 215, 0)
    grid = (70, 70, 70)
    panel = (35, 35, 35)

    any_hero = bool(a_hero_name) or bool(b_hero_name)

    def _winner_flags(a_num, b_num, better: str):
        a_win = b_win = False
        if a_num is None or b_num is None:
            return a_win, b_win
        try:
            if better == "tuple_high":
                if a_num > b_num:
                    a_win = True
                elif b_num > a_num:
                    b_win = True
                return a_win, b_win
            av = float(a_num)
            bv = float(b_num)
            if better == "low":
                av, bv = -av, -bv
            if av > bv:
                a_win = True
            elif bv > av:
                b_win = True
        except Exception:
            pass
        return a_win, b_win

    def _sel_val(p: dict, key_h: str, key_h2h: str):
        return p[key_h] if p.get("hero_id") is not None else p[key_h2h]

    def _sel_acc(p: dict):
        return p["hero_accuracy"] if p.get("hero_id") is not None else p["h2h_accuracy"]

    def _sel_label(hero_name: str | None):
        return f"Hero: {hero_name}" if hero_name else "Opponents Only"

    # Rows
    if not any_hero:
        # Default: pure opponents-only H2H
        rows = [
            {"label": "H2H Win %", "a_disp": lambda: f"{a['h2h_win_pct']:.1f}%", "b_disp": lambda: f"{b['h2h_win_pct']:.1f}%",
             "a_num": lambda: a.get("h2h_win_pct"), "b_num": lambda: b.get("h2h_win_pct"), "better": "high"},
            {"label": "H2H W / L", "a_disp": lambda: f"{a['h2h_wins']}/{a['h2h_losses']}", "b_disp": lambda: f"{b['h2h_wins']}/{b['h2h_losses']}",
             "a_num": lambda: (a["h2h_wins"], -a["h2h_losses"]), "b_num": lambda: (b["h2h_wins"], -b["h2h_losses"]), "better": "tuple_high"},
            {"label": "H2H Avg KDA", "a_disp": lambda: f"{a['h2h_avg_kda']:.2f}", "b_disp": lambda: f"{b['h2h_avg_kda']:.2f}",
             "a_num": lambda: a.get("h2h_avg_kda"), "b_num": lambda: b.get("h2h_avg_kda"), "better": "high"},
            {"label": "H2H Kills / G", "a_disp": lambda: f"{a['h2h_avg_k']:.2f}", "b_disp": lambda: f"{b['h2h_avg_k']:.2f}",
             "a_num": lambda: a.get("h2h_avg_k"), "b_num": lambda: b.get("h2h_avg_k"), "better": "high"},
            {"label": "H2H Deaths / G", "a_disp": lambda: f"{a['h2h_avg_d']:.2f}", "b_disp": lambda: f"{b['h2h_avg_d']:.2f}",
             "a_num": lambda: a.get("h2h_avg_d"), "b_num": lambda: b.get("h2h_avg_d"), "better": "low"},
            {"label": "H2H Assists / G", "a_disp": lambda: f"{a['h2h_avg_a']:.2f}", "b_disp": lambda: f"{b['h2h_avg_a']:.2f}",
             "a_num": lambda: a.get("h2h_avg_a"), "b_num": lambda: b.get("h2h_avg_a"), "better": "high"},
            {"label": "H2H Damage / G", "a_disp": lambda: f"{int(round(a['h2h_avg_dmg']))}", "b_disp": lambda: f"{int(round(b['h2h_avg_dmg']))}",
             "a_num": lambda: a.get("h2h_avg_dmg"), "b_num": lambda: b.get("h2h_avg_dmg"), "better": "high"},
            {"label": "H2H Heal / G", "a_disp": lambda: f"{int(round(a['h2h_avg_heal']))}", "b_disp": lambda: f"{int(round(b['h2h_avg_heal']))}",
             "a_num": lambda: a.get("h2h_avg_heal"), "b_num": lambda: b.get("h2h_avg_heal"), "better": "high"},
            {"label": "H2H Taken / G", "a_disp": lambda: f"{int(round(a['h2h_avg_taken']))}", "b_disp": lambda: f"{int(round(b['h2h_avg_taken']))}",
             "a_num": lambda: a.get("h2h_avg_taken"), "b_num": lambda: b.get("h2h_avg_taken"), "better": "low"},
            {"label": "H2H MVP", "a_disp": lambda: str(int(a["h2h_mvp"])), "b_disp": lambda: str(int(b["h2h_mvp"])),
             "a_num": lambda: a.get("h2h_mvp"), "b_num": lambda: b.get("h2h_mvp"), "better": "high"},
            {"label": "H2H SVP", "a_disp": lambda: str(int(a["h2h_svp"])), "b_disp": lambda: str(int(b["h2h_svp"])),
             "a_num": lambda: a.get("h2h_svp"), "b_num": lambda: b.get("h2h_svp"), "better": "high"},
            {"label": "H2H Hero Pool", "a_disp": lambda: str(int(a["h2h_hero_pool"])), "b_disp": lambda: str(int(b["h2h_hero_pool"])),
             "a_num": lambda: a.get("h2h_hero_pool"), "b_num": lambda: b.get("h2h_hero_pool"), "better": "high"},
            {"label": "H2H Accuracy", "a_disp": lambda: ("—" if a.get("h2h_accuracy") is None else f"{a['h2h_accuracy']*100:.1f}%"),
             "b_disp": lambda: ("—" if b.get("h2h_accuracy") is None else f"{b['h2h_accuracy']*100:.1f}%"),
             "a_num": lambda: (a["h2h_accuracy"] * 100.0) if a.get("h2h_accuracy") is not None else None,
             "b_num": lambda: (b["h2h_accuracy"] * 100.0) if b.get("h2h_accuracy") is not None else None,
             "better": "high"},
        ]
    else:
        # Hero compare (cross-hero / mixed)
        rows = [
            {"label": "Win %", "a_disp": lambda: f"{_sel_val(a,'hero_win_pct','h2h_win_pct'):.1f}%", "b_disp": lambda: f"{_sel_val(b,'hero_win_pct','h2h_win_pct'):.1f}%",
             "a_num": lambda: _sel_val(a,'hero_win_pct','h2h_win_pct'), "b_num": lambda: _sel_val(b,'hero_win_pct','h2h_win_pct'), "better": "high"},

            {"label": "Games", "a_disp": lambda: str(int(_sel_val(a,'hero_games','h2h_games'))), "b_disp": lambda: str(int(_sel_val(b,'hero_games','h2h_games'))),
             "a_num": lambda: None, "b_num": lambda: None, "better": "none"},

            {"label": "Avg KDA", "a_disp": lambda: f"{_sel_val(a,'hero_avg_kda','h2h_avg_kda'):.2f}", "b_disp": lambda: f"{_sel_val(b,'hero_avg_kda','h2h_avg_kda'):.2f}",
             "a_num": lambda: _sel_val(a,'hero_avg_kda','h2h_avg_kda'), "b_num": lambda: _sel_val(b,'hero_avg_kda','h2h_avg_kda'), "better": "high"},

            {"label": "Kills / G", "a_disp": lambda: f"{_sel_val(a,'hero_avg_k','h2h_avg_k'):.2f}", "b_disp": lambda: f"{_sel_val(b,'hero_avg_k','h2h_avg_k'):.2f}",
             "a_num": lambda: _sel_val(a,'hero_avg_k','h2h_avg_k'), "b_num": lambda: _sel_val(b,'hero_avg_k','h2h_avg_k'), "better": "high"},

            {"label": "Deaths / G", "a_disp": lambda: f"{_sel_val(a,'hero_avg_d','h2h_avg_d'):.2f}", "b_disp": lambda: f"{_sel_val(b,'hero_avg_d','h2h_avg_d'):.2f}",
             "a_num": lambda: _sel_val(a,'hero_avg_d','h2h_avg_d'), "b_num": lambda: _sel_val(b,'hero_avg_d','h2h_avg_d'), "better": "low"},

            {"label": "Assists / G", "a_disp": lambda: f"{_sel_val(a,'hero_avg_a','h2h_avg_a'):.2f}", "b_disp": lambda: f"{_sel_val(b,'hero_avg_a','h2h_avg_a'):.2f}",
             "a_num": lambda: _sel_val(a,'hero_avg_a','h2h_avg_a'), "b_num": lambda: _sel_val(b,'hero_avg_a','h2h_avg_a'), "better": "high"},

            {"label": "Final Hits / G",
             "a_disp": lambda: f"{_sel_val(a,'hero_avg_final_hits','h2h_avg_final_hits'):.2f}",
             "b_disp": lambda: f"{_sel_val(b,'hero_avg_final_hits','h2h_avg_final_hits'):.2f}",
             "a_num":  lambda: _sel_val(a,'hero_avg_final_hits','h2h_avg_final_hits'),
             "b_num":  lambda: _sel_val(b,'hero_avg_final_hits','h2h_avg_final_hits'),
             "better": "high"},

            {"label": "Solo Kills / G",
             "a_disp": lambda: f"{_sel_val(a,'hero_avg_solo_kills','h2h_avg_solo_kills'):.2f}",
             "b_disp": lambda: f"{_sel_val(b,'hero_avg_solo_kills','h2h_avg_solo_kills'):.2f}",
             "a_num":  lambda: _sel_val(a,'hero_avg_solo_kills','h2h_avg_solo_kills'),
             "b_num":  lambda: _sel_val(b,'hero_avg_solo_kills','h2h_avg_solo_kills'),
             "better": "high"},

            {"label": "Damage / G", "a_disp": lambda: f"{int(round(_sel_val(a,'hero_avg_dmg','h2h_avg_dmg')))}", "b_disp": lambda: f"{int(round(_sel_val(b,'hero_avg_dmg','h2h_avg_dmg')))}",
             "a_num": lambda: _sel_val(a,'hero_avg_dmg','h2h_avg_dmg'), "b_num": lambda: _sel_val(b,'hero_avg_dmg','h2h_avg_dmg'), "better": "high"},

            {"label": "Healing / G", "a_disp": lambda: f"{int(round(_sel_val(a,'hero_avg_heal','h2h_avg_heal')))}", "b_disp": lambda: f"{int(round(_sel_val(b,'hero_avg_heal','h2h_avg_heal')))}",
             "a_num": lambda: _sel_val(a,'hero_avg_heal','h2h_avg_heal'), "b_num": lambda: _sel_val(b,'hero_avg_heal','h2h_avg_heal'), "better": "high"},

            {"label": "Taken / G", "a_disp": lambda: f"{int(round(_sel_val(a,'hero_avg_taken','h2h_avg_taken')))}", "b_disp": lambda: f"{int(round(_sel_val(b,'hero_avg_taken','h2h_avg_taken')))}",
             "a_num": lambda: _sel_val(a,'hero_avg_taken','h2h_avg_taken'), "b_num": lambda: _sel_val(b,'hero_avg_taken','h2h_avg_taken'), "better": "low"},

            {"label": "Time (min)", "a_disp": lambda: _h2h_fmt_num((_sel_val(a,'hero_seconds','h2h_seconds') or 0) / 60.0),
             "b_disp": lambda: _h2h_fmt_num((_sel_val(b,'hero_seconds','h2h_seconds') or 0) / 60.0),
             "a_num": lambda: None, "b_num": lambda: None, "better": "none"},

            {"label": "Time / G (min)", "a_disp": lambda: _h2h_fmt_num((_sel_val(a,'hero_avg_seconds','h2h_avg_seconds') or 0) / 60.0),
             "b_disp": lambda: _h2h_fmt_num((_sel_val(b,'hero_avg_seconds','h2h_avg_seconds') or 0) / 60.0),
             "a_num": lambda: None, "b_num": lambda: None, "better": "none"},

            {"label": "Accuracy", "a_disp": lambda: ("—" if _sel_acc(a) is None else f"{_sel_acc(a)*100:.1f}%"),
             "b_disp": lambda: ("—" if _sel_acc(b) is None else f"{_sel_acc(b)*100:.1f}%"),
             "a_num": lambda: (_sel_acc(a) * 100.0) if _sel_acc(a) is not None else None,
             "b_num": lambda: (_sel_acc(b) * 100.0) if _sel_acc(b) is not None else None,
             "better": "high"},
        ]

    # Geometry
    W = 1200
    pad = 30
    row_h = 46
    col_gap = 20
    label_w = 240
    col_w = (W - pad * 2 - label_w - col_gap * 2) // 2
    ax = pad
    lx = pad + col_w + col_gap
    bx = lx + label_w + col_gap

    # Measure header + footer using temp canvas
    tmp_img = Image.new("RGB", (10, 10), bg)
    tmp_draw = ImageDraw.Draw(tmp_img)

    _, title_h = _h2h_text_wh(tmp_draw, title, title_font)
    y_header = pad + title_h + 10

    header_lines = []
    if any_hero:
        header_lines.append(f"A: {_sel_label(a_hero_name)}   •   B: {_sel_label(b_hero_name)}")
    header_lines.append(f"Opponents: {a['name']} {pair['a_wins']}-{pair['b_wins']} {b['name']}  (games: {pair['opp_games']})")
    header_lines.append(f"Teammates: {pair['duo_wins']}-{pair['duo_losses']}  (games: {pair['duo_games']})")

    line_gap = 6
    cur_y = y_header
    for line in header_lines:
        _, lh = _h2h_text_wh(tmp_draw, line, small_font)
        cur_y += lh + line_gap
    header_text_bottom = cur_y

    # Push table down enough so header boxes never overlap header text
    y0 = int(header_text_bottom + 14 + 85)

    # Footer paragraphs (season context; wrapped)
    a_lt = "—" if a.get("low_team_pct") is None else f"{a['low_team_pct']:.1f}% ({a['low_team_on_less']}/{a['low_team_uneven']})"
    b_lt = "—" if b.get("low_team_pct") is None else f"{b['low_team_pct']:.1f}% ({b['low_team_on_less']}/{b['low_team_uneven']})"
    a_v = "—" if a.get("vers_pct") is None else f"{a['vers_pct']:.1f}% (K={a.get('vers_heroes',0)})"
    b_v = "—" if b.get("vers_pct") is None else f"{b['vers_pct']:.1f}% (K={b.get('vers_heroes',0)})"

    left_paras = [
        f"Season Win%: {a['season_win_pct']:.1f}%   Low-team: {a_lt}   Vers: {a_v}",
        f"Season Top Hero: {a['top_hero']}",
        f"Badges: {a['badges']}",
    ]
    right_paras = [
        f"Season Win%: {b['season_win_pct']:.1f}%   Low-team: {b_lt}   Vers: {b_v}",
        f"Season Top Hero: {b['top_hero']}",
        f"Badges: {b['badges']}",
    ]

    col_text_w = col_w - 32
    left_lines = []
    right_lines = []

    for p in left_paras:
        left_lines.extend(_h2h_wrap_text_lines(tmp_draw, p, small_font, col_text_w))
        left_lines.append("")
    for p in right_paras:
        right_lines.extend(_h2h_wrap_text_lines(tmp_draw, p, small_font, col_text_w))
        right_lines.append("")

    while left_lines and left_lines[-1] == "":
        left_lines.pop()
    while right_lines and right_lines[-1] == "":
        right_lines.pop()

    _, base_lh = _h2h_text_wh(tmp_draw, "Ag", small_font)
    footer_line_h = base_lh + 4
    footer_pad_top = 18
    footer_pad_bot = 18
    max_footer_lines = max(len(left_lines), len(right_lines), 1)
    footer_h = footer_pad_top + max_footer_lines * footer_line_h + footer_pad_bot

    H = int(y0 + len(rows) * row_h + footer_h + pad)

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    d.text((pad, pad), title, font=title_font, fill=gold)

    cur_y = y_header
    for line in header_lines:
        d.text((pad, cur_y), line, font=small_font, fill=fg)
        _, lh = _h2h_text_wh(d, line, small_font)
        cur_y += lh + line_gap

    # Header boxes
    d.rectangle([ax, y0 - 85, ax + col_w, y0 - 10], fill=panel, outline=grid, width=2)
    d.rectangle([bx, y0 - 85, bx + col_w, y0 - 10], fill=panel, outline=grid, width=2)
    d.rectangle([lx, y0 - 85, lx + label_w, y0 - 10], fill=(30, 30, 30), outline=grid, width=2)

    d.text((ax + 16, y0 - 74), a["name"][:24], font=body_font, fill=fg)
    d.text((bx + 16, y0 - 74), b["name"][:24], font=body_font, fill=fg)

    # Under-name status line
    if any_hero:
        a_sel_games = int(_sel_val(a, "hero_games", "h2h_games"))
        a_sel_win = float(_sel_val(a, "hero_win_pct", "h2h_win_pct"))
        b_sel_games = int(_sel_val(b, "hero_games", "h2h_games"))
        b_sel_win = float(_sel_val(b, "hero_win_pct", "h2h_win_pct"))

        d.text((ax + 16, y0 - 44), f"{_sel_label(a_hero_name)}   •   Games: {a_sel_games}   Win%: {a_sel_win:.1f}%", font=small_font, fill=muted)
        d.text((bx + 16, y0 - 44), f"{_sel_label(b_hero_name)}   •   Games: {b_sel_games}   Win%: {b_sel_win:.1f}%", font=small_font, fill=muted)
        d.text((lx + 16, y0 - 62), "HERO COMPARE", font=small_font, fill=fg)
    else:
        d.text((ax + 16, y0 - 44), f"H2H Games: {a['h2h_games']}   H2H Win%: {a['h2h_win_pct']:.1f}%", font=small_font, fill=muted)
        d.text((bx + 16, y0 - 44), f"H2H Games: {b['h2h_games']}   H2H Win%: {b['h2h_win_pct']:.1f}%", font=small_font, fill=muted)
        d.text((lx + 16, y0 - 62), "HEAD TO HEAD", font=small_font, fill=fg)

    # Grid rows
    y = y0
    for row in rows:
        d.rectangle([ax, y, ax + col_w, y + row_h], outline=grid)
        d.rectangle([lx, y, lx + label_w, y + row_h], outline=grid)
        d.rectangle([bx, y, bx + col_w, y + row_h], outline=grid)

        a_txt = row["a_disp"]()
        b_txt = row["b_disp"]()
        better = row.get("better", "high")

        a_num = row["a_num"]()
        b_num = row["b_num"]()

        a_win = b_win = False
        if better not in ("none",):
            a_win, b_win = _winner_flags(a_num, b_num, better)

        d.text((lx + 16, y + 12), row["label"], font=small_font, fill=fg)
        _h2h_draw_text_bold(d, (ax + 16, y + 10), str(a_txt), body_font, fg, bold=a_win)
        _h2h_draw_text_bold(d, (bx + 16, y + 10), str(b_txt), body_font, fg, bold=b_win)

        y += row_h

    # Footer (wrapped per column)
    fy = y + footer_pad_top
    ly = fy
    ry = fy

    for line in left_lines:
        if line == "":
            ly += footer_line_h // 2
            continue
        d.text((ax + 16, ly), line, font=small_font, fill=muted)
        ly += footer_line_h

    for line in right_lines:
        if line == "":
            ry += footer_line_h // 2
            continue
        d.text((bx + 16, ry), line, font=small_font, fill=muted)
        ry += footer_line_h

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
