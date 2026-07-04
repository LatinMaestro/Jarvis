import io

from PIL import Image, ImageDraw, ImageFont

from jarvis.rendering.fonts import get_fonts


def _ss_clip(text: str, length: int) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= length else (text[: max(0, length - 1)] + "…")


def _rd_role_color(role_label: str):
    # Subtle per-role colours (keeps Season Story palette feel)
    if role_label == "Vanguard":
        return (90, 170, 255)
    if role_label == "Duelist":
        return (255, 110, 110)
    if role_label == "Strategist":
        return (120, 230, 150)
    return (255, 215, 0)

def _rd_text_w(draw: "ImageDraw.ImageDraw", s: str, font: "ImageFont.ImageFont") -> float:
    try:
        return float(draw.textlength(s, font=font))
    except Exception:
        return float(len(s) * 9)

def _rd_line_h(font: "ImageFont.ImageFont") -> int:
    try:
        b = font.getbbox("Ag")
        return int((b[3] - b[1]) + 6)
    except Exception:
        return 26

def _rd_draw_rotated_text(base_img: Image.Image,
                          text: str,
                          font: "ImageFont.ImageFont",
                          fill,
                          x: int,
                          y: int,
                          angle: float = -45.0):
    if not text:
        return
    # create a tight RGBA label image, rotate, then paste using alpha mask
    try:
        tmp = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
        dtmp = ImageDraw.Draw(tmp)
        bbox = dtmp.textbbox((0, 0), text, font=font)
        w = max(1, int(bbox[2] - bbox[0] + 2))
        h = max(1, int(bbox[3] - bbox[1] + 2))

        label = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dl = ImageDraw.Draw(label)
        dl.text((0, 0), text, font=font, fill=fill)

        rot = label.rotate(angle, expand=True, resample=Image.BICUBIC)
        base_img.paste(rot, (int(x), int(y)), rot)
    except Exception:
        # fallback (non-rotated) if anything goes wrong
        try:
            d = ImageDraw.Draw(base_img)
            d.text((x, y), text, font=font, fill=fill)
        except Exception:
            pass

def _rd_render_role_bar_chart(*,
                             season_id: int,
                             role_label: str,
                             role_key: str,   # "v" | "d" | "s"
                             role_rows: list[dict],
                             player_names: dict[int, str]) -> io.BytesIO:
    # --- canvas / palette (match Season Story vibe) ---
    W, H = 1850, 900
    pad = 26

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    # --- dynamic font sizing based on player count ---
    n = len(role_rows)
    if n <= 14:
        body_pt, title_pt, label_pt = 20, 34, 16
    elif n <= 22:
        body_pt, title_pt, label_pt = 18, 32, 14
    else:
        body_pt, title_pt, label_pt = 16, 30, 12

    try:
        body_font, title_font = get_fonts(body_pt=body_pt, title_pt=title_pt)
        label_font, _ = get_fonts(body_pt=label_pt, title_pt=label_pt)
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()
        label_font = ImageFont.load_default()

    LH = _rd_line_h(body_font)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # card background
    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=24, fill=card, outline=line, width=2)

    # title
    title = f"Role Distribution — {role_label} (Season {season_id})"
    draw.text((pad * 2, pad * 2), title, font=title_font, fill=accent)

    # subtitle
    sub = "Y-axis: % of time played (normalised across Vanguard/Duelist/Strategist per player)"
    draw.text((pad * 2, pad * 2 + _rd_line_h(title_font)), sub, font=body_font, fill=muted)

    # plot area
    top_y = pad * 2 + _rd_line_h(title_font) + LH + 28
    left_x = pad * 2 + 70
    right_x = W - pad * 2
    bottom_y = H - pad * 2 - 190  # reserve for rotated labels

    plot_w = max(10, right_x - left_x)
    plot_h = max(10, bottom_y - top_y)

    # axes
    draw.line([(left_x, top_y), (left_x, bottom_y)], fill=muted, width=3)
    draw.line([(left_x, bottom_y), (right_x, bottom_y)], fill=muted, width=3)

    # y grid + ticks
    ticks = [0, 20, 40, 60, 80, 100]
    for t in ticks:
        yy = bottom_y - (t / 100.0) * plot_h
        draw.line([(left_x, yy), (right_x, yy)], fill=line, width=1)
        lab = f"{t}%"
        tw = _rd_text_w(draw, lab, body_font)
        draw.text((left_x - tw - 12, yy - (LH / 2)), lab, font=body_font, fill=muted)

    if n <= 0:
        draw.text((left_x + 20, top_y + 20), "No role distribution data available yet.", font=body_font, fill=text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    # x layout
    space = plot_w / float(n)
    bar_w = int(max(10, min(64, space * 0.62)))
    bar_fill = _rd_role_color(role_label)

    # data in consistent order (role_rows already sorted by total_seconds desc)
    names = []
    pcts = []
    for r in role_rows:
        uid = int(r.get("player_uid", 0))
        nm = _ss_clip(player_names.get(uid, f"UID_{uid}"), 14)
        frac = float(r.get(role_key, 0.0) or 0.0)
        pct = max(0.0, min(100.0, frac * 100.0))
        names.append(nm)
        pcts.append(pct)

    # draw bars
    for i, (nm, pct) in enumerate(zip(names, pcts)):
        cx = left_x + (i + 0.5) * space
        x0 = int(cx - bar_w / 2)
        x1 = int(cx + bar_w / 2)

        h = (pct / 100.0) * plot_h
        y1 = bottom_y
        y0 = int(bottom_y - h)

        # bar
        draw.rectangle([x0, y0, x1, y1], fill=bar_fill, outline=line, width=2)

        # percent label
        p_lab = f"{pct:.1f}%" if n <= 18 else f"{pct:.0f}%"
        tw = _rd_text_w(draw, p_lab, label_font)
        draw.text((int(cx - tw / 2), max(top_y, y0 - LH)), p_lab, font=label_font, fill=text)

        # rotated name label
        # place roughly below x-axis; angle helps when many players
        _rd_draw_rotated_text(
            base_img=img,
            text=nm,
            font=label_font,
            fill=muted,
            x=int(cx - 10),
            y=int(bottom_y + 18),
            angle=-45.0
        )

    # footer note
    foot = "Note: Percentages use the same Season Story role-share logic (mr_hero_segments seconds; humans only)."
    draw.text((pad * 2, H - pad * 2 - 40), _ss_clip(foot, 120), font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
