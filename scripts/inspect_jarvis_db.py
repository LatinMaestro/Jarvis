#!/usr/bin/env python3
"""Inspect the Jarvis SQLite database and repository command surface."""
import argparse
import pathlib
import re
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

BRIS = ZoneInfo("Australia/Brisbane")

def bris(iso):
    if not iso:
        return "OPEN"
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(BRIS).strftime("%Y-%m-%d %H:%M:%S AEST")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--db", default="marvel_rivals_stats.db")
    args = ap.parse_args()
    root = pathlib.Path(args.repo_root)
    db = pathlib.Path(args.db)
    if not db.is_absolute():
        db = root / db
    main_py = root / "main.py"
    print(f"Repository root: {root.resolve()}")
    print(f"Database: {db.resolve()}")
    if main_py.exists():
        text = main_py.read_text(encoding="utf-8", errors="replace")
        commands = re.findall(r"@bot\.command\((.*?)\)\s*\nasync def ([\w_]+)", text, re.S)
        print(f"main.py lines: {text.count(chr(10)) + 1}")
        print(f"Detected bot commands: {len(commands)}")
        for raw, fn in commands:
            m = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", raw)
            name = m.group(1) if m else fn
            print(f"  !{name} -> {fn}")
    con = sqlite3.connect(db)
    cur = con.cursor()
    print(f"Integrity: {cur.execute('PRAGMA integrity_check').fetchone()[0]}")
    for name, typ in cur.execute("select name,type from sqlite_master where type in ('table','view') order by type,name"):
        if typ == "table" and name != "sqlite_sequence":
            print(f"{name}: {cur.execute(f'select count(*) from \"{name}\"').fetchone()[0]}")
    print("bot_settings:")
    for row in cur.execute("select key,value from bot_settings order by key"):
        print(f"  {row[0]} = {row[1]}")
    print("season_windows:")
    for sid, su, eu, note in cur.execute("select season_id,start_utc,end_utc,note from mr_season_windows order by season_id"):
        print(f"  Season {sid}: {bris(su)} -> {bris(eu)} {note or ''}")
    con.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
