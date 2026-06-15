# Marvel Rivals Discord Bot - Railway Setup

## Ownership model

- GitHub is the source of truth for deployed bot code.
- Railway is the live runtime environment.
- The Railway persistent volume database is the source of truth for current live statistics.
- `marvel_rivals_stats.db` in GitHub is a historical snapshot, offline regression fixture, and first-deploy seed only.

Codex must not directly access or modify the live Railway production database or connect automated tests to live Discord.

## Deployment files

- `main.py` - bot runtime code.
- `marvel_rivals_stats.db` - historical snapshot and first-deploy seed.
- `requirements.txt` - runtime packages.
- `runtime.txt` and `.python-version` - Python selection.
- `railway.toml` - start command and restart policy.
- `.env.example` - variable names without secrets.

## Railway variables

```env
DISCORD_BOT_TOKEN=your_discord_bot_token
MR_API_KEY=your_marvel_rivals_api_key
MR_DB_PATH=/data/marvel_rivals_stats.db
MR_DB_SEED_PATH=marvel_rivals_stats.db
AUTO_IMPORT_MAX_HISTORY_PAGES=2
AUTO_IMPORT_MAX_LOOKBACK_DAYS=4
AUTO_IMPORT_FIRST_RUN_LOOKBACK_DAYS=7
AUTO_IMPORT_REFRESH_ROSTER_DEFAULT=false
HERO_NAME_API_FALLBACK_ENABLED=false
ENABLE_COMMAND_HERO_CACHE_REFRESH=false
ENABLE_WEB_MONITOR=false
ENABLE_KEEP_ALIVE=false
```

Never commit real values.

## Persistent volume

Mount one Railway volume at `/data` and keep the service at one running instance while SQLite is used.

On first start, the bot may seed an empty volume from the GitHub snapshot. After that, `/data/marvel_rivals_stats.db` is independent production data and must not be treated as a mirror of the GitHub file.

## Start command

```bash
python main.py
```

## Development validation

Repository CI and Codex use temporary copies of the GitHub snapshot. Snapshot regression output is not proof of current live statistics.

If current-stat validation is required, use an owner-approved copied Railway export or staging service. Never test against the live production database.

Any post-deployment Discord checks are owner-operated.
