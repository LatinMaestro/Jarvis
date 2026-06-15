# Security and Secrets

## Never commit

- Discord bot tokens;
- Marvel Rivals API keys;
- Railway credentials;
- real `.env` files;
- production database exports;
- generated test databases.

The repository includes `.env.example` with blank secret values.

## Production boundaries

Codex must not directly access or modify the live Railway database and must not connect automated tests to live Discord.

The GitHub database is a historical snapshot. Tests use temporary copies and must not present snapshot data as current production statistics.

An owner-approved copied Railway export is sensitive production data. Keep it outside Git, copy it again for testing, and remove it according to the owner's handling instructions.

## API safety

Normal regression tests make no live Marvel Rivals API calls. Prefer stored JSON fixtures and keep cache refresh behavior opt-in.
