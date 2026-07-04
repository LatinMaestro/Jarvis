import io

from PIL import Image, ImageDraw, ImageFont

from jarvis.formatting import format_duration as _fmt_time
from jarvis.rendering.fonts import get_fonts



def _render_session_pairs_underdog_image_api(session_date, session_labels,
                                             matrix_df, name_by_uid,
                                             order_uids, uneven, underdog_wins,
                                             low_team_rows, bans_list,
                                             picks_list):
    body_font, title_font = get_fonts()
    bg = (25, 25, 25)
    fg = (230, 230, 230)
    gold = (255, 215, 0)
    grid = (80, 80, 80)
    pad = 20
    title_h = 100
    row_h = 40
    gap = 26
    header_h = 54
    header_bg = (40, 40, 40)

    bold_font = body_font

    def _len(s):
        try:
            return bold_font.getlength(str(s))
        except Exception:
            return float(len(str(s)) * 10)

    if order_uids:
        col_headers = [name_by_uid.get(uid, str(uid)) for uid in order_uids]
        col_widths = []
        for col_idx, uid in enumerate(order_uids):
            header_len = _len(col_headers[col_idx])
            cell_len = 0.0
            for row_uid in order_uids:
                cell_len = max(cell_len, _len(str(matrix_df.loc[row_uid,
                                                                uid])))
            col_widths.append(int(max(header_len, cell_len) + 30))
        row_label_width = int(
            max(_len(name_by_uid.get(uid, str(uid)))
                for uid in order_uids) + 30)
    else:
        col_headers, col_widths, row_label_width = [], [], 240

    matrix_width = row_label_width + sum(col_widths) + pad * 2
    matrix_height = (len(order_uids) + 2) * row_h if order_uids else (3 *
                                                                      row_h)

    C_headers = ["Player", "On Less", "Uneven", "% on Less", "Win% on Less"]
    C_cols = [320, 140, 140, 160, 180]
    C_h = header_h + row_h * max(1, len(low_team_rows))

    # Estimate wrapped bans/picks height BEFORE creating the image
    # (rebuild the same strings and wrap based on a conservative width)
    approx_width = max(matrix_width, sum(C_cols) + pad * 2)
    tmp_img2 = Image.new("RGB", (10, 10), bg)
    td2 = ImageDraw.Draw(tmp_img2)

    def _wrap_tokens_measure(text: str, max_w: int) -> int:
        if not text or text.strip() == "":
            return 1
        tokens = text.split(" • ")
        lines = 0
        cur = ""
        for t in tokens:
            cand = t if not cur else f"{cur} • {t}"
            if td2.textlength(cand, font=body_font) <= max_w:
                cur = cand
            else:
                lines += 1 if cur else 0
                cur = t
        lines += 1 if cur else 1
        return max(1, lines)

    line_h = int(body_font.size + 6)
    max_text_w = int(approx_width - pad * 2)

    bans_txt = " • ".join([f"{nm}×{ct}"
                           for nm, ct in bans_list]) if bans_list else "—"
    picks_txt = " • ".join(
        [f"{nm}({_fmt_time(sec)})"
         for nm, sec in picks_list]) if picks_list else "—"

    bans_lines_n = _wrap_tokens_measure(bans_txt, max_text_w)
    picks_lines_n = _wrap_tokens_measure(picks_txt, max_text_w)

    bans_h = 30 + (bans_lines_n * line_h) + 18  # label gap + lines + spacing
    picks_h = 30 + (picks_lines_n * line_h) + 18

    width = max(matrix_width, sum(C_cols) + pad * 2)
    total_h = pad + title_h + pad + matrix_height + gap + 34 + bans_h + 18 + picks_h + gap + 40 + gap + C_h + pad

    img = Image.new("RGB", (int(width), int(total_h)), bg)
    d = ImageDraw.Draw(img)

    t1 = f"Session Matrix + Meta — {session_date or 'Latest Session'}"
    t2 = f"{len(session_labels)} game(s)"
    d.text(((width - d.textlength(t1, font=title_font)) // 2, pad),
           t1,
           font=title_font,
           fill=gold)
    d.text(((width - d.textlength(t2, font=title_font)) // 2,
            pad + title_font.size + 6),
           t2,
           font=title_font,
           fill=gold)

    y = pad + title_h

    d.text((pad, y - 28),
           "Teammate Matrix (Same-Team/Overlap + %) — Session",
           font=body_font,
           fill=gold)

    if not order_uids:
        d.text((pad, y + 10), "—", font=body_font, fill=fg)
        y = y + (2 * row_h)
    else:
        x_offsets = [
            row_label_width + pad + sum(col_widths[:i])
            for i in range(len(order_uids))
        ]

        for idx, header in enumerate(col_headers):
            d.text((x_offsets[idx], y),
                   header[:18],
                   font=bold_font,
                   fill=(255, 255, 255))

        for r_idx, r_uid in enumerate(order_uids):
            y_row = y + (r_idx + 1) * row_h
            d.text((pad, y_row),
                   name_by_uid.get(r_uid, str(r_uid))[:18],
                   font=bold_font,
                   fill=(255, 255, 255))
            for c_idx, c_uid in enumerate(order_uids):
                x_cell = x_offsets[c_idx]
                val = str(matrix_df.loc[r_uid, c_uid])
                d.rectangle([
                    x_cell - 6, y_row - 4, x_cell + col_widths[c_idx] - 10,
                    y_row + row_h - 10
                ],
                            outline=grid)
                d.text((x_cell, y_row),
                       val,
                       font=bold_font,
                       fill=(255, 255, 255))

        y = y + (len(order_uids) + 1) * row_h

    # Bans / Picks (WRAPPED)
    y += gap

    max_text_w = int(width - pad * 2)
    line_h = int(body_font.size + 6)

    def _wrap_tokens(text: str, max_w: int) -> list[str]:
        """
        Wrap on the ' • ' token so we keep the same list styling.
        """
        if not text or text.strip() == "":
            return ["—"]

        tokens = text.split(" • ")
        lines = []
        cur = ""

        for t in tokens:
            cand = t if not cur else f"{cur} • {t}"
            if d.textlength(cand, font=body_font) <= max_w:
                cur = cand
            else:
                if cur:
                    lines.append(cur)
                cur = t

        if cur:
            lines.append(cur)

        return lines if lines else ["—"]

    d.text((pad, y), "Top Bans (session)", font=body_font, fill=gold)
    y += 30
    bans_txt = " • ".join([f"{nm}×{ct}"
                           for nm, ct in bans_list]) if bans_list else "—"
    bans_lines = _wrap_tokens(bans_txt, max_text_w)
    for ln in bans_lines:
        d.text((pad, y), ln, font=body_font, fill=fg)
        y += line_h
    y += 18

    d.text((pad, y),
           "Top Picks (by total time, humans)",
           font=body_font,
           fill=gold)
    y += 30
    picks_txt = " • ".join(
        [f"{nm}({_fmt_time(sec)})"
         for nm, sec in picks_list]) if picks_list else "—"
    picks_lines = _wrap_tokens(picks_txt, max_text_w)
    for ln in picks_lines:
        d.text((pad, y), ln, font=body_font, fill=fg)
        y += line_h
    y += 18

    # underdog summary
    y += gap
    summary = f"Uneven games: {uneven}   •   Smaller team won: {underdog_wins}"
    d.text((pad, y), summary, font=body_font, fill=gold)
    y += 36

    d.text((pad, y), "Session Low-Team (condensed)", font=body_font, fill=gold)
    y += 28

    def draw_table(y0, heads, rows, cols):
        xs = [pad + sum(cols[:i]) for i in range(len(cols))]
        for i, h in enumerate(heads):
            x = xs[i]
            d.rectangle([x, y0, x + cols[i], y0 + header_h],
                        fill=header_bg,
                        outline=grid)
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

    _ = draw_table(y, C_headers, low_team_rows, C_cols)

    buf = io.BytesIO()
    img = img.convert("RGB")
    img.save(buf, "PNG")
    buf.seek(0)
    return buf
