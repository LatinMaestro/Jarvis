import io
import re
from collections import defaultdict

from PIL import Image, ImageDraw

from jarvis.rendering.fonts import get_fonts


def calculate_low_team_results(rows) -> list[tuple]:
    def canonical_name(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (name or "").lower())

    games = defaultdict(lambda: {"1": set(), "0": set()})
    display_names = {}
    for game_label, player, win in rows:
        if game_label is None or player is None:
            continue
        key = canonical_name(str(player))
        if not key:
            continue
        games[str(game_label)][str(int(win or 0))].add(key)
        display_names[key] = str(player)

    low_team_counts = defaultdict(int)
    uneven_game_counts = defaultdict(int)
    low_team_win_counts = defaultdict(int)
    on_more_counts = defaultdict(int)
    on_more_loss_counts = defaultdict(int)

    for teams in games.values():
        win_team = teams["1"]
        loss_team = teams["0"]
        if not win_team or not loss_team or len(win_team) == len(loss_team):
            continue

        for player in win_team | loss_team:
            uneven_game_counts[player] += 1

        if len(win_team) < len(loss_team):
            smaller = win_team
            smaller_won = True
            larger = loss_team
            larger_lost = True
        else:
            smaller = loss_team
            smaller_won = False
            larger = win_team
            larger_lost = False

        for player in smaller:
            low_team_counts[player] += 1
            if smaller_won:
                low_team_win_counts[player] += 1
        for player in larger:
            on_more_counts[player] += 1
            if larger_lost:
                on_more_loss_counts[player] += 1

    results = []
    for player in uneven_game_counts:
        name = display_names.get(player, player)
        low = int(low_team_counts.get(player, 0))
        uneven = int(uneven_game_counts.get(player, 0))
        low_wins = int(low_team_win_counts.get(player, 0))
        percent_on_less = (low / uneven * 100.0) if uneven > 0 else 0.0
        win_percent_on_less = (low_wins / low * 100.0) if low > 0 else 0.0
        more_count = int(on_more_counts.get(player, 0))
        more_losses = int(on_more_loss_counts.get(player, 0))
        loss_percent_on_more = (
            more_losses / more_count * 100.0 if more_count > 0 else None
        )
        results.append(
            (
                name,
                low,
                uneven,
                percent_on_less,
                win_percent_on_less,
                loss_percent_on_more,
            )
        )

    results.sort(key=lambda item: (item[3], item[2], item[0].lower()), reverse=True)
    return results


def render_low_team_image(results, title="Low-Team % (Uneven Games Only)"):
    body_font, title_font = get_fonts()
    background = (25, 25, 25)
    foreground = (230, 230, 230)
    gold = (255, 215, 0)
    header_background = (40, 40, 40)
    grid = (80, 80, 80)
    missing = "\u00e2\u20ac\u201d"
    headers = [
        "Player",
        "On Less",
        "Uneven",
        "% on Less",
        "Win% on Less",
        "Loss% on More",
    ]

    table_rows = []
    for item in results or []:
        name = item[0] if len(item) > 0 else missing
        on_less = item[1] if len(item) > 1 else 0
        uneven = item[2] if len(item) > 2 else 0
        percent = item[3] if len(item) > 3 else 0.0
        win_percent = item[4] if len(item) > 4 else 0.0
        loss_more = item[5] if len(item) > 5 else None
        table_rows.append(
            [
                str(name),
                str(int(on_less)),
                str(int(uneven)),
                f"{float(percent):.1f}%",
                f"{float(win_percent):.1f}%",
                missing if loss_more is None else f"{float(loss_more):.1f}%",
            ]
        )
    if not table_rows:
        table_rows = [[missing, "0", "0", "0.0%", "0.0%", missing]]

    padding = 20
    title_height = 92
    header_height = 54
    row_height = 44
    temporary = Image.new("RGB", (10, 10), background)
    temporary_draw = ImageDraw.Draw(temporary)

    def text_width(text) -> float:
        return temporary_draw.textlength(str(text), font=body_font)

    minimum_widths = [260, 120, 120, 160, 180, 200]
    maximum_widths = [520, 180, 180, 220, 240, 260]
    column_widths = []
    for index, header in enumerate(headers):
        width = max(
            text_width(header),
            max(text_width(row[index]) for row in table_rows),
        ) + 26
        column_widths.append(
            int(min(maximum_widths[index], max(minimum_widths[index], width)))
        )

    width = sum(column_widths) + padding * 2
    height = (
        padding
        + title_height
        + 18
        + header_height
        + row_height * len(table_rows)
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
    for row in table_rows:
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
