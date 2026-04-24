# Marvel Rivals Discord Bot — Railway Deployment Pack

This folder is the clean Railway deployment pack prepared from the Replit export.

## Included files

- `main.py` — current working bot code from the Replit export.
- `marvel_rivals_stats.db` — checkpointed SQLite database seed.
- `requirements.txt` — Python packages needed by the bot.
- `runtime.txt` and `.python-version` — Python 3.11 selection.
- `railway.toml` — Railway start command and restart policy.
- `.env.example` — variables to add in Railway.
- `.gitignore` — excludes Replit/system/runtime files.

## Not included

The following Replit export items were deliberately excluded:

- `.git/`, `.local/`, `.agents/`, cache folders, Replit logs.
- `.replit`, because Railway does not use it.
- `keep_alive.py`, `web_monitor.py`, templates/static web monitor files, because the Discord bot does not need a web keep-alive on Railway.
- database sidecars (`.db-wal` and `.db-shm`), because the database has been checkpointed into a clean single `.db` file.
- old/duplicate files such as `new_command.py`, `dump.sql`, and nested old zip files.

## Railway variables

Set these in the Railway service Variables tab:

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

## Railway volume

Attach a Railway volume to the bot service and mount it at:

```text
/data
```

On first start, the bot will copy the bundled `marvel_rivals_stats.db` into `/data/marvel_rivals_stats.db` if the volume does not already contain the database. After that, Railway will persist the live SQLite database on the volume.

## Start command

`railway.toml` sets:

```bash
python main.py
```

## First commands to test in Discord

After Railway shows the deployment as running, test:

```text
!season
!auto_import_status
!roster_list
!hero_roles_check
!helpme
```

Then test the import flow after a gaming session:

```text
!auto_import_run
```

The bot now automatically runs `!run_all_stats` after a successful `!auto_import_run`.

## Important operating notes

- Do not enable Railway serverless mode for this bot. Discord bots need a continuously running process.
- Keep the service scaled to one instance while using SQLite. Multiple instances writing to the same SQLite file can corrupt data.
- Leave background auto-import off. The intended workflow is to run `!auto_import_run` manually after a session.
- Use `!auto_import_run refresh` only when you specifically want to queue API-side roster refreshes first.
- If you suspect missed games during early testing, run `!auto_import_run days=7`. Use `reset_cursor` only for recovery/testing.
