"""Early-exit ledger and summaries. Never alters original match records."""
from collections import defaultdict
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


def ensure_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mr_early_exits (
            guild_id INTEGER NOT NULL,
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            player_uid INTEGER NOT NULL,
            recorded_by INTEGER NOT NULL,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, season_id, match_uid, player_uid)
        )
    """)
    conn.commit()


def find_matches(conn, match_uid, season_id=None):
    sql = """SELECT DISTINCT m.season_id, m.match_uid, m.game_label,
                     m.match_time_utc
               FROM mr_match_meta m WHERE m.match_uid=?"""
    args = [str(match_uid)]
    if season_id is not None:
        sql += " AND m.season_id=?"
        args.append(int(season_id))
    return conn.execute(sql, args).fetchall()


def match_players(conn, season_id, match_uid):
    return conn.execute("""
        SELECT player_uid, player, camp,
               CASE WHEN is_win=1 THEN 1
                    WHEN is_win=0 THEN 0 ELSE NULL END
        FROM mr_player_match
        WHERE season_id=? AND match_uid=? AND is_bot=0
        ORDER BY LOWER(player), player_uid
    """, (int(season_id), str(match_uid))).fetchall()


def get_match(conn, season_id, match_uid):
    rows = find_matches(conn, match_uid, season_id)
    if len(rows) != 1:
        return None
    players = match_players(conn, season_id, match_uid)
    return {"season_id": int(rows[0][0]), "match_uid": str(rows[0][1]),
            "game_label": str(rows[0][2]), "played_at": rows[0][3],
            "players": players}


def add_exit(conn, guild_id, season_id, match_uid, player_uid, recorded_by):
    """Returns 'saved', 'duplicate', 'not_found'; avoid trusting UI state."""
    ensure_tables(conn)
    match = get_match(conn, season_id, match_uid)
    if not match or int(player_uid) not in {int(p[0]) for p in match["players"]}:
        return "not_found"
    before = conn.total_changes
    conn.execute("""
        INSERT OR IGNORE INTO mr_early_exits
        (guild_id, season_id, match_uid, player_uid, recorded_by)
        VALUES (?, ?, ?, ?, ?)
    """, (int(guild_id), int(season_id), str(match_uid),
          int(player_uid), int(recorded_by)))
    added = conn.total_changes > before
    conn.commit()
    return "saved" if added else "duplicate"


def remove_exit(conn, guild_id, season_id, match_uid, player_uid):
    ensure_tables(conn)
    before = conn.total_changes
    conn.execute("""
        DELETE FROM mr_early_exits
        WHERE guild_id=? AND season_id=? AND match_uid=? AND player_uid=?
    """, (int(guild_id), int(season_id), str(match_uid), int(player_uid)))
    removed = conn.total_changes > before
    conn.commit()
    return bool(removed)


def list_exits(conn, guild_id, season_id=None, limit=100):
    ensure_tables(conn)
    sql = """
        SELECT e.season_id,e.match_uid,e.player_uid,e.recorded_by,e.recorded_at,
               COALESCE(m.game_label,e.match_uid)
        FROM mr_early_exits e
        LEFT JOIN mr_match_meta m ON
            m.season_id=e.season_id AND m.match_uid=e.match_uid
        WHERE e.guild_id=?
    """
    args = [int(guild_id)]
    if season_id is not None:
        sql += " AND e.season_id=?"
        args.append(int(season_id))
    sql += " ORDER BY e.recorded_at DESC,e.match_uid DESC LIMIT ?"
    args.append(int(limit))
    return conn.execute(sql,args).fetchall()


def summarize(conn, guild_id, season_id=None, player_uid=None):
    """Use imported players/results as source of truth. Unknown != loss."""
    entries = list_exits(conn, guild_id, season_id, limit=1000000)
    by_player = defaultdict(lambda: {"exits":0,"wins":0,"losses":0,"unknown":0})
    affected = defaultdict(lambda: {"games":0,"wins":0,"losses":0,"unknown":0})
    all_names = {}
    total = {"exits":0,"wins":0,"losses":0,"unknown":0}
    affected_occurrences = 0
    for sid, mid, uid, _author, _ts, _label in entries:
        if player_uid is not None and int(uid)!=int(player_uid):
            continue
        players = match_players(conn, sid, mid)
        departing = next((p for p in players if int(p[0])==int(uid)), None)
        if departing is None:
            result = "unknown"
        else:
            result = "wins" if departing[3] == 1 else "losses" if departing[3] == 0 else "unknown"
            all_names[int(uid)] = departing[1]
        for bucket in (total, by_player[int(uid)]):
            bucket["exits"]+=1
            bucket[result]+=1
        if departing is None or departing[2] is None:
            continue
        for teammate in players:
            if int(teammate[0]) == int(uid) or teammate[2] is None or teammate[2] != departing[2]:
                continue
            teammate_uid = int(teammate[0])
            all_names[teammate_uid] = teammate[1]
            affected[teammate_uid]["games"]+=1
            affected[teammate_uid][result]+=1
            affected_occurrences+=1
    total["affected_occurrences"]=affected_occurrences
    total["unique_teammates"]=len(affected)
    return {"total":total,"by_player":dict(by_player),
            "affected":dict(affected),"names":all_names}


def format_summary(data, title):
    t = data["total"]
    known = t["wins"] + t["losses"]
    rate = f"{t['wins']/known*100:.1f}%" if known else "N/A"
    lines = [f"**{title}**",f"**Early exits:** {t['exits']}  |  **Wins:** {t['wins']}  |  **Losses:** {t['losses']}  |  **Unknown:** {t['unknown']}",
             f"**W/L rate:** {rate}  |  **Teammate-game impacts:** {t['affected_occurrences']}  |  **Unique teammates affected:** {t['unique_teammates']}",
             "**Players who left:**"]
    ordered = sorted(data["by_player"].items(), key=lambda kv:(-kv[1]["exits"],kv[0]))
    for uid, d in ordered[:18]:
        lines.append(f"• {data['names'].get(uid,str(uid))}: {d['exits']} exits, {d['wins']}W / {d['losses']}L / {d['unknown']} unknown")
    if not ordered:
        lines.append("No early exits recorded.")
    lines.append("**Teammates affected (appearances, not blame):**")
    impacted = sorted(data["affected"].items(),key=lambda kv:(-kv[1]["games"],kv[0]))
    for uid,d in impacted[:18]:
        lines.append(f"• {data['names'].get(uid,str(uid))}: {d['games']} affected, {d['wins']}W / {d['losses']}L / {d['unknown']} unknown")
    if not impacted:
        lines.append("No verified teammate impacts recorded.")
    return "\n".join(lines)


def render_summary(data, title):
    """Render a complete Discord-ready report with two readable tables."""
    width, margin, row_height = 1200, 42, 57
    player_rows = sorted(
        data["by_player"].items(), key=lambda item: (-item[1]["exits"], item[0])
    )
    impact_rows = sorted(
        data["affected"].items(), key=lambda item: (-item[1]["games"], item[0])
    )
    # Show every row (instead of hiding remaining people in an image-only report).
    shown_players = player_rows or [(None, None)]
    shown_impacts = impact_rows or [(None, None)]
    top_height = 300
    section_heading = 69
    table_header = 60
    table_gap = 43
    footer_height = 28
    height = (
        top_height
        + section_heading + table_header + len(shown_players) * row_height
        + table_gap
        + section_heading + table_header + len(shown_impacts) * row_height
        + footer_height
    )
    image = Image.new("RGB", (width, height), (15, 22, 39))
    draw = ImageDraw.Draw(image)
    try:
        fonts = {
            "title": ImageFont.truetype("DejaVuSans-Bold.ttf", 40),
            "section": ImageFont.truetype("DejaVuSans-Bold.ttf", 29),
            "metric": ImageFont.truetype("DejaVuSans-Bold.ttf", 42),
            "normal": ImageFont.truetype("DejaVuSans.ttf", 23),
            "bold": ImageFont.truetype("DejaVuSans-Bold.ttf", 24),
            "small": ImageFont.truetype("DejaVuSans.ttf", 20),
        }
    except OSError:
        fonts = {key: ImageFont.load_default() for key in
                 ("title", "section", "metric", "normal", "bold", "small")}

    fg = (242, 245, 251)
    muted = (175, 188, 210)
    purple = (179, 143, 255)
    green = (99, 231, 158)
    red = (255, 126, 133)
    blue = (126, 191, 250)

    def text(value, xy, *, font="normal", fill=fg):
        draw.text(xy, str(value), font=fonts[font], fill=fill)

    def fitted(value, max_width, font="normal"):
        """Prevent usernames longer than their table cell from overlapping values."""
        value = str(value)
        if draw.textbbox((0, 0), value, font=fonts[font])[2] <= max_width:
            return value
        while value and draw.textbbox((0, 0), value + "...",
                                     font=fonts[font])[2] > max_width:
            value = value[:-1]
        return value + "..."

    def section(y, label):
        draw.rounded_rectangle(
            (margin, y, width - margin, y + 53),
            radius=11, fill=(37, 43, 73), outline=(100, 86, 159), width=2
        )
        draw.rounded_rectangle((margin, y, margin + 8, y + 53),
                               radius=4, fill=purple)
        text(label, (margin + 24, y + 9), font="section")
        return y + section_heading

    columns = [margin, 556, 752, 952, width - margin]
    def table(y, headings, rows, first_key):
        draw.rounded_rectangle((margin, y, width - margin, y + table_header),
                               radius=9, fill=(44, 49, 77))
        for i, label in enumerate(headings):
            x = columns[i] + 16 if i == 0 else columns[i] + 12
            text(label, (x, y + 16), font="bold",
                 fill=purple if i == 0 else fg)
        y += table_header
        for index, (uid, details) in enumerate(rows):
            draw.rectangle(
                (margin, y, width - margin, y + row_height),
                fill=(24, 32, 53) if index % 2 == 0 else (33, 39, 62)
            )
            if uid is None:
                text("No records yet", (margin + 17, y + 14), fill=muted)
            else:
                name = data["names"].get(uid, str(uid))
                values = [
                    fitted(name, columns[1] - columns[0] - 30, "bold"),
                    details[first_key], details["wins"], details["losses"]
                ]
                for col, value in enumerate(values):
                    fill = (green if col == 2 else red if col == 3 else fg)
                    text(value, (columns[col] + 16, y + 13),
                         font="bold", fill=fill)
            y += row_height
            draw.line((margin, y, width - margin, y), fill=(65, 71, 102), width=1)
        return y

    text(title, (margin, 30), font="title")
    text("EARLY EXIT STATISTICS  /  MATCH RESULTS & TEAMMATE EXPOSURE",
         (margin, 88), font="small", fill=muted)
    t = data["total"]
    # Only the three headline metrics requested for the Discord image.
    metrics = [
        ("EARLY EXITS", t["exits"], purple),
        ("WINS", t["wins"], green),
        ("LOSSES", t["losses"], red),
    ]
    cell_gap = 15
    cell_width = (width - 2 * margin - 2 * cell_gap) // 3
    for i, (label, value, color) in enumerate(metrics):
        x = margin + i * (cell_width + cell_gap)
        draw.rounded_rectangle((x, 130, x + cell_width, 245),
                               radius=12, fill=(36, 44, 68),
                               outline=(80, 83, 115), width=2)
        # Use smaller font for long metric labels.
        label_font = "small"
        for line_idx, line in enumerate(
            [label] if len(label) <= 14 else label.split(" ", 1)
        ):
            text(fitted(line, cell_width - 16, label_font),
                 (x + 10, 145 + line_idx * 23),
                 font=label_font, fill=muted)
        value_label = str(value)
        value_font = "metric" if len(value_label) <= 4 else "section"
        text(value_label, (x + 12, 184), font=value_font, fill=color)

    y = section(top_height, "PLAYERS WHO LEFT")
    y = table(y, ["Player", "Exits", "Wins", "Losses"],
              shown_players, "exits")
    y += table_gap
    y = section(y, "TEAMMATES AFFECTED")
    y = table(y, ["Teammate", "Affected", "Wins", "Losses"],
              shown_impacts, "games")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output
