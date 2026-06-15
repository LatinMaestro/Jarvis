# Repository Audit - Historical Snapshot

This audit describes the GitHub-bundled regression snapshot. It is not an audit of the current Railway persistent volume and is not proof of current live statistics.

## Snapshot package

- `main.py`: 827,206 bytes / 23,771 lines.
- `marvel_rivals_stats.db`: 22,450,176 bytes.
- detected bot commands: 57.
- Railway start command: `python main.py`.

## Historical validation

- `python -S -m py_compile main.py`: passed.
- SQLite `PRAGMA integrity_check`: `ok`.
- snapshot current season: `7`.
- season windows: 4 rows with no internal overlap.

## Selected snapshot counts

| Table | Rows |
| --- | --- |
| game_stats | 3356 |
| match_imports | 480 |
| mr_match_meta | 480 |
| mr_player_match | 5760 |
| mr_hero_segments | 13444 |
| mr_roster | 16 |
| hero_cache | 51 |

Regenerate current regression evidence with:

```bash
python scripts/inspect_jarvis_db.py
python scripts/generate_db_sample_outputs.py
```
