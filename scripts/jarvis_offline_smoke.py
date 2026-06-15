#!/usr/bin/env python3
"""Offline smoke checks for Jarvis. Never connects to Railway, Discord, or the API."""
import argparse
import pathlib
import py_compile
from datetime import datetime

from offline_test_utils import connect_read_only, prepare_db_fixture

REQUIRED_FILES = ["main.py", "requirements.txt", "railway.toml", ".env.example", "marvel_rivals_stats.db"]
REQUIRED_TABLES = ["bot_settings", "game_stats", "streaks", "mr_roster", "mr_season_windows", "mr_match_meta", "match_imports", "hero_cache"]

def fail(msg):
    print(f"FAIL: {msg}")
    return 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--db", default="marvel_rivals_stats.db")
    args = ap.parse_args()
    root = pathlib.Path(args.repo_root).resolve()
    for rel in REQUIRED_FILES:
        if not (root / rel).exists():
            return fail(f"missing required file: {rel}")
    try:
        py_compile.compile(str(root / "main.py"), doraise=True)
        print("PASS: main.py compiles")
    except Exception as exc:
        return fail(f"main.py compile failed: {exc}")
    try:
        source, db = prepare_db_fixture(root, args.db, "smoke")
    except Exception as exc:
        return fail(str(exc))
    print(f"PASS: copied offline DB fixture from {source.name} to {db.relative_to(root)}")

    con = connect_read_only(db)
    cur = con.cursor()
    integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        return fail(f"SQLite integrity check returned {integrity}")
    print("PASS: SQLite integrity_check ok")
    quick = cur.execute("PRAGMA quick_check").fetchone()[0]
    if quick != "ok":
        return fail(f"SQLite quick_check returned {quick}")
    print("PASS: SQLite quick_check ok")
    foreign_key_violations = cur.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_violations:
        return fail(f"SQLite foreign_key_check returned {len(foreign_key_violations)} rows")
    print("PASS: SQLite foreign_key_check clean")
    existing = {r[0] for r in cur.execute("select name from sqlite_master where type='table'")}
    missing = [t for t in REQUIRED_TABLES if t not in existing]
    if missing:
        return fail(f"missing required tables: {', '.join(missing)}")
    print("PASS: required tables present")
    current = cur.execute("select value from bot_settings where key='current_season'").fetchone()
    if not current:
        return fail("bot_settings.current_season missing")
    print(f"PASS: current_season={current[0]}")
    rows = cur.execute("select season_id,start_utc,end_utc from mr_season_windows order by season_id").fetchall()
    prev_end = None
    for sid, su, eu in rows:
        start = datetime.fromisoformat(str(su).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(eu).replace("Z", "+00:00")) if eu else None
        if end and end < start:
            return fail(f"season {sid} ends before it starts")
        if prev_end and start <= prev_end:
            return fail(f"season {sid} overlaps previous window")
        if end:
            prev_end = end
    print(f"PASS: season windows valid ({len(rows)} rows)")
    print(f"PASS: game_stats rows={cur.execute('select count(*) from game_stats').fetchone()[0]}")
    con.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
