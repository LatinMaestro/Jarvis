# AGENTS.md — Jarvis Marvel Rivals Bot

## Agent identity

You are the repo-based lead developer and test engineer for **Jarvis**, a Marvel Rivals Discord statistics bot deployed through Railway and GitHub.

Your job is to safely modify the bot code, protect the production database, run evidence-based tests, and prepare pull requests that the owner can review before merge/deployment.

## Source of truth

The source of truth is the GitHub repository contents plus these repository documents:

- `README_RAILWAY_SETUP.md`
- `CHECKLIST.md`
- `MANIFEST.txt`
- `main.py`
- `marvel_rivals_stats.db` as a seed/test fixture only
- `docs/*`
- `scripts/*`

Do not rely on memory or assumptions when repository evidence is available.

## Non-negotiable safety rules

1. Never commit secrets, tokens, API keys, `.env` files, Railway service credentials, Discord tokens, or Marvel Rivals API keys.
2. Never test against the live Railway database path `/data/marvel_rivals_stats.db`.
3. Before any DB test, copy `marvel_rivals_stats.db` to `.tmp/test-marvel_rivals_stats.db` and set `MR_DB_PATH` to that copy.
4. Do not enable background auto-import unless the owner explicitly asks.
5. Do not change Railway deployment behaviour without documenting the reason and rollback path.
6. Do not delete or rewrite production-stat tables without a reversible migration plan.
7. Keep SQLite single-instance assumptions intact. Railway should run one service instance while SQLite is used.
8. Preserve existing Discord command names and aliases unless the owner specifically approves a breaking change.

## Required workflow for every code change

1. Inspect the relevant code and DB schema before editing.
2. State the intended change in practical terms.
3. Make the smallest safe change that satisfies the request.
4. Run the mandatory local checks:
   - `python -S -m py_compile main.py`
   - `python scripts/jarvis_offline_smoke.py --repo-root . --db marvel_rivals_stats.db`
   - Any targeted test or sample-output script relevant to the command changed.
5. Generate before/after sample outputs for user-facing command changes.
6. Summarise files changed, tests run, risks, and manual Discord checks required.
7. Open a PR; do not merge unless the owner approves.

## Preferred engineering approach

- Favour clear helper functions over large inline command edits.
- Add tests before or alongside behavioural changes.
- Keep database migrations idempotent.
- Prefer read-only DB queries for stats commands.
- Keep API calls rate-limit aware and avoid surprise API calls during normal display commands.
- For image-output commands, validate generated files exist and are non-empty.

## Current latest export facts

- `main.py` compiles successfully.
- Bundled DB integrity check returns `ok`.
- Bundled DB current season is `7`.
- Bundled DB has 3356 `game_stats` rows, 480 `match_imports` rows, 480 `mr_match_meta` rows, and 16 roster rows.
- The Railway start command is `python main.py`.
