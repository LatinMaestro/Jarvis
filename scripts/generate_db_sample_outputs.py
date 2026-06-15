#!/usr/bin/env python3
# Generate regression Markdown from a copied Jarvis SQLite snapshot.
import argparse
import pathlib
from datetime import datetime
from zoneinfo import ZoneInfo

from offline_test_utils import connect_read_only, detect_bot_commands, prepare_db_fixture

BRIS = ZoneInfo("Australia/Brisbane")

def bris(iso):
    if not iso:
        return "OPEN"
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(BRIS).strftime("%d %b %Y %H:%M:%S AEST")

def table(headers, rows):
    if not rows:
        return "_No rows._\n"
    out = "| " + " | ".join(headers) + " |\n| " + " | ".join(["---"] * len(headers)) + " |\n"
    for row in rows:
        out += "| " + " | ".join(str(x) if x is not None else "—" for x in row) + " |\n"
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--db", default="marvel_rivals_stats.db")
    ap.add_argument("--out", default=".tmp/sample_outputs.md")
    args = ap.parse_args()
    root = pathlib.Path(args.repo_root).resolve()
    source, db = prepare_db_fixture(root, args.db, "samples")
    out = pathlib.Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    con = connect_read_only(db)
    cur = con.cursor()
    integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
    current = int(cur.execute("select cast(value as int) from bot_settings where key='current_season'").fetchone()[0])
    counts = []
    names = [r[0] for r in cur.execute("select name from sqlite_master where type='table' and name <> 'sqlite_sequence' order by name").fetchall()]
    for name in names:
        counts.append((name, cur.execute(f'select count(*) from "{name}"').fetchone()[0]))
    windows = [(sid, bris(su), bris(eu), note or "") for sid, su, eu, note in cur.execute("select season_id,start_utc,end_utc,note from mr_season_windows order by season_id")]
    leaders = cur.execute('''
        select player, count(distinct game_label) games, sum(win) wins, sum(loss) losses,
               round(100.0*sum(win)/nullif(sum(win)+sum(loss),0),1) wr,
               sum(kills) kills, sum(deaths) deaths, sum(assists) assists,
               round(1.0*sum(kills)/nullif(sum(deaths),0),2) kd
        from game_stats where season_id=? group by player order by wins desc, wr desc, games desc limit 12
    ''', (current,)).fetchall()
    roster = cur.execute("select player_uid,player_name,enabled from mr_roster order by enabled desc, player_name collate nocase").fetchall()
    hero_roles = cur.execute("select coalesce(hero_role,'UNKNOWN') role,count(*) from hero_cache group by coalesce(hero_role,'UNKNOWN') order by role").fetchall()
    con.close()
    commands = detect_bot_commands(root / "main.py")
    command_rows = [
        (
            f"!{item['name']}",
            ", ".join(f"!{alias}" for alias in item["aliases"]),
            item["function"],
        )
        for item in commands
    ]
    md = []
    md.append("# Jarvis snapshot regression outputs\n\n")
    md.append(
        "Generated offline from the GitHub-bundled `marvel_rivals_stats.db` snapshot. "
        "These outputs are regression evidence only and are not proof of current live Railway statistics.\n\n"
    )
    md.append(f"Snapshot source: `{source.name}`\n\n")
    md.append(f"Integrity check: `{integrity}`\n\n")
    md.append(f"Snapshot current season: `{current}`\n\n")
    md.append("## Tables\n\n" + table(["Table", "Rows"], counts) + "\n")
    md.append("## Season windows\n\n" + table(["Season", "Start Brisbane", "End Brisbane", "Note"], windows) + "\n")
    md.append("## Leaderboard sample\n\n" + table(["Player", "Games", "Wins", "Losses", "WR %", "Kills", "Deaths", "Assists", "K/D"], leaders) + "\n")
    md.append("## Roster sample\n\n" + table(["UID", "Player", "Enabled"], roster) + "\n")
    md.append("## Hero role summary\n\n" + table(["Role", "Heroes"], hero_roles) + "\n")
    md.append("## Commands detected in `main.py`\n\n" + table(["Command", "Aliases", "Function"], command_rows) + "\n")
    out.write_text("".join(md), encoding="utf-8")
    print(f"Wrote {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
