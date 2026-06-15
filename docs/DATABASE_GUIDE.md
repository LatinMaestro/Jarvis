# Database Guide

## Ownership

- The Railway persistent volume database is the source of truth for current live statistics.
- The GitHub-bundled `marvel_rivals_stats.db` is a historical snapshot for offline regression testing.
- Codex must not directly read, write, overwrite, migrate, reset, or modify the live Railway production database.
- Snapshot results must not be presented as current live statistics.

## Normal development: Option A

Use the GitHub snapshot for:

- compile and startup-adjacent checks;
- schema and query checks;
- offline smoke tests;
- deterministic sample-output regression evidence.

The scripts copy any database input into `.tmp` and open the copy read-only.

```bash
python scripts/inspect_jarvis_db.py
python scripts/jarvis_offline_smoke.py
python scripts/generate_db_sample_outputs.py
```

Never pass `/data/marvel_rivals_stats.db` to repository scripts.

## Current-stat validation

When specifically required, use:

- an owner-approved copied Railway database export; or
- a staging Railway service.

Treat exports as sensitive production data, keep them outside Git, and test against another disposable copy.

## Snapshot facts

The bundled historical snapshot currently reports:

- integrity check: `ok`;
- snapshot current season: `7`;
- `game_stats`: 3356 rows;
- `match_imports`: 480 rows;
- `mr_match_meta`: 480 rows;
- `mr_roster`: 16 rows.

These facts describe only the committed snapshot.

## Migration rules

- Test migrations only against disposable copies.
- Keep migrations idempotent and reversible.
- Guard schema changes with schema inspection.
- Preserve primary-key and season-routing contracts.
- Run integrity, quick, and foreign-key checks afterward.
- Production migration execution is owner-controlled and outside normal Codex testing.

## Important tables

- `bot_settings` - snapshot season settings.
- `game_stats` and `streaks` - season-aware statistics.
- `mr_season_windows` - season routing windows.
- `match_imports` and `mr_match_meta` - import deduplication and metadata.
- `mr_player_match` and `mr_hero_segments` - player and hero match detail.
- `mr_roster` - enabled and disabled roster entries.
- `hero_cache` - hero names and roles.
- `session_state` - persisted fairness-session state.
