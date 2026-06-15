# Known Risks and Technical Debt

## Large monolithic `main.py`

`main.py` is approximately 23,771 lines. Broad changes have a high regression risk. Prefer focused helpers and targeted evidence.

## SQLite production database

Railway must run one service instance while SQLite is used. The persistent volume database is the source of truth for current live statistics.

## Snapshot drift

The GitHub database is expected to drift from Railway production. It is historical regression data, not a production mirror. Codex must not query the live volume to resolve that drift.

Current-stat validation requires an owner-approved copied Railway export or staging service.

## Snapshot season coverage

The bundled snapshot has season windows through Season 7 only. This does not establish the current live season and must not drive production season operations.

## API and Discord access

Import and refresh commands can hit rate limits and mutate state. Normal tests should use stored fixtures, make no live API calls, and never connect to live Discord.

## Image rendering

Image commands depend on Pillow and available fonts. Validate generated files and visual legibility.

## Roster filtering

The snapshot includes disabled players. Tests must verify active-only commands honor the `enabled` flag.
