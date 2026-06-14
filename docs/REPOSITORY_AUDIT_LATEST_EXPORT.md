# Repository Audit — Latest Uploaded Export

## Files detected

| File | Size bytes |
| --- | --- |
| CHECKLIST.md | 678 |
| Downloads - Shortcut.lnk | 714 |
| MANIFEST.txt | 770 |
| README_RAILWAY_SETUP.md | 2989 |
| env.example | 506 |
| gitignore.txt | 305 |
| main.py | 827206 |
| marvel_rivals_stats.db | 22450176 |
| python-version.txt | 5 |
| railway.toml | 133 |
| requirements.txt | 92 |
| runtime.txt | 12 |


## Validation

- `python -S -m py_compile main.py`: passed
- SQLite `PRAGMA integrity_check`: `ok`
- Railway start command: `python main.py`
- Requirements detected: `aiohttp>=3.12.15,<4; discord.py>=2.5.2,<3; pandas>=2.3.1,<3; pillow>=11.3.0,<12; tzdata>=2025.2`

## Database counts

| Table | Rows |
| --- | --- |
| bot_settings | 1 |
| game_stats | 3356 |
| hero_bans | 2743 |
| hero_cache | 51 |
| hero_time_stats | 6683 |
| hero_time_stats_all | 13444 |
| match_imports | 480 |
| mr_auto_import_scan_state | 19 |
| mr_ban_picks | 2764 |
| mr_bot_settings | 6 |
| mr_hero_segments | 13444 |
| mr_match_json_humans | 480 |
| mr_match_json_raw | 480 |
| mr_match_meta | 480 |
| mr_player_badges | 5180 |
| mr_player_match | 5760 |
| mr_players | 1749 |
| mr_roster | 16 |
| mr_season_windows | 4 |
| mr_skipped_matches | 8 |
| seasons | 3 |
| session_state | 2 |
| streaks | 37 |


## Season window validation

| Season | Start Brisbane | End Brisbane | Note |
| --- | --- | --- | --- |
| 4 | 13 Sep 2025 00:00:00 AEST | 14 Nov 2025 23:59:59 AEST |  |
| 5 | 15 Nov 2025 00:00:00 AEST | 16 Jan 2026 23:59:59 AEST |  |
| 6 | 17 Jan 2026 00:00:00 AEST | 20 Mar 2026 23:59:59 AEST |  |
| 7 | 21 Mar 2026 00:00:00 AEST | 22 May 2026 23:59:59 AEST |  |


Result: No internal overlap detected.
