import io

from PIL import Image, ImageDraw

from jarvis.rendering.fonts import get_fonts



def _so_clip(s: str, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")


def _so_draw_role_triangle_panel(draw, x0: int, y0: int, w: int, h: int,
                                 *,
                                 title: str,
                                 role_rows: list[dict],
                                 player_names: dict[int, str],
                                 body_font,
                                 fg,
                                 gold,
                                 grid):
    """
    Draw ternary plot in a bounded panel:
      - Vanguard (top), Duelist (bottom-left), Strategist (bottom-right)
    """
    import math

    pad_in = 12
    lh = max(22, int(getattr(body_font, "size", 18) + 8))

    # Title
    draw.text((x0 + pad_in, y0 + pad_in), str(title or "Role Distribution — Session"), font=body_font, fill=gold)
    y_sep = y0 + pad_in + lh
    draw.line([(x0 + pad_in, y_sep), (x0 + w - pad_in, y_sep)], fill=grid, width=2)

    # Plot bounds
    plot_top = y_sep + 10
    plot_left = x0 + pad_in
    plot_w = max(10, w - pad_in * 2)
    plot_h = max(10, h - (plot_top - y0) - pad_in)

    if not role_rows:
        draw.text((plot_left, plot_top), "No role distribution data available for this session yet.", font=body_font, fill=fg)
        return

    sqrt3 = math.sqrt(3.0)
    side = min(float(plot_w), float(plot_h) * 2.0 / sqrt3)
    tri_h = side * sqrt3 / 2.0

    x_left = float(plot_left) + (float(plot_w) - side) / 2.0
    y_top = float(plot_top) + (float(plot_h) - tri_h) / 2.0
    y_bottom = y_top + tri_h

    A = (x_left + side / 2.0, y_top)       # Vanguard
    B = (x_left, y_bottom)                 # Duelist
    C = (x_left + side, y_bottom)          # Strategist

    # Grid
    def mix(P, Q, t: float):
        return (t * P[0] + (1.0 - t) * Q[0], t * P[1] + (1.0 - t) * Q[1])

    grid_col = (70, 70, 90)
    for t in (0.2, 0.4, 0.6, 0.8):
        p1 = mix(A, B, t)
        p2 = mix(A, C, t)
        draw.line([p1, p2], fill=grid_col, width=1)

        p3 = mix(B, A, t)
        p4 = mix(B, C, t)
        draw.line([p3, p4], fill=grid_col, width=1)

        p5 = mix(C, A, t)
        p6 = mix(C, B, t)
        draw.line([p5, p6], fill=grid_col, width=1)

    # Triangle outline
    draw.line([A, B], fill=grid, width=3)
    draw.line([B, C], fill=grid, width=3)
    draw.line([C, A], fill=grid, width=3)

    # Labels
    def _tw(s: str) -> float:
        try:
            return float(draw.textlength(s, font=body_font))
        except Exception:
            return float(len(s) * 9)

    lab_v = "Vanguard"
    lab_d = "Duelist"
    lab_s = "Strategist"

    draw.text((A[0] - _tw(lab_v) / 2.0, A[1] - lh - 4), lab_v, font=body_font, fill=gold)
    draw.text((B[0] - _tw(lab_d) / 2.0, B[1] + 6), lab_d, font=body_font, fill=gold)
    draw.text((C[0] - _tw(lab_s) / 2.0, C[1] + 6), lab_s, font=body_font, fill=gold)

    # Points + name labels (light offsets, clamped)
    offsets = [(10, -14), (10, 4), (-10, -14), (-10, 4), (14, -6), (-14, -6)]
    rr = 6

    for idx, r in enumerate(role_rows):
        uid = int(r.get("player_uid", 0) or 0)
        v = float(r.get("v", 0.0) or 0.0)
        d = float(r.get("d", 0.0) or 0.0)
        s = float(r.get("s", 0.0) or 0.0)

        # barycentric to Cartesian
        px = d * B[0] + s * C[0] + v * A[0]
        py = d * B[1] + s * C[1] + v * A[1]

        draw.ellipse([px - rr, py - rr, px + rr, py + rr], fill=gold, outline=(0, 0, 0), width=1)

        name = _so_clip(player_names.get(uid, f"UID_{uid}"), 14)
        dx, dy = offsets[idx % len(offsets)]
        tx = px + dx
        ty = py + dy

        tx = max(float(plot_left), min(tx, float(plot_left + plot_w) - _tw(name) - 2.0))
        ty = max(float(plot_top), min(ty, float(plot_top + plot_h) - lh))

        draw.text((tx, ty), name, font=body_font, fill=fg)


# ------------------------------------------------------------------------------------------------------------
# Session overview image renderer
# The right-side panel displays the Role Distribution triangle.
# ------------------------------------------------------------------------------------------------------------
def render_session_overview(session_date, session_labels, session_df, standings_df_after, *, get_season_id, load_role_distribution):
    body_font, title_font = get_fonts()

    bg = (25, 25, 25)
    fg = (230, 230, 230)
    gold = (255, 215, 0)
    header_bg = (40, 40, 40)
    grid = (80, 80, 80)

    pad = 20
    title_h = 100
    section_gap = 26
    header_h = 54
    row_h = 44

    A_headers = [
        "Player", "W/L", "Win%", "AvgKDA", "AvgDmg", "AvgHeal", "AvgTaken",
        "SessHero", "MVP", "SVP", "Badges"
    ]

    A_rows = []
    for _, r in session_df.iterrows():
        A_rows.append([
            str(r["player"])[:22],
            r["wl_str"],
            f"{float(r['winrate']):.1f}%",
            f"{float(r['avg_kda']):.2f}",
            f"{int(r['avg_dmg']):,}",
            f"{int(r['avg_heal']):,}",
            f"{int(r['avg_taken']):,}",
            str(r.get("top_hero_sess", "—"))[:18],
            str(int(r.get("mvp", 0))),
            str(int(r.get("svp", 0))),
            str(r.get("badges", "—"))[:48],
        ])

    B_headers = ["Player", "W/L", "Win%", "Pos"]
    B_rows = []
    for _, r in standings_df_after.iterrows():
        dlt = r.get("delta", "=")
        if dlt == "=":
            pos = f"{int(r['rank'])} –"
        elif dlt == "NEW":
            pos = f"{int(r['rank'])} NEW"
        else:
            pos = f"{int(r['rank'])} {dlt}"
        B_rows.append([
            str(r["player"])[:22], r["wl_str"], f"{float(r['winrate']):.1f}%", pos
        ])

    tmp_img = Image.new("RGB", (10, 10), bg)
    td = ImageDraw.Draw(tmp_img)

    def _tw(s) -> float:
        return td.textlength(str(s), font=body_font)

    def _fit_cols(headers, rows, mins, maxs):
        cols = []
        if not rows:
            rows = [["—"] * len(headers)]
        for i, h in enumerate(headers):
            vals = [r[i] for r in rows]
            w = max([_tw(h)] + [_tw(v) for v in vals]) + 24
            cols.append(int(min(maxs[i], max(mins[i], w))))
        return cols

    A_min = [220, 90, 90, 95, 120, 120, 130, 140, 60, 60, 300]
    A_max = [360, 110, 110, 120, 160, 160, 180, 200, 80, 80, 520]
    B_min = [260, 120, 120, 140]
    B_max = [380, 160, 160, 220]

    A_col = _fit_cols(A_headers, A_rows, A_min, A_max)
    B_col = _fit_cols(B_headers, B_rows, B_min, B_max)

    width = max(sum(A_col), sum(B_col)) + pad * 2

    A_h = header_h + row_h * max(1, len(A_rows))
    B_h = header_h + row_h * max(1, len(B_rows))
    total_h = pad + title_h + pad + 28 + A_h + section_gap + 28 + B_h + pad

    img = Image.new("RGB", (int(width), int(total_h)), bg)
    d = ImageDraw.Draw(img)

    t1 = f"Session Overview — {session_date or 'Latest Session'}"
    t2 = f"{len(session_labels)} game(s)"
    d.text(((width - d.textlength(t1, font=title_font)) // 2, pad), t1, font=title_font, fill=gold)
    d.text(((width - d.textlength(t2, font=body_font)) // 2, pad + title_font.size + 12), t2, font=body_font, fill=fg)

    y = pad + title_h

    def draw_table(y0, heads, rows, cols):
        xs = [pad + sum(cols[:i]) for i in range(len(cols))]
        for i, h in enumerate(heads):
            x = xs[i]
            d.rectangle([x, y0, x + cols[i], y0 + header_h], fill=header_bg, outline=grid)
            d.text((x + 10, y0 + 14), h, font=body_font, fill=fg)

        y1 = y0 + header_h
        if not rows:
            rows = [["—"] * len(heads)]
        for r_ in rows:
            for i, c_ in enumerate(r_):
                x = xs[i]
                d.rectangle([x, y1, x + cols[i], y1 + row_h], outline=grid)
                d.text((x + 10, y1 + 10), str(c_), font=body_font, fill=fg)
            y1 += row_h
        return y1

    d.text((pad, y), "Session Records (API)", font=body_font, fill=gold)
    y += 28
    y = draw_table(y, A_headers, A_rows, A_col)

    y += section_gap
    d.text((pad, y), "Season Standings (change after session)", font=body_font, fill=gold)
    y += 28
    y_b_table_top = y
    y_b_table_end = draw_table(y, B_headers, B_rows, B_col)

    # --------------------------------------------------------------------------------------------------------
    # Role Distribution (triangle) panel — replaces Closest Rivalry (H2H)
    # --------------------------------------------------------------------------------------------------------
    try:
        b_w = int(sum(B_col))
        x0 = pad + b_w + 18
        panel_w = int(width - pad - x0)
        panel_h_max = int(y_b_table_end - y_b_table_top)

        if panel_w >= 360 and panel_h_max >= 240 and session_labels:
            season_id_raw = get_season_id()
            season_id = int(str(season_id_raw).strip().split(".", 1)[0])

            # name map from session_df
            name_map = {}
            player_uids = set()
            for _, rr in session_df.iterrows():
                try:
                    uid = int(rr.get("player_uid"))
                except Exception:
                    continue
                player_uids.add(uid)
                name_map[uid] = str(rr.get("player", uid))

            role_rows = load_role_distribution(
                season_id,
                session_labels,
                player_uids=player_uids,
            )

            d.rectangle([x0, y_b_table_top, x0 + panel_w, y_b_table_top + panel_h_max], fill=header_bg, outline=grid)

            _so_draw_role_triangle_panel(
                d,
                x0,
                y_b_table_top,
                panel_w,
                panel_h_max,
                title="Role Distribution — Session",
                role_rows=list(role_rows or []),
                player_names=name_map,
                body_font=body_font,
                fg=fg,
                gold=gold,
                grid=grid,
            )

    except Exception:
        pass

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
