# Season Management Guide

## Snapshot meaning

The GitHub snapshot contains historical season data through Season 7. This does not establish the current live Railway season.

Codex must not query or modify the live Railway database to compare season state. Current-state validation requires an owner-approved copied Railway export or staging service.

## Snapshot commands in `main.py`

- `!season`
- `!set_season`
- `!list_seasons`
- `!reset_season`
- `!season_window_set`
- `!season_windows`

## Development rules

- Treat snapshot season rows as regression fixtures.
- Test season logic only against disposable copied databases.
- Do not change season windows without explicit scope and verified dates.
- Document Brisbane/AEST boundary assumptions.
- Keep changes idempotent and reversible.

Live season operations are owner-controlled and outside automated Codex testing.
