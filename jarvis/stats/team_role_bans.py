"""Confirmed teammate role-ban matrix reporting."""

from __future__ import annotations

import io
from collections import defaultdict

from PIL import Image, ImageDraw

from jarvis.rendering.fonts import get_fonts


ROLES = ("Vanguard", "Duelist", "Strategist")
ROLE_SHORT = {"Vanguard": "V", "Duelist": "D", "Strategist": "S"}


def build_teammate_role_ban_matrix(history: object, player_names: dict[str, str]) -> dict:
    """Build ordered receiver-by-teammate counts from confirmed rolls only."""
    rolls = history.get("rolls", []) if isinstance(history, dict) else []
    counts = defaultdict(lambda: defaultdict(int))
    seen_players = set(player_names)

    for roll in rolls:
        if not isinstance(roll, dict) or not roll.get("confirmed_match_uid"):
            continue
        restrictions = roll.get("restricted_roles") or {}
        for team in (roll.get("team_a", []), roll.get("team_b", [])):
            team = [str(player) for player in team]
            seen_players.update(team)
            for receiver in team:
                for teammate in team:
                    if receiver == teammate:
                        continue
                    role = str(restrictions.get(teammate) or "")
                    if role in ROLES:
                        counts[(receiver, teammate)][role] += 1

    players = sorted(
        seen_players,
        key=lambda player: str(player_names.get(player, player)).lower(),
    )
    cells = {}
    for receiver in players:
        for teammate in players:
            if receiver == teammate:
                continue
            cells[(receiver, teammate)] = {
                role: int(counts[(receiver, teammate)].get(role, 0))
                for role in ROLES
            }
    return {
        "players": players,
        "player_names": {
            player: str(player_names.get(player, player)) for player in players
        },
        "cells": cells,
        "confirmed_rolls": sum(
            1 for roll in rolls
            if isinstance(roll, dict) and roll.get("confirmed_match_uid")
        ),
    }


def render_teammate_role_ban_matrix(report: dict, season_id: int) -> io.BytesIO:
    """Render a readable dark-theme ordered teammate role-ban matrix."""
    players = list(report.get("players", []))
    names = dict(report.get("player_names", {}))
    cells = dict(report.get("cells", {}))

    cell_w = 150
    row_h = 58
    label_w = 220
    top_h = 180
    right_pad = 30
    bottom_pad = 35
    width = label_w + (cell_w * max(1, len(players))) + right_pad
    height = top_h + (row_h * max(1, len(players))) + bottom_pad

    bg = (24, 24, 26)
    panel = (38, 38, 42)
    grid = (85, 85, 92)
    text = (235, 235, 238)
    muted = (180, 180, 188)
    gold = (255, 215, 0)

    body_font, title_font = get_fonts(body_pt=20, title_pt=30)
    small_font, _ = get_fonts(body_pt=16, title_pt=24)
    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)

    draw.text((20, 18), f"Teammate Role-Ban Matrix - Season {int(season_id)}", font=title_font, fill=gold)
    draw.text(
        (20, 60),
        "Row player received the column teammate with these bans: V Vanguard, D Duelist, S Strategist",
        font=small_font,
        fill=text,
    )
    draw.text(
        (20, 90),
        f"Confirmed uploaded games only: {int(report.get('confirmed_rolls', 0))}",
        font=small_font,
        fill=muted,
    )
    draw.text((20, 125), "Receiver / teammate", font=small_font, fill=muted)

    for column, player in enumerate(players):
        x = label_w + column * cell_w
        draw.rectangle((x, 120, x + cell_w, top_h), fill=panel, outline=grid)
        label = names.get(player, player)
        if len(label) > 17:
            label = label[:16] + "..."
        draw.text((x + 8, 140), label, font=small_font, fill=text)

    for row, receiver in enumerate(players):
        y = top_h + row * row_h
        draw.rectangle((0, y, label_w, y + row_h), fill=panel, outline=grid)
        label = names.get(receiver, receiver)
        if len(label) > 21:
            label = label[:20] + "..."
        draw.text((14, y + 17), label, font=small_font, fill=text)

        for column, teammate in enumerate(players):
            x = label_w + column * cell_w
            fill = (46, 46, 50) if receiver == teammate else bg
            draw.rectangle((x, y, x + cell_w, y + row_h), fill=fill, outline=grid)
            if receiver == teammate:
                draw.text((x + cell_w // 2 - 5, y + 17), "-", font=body_font, fill=muted)
                continue
            values = cells.get((receiver, teammate), {})
            value = " ".join(
                f"{ROLE_SHORT[role]}{int(values.get(role, 0))}"
                for role in ROLES
            )
            draw.text((x + 12, y + 17), value, font=small_font, fill=text)

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output
