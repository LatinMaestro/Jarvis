# Known Risks and Technical Debt

## Large monolithic `main.py`

`main.py` is currently 23,771 lines. This increases regression risk. Codex should avoid broad refactors unless specifically requested.

## SQLite production database

SQLite is acceptable for a small Discord bot, but Railway must run a single instance with a persistent volume. Multiple writers can corrupt data.

## Seed DB vs live DB drift

The repo seed DB may not always match the live Railway volume. Before season routing, import logic, or data cleanup changes, Codex should confirm which database is being used for the task.

## Season 8 / 8.5 not in bundled seed DB

The latest bundled seed DB has season windows through Season 7 only. If Season 8/8.5 is already configured live, the seed DB is behind. If not configured live, it needs an approved setup action.

## API rate limits

Import and refresh commands use the Marvel Rivals API and may hit rate limits. Normal display/stat tests should avoid live API calls.

## Image rendering

Image commands depend on fonts and Pillow. Keep robust font fallbacks and test generated files.

## Disabled roster players

The roster table includes disabled players. Codex must respect `enabled` filtering when a command is intended to use the active roster only.
