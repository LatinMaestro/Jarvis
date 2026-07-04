import io

from PIL import Image, ImageDraw, ImageFont

from jarvis.rendering.fonts import get_fonts


TOP3_MORE_MIN_GAMES_FOR_LIFT = 3


def _top3_more_clip(s: str, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")

def _top3_more_render_image(season_id: int, top3_names: list[str], payload: dict) -> io.BytesIO:
    rows = list(payload.get("rows") or [])
    summary = dict(payload.get("summary") or {})

    scope_label = str(summary.get("scope_label", "all games"))

    W = 2500
    pad = 26
    row_h = 32
    table_rows = max(1, len(rows))
    extra_h = 330
    H = max(1100, 255 + (table_rows * row_h) + extra_h)

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)
    good = (140, 220, 140)
    bad = (235, 140, 140)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    title = f"More Selected Top-3 Exposure — Season {season_id}"
    subtitle_1 = "Selected top 3: " + ", ".join(str(x) for x in top3_names)
    subtitle_2 = f"Denominator: {scope_label}"

    draw.text((pad * 2, int(pad * 1.35)), title, font=title_font, fill=accent)
    draw.text((pad * 2, int(pad * 2.7)), subtitle_1, font=body_font, fill=muted)
    draw.text((pad * 2, int(pad * 3.65)), subtitle_2, font=body_font, fill=muted)

    left_x = pad * 2
    y = int(pad * 5.0)

    x_player = left_x
    x_top3 = left_x + 300
    x_games = left_x + 390
    x_moreg = left_x + 500
    x_morep = left_x + 640
    x_morewr = left_x + 760
    x_vsg = left_x + 890
    x_vsp = left_x + 1030
    x_vswr = left_x + 1150
    x_owr = left_x + 1280
    x_lift = left_x + 1410
    x_by1 = left_x + 1550
    x_by2p = left_x + 1670

    headers = [
        (x_player, "Player"),
        (x_top3, "Top3"),
        (x_games, "Games"),
        (x_moreg, "More Gms"),
        (x_morep, "More %"),
        (x_morewr, "More WR"),
        (x_vsg, "Vs More Gms"),
        (x_vsp, "Vs More %"),
        (x_vswr, "Vs More WR"),
        (x_owr, "Overall WR"),
        (x_lift, "WR Lift"),
        (x_by1, "More by 1"),
        (x_by2p, "More by 2+"),
    ]
    for x, label in headers:
        draw.text((x, y), label, font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for r in rows:
        top3_txt = "Yes" if r["is_top3"] else "No"
        more_wr_txt = "—" if r["more_wr"] is None else f"{r['more_wr']:.1f}%"
        vs_wr_txt = "—" if r["vs_more_wr"] is None else f"{r['vs_more_wr']:.1f}%"
        lift_txt = "—" if r["wr_lift"] is None else f"{r['wr_lift']:+.1f}%"
        lift_fill = muted if r["wr_lift"] is None else (good if float(r["wr_lift"]) >= 0 else bad)
        name_fill = accent if r["is_top3"] else text

        draw.text((x_player, y), _top3_more_clip(r["player"], 18), font=body_font, fill=name_fill)
        draw.text((x_top3, y), top3_txt, font=body_font, fill=name_fill if r["is_top3"] else text)
        draw.text((x_games, y), str(r["games"]), font=body_font, fill=text)
        draw.text((x_moreg, y), str(r["more_games"]), font=body_font, fill=text)
        draw.text((x_morep, y), f"{r['more_pct']:.1f}%", font=body_font, fill=text)
        draw.text((x_morewr, y), more_wr_txt, font=body_font, fill=text)
        draw.text((x_vsg, y), str(r["vs_more_games"]), font=body_font, fill=text)
        draw.text((x_vsp, y), f"{r['vs_more_pct']:.1f}%", font=body_font, fill=text)
        draw.text((x_vswr, y), vs_wr_txt, font=body_font, fill=text)
        draw.text((x_owr, y), f"{r['overall_wr']:.1f}%", font=body_font, fill=text)
        draw.text((x_lift, y), lift_txt, font=body_font, fill=lift_fill)
        draw.text((x_by1, y), str(r["more_by1"]), font=body_font, fill=text)
        draw.text((x_by2p, y), str(r["more_by2plus"]), font=body_font, fill=text)
        y += row_h

    y += 8
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 18

    total_matches = int(summary.get("total_matches", 0))
    qualifying_matches = int(summary.get("qualifying_matches", 0))
    equal_matches = int(summary.get("equal_matches", 0))
    no_selected_matches = int(summary.get("no_selected_matches", 0))
    balanced_selected_matches = int(summary.get("balanced_selected_matches", 0))
    diff1_matches = int(summary.get("diff1_matches", 0))
    diff2plus_matches = int(summary.get("diff2plus_matches", 0))

    line_1 = (
        f"Match summary: total {total_matches}  •  qualifying imbalance {qualifying_matches}  •  equal split {equal_matches}"
    )
    line_2 = (
        f"Qualifying split sizes: diff 1 = {diff1_matches}  •  diff 2+ = {diff2plus_matches}  •  no selected online = {no_selected_matches}  •  balanced selected = {balanced_selected_matches}"
    )

    draw.text((left_x, y), line_1, font=body_font, fill=muted)
    y += 34
    draw.text((left_x, y), line_2, font=body_font, fill=muted)
    y += 42

    exposure_rows = list(summary.get("biggest_exposure") or [])
    lift_rows = list(summary.get("biggest_lift") or [])
    faced_rows = list(summary.get("most_faced") or [])

    col1_x = left_x
    col2_x = left_x + 820
    col3_x = left_x + 1550

    draw.text((col1_x, y), "Top non-top3 by More %", font=body_font, fill=muted)
    draw.text((col2_x, y), f"Top non-top3 by WR lift (min {TOP3_MORE_MIN_GAMES_FOR_LIFT} More Gms)", font=body_font, fill=muted)
    draw.text((col3_x, y), "Top non-top3 by facing advantage teams", font=body_font, fill=muted)
    y += 34

    max_summary_rows = max(len(exposure_rows), len(lift_rows), len(faced_rows), 1)
    for i in range(max_summary_rows):
        if i < len(exposure_rows):
            r = exposure_rows[i]
            txt = f"#{i+1} {_top3_more_clip(r['player'], 16)} — {r['more_games']} gms ({r['more_pct']:.1f}%)"
            draw.text((col1_x, y), txt, font=body_font, fill=text)

        if i < len(lift_rows):
            r = lift_rows[i]
            txt = f"#{i+1} {_top3_more_clip(r['player'], 16)} — {r['wr_lift']:+.1f}% lift"
            draw.text((col2_x, y), txt, font=body_font, fill=(good if float(r["wr_lift"]) >= 0 else bad))

        if i < len(faced_rows):
            r = faced_rows[i]
            faced_wr_txt = "—" if r["vs_more_wr"] is None else f"{r['vs_more_wr']:.1f}%"
            txt = f"#{i+1} {_top3_more_clip(r['player'], 16)} — {r['vs_more_games']} gms ({r['vs_more_pct']:.1f}%) WR {faced_wr_txt}"
            draw.text((col3_x, y), txt, font=body_font, fill=text)

        y += row_h

    footer = (
        "'More Gms' = games where a player's team had more of the selected top 3 than the other team. "
        "Scope changes only the denominator and Overall WR."
    )
    draw.text((left_x, H - pad - 58), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
