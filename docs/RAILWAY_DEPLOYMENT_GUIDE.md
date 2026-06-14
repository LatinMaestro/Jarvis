# Railway Deployment Guide

## Current Railway deployment model

The latest export uses Railway with:

```toml
[build]
builder = "RAILPACK"

[deploy]
startCommand = "python main.py"
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
```

## Required Railway variables

Use the variables listed in `env.example` and `README_RAILWAY_SETUP.md`.

Required secrets:

```env
DISCORD_BOT_TOKEN=...
MR_API_KEY=...
```

Persistent SQLite volume:

```env
MR_DB_PATH=/data/marvel_rivals_stats.db
MR_DB_SEED_PATH=marvel_rivals_stats.db
```

Recommended safe defaults:

```env
AUTO_IMPORT_REFRESH_ROSTER_DEFAULT=false
HERO_NAME_API_FALLBACK_ENABLED=false
ENABLE_COMMAND_HERO_CACHE_REFRESH=false
ENABLE_WEB_MONITOR=false
ENABLE_KEEP_ALIVE=false
```

## Volume rule

Attach one Railway volume to the bot service and mount it at `/data`. Keep the service scaled to one running instance while SQLite is used.

## Deployment review steps

Before merging a PR that will deploy to Railway:

1. Check `python -S -m py_compile main.py` passed.
2. Check offline DB smoke tests passed.
3. Check no secret files were added.
4. Check Railway variables did not need changes, or document exact changes.
5. Check rollback is simple: revert merge commit and redeploy previous commit.

## Post-deployment smoke commands

Run in Discord after deployment:

```text
!season
!season_windows
!auto_import_status
!roster_list
!hero_roles_check
!helpme
```

For import-related changes, test after a gaming session with:

```text
!auto_import_run
```
