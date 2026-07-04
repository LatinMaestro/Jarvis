import io

import pandas
from PIL import Image, ImageDraw

from jarvis.rendering.fonts import get_fonts


def eligible_exact_2v2_labels(cursor, season_id: int) -> list[str]:
    try:
        cursor.execute(
            """
            WITH human_by_camp AS (
                SELECT season_id, game_label, match_uid, camp, COUNT(*) AS n
                FROM mr_player_match
                WHERE season_id=?
                  AND COALESCE(is_bot,0)=0
                  AND camp IS NOT NULL
                GROUP BY season_id, game_label, match_uid, camp
            ),
            per_game AS (
                SELECT season_id, game_label, match_uid,
                       SUM(n) AS human_ct,
                       COUNT(*) AS human_camp_ct,
                       MIN(n) AS min_humans_same_camp,
                       MAX(n) AS max_humans_same_camp
                FROM human_by_camp
                GROUP BY season_id, game_label, match_uid
            )
            SELECT game_label
            FROM per_game
            WHERE human_ct=4
              AND human_camp_ct=2
              AND min_humans_same_camp=2
              AND max_humans_same_camp=2
            ORDER BY game_label ASC
            """,
            (int(season_id),),
        )
        return [
            str(row[0])
            for row in (cursor.fetchall() or [])
            if row and row[0] is not None
        ]
    except Exception:
        return []


def eligible_min_4v4_labels(cursor, season_id: int) -> list[str]:
    try:
        cursor.execute(
            """
            WITH human_by_camp AS (
                SELECT season_id, game_label, match_uid, camp, COUNT(*) AS n
                FROM mr_player_match
                WHERE season_id=?
                  AND COALESCE(is_bot,0)=0
                  AND camp IS NOT NULL
                GROUP BY season_id, game_label, match_uid, camp
            ),
            per_game AS (
                SELECT season_id, game_label, match_uid,
                       SUM(n) AS human_ct,
                       COUNT(*) AS human_camp_ct,
                       MIN(n) AS min_humans_same_camp
                FROM human_by_camp
                GROUP BY season_id, game_label, match_uid
            )
            SELECT game_label
            FROM per_game
            WHERE human_ct>=8
              AND human_camp_ct=2
              AND min_humans_same_camp>=4
            ORDER BY game_label ASC
            """,
            (int(season_id),),
        )
        return [
            str(row[0])
            for row in (cursor.fetchall() or [])
            if row and row[0] is not None
        ]
    except Exception:
        return []


def aggregate_records(cursor, season_id: int, labels: list[str]) -> pandas.DataFrame:
    columns = [
        "player_uid",
        "player",
        "games",
        "wins",
        "losses",
        "wl_str",
        "winrate",
    ]
    if not labels:
        return pandas.DataFrame(columns=columns)

    qmarks = ",".join("?" for _ in labels)
    cursor.execute(
        f"""
        SELECT pm.player_uid,
               MAX(pm.player) AS player,
               SUM(CASE WHEN pm.is_win=1 THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN pm.is_win=0 THEN 1 ELSE 0 END) AS losses
        FROM mr_player_match pm
        WHERE pm.season_id=?
          AND COALESCE(pm.is_bot,0)=0
          AND pm.game_label IN ({qmarks})
        GROUP BY pm.player_uid
        """,
        (int(season_id), *labels),
    )

    data = []
    for uid, player, wins, losses in cursor.fetchall() or []:
        wins = int(wins or 0)
        losses = int(losses or 0)
        games = wins + losses
        if games <= 0:
            continue
        data.append(
            {
                "player_uid": int(uid),
                "player": str(player),
                "games": games,
                "wins": wins,
                "losses": losses,
                "wl_str": f"{wins}/{losses}",
                "winrate": round((wins / games) * 100.0, 1),
            }
        )

    frame = pandas.DataFrame(data)
    if frame.empty:
        return frame
    return frame.sort_values(
        by=["winrate", "wins", "games"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def render_records_image(results, title="2v2 (Humans) Records"):
    body_font, title_font = get_fonts()
    background = (25, 25, 25)
    foreground = (230, 230, 230)
    gold = (255, 215, 0)
    header_background = (40, 40, 40)
    grid = (80, 80, 80)
    headers = ["Player", "Games", "W", "L", "W/L", "Win%"]

    rows = []
    for item in results or []:
        name = item[0] if len(item) > 0 else "\u00e2\u20ac\u201d"
        games = int(item[1] if len(item) > 1 else 0)
        wins = int(item[2] if len(item) > 2 else 0)
        losses = int(item[3] if len(item) > 3 else 0)
        winrate = float(item[4] if len(item) > 4 else 0.0)
        rows.append(
            [
                str(name),
                str(games),
                str(wins),
                str(losses),
                f"{wins}/{losses}",
                f"{winrate:.1f}%",
            ]
        )
    if not rows:
        rows = [["\u00e2\u20ac\u201d", "0", "0", "0", "0/0", "0.0%"]]

    padding = 20
    title_height = 92
    header_height = 54
    row_height = 44
    temporary = Image.new("RGB", (10, 10), background)
    temporary_draw = ImageDraw.Draw(temporary)

    def text_width(text) -> float:
        return temporary_draw.textlength(str(text), font=body_font)

    minimum_widths = [280, 120, 90, 90, 130, 140]
    maximum_widths = [560, 160, 110, 110, 160, 180]
    column_widths = []
    for index, header in enumerate(headers):
        width = max(text_width(header), max(text_width(row[index]) for row in rows)) + 26
        column_widths.append(
            int(min(maximum_widths[index], max(minimum_widths[index], width)))
        )

    width = sum(column_widths) + padding * 2
    height = (
        padding
        + title_height
        + 18
        + header_height
        + row_height * len(rows)
        + padding
    )
    image = Image.new("RGB", (int(width), int(height)), background)
    draw = ImageDraw.Draw(image)
    draw.text(
        ((width - draw.textlength(title, font=title_font)) // 2, padding),
        title,
        font=title_font,
        fill=gold,
    )

    y = padding + title_height
    x = padding
    for index, header in enumerate(headers):
        draw.rectangle(
            [x, y, x + column_widths[index], y + header_height],
            fill=header_background,
            outline=grid,
        )
        draw.text((x + 10, y + 14), header, font=body_font, fill=foreground)
        x += column_widths[index]

    y += header_height
    for row in rows:
        x = padding
        for index, cell in enumerate(row):
            draw.rectangle(
                [x, y, x + column_widths[index], y + row_height],
                outline=grid,
            )
            draw.text((x + 10, y + 10), str(cell), font=body_font, fill=foreground)
            x += column_widths[index]
        y += row_height

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
