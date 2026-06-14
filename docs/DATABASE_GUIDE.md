# Database Guide

## Purpose

This guide explains how Codex must work with the Jarvis SQLite database.

## Production vs test database

The Railway live bot should use:

```env
MR_DB_PATH=/data/marvel_rivals_stats.db
MR_DB_SEED_PATH=marvel_rivals_stats.db
```

The repo-bundled `marvel_rivals_stats.db` is a seed and test fixture. Codex must copy it before tests:

```bash
mkdir -p .tmp
cp marvel_rivals_stats.db .tmp/test-marvel_rivals_stats.db
MR_DB_PATH=.tmp/test-marvel_rivals_stats.db python scripts/generate_db_sample_outputs.py --db .tmp/test-marvel_rivals_stats.db
```

## Latest bundled DB summary

- Integrity check: `ok`
- Current season: `7`
- Tables/views detected: 26
- `game_stats` rows: 3356
- `match_imports` rows: 480
- `mr_match_meta` rows: 480
- `mr_roster` rows: 16

## Migration rules

- Migrations must be idempotent.
- Use `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE` guarded by `PRAGMA table_info`, and `INSERT OR IGNORE` where appropriate.
- Any destructive operation must be reversible or explicitly approved.
- Do not alter primary keys lightly; many stat commands depend on `season_id`, `game_label`, player names and match UIDs.
- After migration changes, run the smoke script and a database integrity check.

## Key schemas from latest export

### `game_stats`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | season_id | INTEGER | 1 | — | 1 |
| 1 | game_label | TEXT | 1 | — | 2 |
| 2 | player | TEXT | 1 | — | 3 |
| 3 | kills | INTEGER | 0 | — | 0 |
| 4 | deaths | INTEGER | 0 | — | 0 |
| 5 | assists | INTEGER | 0 | — | 0 |
| 6 | damage | INTEGER | 0 | — | 0 |
| 7 | damage_taken | INTEGER | 0 | — | 0 |
| 8 | healing | INTEGER | 0 | — | 0 |
| 9 | win | INTEGER | 0 | — | 0 |
| 10 | loss | INTEGER | 0 | — | 0 |
| 11 | mvp | INTEGER | 0 | — | 0 |
| 12 | svp | INTEGER | 0 | — | 0 |
| 13 | timestamp | DATETIME | 0 | CURRENT_TIMESTAMP | 0 |

### `streaks`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | season_id | INTEGER | 1 | — | 1 |
| 1 | player | TEXT | 1 | — | 2 |
| 2 | current_streak | INTEGER | 0 | — | 0 |
| 3 | longest_win_streak | INTEGER | 0 | — | 0 |

### `mr_match_meta`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | season_id | INTEGER | 1 | — | 1 |
| 1 | match_uid | TEXT | 1 | — | 2 |
| 2 | game_label | TEXT | 1 | — | 0 |
| 3 | game_mode_id | INTEGER | 0 | — | 0 |
| 4 | game_mode_name | TEXT | 0 | — | 0 |
| 5 | replay_id | TEXT | 0 | — | 0 |
| 6 | mvp_uid | INTEGER | 0 | — | 0 |
| 7 | mvp_hero_id | INTEGER | 0 | — | 0 |
| 8 | svp_uid | INTEGER | 0 | — | 0 |
| 9 | svp_hero_id | INTEGER | 0 | — | 0 |
| 10 | imported_at | DATETIME | 0 | CURRENT_TIMESTAMP | 0 |
| 11 | match_time_utc | TEXT | 0 | — | 0 |

### `match_imports`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | season_id | INTEGER | 1 | — | 1 |
| 1 | match_uid | TEXT | 1 | — | 2 |
| 2 | game_label | TEXT | 1 | — | 0 |
| 3 | imported_at | DATETIME | 0 | CURRENT_TIMESTAMP | 0 |

### `mr_roster`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | player_uid | INTEGER | 0 | — | 1 |
| 1 | player_name | TEXT | 0 | — | 0 |
| 2 | enabled | INTEGER | 0 | 1 | 0 |
| 3 | created_at | TEXT | 0 | datetime('now') | 0 |

### `mr_season_windows`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | season_id | INTEGER | 0 | — | 1 |
| 1 | start_utc | TEXT | 1 | — | 0 |
| 2 | end_utc | TEXT | 0 | — | 0 |
| 3 | note | TEXT | 0 | — | 0 |

### `mr_player_match`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | season_id | INTEGER | 1 | — | 1 |
| 1 | match_uid | TEXT | 1 | — | 2 |
| 2 | game_label | TEXT | 1 | — | 0 |
| 3 | player_uid | INTEGER | 1 | — | 3 |
| 4 | player | TEXT | 1 | — | 0 |
| 5 | is_bot | INTEGER | 1 | 0 | 0 |
| 6 | player_icon | INTEGER | 0 | — | 0 |
| 7 | camp | INTEGER | 0 | — | 0 |
| 8 | cur_hero_id | INTEGER | 0 | — | 0 |
| 9 | cur_hero_icon | TEXT | 0 | — | 0 |
| 10 | is_win | INTEGER | 0 | — | 0 |
| 11 | kills | INTEGER | 0 | — | 0 |
| 12 | deaths | INTEGER | 0 | — | 0 |
| 13 | assists | INTEGER | 0 | — | 0 |
| 14 | total_hero_damage | REAL | 0 | — | 0 |
| 15 | total_hero_heal | REAL | 0 | — | 0 |
| 16 | total_damage_taken | REAL | 0 | — | 0 |
| 17 | system | TEXT | 0 | — | 0 |
| 18 | dynamic_name | TEXT | 0 | — | 0 |
| 19 | dynamic_json | TEXT | 0 | — | 0 |
| 20 | final_hits | INTEGER | 0 | — | 0 |
| 21 | solo_kill | INTEGER | 0 | — | 0 |

### `mr_hero_segments`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | season_id | INTEGER | 1 | — | 1 |
| 1 | match_uid | TEXT | 1 | — | 2 |
| 2 | game_label | TEXT | 1 | — | 0 |
| 3 | player_uid | INTEGER | 1 | — | 3 |
| 4 | player | TEXT | 1 | — | 0 |
| 5 | is_bot | INTEGER | 1 | 0 | 0 |
| 6 | hero_id | INTEGER | 1 | — | 4 |
| 7 | hero_icon | TEXT | 0 | — | 0 |
| 8 | seconds | REAL | 0 | — | 0 |
| 9 | kills | INTEGER | 0 | — | 0 |
| 10 | deaths | INTEGER | 0 | — | 0 |
| 11 | assists | INTEGER | 0 | — | 0 |
| 12 | session_hit_rate | REAL | 0 | — | 0 |
| 13 | hero_damage | REAL | 0 | — | 0 |
| 14 | hero_heal | REAL | 0 | — | 0 |
| 15 | hero_damage_taken | REAL | 0 | — | 0 |
| 16 | final_hits | INTEGER | 0 | — | 0 |
| 17 | solo_kills | INTEGER | 0 | — | 0 |

### `hero_cache`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | hero_id | TEXT | 0 | — | 1 |
| 1 | hero_name | TEXT | 0 | — | 0 |
| 2 | updated_at | TEXT | 0 | — | 0 |
| 3 | hero_role | TEXT | 0 | — | 0 |

### `session_state`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | guild_id | INTEGER | 1 | — | 1 |
| 1 | channel_id | INTEGER | 1 | — | 2 |
| 2 | state_json | TEXT | 1 | — | 0 |
| 3 | updated_at | DATETIME | 0 | CURRENT_TIMESTAMP | 0 |

### `mr_bot_settings`

| CID | Name | Type | Not null | Default | PK |
| --- | --- | --- | --- | --- | --- |
| 0 | k | TEXT | 0 | — | 1 |
| 1 | v | TEXT | 0 | — | 0 |
