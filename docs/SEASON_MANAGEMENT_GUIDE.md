# Season Management Guide

## Current bundled DB season state

The latest uploaded GitHub export contains:

- `bot_settings.current_season = 7`
- `mr_season_windows` rows:

| Season | Start Brisbane | End Brisbane | Note |
| --- | --- | --- | --- |
| 4 | 13 Sep 2025 00:00:00 AEST | 14 Nov 2025 23:59:59 AEST |  |
| 5 | 15 Nov 2025 00:00:00 AEST | 16 Jan 2026 23:59:59 AEST |  |
| 6 | 17 Jan 2026 00:00:00 AEST | 20 Mar 2026 23:59:59 AEST |  |
| 7 | 21 Mar 2026 00:00:00 AEST | 22 May 2026 23:59:59 AEST |  |


Internal overlap check: no internal overlap detected.

## Important note

The bundled seed DB currently contains windows through Season 7 only. It does not contain a Season 8 or Season 8.5 row in `mr_season_windows`.

If the live Railway DB has already been updated beyond this seed DB, Codex must verify the live state through an approved Railway backup/export workflow before making season-routing changes. Do not assume the repo seed DB and Railway live DB are identical.

## Commands available in bot

The latest `main.py` includes season-related commands:

- `!season`
- `!set_season`
- `!list_seasons`
- `!reset_season`
- `!season_window_set`
- `!season_windows`

## Rules for changing seasons

- Prefer command-based season updates in Discord for live operations unless a controlled DB migration is approved.
- For repo seed updates, use SQL scripts that are clear and idempotent.
- Do not silently overlap season windows.
- Document timezone assumptions. The bot uses Brisbane/AEST boundaries for season window helper functions.

## Template for future Season 8 / 8.5 setup

Use `scripts/apply_season_windows_template.sql` as a reviewed starting point only. Confirm the exact official dates before applying to live data.
