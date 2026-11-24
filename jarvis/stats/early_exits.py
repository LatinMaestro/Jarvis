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
    """PIL-only scoreboard graphic; does not require optional chart packages."""
    width, height = 1050, 700
    img = Image.new("RGB",(width,height),(17,26,40))
    draw = ImageDraw.Draw(img)
    try:
        heading = ImageFont.truetype("DejaVuSans-Bold.ttf",36)
        medium = ImageFont.truetype("DejaVuSans-Bold.ttf",24)
        normal = ImageFont.truetype("DejaVuSans.ttf",21)
    except OSError:
        heading = medium = normal = ImageFont.load_default()
    fg=(242,246,252); subdued=(176,194,216)
    draw.text((42,32),title,fill=fg,font=heading)
    t=data["total"]
    for i,(label,value) in enumerate([("EARLY EXITS",t["exits"]),("WINS",t["wins"]),("LOSSES",t["losses"])]):
        x=42+i*340
        draw.rounded_rectangle((x,100,x+318,195),radius=14,fill=(34,49,72))
        draw.text((x+19,112),label,font=normal,fill=subdued)
        draw.text((x+19,142),str(value),font=heading,fill=fg)
    known=t["wins"]+t["losses"]
    draw.text((42,230),f"Results after early exit  |  Win rate: {t['wins']/known*100:.1f}%" if known else "Results after early exit  |  Win rate: N/A",font=medium,fill=fg)
    draw.rounded_rectangle((42,272,1008,304),radius=10,fill=(89,102,124))
    if known:
        win_width=round(966*t["wins"]/known)
        if win_width:
            draw.rounded_rectangle((42,272,42+win_width,304),radius=8,fill=(43,172,122))
        if known-t["wins"]:
            draw.rectangle((42+win_width,272,1008,304),fill=(211,85,90))
    draw.text((42,320),f"{t['wins']} wins    {t['losses']} losses    {t['unknown']} unknown",font=normal,fill=subdued)
    draw.text((42,375),"TEAMMATES AFFECTED",font=medium,fill=fg)
    rows=sorted(data["affected"].items(),key=lambda kv:(-kv[1]["games"],kv[0]))[:6]
    max_games=max([r[1]["games"] for r in rows] or [1])
    for index,(uid,stats) in enumerate(rows):
        y=422+index*43
        name=str(data["names"].get(uid,uid))[:22]
        draw.text((43,y),name,font=normal,fill=fg)
        draw.rounded_rectangle((335,y+2,920,y+25),radius=6,fill=(43,56,78))
        bar=int(585*stats["games"]/max_games)
        if bar:
            draw.rounded_rectangle((335,y+2,335+bar,y+25),radius=6,fill=(58,166,218))
        draw.text((935,y),str(stats["games"]),font=normal,fill=fg)
    if not rows:
        draw.text((43,433),"No recorded teammate impacts yet",font=normal,fill=subdued)
    draw.text((42,672),"Affected = recorded on the same team; not proof of causing a loss",font=normal,fill=subdued)
    output=BytesIO()
    img.save(output,format="PNG")
    output.seek(0)
    return output
