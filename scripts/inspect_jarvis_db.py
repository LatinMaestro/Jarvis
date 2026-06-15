#!/usr/bin/env python3
"""Inspect Jarvis code and an offline copy of a SQLite snapshot."""
import argparse
import pathlib
from datetime import datetime
from zoneinfo import ZoneInfo

from offline_test_utils import connect_read_only, detect_bot_commands, prepare_db_fixture

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
    root = pathlib.Path(args.repo_root).resolve()
    source, db = prepare_db_fixture(root, args.db, "inspect")
    main_py = root / "main.py"
    print(f"Repository root: {root.resolve()}")
    print(f"Snapshot source: {source}")
    print(f"Offline fixture: {db}")
    print("Data note: snapshot/regression data only; not current Railway production stats.")
    if main_py.exists():
        text = main_py.read_text(encoding="utf-8", errors="replace")
        commands = detect_bot_commands(main_py)
        print(f"main.py lines: {text.count(chr(10)) + 1}")
        print(f"Detected bot commands: {len(commands)}")
        for command in commands:
            aliases = ", ".join(f"!{alias}" for alias in command["aliases"])
            suffix = f" (aliases: {aliases})" if aliases else ""
            print(f"  !{command['name']} -> {command['function']}{suffix}")
    con = connect_read_only(db)
    cur = con.cursor()
    print(f"Integrity: {cur.execute('PRAGMA integrity_check').fetchone()[0]}")
    objects = cur.execute(
        "select name,type from sqlite_master "
        "where type in ('table','view') order by type,name"
    ).fetchall()
    for name, typ in objects:
        if typ == "table" and name != "sqlite_sequence":
            quoted_name = name.replace('"', '""')
            sql = f'SELECT COUNT(*) FROM "{quoted_name}"'
            count = cur.execute(sql).fetchone()[0]
            print(f"{name}: {count}")
        elif typ == "view":
            print(f"{name}: view")
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
