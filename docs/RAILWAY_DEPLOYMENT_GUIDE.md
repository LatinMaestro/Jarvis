# Railway Deployment Guide

## Ownership model

- GitHub is the source of truth for deployed code.
- Railway is the live runtime environment.
- The Railway persistent volume database is the source of truth for current live statistics.
- The GitHub database is only a historical snapshot and first-deploy seed.

## Current deployment configuration

```toml
[build]
builder = "RAILPACK"

[deploy]
startCommand = "python main.py"
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
```

The volume is mounted at `/data`, and the live database path is:

```env
MR_DB_PATH=/data/marvel_rivals_stats.db
MR_DB_SEED_PATH=marvel_rivals_stats.db
```

Keep one Railway service instance while SQLite is used.

## Codex boundary

Codex must not directly read, write, overwrite, migrate, reset, download, or modify the live production database. Codex must not connect to live Discord.

Normal development uses copied GitHub snapshot fixtures. If current-stat validation is required, the owner may provide a copied Railway export or authorize a staging Railway service. Neither path permits tests against the live production database.

## Deployment review

Before merging a deployable code PR:

1. Confirm compile and offline snapshot checks passed.
2. Confirm no secrets or production data were committed.
3. Confirm Railway configuration changes are absent or explicitly documented.
4. Confirm any database change was tested against disposable copies.
5. Document rollback steps and owner-operated post-deployment checks.
